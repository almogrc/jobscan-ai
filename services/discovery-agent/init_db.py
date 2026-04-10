from db.database import Base, engine
import db.model
print("before building a db")
Base.metadata.create_all(bind=engine)
print("after building a db")