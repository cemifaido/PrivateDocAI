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


# One fixed number of torch threads for the whole process, set on first use by the OCR OR the
# model (whichever comes first) and never changed again: torch's setting is process-wide, so
# changing it while another run (or an abandoned worker) is alive would silently slow it down.
TORCH_THREADS = max(1, min(4, (os.cpu_count() or 4) // 3))
_torch_threads_set = False


def ensure_torch_threads(torch_module) -> int:
    global _torch_threads_set
    if not _torch_threads_set:
        _torch_threads_set = True
        try:
            torch_module.set_num_threads(TORCH_THREADS)
        except Exception:
            pass
    return TORCH_THREADS
