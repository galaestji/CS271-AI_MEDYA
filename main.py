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
from linebot.models import MessageEvent, ImageMessage, TextMessage, TextSendMessage, PostbackEvent, FlexSendMessage

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

def create_simple_flex(text: str, title: str = "แจ้งเตือน", color: str = "#4CB0A0") -> FlexSendMessage:
    return FlexSendMessage(
        alt_text=text[:40] + "...",
        contents={
            "type": "bubble",
            "header": { "type": "box", "layout": "vertical", "backgroundColor": color, "paddingAll": "15px", "contents": [ { "type": "text", "text": title, "weight": "bold", "color": "#FFFFFF", "size": "lg" } ] },
            "body": { "type": "box", "layout": "vertical", "paddingAll": "20px", "contents": [ { "type": "text", "text": text, "size": "md", "color": "#333333", "wrap": True } ] }
        }
    )

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
        user_id = event.source.user_id

        if isinstance(event, PostbackEvent):
            data = event.postback.data
            if data.startswith("log_action="):
                parts = data.split("&")
                action = parts[0].split("=")[1]  # TAKEN or SKIPPED
                log_id = int(parts[1].split("=")[1])
                
                db = SessionLocal()
                try:
                    from database import MedicationLog # local import to avoid circular if any, or just use it
                    log = db.query(MedicationLog).filter(MedicationLog.id == log_id).first()
                    if log:
                        if log.status != "WAITING":
                            line_bot_api.reply_message(event.reply_token, create_simple_flex("รายการนี้ถูกบันทึกไปแล้วค่ะ ✅", "ตรวจสอบแล้ว"))
                        else:
                            log.status = "TAKEN" if action == "TAKEN" else "MISSED"
                            from datetime import datetime
                            log.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            if action == "TAKEN":
                                med = db.query(Medication).filter(Medication.id == log.medication_id).first()
                                if med and med.pills_left is not None:
                                    med.pills_left -= med.pills_per_dose
                                    if med.pills_left < 0: med.pills_left = 0
                            db.commit()
                            reply_text = "✅ บันทึกว่า 'ทานยาแล้ว' เรียบร้อยค่ะ" if action == "TAKEN" else "⚠️ บันทึกว่า 'ลืม/ข้ามการทานยา' เรียบร้อยค่ะ"
                            line_bot_api.reply_message(event.reply_token, create_simple_flex(reply_text, "บันทึกสำเร็จ"))
                except Exception as e:
                    print(e)
                finally:
                    db.close()
            continue
            
        if not isinstance(event, MessageEvent):
            continue
            
        if isinstance(event.message, TextMessage):
            user_text = event.message.text.strip()
            if user_text.lower() == "dev":
                from datetime import datetime
                import pytz
                tz = pytz.timezone('Asia/Bangkok')
                now = datetime.now(tz)
                
                db = SessionLocal()
                try:
                    meds = db.query(Medication).filter(Medication.user_id == user_id, Medication.is_active == True).all()
                    if not meds:
                        line_bot_api.reply_message(event.reply_token, create_simple_flex("ไม่มียาในระบบ ยิงเทสแจ้งเตือนไม่ได้ครับ กรุณาเพิ่มยาก่อน", "Dev Mode", "#E74C3C"))
                    else:
                        from database import MedicationLog
                        bubbles = []
                        for med in meds:
                            log = MedicationLog(
                                user_id=user_id,
                                medication_id=med.id,
                                scheduled_time=now.strftime("%Y-%m-%d %H:%M"),
                                status="WAITING"
                            )
                            db.add(log)
                            db.commit()
                            db.refresh(log)

                            bubbles.append({
                                "type": "bubble",
                                "header": { "type": "box", "layout": "vertical", "backgroundColor": "#F39C12", "paddingAll": "20px", "contents": [ {"type": "text", "text": "🛠️ DEV: ลืมดูเวลาใช่ไหม!", "weight": "bold", "color": "#FFFFFF", "size": "xl"} ] },
                                "body": { "type": "box", "layout": "vertical", "paddingAll": "20px", "contents": [
                                    {"type": "text", "text": med.med_name, "weight": "bold", "size": "xxl", "color": "#333333", "wrap": True},
                                    {"type": "text", "text": f"วิธีใช้: {med.dosage}", "size": "md", "color": "#666666", "wrap": True, "margin": "md"},
                                    {"type": "text", "text": "กรุณากดยืนยันการทานยาภายใน 10 นาที", "size": "sm", "color": "#aaaaaa", "margin": "xl", "wrap": True}
                                ]},
                                "footer": { "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "20px", "contents": [
                                    {"type": "button", "style": "primary", "color": "#4CB0A0", "action": {"type": "postback", "label": "✅ ทานยาเรียบร้อย", "data": f"log_action=TAKEN&id={log.id}", "displayText": "ทานแล้ว"}},
                                    {"type": "button", "style": "secondary", "action": {"type": "postback", "label": "❌ เลื่อน/ยังไม่ทาน", "data": f"log_action=SKIPPED&id={log.id}", "displayText": "ยังไม่ทาน"}}
                                ]}
                            })
                            
                        contents = bubbles[0] if len(bubbles) == 1 else {"type": "carousel", "contents": bubbles[:12]}
                        flex_message = FlexSendMessage(alt_text='[DEV] ถึงเวลาทานยาแล้วค่ะ!', contents=contents)
                        line_bot_api.reply_message(event.reply_token, flex_message)
                finally:
                    db.close()
            elif user_text == "เพิ่มยาใหม่":
                flex_msg = FlexSendMessage(
                    alt_text="เพิ่มยาใหม่",
                    contents={
                        "type": "bubble",
                        "header": { "type": "box", "layout": "vertical", "backgroundColor": "#4CB0A0", "paddingAll": "15px", "contents": [ { "type": "text", "text": "เพิ่มยาใหม่", "weight": "bold", "color": "#FFFFFF", "size": "lg" } ] },
                        "body": { "type": "box", "layout": "vertical", "paddingAll": "20px", "contents": [ { "type": "text", "text": "กรุณาส่ง 'ภาพถ่าย' หน้าซองยาหรือใบสั่งแพทย์มาได้เลยค่ะ 📸", "size": "md", "color": "#333333", "wrap": True } ] },
                        "footer": { "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "20px", "contents": [
                            {"type": "button", "style": "primary", "color": "#4CB0A0", "action": {"type": "message", "label": "✍️ พิมพ์ข้อมูลยาเอง", "text": "เพิ่มยาด้วยการพิมพ์"}}
                        ]}
                    }
                )
                line_bot_api.reply_message(event.reply_token, flex_msg)
            elif user_text == "เพิ่มยาด้วยการพิมพ์":
                reply_text = "--- แบบฟอร์มเพิ่มยา ---\n💊 ชื่อยา: \n📝 วิธีใช้: \n📦 จำนวนทั้งหมด(เม็ด): \n⏰ เวลาเตือน(เช่น 08:00):"
                reply_msg = "ก๊อปปี้ข้อความด้านล่างนี้ไปเติมคำในช่องว่าง แล้วส่งกลับมาเพื่อให้ระบบบันทึกได้เลยค่ะ 👇"
                line_bot_api.reply_message(event.reply_token, [
                    TextSendMessage(text=reply_msg),
                    TextSendMessage(text=reply_text)
                ])
            elif user_text.startswith("--- แบบฟอร์มเพิ่มยา ---"):
                lines = user_text.split('\n')
                med_name, dosage, total_pills, times_str = "ไม่ทราบชื่อ", "ไม่ระบุ", None, ""
                
                for line in lines:
                    line = line.strip()
                    if "ชื่อยา:" in line: med_name = line.split(":", 1)[-1].strip()
                    elif "วิธีใช้:" in line: dosage = line.split(":", 1)[-1].strip()
                    elif "จำนวนทั้งหมด" in line:
                        val = line.split(":", 1)[-1].strip()
                        try: total_pills = int(val)
                        except: pass
                    elif "เวลาเตือน" in line: times_str = line.split(":", 1)[-1].strip()
                
                if not med_name or med_name == "ไม่ทราบชื่อ":
                    line_bot_api.reply_message(event.reply_token, create_simple_flex("กรุณากรอกชื่อยาด้วยค่ะ", "ข้อผิดพลาด", "#E74C3C"))
                    continue
                    
                db = SessionLocal()
                try:
                    new_med = Medication(
                        user_id=user_id, med_name=med_name, dosage=dosage,
                        time_to_take=times_str, total_pills=total_pills,
                        pills_left=total_pills, pills_per_dose=1
                    )
                    db.add(new_med)
                    db.commit()
                finally:
                    db.close()
                
                pills_str = f"{total_pills} เม็ด" if total_pills else "ไม่ระบุ"
                body_contents = [
                    {"type": "text", "text": med_name, "weight": "bold", "size": "xl", "color": "#333333", "wrap": True},
                    {"type": "text", "text": f"วิธีใช้: {dosage}", "size": "md", "color": "#666666", "wrap": True, "margin": "md"},
                    {"type": "text", "text": f"จำนวนทั้งหมด: {pills_str}", "size": "sm", "color": "#666666", "wrap": True, "margin": "md"},
                    {"type": "text", "text": f"แจ้งเตือน: {times_str}", "size": "md", "color": "#4CB0A0", "weight": "bold", "margin": "md"}
                ]
                flex_message = FlexSendMessage(
                    alt_text="บันทึกข้อมูลยาสำเร็จ",
                    contents={
                        "type": "bubble",
                        "header": { "type": "box", "layout": "vertical", "backgroundColor": "#4CB0A0", "paddingAll": "20px", "contents": [ {"type": "text", "text": "✅ บันทึกยาสำเร็จ", "weight": "bold", "color": "#FFFFFF", "size": "xl"} ] },
                        "body": { "type": "box", "layout": "vertical", "paddingAll": "20px", "contents": body_contents }
                    }
                )
                line_bot_api.reply_message(event.reply_token, flex_message)
            elif user_text == "ดูยาทั้งหมด":
                db = SessionLocal()
                meds = db.query(Medication).filter(Medication.user_id == user_id, Medication.is_active == True).all()
                if not meds:
                    line_bot_api.reply_message(event.reply_token, create_simple_flex("คุณยังไม่มียาที่ต้องทานในระบบค่ะ ❌", "ไม่มีข้อมูล", "#E74C3C"))
                else:
                    med_boxes = []
                    for m in meds:
                        pills_text = f"เหลือ {m.pills_left} เม็ด" if m.pills_left is not None else "ไม่ได้ระบุจำนวน"
                        pill_color = "#E74C3C" if (m.pills_left is not None and m.pills_left < 5) else "#666666"
                        med_boxes.append({
                            "type": "box",
                            "layout": "horizontal",
                            "margin": "md",
                            "contents": [
                                { "type": "text", "text": f"• {m.med_name}", "size": "sm", "color": "#333333", "flex": 2, "wrap": True },
                                { "type": "text", "text": pills_text, "size": "sm", "color": pill_color, "align": "end", "flex": 1 }
                            ]
                        })
                    flex_msg = FlexSendMessage(
                        alt_text="รายการยาทั้งหมดของคุณ",
                        contents={
                            "type": "bubble",
                            "header": { "type": "box", "layout": "vertical", "backgroundColor": "#4CB0A0", "paddingAll": "20px", "contents": [ {"type": "text", "text": "💊 สต๊อกยาทั้งหมด", "color": "#FFFFFF", "weight": "bold", "size": "xl"} ] },
                            "body": { "type": "box", "layout": "vertical", "paddingAll": "20px", "contents": med_boxes }
                        }
                    )
                    line_bot_api.reply_message(event.reply_token, flex_msg)
                db.close()
            elif user_text == "ดูประวัติการทานยา":
                from database import MedicationLog
                db = SessionLocal()
                logs_query = db.query(MedicationLog).filter(MedicationLog.user_id == user_id).order_by(MedicationLog.id.desc()).limit(15).all()
                logs = list(reversed(logs_query))
                if not logs:
                    line_bot_api.reply_message(event.reply_token, create_simple_flex("ยังไม่มีประวัติการแจ้งเตือนค่ะ ❌", "ไม่มีข้อมูล", "#E74C3C"))
                else:
                    log_boxes = []
                    med_dict = {m.id: m.med_name for m in db.query(Medication).filter(Medication.user_id == user_id).all()}
                    for log in logs:
                        status_str = "✅ ทานแล้ว" if log.status == "TAKEN" else "❌ ลืมทาน" if log.status == "MISSED" else "⏳ รอการยืนยัน"
                        color_str = "#4CB0A0" if log.status == "TAKEN" else "#E74C3C" if log.status == "MISSED" else "#F39C12"
                        m_name = med_dict.get(log.medication_id, "ไม่ทราบชื่อ")
                        log_boxes.append({
                            "type": "box", "layout": "vertical", "margin": "md", "paddingAll": "13px", "backgroundColor": "#F4F6F6", "cornerRadius": "8px",
                            "contents": [
                                { "type": "text", "text": m_name, "size": "md", "weight": "bold", "color": "#333333", "wrap": True },
                                { 
                                    "type": "box", "layout": "horizontal", "margin": "sm",
                                    "contents": [
                                        { "type": "text", "text": log.scheduled_time, "size": "xs", "color": "#aaaaaa" },
                                        { "type": "text", "text": status_str, "size": "xs", "color": color_str, "align": "end", "weight": "bold" }
                                    ]
                                }
                            ]
                        })
                    flex_msg = FlexSendMessage(
                        alt_text="ประวัติการทานยาล่าสุด",
                        contents={
                            "type": "bubble",
                            "header": { "type": "box", "layout": "vertical", "backgroundColor": "#4CB0A0", "paddingAll": "20px", "contents": [ {"type": "text", "text": "📅 ประวัติล่าสุด", "color": "#FFFFFF", "weight": "bold", "size": "xl"} ] },
                            "body": { "type": "box", "layout": "vertical", "paddingAll": "20px", "contents": log_boxes }
                        }
                    )
                    line_bot_api.reply_message(event.reply_token, flex_msg)
                db.close()
            else:
                line_bot_api.reply_message(event.reply_token, create_simple_flex("กรุณาเลือกเมนูที่ต้องการ หรือส่งภาพหน้าซองยาค่ะ", "ช่วยเหลือ", "#F39C12"))
                
        elif isinstance(event.message, ImageMessage):
            # Reply acknowledging receipt
            line_bot_api.reply_message(event.reply_token, create_simple_flex("กำลังประมวลผลคำสั่งและอ่านฉลากยาด้วย AI... กรุณารอสักครู่นะคะ ⏳", "กำลังประมวลผล", "#F39C12"))
            
            # 1. Download Image from Line
            message_content = line_bot_api.get_message_content(event.message.id)
            image_bytes = b"".join(message_content.iter_content())
            
            # 2. Extract Text with OCR
            text = extract_text_from_image(image_bytes)
            if not text:
                msg = "❌ ถ่ายภาพไม่เห็นตัวหนังสือเลยค่ะ\n\nอาจเป็นเพราะแสงสะท้อน เบลอเกินไป หรือในรูปไม่มีตัวอักษร รบกวนถ่ายรูปหน้า 'ฉลากยา' ชัดๆ อีกครั้งนะคะ"
                line_bot_api.push_message(user_id, create_simple_flex(msg, "อ่านข้อความไม่ได้", "#E74C3C"))
                continue
                
            # 3. Parse Text with LLM
            parsed_data = parse_medication_text(text)
            if not parsed_data:
                line_bot_api.push_message(user_id, create_simple_flex("ระบบเซิร์ฟเวอร์ AI มีปัญหาเล็กน้อย ลองส่งใหม่อีกครั้งนะคะ", "ข้อผิดพลาดระบบ", "#E74C3C"))
                continue
                
            med_name = parsed_data.get("med_name")
            if not med_name or str(med_name).strip() == "" or str(med_name).lower() == "null" or med_name == "ไม่ทราบชื่อยา":
                msg = "❌ ไม่พบข้อมูลยาในภาพนี้\n\nระบบ AI ประเมินว่าภาพนี้น่าจะไม่ใช่ฉลากยา (เช่น ถ่ายติดใบกระดาษเปล่า, สลิปโอนเงิน) หรือภาพอาจจะเบลอเกินไป เพื่อป้องกันความผิดพลาด กรุณาตั้งกล้องให้ขนานกับใบสั่งยาและถ่ายใหม่อีกครั้งค่ะ"
                line_bot_api.push_message(user_id, create_simple_flex(msg, "ไม่พบร่องรอยฉลากยา", "#E74C3C"))
                continue
            std_med_name = parsed_data.get("std_med_name", None)
            dosage = parsed_data.get("dosage", "ไม่ทราบวิธีใช้")
            times = parsed_data.get("times", [])
            pills_per_dose = parsed_data.get("pills_per_dose", 1)
            total_pills = parsed_data.get("total_pills", None)
            
            # 4. Save to Database
            times_str = ", ".join(times) if times else "ไม่ได้ระบุเวลา"
            db = SessionLocal()
            try:
                new_med = Medication(
                    user_id=user_id,
                    med_name=med_name,
                    dosage=dosage,
                    time_to_take=times_str,
                    total_pills=total_pills,
                    pills_left=total_pills,
                    pills_per_dose=pills_per_dose
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

            pills_str = f"{total_pills} เม็ด" if total_pills else "ไม่ระบุ"
            
            body_contents = [
                {"type": "text", "text": med_name, "weight": "bold", "size": "xl", "color": "#333333", "wrap": True},
                {"type": "text", "text": f"วิธีใช้: {dosage}", "size": "md", "color": "#666666", "wrap": True, "margin": "md"},
                {"type": "text", "text": f"จำนวนทั้งหมด: {pills_str}", "size": "sm", "color": "#666666", "wrap": True, "margin": "md"},
                {"type": "text", "text": f"แจ้งเตือน: {times_str}", "size": "md", "color": "#4CB0A0", "weight": "bold", "margin": "md"}
            ]
            
            if med_info:
                body_contents.append({
                    "type": "box", "layout": "vertical", "margin": "xl", "spacing": "sm", "paddingAll": "13px", "backgroundColor": "#FFF9C4", "cornerRadius": "8px",
                    "contents": [
                        {"type": "text", "text": "💡 สรรพคุณ", "size": "sm", "color": "#F39C12", "weight": "bold"},
                        {"type": "text", "text": med_info.get('usage', 'ไม่มีข้อมูล'), "size": "xs", "color": "#666666", "wrap": True},
                        {"type": "text", "text": "⚠️ ข้อควรระวัง", "size": "sm", "color": "#E74C3C", "weight": "bold", "margin": "md"},
                        {"type": "text", "text": med_info.get('warning', 'ไม่มีข้อควรระวังพิเศษ'), "size": "xs", "color": "#666666", "wrap": True}
                    ]
                })

            flex_message = FlexSendMessage(
                alt_text="บันทึกข้อมูลยาสำเร็จ",
                contents={
                    "type": "bubble",
                    "header": { "type": "box", "layout": "vertical", "backgroundColor": "#4CB0A0", "paddingAll": "20px", "contents": [ {"type": "text", "text": "✅ บันทึกยาสำเร็จ", "weight": "bold", "color": "#FFFFFF", "size": "xl"} ] },
                    "body": { "type": "box", "layout": "vertical", "paddingAll": "20px", "contents": body_contents }
                }
            )
            try:
                line_bot_api.push_message(user_id, flex_message)
            except Exception as e:
                print("Could not push message:", e)
            
    return JSONResponse(content={"status": "ok"})
