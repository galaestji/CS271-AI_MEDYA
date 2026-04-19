import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from database import SessionLocal, Medication
from ocr_engine import extract_text_from_image
from llm_parser import parse_medication_text
from scheduler import start_scheduler

from linebot import LineBotApi, WebhookParser
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, ImageMessage, TextSendMessage

load_dotenv()

app = FastAPI(title="Medication Reminder Bot")

# Initialize Line Bot
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')

if LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET:
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    parser = WebhookParser(LINE_CHANNEL_SECRET)
else:
    print("Warning: LINe Channel Access Token or Secret is missing in .env")
    line_bot_api = None
    parser = None

@app.on_event("startup")
def startup_event():
    start_scheduler()

@app.post("/callback")
async def callback(request: Request):
    if not parser:
        return JSONResponse(content={"status": "error", "message": "LINE configurations not set"}, status_code=500)
        
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    body_text = body.decode('utf-8')

    try:
        events = parser.parse(body_text, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if not isinstance(event, MessageEvent):
            continue
            
        user_id = event.source.user_id
        
        if isinstance(event.message, ImageMessage):
            # Reply acknowledging receipt
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กำลังอ่านฉลากยาและประมวลผล กรุณารอสักครู่นะคะ ⏳"))
            
            # 1. Download Image from Line
            message_content = line_bot_api.get_message_content(event.message.id)
            image_bytes = b"".join(message_content.iter_content())
            
            # 2. Extract Text with OCR
            text = extract_text_from_image(image_bytes)
            if not text:
                line_bot_api.push_message(user_id, TextSendMessage(text="ขออภัยค่ะ มองไม่เห็นตัวอักษรเลย รบกวนถ่ายรูปให้ชัดขึ้นอีกนิดนะคะ"))
                continue
                
            # 3. Parse Text with LLM
            parsed_data = parse_medication_text(text)
            if not parsed_data:
                line_bot_api.push_message(user_id, TextSendMessage(text="ขออภัยค่ะ ไม่สามารถวิเคราะห์ข้อมูลยาได้ อาจเป็นเพราะภาพไม่ชัดเจน"))
                continue
                
            med_name = parsed_data.get("med_name", "ไม่ทราบชื่อยา")
            std_med_name = parsed_data.get("std_med_name", None)
            dosage = parsed_data.get("dosage", "ไม่ทราบวิธีใช้")
            times = parsed_data.get("times", [])
            
            # 4. Save to Database
            times_str = ", ".join(times) if times else "ไม่ได้ระบุเวลา"
            db = SessionLocal()
            try:
                new_med = Medication(
                    user_id=user_id,
                    med_name=med_name,
                    dosage=dosage,
                    time_to_take=times_str
                )
                db.add(new_med)
                db.commit()
            except Exception as e:
                print(e)
            finally:
                db.close()
            
            # 5. Send Success Message
            import json
            med_info = None
            if std_med_name:
                try:
                    with open("medicine_db.json", "r", encoding="utf-8") as f:
                        med_db = json.load(f)
                    med_info = next((m for m in med_db if m.get("name") == std_med_name), None)
                except Exception as e:
                    print(f"Error loading medicine_db.json in main.py: {e}")

            reply_msg = f"✅ บันทึกรอบทานยาเรียบร้อยค่ะ!\n\n💊 ชื่อยา: {med_name}\n📝 วิธีใช้: {dosage}\n⏰ เวลาแจ้งเตือน: {times_str}\n"
            
            if med_info:
                reply_msg += f"\n💡 สรรพคุณ: {med_info.get('usage', 'ไม่มีข้อมูล')}\n⚠️ ข้อควรระวัง: {med_info.get('warning', 'ไม่มีข้อมูล')}\n"
                
            reply_msg += "\nระบบจะส่งข้อความแจ้งเตือนเมื่อถึงเวลานะคะ 😊"
            try:
                line_bot_api.push_message(user_id, TextSendMessage(text=reply_msg))
            except Exception as e:
                print("Could not push message:", e)
            
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาส่ง 'ภาพถ่าย' หน้าซองยาหรือใบสั่งแพทย์เพื่อตั้งเวลาแจ้งเตือนนะคะ 💊"))

    return JSONResponse(content={"status": "ok"})
