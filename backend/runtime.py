"""Where bundled files and writable data live, both from source and from the packaged app."""
import os
import sys
from typing import Optional

FROZEN = getattr(sys, "frozen", False)

# Folder holding the project files (static/, OCR models): inside the bundle when packaged
RESOURCE_DIR = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Writable folder (profiles/, data/): next to the .exe when packaged, the project folder otherwise
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
)


def installed_chrome() -> Optional[str]:
    return next((p for p in _CHROME_PATHS if os.path.exists(p)), None)


def ocr_model_dir() -> Optional[str]:
    """OCR models shipped with the packaged app, so no download is needed on first use."""
    path = os.path.join(RESOURCE_DIR, "easyocr_models")
    return path if os.path.isdir(path) else None
