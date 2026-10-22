"""The user can say that two protected entries are the same party."""
import shutil
import tempfile
import unittest

from backend.anonymizer import DeterministicAnonymizer
from backend.vault import Vault


class TestMergeEntities(unittest.TestCase):
    def setUp(self):
        self.a = DeterministicAnonymizer()
        self.text = "Il contratto con Pippo Uno e con Pluto Due prevede che Pippo Uno consegni."
        self.first = self.a.add_custom_entity("Pippo Uno", "SOCIETA")
        self.second = self.a.add_custom_entity("Pluto Due", "SOCIETA")

    def test_two_entries_become_one_party_with_one_code(self):
        self.assertNotEqual(self.first, self.second)
        self.a.merge_entities(self.second, self.first)
        masked = self.a.mask_text(self.text)
        self.assertEqual(masked.count(self.first), 3)
        self.assertNotIn(self.second, masked)
        self.assertEqual([r["token"] for r in self.a.get_registry()], [self.first])
        self.assertEqual(self.a.de_anonymize_text(masked).count("Pippo Uno"), 3)   # the kept entry is shown back

    def test_the_union_survives_saving_and_a_later_mention(self):
        self.a.merge_entities(self.second, self.first)
        reopened = DeterministicAnonymizer.from_dict(self.a.to_dict())
        self.assertEqual(reopened.get_or_create_token("Pluto Due", "SOCIETA"), self.first)   # the written form is still known
        self.assertNotIn("Pluto", reopened.mask_text("Scrive Pluto Due."))

    def test_refused_when_it_makes_no_sense(self):
        for src, dst in ((self.first, self.first), ("[SOCIETA_99]", self.first), (self.first, "[SOCIETA_99]")):
            with self.assertRaises(ValueError):
                self.a.merge_entities(src, dst)


class TestMergeThroughTheApi(unittest.TestCase):
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

    def test_merging_from_the_interface_reduces_the_list_and_the_prompt_uses_one_code(self):
        up = self.client.post("/api/upload", files=[("files", ("atto.txt",
                              "Pippo Uno consegna a Pluto Due; poi Pluto Due paga Pippo Uno.".encode(), "text/plain"))]).json()
        sid = up["session_id"]
        for name in ("Pippo Uno", "Pluto Due"):
            self.client.post("/api/entity/add", json={"session_id": sid, "text": name, "category": "SOCIETA"})
        entities = self.client.post("/api/entity/add", json={"session_id": sid, "text": "Pippo Uno", "category": "SOCIETA"}).json()["entities"]
        by_name = {e["original"]: e["token"] for e in entities}
        merged = self.client.post("/api/entity/merge", json={"session_id": sid, "source_token": by_name["Pluto Due"],
                                                                "target_token": by_name["Pippo Uno"]})
        self.assertEqual(merged.status_code, 200)
        tokens = {e["token"] for e in merged.json()["entities"] if "Pluto" in e["original"] or "Pippo" in e["original"]}
        self.assertEqual(tokens, {by_name["Pippo Uno"]})
        prompt = self.client.post("/api/prompt/generate", json={"session_id": sid, "instruction": "x"}).json()["prompt"]
        self.assertNotIn("Pluto", prompt)
        self.assertNotIn(by_name["Pluto Due"], prompt)

    def test_a_bad_request_is_a_clear_error(self):
        up = self.client.post("/api/upload", files=[("files", ("a.txt", b"Testo Beta.", "text/plain"))]).json()
        r = self.client.post("/api/entity/merge", json={"session_id": up["session_id"],
                                                          "source_token": "[X_1]", "target_token": "[X_2]"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
