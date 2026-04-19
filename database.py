import os
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./med_reminder.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class Medication(Base):
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True) # LINE User ID
    med_name = Column(String)
    dosage = Column(String)
    time_to_take = Column(String) # comma-separated string, e.g., "08:00, 12:00, 18:00"
    is_active = Column(Boolean, default=True)

Base.metadata.create_all(bind=engine)
