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
    
    total_pills = Column(Integer, nullable=True)     # จำนวนยาทั้งหมดที่ได้มาตอนแรก
    pills_left = Column(Integer, nullable=True)      # จำนวนยาที่เหลืออยู่ (เอาไว้หักลบ)
    pills_per_dose = Column(Integer, default=1)      # จำนวนยาที่ต้องกินต่อครั้ง

class MedicationLog(Base):
    __tablename__ = "medication_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    medication_id = Column(Integer, index=True)
    scheduled_time = Column(String) # e.g. "2026-04-20 08:00"
    status = Column(String) # "WAITING", "TAKEN", "MISSED"
    timestamp = Column(String, nullable=True) # เวลาที่รับประทานจริง (สำหรับเก็บประวัติ)

Base.metadata.create_all(bind=engine)
