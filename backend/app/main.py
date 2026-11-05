import os,json,secrets,csv,io
from contextlib import asynccontextmanager
from datetime import timedelta,datetime
from typing import Literal
import jwt
from pwdlib import PasswordHash
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from .database import *
from .seed import seed
from .agents import AGENTS,execute,workflow,event,priority

DEMO=os.getenv('DEMO_MODE','true').lower()=='true'
SECRET=os.getenv('JWT_SECRET_KEY') or secrets.token_urlsafe(48)
password_hash=PasswordHash.recommended()
READY=False

def initialize():
    global READY
    if READY:return
    Base.metadata.create_all(engine)
    with Session() as db:
        if DEMO:seed(db)
    READY=True

@asynccontextmanager
async def lifespan(app):
    initialize();yield

app=FastAPI(title='Warehouse Intelligence AI',version='1.0.0',lifespan=lifespan,docs_url='/api/docs',openapi_url='/api/openapi.json')
app.add_middleware(CORSMiddleware,allow_origins=[os.getenv('FRONTEND_URL','http://localhost:3000')],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

def database():
    initialize()
    with Session() as db:
        try:yield db;db.commit()
        except:db.rollback();raise

def current(request:Request,db=Depends(database)):
    token=request.headers.get('authorization','').removeprefix('Bearer ')
    try:
        payload=jwt.decode(token,SECRET,algorithms=['HS256'])
        if payload.get('demo') and DEMO:return {'id':0,'name':'Demo Operator','role':'Demo','email':'demo@example.com'}
        user=db.get(User,int(payload['sub']))
        if not user:raise ValueError()
        return serialize(user)
    except Exception:raise HTTPException(401,'Please sign in to continue')

def access(user,roles):
    if user['role'] not in roles+['Admin','Demo']:raise HTTPException(403,'Your role does not allow this operation')

def token_for(user,demo=False):
    return jwt.encode({'sub':str(user['id']),'demo':demo,'exp':now()+timedelta(hours=1)},SECRET,algorithm='HS256')

class Credentials(BaseModel):
    email:str=Field(min_length=5,max_length=250)
    password:str=Field(min_length=8,max_length=128)
    name:str=Field(default='Warehouse user',min_length=2,max_length=120)

@app.get('/api/health')
def health(db=Depends(database)):
    db.execute(select(1))
    return {'status':'ok','demo':DEMO,'persistent':not url.startswith('sqlite') or not os.getenv('VERCEL'),'engine':'PostgreSQL' if 'postgresql' in url else 'SQLite','orchestration':'LangGraph','ai':'Local deterministic agents'}

@app.post('/api/auth/demo')
def demo():
    if not DEMO:raise HTTPException(403,'Demo mode disabled')
    user={'id':0,'name':'Demo Operator','email':'demo@example.com','role':'Demo'}
    return {'token':token_for(user,True),'user':user}

@app.post('/api/auth/register')
def register(data:Credentials,db=Depends(database)):
    if os.getenv('ALLOW_REGISTRATION','true').lower()!='true':raise HTTPException(403,'Registration disabled')
    if '@' not in data.email:raise HTTPException(422,'Enter a valid email')
    if db.scalar(select(User).where(User.email==data.email.lower())):raise HTTPException(409,'Email already registered')
    user=User(name=data.name,email=data.email.lower(),password=password_hash.hash(data.password),role='Analyst')
    db.add(user);db.flush();event(db,'Account','Read-only analyst account registered',actor=user.email)
    return {'token':token_for(serialize(user)),'user':serialize(user)}

@app.post('/api/auth/login')
def login(data:Credentials,db=Depends(database)):
    user=db.scalar(select(User).where(User.email==data.email.lower()))
    if not user or not password_hash.verify(data.password,user.password):raise HTTPException(401,'Invalid email or password')
    return {'token':token_for(serialize(user)),'user':serialize(user)}

@app.get('/api/auth/me')
def me(user=Depends(current)):return user

def orders_data(db):
    customers={c.id:c for c in db.scalars(select(Customer)).all()}
    workers={w.id:w for w in db.scalars(select(Worker)).all()}
    return [{**serialize(o),'customer':customers[o.customer_id].name,'worker':workers[o.worker_id].name if o.worker_id in workers else None,'route':json.loads(o.route)} for o in db.scalars(select(Order).order_by(Order.created.desc())).all()]

@app.get('/api/state')
def state(user=Depends(current),db=Depends(database)):
    orders=orders_data(db); products=[serialize(p) for p in db.scalars(select(Product)).all()]
    workers=[serialize(w) for w in db.scalars(select(Worker)).all()]
    for w in workers:w['tasks']=sum(o['worker_id']==w['id'] and o['status'] not in ['Delivered','Cancelled','Shipped'] for o in orders)
    runs=[serialize(r) for r in db.scalars(select(AgentRun).order_by(AgentRun.id.desc()).limit(150)).all()]
    events=[serialize(e) for e in db.scalars(select(Event).order_by(Event.created.desc()).limit(100)).all()]
    recs=[serialize(r) for r in db.scalars(select(Recommendation).order_by(Recommendation.id.desc())).all()]
    routes=[o['route'] for o in orders if o['route'].get('optimized_distance') is not None]
    delivered=[o for o in orders if o['status']=='Delivered']
    completed=[o for o in delivered if o['completed_at']]
    hours=[(datetime.fromisoformat(o['completed_at'].rstrip('Z'))-datetime.fromisoformat(o['created'].rstrip('Z'))).total_seconds()/3600 for o in completed]
    ontime=sum(o['completed_at']<=o['deadline'] for o in completed)
    before=sum(r['original_distance'] for r in routes)
    metrics={'total':len(orders),'pending':sum(o['status'] in ['Received','Validating','Awaiting Inventory','Prioritized','Ready for Picking','Delayed'] for o in orders),'picking':sum(o['status']=='Picking' for o in orders),'fulfilled':len(delivered),'availability':round(sum(p['stock']>p['reserved'] for p in products)/max(1,len(products))*100,1),'efficiency':round(sum(r['saved'] for r in routes)/before*100,1) if before else 0,'processing_hours':round(sum(hours)/len(hours),1) if hours else 0,'on_time':round(ontime/max(1,len(completed))*100,1),'distance_saved':sum(r['saved'] for r in routes),'low_stock':sum(p['stock']-p['reserved']<p['reorder'] for p in products)}
    days=[]
    for ago in range(6,-1,-1):
        day=(now()-timedelta(days=ago)).date().isoformat()
        days.append({'day':day[5:],'received':sum(o['created'].startswith(day) for o in orders),'completed':sum(bool(o['completed_at']) and o['completed_at'].startswith(day) for o in orders)})
    return {'orders':orders,'products':products,'customers':[serialize(c) for c in db.scalars(select(Customer)).all()],'workers':workers,'runs':runs,'events':events,'recommendations':recs,'metrics':metrics,'trends':days,'agents':AGENTS,'demo':DEMO,'user':user}

@app.get('/api/orders/{order_id}')
def order_detail(order_id:int,user=Depends(current),db=Depends(database)):
    o=db.get(Order,order_id)
    if not o:raise HTTPException(404,'Order not found')
    return {**serialize(o),'items':[{**serialize(i),'product':serialize(db.get(Product,i.product_id))} for i in db.scalars(select(Item).where(Item.order_id==o.id)).all()],'events':[serialize(e) for e in db.scalars(select(Event).where(Event.order_id==o.id).order_by(Event.created)).all()]}

class LineInput(BaseModel):
    product_id:int
    quantity:int=Field(ge=1,le=10000)
class OrderInput(BaseModel):
    customer_id:int
    shipping:Literal['Standard','Express']='Standard'
    deadline:datetime
    items:list[LineInput]=Field(min_length=1,max_length=100)

@app.post('/api/orders')
def create_order(data:OrderInput,user=Depends(current),db=Depends(database)):
    access(user,['Warehouse Manager','Supervisor'])
    customer=db.get(Customer,data.customer_id)
    if not customer:raise HTTPException(422,'Customer not found')
    deadline=data.deadline.replace(tzinfo=None)
    if deadline<=now():raise HTTPException(422,'Deadline must be in the future')
    o=Order(customer_id=data.customer_id,shipping=data.shipping,deadline=deadline)
    db.add(o);db.flush()
    grouped={}
    for i in data.items:grouped[i.product_id]=grouped.get(i.product_id,0)+i.quantity
    for pid,q in grouped.items():
        p=db.get(Product,pid)
        if not p:raise HTTPException(422,'Product not found')
        db.add(Item(order_id=o.id,product_id=pid,quantity=q));o.value+=p.price*q
    event(db,'Order received','Order created by operator',o.id,user['name'])
    db.flush()
    for name in ['Order Intake','Inventory Intelligence','Order Prioritization']:execute(db,name)
    return serialize(o)

class OrderEdit(BaseModel):
    deadline:datetime
    shipping:Literal['Standard','Express']

@app.patch('/api/orders/{order_id}')
def edit_order(order_id:int,data:OrderEdit,user=Depends(current),db=Depends(database)):
    access(user,['Supervisor','Warehouse Manager']);o=db.get(Order,order_id)
    if not o:raise HTTPException(404,'Order not found')
    if o.status in ['Shipped','Delivered','Cancelled']:raise HTTPException(409,'Order is closed')
    o.deadline=data.deadline.replace(tzinfo=None);o.shipping=data.shipping;event(db,'Order updated','Deadline and shipping updated',o.id,user['name'])
    return serialize(o)

@app.delete('/api/orders/{order_id}')
def cancel(order_id:int,user=Depends(current),db=Depends(database)):
    access(user,['Supervisor','Warehouse Manager']);o=db.scalar(select(Order).where(Order.id==order_id).with_for_update())
    if not o:raise HTTPException(404,'Order not found')
    if o.status in ['Picked','Packing','Packed','Ready for Dispatch','Shipped','Delivered','Cancelled']:raise HTTPException(409,'Order cannot be cancelled after picking confirmation')
    if o.allocated:
        for i in db.scalars(select(Item).where(Item.order_id==o.id)).all():
            p=db.scalar(select(Product).where(Product.id==i.product_id).with_for_update());p.reserved-=i.quantity
    o.allocated=False;o.worker_id=None;o.status='Cancelled';event(db,'Cancelled','Order cancelled; reservations released',o.id,user['name'])
    return {'status':'Cancelled'}

class AgentInput(BaseModel):
    strategy:Literal['Batch','Zone','Wave']='Batch'

@app.post('/api/agents/{name}/run')
def run_agent(name:str,data:AgentInput,user=Depends(current),db=Depends(database)):
    access(user,['Supervisor','Warehouse Manager'])
    if name=='workflow':return workflow(db,data.strategy)
    if name not in AGENTS:raise HTTPException(404,'Agent not found')
    return execute(db,name,data.strategy)

class Advance(BaseModel):
    action:Literal['confirm_pick','start_pack','verify_pack','dispatch','ship','deliver']
    quantities:dict[str,int]|None=None

@app.post('/api/orders/{order_id}/advance')
def advance(order_id:int,data:Advance,user=Depends(current),db=Depends(database)):
    access(user,['Supervisor','Warehouse Manager','Warehouse Worker'])
    if user['role']=='Warehouse Worker':raise HTTPException(403,'Supervisor confirmation required for shared operations console')
    o=db.scalar(select(Order).where(Order.id==order_id).with_for_update())
    if not o:raise HTTPException(404,'Order not found')
    transitions={'confirm_pick':('Picking','Picked'),'start_pack':('Picked','Packing'),'verify_pack':('Packing','Packed'),'dispatch':('Packed','Ready for Dispatch'),'ship':('Ready for Dispatch','Shipped'),'deliver':('Shipped','Delivered')}
    expected,next_status=transitions[data.action]
    if o.status!=expected:raise HTTPException(409,f'Expected {expected}, found {o.status}')
    items=db.scalars(select(Item).where(Item.order_id==o.id)).all()
    if data.action in ['confirm_pick','verify_pack']:
        if data.quantities!={str(i.product_id):i.quantity for i in items}:
            event(db,'Picking mismatch','Quantity verification failed; stage blocked',o.id,user['name']);db.commit();raise HTTPException(409,'Quantities must exactly match order items')
    if data.action=='confirm_pick':
        for i in items:
            p=db.scalar(select(Product).where(Product.id==i.product_id).with_for_update())
            if p.stock<i.quantity or p.reserved<i.quantity:raise HTTPException(409,'Reservation mismatch; supervisor review required')
            p.stock-=i.quantity;p.reserved-=i.quantity;db.add(Movement(product_id=p.id,quantity=-i.quantity,reason=f'Picked WH-{o.id:05}'))
        o.allocated=False
    if data.action=='ship':
        o.tracking='WH-'+secrets.token_hex(6).upper()
        if o.worker_id:db.get(Worker,o.worker_id).completed+=1
    if data.action=='deliver':o.completed_at=now()
    o.status=next_status;event(db,next_status,f'Operator confirmed {data.action.replace("_"," ")}',o.id,user['name'])
    return serialize(o)

class ProductInput(BaseModel):
    sku:str=Field(min_length=2,max_length=80)
    name:str=Field(min_length=2,max_length=200)
    category:str=Field(min_length=2,max_length=80)
    stock:int=Field(ge=0,le=1000000)
    reorder:int=Field(default=20,ge=0)
    price:float=Field(default=10,ge=0)
    zone:Literal['A','B','C','D']='A'
    x:int=Field(default=2,ge=0,le=33)
    y:int=Field(default=2,ge=0,le=15)

@app.post('/api/products')
def add_product(data:ProductInput,user=Depends(current),db=Depends(database)):
    access(user,['Warehouse Manager'])
    if db.scalar(select(Product).where(Product.sku==data.sku)):raise HTTPException(409,'SKU already exists')
    p=Product(**data.model_dump(),bin=f'{data.zone}-{data.x}-{data.y}');db.add(p);db.flush();event(db,'Inventory','Product created: '+p.sku,actor=user['name']);return serialize(p)

@app.patch('/api/products/{pid}')
def edit_product(pid:int,data:ProductInput,user=Depends(current),db=Depends(database)):
    access(user,['Warehouse Manager']);p=db.scalar(select(Product).where(Product.id==pid).with_for_update())
    if not p:raise HTTPException(404,'Product not found')
    if data.stock<p.reserved:raise HTTPException(409,'Stock cannot fall below reserved quantity')
    if db.scalar(select(Product).where(Product.sku==data.sku,Product.id!=pid)):raise HTTPException(409,'SKU already exists')
    delta=data.stock-p.stock
    for k,v in data.model_dump().items():setattr(p,k,v)
    if delta:db.add(Movement(product_id=p.id,quantity=delta,reason='Operator stock adjustment'))
    event(db,'Inventory','Product updated: '+p.sku,actor=user['name']);return serialize(p)

@app.delete('/api/products/{pid}')
def remove_product(pid:int,user=Depends(current),db=Depends(database)):
    access(user,['Warehouse Manager']);p=db.get(Product,pid)
    if not p:raise HTTPException(404,'Product not found')
    if db.scalar(select(Item.id).where(Item.product_id==pid)) or db.scalar(select(Movement.id).where(Movement.product_id==pid)):raise HTTPException(409,'Product has operational history; retain it for audit')
    db.delete(p);event(db,'Inventory','Unused product removed',actor=user['name']);return {'removed':pid}

class Adjustment(BaseModel):
    quantity:int=Field(ge=-100000,le=100000)
    reason:str=Field(min_length=3,max_length=500)

@app.post('/api/products/{pid}/adjust')
def adjust(pid:int,data:Adjustment,user=Depends(current),db=Depends(database)):
    access(user,['Warehouse Manager']);p=db.scalar(select(Product).where(Product.id==pid).with_for_update())
    if not p:raise HTTPException(404,'Product not found')
    if p.stock+data.quantity<p.reserved:raise HTTPException(409,'Adjustment would invalidate reservations')
    p.stock+=data.quantity;db.add(Movement(product_id=pid,quantity=data.quantity,reason=data.reason));event(db,'Stock adjustment',f'{p.sku}: {data.quantity:+} units. {data.reason}',actor=user['name']);return serialize(p)

@app.get('/api/products/{pid}/movements')
def movements(pid:int,user=Depends(current),db=Depends(database)):return [serialize(m) for m in db.scalars(select(Movement).where(Movement.product_id==pid).order_by(Movement.id.desc())).all()]

class WorkerInput(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    role:str=Field(default='Picker',max_length=80)
    skills:str=Field(default='Picking, Packing',max_length=250)
    available:bool=True

@app.post('/api/workers')
def add_worker(data:WorkerInput,user=Depends(current),db=Depends(database)):
    access(user,['Warehouse Manager']);w=Worker(**data.model_dump());db.add(w);db.flush();event(db,'Worker','Worker added: '+w.name,actor=user['name']);return serialize(w)

@app.patch('/api/workers/{wid}')
def edit_worker(wid:int,data:WorkerInput,user=Depends(current),db=Depends(database)):
    access(user,['Warehouse Manager']);w=db.get(Worker,wid)
    if not w:raise HTTPException(404,'Worker not found')
    for k,v in data.model_dump().items():setattr(w,k,v)
    event(db,'Worker','Worker updated: '+w.name,actor=user['name']);return serialize(w)

class Assignment(BaseModel):worker_id:int
@app.post('/api/orders/{oid}/assign')
def reassign(oid:int,data:Assignment,user=Depends(current),db=Depends(database)):
    access(user,['Supervisor','Warehouse Manager']);o=db.scalar(select(Order).where(Order.id==oid).with_for_update());w=db.scalar(select(Worker).where(Worker.id==data.worker_id).with_for_update())
    if not o or not w:raise HTTPException(404,'Order or worker not found')
    if o.status not in ['Ready for Picking','Picking']:raise HTTPException(409,'Reassignment only available during picking')
    busy=db.scalar(select(Order.id).where(Order.worker_id==w.id,Order.id!=o.id,Order.status.in_(['Picking','Picked','Packing','Packed','Ready for Dispatch'])))
    if not w.available or busy or 'Picking' not in w.skills:raise HTTPException(409,'Worker unavailable, lacks picking skill, or has conflicting task')
    o.worker_id=w.id;event(db,'Reassigned','Task reassigned to '+w.name,o.id,user['name']);return serialize(o)

class Override(BaseModel):
    score:float=Field(ge=0,le=100)
    reason:str=Field(min_length=5,max_length=500)
@app.post('/api/orders/{oid}/priority')
def override(oid:int,data:Override,user=Depends(current),db=Depends(database)):
    access(user,['Supervisor']);o=db.get(Order,oid)
    if not o:raise HTTPException(404,'Order not found')
    before=o.score;o.score=data.score;o.priority='Critical' if data.score>=80 else 'High' if data.score>=60 else 'Medium' if data.score>=35 else 'Low';o.explanation='Supervisor override: '+data.reason
    event(db,'Priority override',f'{before} → {data.score}: {data.reason}',o.id,user['name']);return serialize(o)

class Decision(BaseModel):status:Literal['Acknowledged','Dismissed','Replenishment requested']
@app.patch('/api/recommendations/{rid}')
def decision(rid:int,data:Decision,user=Depends(current),db=Depends(database)):
    access(user,['Warehouse Manager','Supervisor']);r=db.get(Recommendation,rid)
    if not r:raise HTTPException(404,'Recommendation not found')
    r.status=data.status;event(db,'Recommendation',f'{data.status}: {r.title}',actor=user['name']);return serialize(r)

@app.get('/api/reports/orders.csv')
def export(start:str|None=None,end:str|None=None,user=Depends(current),db=Depends(database)):
    rows=orders_data(db)
    rows=[o for o in rows if (not start or o['created'][:10]>=start) and (not end or o['created'][:10]<=end)]
    buffer=io.StringIO();fields=['id','customer','status','priority','score','value','created','deadline','tracking'];writer=csv.DictWriter(buffer,fieldnames=fields,extrasaction='ignore');writer.writeheader()
    for row in rows:
        writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in row.items()})
    return StreamingResponse(iter([buffer.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=warehouse-orders.csv'})
