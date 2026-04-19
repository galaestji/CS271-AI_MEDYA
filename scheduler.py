import os
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import pytz
from database import SessionLocal, Medication, MedicationLog
from linebot import LineBotApi
from linebot.models import TemplateSendMessage, ButtonsTemplate, PostbackAction, TextSendMessage, FlexSendMessage
from dotenv import load_dotenv

load_dotenv()

line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))

def check_medication_schedule():
    tz = pytz.timezone('Asia/Bangkok')
    now = datetime.now(tz)
    current_time_str = now.strftime("%H:%M")
    
    db = SessionLocal()
    try:
        medications = db.query(Medication).filter(Medication.is_active == True).all()
        medications = db.query(Medication).filter(Medication.is_active == True).all()
        user_meds = {}
        for med in medications:
            if not med.time_to_take: continue
            times = [t.strip() for t in med.time_to_take.split(",")]
            if current_time_str in times:
                if med.user_id not in user_meds:
                    user_meds[med.user_id] = []
                user_meds[med.user_id].append(med)
                
        for user_id, meds in user_meds.items():
            bubbles = []
            for med in meds:
                # 1. Create Log
                log = MedicationLog(
                    user_id=med.user_id,
                    medication_id=med.id,
                    scheduled_time=now.strftime("%Y-%m-%d %H:%M"),
                    status="WAITING"
                )
                db.add(log)
                db.commit()
                db.refresh(log)

                # 2. Add Bubble
                bubble = {
                    "type": "bubble",
                    "header": {
                        "type": "box", "layout": "vertical", "backgroundColor": "#4CB0A0", "paddingAll": "20px",
                        "contents": [ {"type": "text", "text": "🔔 ถึงเวลาทานยาแล้ว!", "weight": "bold", "color": "#FFFFFF", "size": "xl"} ]
                    },
                    "body": {
                        "type": "box", "layout": "vertical", "paddingAll": "20px",
                        "contents": [
                            {"type": "text", "text": med.med_name, "weight": "bold", "size": "xxl", "color": "#333333", "wrap": True},
                            {"type": "text", "text": f"วิธีใช้: {med.dosage}", "size": "md", "color": "#666666", "wrap": True, "margin": "md"},
                            {"type": "text", "text": "กรุณากดยืนยันการทานยาภายใน 10 นาที", "size": "sm", "color": "#aaaaaa", "margin": "xl", "wrap": True}
                        ]
                    },
                    "footer": {
                        "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "20px",
                        "contents": [
                            {"type": "button", "style": "primary", "color": "#4CB0A0", "action": {"type": "postback", "label": "✅ ทานยาเรียบร้อย", "data": f"log_action=TAKEN&id={log.id}", "displayText": "ทานแล้ว"}},
                            {"type": "button", "style": "secondary", "action": {"type": "postback", "label": "❌ เลื่อน/ยังไม่ทาน", "data": f"log_action=SKIPPED&id={log.id}", "displayText": "ยังไม่ทาน"}}
                        ]
                    }
                }
                bubbles.append(bubble)
            
            if not bubbles: continue
            
            if len(bubbles) == 1:
                contents = bubbles[0]
            else:
                contents = {"type": "carousel", "contents": bubbles[:12]} # up to 12 capsules
                
            flex_message = FlexSendMessage(
                alt_text=f"ถึงเวลาทานยา {len(bubbles)} รายการค่ะ! (กรุณาเปิดแชทดู)",
                contents=contents
            )
            try:
                line_bot_api.push_message(user_id, flex_message)
            except Exception as e:
                print(e)
    finally:
        db.close()

def check_timeouts():
    tz = pytz.timezone('Asia/Bangkok')
    now = datetime.now(tz)
    
    db = SessionLocal()
    try:
        waiting_logs = db.query(MedicationLog).filter(MedicationLog.status == "WAITING").all()
        for log in waiting_logs:
            sched_time = datetime.strptime(log.scheduled_time, "%Y-%m-%d %H:%M")
            sched_time = tz.localize(sched_time)
            
            if now - sched_time > timedelta(minutes=10):
                log.status = "MISSED"
                db.commit()
                med = db.query(Medication).filter(Medication.id == log.medication_id).first()
                med_name = med.med_name if med else "ไม่ทราบชื่อ"
                
                flex_msg = FlexSendMessage(
                    alt_text="คุณลืมทานยา!",
                    contents={
                        "type": "bubble",
                        "header": { "type": "box", "layout": "vertical", "backgroundColor": "#E74C3C", "paddingAll": "15px", "contents": [ {"type": "text", "text": "⚠️ ลืมทานยา!", "weight": "bold", "color": "#FFFFFF", "size": "lg"} ] },
                        "body": { "type": "box", "layout": "vertical", "paddingAll": "20px", "contents": [ 
                            {"type": "text", "text": f"เลยเวลามา 10 นาทีแล้ว\nระบบบันทึกว่าขาดทานยา:\n💊 {med_name}", "size": "md", "color": "#333333", "wrap": True},
                            {"type": "text", "text": "หากลืมทานจริงๆ โปรดปรึกษาเภสัชกรนะคะ", "size": "xs", "color": "#E74C3C", "wrap": True, "margin": "lg"}
                         ] }
                    }
                )
                try:
                    line_bot_api.push_message(log.user_id, flex_msg)
                except:
                    pass
    finally:
        db.close()

def start_scheduler():
    scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Bangkok'))
    scheduler.add_job(check_medication_schedule, 'cron', minute='*')
    scheduler.add_job(check_timeouts, 'cron', minute='*')
    scheduler.start()
