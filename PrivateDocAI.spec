# PyInstaller spec: cartella (non onefile) con PrivateDocAI.exe
# Build: build_exe.bat  (oppure: pyinstaller --noconfirm PrivateDocAI.spec)
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

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

# Optional recogniser (backend/ner.py): the libraries are bundled, the model (1.2 GB) is not.
# The build FAILS (instead of silently producing an exe without them) unless it is told to skip:
#   set PRIVATEDOC_BUILD_WITHOUT_NER=1
import importlib.util
if os.environ.get('PRIVATEDOC_BUILD_WITHOUT_NER') == '1':
    print('WARNING: building WITHOUT the optional model libraries')
else:
    for required in ('transformers', 'tokenizers', 'safetensors'):
        if importlib.util.find_spec(required) is None:
            raise SystemExit(f"Missing '{required}': pip install -r requirements-ner.txt "
                             "(or set PRIVATEDOC_BUILD_WITHOUT_NER=1 to build without the model)")
    for pkg in ('tokenizers', 'safetensors'):
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    for pkg in ('transformers.models.modernbert', 'transformers.models.auto'):
        hiddenimports += collect_submodules(pkg)

a = Analysis(
    ['run.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # heavy packages pulled in by the model libraries' hooks that the program never uses
    excludes=['tkinter', 'matplotlib', 'IPython', 'pytest', 'notebook', 'tensorboard',
              'pandas', 'pyarrow', 'botocore', 'boto3', 'nltk'],
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
