import asyncio
import logging
import os
import socket
import sys
import webbrowser
import threading
import time
import uvicorn

from app import app

PORT = int(os.environ.get("PRIVATEDOC_PORT", "8765"))


class QuietShutdown(logging.Filter):
    """Closing the server while a request is open is normal: hide the cancellation tracebacks."""

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        return not isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt))


def ensure_streams() -> None:
    """The packaged app has no console window: stdout/stderr are None and uvicorn's logging would crash."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def attach_parent_console() -> None:
    """`--self-test` from a terminal: show the output even though the .exe has no console of its own."""
    if sys.stdout is not None or os.name != "nt":
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8")
            sys.stderr = sys.stdout
    except Exception:
        pass


def already_running() -> bool:
    """A second launch (for example a second click on the desktop icon) just reopens the first one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", PORT)) == 0


def open_browser():
    time.sleep(1.2)
    if not os.environ.get("PRIVATEDOC_NO_BROWSER"):
        webbrowser.open(f"http://127.0.0.1:{PORT}")

def self_test() -> int:
    """`PrivateDocAI.exe --self-test`: checks the packaged libraries (and the model, if installed)."""
    import importlib
    failures = 0
    for name in ("fastapi", "uvicorn", "fitz", "docx", "openpyxl", "cryptography", "easyocr", "playwright",
                 "transformers", "tokenizers", "safetensors"):
        try:
            importlib.import_module(name)
            print(f"  ok       {name}")
        except Exception as exc:
            optional = name in ("transformers", "tokenizers", "safetensors")
            print(f"  {'(manca)' if optional else 'ERRORE '}  {name}: {type(exc).__name__}")
            failures += 0 if optional else 1
    from app import doc_service
    ner = doc_service.ner
    ner.start_verification()
    status = ner.status()
    if status["state"] == "missing":
        print("  modello: non installato (si usano solo le regole)")
    else:
        if ner._verify_thread is not None:
            ner._verify_thread.join()
        found = ner.detect("Il Sig. Giuseppe Esposito abita in Via dei Mille 14, Bergamo.")
        print(f"  modello: {ner.status()['state']} - riconosciuti: {[c['raw'] for c in found]}")
        failures += 0 if found else 1
    print("AUTOTEST", "SUPERATO" if failures == 0 else f"FALLITO ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        attach_parent_console()
        ensure_streams()
        sys.exit(self_test())
    ensure_streams()
    if already_running():
        if not os.environ.get("PRIVATEDOC_NO_BROWSER"):
            webbrowser.open(f"http://127.0.0.1:{PORT}")
        sys.exit(0)
    print("=" * 65)
    print("  PrivateDoc AI - Privacy Shield & Multi-Document Hub")
    print(f"  Server locale protetto su http://127.0.0.1:{PORT}")
    print("  Per chiudere: pulsante «Chiudi programma» nell'app, oppure Ctrl+C.")
    print("=" * 65)

    for name in ("uvicorn.error", "uvicorn"):
        logging.getLogger(name).addFilter(QuietShutdown())

    # Launch browser automatically
    threading.Thread(target=open_browser, daemon=True).start()

    # app object, not "app:app": works when packaged. The server is kept in app.state so the
    # "Chiudi programma" button can ask it to stop in an orderly way.
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="info", timeout_graceful_shutdown=3)
    server = uvicorn.Server(config)
    app.state.server = server
    try:
        server.run()
    except KeyboardInterrupt:
        pass
