"""
Optional, OFF by default: ask Gemini through Google's official API with the user's own key.

Why it exists: the web login of Gemini cannot be automated (Google refuses automated browsers and the
program does not try to hide the automation). The official API is the supported way to call it.
Rules:
- the key is stored only in the encrypted vault (see ``DocumentService``), never in a file in clear,
  never logged and never put in a URL: it travels in the ``x-goog-api-key`` header, over HTTPS;
- what is sent is the same pseudonymised text as in every other mode, after the same pre-flight check;
- the data terms depend on the kind of quota: see the notice shown before it can be enabled.
"""
import json
import re
import urllib.error
from typing import Any, Callable, Dict

from .model_downloader import default_opener

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODEL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.\-]{2,60}$")
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{20,200}$")


class GeminiApiError(Exception):
    """A failure whose message is safe to show (it never contains the key)."""


def generate(api_key: str, model: str, prompt: str, opener: Callable = default_opener) -> str:
    if not KEY_PATTERN.match(api_key or ""):
        raise GeminiApiError("Chiave API non valida.")
    if not MODEL_PATTERN.match(model or ""):
        raise GeminiApiError("Nome del modello non valido.")
    body = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}]}).encode("utf-8")
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    try:
        response = opener(ENDPOINT.format(model=model), headers, body)
        try:
            payload: Dict[str, Any] = json.loads(response.read().decode("utf-8"))
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
    except urllib.error.HTTPError as exc:
        reasons = {400: "richiesta non valida (controlla il nome del modello)", 401: "chiave non accettata",
                   403: "accesso negato o servizio non abilitato per questa chiave",
                   404: "modello non trovato", 429: "limite di richieste raggiunto, riprova più tardi"}
        raise GeminiApiError(f"Gemini API: {reasons.get(exc.code, f'errore {exc.code}')}.") from None
    except (OSError, ValueError) as exc:
        raise GeminiApiError(f"Gemini API non raggiungibile ({type(exc).__name__}).") from None
    feedback = payload.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        raise GeminiApiError(f"Gemini ha rifiutato la richiesta ({feedback['blockReason']}).")
    parts = ((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    if not text.strip():
        raise GeminiApiError("Gemini non ha restituito testo.")
    return text
