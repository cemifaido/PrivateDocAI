"""
Explicit, verified download of the optional recognition model (see backend/ner.py).

The only place where the program talks to the internet on its own initiative, and only after
the user has said yes in the interface. Rules:
- pinned source: one repository at ONE immutable commit (the tag v1.5.0 resolved on 2026-10-22),
  never a branch or a moving tag; HTTPS only, also across redirects;
- every file is checked against the SHA-256 pinned in ``ner.EXPECTED_SHA256`` and against its
  size; a single mismatch discards everything and nothing is activated;
- files are written to a staging folder next to the model folder and moved in only when all
  five are verified; an existing folder is kept as a backup until the swap has succeeded;
- interrupted downloads resume with HTTP Range, but only when the server answers 206 with the
  right Content-Range (a 200 is never appended: it restarts the file);
- standard library only: proxies come from the system/environment, a company CA bundle from
  SSL_CERT_FILE / REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE.
Nothing here loads or runs the downloaded files: ``ner.py`` does that, after its own check.
"""
import hashlib
import os
import shutil
import ssl
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional

from .ner import EXPECTED_SHA256

REPOSITORY = "rizzoaiacademy/rizzo-pii-0.3B"
# tag v1.5.0, resolved through the Hugging Face API on 2026-10-22
REVISION = "a1c3c83827eca22e9675e30c1111c4641caf5901"
BASE_URL = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/"
LICENSE = "MIT"
FILE_SIZES = {
    "config.json": 3_137,
    "model.safetensors": 1_230_273_700,
    "special_tokens_map.json": 1_051,
    "tokenizer.json": 34_363_286,
    "tokenizer_config.json": 46_469,
}
TOTAL_BYTES = sum(FILE_SIZES.values())
CHUNK = 1 << 20


class DownloadError(Exception):
    """A failure that retrying cannot fix (wrong hash or size, unexpected answer...)."""


class DownloadCancelled(Exception):
    pass


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise DownloadError("reindirizzamento non sicuro rifiutato")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_opener(url: str, headers: Dict[str, str]):
    """Opens ``url`` (HTTPS only) with the system proxy and an optional company CA bundle."""
    if not url.lower().startswith("https://"):
        raise DownloadError("sono ammessi solo indirizzi HTTPS")
    cafile = next((os.environ[v] for v in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
                   if os.environ.get(v) and os.path.isfile(os.environ[v])), None)
    context = ssl.create_default_context(cafile=cafile)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(), _HttpsOnlyRedirects(),
                                         urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(url, headers={**headers, "User-Agent": "PrivateDocAI-model-download"})
    return opener.open(request, timeout=30)


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


class ModelDownloader:
    def __init__(self, model_dir: str, on_installed: Optional[Callable[[], None]] = None,
                 opener: Callable = default_opener, base_url: str = BASE_URL,
                 sizes: Optional[Dict[str, int]] = None, expected: Optional[Dict[str, str]] = None,
                 retries: int = 3, sleep: Callable[[float], None] = time.sleep, check_space: bool = True):
        self.model_dir = os.path.abspath(model_dir)
        self.staging = self.model_dir + ".staging"
        self.backup = self.model_dir + ".old"
        self._on_installed = on_installed
        self._opener = opener
        self._base_url = base_url
        self._sizes = dict(sizes or FILE_SIZES)
        self._expected = dict(expected or EXPECTED_SHA256)
        self._retries = retries
        self._sleep = sleep
        self._check_space = check_space
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._state = {"state": "idle", "file": "", "done_bytes": 0, "error": "", "speed": 0.0}

    # ----- what the interface shows before asking for consent -----
    def info(self) -> Dict[str, Any]:
        total = sum(self._sizes.values())
        return {"repository": REPOSITORY, "revision": REVISION, "license": LICENSE,
                "total_bytes": total, "files": dict(self._sizes)}

    def status(self) -> Dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        state["total_bytes"] = sum(self._sizes.values())
        return state

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _set(self, **changes) -> None:
        with self._lock:
            self._state.update(changes)

    # ----- control -----
    def start(self) -> bool:
        """Starts the download in the background; False when one is already running."""
        with self._lock:
            if self.running:
                return False
            self._cancel.clear()
            self._state = {"state": "downloading", "file": "", "done_bytes": 0, "error": "", "speed": 0.0}
            self._thread = threading.Thread(target=self._run, name="model-download", daemon=True)
            self._thread.start()
            return True

    def cancel(self) -> None:
        self._cancel.set()

    def wait(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # ----- work -----
    def _run(self) -> None:
        try:
            self._download_all()
            self._set(state="installing", file="")
            self._install()
        except DownloadCancelled:
            shutil.rmtree(self.staging, ignore_errors=True)
            self._set(state="cancelled", error="", speed=0.0)
            return
        except DownloadError as exc:
            shutil.rmtree(self.staging, ignore_errors=True)   # a wrong file is never kept
            self._set(state="error", error=str(exc), speed=0.0)
            return
        except Exception as exc:  # network down for good, disk full, permissions...
            # the verified part of the staging folder stays, so a later attempt resumes from it
            self._set(state="error", speed=0.0,
                      error=f"download interrotto ({type(exc).__name__}): riprova, riprenderà da dove si è fermato")
            return
        self._set(state="done", file="", speed=0.0)
        if self._on_installed is not None:
            try:
                self._on_installed()
            except Exception as exc:
                self._set(state="error", error=f"installato, ma non attivato ({type(exc).__name__}): riavvia il programma")

    def _download_all(self) -> None:
        total = sum(self._sizes.values())
        parent = os.path.dirname(self.model_dir) or "."
        os.makedirs(parent, exist_ok=True)
        if self._check_space and shutil.disk_usage(parent).free < total * 1.05:
            raise DownloadError(f"spazio su disco insufficiente: servono circa {total // 2**20} MB liberi")
        os.makedirs(self.staging, exist_ok=True)
        done_before = 0
        for name in self._expected:
            self._set(file=name, done_bytes=done_before)
            self._fetch(name, done_before)
            done_before += self._sizes[name]
        self._set(done_bytes=done_before, state="verifying")
        for name, digest in self._expected.items():      # final check of what is really on disk
            if sha256_file(os.path.join(self.staging, name)) != digest:
                raise DownloadError(f"impronta di {name} diversa da quella attesa: pacchetto scartato")

    def _fetch(self, name: str, done_before: int) -> None:
        final = os.path.join(self.staging, name)
        size, digest = self._sizes[name], self._expected[name]
        if os.path.isfile(final):                         # left by an earlier attempt
            if os.path.getsize(final) == size and sha256_file(final) == digest:
                return
            os.remove(final)
        part = final + ".part"
        failures = 0
        while True:
            try:
                self._stream(name, part, size, done_before)
                break
            except (DownloadError, DownloadCancelled):
                raise
            except (OSError, urllib.error.URLError, EOFError) as exc:   # includes IncompleteRead / timeouts
                failures += 1
                if failures > self._retries:
                    raise
                self._set(error=f"connessione interrotta ({type(exc).__name__}): nuovo tentativo {failures}/{self._retries}")
                self._sleep(min(2 ** failures, 10))
                self._set(error="")
        if os.path.getsize(part) != size:
            os.remove(part)
            raise DownloadError(f"dimensione di {name} diversa da quella attesa")
        if sha256_file(part) != digest:
            os.remove(part)
            raise DownloadError(f"impronta di {name} diversa da quella attesa: pacchetto scartato")
        os.replace(part, final)

    def _stream(self, name: str, part: str, size: int, done_before: int) -> None:
        start = os.path.getsize(part) if os.path.isfile(part) else 0
        if start > size:
            os.remove(part)
            start = 0
        if start == size:
            return                                        # complete: verified by the caller
        headers = {"Range": f"bytes={start}-"} if start else {}
        response = self._opener(self._base_url + name, headers)
        try:
            status = getattr(response, "status", None) or response.getcode()
            if start and status == 206:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {start}-"):
                    raise DownloadError("risposta di ripresa non coerente: download scartato")
                mode = "ab"
            elif status == 200:
                mode, start = "wb", 0                     # the server ignored Range: restart, never append
            else:
                raise DownloadError(f"risposta inattesa dal server ({status})")
            began, received = time.time(), 0
            with open(part, mode) as out:
                while True:
                    if self._cancel.is_set():
                        raise DownloadCancelled()
                    block = response.read(CHUNK)
                    if not block:
                        break
                    out.write(block)
                    received += len(block)
                    if start + received > size:
                        raise DownloadError(f"{name} più grande del previsto: download scartato")
                    elapsed = max(time.time() - began, 0.001)
                    self._set(done_bytes=done_before + start + received, speed=received / elapsed)
        finally:
            close = getattr(response, "close", None)
            if close:
                close()

    def _install(self) -> None:
        """Swaps the verified staging folder in; an existing folder is kept until the swap worked."""
        had_old = os.path.isdir(self.model_dir)
        if had_old:
            shutil.rmtree(self.backup, ignore_errors=True)
            os.replace(self.model_dir, self.backup)
        try:
            os.replace(self.staging, self.model_dir)
        except Exception:
            if had_old:
                os.replace(self.backup, self.model_dir)
            raise
        shutil.rmtree(self.backup, ignore_errors=True)
