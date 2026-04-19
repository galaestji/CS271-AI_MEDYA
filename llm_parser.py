import os
import json
from google import genai
from dotenv import load_dotenv

load_dotenv()

def parse_medication_text(text: str) -> dict:
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    # Load medicine database to give context to LLM
    try:
        with open("medicine_db.json", "r", encoding="utf-8") as f:
            med_db = json.load(f)
            # Create a simplified string of db for the prompt
            db_context = []
            for item in med_db:
                aliases_str = ", ".join(item.get("aliases", []))
                db_context.append(f"- Name: {item['name']}, Aliases: {aliases_str}")
            db_context_str = "\n    ".join(db_context)
    except Exception as e:
        print(f"Error loading medicine_db.json for prompt: {e}")
        db_context_str = "ไม่พบฐานข้อมูลยา"

    prompt = f"""
    คุณเป็นเภสัชกรผู้เชี่ยวชาญ หน้าที่ของคุณคืออ่านข้อความบนฉลากยาที่ถูกสกัดมาจากโปรแกรมอ่านภาพ (OCR) 
    แล้วสรุปเป็นรูปแบบ JSON ให้ถูกต้อง

    🚨 กฎสำคัญมาก: ข้อความจาก OCR มักจะสะกดผิด, ตัวอักษรตกหล่น, หรือมีตัวอักษรแปลกประหลาดแทรกอยู่ คุณต้องทำหน้าที่ "แก้ไขคำผิดอัตโนมัติ (Auto-Correct)" ทั้งชื่อยาและวิธีใช้ ให้กลับมาเป็นคำศัพท์แพทย์และภาษาไทยที่ถูกต้องสมบูรณ์ ห้ามลอกคำผิดมาจาก OCR อาการเพี้ยนมาเด็ดขาด!
    🚨 ข้อควรระวัง (Human Error Protection): หากข้อความที่สกัดมาดูแล้ว "ไม่ใช่ฉลากยาเลย" (เช่น เป็นใบเสร็จเซเว่น, ป้ายโฆษณา, หรือถ่ายติดแบล็คกราวด์จนตัวหนังสือเละเป็นภาษาต่างดาว) โอกาสที่จะเกิดอันตรายจากการบันทึกยาผิดจะสูงมาก ให้คุณแก้เกมนี้โดยการตั้งค่าฟิลด์ "med_name" เป็น null ทันที เพื่อให้ระบบรู้ว่านี่อ่านไม่ออกหรือเป็นขยะ

    นี่คือฐานข้อมูลยาที่เรามี (รายชื่อยามาตรฐาน และ ชื่อเรียกต่างๆ):
    {db_context_str}

    ข้อความที่สกัดมาจากภาพ (อาจมีคำสะกดผิด):
    {text}

    กรุณาสกัดข้อมูลและตอบกลับเป็น JSON FORMAT เท่านั้น โดยไม่ต้องมี markdown ```json
    หน้าที่ 2: ให้คุณเทียบชื่อยาที่เจอใน OCR กับฐานข้อมูลด้านบน หากพบว่าตรงกับยาตัวไหน (พิจารณาจากชื่อเรียก Aliases ด้วย) ให้ระบุฟิลด์ "std_med_name" เป็นค่า Name มาตรฐานของยานั้นๆ ในฐานข้อมูลของเรา หากไม่ตรงให้ตั้งเป็น null

    รูปแบบที่ต้องการ:
    {{
        "med_name": "ชื่อยาที่สะกดถูกต้องและสมบูรณ์ (string) (ถ้าไม่ใช่ฉลากยา หรือภาพขยะอ่านไม่รู้เรื่อง ให้ใส่ null)",
        "std_med_name": "ชื่อยามาตรฐานตามฐานข้อมูลของเรา (string หรือ null)",
        "dosage": "วิธีใช้ที่สรุปมาอ่านง่ายๆ และสะกดถูกต้อง เช่น ทานครั้งละ 1 เม็ด (string หรือ null)",
        "pills_per_dose": 1, // จำนวนเม็ดยาที่ต้องทานต่อครั้ง (integer) ถ้าไม่แน่ใจให้เป็น 1
        "total_pills": 30, // ปริมาณเม็ดยาทั้งหมดหรือปริมาตรทั้งหมดที่ระบุบนซอง (integer หรือ null ถ้าไม่มีระบุ)
        "times": ["08:00", "12:00", "18:00", "20:00"] // list ของเวลาที่ต้องทานยา (ถ้าในฉลากบอกแค่ เช้า/กลางวัน/เย็น ให้ประเมินเวลาคร่าวๆ เช่น เช้า=08:00, กลางวัน=12:00, เย็น=18:00, ก่อนนอน=20:00) ถ้าไม่มีให้ออกเป็น list ว่าง
    }}
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-flash-latest', 
            contents=prompt
        )
        # Using string matching since response structure might vary
        raw_text = getattr(response, 'text', '')
        if not raw_text and hasattr(response, 'candidates'):
            raw_text = response.candidates[0].content.parts[0].text
        
        raw_text = raw_text.strip()
        
        # Clean markdown if generated
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
            
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
            
        parsed_data = json.loads(raw_text.strip())
        return parsed_data
    except Exception as e:
        print(f"Error parsing with LLM: {e}")
        return None
