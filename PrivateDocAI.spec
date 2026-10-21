# PyInstaller spec: cartella (non onefile) con PrivateDocAI.exe
# Build: build_exe.bat  (oppure: pyinstaller --noconfirm PrivateDocAI.spec)
import os
from PyInstaller.utils.hooks import collect_all

datas = [('static', 'static')]
binaries = []
hiddenimports = ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
                 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on', 'multipart']

# OCR models shipped with the app so the first scan does not need a download
ocr_models = os.path.expanduser('~/.EasyOCR/model')
if os.path.isdir(ocr_models):
    datas.append((ocr_models, 'easyocr_models'))

for pkg in ('easyocr', 'playwright', 'cryptography', 'docx', 'extract_msg', 'openpyxl', 'xlrd', 'fitz', 'pymupdf'):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ['run.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['tkinter', 'matplotlib', 'IPython', 'pytest', 'notebook', 'tensorboard'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PrivateDocAI',
    console=True,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='PrivateDocAI',
    upx=False,
)
