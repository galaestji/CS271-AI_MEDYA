import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

for model in ['gemini-1.5-flash', 'gemini-1.5-flash-latest', 'gemini-pro', 'gemini-2.0-flash']:
    try:
        m = genai.GenerativeModel(model)
        r = m.generate_content("hi")
        print(f"{model}: SUCCESS! (reply: {r.text.strip()})")
    except Exception as e:
        print(f"{model}: FAILED - {e}")
