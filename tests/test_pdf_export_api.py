"""PDF export through the API: the original is received, processed and never kept."""
import os
import shutil
import tempfile
import unittest

import fitz

from backend.vault import Vault

TEXT = ("Contratto tra Valerio De Santis e Finint S.p.A.\n"
        "Il Sig. Valerio De Santis, C.F. KFBZMW80A01H501A, paga sul conto IT60X0542811101000000123456.\n")


def make_pdf(text=TEXT, image_only=False):
    doc = fitz.open()
    page = doc.new_page()
    if image_only:
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60), False)
        pix.clear_with(200)
        page.insert_image(fitz.Rect(50, 50, 250, 250), pixmap=pix)
    else:
        page.insert_text((50, 80), text.splitlines()[0], fontsize=11)
        page.insert_text((50, 110), text.splitlines()[1], fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


class TestPdfExport(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import app as app_module
        self.service = app_module.doc_service
        self.dir = tempfile.mkdtemp()
        self._saved = (self.service.vault, self.service.save_delay)
        self.service.vault = Vault(self.dir)
        self.service.vault.setup("password-di-prova")
        self.service.save_delay = 0
        self.client = TestClient(app_module.app, base_url="http://127.0.0.1:8765",
                                 headers={"X-PrivateDoc-Token": app_module.APP_TOKEN})
        up = self.client.post("/api/upload", files=[("files", ("atto.txt", TEXT.encode(), "text/plain"))]).json()
        self.sid = up["session_id"]

    def tearDown(self):
        self.service.vault, self.service.save_delay = self._saved
        self.service.sessions.clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def export(self, data, mode="nero", sid=None):
        return self.client.post("/api/export/pdf", data={"session_id": sid or self.sid, "mode": mode},
                                files={"file": ("atto riservato.pdf", data, "application/pdf")})

    @staticmethod
    def text_of(pdf_bytes):
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            return "".join(page.get_text("text") for page in doc)
        finally:
            doc.close()

    def test_protected_data_is_really_gone_from_the_delivered_pdf(self):
        r = self.export(make_pdf())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertGreater(int(r.headers["x-privatedoc-removed"]), 0)
        self.assertNotIn("filename*", r.headers["content-disposition"])
        text = self.text_of(r.content)
        for secret in ("De Santis", "Finint", "KFBZMW80A01H501A", "IT60X0542811101000000123456"):
            self.assertNotIn(secret, text)
        self.assertNotIn(b"De Santis", r.content)

    def test_label_mode_puts_the_placeholder_where_the_text_was(self):
        r = self.export(make_pdf(), mode="etichetta")
        self.assertEqual(r.status_code, 200, r.text)
        text = self.text_of(r.content)
        self.assertNotIn("De Santis", text)
        self.assertIn("[PERSONA_", text)

    def test_the_original_is_never_stored(self):
        self.export(make_pdf())
        self.service.persist(self.sid, immediate=True)
        for root, _dirs, files in os.walk(self.dir):
            for name in files:
                with open(os.path.join(root, name), "rb") as f:
                    self.assertNotIn(b"%PDF", f.read())

    def test_a_scanned_pdf_is_refused_with_a_clear_message(self):
        r = self.export(make_pdf(image_only=True))
        self.assertEqual(r.status_code, 422)
        self.assertIn("OCR", r.json()["detail"])

    def test_not_a_pdf_unknown_case_and_empty_case_are_refused(self):
        self.assertEqual(self.export(b"questo non e' un pdf").status_code, 422)
        self.assertEqual(self.export(make_pdf(), sid="non-esiste").status_code, 404)
        empty = self.client.post("/api/upload", files=[("files", ("v.txt", b"Niente di riservato qui.", "text/plain"))]).json()
        self.assertEqual(self.export(make_pdf(), sid=empty["session_id"]).status_code, 422)

    def test_the_response_is_not_cacheable_and_not_sniffable(self):
        r = self.export(make_pdf())
        self.assertEqual(r.headers["cache-control"], "no-store, private")
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")

    def test_hostile_file_names_never_reach_the_headers(self):
        r = self.client.post("/api/export/pdf", data={"session_id": self.sid, "mode": "nero"},
                             files={"file": ("../../x\r\nSet-Cookie: a=b.pdf", make_pdf(), "application/pdf")})
        self.assertEqual(r.status_code, 200)
        disposition = r.headers["content-disposition"]
        self.assertNotIn("..", disposition)
        self.assertNotIn("Set-Cookie", r.headers)
        self.assertRegex(disposition, r'^attachment; filename="[A-Za-z0-9._-]+_censurato\.pdf"$')

    def test_oversized_uploads_and_pdfs_with_too_many_pages_are_refused(self):
        import app as app_module
        saved = app_module.MAX_UPLOAD_FILE_BYTES
        app_module.MAX_UPLOAD_FILE_BYTES = 500
        try:
            self.assertEqual(self.export(make_pdf()).status_code, 413)
        finally:
            app_module.MAX_UPLOAD_FILE_BYTES = saved
        self.service.MAX_PDF_PAGES = 1
        try:
            doc = fitz.open()
            doc.new_page().insert_text((50, 80), TEXT.splitlines()[0])
            doc.new_page().insert_text((50, 80), "Valerio De Santis")
            two_pages = doc.tobytes()
            r = self.export(two_pages)
            self.assertEqual(r.status_code, 422)
            self.assertIn("pagine", r.json()["detail"])
        finally:
            del self.service.MAX_PDF_PAGES

    def test_too_many_terms_are_refused_and_errors_do_not_echo_the_data(self):
        self.service.MAX_PDF_TERMS = 1
        try:
            r = self.export(make_pdf())
            self.assertEqual(r.status_code, 422)
            self.assertNotIn("De Santis", r.text)
        finally:
            del self.service.MAX_PDF_TERMS

    def test_a_request_without_the_token_is_rejected(self):
        from fastapi.testclient import TestClient
        import app as app_module
        bare = TestClient(app_module.app, base_url="http://127.0.0.1:8765")
        r = bare.post("/api/export/pdf", data={"session_id": self.sid},
                      files={"file": ("a.pdf", make_pdf(), "application/pdf")})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
