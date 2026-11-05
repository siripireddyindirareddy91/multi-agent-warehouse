import json, time
from typing import TypedDict
from sqlalchemy import select
from langgraph.graph import StateGraph, END
from .database import *
from .optimization import optimize

AGENTS=['Order Intake','Inventory Intelligence','Order Prioritization','Worker Allocation','Picking Optimization','Fulfillment','Delivery Risk','Replenishment','Supervisor']
ACTIVE=['Received','Validating','Awaiting Inventory','Prioritized','Ready for Picking','Delayed']

def event(db,kind,message,order_id=None,actor='Agent'):
    db.add(Event(kind=kind,message=message,order_id=order_id,actor=actor))

def recommend(db,key,title,description,impact,severity='Medium',product_id=None):
    existing=db.scalar(select(Recommendation).where(Recommendation.key==key))
    if not existing:db.add(Recommendation(key=key,title=title,description=description,impact=impact,severity=severity,product_id=product_id))

def priority(order,customer,ready):
    hours=(order.deadline-now()).total_seconds()/3600
    age=max(0,(now()-order.created).total_seconds()/3600)
    factors={'Delivery urgency':max(0,min(100,100-hours*3)), 'SLA risk':max(0,min(100,100-hours*5)), 'Customer priority':customer.priority, 'Order age':min(100,age*2), 'Shipping priority':100 if order.shipping=='Express' else 30, 'Inventory readiness':100 if ready else 0}
    score=round(sum(v*w for v,w in zip(factors.values(),[.30,.25,.15,.10,.10,.10])),1)
    category='Critical' if score>=80 else 'High' if score>=60 else 'Medium' if score>=35 else 'Low'
    return score,category,', '.join(f'{k}: {round(v,1)}' for k,v in factors.items())

def execute(db,name,strategy='Batch'):
    started=time.perf_counter();output={};status='Success'
    try:
        # Nested transaction allows failed agent changes to roll back while retaining failure log.
        with db.begin_nested():
            orders=db.scalars(select(Order).order_by(Order.score.desc()).with_for_update()).all()
            products={p.id:p for p in db.scalars(select(Product).with_for_update()).all()}
            customers={c.id:c for c in db.scalars(select(Customer)).all()}
            items={o.id:[] for o in orders}
            for item in db.scalars(select(Item)).all():items[item.order_id].append(item)
            pending=[o for o in orders if o.status in ACTIVE]
            if name=='Order Intake':
                count=0
                for o in pending:
                    if o.status!='Received':continue
                    if not items[o.id] or not customers[o.customer_id].address:raise ValueError(f'Order {o.id} missing products or address')
                    o.status='Validating';count+=1;event(db,'Validated','Order details validated',o.id)
                output={'validated':count}
            elif name=='Inventory Intelligence':
                blocked=0
                for o in pending:
                    if o.allocated:continue
                    shortages=[products[i.product_id].sku for i in items[o.id] if products[i.product_id].stock-products[i.product_id].reserved<i.quantity]
                    if shortages:
                        if o.status!='Awaiting Inventory':event(db,'Shortage',f'Allocation blocked: {", ".join(shortages)}',o.id)
                        o.status='Awaiting Inventory';blocked+=1
                    elif o.status in ['Validating','Awaiting Inventory']:o.status='Prioritized'
                output={'checked':len(pending),'blocked':blocked}
            elif name=='Order Prioritization':
                for o in pending:
                    ready=all(products[i.product_id].stock-products[i.product_id].reserved>=i.quantity for i in items[o.id])
                    o.score,o.priority,o.explanation=priority(o,customers[o.customer_id],ready)
                output={'scored':len(pending),'formula':'urgency .30 + SLA .25 + customer .15 + age .10 + shipping .10 + inventory .10'}
            elif name=='Worker Allocation':
                busy={o.worker_id for o in orders if o.status in ['Picking','Picked','Packing','Packed','Ready for Dispatch']}
                workers=db.scalars(select(Worker).where(Worker.available==True).order_by(Worker.completed,Worker.id).with_for_update()).all()
                assigned=0
                for o in sorted(pending,key=lambda o:o.score,reverse=True):
                    if o.status=='Awaiting Inventory' or o.allocated:continue
                    eligible=[w for w in workers if w.id not in busy and 'Picking' in w.skills]
                    if not eligible:break
                    if not all(products[i.product_id].stock-products[i.product_id].reserved>=i.quantity for i in items[o.id]):o.status='Awaiting Inventory';continue
                    w=eligible[0]
                    for i in items[o.id]:products[i.product_id].reserved+=i.quantity
                    o.worker_id=w.id;o.allocated=True;o.status='Ready for Picking';busy.add(w.id);assigned+=1
                    event(db,'Worker assigned',f'{w.name} assigned; stock reserved atomically',o.id)
                output={'assigned':assigned,'available_workers':len(workers)-len(busy)}
            elif name=='Picking Optimization':
                count=0
                for o in orders:
                    if o.status!='Ready for Picking':continue
                    w=db.get(Worker,o.worker_id)
                    result=optimize([(products[i.product_id].x,products[i.product_id].y) for i in items[o.id]],(w.x,w.y),strategy)
                    o.route=json.dumps(result);o.status='Picking';count+=1
                    event(db,'Route generated',f'{result["stops"]} stops; {result["optimized_distance"]}m route; {result["saved"]}m saved',o.id)
                output={'routes_generated':count,'strategy':strategy}
            elif name=='Fulfillment':
                output={'awaiting_picking':sum(o.status=='Picking' for o in orders),'awaiting_verification':sum(o.status in ['Picked','Packing','Packed'] for o in orders),'message':'Physical picking and packing confirmation required; no shipment inferred.'}
            elif name=='Delivery Risk':
                count=0
                for o in orders:
                    if o.status in ['Delivered','Cancelled']:continue
                    hours=(o.deadline-now()).total_seconds()/3600
                    o.risk=round(min(100,max(0,75-hours*4)+(25 if o.status=='Awaiting Inventory' else 0)),1)
                    if o.risk>=70:
                        count+=1;recommend(db,f'risk-{o.id}',f'Expedite WH-{o.id:05}',f'Deadline {o.deadline.isoformat()} UTC. Delivery risk {o.risk}%. Assign supervisor review.','Reduce SLA exposure','High')
                output={'high_risk_orders':count}
            elif name=='Replenishment':
                count=0
                for p in products.values():
                    available=p.stock-p.reserved
                    if available<p.reorder:
                        q=max(0,p.reorder*3-available);count+=1
                        recommend(db,f'restock-{p.id}',f'Replenish {p.sku}',f'{p.name}: {available} available against threshold {p.reorder}. Request {q} units.',f'Restore {q} units of capacity','High' if available==0 else 'Medium',p.id)
                output={'replenishment_requests':count}
            elif name=='Supervisor':
                output={'pending_orders':len(pending),'inventory_exceptions':sum(o.status=='Awaiting Inventory' for o in orders),'picking':sum(o.status=='Picking' for o in orders),'summary':'Workflow evaluated. Shortages require replenishment; physical stages require operator confirmation.'}
            else:raise ValueError('Unknown agent')
    except Exception as exc:
        status='Failed';output={'error':str(exc)}
    db.add(AgentRun(agent=name,status=status,input=json.dumps({'strategy':strategy}),output=json.dumps(output),duration_ms=round((time.perf_counter()-started)*1000,2)))
    db.flush()
    return {'agent':name,'status':status,'output':output}

class State(TypedDict):
    results:list

def workflow(db,strategy='Batch'):
    graph=StateGraph(State)
    sequence=['Order Intake','Inventory Intelligence','Order Prioritization','Worker Allocation','Picking Optimization','Fulfillment','Delivery Risk','Replenishment','Supervisor']
    for name in sequence:
        def node(state,n=name):
            result=execute(db,n,strategy)
            return {'results':state['results']+[result]}
        graph.add_node(name,node)
    graph.set_entry_point(sequence[0])
    for a,b in zip(sequence,sequence[1:]):graph.add_conditional_edges(a,lambda state,n=b: END if state['results'][-1]['status']=='Failed' else n)
    graph.add_edge(sequence[-1],END)
    return graph.compile().invoke({'results':[]})
