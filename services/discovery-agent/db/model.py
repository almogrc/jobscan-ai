from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from .database import Base
class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    url = Column(String, unique=True) 
    job_hash = Column(String, index=True) 
    should_delete = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class TargetSite(Base):
    __tablename__ = "target_sites"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    base_url = Column(String)
    is_active = Column(Boolean, default=True)