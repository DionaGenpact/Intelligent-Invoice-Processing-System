import os
import shutil
import pytesseract

def configure_tesseract():
    cmd = os.getenv("TESSERACT_CMD") or shutil.which("tesseract")

    if not cmd:
        cmd = r"C:\Users\602000840\Desktop\Tesseract-OCR\tesseract.exe"

    pytesseract.pytesseract.tesseract_cmd = cmd
    return cmd