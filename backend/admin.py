"""Create an administrator without committing credentials: python admin.py email name."""
import sys,getpass
from sqlalchemy import select
from app.database import Base,engine,Session,User
from app.main import password_hash
if len(sys.argv)!=3:raise SystemExit('Usage: python admin.py email name')
password=getpass.getpass('New password (minimum 12 characters): ')
if len(password)<12:raise SystemExit('Password too short')
Base.metadata.create_all(engine)
with Session() as db:
    if db.scalar(select(User).where(User.email==sys.argv[1].lower())):raise SystemExit('Account exists; use a controlled database role update.')
    db.add(User(email=sys.argv[1].lower(),name=sys.argv[2],password=password_hash.hash(password),role='Admin'));db.commit()
print('Administrator created.')
