import asyncio
import logging
import os
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


def open_browser():
    time.sleep(1.2)
    if not os.environ.get("PRIVATEDOC_NO_BROWSER"):
        webbrowser.open(f"http://127.0.0.1:{PORT}")

if __name__ == "__main__":
    print("=" * 65)
    print("  PrivateDoc AI - Privacy Shield & Multi-Document Hub")
    print(f"  Server locale protetto su http://127.0.0.1:{PORT}")
    print("  Per chiudere: pulsante «Chiudi programma» nell'app, oppure Ctrl+C / chiudi questa finestra.")
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
