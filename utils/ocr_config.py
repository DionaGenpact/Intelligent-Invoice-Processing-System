import os
import shutil
import pytesseract

def configure_tesseract():
    cmd = os.getenv("TESSERACT_CMD") or shutil.which("tesseract")
    if not cmd:
        raise EnvironmentError(
            "Tesseract not found. Set TESSERACT_CMD or add tesseract to PATH."
        )
    pytesseract.pytesseract.tesseract_cmd = cmd
    return cmd