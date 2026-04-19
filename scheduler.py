import os
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz
from database import SessionLocal, Medication
from linebot import LineBotApi
from linebot.models import TextSendMessage
from dotenv import load_dotenv

load_dotenv()

line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))

def check_medication_schedule():
    tz = pytz.timezone('Asia/Bangkok')
    now = datetime.now(tz)
    current_time_str = now.strftime("%H:%M")
    
    db = SessionLocal()
    try:
        # Get all active medications
        medications = db.query(Medication).filter(Medication.is_active == True).all()
        for med in medications:
            if not med.time_to_take:
                continue
                
            times = [t.strip() for t in med.time_to_take.split(",")]
            if current_time_str in times:
                # Send Line message
                msg = f"💊 ถึงเวลาทานยาแล้วค่ะ!\nชื่อยา: {med.med_name}\nวิธีใช้: {med.dosage}\nขอให้สุขภาพแข็งแรงนะคะ ❤️"
                try:
                    line_bot_api.push_message(med.user_id, TextSendMessage(text=msg))
                    print(f"Sent reminder for {med.med_name} to {med.user_id}")
                except Exception as e:
                    print(f"Error sending message to {med.user_id}: {e}")
    finally:
        db.close()

def start_scheduler():
    scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Bangkok'))
    # Run every minute
    scheduler.add_job(check_medication_schedule, 'cron', minute='*')
    scheduler.start()
