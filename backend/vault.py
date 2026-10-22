"""
Encrypted storage for saved cases ("pratiche").

One master password protects everything: it is stretched with scrypt into an AES-256-GCM
key that exists only in memory while the vault is unlocked. Nothing readable is written
to disk, and a forgotten password cannot be recovered.

Format (version 2): every case file is  MAGIC | nonce | ciphertext  and is authenticated
together with its case id (AAD), so a file copied onto another case's name is rejected.
Known limit: restoring an OLDER copy of the same file cannot be detected without an
external trust anchor (e.g. Windows DPAPI or a server).
"""
import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultError(Exception):
    pass


class WrongPassword(VaultError):
    pass


class TooManyAttempts(VaultError):
    pass


class Vault:
    MIN_PASSWORD_LENGTH = 12
    _CANARY = b"privatedoc-vault-ok"
    # OWASP-style minimum for scrypt: N=2^16, r=8, p=2 (about 64 MiB)
    _DEFAULT_KDF = {"n": 2 ** 16, "r": 8, "p": 2}
    _LEGACY_KDF = {"n": 2 ** 15, "r": 8, "p": 1}
    _MAGIC = b"PDV2"
    _ID_PATTERN = re.compile(r"^[0-9a-f\-]{8,64}$")
    _CASE_AAD = b"PrivateDoc/case/v2:"
    _CHECK_AAD = b"PrivateDoc/vault-check/v2"
    _LIBRARY_AAD = b"PrivateDoc/library/v1:"
    _LIBRARY_NAME = re.compile(r"^[a-z]{3,20}$")

    def __init__(self, directory: str):
        self.directory = directory
        self.cases_dir = os.path.join(directory, "pratiche")
        self.meta_path = os.path.join(directory, "vault.json")
        os.makedirs(self.cases_dir, exist_ok=True)
        self._key: Optional[bytes] = None
        self._lock = threading.RLock()
        self._failed_attempts = 0
        self._blocked_until = 0.0

    # ----- state -----
    @property
    def initialized(self) -> bool:
        return os.path.exists(self.meta_path)

    @property
    def unlocked(self) -> bool:
        return self._key is not None

    # ----- password handling -----
    @classmethod
    def _validated_kdf(cls, params: Dict[str, Any]) -> Dict[str, int]:
        """Parameters read from disk are untrusted: bound them so a tampered file cannot exhaust memory."""
        try:
            n, r, p = int(params["n"]), int(params["r"]), int(params["p"])
        except (KeyError, TypeError, ValueError):
            raise VaultError("Parametri di cifratura non validi.")
        if n < 2 ** 14 or n > 2 ** 20 or n & (n - 1) or not 1 <= r <= 16 or not 1 <= p <= 16 \
                or 128 * n * r > 512 * 1024 * 1024:
            raise VaultError("Parametri di cifratura fuori dai limiti consentiti.")
        return {"n": n, "r": r, "p": p}

    @staticmethod
    def _derive(password: str, salt: bytes, params: Dict[str, int]) -> bytes:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32,
                              maxmem=1024 * 1024 * 1024, **params)

    def setup(self, password: str):
        with self._lock:
            if self.initialized:
                raise VaultError("La password è già stata impostata.")
            if len(password) < self.MIN_PASSWORD_LENGTH:
                raise VaultError(f"La password deve avere almeno {self.MIN_PASSWORD_LENGTH} caratteri.")
            salt = secrets.token_bytes(16)
            params = dict(self._DEFAULT_KDF)
            key = self._derive(password, salt, params)
            meta = {
                "version": 2,
                "kdf": "scrypt",
                "params": params,
                "salt": base64.b64encode(salt).decode(),
                "check": base64.b64encode(self._encrypt(key, self._CANARY, self._CHECK_AAD)).decode(),
            }
            self._write_atomic(self.meta_path, json.dumps(meta).encode())
            self._key = key

    def unlock(self, password: str):
        with self._lock:
            if not self.initialized:
                raise VaultError("Password non ancora impostata.")
            wait = self._blocked_until - time.time()
            if wait > 0:
                raise TooManyAttempts(f"Troppi tentativi: riprova tra {int(wait) + 1} secondi.")
            try:
                with open(self.meta_path, "rb") as f:
                    meta = json.load(f)
                salt = base64.b64decode(meta["salt"])
                check = base64.b64decode(meta["check"])
                legacy = meta.get("version", 1) < 2
                params = self._validated_kdf(self._LEGACY_KDF if legacy else meta.get("params", {}))
            except (OSError, ValueError, KeyError, TypeError, binascii.Error):
                raise VaultError("File dell'archivio illeggibile o danneggiato.")
            key = self._derive(password, salt, params)
            try:
                ok = self._decrypt(key, check, None if legacy else self._CHECK_AAD) == self._CANARY
            except InvalidTag:
                ok = False
            if not ok:
                self._register_failure()
                raise WrongPassword("Password errata.")
            self._failed_attempts = 0
            self._key = key

    def _register_failure(self):
        # exponential back-off from the 4th wrong attempt on (2, 4, 8 ... up to 60 s); no permanent lockout
        self._failed_attempts += 1
        if self._failed_attempts > 3:
            self._blocked_until = time.time() + min(60, 2 ** (self._failed_attempts - 3))

    def lock(self):
        with self._lock:
            self._key = None

    # ----- cases -----
    def save(self, case_id: str, data: Dict[str, Any]):
        with self._lock:
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            blob = self._MAGIC + self._encrypt(self._require_key(), payload, self._CASE_AAD + case_id.encode())
            self._write_atomic(self._case_path(case_id), blob)

    def load(self, case_id: str) -> Dict[str, Any]:
        with self._lock:
            path = self._case_path(case_id)
            if not os.path.exists(path):
                raise VaultError("Pratica non trovata.")
            key = self._require_key()
            try:
                with open(path, "rb") as f:
                    blob = f.read()
                is_v2 = blob.startswith(self._MAGIC)
                if is_v2:
                    plain = self._decrypt(key, blob[len(self._MAGIC):], self._CASE_AAD + case_id.encode())
                else:  # case saved by the first version of the app (no magic, no AAD)
                    plain = self._decrypt(key, blob, None)
                data = json.loads(plain.decode("utf-8"))
            except (InvalidTag, ValueError, OSError, TypeError):
                raise VaultError("Pratica illeggibile (file danneggiato, spostato o password diversa).")
            if not isinstance(data, dict):
                raise VaultError("Pratica illeggibile (contenuto non valido).")
            if (is_v2 and data.get("id") != case_id) or \
                    (not is_v2 and data.get("id") not in (None, case_id)):
                raise VaultError("Pratica non coerente con il nome del file.")
            return data

    # ----- small encrypted libraries shared by all cases (e.g. the user's own categories) -----
    def save_library(self, name: str, data: Dict[str, Any]):
        if not self._LIBRARY_NAME.match(name):
            raise VaultError("Nome della raccolta non valido.")
        with self._lock:
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            blob = self._MAGIC + self._encrypt(self._require_key(), payload, self._LIBRARY_AAD + name.encode())
            self._write_atomic(os.path.join(self.directory, f"{name}.enc"), blob)

    def load_library(self, name: str) -> Dict[str, Any]:
        """The saved library, or {} when there is none yet."""
        if not self._LIBRARY_NAME.match(name):
            raise VaultError("Nome della raccolta non valido.")
        with self._lock:
            path = os.path.join(self.directory, f"{name}.enc")
            key = self._require_key()
            if not os.path.exists(path):
                return {}
            try:
                with open(path, "rb") as f:
                    blob = f.read()
                if not blob.startswith(self._MAGIC):
                    raise ValueError("formato non riconosciuto")
                data = json.loads(self._decrypt(key, blob[len(self._MAGIC):],
                                                self._LIBRARY_AAD + name.encode()).decode("utf-8"))
            except (InvalidTag, ValueError, OSError, TypeError):
                raise VaultError("Raccolta illeggibile (file danneggiato, spostato o password diversa).")
            return data if isinstance(data, dict) else {}

    def delete(self, case_id: str):
        with self._lock:
            path = self._case_path(case_id)
            if os.path.exists(path):
                os.remove(path)

    def list_cases(self) -> List[Dict[str, Any]]:
        with self._lock:
            cases = []
            for name in os.listdir(self.cases_dir):
                if not name.endswith(".enc"):
                    continue
                case_id = name[:-4]
                try:
                    data = self.load(case_id)
                except VaultError:
                    # a damaged file is shown (so it can be deleted), never silently hidden
                    cases.append({"id": case_id, "name": "(pratica illeggibile)", "created": None,
                                  "updated": None, "document_count": 0, "error": True})
                    continue
                cases.append({
                    "id": case_id,
                    "name": data.get("name", "Pratica"),
                    "created": data.get("created"),
                    "updated": data.get("updated"),
                    "document_count": len(data.get("documents", [])),
                    "error": False,
                })
            return sorted(cases, key=lambda c: c.get("updated") or "", reverse=True)

    # ----- internals -----
    def _require_key(self) -> bytes:
        if self._key is None:
            raise VaultError("Archivio bloccato: inserisci la password.")
        return self._key

    def _case_path(self, case_id: str) -> str:
        if not self._ID_PATTERN.match(case_id):
            raise VaultError("Identificativo pratica non valido.")
        return os.path.join(self.cases_dir, f"{case_id}.enc")

    @staticmethod
    def _encrypt(key: bytes, plaintext: bytes, aad: Optional[bytes]) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)

    @staticmethod
    def _decrypt(key: bytes, blob: bytes, aad: Optional[bytes]) -> bytes:
        if len(blob) < 12 + 16:
            raise ValueError("blob troppo corto")
        return AESGCM(key).decrypt(blob[:12], blob[12:], aad)

    def _write_atomic(self, path: str, content: bytes):
        # temp file + fsync + replace: a crash never leaves a half-written case
        with self._lock:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
            except BaseException:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise
