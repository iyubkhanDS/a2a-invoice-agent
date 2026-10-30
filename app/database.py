import os
import json
from datetime import datetime
from sqlalchemy import create_engine, Column, String, DateTime, Text, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Setup local SQLite database file path
DATABASE_URL = "sqlite:///./a2a_agent.db"

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False}  # Needed for multi-threaded SQLite in FastAPI
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class TaskRecord(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, index=True)         # Server-generated Task UUID
    principal = Column(String, index=True, nullable=False)     # Bearer Token Identity (User Isolation)
    context_id = Column(String, index=True, nullable=False)    # Context Session UUID
    batch_id = Column(String, index=True, nullable=False)      # Invoice Batch Identifier
    state = Column(String, nullable=False, default="TASK_STATE_SUBMITTED") # Lifecycle state
    
    # Store complex protocol structures as compressed text blobs
    status_msg = Column(Text, nullable=True)     # Latest descriptive message object
    proposals = Column(Text, nullable=True)      # Active action suggestions array
    executions = Column(Text, nullable=True)     # Validated final receipt nonces array
    history = Column(Text, nullable=False, default="[]") # Appended raw message exchange structures
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    # Compound key: uniquely locks a request by combining the caller profile + the client's message identifier
    principal_message_hash = Column(String, primary_key=True, index=True)
    task_id = Column(String, nullable=False)
    compact_response_blob = Column(LargeBinary, nullable=False) # Cached Task layout string for immediate replay

# Create all database tracking surfaces immediately upon boot
def init_db():
    Base.metadata.create_all(bind=engine)

# Clean context dependency hook for FastAPI paths
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
