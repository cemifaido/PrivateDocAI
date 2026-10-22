import hmac
import os
import re
import secrets
from typing import List, Optional, Dict
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from backend.document_service import DocumentService, SessionInvalidated, UploadBusy
from backend.vault import Vault, VaultError, WrongPassword
from backend.pdf_redaction import PdfRedactionError, RedactionIncomplete
from backend.runtime import RESOURCE_DIR

app = FastAPI(title="PrivateDoc AI - Privacy & Multi-Format LLM Hub")

doc_service = DocumentService()
doc_service.vault = Vault(doc_service.data_dir)


# Random per start and embedded only in the page this server hands out: every API call must
# carry it, so a page from another site cannot drive the app (CSRF), even through DNS rebinding.
APP_TOKEN = secrets.token_urlsafe(32)
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def _host_name(request: Request) -> str:
    # Host names are case-insensitive.  Use Starlette's parsed hostname instead of
    # splitting the header ourselves (which is error-prone for bracketed IPv6).
    return (request.url.hostname or "").lower()


@app.middleware("http")
async def local_security(request: Request, call_next):
    """
    1. Only requests addressed to localhost are served (blocks DNS rebinding).
    2. /api/* needs the per-start token, and a browser Origin, if present, must be this very app.
    3. Until the password is entered nothing can be read or written.
    """
    if _host_name(request) not in ALLOWED_HOSTS:
        return JSONResponse(status_code=400, content={"detail": "Host non consentito."})
    path = request.url.path
    if path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin and origin != f"http://{request.headers.get('host')}":
            return JSONResponse(status_code=403, content={"detail": "Origine non consentita."})
        token = request.headers.get("x-privatedoc-token") or ""
        if not hmac.compare_digest(token, APP_TOKEN):
            return JSONResponse(status_code=403, content={"detail": "Token mancante o non valido."})
        vault = doc_service.vault
        if not path.startswith("/api/vault/") and path != "/api/shutdown" \
                and vault is not None and not vault.unlocked:
            return JSONResponse(status_code=423, content={"detail": "vault_locked"})
    return await call_next(request)


class PasswordRequest(BaseModel):
    password: str
    confirm: Optional[str] = None


@app.post("/api/shutdown")
async def shutdown():
    """Orderly stop: interrupts a running upload, locks the archive, then stops the server."""
    doc_service.cancel_upload()
    doc_service.lock_all()
    server = getattr(app.state, "server", None)
    if server is not None:
        server.should_exit = True
    return {"status": "closing"}


@app.get("/api/vault/status")
async def vault_status():
    vault = doc_service.vault
    return {
        "initialized": vault.initialized,
        "unlocked": vault.unlocked,
        "min_password_length": vault.MIN_PASSWORD_LENGTH,
    }


@app.post("/api/vault/setup")
async def vault_setup(data: PasswordRequest):
    if data.password != data.confirm:
        raise HTTPException(status_code=400, detail="Le due password non coincidono.")
    try:
        doc_service.vault.setup(data.password)
    except VaultError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success"}


@app.post("/api/vault/unlock")
async def vault_unlock(data: PasswordRequest):
    try:
        doc_service.vault.unlock(data.password)
    except WrongPassword as e:
        raise HTTPException(status_code=401, detail=str(e))
    except VaultError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success"}


@app.post("/api/vault/lock")
async def vault_lock():
    doc_service.lock_all()  # saves, locks and forgets decrypted data in one atomic step
    return {"status": "success"}


@app.get("/api/pratiche")
async def list_cases():
    doc_service.flush_pending()
    return {"cases": doc_service.vault.list_cases()}


class CaseRequest(BaseModel):
    id: str
    name: Optional[str] = None


@app.post("/api/pratiche/open")
async def open_case(data: CaseRequest):
    try:
        return doc_service.open_case(data.id)
    except VaultError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/pratiche/rename")
async def rename_case(data: CaseRequest):
    try:
        doc_service.rename_case(data.id, data.name or "")
    except VaultError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "success"}


@app.post("/api/pratiche/delete")
async def delete_case(data: CaseRequest):
    try:
        doc_service.delete_case(data.id)
    except VaultError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "success"}

UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_UPLOAD_FILE_BYTES = 50 * 1024 * 1024
MAX_UPLOAD_TOTAL_BYTES = 100 * 1024 * 1024

# Serve static files
static_dir = os.path.join(RESOURCE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read().replace("__APP_TOKEN__", APP_TOKEN)
    return "<h1>PrivateDoc AI Backend Running</h1>"

@app.get("/guida", response_class=HTMLResponse)
async def read_guide():
    with open(os.path.join(static_dir, "guida.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/upload")
async def upload_files(
    session_id: Optional[str] = Form(None),
    operation_id: Optional[str] = Form(None),
    files: List[UploadFile] = File(...)
):
    """
    Receives multi-format files and archives (.zip, .pdf, .docx, .odt, .xlsx, .eml, .msg).
    Extracts content, detects entities, and creates consistent cross-document pseudonymization.
    """
    uploaded_tuples = []
    total_bytes = 0
    for f in files:
        contents = bytearray()
        while chunk := await f.read(UPLOAD_CHUNK_BYTES):
            contents.extend(chunk)
            total_bytes += len(chunk)
            if len(contents) > MAX_UPLOAD_FILE_BYTES:
                raise HTTPException(status_code=413, detail="Il singolo file supera il limite di 50 MB.")
            if total_bytes > MAX_UPLOAD_TOTAL_BYTES:
                raise HTTPException(status_code=413, detail="Il caricamento complessivo supera il limite di 100 MB.")
        uploaded_tuples.append((f.filename or "documento", bytes(contents)))

    s_id = session_id if (session_id and session_id.strip() != "null") else None
    # CPU-heavy (OCR): run it off the event loop so the rest of the app stays responsive
    try:
        return await run_in_threadpool(doc_service.add_uploaded_files, s_id, uploaded_tuples, operation_id)
    except UploadBusy:
        raise HTTPException(status_code=409, detail="Un altro caricamento è ancora in corso: attendi che finisca.")
    except SessionInvalidated:
        raise HTTPException(status_code=423, detail="vault_locked")

@app.get("/api/ner/status")
async def ner_status():
    return doc_service.ner.status()

class NerSettings(BaseModel):
    enabled: Optional[bool] = None
    extended: Optional[bool] = None

@app.post("/api/ner/settings")
async def ner_settings(data: NerSettings):
    if data.enabled is not None:
        doc_service.ner.enabled = data.enabled
    if data.extended is not None:
        doc_service.ner.extended = data.extended
    return doc_service.ner.status()

@app.get("/api/model/info")
async def model_info():
    return doc_service.model_downloader.info()

@app.get("/api/model/status")
async def model_status():
    return {**doc_service.model_downloader.status(), "ner": doc_service.ner.status()}

class ModelDownloadRequest(BaseModel):
    consent: bool = False

@app.post("/api/model/download")
async def model_download(data: ModelDownloadRequest):
    if not data.consent:
        raise HTTPException(status_code=400, detail="Serve il consenso esplicito dell'utente.")
    if doc_service.ner.status()["state"] not in ("missing", "rejected", "error"):
        raise HTTPException(status_code=409, detail="Il modello è già installato.")
    if not doc_service.model_downloader.start():
        raise HTTPException(status_code=409, detail="Un download è già in corso.")
    return doc_service.model_downloader.status()

@app.post("/api/model/cancel")
async def model_cancel():
    doc_service.model_downloader.cancel()
    return {"ok": True}

@app.get("/api/upload/progress")
async def upload_progress():
    return doc_service.progress

@app.post("/api/upload/cancel")
async def upload_cancel():
    doc_service.cancel_upload()
    return {"status": "success"}

class EntityUpdate(BaseModel):
    session_id: str
    token: str
    new_original: str

class DocumentSelection(BaseModel):
    session_id: str
    selected_ids: List[str]

@app.post("/api/documents/select")
async def select_documents(data: DocumentSelection):
    documents = doc_service.select_documents(data.session_id, data.selected_ids)
    return {"status": "success", "documents": documents}

class DiscardRequest(BaseModel):
    session_id: str
    operation_id: str

@app.post("/api/upload/discard")
async def discard_upload(data: DiscardRequest):
    return {"status": "success", **doc_service.discard_added(data.session_id, data.operation_id)}

class DocumentRemoval(BaseModel):
    session_id: str
    id: str
    purge: bool = False

@app.post("/api/documents/remove")
async def remove_document(data: DocumentRemoval):
    return {"status": "success", **doc_service.remove_document(data.session_id, data.id, data.purge)}

@app.post("/api/entity/update")
async def update_entity(data: EntityUpdate):
    with doc_service.state_lock:
        session = doc_service.get_or_create_session(data.session_id)
        anonymizer = session["anonymizer"]
        anonymizer.update_entity(data.token, data.new_original)
        doc_service.persist(data.session_id)
        return {"status": "success", "entities": anonymizer.get_registry()}

class EntityRemove(BaseModel):
    session_id: str
    token: str

@app.post("/api/entity/remove")
async def remove_entity(data: EntityRemove):
    with doc_service.state_lock:
        session = doc_service.get_or_create_session(data.session_id)
        anonymizer = session["anonymizer"]
        anonymizer.remove_entity(data.token)
        doc_service.persist(data.session_id)
        return {"status": "success", "entities": anonymizer.get_registry()}

@app.get("/api/categories")
async def list_categories():
    return doc_service.list_categories()

class CategoryCreate(BaseModel):
    name: str

@app.post("/api/categories")
async def create_category(data: CategoryCreate):
    try:
        ident = doc_service.add_category(data.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": ident, **doc_service.list_categories()}

def _checked_category(category: str) -> str:
    if not re.fullmatch(r"[A-Z]+(?:_[A-Z]+)*", category or "") or not 2 <= len(category) <= 30:
        raise HTTPException(status_code=400, detail="Categoria non valida.")
    return category

class EntityAdd(BaseModel):
    session_id: str
    text: str
    category: str

@app.post("/api/entity/add")
async def add_entity(data: EntityAdd):
    with doc_service.state_lock:
        session = doc_service.get_or_create_session(data.session_id)
        anonymizer = session["anonymizer"]
        token = anonymizer.add_custom_entity(data.text, _checked_category(data.category))
        doc_service.persist(data.session_id)
        return {"status": "success", "token": token, "entities": anonymizer.get_registry()}

class PromptGenRequest(BaseModel):
    session_id: str
    instruction: str

@app.post("/api/prompt/generate")
async def generate_prompt(data: PromptGenRequest):
    if not doc_service.has_selected_documents(data.session_id):
        raise HTTPException(status_code=400, detail="Seleziona almeno un documento da includere.")
    prompt = doc_service.build_comparison_prompt(data.session_id, data.instruction)
    session = doc_service.get_or_create_session(data.session_id)
    return {
        "status": "success",
        "prompt": prompt,
        "entities": session["anonymizer"].get_registry(),
        "preflight": doc_service.preflight_report(data.session_id, data.instruction)
    }

class PreflightRequest(BaseModel):
    session_id: str
    instruction: str = ""

@app.post("/api/documents/preflight")
async def get_preflight(data: PreflightRequest):
    return doc_service.preflight_report(data.session_id, data.instruction)

@app.get("/api/session/state")
async def get_session_state(session_id: str):
    state = doc_service.get_session_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sessione non trovata")
    return state

class QuickProtectRequest(BaseModel):
    session_id: str
    term: str
    action: str  # "SOCIETA", "PERSONA", "IGNORE"

@app.post("/api/documents/quick-protect")
async def quick_protect(data: QuickProtectRequest):
    with doc_service.state_lock:
        session = doc_service.get_or_create_session(data.session_id)
        anonymizer = session["anonymizer"]
        if data.action == "IGNORE":
            anonymizer.whitelist.add(data.term.lower().rstrip('.,;:'))
        else:
            anonymizer.add_custom_entity(data.term, _checked_category(data.action))
        doc_service.persist(data.session_id)
        return {
            "status": "success",
            "preflight": doc_service.preflight_report(data.session_id),
            "entities": anonymizer.get_registry()
        }

class AuthOpenRequest(BaseModel):
    provider: str

@app.post("/api/auth/open-login")
def open_login(data: AuthOpenRequest):
    """
    Opens the official web login window for the selected provider (Gemini, ChatGPT, Claude)
    so the user logs in with their standard email & password.
    """
    res = doc_service.browser_bridge.open_login_window(data.provider)
    return res

@app.get("/api/auth/status")
def check_auth_status(provider: str):
    res = doc_service.browser_bridge.check_login_status(provider)
    return res

class ExecuteRequest(BaseModel):
    session_id: str
    provider: str
    instruction: str
    confirmed_suspects: List[str] = Field(default_factory=list)

@app.post("/api/execute")
def execute_task(data: ExecuteRequest):
    """
    Executes the analysis:
    1. Builds the pseudonymized prompt
    2. Sends it through the authenticated browser session
    3. Retrieves the raw response
    4. De-anonymizes it locally, restoring real names and data
    """
    # Captured before preflight/build-prompt: a lock+unlock cycle that happens while those run
    # would otherwise be invisible to the epoch check below.
    epoch = doc_service.epoch
    try:
        prepared = doc_service.prepare_execution(data.session_id, data.instruction, epoch)
    except SessionInvalidated:
        return JSONResponse(status_code=423, content={"detail": "vault_locked"})
    if prepared is None:
        return {"status": "error", "message": "Seleziona almeno un documento da includere."}
    preflight = prepared["preflight"]
    if preflight["leaks"]:
        return {
            "status": "error",
            "message": "Invio bloccato: alcuni dati sensibili risultano ancora in chiaro nel testo.",
            "preflight": preflight
        }
    suspects = sorted(set(preflight["suspects"]))
    confirmed = sorted(set(data.confirmed_suspects))
    if suspects and confirmed != suspects:
        # Confirm the exact current set: a stale yes must not authorize suspects that
        # appeared after the warning was shown.
        return {"status": "needs_confirmation", "suspects": preflight["suspects"]}

    prompt = prepared["prompt"]

    # Run through browser bridge
    bridge_result = doc_service.browser_bridge.execute_prompt(data.provider, prompt)
    if bridge_result.get("status") != "success":
        return {
            "status": "error",
            "message": bridge_result.get("message", "Errore sconosciuto"),
            "masked_prompt": prompt
        }

    raw_response = bridge_result.get("response", "")
    # Epoch/unlocked/session-exists are checked atomically with the commit itself: a plain
    # check here followed by a separate process_llm_response call would leave a window where
    # lock_all() runs in between and the response still gets decrypted and written back.
    processed = doc_service.process_llm_response_if_current(data.session_id, raw_response, epoch)
    if processed is None:
        # the archive was locked meanwhile (or the session is gone): drop the answer, do not
        # rebuild the decrypted session
        return JSONResponse(status_code=423, content={"detail": "vault_locked"})

    return {
        "status": "success",
        "result": processed
    }

class DeanonymizeManualRequest(BaseModel):
    session_id: str
    raw_response: str

@app.post("/api/deanonymize")
async def deanonymize_manual(data: DeanonymizeManualRequest):
    """
    Manual fallback: user pasted a response from their own browser,
    and this endpoint restores the real names and data instantly.
    """
    processed = doc_service.process_llm_response(data.session_id, data.raw_response)
    return {"status": "success", "result": processed}

@app.post("/api/export/pdf")
async def export_pdf(session_id: str = Form(...), mode: str = Form("nero"), file: UploadFile = File(...)):
    """
    PDF with the protected data really removed. The original is received here, processed in
    memory and discarded: it is never saved in the case. Delivered only after the check found
    nothing left; scanned PDFs (images) are refused.
    """
    contents = bytearray()
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        contents.extend(chunk)
        if len(contents) > MAX_UPLOAD_FILE_BYTES:
            raise HTTPException(status_code=413, detail="Il file supera il limite di 50 MB.")
    try:
        pdf, report = await run_in_threadpool(doc_service.export_redacted_pdf, session_id, bytes(contents), mode)
    except KeyError:
        raise HTTPException(status_code=404, detail="Pratica non trovata.")
    except RedactionIncomplete as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except PdfRedactionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    removed = sum(item["removed"] for item in report["terms"].values())
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.splitext(os.path.basename(file.filename or "documento"))[0]) or "documento"
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{stem}_censurato.pdf"',
        "X-PrivateDoc-Removed": str(removed),
        "Cache-Control": "no-store, private",
        "X-Content-Type-Options": "nosniff",
    })

@app.get("/api/export/docx")
async def export_docx(session_id: str):
    docx_io = doc_service.export_report_docx(session_id)
    return StreamingResponse(
        docx_io,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=Report_Confronto_Documentale.docx"}
    )

@app.post("/api/session/reset")
async def reset_session(data: Dict[str, str]):
    s_id = data.get("session_id")
    with doc_service.state_lock:
        doc_service.flush_pending()
        if s_id and s_id in doc_service.sessions:
            del doc_service.sessions[s_id]
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=True)
