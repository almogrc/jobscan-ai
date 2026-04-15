from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from datetime import datetime, timezone
from .database import Base
class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    site_id = Column(Integer, ForeignKey("target_sites.id"))
    url = Column(String, unique=True) 
    job_hash = Column(String, index=True) 
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class TargetSite(Base):
    __tablename__ = "target_sites"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    base_url = Column(String)
    is_active = Column(Boolean, default=True)