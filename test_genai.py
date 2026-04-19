import os
from dotenv import load_dotenv
load_dotenv()
from google import genai
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
try:
    response = client.models.generate_content(model='gemini-1.5-flash', contents='hi')
    print("SUCCESS 1.5:", response.text)
except Exception as e:
    print("FAILED 1.5:", e)
