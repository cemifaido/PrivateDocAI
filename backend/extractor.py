import os
import re
import io
import zipfile
import queue
import tempfile
import time
import threading
import warnings
from email import policy
from email.parser import BytesParser
from typing import List, Dict, Any, Optional

import fitz  # PyMuPDF
import docx
import openpyxl
import xlrd
import extract_msg

from .runtime import ocr_model_dir

class DocumentExtractor:
    """
    Handles multi-format extraction from files and archives:
    - .zip (recursive, sanitized against zip slip)
    - .eml (MIME email headers + body + attachments)
    - .msg (Outlook email headers + body + attachments)
    - .pdf (text extraction + fallback note)
    - .docx (paragraphs + tables)
    - .odt (ODF XML text extraction)
    - .xlsx / .xls (tabular markdown format)
    - .txt / .csv / .md / .json
    """

    ALLOWED_EXTENSIONS = {
        '.pdf', '.docx', '.doc', '.odt', 
        '.xlsx', '.xls', '.csv', 
        '.eml', '.msg', 
        '.txt', '.md', '.json',
        '.zip'
    }

    IGNORE_FILES = {'__macosx', '.ds_store', 'thumbs.db', 'desktop.ini'}

    MAX_ZIP_BYTES = 50 * 1024 * 1024  # 50 MB
    # OCR runs on the CPU. Pages are read in parallel by several workers, each with its own
    # reader (measured here: 4 workers about 1.6x faster than one; more workers do not help).
    OCR_DPI = 100
    OCR_MAX_WORKERS = 4

    MAX_ZIP_FILES = 100
    MAX_ZIP_DEPTH = 3

    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = temp_dir or os.path.join(tempfile.gettempdir(), 'cryptodoc_extractor')
        os.makedirs(self.temp_dir, exist_ok=True)
        self._ocr_readers: List[Any] = []
        self._ocr_unavailable = False
        self._torch_threads_set = False
        self._ocr_lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.on_progress = None  # callable(pages_done, pages_total, file_name)
        self.current_name = ""

    def begin_job(self, on_progress=None):
        """
        Starts a new upload job with its OWN cancel event and progress callback. The previous
        event is never cleared: workers abandoned by an interrupted job keep seeing it set, so
        they stop by themselves and cannot report progress for the new job.
        """
        self.cancel_event = threading.Event()
        self.on_progress = on_progress
        self.current_name = ""

    def _get_ocr_readers(self, wanted: int) -> List[Any]:
        """Up to `wanted` EasyOCR readers (created on demand); empty list when EasyOCR is missing."""
        if self._ocr_unavailable:
            return []
        try:
            import easyocr
            model_dir = ocr_model_dir()
            kwargs = {'model_storage_directory': model_dir, 'download_enabled': False} if model_dir else {}
            # CPU-only on purpose: silence the "no GPU" notices, they are not errors
            warnings.filterwarnings("ignore", message=".*pin_memory.*")
            while len(self._ocr_readers) < wanted:
                self._ocr_readers.append(easyocr.Reader(['it', 'en'], gpu=False, verbose=False, **kwargs))
            if not self._torch_threads_set:
                self._torch_threads_set = True
                try:  # share the cores among the workers instead of oversubscribing them
                    import torch
                    cores = os.cpu_count() or 4
                    # more threads than physical cores (about half the logical ones) slows torch down
                    torch.set_num_threads(min(max(1, cores // self.OCR_MAX_WORKERS), max(1, cores // 2)))
                except Exception:
                    pass
        except Exception:
            if not self._ocr_readers:
                self._ocr_unavailable = True
        return self._ocr_readers[:wanted]

    @staticmethod
    def _render_page_png(page, dpi: int) -> bytes:
        return page.get_pixmap(dpi=dpi).tobytes("png")

    @staticmethod
    def _ocr_with_tesseract(png: bytes) -> str:
        try:
            import pytesseract
            from PIL import Image
            return pytesseract.image_to_string(Image.open(io.BytesIO(png)), lang='ita+eng')
        except Exception:
            return ""

    def _ocr_pages(self, doc, page_numbers: List[int]) -> Dict[int, Optional[str]]:
        """
        Reads the given pages (0-based). Pages are rendered in tranches (bounded memory) and each
        tranche is split among the workers. A page that was not read because the user interrupted
        the upload maps to None.
        """
        results: Dict[int, Optional[str]] = {}
        total = len(page_numbers)
        if total == 0:
            return results

        cancel = self.cancel_event          # this job's context, captured once
        on_progress = self.on_progress
        name = self.current_name
        with self._ocr_lock:
            readers = self._get_ocr_readers(min(self.OCR_MAX_WORKERS, total))
            workers = max(1, len(readers))
            done = 0
            if on_progress:
                on_progress(0, total, name)

            for start in range(0, total, workers * 3):
                tranche = page_numbers[start:start + workers * 3]
                if cancel.is_set():
                    results.update({n: None for n in tranche})
                    continue
                # fitz is not thread-safe: render here, recognise in the workers
                rendered = [(n, self._render_page_png(doc[n], self.OCR_DPI)) for n in tranche]
                jobs: "queue.Queue" = queue.Queue()
                for item in rendered:
                    jobs.put(item)
                counter_lock = threading.Lock()

                def worker(reader):
                    nonlocal done
                    while True:
                        try:
                            n, png = jobs.get_nowait()
                        except queue.Empty:
                            return
                        if cancel.is_set():
                            results[n] = None
                            continue
                        try:
                            if reader:
                                text = "\n".join(reader.readtext(png, detail=0, canvas_size=1280, batch_size=4))
                            else:
                                text = self._ocr_with_tesseract(png)
                        except Exception:
                            text = ""
                        results[n] = text
                        with counter_lock:
                            done += 1
                            if on_progress:
                                on_progress(done, total, name)

                pairs = [(threading.Thread(target=worker, args=(readers[i] if readers else None,), daemon=True),
                          readers[i] if readers else None) for i in range(workers)]
                for t, _reader in pairs:
                    t.start()
                while any(t.is_alive() for t, _ in pairs):
                    if cancel.is_set():
                        # A page already being read cannot be stopped midway (up to ~25 s here):
                        # do not wait for it. Its reader is dropped from the pool, so the next
                        # run builds a fresh one instead of sharing a reader that is still busy.
                        busy = [r for t, r in pairs if t.is_alive() and r is not None]
                        self._ocr_readers = [r for r in self._ocr_readers if not any(r is b for b in busy)]
                        break
                    time.sleep(0.1)
                if cancel.is_set():
                    break
        final = dict(results)  # late writes by abandoned workers must not change the outcome
        for n in page_numbers:
            final.setdefault(n, None)
        return final

    def extract_from_bytes(self, filename: str, content: bytes) -> List[Dict[str, Any]]:
        return self.extract_with_report(filename, content)[0]

    @staticmethod
    def _skip(skipped: Optional[List[Dict[str, str]]], path: str, reason: str):
        """Records a file that will not be part of the analysis (name, full path, why)."""
        if skipped is not None:
            skipped.append({"filename": path.split(" > ")[-1].replace("\\", "/").split("/")[-1],
                            "path": path, "reason": reason})

    def _is_system_junk(self, name: str) -> bool:
        lowered = name.lower()
        return (not name or name.startswith(('._', '~$')) or lowered in self.IGNORE_FILES)

    def extract_with_report(self, filename: str, content: bytes):
        """
        Like extract_from_bytes, but also returns the files that were left out and why.
        `filename` may be a path ("Cartella/sub/atto.pdf") when a whole folder is uploaded.
        """
        skipped: List[Dict[str, str]] = []
        path = filename.replace("\\", "/")
        base = path.rsplit("/", 1)[-1]
        ext = os.path.splitext(base)[1].lower()

        if self._is_system_junk(base) or any(part.lower() == '__macosx' for part in path.split("/")):
            return [], skipped
        if ext == '.zip':
            return self._process_zip(path, content, skipped=skipped), skipped
        doc = self._process_single_file(base, content)
        if not doc:
            self._skip(skipped, path, f"formato non supportato ({ext or 'senza estensione'})")
        else:
            if path != base:
                doc["internal_path"] = path
            self._report_unread_pages(doc, path, skipped)
        return ([doc] if doc else []), skipped

    def _report_unread_pages(self, doc: Dict[str, Any], path: str, skipped: Optional[List[Dict[str, str]]]):
        pages = doc.get("metadata", {}).get("ocr_pages_skipped") or []
        if pages:
            self._skip(skipped, path, f"{len(pages)} pagine scansionate non lette (caricamento interrotto): "
                                      f"da pagina {pages[0]} a {pages[-1]}")

    def _process_zip(
        self,
        zip_name: str,
        content: bytes,
        current_depth: int = 1,
        budget: Optional[Dict[str, int]] = None,
        skipped: Optional[List[Dict[str, str]]] = None
    ) -> List[Dict[str, Any]]:
        results = []
        if current_depth > self.MAX_ZIP_DEPTH:
            self._skip(skipped, zip_name, f"archivio annidato oltre il limite di {self.MAX_ZIP_DEPTH} livelli")
            return [{
                "filename": zip_name,
                "file_type": "zip",
                "text": "[Avviso di sicurezza: superata la profondità massima di 3 livelli di archivi annidati]",
                "metadata": {"error": "max_depth_exceeded"},
                "source_archive": None
            }]

        # The same budget is shared by every recursive level. Resetting counters
        # for nested archives would let an attacker multiply the effective limit.
        if budget is None:
            budget = {"bytes": 0, "files": 0}

        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                members = zf.infolist()
                for index, member in enumerate(members):
                    member_path = f"{zip_name} > {member.filename}"
                    if member.is_dir():
                        continue
                    clean_name = os.path.basename(member.filename)
                    if self._is_system_junk(clean_name):
                        continue
                    
                    # Prevent Zip Slip path traversal
                    if ".." in member.filename or member.filename.startswith(("/", "\\")):
                        self._skip(skipped, member_path, "percorso non sicuro nell'archivio")
                        continue

                    ext = os.path.splitext(clean_name)[1].lower()
                    if ext not in self.ALLOWED_EXTENSIONS:
                        self._skip(skipped, member_path, f"formato non supportato ({ext or 'senza estensione'})")
                        continue

                    # Anti Zip-Bomb checks
                    budget["bytes"] += member.file_size
                    budget["files"] += 1
                    if budget["bytes"] > self.MAX_ZIP_BYTES or budget["files"] > self.MAX_ZIP_FILES:
                        results.append({
                            "filename": clean_name,
                            "file_type": "zip",
                            "text": "[Blocco di sicurezza: l'archivio supera il limite consentito di 50MB o 100 file]",
                            "metadata": {"error": "zip_bomb_protection_triggered"},
                            "source_archive": zip_name
                        })
                        # this file and every one after it are left out
                        for left_out in members[index:]:
                            if not left_out.is_dir() and os.path.basename(left_out.filename) not in self.IGNORE_FILES:
                                self._skip(skipped, f"{zip_name} > {left_out.filename}",
                                           "limite di sicurezza dell'archivio superato (50 MB o 100 file)")
                        return results

                    member_bytes = zf.read(member.filename)
                    if ext == '.zip':
                        sub_results = self._process_zip(
                            f"{zip_name} > {clean_name}",
                            member_bytes,
                            current_depth + 1,
                            budget,
                            skipped
                        )
                        results.extend(sub_results)
                    else:
                        doc = self._process_single_file(clean_name, member_bytes)
                        if doc:
                            doc["source_archive"] = zip_name
                            doc["internal_path"] = member.filename
                            self._report_unread_pages(doc, member_path, skipped)
                            results.append(doc)
        except Exception as e:
            results.append({
                "filename": zip_name,
                "file_type": "zip",
                "text": f"[Errore durante l'estrazione dell'archivio zip: {str(e)}]",
                "metadata": {"error": str(e)},
                "source_archive": None
            })
        return results

    def _process_single_file(self, filename: str, content: bytes) -> Optional[Dict[str, Any]]:
        self.current_name = filename
        ext = os.path.splitext(filename)[1].lower()
        text = ""
        metadata: Dict[str, Any] = {"file_size": len(content)}

        try:
            if ext == '.pdf':
                text, metadata = self._extract_pdf(content)
            elif ext == '.docx':
                text, metadata = self._extract_docx(content)
            elif ext == '.odt':
                text, metadata = self._extract_odt(content)
            elif ext in ('.xlsx', '.xls'):
                text, metadata = self._extract_excel(content, ext)
            elif ext == '.eml':
                text, metadata = self._extract_eml(content)
            elif ext == '.msg':
                text, metadata = self._extract_msg(content)
            elif ext in ('.txt', '.csv', '.md', '.json'):
                text = content.decode('utf-8', errors='replace')
                metadata["encoding"] = "utf-8"
            else:
                return None

            clean_text = text.replace('\xa0', ' ').replace('\u202f', ' ').replace('\u200b', '').strip() if text else ""
            return {
                "filename": filename,
                "file_type": ext.lstrip('.'),
                "text": clean_text,
                "metadata": metadata,
                "source_archive": None
            }
        except Exception as e:
            return {
                "filename": filename,
                "file_type": ext.lstrip('.'),
                "text": f"[Errore durante l'estrazione del file {filename}: {str(e)}]",
                "metadata": {"error": str(e)},
                "source_archive": None
            }

    def _extract_pdf(self, content: bytes):
        doc = fitz.open(stream=content, filetype="pdf")
        page_count = len(doc)
        layer_text = []
        scanned = []
        for i, page in enumerate(doc):
            t = page.get_text().strip()
            layer_text.append(t)
            if len(t) < 30 and len(page.get_images()) > 0:
                scanned.append(i)
        has_scanned_pages = bool(scanned)

        ocr_texts = self._ocr_pages(doc, scanned)
        ocr_skipped_pages = [n + 1 for n in scanned if ocr_texts.get(n) is None]

        pages_text = []
        for i in range(page_count):
            if i in ocr_texts and ocr_texts[i] is None:
                pages_text.append(f"--- Pagina {i+1} ---\n[Pagina scansionata non letta: caricamento interrotto]")
            elif i in ocr_texts and ocr_texts[i].strip():
                pages_text.append(f"--- Pagina {i+1} (OCR) ---\n{ocr_texts[i].strip()}")
            else:
                pages_text.append(f"--- Pagina {i+1} ---\n{layer_text[i]}")

        full_text = "\n\n".join(pages_text)
        metadata = {
            "page_count": page_count,
            "has_scanned_pages": has_scanned_pages,
            "ocr_pages_skipped": ocr_skipped_pages,
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", "")
        }
        return full_text, metadata

    def _extract_docx(self, content: bytes):
        doc = docx.Document(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        
        # Extract tables
        tables_text = []
        for t_idx, table in enumerate(doc.tables):
            rows_data = []
            for row in table.rows:
                row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                rows_data.append(" | ".join(row_cells))
            if rows_data:
                tables_text.append(f"[Tabella {t_idx+1}]\n" + "\n".join(rows_data))

        parts = []
        if paragraphs:
            parts.append("\n\n".join(paragraphs))
        if tables_text:
            parts.append("\n\n".join(tables_text))

        return "\n\n".join(parts), {"paragraph_count": len(paragraphs), "table_count": len(doc.tables)}

    def _extract_odt(self, content: bytes):
        """Extracts text and tables from OpenDocument Text (.odt) XML container."""
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            if 'content.xml' not in zf.namelist():
                return "[ODT privo di content.xml]", {}
            xml_bytes = zf.read('content.xml')

        root = ET.fromstring(xml_bytes)
        # Find all text:p and text:h tags
        text_elements = []
        for elem in root.iter():
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag in ('p', 'h', 'table-cell'):
                txt = "".join(elem.itertext()).strip()
                if txt:
                    text_elements.append(txt)

        return "\n\n".join(text_elements), {"elements_count": len(text_elements)}

    def _extract_excel(self, content: bytes, ext: str):
        sheets_data = []
        if ext == '.xlsx':
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows = []
                for row in ws.iter_rows(values_only=True):
                    # Filter empty rows
                    if any(cell is not None and str(cell).strip() != "" for cell in row):
                        row_str = " | ".join(str(c).strip() if c is not None else "" for c in row)
                        rows.append(row_str)
                if rows:
                    sheets_data.append(f"### Foglio: {sheet_name}\n" + "\n".join(rows))
            metadata = {"sheets": wb.sheetnames}
        else: # .xls
            wb = xlrd.open_workbook(file_contents=content)
            for sheet_name in wb.sheet_names():
                ws = wb.sheet_by_name(sheet_name)
                rows = []
                for r in range(ws.nrows):
                    row_vals = ws.row_values(r)
                    if any(c is not None and str(c).strip() != "" for c in row_vals):
                        row_str = " | ".join(str(c).strip() for c in row_vals)
                        rows.append(row_str)
                if rows:
                    sheets_data.append(f"### Foglio: {sheet_name}\n" + "\n".join(rows))
            metadata = {"sheets": wb.sheet_names()}

        return "\n\n".join(sheets_data), metadata

    def _extract_eml(self, content: bytes):
        msg = BytesParser(policy=policy.default).parsebytes(content)
        headers = []
        for field in ['From', 'To', 'Cc', 'Bcc', 'Date', 'Subject']:
            val = msg.get(field)
            if val:
                headers.append(f"{field}: {val}")

        body = ""
        # Prefer plain text, fallback to html stripped
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get('Content-Disposition', ''))
                if 'attachment' not in content_disposition:
                    if content_type == 'text/plain':
                        body = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                        break
                    elif content_type == 'text/html' and not body:
                        html = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                        body = self._strip_html(html)
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(msg.get_content_charset() or 'utf-8', errors='replace')

        full_text = "\n".join(headers) + "\n\n--- Corpo Messaggio ---\n" + body
        metadata = {
            "subject": msg.get('Subject', ''),
            "from": msg.get('From', ''),
            "to": msg.get('To', ''),
            "date": msg.get('Date', '')
        }
        return full_text, metadata

    def _extract_msg(self, content: bytes):
        msg = extract_msg.Message(content)
        headers = []
        if msg.sender:
            headers.append(f"From: {msg.sender}")
        if msg.to:
            headers.append(f"To: {msg.to}")
        if msg.cc:
            headers.append(f"Cc: {msg.cc}")
        if msg.date:
            headers.append(f"Date: {msg.date}")
        if msg.subject:
            headers.append(f"Subject: {msg.subject}")

        body = msg.body or ""
        full_text = "\n".join(headers) + "\n\n--- Corpo Messaggio ---\n" + body
        metadata = {
            "subject": msg.subject or "",
            "from": msg.sender or "",
            "to": msg.to or "",
            "date": str(msg.date) if msg.date else ""
        }
        msg.close()
        return full_text, metadata

    def _strip_html(self, html: str) -> str:
        # Simple fast regex HTML stripper
        clean = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<style.*?</style>', '', clean, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r'<br\s*/?>', '\n', clean, flags=re.IGNORECASE)
        clean = re.sub(r'</p>', '\n\n', clean, flags=re.IGNORECASE)
        clean = re.sub(r'<[^>]+>', '', clean)
        clean = re.sub(r'&nbsp;', ' ', clean)
        clean = re.sub(r'&amp;', '&', clean)
        clean = re.sub(r'&lt;', '<', clean)
        clean = re.sub(r'&gt;', '>', clean)
        return clean.strip()
