import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch
import docx
import openpyxl
from fastapi.testclient import TestClient

import app as app_module
from app import app
from backend.vault import Vault, VaultError, WrongPassword, TooManyAttempts
from backend.extractor import DocumentExtractor
from backend.anonymizer import DeterministicAnonymizer
from backend.document_service import DocumentService

def make_client(token=True, host="127.0.0.1:8765", **kwargs):
    headers = {"X-PrivateDoc-Token": app_module.APP_TOKEN} if token else {}
    return TestClient(app, base_url=f"http://{host}", headers=headers, **kwargs)


class TestFullPrivateDocSuite(unittest.TestCase):

    def setUp(self):
        self.extractor = DocumentExtractor()
        self.anonymizer = DeterministicAnonymizer()
        self.service = DocumentService()
        self.client = make_client()
        # every test works on a throw-away, unlocked vault: real data/ is never touched
        self._vault_dir = tempfile.mkdtemp()
        self._real_vault = app_module.doc_service.vault
        app_module.doc_service.vault = Vault(self._vault_dir)
        app_module.doc_service.save_delay = 0
        app_module.doc_service.vault.setup("password-di-prova")

    def tearDown(self):
        app_module.doc_service.vault = self._real_vault
        app_module.doc_service.sessions.clear()
        shutil.rmtree(self._vault_dir, ignore_errors=True)

    # ==========================
    # 1. EXTRACTOR TESTS
    # ==========================
    def test_docx_extraction(self):
        doc = docx.Document()
        doc.add_paragraph("Testo di prova nel contratto")
        table = doc.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = "Cella A"
        table.rows[0].cells[1].text = "Cella B"
        buf = io.BytesIO()
        doc.save(buf)

        res = self.extractor.extract_from_bytes("test.docx", buf.getvalue())
        self.assertEqual(len(res), 1)
        self.assertIn("Testo di prova", res[0]["text"])
        self.assertIn("Cella A", res[0]["text"])

    def test_xlsx_extraction(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Dati"
        ws.append(["Header 1", "Header 2"])
        ws.append(["Valore 1", "Valore 2"])
        buf = io.BytesIO()
        wb.save(buf)

        res = self.extractor.extract_from_bytes("dati.xlsx", buf.getvalue())
        self.assertEqual(len(res), 1)
        self.assertIn("Header 1 | Header 2", res[0]["text"])
        self.assertIn("Valore 1 | Valore 2", res[0]["text"])

    def test_zip_extraction_and_limits(self):
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w') as zf:
            zf.writestr("test1.txt", "Contenuto file 1")
            zf.writestr("subfolder/test2.txt", "Contenuto file 2")
            zf.writestr(".DS_Store", "junk")

        res = self.extractor.extract_from_bytes("archivio.zip", zip_buf.getvalue())
        self.assertEqual(len(res), 2)
        filenames = [r["filename"] for r in res]
        self.assertIn("test1.txt", filenames)
        self.assertIn("test2.txt", filenames)
        self.assertNotIn(".DS_Store", filenames)

    def test_nested_zip_uses_one_global_budget(self):
        inner_buf = io.BytesIO()
        with zipfile.ZipFile(inner_buf, 'w') as inner:
            inner.writestr("one.txt", "one")
            inner.writestr("two.txt", "two")

        outer_buf = io.BytesIO()
        with zipfile.ZipFile(outer_buf, 'w') as outer:
            outer.writestr("nested.zip", inner_buf.getvalue())

        self.extractor.MAX_ZIP_FILES = 2
        res = self.extractor.extract_from_bytes("outer.zip", outer_buf.getvalue())
        self.assertTrue(any(r.get("metadata", {}).get("error") == "zip_bomb_protection_triggered" for r in res))

    # ==========================
    # 2. ANONYMIZER & PRIVACY TESTS
    # ==========================
    def test_deterministic_consistency(self):
        doc1 = {"filename": "doc1.txt", "text": "L'accordo è con Mario Rossi e la società Acme S.r.l. per 150.000 €"}
        doc2 = {"filename": "doc2.txt", "text": "Confermo che Mario Rossi di Acme S.r.l. ha pagato 150.000 €"}
        
        self.anonymizer.analyze_documents([doc1, doc2])
        
        masked1 = self.anonymizer.mask_text(doc1["text"])
        masked2 = self.anonymizer.mask_text(doc2["text"])

        # Same tokens in both documents
        self.assertIn("[PERSONA_1]", masked1)
        self.assertIn("[PERSONA_1]", masked2)
        self.assertIn("[SOCIETA_A]", masked1)
        self.assertIn("[SOCIETA_A]", masked2)
        self.assertIn("[IMPORTO_1]", masked1)
        self.assertIn("[IMPORTO_1]", masked2)

        # No raw data leaks
        self.assertNotIn("Mario Rossi", masked1)
        self.assertNotIn("Mario Rossi", masked2)
        self.assertNotIn("150.000 €", masked1)
        self.assertNotIn("150.000 €", masked2)

    def test_entity_categories_detection(self):
        sample_text = """
        CF: RSSMRA80A01H501U
        P.IVA: 01234567890
        IBAN: IT02L1234512345000000123456
        Email: mario.rossi@provider.it
        Tel: +39 335 1234567
        Indirizzo: Via Garibaldi 12
        Data: 15/10/2026
        """
        entities = self.anonymizer._detect_entities(sample_text)
        categories = {e["category"] for e in entities}
        self.assertIn("CODICE_FISCALE", categories)
        self.assertIn("PARTITA_IVA", categories)
        self.assertIn("IBAN", categories)
        self.assertIn("EMAIL", categories)
        self.assertIn("TELEFONO", categories)
        self.assertIn("INDIRIZZO", categories)
        self.assertIn("DATA", categories)

    def test_de_anonymization(self):
        self.anonymizer.get_or_create_token("Mario Rossi", "PERSONA")
        self.anonymizer.get_or_create_token("Acme S.r.l.", "SOCIETA")
        
        llm_response = "Il contraente [PERSONA_1] si è accordato con [SOCIETA_A]."
        restored = self.anonymizer.de_anonymize_text(llm_response)
        
        self.assertEqual(restored, "Il contraente Mario Rossi si è accordato con Acme S.r.l..")

    def test_damaged_placeholders_are_restored_and_reported(self):
        self.anonymizer.get_or_create_token("Mario Rossi", "PERSONA")
        self.anonymizer.get_or_create_token("Anna Verdi", "PERSONA")
        self.anonymizer.get_or_create_token("Acme S.r.l.", "SOCIETA")
        reply = "[persona_1], [ PERSONA 2 ], PERSONA_1 e [Societa-A] firmano; [PERSONA_9] non esiste; [Allegato A] resta."
        restored, report = self.anonymizer.de_anonymize_with_report(reply)
        self.assertEqual(restored, "Mario Rossi, Anna Verdi, Mario Rossi e Acme S.r.l. firmano; "
                                   "[PERSONA_9] non esiste; [Allegato A] resta.")
        self.assertEqual(len(report["fuzzy"]), 4)
        self.assertEqual(report["unknown"], ["[PERSONA_9]"])       # a known category, but never registered

    def test_exact_placeholders_are_not_reported_and_restored_text_is_not_rescanned(self):
        self.anonymizer.get_or_create_token("Mario Rossi", "PERSONA")
        self.anonymizer.get_or_create_token("Codice PERSONA_1 interno", "ORG")
        restored, report = self.anonymizer.de_anonymize_with_report("Parla [PERSONA_1] per [ORG_1].")
        self.assertEqual(restored, "Parla Mario Rossi per Codice PERSONA_1 interno.")   # inserted text left alone
        self.assertEqual(report, {"fuzzy": [], "unknown": []})

    def test_bare_words_that_are_not_registered_tokens_are_untouched(self):
        self.anonymizer.get_or_create_token("Mario Rossi", "PERSONA")
        text = "Vedi PERSONA_7, SOCIETA_X e la persona 1 del testo."
        restored, report = self.anonymizer.de_anonymize_with_report(text)
        self.assertEqual(restored, text)
        self.assertEqual(report, {"fuzzy": [], "unknown": []})

    def _masked(self, text):
        self.anonymizer.analyze_documents([{"id": "A", "filename": "a.txt", "text": text}])
        return self.anonymizer.mask_text(text, doc_key="A")

    def test_printed_iban_with_valid_checksum_is_masked(self):
        masked = self._masked("Bonifico su IT60 X054 2811 1010 0000 0123 456 entro il termine.")
        self.assertNotIn("X054", masked)
        self.assertNotIn("0123", masked)
        self.assertIn("[IBAN_1]", masked)

    def test_printed_iban_with_wrong_checksum_is_not_guessed_but_compact_ones_stay_masked(self):
        masked = self._masked("Codice IT61 X054 2811 1010 0000 0123 456 e IBAN IT61X0542811101000000123456.")
        self.assertIn("IT61 X054", masked)              # printed form: only a valid checksum accepts it
        self.assertNotIn("IT61X0542811101000000123456", masked)   # compact form: shape is enough, never dropped

    def test_prefixed_vat_number_needs_a_valid_check_digit(self):
        masked = self._masked("Sede legale, IT12345678903 e il codice IT12345678904.")
        self.assertNotIn("IT12345678903", masked)
        self.assertIn("IT12345678904", masked)

    def test_preflight_leak_verification(self):
        self.anonymizer.get_or_create_token("Mario Rossi", "PERSONA")
        
        clean_text = "Il documento menziona [PERSONA_1]."
        leaks_clean = self.anonymizer.verify_masking_coverage(clean_text)
        self.assertEqual(len(leaks_clean), 0)

        leaky_text = "Il documento menziona Mario Rossi chiaramente."
        leaks_dirty = self.anonymizer.verify_masking_coverage(leaky_text)
        self.assertEqual(len(leaks_dirty), 1)
        self.assertEqual(leaks_dirty[0]["value"], "mario rossi")

    def _mask(self, text):
        self.anonymizer.analyze_documents([{"text": text, "filename": "t"}])
        return self.anonymizer.mask_text(text)

    def test_amounts_are_masked(self):
        masked = self._mask("Pagati 150.000 € e 12.000 euro oggi.")
        self.assertNotIn("150.000", masked)
        self.assertNotIn("12.000", masked)

    def test_no_stray_dot_after_company(self):
        masked = self._mask("Contratto con Acme S.r.l. firmato.")
        self.assertIn("[SOCIETA_A] firmato", masked)

    def test_bare_names_particles_and_apostrophes(self):
        masked = self._mask("Cliente: Luigi Verdi. Giovanni De Luca e Mario O'Neil.")
        for plain in ("Luigi", "Verdi", "De Luca", "O'Neil"):
            self.assertNotIn(plain, masked)

    def test_surname_alone_reuses_full_name_token(self):
        masked = self._mask("Mario Rossi ha firmato. Poi Rossi ha pagato. Rossini no.")
        token = self.anonymizer.forward_map["mario rossi"]
        self.assertEqual(masked.count(token), 2)
        self.assertIn("Rossini", masked)

    def test_shared_surname_is_not_guessed_but_flagged(self):
        masked = self._mask("Mario Rossi e Anna Rossi. Rossi ha firmato.")
        self.assertIn("Rossi ha firmato", masked)
        self.assertIn("Rossi", self.anonymizer.find_unmasked_suspects(masked))

    def test_common_document_words_are_not_names(self):
        self._mask("Pagina Uno. Il Tribunale Civile decide.")
        self.assertEqual(self.anonymizer.registry, [])

    def test_every_detected_entity_is_masked(self):
        text = ("Dott. Mario Rossi (RSSMRA80A01H501U), Via Roma 42, mario@acme.it, "
                "+39 335 1234567, IBAN IT02L1234512345000000123456, P.IVA 01234567890, "
                "Acme S.r.l., 150.000 €, 15/10/2026. Luigi Verdi.")
        masked = self._mask(text)
        self.assertEqual(self.anonymizer.verify_masking_coverage(masked), [])
        for entity in self.anonymizer.registry:
            self.assertNotIn(entity["original"], masked)

    def test_payment_card_and_vehicle_plate_are_masked(self):
        masked = self._mask("Carta 4111 1111 1111 1111, targa AB123CD.")
        self.assertNotIn("4111 1111 1111 1111", masked)
        self.assertNotIn("AB123CD", masked)
        self.assertIn("[CARTA_PAGAMENTO_1]", masked)
        self.assertIn("[TARGA_1]", masked)

    def test_preflight_report_is_clean_after_masking(self):
        sid = "leak_session"
        self.service.add_uploaded_files(sid, [("a.txt", "Mario Rossi firma.".encode())])
        report = self.service.preflight_report(sid, "Cosa fa Mario Rossi?")
        self.assertEqual(report["leaks"], [])

    def test_filename_is_never_in_outbound_prompt(self):
        sid = "filename_session"
        filename = "Pratica_Alice_Bianchi.txt"
        self.service.add_uploaded_files(sid, [(filename, b"Documento generico.")])
        prompt = self.service.build_comparison_prompt(sid, "Riassumi il documento.")
        report = self.service.preflight_report(sid, "Riassumi il documento.")
        self.assertNotIn(filename, prompt)
        self.assertNotIn("Alice_Bianchi", prompt)
        self.assertEqual(report["leaks"], [])

    # ==========================
    # 3. FASTAPI API ENDPOINTS TESTS
    # ==========================
    def test_shutdown_requires_the_token_and_locks_the_archive(self):
        self.assertEqual(make_client(token=False).post("/api/shutdown").status_code, 403)
        ok = self.client.post("/api/shutdown")
        self.assertEqual(ok.status_code, 200)
        self.assertFalse(app_module.doc_service.vault.unlocked)

    def test_guide_page_is_served_and_links_the_legal_references(self):
        response = self.client.get("/guida")
        self.assertEqual(response.status_code, 200)
        for needle in ("2016/679", "132", "622", "01/2025", "non costituisce consulenza legale"):
            self.assertIn(needle, response.text)
        self.assertIn('href="/guida"', self.client.get("/").text)

    def test_api_index(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("PrivateDoc AI", response.text)

    def test_api_upload_and_deanonymize_flow(self):
        file_content = b"Contratto con Dott. Mario Rossi della societa Acme S.r.l. per 50.000 EUR."
        files = [('files', ('contratto.txt', file_content, 'text/plain'))]
        
        upload_resp = self.client.post("/api/upload", files=files)
        self.assertEqual(upload_resp.status_code, 200)
        data = upload_resp.json()
        session_id = data["session_id"]
        self.assertTrue(len(data["entities"]) > 0)

        # Generate Prompt
        prompt_resp = self.client.post("/api/prompt/generate", json={
            "session_id": session_id,
            "instruction": "Confronta i prezzi per Mario Rossi"
        })
        self.assertEqual(prompt_resp.status_code, 200)
        p_data = prompt_resp.json()
        self.assertNotIn("Mario Rossi", p_data["prompt"])

        # Manual De-anonymize
        deanonymize_resp = self.client.post("/api/deanonymize", json={
            "session_id": session_id,
            "raw_response": "Risultato: [PERSONA_1] ha approvato."
        })
        self.assertEqual(deanonymize_resp.status_code, 200)
        res_data = deanonymize_resp.json()
        self.assertIn("Mario Rossi", res_data["result"]["deanonymized_response"])

        # Export Word
        export_resp = self.client.get(f"/api/export/docx?session_id={session_id}")
        self.assertEqual(export_resp.status_code, 200)
        self.assertTrue(len(export_resp.content) > 1000)

    def _upload_text(self, text):
        resp = self.client.post("/api/upload", files=[("files", ("a.txt", text.encode(), "text/plain"))])
        return resp.json()["session_id"]

    def test_suspects_ignore_the_fixed_prompt_template(self):
        sid = self._upload_text("Il bene passa a Kalimera domani.")
        suspects = self.client.post("/api/documents/preflight", json={"session_id": sid}).json()["suspects"]
        self.assertEqual(suspects, ["Kalimera"])

    def test_protecting_a_template_word_does_not_block_sending(self):
        sid = self._upload_text("Il bene passa a Kalimera domani.")
        self.client.post("/api/documents/quick-protect",
                         json={"session_id": sid, "term": "RIGOROSAMENTE", "action": "SOCIETA"})
        report = self.client.post("/api/documents/preflight", json={"session_id": sid}).json()
        self.assertEqual(report["leaks"], [])

    def test_quick_protect_actions_clear_the_suspect(self):
        for action in ("SOCIETA", "PERSONA", "IGNORE"):
            sid = self._upload_text("Il bene passa a Kalimera domani.")
            resp = self.client.post("/api/documents/quick-protect",
                                    json={"session_id": sid, "term": "Kalimera", "action": action}).json()
            self.assertEqual(resp["preflight"]["suspects"], [], action)

    def test_session_state_allows_resuming_after_reload(self):
        sid = self._upload_text("Mario Rossi firma.")
        state = self.client.get("/api/session/state", params={"session_id": sid})
        self.assertEqual(state.status_code, 200)
        self.assertEqual(len(state.json()["documents"]), 1)
        self.assertEqual(self.client.get("/api/session/state", params={"session_id": "nope"}).status_code, 404)

    def _scanned_pdf(self, pages):
        import fitz
        from PIL import Image
        png = io.BytesIO()
        Image.new("RGB", (200, 300), "white").save(png, "PNG")
        pdf = fitz.open()
        for _ in range(pages):
            pdf.new_page(width=200, height=300).insert_image(fitz.Rect(0, 0, 200, 300), stream=png.getvalue())
        return pdf.tobytes()

    def test_scanned_pdf_pages_are_all_read_in_order_by_parallel_workers(self):
        import threading

        class FakeReader:
            threads_used = set()

            def readtext(self, png, **kwargs):
                FakeReader.threads_used.add(threading.get_ident())
                import time
                time.sleep(0.05)
                return ["riga"]

        self.extractor.OCR_MAX_WORKERS = 3
        self.extractor._get_ocr_readers = lambda wanted: [FakeReader() for _ in range(wanted)]
        seen = []
        self.extractor.on_progress = lambda done, total, name: seen.append((done, total))
        text, meta = self.extractor._extract_pdf(self._scanned_pdf(7))
        for n in range(1, 8):
            self.assertIn(f"--- Pagina {n} (OCR) ---", text)
        self.assertLess(text.index("Pagina 2 "), text.index("Pagina 3 "))
        self.assertEqual(meta["ocr_pages_skipped"], [])
        self.assertEqual(seen[-1], (7, 7))
        self.assertGreater(len(FakeReader.threads_used), 1)

    def test_interrupting_stops_ocr_and_reports_unread_pages(self):
        class FakeReader:
            def readtext(self, png, **kwargs):
                return ["riga"]

        self.extractor.OCR_MAX_WORKERS = 1
        self.extractor._get_ocr_readers = lambda wanted: [FakeReader()]
        # interrupt as soon as the first page is read
        self.extractor.on_progress = lambda done, total, name: self.extractor.cancel_event.set()
        text, meta = self.extractor._extract_pdf(self._scanned_pdf(8))
        self.assertGreater(len(meta["ocr_pages_skipped"]), 0)
        self.assertIn("caricamento interrotto", text)
        self.extractor.cancel_event.clear()

    def test_interrupt_does_not_wait_for_pages_already_being_read(self):
        import threading
        import time

        class SlowReader:
            def readtext(self, png, **kwargs):
                time.sleep(3)
                return ["riga"]

        self.extractor.OCR_MAX_WORKERS = 2
        self.extractor._ocr_readers = [SlowReader(), SlowReader()]
        self.extractor._get_ocr_readers = lambda wanted: self.extractor._ocr_readers[:wanted]
        threading.Timer(0.4, self.extractor.cancel_event.set).start()
        started = time.time()
        text, meta = self.extractor._extract_pdf(self._scanned_pdf(6))
        self.assertLess(time.time() - started, 1.5)
        self.assertEqual(len(meta["ocr_pages_skipped"]), 6)
        self.assertEqual(self.extractor._ocr_readers, [])  # busy readers are not reused
        self.extractor.cancel_event.clear()

    def test_discarding_an_interrupted_upload_removes_only_what_it_added(self):
        first = self.client.post("/api/upload", data={"operation_id": "op-1"},
                                 files=[("files", ("a.txt", b"Uno", "text/plain"))]).json()
        sid = first["session_id"]
        second = self.client.post("/api/upload", data={"session_id": sid, "operation_id": "op-2"}, files=[
            ("files", ("b.txt", b"Due", "text/plain")),
            ("files", ("foto.jpg", b"\\xff", "image/jpeg")),
        ]).json()
        self.assertEqual(len(second["documents"]), 2)
        result = self.client.post("/api/upload/discard", json={"session_id": sid, "operation_id": "op-2"}).json()
        self.assertEqual([d["filename"] for d in result["documents"]], ["a.txt"])
        self.assertEqual(result["skipped"], [])

    def test_removed_document_keeps_the_other_numbers(self):
        up = self.client.post("/api/upload", files=[
            ("files", ("a.txt", b"Uno", "text/plain")),
            ("files", ("b.txt", b"Due", "text/plain")),
            ("files", ("c.txt", b"Tre", "text/plain")),
        ]).json()
        sid, ids = up["session_id"], [d["id"] for d in up["documents"]]
        docs = self.client.post("/api/documents/remove", json={"session_id": sid, "id": ids[1]}).json()["documents"]
        self.assertEqual([(d["number"], d["filename"]) for d in docs], [(1, "a.txt"), (3, "c.txt")])
        prompt = self.client.post("/api/prompt/generate", json={"session_id": sid, "instruction": "x"}).json()["prompt"]
        self.assertIn("DOCUMENTO 3", prompt)
        self.assertNotIn("Due", prompt)

    def test_only_selected_documents_enter_the_prompt_with_fixed_numbers(self):
        up = self.client.post("/api/upload", files=[
            ("files", ("a.txt", b"Alfa: Mario Rossi firma.", "text/plain")),
            ("files", ("b.txt", b"Beta: Mario Rossi paga.", "text/plain")),
            ("files", ("c.txt", b"Gamma: Luigi Verdi risponde.", "text/plain")),
        ]).json()
        sid = up["session_id"]
        self.assertEqual([d["number"] for d in up["documents"]], [1, 2, 3])
        self.assertTrue(all(d["selected"] for d in up["documents"]))
        ids = [d["id"] for d in up["documents"]]

        docs = self.client.post("/api/documents/select", json={"session_id": sid, "selected_ids": [ids[0], ids[2]]}).json()["documents"]
        self.assertEqual([d["selected"] for d in docs], [True, False, True])
        prompt = self.client.post("/api/prompt/generate", json={"session_id": sid, "instruction": "Confronta"}).json()["prompt"]
        self.assertIn("DOCUMENTO 1 [TXT]", prompt)
        self.assertIn("DOCUMENTO 3 [TXT]", prompt)
        self.assertNotIn("DOCUMENTO 2", prompt)
        self.assertNotIn("Beta", prompt)
        self.assertIn("Alfa", prompt)

    def test_nothing_selected_is_rejected_and_select_all_restores(self):
        up = self.client.post("/api/upload", files=[("files", ("a.txt", b"Testo uno", "text/plain"))]).json()
        sid, doc_id = up["session_id"], up["documents"][0]["id"]
        self.client.post("/api/documents/select", json={"session_id": sid, "selected_ids": []})
        resp = self.client.post("/api/prompt/generate", json={"session_id": sid, "instruction": "x"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.client.post("/api/execute", json={"session_id": sid, "provider": "gemini", "instruction": "x"}).json()["status"], "error")
        self.client.post("/api/documents/select", json={"session_id": sid, "selected_ids": [doc_id]})
        self.assertEqual(self.client.post("/api/prompt/generate", json={"session_id": sid, "instruction": "x"}).status_code, 200)

    def test_adding_a_document_to_an_open_case_keeps_tokens_and_selection(self):
        first = self.client.post("/api/upload", files=[("files", ("a.txt", b"Mario Rossi firma.", "text/plain"))]).json()
        sid = first["session_id"]
        token = next(e["token"] for e in first["entities"] if e["canonical"] == "mario rossi")
        self.client.post("/api/documents/select", json={"session_id": sid, "selected_ids": []})
        second = self.client.post("/api/upload", data={"session_id": sid},
                                  files=[("files", ("b.txt", b"Mario Rossi paga Acme S.r.l.", "text/plain"))]).json()
        self.assertEqual([d["number"] for d in second["documents"]], [1, 2])
        self.assertEqual([d["selected"] for d in second["documents"]], [False, True])
        prompt = self.client.post("/api/prompt/generate", json={"session_id": sid, "instruction": "x"}).json()["prompt"]
        self.assertIn(token, prompt)
        self.assertIn("DOCUMENTO 2", prompt)
        self.assertNotIn("DOCUMENTO 1", prompt)

    def test_unsupported_files_are_reported_with_name_and_path(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("atti/nota.txt", "Mario Rossi firma.")
            zf.writestr("atti/foto/Foto_1.jpg", b"\xff\xd8\xff")
            zf.writestr("__MACOSX/._nota.txt", "x")
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as zf:
            zf.writestr("Pacchetto.zip", buf.getvalue())
            zf.writestr("firma.png", b"\x89PNG")
        docs, skipped = self.extractor.extract_with_report("Tutto.zip", outer.getvalue())
        self.assertEqual([d["filename"] for d in docs], ["nota.txt"])
        paths = {s["path"]: s for s in skipped}
        self.assertIn("Tutto.zip > Pacchetto.zip > atti/foto/Foto_1.jpg", paths)
        self.assertIn("Tutto.zip > firma.png", paths)
        self.assertEqual(paths["Tutto.zip > firma.png"]["filename"], "firma.png")
        self.assertIn("formato non supportato", paths["Tutto.zip > firma.png"]["reason"])
        self.assertEqual(len(skipped), 2)  # system junk (__MACOSX) is not reported

    def test_uploaded_folder_keeps_paths_subfolders_and_nested_zip(self):
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as zf:
            zf.writestr("allegati/mail.eml", "From: a@b.it\nSubject: x\n\nCiao Mario Rossi")
            zf.writestr("allegati/scan.jpg", b"\xff\xd8")
        resp = self.client.post("/api/upload", files=[
            ("files", ("Pratica/contratto.txt", b"Mario Rossi firma", "text/plain")),
            ("files", ("Pratica/sub/livello2/note.txt", b"Acme S.r.l.", "text/plain")),
            ("files", ("Pratica/sub/archivio.zip", inner.getvalue(), "application/zip")),
            ("files", ("Pratica/foto/IMG_1.png", b"\x89PNG", "image/png")),
            ("files", ("Pratica/Thumbs.db", b"x", "application/octet-stream")),
            ("files", ("Pratica/~$bozza.docx", b"x", "application/octet-stream")),
        ]).json()
        names = sorted(d["filename"] for d in resp["documents"])
        self.assertEqual(names, ["contratto.txt", "mail.eml", "note.txt"])
        skipped = {s["path"] for s in resp["skipped"]}
        self.assertEqual(skipped, {"Pratica/foto/IMG_1.png", "Pratica/sub/archivio.zip > allegati/scan.jpg"})

    def test_direct_upload_of_unsupported_file_is_reported(self):
        resp = self.client.post("/api/upload", files=[
            ("files", ("ok.txt", b"Testo", "text/plain")),
            ("files", ("scatto.jpg", b"\xff\xd8", "image/jpeg")),
        ]).json()
        self.assertEqual(resp["document_count"], 1)
        self.assertEqual([s["path"] for s in resp["skipped"]], ["scatto.jpg"])
        state = self.client.get("/api/session/state", params={"session_id": resp["session_id"]}).json()
        self.assertEqual(len(state["skipped"]), 1)

    def test_api_rejects_oversized_upload_while_streaming(self):
        with patch("app.MAX_UPLOAD_FILE_BYTES", 4):
            response = self.client.post(
                "/api/upload",
                files=[("files", ("large.txt", b"12345", "text/plain"))]
            )
        self.assertEqual(response.status_code, 413)

class TestVaultAndSavedCases(unittest.TestCase):

    def setUp(self):
        self.client = make_client()
        self.dir = tempfile.mkdtemp()
        self._real_vault = app_module.doc_service.vault
        app_module.doc_service.vault = Vault(self.dir)
        app_module.doc_service.save_delay = 0

    def tearDown(self):
        app_module.doc_service.vault = self._real_vault
        app_module.doc_service.sessions.clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _unlock(self):
        self.client.post("/api/vault/setup", json={"password": "password-lunga", "confirm": "password-lunga"})

    def test_api_is_locked_until_password_is_set(self):
        status = self.client.get("/api/vault/status").json()
        self.assertEqual(status, {"initialized": False, "unlocked": False, "min_password_length": 12})
        resp = self.client.post("/api/upload", files=[("files", ("a.txt", b"Mario Rossi", "text/plain"))])
        self.assertEqual(resp.status_code, 423)

    def test_setup_requires_matching_and_long_enough_password(self):
        bad = self.client.post("/api/vault/setup", json={"password": "password-lunga", "confirm": "altra-cosa"})
        self.assertEqual(bad.status_code, 400)
        short = self.client.post("/api/vault/setup", json={"password": "corta", "confirm": "corta"})
        self.assertEqual(short.status_code, 400)
        self.assertFalse(self.client.get("/api/vault/status").json()["initialized"])

    def test_wrong_password_is_rejected_and_right_one_unlocks(self):
        self._unlock()
        self.client.post("/api/vault/lock")
        self.assertEqual(self.client.post("/api/vault/unlock", json={"password": "sbagliata1"}).status_code, 401)
        self.assertEqual(self.client.post("/api/vault/unlock", json={"password": "password-lunga"}).status_code, 200)

    def test_case_survives_restart_with_same_tokens(self):
        self._unlock()
        up = self.client.post("/api/upload", files=[("files", ("a.txt", b"Mario Rossi firma per Acme S.r.l.", "text/plain"))]).json()
        sid = up["session_id"]
        token = next(e["token"] for e in up["entities"] if e["canonical"] == "mario rossi")
        self.client.post("/api/documents/quick-protect", json={"session_id": sid, "term": "Kalimera", "action": "RISERVATO"})

        # "restart": new process = empty memory, new Vault object on the same folder
        app_module.doc_service.sessions.clear()
        app_module.doc_service.vault = Vault(self.dir)
        self.assertEqual(self.client.post("/api/vault/unlock", json={"password": "password-lunga"}).status_code, 200)

        cases = self.client.get("/api/pratiche").json()["cases"]
        self.assertEqual([c["id"] for c in cases], [sid])
        state = self.client.post("/api/pratiche/open", json={"id": sid}).json()
        self.assertEqual(len(state["documents"]), 1)
        self.assertEqual(next(e["token"] for e in state["entities"] if e["canonical"] == "mario rossi"), token)
        prompt = self.client.post("/api/prompt/generate", json={"session_id": sid, "instruction": "Riassumi"}).json()["prompt"]
        self.assertIn(token, prompt)
        self.assertNotIn("Mario Rossi", prompt)

    def test_nothing_readable_is_written_to_disk(self):
        self._unlock()
        self.client.post("/api/upload", files=[("files", ("a.txt", b"Mario Rossi firma per Acme S.r.l.", "text/plain"))])
        for root, _dirs, files in os.walk(self.dir):
            for name in files:
                with open(os.path.join(root, name), "rb") as f:
                    content = f.read()
                self.assertNotIn(b"Mario", content)
                self.assertNotIn(b"Rossi", content)

    def test_rename_and_delete_case(self):
        self._unlock()
        sid = self.client.post("/api/upload", files=[("files", ("a.txt", b"Testo", "text/plain"))]).json()["session_id"]
        self.client.post("/api/pratiche/rename", json={"id": sid, "name": "Causa Rossi"})
        self.assertEqual(self.client.get("/api/pratiche").json()["cases"][0]["name"], "Causa Rossi")
        self.client.post("/api/pratiche/delete", json={"id": sid})
        self.assertEqual(self.client.get("/api/pratiche").json()["cases"], [])

    def test_lock_forgets_decrypted_data_in_memory(self):
        self._unlock()
        self.client.post("/api/upload", files=[("files", ("a.txt", b"Testo", "text/plain"))])
        self.client.post("/api/vault/lock")
        self.assertEqual(app_module.doc_service.sessions, {})


class TestHardening(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self._real_vault = app_module.doc_service.vault
        app_module.doc_service.vault = Vault(self.dir)
        app_module.doc_service.save_delay = 0
        app_module.doc_service.vault.setup("password-di-prova")
        self.client = make_client()

    def tearDown(self):
        app_module.doc_service.vault = self._real_vault
        app_module.doc_service.sessions.clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _upload(self, *names_and_texts, **data):
        files = [("files", (n, x.encode(), "text/plain")) for n, x in names_and_texts]
        return self.client.post("/api/upload", data=data, files=files).json()

    # ----- local security -----
    def test_hostile_host_is_refused_even_with_the_token(self):
        # DNS rebinding: the browser sends the attacker's host name
        resp = make_client(host="evil.example").get("/api/vault/status")
        self.assertEqual(resp.status_code, 400)

    def test_localhost_host_is_case_insensitive(self):
        resp = make_client(host="LOCALHOST").get("/api/vault/status")
        self.assertEqual(resp.status_code, 200)

    def test_hostile_origin_is_refused(self):
        resp = self.client.post("/api/vault/lock", headers={"Origin": "https://evil.example"})
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(app_module.doc_service.vault.unlocked)

    def test_api_needs_the_token_but_the_page_does_not(self):
        anonymous = make_client(token=False)
        self.assertEqual(anonymous.get("/api/pratiche").status_code, 403)
        self.assertEqual(anonymous.get("/").status_code, 200)

    def test_served_page_embeds_the_current_token_and_it_is_not_static(self):
        page = make_client(token=False).get("/").text
        self.assertIn(app_module.APP_TOKEN, page)
        self.assertNotIn("__APP_TOKEN__", page)
        with open(os.path.join(app_module.static_dir, "app.js"), encoding="utf-8") as script:
            self.assertNotIn(app_module.APP_TOKEN, script.read())

    def test_unrecognised_words_need_confirmation_before_sending(self):
        sid = self._upload(("a.txt", "Il bene passa a Kalimera domani."))["session_id"]
        body = {"session_id": sid, "provider": "claude", "instruction": "x"}
        first = self.client.post("/api/execute", json=body).json()
        self.assertEqual(first["status"], "needs_confirmation")
        self.assertIn("Kalimera", first["suspects"])
        confirmed = self.client.post("/api/execute", json={**body, "confirmed_suspects": first["suspects"]}).json()
        self.assertNotEqual(confirmed["status"], "needs_confirmation")

    def test_stale_suspect_confirmation_does_not_authorize_a_changed_set(self):
        sid = self._upload(("a.txt", "Il bene passa a Kalimera domani."))["session_id"]
        body = {"session_id": sid, "provider": "claude", "instruction": "x"}
        first = self.client.post("/api/execute", json=body).json()
        changed = self.client.post("/api/execute", json={
            **body,
            "instruction": "Parlane anche con Zebulon",
            "confirmed_suspects": first["suspects"],
        }).json()
        self.assertEqual(changed["status"], "needs_confirmation")
        self.assertIn("Zebulon", changed["suspects"])

    def test_frequent_changes_are_written_together_not_one_by_one(self):
        import time
        service = app_module.doc_service
        service.save_delay = 0.4
        saves = []
        real_save = service.vault.save
        service.vault.save = lambda cid, data: (saves.append(cid), real_save(cid, data))[1]
        first = self._upload(("a.txt", "Uno"))  # also writes nothing yet
        sid = first["session_id"]
        for n in range(5):
            self.client.post("/api/documents/select", json={"session_id": sid, "selected_ids": []})
        self.assertEqual(saves, [])             # nothing written during the burst
        time.sleep(0.9)
        self.assertEqual(saves, [sid])          # one single write afterwards
        # listing the cases flushes anything still waiting
        self.client.post("/api/documents/select", json={"session_id": sid, "selected_ids": [first["documents"][0]["id"]]})
        self.assertEqual(self.client.get("/api/pratiche").json()["cases"][0]["document_count"], 1)
        self.assertEqual(len(saves), 2)

    def test_dist_check_fails_when_working_data_is_present(self):
        import check_dist
        clean = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(clean, "_internal"))
            open(os.path.join(clean, "PrivateDocAI.exe"), "wb").close()
            self.assertEqual(check_dist.scan(clean), [])
            os.makedirs(os.path.join(clean, "data", "pratiche"))
            open(os.path.join(clean, "data", "pratiche", "x.enc"), "wb").close()
            os.makedirs(os.path.join(clean, "profiles"))
            found = [os.path.relpath(p, clean) for p in check_dist.scan(clean)]
            self.assertIn("data", found)
            self.assertIn("profiles", found)
            self.assertIn(os.path.join("data", "pratiche", "x.enc"), found)
        finally:
            shutil.rmtree(clean, ignore_errors=True)

    def test_token_in_the_url_is_not_accepted(self):
        anonymous = make_client(token=False)
        resp = anonymous.get(f"/api/pratiche?t={app_module.APP_TOKEN}")
        self.assertEqual(resp.status_code, 403)

    def test_lock_during_a_running_send_voids_the_answer(self):
        service = app_module.doc_service
        sid = self._upload(("a.txt", "Il bene passa a Mario Rossi domani."))["session_id"]
        self.client.post("/api/documents/quick-protect", json={"session_id": sid, "term": "Il", "action": "IGNORE"})

        def slow_bridge(provider, prompt, *args, **kwargs):
            service.lock_all()                    # the user locks while the provider is answering
            return {"status": "success", "response": "Risposta con [PERSONA_1]"}

        real = service.browser_bridge.execute_prompt
        service.browser_bridge.execute_prompt = slow_bridge
        try:
            resp = self.client.post("/api/execute", json={
                "session_id": sid, "provider": "gemini", "instruction": "x",
                "confirmed_suspects": self.client.post("/api/documents/preflight",
                                                       json={"session_id": sid, "instruction": "x"}).json()["suspects"]})
        finally:
            service.browser_bridge.execute_prompt = real
        self.assertEqual(resp.status_code, 423)
        self.assertEqual(service.sessions, {})   # the decrypted session did not come back

    def test_lock_between_final_check_and_commit_voids_the_answer(self):
        service = app_module.doc_service
        sid = self._upload(("a.txt", "testo semplice senza nomi"))["session_id"]
        real_commit = service.process_llm_response_if_current

        def lock_before_commit(session_id, response, expected_epoch):
            service.lock_all()
            return real_commit(session_id, response, expected_epoch)

        real_bridge = service.browser_bridge.execute_prompt
        service.browser_bridge.execute_prompt = lambda provider, prompt: {
            "status": "success", "response": "RISPOSTA RISERVATA"
        }
        service.process_llm_response_if_current = lock_before_commit
        try:
            resp = self.client.post("/api/execute", json={
                "session_id": sid, "provider": "gemini", "instruction": "analizza"
            })
        finally:
            service.process_llm_response_if_current = real_commit
            service.browser_bridge.execute_prompt = real_bridge
        self.assertEqual(resp.status_code, 423)
        self.assertFalse(service.vault.unlocked)
        self.assertEqual(service.sessions, {})

    def test_lock_during_extraction_discards_the_upload_commit(self):
        service = app_module.doc_service
        real_extract = service.extractor.extract_with_report

        def lock_during_extract(filename, content):
            service.lock_all()
            return real_extract(filename, content)

        service.extractor.extract_with_report = lock_during_extract
        try:
            resp = self.client.post(
                "/api/upload", files=[("files", ("a.txt", b"dati riservati", "text/plain"))]
            )
        finally:
            service.extractor.extract_with_report = real_extract
        self.assertEqual(resp.status_code, 423)
        self.assertFalse(service.vault.unlocked)
        self.assertEqual(service.sessions, {})

    def test_second_upload_while_one_is_running_gets_409(self):
        service = app_module.doc_service
        self.assertTrue(service._upload_lock.acquire(blocking=False))
        try:
            resp = self.client.post("/api/upload", files=[("files", ("a.txt", b"x", "text/plain"))])
            self.assertEqual(resp.status_code, 409)
        finally:
            service._upload_lock.release()

    def test_progress_of_a_stopped_job_does_not_leak_into_the_next(self):
        service = app_module.doc_service
        service._job_id = "new-job"
        service.progress = {"file": "", "pages_done": 0, "pages_total": 0}
        service._set_progress("old-job", 5, 9, "vecchio.pdf")
        self.assertEqual(service.progress["pages_total"], 0)
        service._set_progress("new-job", 1, 9, "nuovo.pdf")
        self.assertEqual(service.progress["file"], "nuovo.pdf")

    # ----- vault hardening -----
    def test_case_file_copied_onto_another_case_is_rejected(self):
        vault = app_module.doc_service.vault
        a, b = "11111111-aaaa", "22222222-bbbb"
        vault.save(a, {"id": a, "name": "A", "documents": []})
        vault.save(b, {"id": b, "name": "B", "documents": []})
        shutil.copy(vault._case_path(a), vault._case_path(b))
        self.assertEqual(vault.load(a)["name"], "A")
        with self.assertRaises(VaultError):
            vault.load(b)

    def test_v2_case_requires_its_id_inside_the_encrypted_payload(self):
        vault = app_module.doc_service.vault
        cid = "abababab-cdef"
        payload = json.dumps({"name": "senza id", "documents": []}).encode()
        blob = vault._MAGIC + vault._encrypt(vault._require_key(), payload, vault._CASE_AAD + cid.encode())
        vault._write_atomic(vault._case_path(cid), blob)
        with self.assertRaises(VaultError):
            vault.load(cid)

    def test_corrupted_case_is_listed_with_an_error_instead_of_hidden(self):
        vault = app_module.doc_service.vault
        cid = "33333333-cccc"
        vault.save(cid, {"id": cid, "name": "C", "documents": []})
        with open(vault._case_path(cid), "r+b") as f:
            f.truncate(10)
        listed = vault.list_cases()
        self.assertEqual([(c["id"], c["error"]) for c in listed], [(cid, True)])

    def test_kdf_parameters_come_from_the_file_and_are_bounded(self):
        vault = app_module.doc_service.vault
        with open(vault.meta_path, encoding="utf-8") as meta_file:
            meta = json.load(meta_file)
        self.assertEqual(meta["version"], 2)
        self.assertEqual(meta["params"], {"n": 2 ** 16, "r": 8, "p": 2})
        meta["params"]["n"] = 2 ** 28  # tampered: would need gigabytes of memory
        with open(vault.meta_path, "w", encoding="utf-8") as meta_file:
            json.dump(meta, meta_file)
        vault.lock()
        with self.assertRaises(VaultError):
            vault.unlock("password-di-prova")

    def test_wrong_passwords_are_slowed_down_after_a_few_attempts(self):
        vault = app_module.doc_service.vault
        vault.lock()
        for _ in range(4):
            with self.assertRaises(WrongPassword):
                vault.unlock("sbagliata-123456")
        with self.assertRaises(TooManyAttempts):
            vault.unlock("password-di-prova")  # even the right one waits

    # ----- numbering, discard, purge -----
    def test_document_numbers_are_never_reused(self):
        first = self._upload(("a.txt", "Uno"), ("b.txt", "Due"), ("c.txt", "Tre"))
        sid = first["session_id"]
        self.client.post("/api/documents/remove", json={"session_id": sid, "id": first["documents"][2]["id"]})
        added = self._upload(("d.txt", "Quattro"), session_id=sid)
        self.assertEqual([d["number"] for d in added["documents"]], [1, 2, 4])
        # and it survives a restart of the app
        app_module.doc_service.sessions.clear()
        reopened = self.client.post("/api/pratiche/open", json={"id": sid}).json()
        again = self._upload(("e.txt", "Cinque"), session_id=sid)
        self.assertEqual([d["number"] for d in reopened["documents"]], [1, 2, 4])
        self.assertEqual(again["documents"][-1]["number"], 5)

    def test_discard_forgets_the_entities_found_by_that_operation_only(self):
        first = self._upload(("a.txt", "Mario Rossi firma."), operation_id="op-1")
        sid = first["session_id"]
        second = self._upload(("b.txt", "Luigi Verdi paga."), session_id=sid, operation_id="op-2")
        self.assertEqual(len(second["entities"]), 2)
        result = self.client.post("/api/upload/discard", json={"session_id": sid, "operation_id": "op-2"}).json()
        self.assertEqual([e["canonical"] for e in result["entities"]], ["mario rossi"])

    def test_remove_keeps_protected_terms_unless_purge_is_requested(self):
        up = self._upload(("a.txt", "Mario Rossi firma."), ("b.txt", "Luigi Verdi paga."))
        sid, ids = up["session_id"], [d["id"] for d in up["documents"]]
        self.client.post("/api/documents/quick-protect", json={"session_id": sid, "term": "Acme", "action": "SOCIETA"})
        kept = self.client.post("/api/documents/remove", json={"session_id": sid, "id": ids[1]}).json()
        self.assertEqual(kept["purged"], 0)
        self.assertIn("luigi verdi", [e["canonical"] for e in kept["entities"]])
        purged = self.client.post("/api/documents/remove", json={"session_id": sid, "id": ids[0], "purge": True}).json()
        canon = [e["canonical"] for e in purged["entities"]]
        self.assertNotIn("luigi verdi", canon)
        self.assertNotIn("mario rossi", canon)
        self.assertIn("acme", canon)  # chosen by the user: never purged


if __name__ == '__main__':
    unittest.main()
