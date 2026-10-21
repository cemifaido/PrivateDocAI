import os
import io
import threading
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
import docx

from .extractor import DocumentExtractor
from .runtime import APP_DIR
from .anonymizer import DeterministicAnonymizer
from .browser_bridge import BrowserBridge
from .vault import Vault

# Type aliases for clean code
Tuple_Session = Dict[str, Any]
Tuple_File = Any

class UploadBusy(Exception):
    """Another upload is still being processed."""


class DocumentService:
    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or os.environ.get("PRIVATEDOC_DATA_DIR") or os.path.join(APP_DIR, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.extractor = DocumentExtractor()
        self.progress: Dict[str, Any] = {"file": "", "pages_done": 0, "pages_total": 0}
        self._job_id = ""
        self._upload_lock = threading.Lock()   # one upload at a time (desktop app)
        self._state_lock = threading.RLock()   # session changes + their snapshot/save
        self._epoch = 0                        # bumped on every lock: work started before it is void
        # Small cases live in ONE encrypted file: instead of rewriting it after every batch or click,
        # changes are marked dirty and written together at most every `save_delay` seconds.
        self.save_delay = 3.0
        self._dirty: set = set()
        self._save_timer: Optional[threading.Timer] = None
        self.browser_bridge = BrowserBridge()
        
        # In-memory sessions; each one is mirrored to an encrypted file once the vault is unlocked
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.vault: Optional[Vault] = None

    def _set_progress(self, job_id: str, done: int, total: int, name: str):
        if job_id == self._job_id:  # a stopped job must not write into the next one
            self.progress = {"file": name, "pages_done": done, "pages_total": total}

    @property
    def state_lock(self) -> "threading.RLock":
        """Held by anything that changes a session outside this class (entity edits, reset)."""
        return self._state_lock

    @property
    def epoch(self) -> int:
        return self._epoch

    def lock_all(self):
        """Saves what is pending, locks the vault and forgets every decrypted session, atomically."""
        with self._state_lock:
            self.flush_pending()
            if self.vault is not None:
                self.vault.lock()
            self.sessions.clear()
            self._epoch += 1

    def cancel_upload(self):
        self.extractor.cancel_event.set()

    # ----- persistence of cases ("pratiche") -----
    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def persist(self, session_id: str, immediate: bool = False):
        """
        Saves the session encrypted (no-op when the vault is missing or locked). Frequent small
        changes are coalesced; `immediate=True` writes now.
        """
        with self._state_lock:
            if immediate or self.save_delay <= 0:
                self._dirty.discard(session_id)
                self._persist_locked(session_id)
                return
            self._dirty.add(session_id)
            if self._save_timer is None:
                self._save_timer = threading.Timer(self.save_delay, self.flush_pending)
                self._save_timer.daemon = True
                self._save_timer.start()

    def flush_pending(self):
        """Writes every change still waiting: called before locking, closing, listing or opening."""
        with self._state_lock:
            timer, self._save_timer = self._save_timer, None
            if timer is not None:
                timer.cancel()
            for session_id in list(self._dirty):
                self._persist_locked(session_id)
            self._dirty.clear()

    def _persist_locked(self, session_id: str):
        session = self.sessions.get(session_id)
        if not session or self.vault is None or not self.vault.unlocked:
            return
        session["updated"] = self._now()
        self.vault.save(session_id, {
            "next_document_number": session.get("next_document_number", 1),
            "id": session_id,
            "name": session["name"],
            "created": session["created"],
            "updated": session["updated"],
            "documents": session["documents"],
            "skipped": session.get("skipped", []),
            "anonymizer": session["anonymizer"].to_dict(),
            "last_result": session.get("last_result"),
            "history": session.get("history", []),
        })

    def open_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Loads a saved case into memory and returns its state."""
        if case_id not in self.sessions:
            data = self.vault.load(case_id)
            self.sessions[case_id] = {
                "id": case_id,
                "name": data["name"],
                "created": data["created"],
                "updated": data["updated"],
                "documents": data["documents"],
                "skipped": data.get("skipped", []),
                "anonymizer": DeterministicAnonymizer.from_dict(data["anonymizer"]),
                "last_result": data.get("last_result"),
                "history": data.get("history", []),
                "next_document_number": data.get("next_document_number", 1),
            }
        return self.get_session_state(case_id)

    def rename_case(self, case_id: str, name: str):
        if case_id not in self.sessions:
            self.open_case(case_id)
        self.sessions[case_id]["name"] = name.strip()[:120] or self.sessions[case_id]["name"]
        self.persist(case_id, immediate=True)

    def delete_case(self, case_id: str):
        with self._state_lock:
            self._dirty.discard(case_id)
        self.sessions.pop(case_id, None)
        if self.vault is not None:
            self.vault.delete(case_id)

    def get_or_create_session(self, session_id: Optional[str] = None) -> Tuple_Session:
        if not session_id or session_id not in self.sessions:
            s_id = session_id or str(uuid.uuid4())
            now = self._now()
            self.sessions[s_id] = {
                "id": s_id,
                "name": "Pratica del " + datetime.now().strftime("%d/%m/%Y %H:%M"),
                "created": now,
                "updated": now,
                "documents": [],
                "anonymizer": DeterministicAnonymizer(),
                "last_result": None,
                "history": []
            }
            return self.sessions[s_id]
        return self.sessions[session_id]

    def add_uploaded_files(self, session_id: str, files: List[Tuple_File],
                           operation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Receives uploaded files [(filename, bytes)], extracts them,
        updates the session documents, and runs deterministic entity analysis.
        `operation_id` groups the batches of one user operation so it can be undone as a whole.
        """
        if not self._upload_lock.acquire(blocking=False):
            raise UploadBusy()
        try:
            return self._add_uploaded_files(session_id, files, operation_id)
        finally:
            self._upload_lock.release()

    def _add_uploaded_files(self, session_id: str, files: List[Tuple_File],
                            operation_id: Optional[str]) -> Dict[str, Any]:
        job_id = str(uuid.uuid4())
        self._job_id = job_id
        self.progress = {"file": "", "pages_done": 0, "pages_total": 0}
        # fresh cancel event + progress callback for THIS job (see DocumentExtractor.begin_job)
        self.extractor.begin_job(on_progress=lambda d, t, n: self._set_progress(job_id, d, t, n))

        extracted_all = []
        for filename, content in files:  # slow part (OCR): outside the state lock
            extracted_all.append(self.extractor.extract_with_report(filename, content))

        with self._state_lock:
            session = self.get_or_create_session(session_id)
            anonymizer: DeterministicAnonymizer = session["anonymizer"]
            skipped_all = session.setdefault("skipped", [])
            new_documents = []
            self._ensure_numbers(session)
            for extracted_docs, skipped in extracted_all:
                for item in skipped:
                    item["operation_id"] = operation_id
                skipped_all.extend(skipped)
                for doc in extracted_docs:
                    doc["id"] = str(uuid.uuid4())
                    doc["operation_id"] = operation_id
                    session["documents"].append(doc)
                    self._ensure_numbers(session)
                    new_documents.append(doc)

            # Analyze only the new documents to extend the deterministic mapping
            anonymizer.current_operation = operation_id
            try:
                entities = anonymizer.analyze_documents(new_documents)
            finally:
                anonymizer.current_operation = None
            self.persist(session["id"])
            return self._upload_result(session, entities)

    def _upload_result(self, session: Dict[str, Any], entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "session_id": session["id"],
            "document_count": len(session["documents"]),
            "documents": self._document_summaries(session),
            "entities": entities,
            "skipped": session["skipped"],
            "name": session["name"]
        }

    @staticmethod
    def _ensure_numbers(session: Dict[str, Any]):
        """
        Each document keeps its number for good ("Documento 3"), even after others are
        removed, so the user's references stay valid.
        """
        docs = session["documents"]
        used = [d["number"] for d in docs if d.get("number")]
        # monotonic counter stored in the case: a number is never given out twice
        next_number = max(session.get("next_document_number", 1), max(used, default=0) + 1)
        for d in docs:
            if not d.get("number"):
                d["number"] = next_number
                next_number += 1
        session["next_document_number"] = next_number

    def discard_added(self, session_id: str, operation_id: str) -> Dict[str, Any]:
        """Undo an interrupted upload operation: its documents, skipped-file reports and entities."""
        with self._state_lock:
            session = self.get_or_create_session(session_id)
            session["documents"] = [d for d in session["documents"] if d.get("operation_id") != operation_id]
            session["skipped"] = [s for s in session.get("skipped", []) if s.get("operation_id") != operation_id]
            session["anonymizer"].remove_by_operation(operation_id)
            self.persist(session_id)
            return {"documents": self._document_summaries(session), "skipped": session["skipped"],
                    "entities": session["anonymizer"].get_registry()}

    def remove_document(self, session_id: str, doc_id: str, purge: bool = False) -> Dict[str, Any]:
        """
        Deletes a document (text included). By default its protected terms stay in the case so the
        codes of earlier answers keep working; with purge=True the automatic ones that no remaining
        document contains are forgotten too.
        """
        with self._state_lock:
            session = self.get_or_create_session(session_id)
            session["documents"] = [d for d in session["documents"] if d["id"] != doc_id]
            purged = 0
            if purge:
                purged = session["anonymizer"].purge_unreferenced([d.get("text", "") for d in session["documents"]])
            self.persist(session_id)
            return {"documents": self._document_summaries(session), "purged": purged,
                    "entities": session["anonymizer"].get_registry()}

    def _document_summaries(self, session: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._ensure_numbers(session)
        return [
            {
                "id": d["id"],
                "number": d["number"],
                "selected": d.get("selected", True),
                "filename": d["filename"],
                "source_archive": d.get("source_archive"),
                "file_type": d["file_type"],
                "char_count": len(d.get("text", "")),
                "metadata": d.get("metadata", {})
            }
            for d in session["documents"]
        ]

    def select_documents(self, session_id: str, selected_ids: List[str]) -> List[Dict[str, Any]]:
        """Only the selected documents are masked, checked and sent."""
        with self._state_lock:
            session = self.get_or_create_session(session_id)
            chosen = set(selected_ids)
            for d in session["documents"]:
                d["selected"] = d["id"] in chosen
            self.persist(session_id)
            return self._document_summaries(session)

    def has_selected_documents(self, session_id: str) -> bool:
        session = self.get_or_create_session(session_id)
        return any(d.get("selected", True) for d in session["documents"])

    def get_masked_corpus(self, session_id: str) -> Dict[str, Any]:
        session = self.get_or_create_session(session_id)
        anonymizer: DeterministicAnonymizer = session["anonymizer"]
        
        masked_docs = []
        self._ensure_numbers(session)
        for doc in session["documents"]:
            if not doc.get("selected", True):
                continue
            masked_text = anonymizer.mask_text(doc.get("text", ""))
            masked_docs.append({
                "number": doc["number"],
                "filename": doc["filename"],
                "source_archive": doc.get("source_archive"),
                "masked_text": masked_text
            })

        return {
            "session_id": session_id,
            "masked_documents": masked_docs,
            "entities_count": len(anonymizer.get_registry())
        }

    def build_comparison_prompt(self, session_id: str, user_instruction: str) -> str:
        """
        Constructs the structured prompt containing all pseudonymized documents
        and clear legal instructions for the LLM.
        """
        corpus = self.get_masked_corpus(session_id)
        masked_docs = corpus["masked_documents"]

        session = self.get_or_create_session(session_id)
        anonymizer: DeterministicAnonymizer = session["anonymizer"]

        # The fixed instructions are masked too: a term the user protects must not
        # stay readable in the template (it would block sending with no way out).
        template = [
            "Sei un assistente giuridico altamente qualificato per professionisti legali, avvocati e magistrati, specializzato nell'analisi di atti processuali, memorie difensive, perizie, contratti e nella loro eventuale traduzione giuridica (italiano / inglese).",
            "I soggetti, le persone fisiche, le denominazioni societarie, gli importi, le date e i dati identificativi contenuti nei testi sono stati rigorosamente protetti tramite identificatori pseudonimi (es. [PERSONA_1], [SOCIETA_A], [IMPORTO_1], [DATA_A], ecc.).",
            "REGOLE FONDAMENTALI PER LA RISPOSTA E PER L'EVENTUALE TRADUZIONE:",
            "1. Mantieni RIGOROSAMENTE inalterati tutti gli identificatori tra parentesi quadre (es. [PERSONA_1], [SOCIETA_A], [DATA_A], [IMPORTO_1]): il sistema locale provvederà a decifrarli e ripristinarli automaticamente in chiaro.",
            "2. Se l'utente richiede una traduzione (es. in inglese o in italiano), traduci con rigore terminologico forense tutto il testo dell'atto, lasciando intatti e immutati i token pseudonimi.",
            "3. Se l'utente richiede un'analisi o parere, fornisci una trattazione giuridica analitica e strutturata (quadro fattuale, eccezioni preliminari/di rito, merito, corrispettivi/scadenze, considerazioni probatorie e conclusioni operative).",
            "\n=== ATTI E DOCUMENTI ==="
        ]
        prompt_parts = [anonymizer.mask_text(line) for line in template]

        for d in masked_docs:
            file_type = d["filename"].rsplit(".", 1)[-1].upper() if "." in d["filename"] else "TESTO"
            source_info = " (estratto da archivio)" if d.get("source_archive") else ""
            prompt_parts.append(
                f"\n--- DOCUMENTO {d['number']} [{file_type}]{source_info} ---\n{d['masked_text']}"
            )

        prompt_parts.append("\n=== RICHIESTA DELL'UTENTE ===")
        masked_instruction = (
            anonymizer.mask_text(user_instruction)
            if user_instruction.strip()
            else "Effettua un'analisi giuridica approfondita degli atti e documenti: riassumi le posizioni delle parti, individua le eccezioni preliminari e di rito, esamina il merito della controversia, evidenzia i corrispettivi e le scadenze contestate, e segnala i profili probatori critici."
        )
        prompt_parts.append(masked_instruction)

        return "\n".join(prompt_parts)

    def preflight_report(self, session_id: str, user_instruction: str = "") -> Dict[str, Any]:
        """
        What would still be readable if the prompt were sent now.
        `leaks`: registered entities left unmasked (must be empty to send).
        `suspects`: capitalized words the detector did not recognise (user should check).
        """
        session = self.get_or_create_session(session_id)
        anonymizer: DeterministicAnonymizer = session["anonymizer"]
        outbound_prompt = self.build_comparison_prompt(session_id, user_instruction)
        # Suspects come from the user's own content only, never from the fixed template
        content = [d["masked_text"] for d in self.get_masked_corpus(session_id)["masked_documents"]]
        content.append(anonymizer.mask_text(user_instruction))
        return {
            "leaks": anonymizer.verify_masking_coverage(outbound_prompt),
            "suspects": anonymizer.find_unmasked_suspects("\n".join(content))
        }

    def get_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Documents and entities of an existing session, so the UI can resume after a reload."""
        session = self.sessions.get(session_id)
        if not session:
            return None
        return {
            "session_id": session["id"],
            "documents": self._document_summaries(session),
            "entities": session["anonymizer"].get_registry(),
            "skipped": session.get("skipped", []),
            "name": session.get("name", "Pratica"),
            "history": session.get("history", [])
        }

    def process_llm_response(self, session_id: str, llm_raw_response: str) -> Dict[str, Any]:
        """
        Takes the raw LLM response (with tokens like [PERSONA_1]) and de-anonymizes it.
        """
        session = self.get_or_create_session(session_id)
        anonymizer: DeterministicAnonymizer = session["anonymizer"]

        restored_response = anonymizer.de_anonymize_text(llm_raw_response)
        
        result = {
            "session_id": session_id,
            "raw_masked_response": llm_raw_response,
            "deanonymized_response": restored_response,
            "entities_restored_count": len(anonymizer.get_registry())
        }
        session["last_result"] = result
        session.setdefault("history", []).append({
            "timestamp": self._now(),
            "raw_masked_response": llm_raw_response,
            "deanonymized_response": restored_response,
        })
        self.persist(session_id, immediate=True)
        return result

    def export_report_docx(self, session_id: str) -> io.BytesIO:
        session = self.get_or_create_session(session_id)
        last_res = session.get("last_result")
        text = last_res["deanonymized_response"] if last_res else "Nessuna analisi completata."

        doc = docx.Document()
        doc.add_heading("Report di Analisi e Traduzione Giuridica", 0)
        
        doc.add_heading("Documenti Inclusi", level=1)
        self._ensure_numbers(session)
        for d in session.get("documents", []):
            if not d.get("selected", True):
                continue
            p = doc.add_paragraph(style='List Bullet')
            p.add_run(f"Documento {d['number']}: {d['filename']}").bold = True
            if d.get("source_archive"):
                p.add_run(f" (in {d['source_archive']})")

        doc.add_heading("Esito dell'Elaborazione / Traduzione", level=1)
        for paragraph in text.split("\n\n"):
            if paragraph.strip():
                doc.add_paragraph(paragraph.strip())

        output = io.BytesIO()
        doc.save(output)
        output.seek(0)
        return output
