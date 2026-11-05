import random
from datetime import timedelta
from sqlalchemy import select
from .database import *

def seed(db):
    if db.scalar(select(Product.id).limit(1)): return
    rng = random.Random(72)
    names = ['Wireless scanner', 'Safety gloves', 'Industrial sensor', 'Packing tape', 'Steel fastener', 'USB-C adapter', 'LED work light', 'Cable organizer', 'Thermal label', 'Precision bearing', 'Filter cartridge', 'Motor controller']
    categories = ['Electronics','Safety','Industrial','Packaging']
    for i in range(120):
        zone='ABCD'[i//30]; x=(i//30)*8+2+(i%5); y=2+(i%30//5)*2
        db.add(Product(sku=f'WH-{1001+i}', name=f'{names[i%12]} {i//12+1:02}', category=categories[i%4], stock=0 if i%19==0 else rng.randint(3,180), reorder=20, price=round(rng.uniform(5,250),2),zone=zone,aisle=i%5+1,rack=i%6+1,shelf=i%3+1,bin=f'{zone}-{i%5+1:02}-{i%6+1:02}',x=x,y=y))
    for i in range(55):
        db.add(Customer(name=f'{["Meridian", "Northstar", "Atlas", "Vertex", "Summit"][i%5]} {["Retail", "Industries", "Supply", "Labs", "Logistics"][i//5%5]} {i+1}',email=f'operations{i+1}@example.com',address=f'{100+i} Commerce Avenue, Bengaluru, India',priority=rng.choice([30,50,75,100])))
    for i,name in enumerate(['Arjun Mehta','Priya Sharma','Ravi Kumar','Ananya Rao','Vikram Singh','Sneha Patel','Kiran Reddy','Divya Nair','Aditya Das','Meera Joshi','Rahul Shah','Neha Gupta','Sanjay Roy','Pooja Iyer','Aman Verma','Isha Jain']):
        db.add(Worker(name=name, role='Supervisor' if i==0 else 'Picker',skills='Picking, Packing, Express' if i%3==0 else 'Picking, Packing',available=i!=14, x=(i%4)*8,y=0))
    db.flush()
    products=db.scalars(select(Product)).all()
    for i in range(220):
        created=now()-timedelta(hours=rng.randint(0,168))
        order=Order(customer_id=i%55+1,created=created,deadline=created+timedelta(hours=rng.choice([12,24,48,96,192])),shipping='Express' if i%4==0 else 'Standard')
        db.add(order); db.flush()
        for p in rng.sample(products,rng.randint(1,4)):
            q=rng.randint(1,4); db.add(Item(order_id=order.id,product_id=p.id,quantity=q));order.value+=p.price*q
        if i<125:
            order.status='Delivered';order.completed_at=created+timedelta(hours=rng.randint(2,10));order.tracking=f'DEMO-{order.id:07}'
            for stage in ['Picked','Packed','Shipped','Delivered']:
                db.add(Event(kind=stage,message=f'Synthetic historical {stage.lower()} event',order_id=order.id,created=order.completed_at,actor='Demo seed'))
        db.add(Event(kind='Order received',message=f'Order WH-{order.id:05} received',order_id=order.id,created=created,actor='Demo seed'))
    db.add(Event(kind='System',message='Synthetic demo dataset initialized: 120 products, 55 customers, 220 orders and 16 workers.'))
    db.commit()
