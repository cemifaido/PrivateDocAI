"""The user's own categories: a library shared by every case, encrypted in the vault."""
import os
import shutil
import tempfile
import unittest

from backend.anonymizer import DeterministicAnonymizer
from backend.vault import Vault, VaultError


class TestNormalisation(unittest.TestCase):
    def test_names_become_safe_identifiers(self):
        n = DeterministicAnonymizer.normalize_category
        self.assertEqual(n("Numero di Protocollo"), "NUMERO_DI_PROTOCOLLO")
        self.assertEqual(n("  Codice cliente  "), "CODICE_CLIENTE")
        self.assertEqual(n("Perizia città"), "PERIZIA_CITTA")

    def test_unusable_names_are_refused(self):
        n = DeterministicAnonymizer.normalize_category
        for bad in ("", "a", "123", "ignore", "x" * 40, "!!"):
            with self.assertRaises(ValueError, msg=bad):
                n(bad)


class TestLibraryInTheVault(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.vault = Vault(self.dir)
        self.vault.setup("password-di-prova")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_a_library_is_saved_encrypted_and_survives_a_relock(self):
        self.vault.save_library("categorie", {"custom": {"PROTOCOLLO": "Protocollo"}})
        with open(os.path.join(self.dir, "categorie.enc"), "rb") as f:
            self.assertNotIn(b"Protocollo", f.read())
        self.vault.lock()
        self.vault.unlock("password-di-prova")
        self.assertEqual(self.vault.load_library("categorie")["custom"], {"PROTOCOLLO": "Protocollo"})

    def test_missing_library_is_empty_and_a_swapped_file_is_refused(self):
        self.assertEqual(self.vault.load_library("categorie"), {})
        self.vault.save_library("categorie", {"custom": {"A_B": "ab"}})
        os.replace(os.path.join(self.dir, "categorie.enc"), os.path.join(self.dir, "altra.enc"))
        with self.assertRaises(VaultError):
            self.vault.load_library("altra")      # bound to its own name: not interchangeable

    def test_the_library_is_not_listed_as_a_case(self):
        self.vault.save_library("categorie", {"custom": {}})
        self.assertEqual(self.vault.list_cases(), [])

    def test_bad_library_names_are_refused(self):
        with self.assertRaises(VaultError):
            self.vault.save_library("../x", {})


class TestThroughTheApi(unittest.TestCase):
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

    def tearDown(self):
        self.service.vault, self.service.save_delay = self._saved
        self.service.sessions.clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _upload(self, text):
        return self.client.post("/api/upload", files=[("files", ("atto.txt", text.encode(), "text/plain"))]).json()

    def test_a_new_category_is_listed_for_every_case(self):
        created = self.client.post("/api/categories", json={"name": "Numero di protocollo interno"}).json()
        self.assertEqual(created["id"], "NUMERO_DI_PROTOCOLLO_INTERNO")
        listed = self.client.get("/api/categories").json()
        self.assertIn("PERSONA", [c["id"] for c in listed["presets"]])
        self.assertEqual([c["id"] for c in listed["custom"]], ["NUMERO_DI_PROTOCOLLO_INTERNO"])
        self.service.sessions.clear()                       # "another project": nothing case-specific
        self.assertEqual(len(self.client.get("/api/categories").json()["custom"]), 1)

    def test_creating_the_same_or_a_preset_category_adds_nothing(self):
        self.client.post("/api/categories", json={"name": "Protocollo"})
        self.client.post("/api/categories", json={"name": "protocollo"})
        self.client.post("/api/categories", json={"name": "Persona"})
        self.assertEqual(len(self.client.get("/api/categories").json()["custom"]), 1)

    def test_an_invalid_name_is_a_clear_error(self):
        self.assertEqual(self.client.post("/api/categories", json={"name": "1"}).status_code, 400)

    def test_masking_with_a_custom_category_and_restoring_the_answer(self):
        self.client.post("/api/categories", json={"name": "Protocollo"})
        up = self._upload("Vedi la nota prot. Zx-8841 del fascicolo.")
        sid = up["session_id"]
        done = self.client.post("/api/documents/quick-protect",
                                json={"session_id": sid, "term": "Zx-8841", "action": "PROTOCOLLO"}).json()
        self.assertIn("[PROTOCOLLO_1]", {e["token"] for e in done["entities"]})
        prompt = self.client.post("/api/prompt/generate", json={"session_id": sid, "instruction": "x"}).json()["prompt"]
        self.assertNotIn("Zx-8841", prompt)
        self.assertIn("[PROTOCOLLO_1]", prompt)
        result = self.client.post("/api/deanonymize", json={
            "session_id": sid, "raw_response": "La nota [protocollo_1] va allegata."}).json()
        self.assertIn("Zx-8841", result["result"]["deanonymized_response"])

    def test_a_category_that_is_not_a_plain_identifier_is_refused(self):
        up = self._upload("Testo qualunque con Alfa.")
        for bad in ("../x", "persona", "A", "X" * 40, "A B"):
            r = self.client.post("/api/documents/quick-protect",
                                 json={"session_id": up["session_id"], "term": "Alfa", "action": bad})
            self.assertEqual(r.status_code, 400, bad)


if __name__ == "__main__":
    unittest.main()
