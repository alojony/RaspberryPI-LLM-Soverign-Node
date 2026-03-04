import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Float
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////data/db/pi_node.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class ReminderDB(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    text = Column(String, nullable=False)
    trigger_at = Column(DateTime, nullable=False)
    recurring = Column(String, nullable=True)
    completed = Column(Boolean, default=False)


class DocumentDB(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String, unique=True, nullable=False)
    file_hash = Column(String, nullable=False)
    last_indexed = Column(DateTime, nullable=False)
    chunk_count = Column(Integer, nullable=True)


class TimerDB(Base):
    __tablename__ = "timers"

    id = Column(Integer, primary_key=True)
    label = Column(String, nullable=False)
    duration_seconds = Column(Integer, nullable=False)
    fire_at = Column(DateTime, nullable=False)
    fired = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, nullable=False)


class ConversationDB(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

class MessageDB(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, nullable=False, index=True)
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    sources = Column(String, nullable=True)   # JSON-encoded list
    latency_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
