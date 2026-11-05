from app.database import Base, engine, Session
from app.seed import seed
Base.metadata.create_all(engine)
with Session() as db: seed(db)
print('Demo seed complete (safe to rerun).')
