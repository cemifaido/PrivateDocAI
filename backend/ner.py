"""
Optional second recogniser: a small token-classification model (rizzo-pii 0.3B, MIT licence,
built on mmBERT, MIT) that runs on the CPU and finds what plain rules miss (names in context,
company names, case numbers, cadastral data, identity documents...).

Design rules:
- OPTIONAL: nothing here is needed to run the program. If the model folder is missing, damaged
  or its files do not match the pinned SHA-256, the detector says why and the rules work alone.
- OFFLINE: nothing is ever downloaded; the libraries are told so before they are imported.
- VERIFIED BEFORE USE: every file the model loads is checked against a pinned SHA-256. The state
  shown to the user is "active" only after that check passed.
- ADDITIVE AND SAFE: it only proposes candidates. Any failure discards ALL of that run's partial
  results and the program carries on with the rules (see ``DeterministicAnonymizer``).
"""
import hashlib
import os
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from .runtime import ensure_torch_threads

# Defence in depth on top of local_files_only: no network, no telemetry, even by accident.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# rizzoaiacademy/rizzo-pii-0.3B, revision v1.5.0: every file consumed by the loader.
EXPECTED_SHA256 = {
    "config.json": "6b9d5bdd4a194d40fb40c53fdc302e225514cd7940d97f657c4082454ee7e91b",
    "model.safetensors": "b1e046e3aec52c3cd74eaf166b034644a4dac0c91128bf06803e1478657fcd9f",
    "tokenizer.json": "a0ab5772a8c5450f45a66c95985d6df2205bf09449ba7ff7bb46de034eaa118a",
    "tokenizer_config.json": "3b66ca84514d9aacf4b90c65a61e561127c6c21d81bbf4e8ba9d46a4c15ac82d",
    "special_tokens_map.json": "6e3204c5a4004719c185007a745d1940471a6fb02521cfa0a00306dbb6bc5903",
}
MODEL_FILES = tuple(EXPECTED_SHA256)

CHUNK_WORDS = 120      # like the reference app; the tokenizer windows below guarantee the token limit
CHUNK_OVERLAP = 20
MAX_TOKENS = 512
TOKEN_STRIDE = 64      # overlap between windows of a chunk that is longer than MAX_TOKENS
MIN_SCORE = 0.85       # for every category: a guess below this is not worth a mask

# model tag -> our category. Anything not listed is ignored.
CORE_TAGS = {
    "FULLNAME": "PERSONA", "ORG": "SOCIETA",
    "CF": "CODICE_FISCALE", "PIVA": "PARTITA_IVA", "IBAN": "IBAN", "EMAIL": "EMAIL",
    "TELEPHONENUM": "TELEFONO", "CREDITCARDNUMBER": "CARTA_PAGAMENTO", "TARGA": "TARGA",
    "DATE": "DATA", "AMOUNT": "IMPORTO", "STREET": "INDIRIZZO",
    "CATASTO": "CATASTO", "DOCID": "RIFERIMENTO", "ID_DOC": "DOC_IDENTITA",
}
# Switched off by default: masking them hides context the reader of the act needs (where? when?
# how old?) and risks over-masking. Available through the "extended profile".
EXTENDED_TAGS = {
    "CITY": "CITTA", "ZIPCODE": "CAP", "PROVINCE": "PROVINCIA", "AGE": "ETA",
    "GENDER": "SESSO", "TIME": "ORA", "BUILDINGNUM": "CIVICO",
}
STRUCTURED = {"CODICE_FISCALE", "PARTITA_IVA", "IBAN", "EMAIL", "TELEFONO", "CARTA_PAGAMENTO", "TARGA"}

# A model-only guess for a fixed-shape identifier must still LOOK like one (the rules are the
# safety net for these; the model must not be able to mask arbitrary words as an "e-mail").
_SHAPES = {
    "EMAIL": re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"),
    "CODICE_FISCALE": re.compile(r"^[A-Za-z]{6}\d{2}[A-Za-z]\d{2}[A-Za-z]\d{3}[A-Za-z]$"),
    "PARTITA_IVA": re.compile(r"^(?:IT)?\d{11}$", re.IGNORECASE),
    "IBAN": re.compile(r"^[A-Za-z]{2}\d{2}[A-Za-z0-9]{11,30}$"),
    "TARGA": re.compile(r"^[A-Za-z]{2}\s?\d{3}\s?[A-Za-z]{2}$"),
}


def _shape_ok(category: str, raw: str) -> bool:
    if category == "TELEFONO":
        return len(re.sub(r"\D", "", raw)) >= 8
    if category == "CARTA_PAGAMENTO":
        digits = re.sub(r"\D", "", raw)
        return 13 <= len(digits) <= 19 and _luhn(digits)
    shape = _SHAPES.get(category)
    return True if shape is None else bool(shape.match(raw.replace(" ", "") if category != "TARGA" else raw))


def _luhn(digits: str) -> bool:
    total, flip = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if flip:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        flip = not flip
    return total % 10 == 0


Span = Tuple[int, int, str, float]  # start, end, tag, score (offsets inside the text given)


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def chunk_text(text: str, max_words: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> List[Tuple[str, int]]:
    """[(substring, global char offset)] cut on word boundaries, overlapping so no entity is split."""
    words = list(re.finditer(r"\S+", text))
    chunks, i, step = [], 0, max(1, max_words - overlap)
    while i < len(words):
        block = words[i:i + max_words]
        start, end = block[0].start(), block[-1].end()
        chunks.append((text[start:end], start))
        if i + max_words >= len(words):
            break
        i += step
    return chunks


def aggregate_bio(tokens: List[Tuple[int, int, str, float]]) -> List[Span]:
    """
    Joins per-token labels ("B-FULLNAME", "I-FULLNAME", "O") into spans.
    `tokens` = [(char_start, char_end, label, probability)] for real tokens only.
    """
    spans: List[Span] = []
    current: Optional[List[Any]] = None  # [start, end, tag, [scores]]
    for start, end, label, prob in tokens:
        if label == "O":
            if current:
                spans.append((current[0], current[1], current[2], sum(current[3]) / len(current[3])))
            current = None
            continue
        prefix, _, tag = label.partition("-")
        if current is None or prefix == "B" or tag != current[2]:
            if current:
                spans.append((current[0], current[1], current[2], sum(current[3]) / len(current[3])))
            current = [start, end, tag, [prob]]
        else:
            current[1] = end
            current[3].append(prob)
    if current:
        spans.append((current[0], current[1], current[2], sum(current[3]) / len(current[3])))
    return spans


def _trim(text: str, start: int, end: int) -> Tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def merge_overlaps(spans: List[Span]) -> List[Span]:
    """
    Arbitrates ALL overlapping spans, not just neighbours: the same tag overlapping is one span
    (chunks and token windows overlap); two different tags overlapping cannot both be right, so
    the more confident one wins (the longer one on a tie).
    """
    accepted: List[Span] = []
    for span in sorted(spans, key=lambda s: (s[0], -(s[1] - s[0]))):
        overlapping = [a for a in accepted if span[0] < a[1] and a[0] < span[1]]
        if not overlapping:
            accepted.append(span)
            continue
        same = [a for a in overlapping if a[2] == span[2]]
        if same and len(same) == len(overlapping):
            union = (min([span[0]] + [a[0] for a in same]), max([span[1]] + [a[1] for a in same]), span[2],
                     max([span[3]] + [a[3] for a in same]))
            accepted = [a for a in accepted if a not in same] + [union]
        else:
            best_old = max(overlapping, key=lambda a: (a[3], a[1] - a[0]))
            if (span[3], span[1] - span[0]) > (best_old[3], best_old[1] - best_old[0]):
                accepted = [a for a in accepted if a not in overlapping] + [span]
    return sorted(accepted, key=lambda s: s[0])


_CADASTRAL_GAP = re.compile(r"^[\s,;.\-–a-zA-Z°]{0,25}$")


def join_neighbours(text: str, spans: List[Span]) -> List[Span]:
    """Cadastral figures and "street + number" are one thing to the reader, one code for us."""
    out: List[Span] = []
    for span in sorted(spans, key=lambda s: s[0]):
        if out:
            last = out[-1]
            gap = text[last[1]:span[0]]
            same_cadastre = last[2] == span[2] == "CATASTO" and _CADASTRAL_GAP.match(gap)
            street_number = last[2] == "STREET" and span[2] == "BUILDINGNUM" and len(gap) <= 3
            if same_cadastre or street_number:
                out[-1] = (last[0], span[1], last[2], min(last[3], span[3]))
                continue
        out.append(span)
    return out


class TorchBackend:
    """The actual model. Imported lazily: nothing heavy is loaded unless the feature is used."""

    def __init__(self, model_dir: str):
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        self._torch = torch
        # no remote code, no network: only the (already verified) files in model_dir
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False)
        self.model = AutoModelForTokenClassification.from_pretrained(
            model_dir, local_files_only=True, trust_remote_code=False)
        self.model.eval()
        self.id2label = {int(k): v for k, v in self.model.config.id2label.items()}
        ensure_torch_threads(torch)  # the same fixed policy as the OCR, set once

    def predict(self, texts: List[str]) -> List[List[Span]]:
        """Spans per text. A text longer than MAX_TOKENS is read in overlapping token windows."""
        torch = self._torch
        enc = self.tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=MAX_TOKENS,
                             stride=TOKEN_STRIDE, return_overflowing_tokens=True, return_offsets_mapping=True)
        owner = enc.pop("overflow_to_sample_mapping").tolist()
        offsets = enc.pop("offset_mapping")
        result: List[List[Span]] = [[] for _ in texts]
        window_batch = 8
        for first in range(0, len(owner), window_batch):
            rows = range(first, min(first + window_batch, len(owner)))
            batch = {k: v[first:first + window_batch] for k, v in enc.items()}
            with torch.no_grad():
                probs = torch.softmax(self.model(**batch).logits, dim=-1)
            best_prob, best_id = probs.max(dim=-1)
            for local, row in enumerate(rows):
                tokens = []
                for i in range(offsets.shape[1]):
                    start, end = int(offsets[row, i, 0]), int(offsets[row, i, 1])
                    if end <= start:  # special / padding tokens
                        continue
                    tokens.append((start, end, self.id2label[int(best_id[local, i])], float(best_prob[local, i])))
                result[owner[row]].extend(aggregate_bio(tokens))
        return [merge_overlaps(spans) for spans in result]


class NerDetector:
    """
    States shown to the user (`status()["state"]`):
      missing -> files not there · verifying -> hash check running · ready -> verified and usable ·
      rejected -> files differ from the pinned ones · error -> loading or running failed · off -> switched off
    """

    def __init__(self, model_dir: Optional[str] = None, backend: Any = None,
                 expected_sha256: Optional[Dict[str, str]] = None):
        self._model_dir = model_dir
        self.extended = False
        self.enabled = True
        self._backend = backend
        # a stand-in backend (tests) needs no files; the real one is verified against the pins
        self._expected = (EXPECTED_SHA256 if expected_sha256 is None and backend is None else expected_sha256) or {}
        self._load_lock = threading.Lock()
        self._infer_lock = threading.Lock()   # one inference at a time: the model is shared
        self._verified: Optional[bool] = True if backend is not None else None
        self._verify_thread: Optional[threading.Thread] = None
        self._failure: Optional[str] = None

    # ----- verification (background, once) -----
    def _files_present(self) -> bool:
        return bool(self._model_dir) and all(os.path.exists(os.path.join(self._model_dir, f)) for f in MODEL_FILES)

    def start_verification(self):
        """Hashes the files in the background so the check never blocks the interface."""
        with self._load_lock:
            if self._verified is not None or self._verify_thread or not self._files_present():
                return
            self._verify_thread = threading.Thread(target=self._verify, daemon=True)
            self._verify_thread.start()

    def _verify(self):
        try:
            ok = all(sha256_of(os.path.join(self._model_dir, name)) == digest
                     for name, digest in self._expected.items())
        except OSError:
            ok = False
        with self._load_lock:
            self._verified = ok
            if not ok:
                self._failure = "i file del modello non corrispondono a quelli verificati: non usato"

    def _wait_verified(self) -> bool:
        self.start_verification()
        thread = self._verify_thread
        if thread is not None:
            thread.join()
        return bool(self._verified)

    # ----- state shown to the user -----
    def status(self) -> Dict[str, Any]:
        self.start_verification()
        if self._backend is None and not self._files_present():
            state, reason = "missing", "modello non installato: si usano solo le regole"
        elif self._failure:
            state = "rejected" if self._verified is False else "error"
            reason = self._failure
        elif self._verified is None:
            state, reason = "verifying", "verifica dei file in corso"
        elif not self.enabled:
            state, reason = "off", "disattivato dalle impostazioni"
        else:
            state, reason = "ready", "attivo"
        usable = state in ("ready", "off")
        return {"state": state, "available": usable, "enabled": self.enabled,
                "active": state == "ready", "extended": self.extended, "reason": reason}

    @property
    def active(self) -> bool:
        return self.status()["active"]

    # ----- loading (once, only after the check passed) -----
    def _load(self) -> bool:
        with self._load_lock:
            if self._backend is not None:
                return True
            if self._failure:
                return False
        if not self._wait_verified():
            return False
        with self._load_lock:
            if self._backend is None:
                try:
                    self._backend = TorchBackend(self._model_dir)
                except Exception as exc:  # missing library, damaged file...
                    self._failure = f"modello non utilizzabile ({type(exc).__name__}): si usano solo le regole"
                    return False
            return True

    # ----- detection -----
    @staticmethod
    def _tag_map(extended: bool) -> Dict[str, str]:
        return {**CORE_TAGS, **(EXTENDED_TAGS if extended else {})}

    def detect(self, text: str, cancel: Optional[threading.Event] = None,
               progress: Optional[Callable[[int, int], None]] = None) -> List[Dict[str, Any]]:
        """
        Candidates [{"raw", "category", "score"}]. [] when the model is not usable, when it fails
        (ALL partial results are dropped and the failure becomes visible) or when cancelled.
        """
        if self._backend is None and not self._wait_verified():
            return []
        if not self.enabled or not self._load():
            return []
        extended = self.extended  # snapshot: a toggle during the run applies from the next one
        try:
            chunks = chunk_text(text)
            spans: List[Span] = []
            batch = 8
            for index in range(0, len(chunks), batch):
                if cancel is not None and cancel.is_set():
                    return []  # interrupted: a half-read document must not look fully analysed
                group = chunks[index:index + batch]
                with self._infer_lock:
                    predicted = self._backend.predict([c for c, _ in group])
                for (_, offset), found in zip(group, predicted):
                    spans.extend((s + offset, e + offset, tag, score) for s, e, tag, score in found)
                if progress:
                    progress(min(index + batch, len(chunks)), len(chunks))
            return self._to_candidates(text, spans, extended)
        except Exception as exc:
            self._failure = f"errore durante il riconoscimento ({type(exc).__name__}): si usano solo le regole"
            return []

    def _to_candidates(self, text: str, spans: List[Span], extended: bool = False) -> List[Dict[str, Any]]:
        tags = self._tag_map(extended)
        spans = join_neighbours(text, merge_overlaps([s for s in spans if s[2] in tags]))
        candidates = []
        for start, end, tag, score in spans:
            start, end = _trim(text, start, end)
            category = tags.get(tag)
            raw = text[start:end]
            if not category or len(raw) < 2 or score < MIN_SCORE:
                continue
            if category in STRUCTURED and not _shape_ok(category, raw):
                continue  # a guess that does not even look like the identifier it claims to be
            candidates.append({"raw": raw, "category": category, "score": round(score, 3)})
        return candidates
