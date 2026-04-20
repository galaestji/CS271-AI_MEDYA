import os
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from database import SessionLocal, Medication, UserProfile
from ocr_engine import extract_text_from_image
from llm_parser import parse_medication_text
from scheduler import start_scheduler

from linebot import LineBotApi, WebhookParser
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, ImageMessage, TextMessage, TextSendMessage, PostbackEvent, FlexSendMessage, FollowEvent

load_dotenv()

app = FastAPI(title="Medication Reminder Bot")
app.mount("/static", StaticFiles(directory="static"), name="static")

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

@app.get("/profile", response_class=HTMLResponse)
async def get_profile_form(user_id: str = ""):
    html_content = f"""
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>บันทึกประวัติทางการแพทย์</title>
        <style>
            body {{ font-family: 'Sarabun', sans-serif; background-color: #f4f6f9; display: flex; justify-content: center; padding: 20px; }}
            .container {{ background: white; padding: 30px; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); width: 100%; max-width: 400px; margin-top: 20px; }}
            h2 {{ color: #4CB0A0; text-align: center; margin-bottom: 20px; font-weight: bold; }}
            label {{ font-weight: bold; color: #555; display: block; margin-top: 15px; font-size: 14px; }}
            input, select, textarea {{ width: 100%; padding: 12px; margin-top: 5px; border: 1px solid #ccc; border-radius: 8px; box-sizing: border-box; font-size: 16px; background-color: #FAFAFA; }}
            input:focus, textarea:focus, select:focus {{ border-color: #4CB0A0; outline: none; box-shadow: 0 0 5px rgba(76, 176, 160, 0.4); background-color: #FFF; }}
            button {{ background-color: #4CB0A0; color: white; border: none; padding: 15px; width: 100%; border-radius: 8px; font-size: 18px; font-weight: bold; margin-top: 25px; cursor: pointer; transition: background 0.3s; box-shadow: 0 4px 6px rgba(76, 176, 160, 0.3); }}
            button:hover {{ background-color: #3b8e81; transform: translateY(-1px); }}
        </style>
        <link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;700&display=swap" rel="stylesheet">
    </head>
    <body>
        <div class="container">
            <h2>📝 ข้อมูลแพทย์ประจำตัว</h2>
            <form action="/profile" method="post">
                <input type="hidden" name="user_id" value="{user_id}">
                
                <label>ชื่อ-นามสกุล / ชื่อเล่น</label>
                <input type="text" name="name" required placeholder="เช่น น้องขุนทอง">

                <div style="display: flex; gap: 10px;">
                    <div style="flex: 1;">
                        <label>อายุ (ปี)</label>
                        <input type="number" name="age" required placeholder="เช่น 25">
                    </div>
                    <div style="flex: 1;">
                        <label>เพศ</label>
                        <select name="gender">
                            <option value="ชาย">ชาย</option>
                            <option value="หญิง">หญิง</option>
                            <option value="อื่นๆ">อื่นๆ</option>
                        </select>
                    </div>
                </div>

                <div style="display: flex; gap: 10px;">
                    <div style="flex: 1;">
                        <label>น้ำหนัก (กก.)</label>
                        <input type="number" step="0.1" name="weight" placeholder="0.0">
                    </div>
                    <div style="flex: 1;">
                        <label>ส่วนสูง (ซม.)</label>
                        <input type="number" name="height" placeholder="0">
                    </div>
                </div>

                <label>โรคประจำตัว (ถ้ามี)</label>
                <input type="text" name="sickness" placeholder="เช่น ความดัน, เบาหวาน (ถ้าไม่มีเว้นว่าง)">

                <label>ประวัติการแพ้ยา (ถ้ามี)</label>
                <textarea name="allergies" rows="2" placeholder="เช่น แพ้เพนิซิลลิน, อาหารทะเล (ถ้าไม่มีเว้นว่าง)"></textarea>

                <button type="submit">บันทึกข้อมูลส่วนตัว</button>
            </form>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/profile", response_class=HTMLResponse)
async def post_profile(
    user_id: str = Form(...),
    name: str = Form(""),
    age: int = Form(None),
    gender: str = Form(""),
    weight: str = Form(""),
    height: str = Form(""),
    sickness: str = Form(""),
    allergies: str = Form("")
):
    db = SessionLocal()
    try:
        profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        if not profile:
            profile = UserProfile(user_id=user_id)
            db.add(profile)
        
        profile.name = name
        profile.age = age
        profile.gender = gender
        profile.weight = weight
        profile.height = height
        profile.sickness = sickness
        profile.allergies = allergies
        
        db.commit()
    finally:
        db.close()
        
    html_content = """
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>บันทึกสำเร็จ</title>
        <link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;700&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Sarabun', sans-serif; background-color: #4CB0A0; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
            .container { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 10px 25px rgba(0,0,0,0.2); text-align: center; width: 80%; max-width: 350px; }
            h2 { color: #4CB0A0; font-weight: bold; margin-bottom: 5px; }
            p { font-size: 16px; color: #666; margin-bottom: 25px; }
            .icon { font-size: 60px; margin-bottom: 15px; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">✨</div>
            <h2>บันทึกข้อมูลสำเร็จ!</h2>
            <p>ประวัติทางการแพทย์ของคุณถูกเก็บรักษาอย่างปลอดภัย</p>
            <p style="font-weight: bold; color: #333; margin-top: 20px;">กรุณากดปิดหน้านี้ แล้วกลับไปยังแชท LINE เพื่อใช้งานต่อได้เลยค่ะ 😄</p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ─────────────── Add Medication HTML Form ───────────────
CSS_SHARED = """
    body { font-family: 'Sarabun', sans-serif; background: #f4f6f9; display: flex; justify-content: center; padding: 20px; min-height: 100vh; margin: 0; box-sizing: border-box; }
    .container { background: white; padding: 28px; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); width: 100%; max-width: 420px; margin-top: 16px; }
    h2 { color: #4CB0A0; text-align: center; margin-bottom: 18px; font-weight: bold; font-size: 1.3rem; }
    label { font-weight: bold; color: #555; display: block; margin-top: 14px; font-size: 13px; }
    input, select, textarea { width: 100%; padding: 11px; margin-top: 5px; border: 1px solid #ccc; border-radius: 8px; box-sizing: border-box; font-size: 15px; background: #FAFAFA; font-family: 'Sarabun', sans-serif; }
    input:focus, textarea:focus, select:focus { border-color: #4CB0A0; outline: none; box-shadow: 0 0 5px rgba(76,176,160,0.4); background: #FFF; }
    .btn-primary { background-color: #4CB0A0; color: white; border: none; padding: 14px; width: 100%; border-radius: 8px; font-size: 17px; font-weight: bold; margin-top: 22px; cursor: pointer; transition: background 0.2s, transform 0.1s; box-shadow: 0 4px 6px rgba(76,176,160,0.3); display: block; text-align: center; }
    .btn-primary:hover { background-color: #3b8e81; transform: translateY(-1px); }
    .btn-danger { background-color: #E74C3C; color: white; border: none; padding: 14px; width: 100%; border-radius: 8px; font-size: 17px; font-weight: bold; margin-top: 10px; cursor: pointer; transition: background 0.2s; }
    .btn-danger:hover { background-color: #c0392b; }
    .hint { font-size: 12px; color: #999; margin-top: 4px; }
    .success-page { font-family: 'Sarabun', sans-serif; background: #4CB0A0; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
    .success-box { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 10px 25px rgba(0,0,0,0.2); text-align: center; width: 80%; max-width: 350px; }
    .success-box h2 { color: #4CB0A0; } .success-box .icon { font-size: 56px; margin-bottom: 12px; }
"""
GOOGLE_FONT = '<link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@400;700&display=swap" rel="stylesheet">'

@app.get("/add-med", response_class=HTMLResponse)
async def get_add_med_form(user_id: str = ""):
    html = f"""
    <!DOCTYPE html><html lang="th"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>เพิ่มยาใหม่ - MED-YA</title><style>{CSS_SHARED}</style>{GOOGLE_FONT}</head>
    <body><div class="container">
        <h2>💊 เพิ่มข้อมูลยาใหม่</h2>
        <form action="/add-med" method="post">
            <input type="hidden" name="user_id" value="{user_id}">
            <label>ชื่อยา *</label>
            <input type="text" name="med_name" required placeholder="เช่น Amoxicillin, ยาพาราเซตามอล">
            <label>วิธีใช้ / ขนาดยา *</label>
            <input type="text" name="dosage" required placeholder="เช่น กินหลังอาหาร 1 เม็ด">
            <label>จำนวนเม็ดต่อครั้ง</label>
            <input type="number" name="pills_per_dose" value="1" min="1" placeholder="1">
            <label>จำนวนยาทั้งหมด (เม็ด)</label>
            <input type="number" name="total_pills" placeholder="เช่น 30 (เว้นว่างถ้าไม่ทราบ)">
            <label>เวลาแจ้งเตือน *</label>
            <input type="text" name="time_to_take" required placeholder="เช่น 08:00, 12:00, 20:00">
            <p class="hint">⏰ ใส่หลายเวลาได้โดยคั่นด้วยเครื่องหมาย , (comma)</p>
            <button class="btn-primary" type="submit">💾 บันทึกยา</button>
        </form>
    </div></body></html>
    """
    return HTMLResponse(content=html)

@app.post("/add-med", response_class=HTMLResponse)
async def post_add_med(
    user_id: str = Form(...),
    med_name: str = Form(...),
    dosage: str = Form(""),
    pills_per_dose: int = Form(1),
    total_pills: str = Form(""),
    time_to_take: str = Form("")
):
    total = int(total_pills) if total_pills.strip().isdigit() else None
    db = SessionLocal()
    try:
        new_med = Medication(
            user_id=user_id, med_name=med_name, dosage=dosage,
            time_to_take=time_to_take, total_pills=total,
            pills_left=total, pills_per_dose=pills_per_dose
        )
        db.add(new_med)
        db.commit()
    finally:
        db.close()
    html = f"""
    <!DOCTYPE html><html lang="th"><head><meta charset="UTF-8"><style>{CSS_SHARED}</style>{GOOGLE_FONT}</head>
    <body class="success-page"><div class="success-box">
        <div class="icon">✅</div><h2>บันทึกยาสำเร็จ!</h2>
        <p>ยา <strong>{med_name}</strong> ถูกเพิ่มเข้าระบบแล้วค่ะ</p>
        <p style="color:#777; margin-top:16px;">ปิดหน้านี้แล้วกลับสู่แชท LINE ได้เลยค่ะ 😊</p>
    </div></body></html>
    """
    return HTMLResponse(content=html)

# ─────────────── Edit Medication HTML Form ───────────────
@app.get("/edit-med", response_class=HTMLResponse)
async def get_edit_med_form(med_id: int = 0, user_id: str = ""):
    db = SessionLocal()
    med = db.query(Medication).filter(Medication.id == med_id, Medication.user_id == user_id).first()
    db.close()
    if not med:
        return HTMLResponse(content="<h3>ไม่พบข้อมูลยานี้</h3>", status_code=404)
    html = f"""
    <!DOCTYPE html><html lang="th"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>แก้ไขข้อมูลยา - MED-YA</title><style>{CSS_SHARED}</style>{GOOGLE_FONT}</head>
    <body><div class="container">
        <h2>✏️ แก้ไขข้อมูลยา</h2>
        <form action="/edit-med" method="post">
            <input type="hidden" name="med_id" value="{med.id}">
            <input type="hidden" name="user_id" value="{user_id}">
            <label>ชื่อยา *</label>
            <input type="text" name="med_name" required value="{med.med_name}">
            <label>วิธีใช้ / ขนาดยา</label>
            <input type="text" name="dosage" value="{med.dosage or ''}">
            <label>จำนวนเม็ดต่อครั้ง</label>
            <input type="number" name="pills_per_dose" value="{med.pills_per_dose or 1}" min="1">
            <label>จำนวนยาที่เหลือ (เม็ด)</label>
            <input type="number" name="pills_left" value="{med.pills_left if med.pills_left is not None else ''}" placeholder="เว้นว่างถ้าไม่ทราบ">
            <label>เวลาแจ้งเตือน</label>
            <input type="text" name="time_to_take" value="{med.time_to_take or ''}" placeholder="เช่น 08:00, 20:00">
            <p class="hint">⏰ คั่นหลายเวลาด้วยเครื่องหมาย , (comma)</p>
            <button class="btn-primary" type="submit">💾 บันทึกการแก้ไข</button>
        </form>
    </div></body></html>
    """
    return HTMLResponse(content=html)

@app.post("/edit-med", response_class=HTMLResponse)
async def post_edit_med(
    med_id: int = Form(...),
    user_id: str = Form(...),
    med_name: str = Form(...),
    dosage: str = Form(""),
    pills_per_dose: int = Form(1),
    pills_left: str = Form(""),
    time_to_take: str = Form("")
):
    db = SessionLocal()
    try:
        med = db.query(Medication).filter(Medication.id == med_id, Medication.user_id == user_id).first()
        if med:
            med.med_name = med_name
            med.dosage = dosage
            med.pills_per_dose = pills_per_dose
            med.pills_left = int(pills_left) if pills_left.strip().isdigit() else None
            med.time_to_take = time_to_take
            db.commit()
    finally:
        db.close()
    html = f"""
    <!DOCTYPE html><html lang="th"><head><meta charset="UTF-8"><style>{CSS_SHARED}</style>{GOOGLE_FONT}</head>
    <body class="success-page"><div class="success-box">
        <div class="icon">✏️</div><h2>แก้ไขข้อมูลสำเร็จ!</h2>
        <p>อัปเดตข้อมูลยา <strong>{med_name}</strong> เรียบร้อยแล้วค่ะ</p>
        <p style="color:#777; margin-top:16px;">ปิดหน้านี้แล้วกลับสู่แชท LINE ได้เลยค่ะ 😊</p>
    </div></body></html>
    """
    return HTMLResponse(content=html)

@app.get("/delete-med", response_class=HTMLResponse)
async def delete_med(med_id: int = 0, user_id: str = ""):
    db = SessionLocal()
    try:
        med = db.query(Medication).filter(Medication.id == med_id, Medication.user_id == user_id).first()
        med_name = med.med_name if med else "ไม่พบ"
        if med:
            med.is_active = False  # soft delete
            db.commit()
    finally:
        db.close()
    html = f"""
    <!DOCTYPE html><html lang="th"><head><meta charset="UTF-8"><style>{CSS_SHARED}</style>{GOOGLE_FONT}</head>
    <body class="success-page"><div class="success-box">
        <div class="icon">🗑️</div><h2>ลบยาสำเร็จ!</h2>
        <p>ยา <strong>{med_name}</strong> ถูกลบออกจากระบบแล้วค่ะ</p>
        <p style="color:#777; margin-top:16px;">ปิดหน้านี้แล้วกลับสู่แชท LINE ได้เลยค่ะ 😊</p>
    </div></body></html>
    """
    return HTMLResponse(content=html)

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
            
        if isinstance(event, FollowEvent):
            user_id = event.source.user_id
            try:
                profile = line_bot_api.get_profile(user_id)
                display_name = profile.display_name
            except:
                display_name = "ผู้ใช้งาน"

            base_url = str(request.base_url).rstrip("/")
            img_url = f"{base_url}/static/doctor.png"
            
            welcome_flex = FlexSendMessage(
                alt_text="MED-YA คุณหมอมาแล้ว ยินดีต้อนรับครับ!",
                contents={
                    "type": "bubble",
                    "body": {
                        "type": "box", "layout": "vertical", "paddingAll": "0px",
                        "contents": [
                            {
                                "type": "box", "layout": "horizontal", "paddingAll": "20px", "paddingBottom": "10px",
                                "contents": [
                                    {
                                        "type": "box", "layout": "vertical", "flex": 2, "justifyContent": "center",
                                        "contents": [
                                            {"type": "text", "text": "สวัสดีครับ", "weight": "bold", "size": "xl", "color": "#333333"},
                                            {"type": "text", "text": "MED-YA คุณหมอมาแล้ว", "weight": "bold", "size": "sm", "color": "#4CB0A0", "margin": "sm"}
                                        ]
                                    },
                                    {
                                        "type": "box", "layout": "vertical", "flex": 1, "alignItems": "flex-end",
                                        "contents": [
                                            {"type": "image", "url": img_url, "size": "full", "aspectMode": "cover", "aspectRatio": "1:1", "gravity": "top"}
                                        ]
                                    }
                                ]
                            },
                            {
                                "type": "box", "layout": "vertical", "paddingAll": "20px", "paddingTop": "10px",
                                "contents": [
                                    {"type": "text", "text": f"ยินดีที่ได้รู้จักคุณ {display_name}", "weight": "bold", "size": "md", "color": "#333333", "wrap": True},
                                    {"type": "text", "text": "น้องหมอเม็ดยายินดีให้บริการครับ\nน้องหมอจะช่วยคุณให้กินยาให้ตรงเวลา จะได้ไม่โดนพี่หมอดุ", "size": "sm", "color": "#666666", "wrap": True, "margin": "lg"},
                                    {"type": "text", "text": "อันดับแรก ปฏิบัติตามขั้นตอนนี้เพื่อใช้งานน้องหมอเม็ดยาเลย", "size": "sm", "color": "#333333", "wrap": True, "margin": "xl", "weight": "bold"},
                                    {
                                        "type": "box", "layout": "vertical", "margin": "md", "spacing": "sm",
                                        "contents": [
                                            {"type": "text", "text": "• 1. กรอกข้อมูลส่วนตัวทางการแพทย์", "size": "sm", "color": "#666666", "wrap": True},
                                            {"type": "text", "text": "• 2. ถ่ายรูปยาที่ต้องทาน", "size": "sm", "color": "#666666", "wrap": True},
                                            {"type": "text", "text": "• 3. ตรวจสอบข้อมูล", "size": "sm", "color": "#666666", "wrap": True},
                                            {"type": "text", "text": "• 4. นอนสวยๆรอน้องหมอปลุกกินยาได้เลย", "size": "sm", "color": "#666666", "wrap": True}
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    "footer": {
                        "type": "box", "layout": "vertical", "paddingAll": "20px",
                        "contents": [
                            {
                                "type": "button", "style": "primary", "color": "#4CB0A0",
                                "action": { "type": "uri", "label": "เพิ่มประวัติทางการแพทย์", "uri": f"{base_url}/profile?user_id={user_id}" }
                            }
                        ]
                    }
                }
            )
            line_bot_api.reply_message(event.reply_token, welcome_flex)
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
                            {"type": "button", "style": "primary", "color": "#2ECC71", "action": {"type": "uri", "label": "✍️ พิมพ์ข้อมูลยาเอง", "uri": f"{str(request.base_url).rstrip('/')}/add-med?user_id={user_id}"}}
                        ]}
                    }
                )
                line_bot_api.reply_message(event.reply_token, flex_msg)
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
            elif user_text == "แก้ไขข้อมูล":
                db = SessionLocal()
                meds = db.query(Medication).filter(Medication.user_id == user_id, Medication.is_active == True).all()
                db.close()
                base_url = str(request.base_url).rstrip("/")
                if not meds:
                    line_bot_api.reply_message(event.reply_token, create_simple_flex("ยังไม่มียาในระบบที่จะแก้ไขค่ะ ❌", "ไม่มีข้อมูล", "#E74C3C"))
                else:
                    bubbles = []
                    for m in meds:
                        pills_text = f"เหลือ {m.pills_left} เม็ด" if m.pills_left is not None else "ไม่ระบุจำนวน"
                        pill_color = "#E74C3C" if (m.pills_left is not None and m.pills_left < 5) else "#4CB0A0"
                        bubbles.append({
                            "type": "bubble",
                            "header": {
                                "type": "box", "layout": "vertical", "backgroundColor": "#4CB0A0", "paddingAll": "18px",
                                "contents": [{"type": "text", "text": "💊 " + m.med_name, "weight": "bold", "size": "lg", "color": "#FFFFFF", "wrap": True}]
                            },
                            "body": {
                                "type": "box", "layout": "vertical", "paddingAll": "18px", "spacing": "sm",
                                "contents": [
                                    {"type": "text", "text": f"วิธีใช้: {m.dosage or 'ไม่ระบุ'}", "size": "sm", "color": "#555", "wrap": True},
                                    {"type": "text", "text": f"เวลา: {m.time_to_take or 'ไม่ระบุ'}", "size": "sm", "color": "#555", "wrap": True},
                                    {"type": "text", "text": pills_text, "size": "sm", "color": pill_color, "weight": "bold"}
                                ]
                            },
                            "footer": {
                                "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "18px",
                                "contents": [
                                    {"type": "button", "style": "primary", "color": "#F39C12", "height": "sm",
                                     "action": {"type": "uri", "label": "✏️ แก้ไข", "uri": f"{base_url}/edit-med?med_id={m.id}&user_id={user_id}"}},
                                    {"type": "button", "style": "secondary", "height": "sm",
                                     "action": {"type": "uri", "label": "🗑️ ลบยานี้", "uri": f"{base_url}/delete-med?med_id={m.id}&user_id={user_id}"}}
                                ]
                            }
                        })
                    contents = bubbles[0] if len(bubbles) == 1 else {"type": "carousel", "contents": bubbles[:12]}
                    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="จัดการข้อมูลยา", contents=contents))
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
