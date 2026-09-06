import numpy as np
import cv2
from rapidocr_onnxruntime import RapidOCR

_engine = RapidOCR()

def ocr_image(data: bytes) -> str:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    result, _ = _engine(img)
    if not result:
        return ""
    return "\n".join(line[1] for line in result)
