from db.database import Base, engine
import db.model
from db.db_operations import seed_initial_sites
print("before building a db")
Base.metadata.create_all(bind=engine)
seed_initial_sites()
print("after building a db")