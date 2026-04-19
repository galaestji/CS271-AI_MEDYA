import easyocr
import cv2
import numpy as np

# Initialize the EasyOCR reader with Thai and English (downloads models on first run)
reader = easyocr.Reader(['th', 'en'], gpu=False)

def extract_text_from_image(image_bytes: bytes) -> str:
    # Convert bytes to numpy array
    nparr = np.frombuffer(image_bytes, np.uint8)
    # Decode image using OpenCV
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is None:
        return ""
    
    # Run EasyOCR
    result = reader.readtext(img, detail=0, paragraph=True)
    
    return "\n".join(result)
