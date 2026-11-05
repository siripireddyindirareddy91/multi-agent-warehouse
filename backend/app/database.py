import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Integer, Float, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

url = os.getenv('DATABASE_URL', 'sqlite:////tmp/warehouse.db' if os.getenv('VERCEL') else 'sqlite:///./warehouse.db')
if url.startswith(('postgres://', 'postgresql://')):
    url = url.replace('postgres://', 'postgresql+psycopg://', 1).replace('postgresql://', 'postgresql+psycopg://', 1)
engine = create_engine(url, connect_args={'check_same_thread': False} if url.startswith('sqlite') else {}, pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(250), unique=True)
    password: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(40), default='Analyst')

class Product(Base):
    __tablename__ = 'products'
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80))
    stock: Mapped[int] = mapped_column(default=0)
    reserved: Mapped[int] = mapped_column(default=0)
    reorder: Mapped[int] = mapped_column(default=15)
    price: Mapped[float] = mapped_column(Float, default=0)
    zone: Mapped[str] = mapped_column(String(1))
    aisle: Mapped[int] = mapped_column(default=1)
    rack: Mapped[int] = mapped_column(default=1)
    shelf: Mapped[int] = mapped_column(default=1)
    bin: Mapped[str] = mapped_column(String(30))
    x: Mapped[int] = mapped_column()
    y: Mapped[int] = mapped_column()

class Customer(Base):
    __tablename__ = 'customers'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(250))
    address: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(default=50)

class Worker(Base):
    __tablename__ = 'workers'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(80), default='Picker')
    skills: Mapped[str] = mapped_column(String(250), default='Picking, Packing')
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    completed: Mapped[int] = mapped_column(default=0)
    x: Mapped[int] = mapped_column(default=0)
    y: Mapped[int] = mapped_column(default=0)

class Order(Base):
    __tablename__ = 'orders'
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey('customers.id'))
    status: Mapped[str] = mapped_column(String(40), default='Received')
    shipping: Mapped[str] = mapped_column(String(40), default='Standard')
    created: Mapped[datetime] = mapped_column(DateTime, default=now)
    deadline: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0)
    priority: Mapped[str] = mapped_column(String(20), default='Low')
    explanation: Mapped[str] = mapped_column(Text, default='Awaiting prioritization')
    risk: Mapped[float] = mapped_column(Float, default=0)
    worker_id: Mapped[int | None] = mapped_column(ForeignKey('workers.id'), nullable=True)
    route: Mapped[str] = mapped_column(Text, default='{}')
    allocated: Mapped[bool] = mapped_column(Boolean, default=False)
    value: Mapped[float] = mapped_column(Float, default=0)
    tracking: Mapped[str | None] = mapped_column(String(100), nullable=True)

class Item(Base):
    __tablename__ = 'order_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('orders.id'))
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    quantity: Mapped[int] = mapped_column()

class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor: Mapped[str] = mapped_column(String(150), default='System')
    created: Mapped[datetime] = mapped_column(DateTime, default=now)

class AgentRun(Base):
    __tablename__ = 'agent_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    agent: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    input: Mapped[str] = mapped_column(Text)
    output: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[float] = mapped_column(Float)
    created: Mapped[datetime] = mapped_column(DateTime, default=now)

class Movement(Base):
    __tablename__ = 'stock_movements'
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'))
    quantity: Mapped[int] = mapped_column()
    reason: Mapped[str] = mapped_column(Text)
    created: Mapped[datetime] = mapped_column(DateTime, default=now)

class Recommendation(Base):
    __tablename__ = 'recommendations'
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default='Open')
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

def serialize(obj):
    return {c.name: (getattr(obj,c.name).isoformat()+'Z' if isinstance(getattr(obj,c.name),datetime) else getattr(obj,c.name)) for c in obj.__table__.columns if c.name != 'password'}
