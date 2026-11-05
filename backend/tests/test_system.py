import os,tempfile
os.environ['DATABASE_URL']='sqlite:///'+tempfile.mktemp(suffix='.db')
os.environ['JWT_SECRET_KEY']='test-secret-only-not-for-production-123456789'
os.environ['DEMO_MODE']='true'
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from app.main import app
from app.database import Session,Product,Order,Item,Worker,AgentRun,Event,now,User
from app.optimization import optimize,length
from app.seed import seed

@pytest.fixture(scope='module')
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture(scope='module')
def headers(client):
    token=client.post('/api/auth/demo').json()['token']
    return {'Authorization':'Bearer '+token}

def test_health_and_auth(client):
    assert client.get('/api/health').json()['status']=='ok'
    assert client.get('/api/state').status_code==401
    assert client.get('/api/state',headers={'Authorization':'Bearer invalid'}).status_code==401

def test_seed_rerunnable(client,headers):
    with Session() as db:
        seed(db);seed(db)
        assert db.scalar(select(func.count()).select_from(Product))==120
    state=client.get('/api/state',headers=headers).json()
    assert len(state['customers'])==55 and len(state['orders'])==220 and len(state['workers'])==16
    assert state['metrics']['total']==len(state['orders'])

def test_auth_registration_and_rbac(client):
    payload={'email':'analyst@example.com','password':'a-secure-test-password','name':'Test analyst'}
    r=client.post('/api/auth/register',json=payload)
    assert r.status_code==200 and r.json()['user']['role']=='Analyst'
    auth={'Authorization':'Bearer '+r.json()['token']}
    assert client.get('/api/state',headers=auth).status_code==200
    assert client.post('/api/agents/workflow/run',json={},headers=auth).status_code==403
    assert client.post('/api/auth/register',json=payload).status_code==409
    assert client.post('/api/auth/login',json={**payload,'password':'wrong-password'}).status_code==401
    assert client.post('/api/auth/login',json=payload).status_code==200
    with Session() as db:
        assert db.scalar(select(User).where(User.email==payload['email'])).password.startswith('$argon2')

def new_order(client,headers,pid,quantity=2):
    return client.post('/api/orders',headers=headers,json={'customer_id':1,'deadline':(now()+timedelta(hours=8)).isoformat()+'Z','shipping':'Express','items':[{'product_id':pid,'quantity':quantity}]})

def test_order_priority_and_shortage(client,headers):
    with Session() as db:p=db.scalar(select(Product).where(Product.stock==0));pid=p.id
    r=new_order(client,headers,pid)
    assert r.status_code==200
    o=r.json();assert o['status']=='Awaiting Inventory' and o['score']>0
    assert 'Delivery urgency' in o['explanation']
    client.post('/api/agents/workflow/run',headers=headers,json={})
    detail=client.get('/api/orders/'+str(o['id']),headers=headers).json()
    assert detail['worker_id'] is None and not detail['allocated']

def test_langgraph_workflow_and_invariants(client,headers):
    r=client.post('/api/agents/workflow/run',headers=headers,json={'strategy':'Batch'})
    assert r.status_code==200
    assert len(r.json()['results'])==9
    assert all(x['status']=='Success' for x in r.json()['results'])
    with Session() as db:
        for p in db.scalars(select(Product)).all():assert 0<=p.reserved<=p.stock
        picking=db.scalars(select(Order).where(Order.status=='Picking')).all()
        assert picking
        assert len({o.worker_id for o in picking})==len(picking)
        assert db.scalar(select(func.count()).select_from(AgentRun))>=9

def test_optimizer_computes_distances():
    route=optimize([(10,5),(1,2),(15,3),(2,2)])
    assert route['optimized_distance']<=route['original_distance']
    assert route['original_distance']==length(route['original'])*2
    assert route['saved']==route['original_distance']-route['optimized_distance']
    assert route['stops']==4
    assert optimize([])['saved']==0
    assert optimize([(2,3),(2,3)])['stops']==1
    for strategy in ['Batch','Zone','Wave']:
        result=optimize([(10,5),(1,2),(15,3),(2,2)],strategy=strategy)
        assert result['optimized_distance']<=result['original_distance']
        assert len(result['optimized'])==6
        assert result['strategy']==strategy

def test_fulfillment_requires_quantity_verification(client,headers):
    state=client.get('/api/state',headers=headers).json()
    order=next(o for o in state['orders'] if o['status']=='Picking')
    oid=order['id'];detail=client.get(f'/api/orders/{oid}',headers=headers).json()
    quantities={str(i['product_id']):i['quantity'] for i in detail['items']}
    def advance(action,q=None):return client.post(f'/api/orders/{oid}/advance',headers=headers,json={'action':action,'quantities':q})
    assert advance('ship').status_code==409
    assert advance('confirm_pick',{}).status_code==409
    assert advance('confirm_pick',quantities).json()['status']=='Picked'
    assert advance('confirm_pick',quantities).status_code==409
    assert advance('start_pack').json()['status']=='Packing'
    assert advance('verify_pack',{}).status_code==409
    assert advance('verify_pack',quantities).json()['status']=='Packed'
    assert advance('dispatch').json()['status']=='Ready for Dispatch'
    shipped=advance('ship');assert shipped.json()['tracking'] and shipped.json()['status']=='Shipped'
    assert advance('deliver').json()['completed_at']
    detail=client.get(f'/api/orders/{oid}',headers=headers).json()
    assert any(e['kind']=='Shipped' for e in detail['events'])
    assert any(e['kind']=='Picking mismatch' for e in detail['events'])

def test_negative_stock_rejected(client,headers):
    r=client.post('/api/products/1/adjust',headers=headers,json={'quantity':-100000,'reason':'Test invalid adjustment'})
    assert r.status_code==409
    assert client.post('/api/products/1/adjust',headers=headers,json={'quantity':50,'reason':'Test receipt'}).status_code==200
    assert client.get('/api/products/1/movements',headers=headers).json()

def test_cancellation_releases_reservations(client,headers):
    with Session() as db:
        o=db.scalar(select(Order).where(Order.status=='Picking'));oid=o.id
        before={p.id:p.reserved for p in db.scalars(select(Product)).all()}
        items=[(i.product_id,i.quantity) for i in db.scalars(select(Item).where(Item.order_id==oid)).all()]
    assert client.delete(f'/api/orders/{oid}',headers=headers).status_code==200
    with Session() as db:
        for pid,q in items:assert db.get(Product,pid).reserved==before[pid]-q

def test_agent_failure_logged(client,headers):
    from app.agents import execute
    with Session() as db:
        result=execute(db,'Invalid agent');db.commit()
        assert result['status']=='Failed'
        run=db.scalar(select(AgentRun).where(AgentRun.agent=='Invalid agent'))
        assert run.status=='Failed' and 'Unknown agent' in run.output

def test_crud_and_reporting(client,headers):
    p={'sku':'TEST-NEW','name':'Test scanner','category':'Electronics','stock':15,'zone':'B','x':10,'y':4}
    r=client.post('/api/products',json=p,headers=headers);assert r.status_code==200;pid=r.json()['id']
    assert client.post('/api/products',json=p,headers=headers).status_code==409
    assert client.patch(f'/api/products/{pid}',json={**p,'name':'Updated scanner'},headers=headers).status_code==200
    assert client.delete(f'/api/products/{pid}',headers=headers).status_code==200
    w=client.post('/api/workers',json={'name':'New worker'},headers=headers);assert w.status_code==200
    assert client.patch('/api/workers/'+str(w.json()['id']),json={'name':'Updated worker','available':False},headers=headers).status_code==200
    report=client.get('/api/reports/orders.csv?start=2000-01-01',headers=headers)
    assert report.status_code==200 and 'text/csv' in report.headers['content-type'] and 'customer' in report.text

def test_invalid_inputs(client,headers):
    assert new_order(client,headers,999999).status_code==422
    assert new_order(client,headers,1,0).status_code==422
    assert client.post('/api/agents/unknown/run',json={},headers=headers).status_code==404
