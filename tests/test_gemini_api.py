"""Optional official Gemini API: simulated network only, the key is never exposed."""
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from unittest import mock

from backend import gemini_api
from backend.vault import Vault

KEY = "AIza" + "x" * 35
MODEL = "gemini-test-model"


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def close(self):
        pass


def blocked(url, headers, body):
    return FakeResponse({"promptFeedback": {"blockReason": "SAFETY"}})


def empty(url, headers, body):
    return FakeResponse({"candidates": [{"content": {"parts": []}}]})


class TestGenerate(unittest.TestCase):
    def test_the_key_travels_in_a_header_never_in_the_address_and_the_text_comes_back(self):
        seen = {}

        def opener(url, headers, body):
            seen.update(url=url, headers=headers, body=json.loads(body))
            return FakeResponse({"candidates": [{"content": {"parts": [{"text": "Ecco "}, {"text": "[PERSONA_1]"}]}}]})

        text = gemini_api.generate(KEY, MODEL, "Testo anonimo [PERSONA_1]", opener=opener)
        self.assertEqual(text, "Ecco [PERSONA_1]")
        self.assertTrue(seen["url"].startswith("https://generativelanguage.googleapis.com/"))
        self.assertNotIn(KEY, seen["url"])
        self.assertEqual(seen["headers"]["x-goog-api-key"], KEY)
        self.assertEqual(seen["body"]["contents"][0]["parts"][0]["text"], "Testo anonimo [PERSONA_1]")

    def test_errors_are_readable_and_never_contain_the_key(self):
        def denied(url, headers, body):
            raise urllib.error.HTTPError(url, 403, "denied " + KEY, {}, None)

        with self.assertRaises(gemini_api.GeminiApiError) as ctx:
            gemini_api.generate(KEY, MODEL, "x", opener=denied)
        self.assertNotIn(KEY, str(ctx.exception))
        self.assertIn("accesso negato", str(ctx.exception))

        def down(url, headers, body):
            raise OSError("rete assente " + KEY)

        with self.assertRaises(gemini_api.GeminiApiError) as ctx:
            gemini_api.generate(KEY, MODEL, "x", opener=down)
        self.assertNotIn(KEY, str(ctx.exception))

    def test_blocked_or_empty_answers_and_bad_input_are_refused(self):
        for opener in (blocked, empty):
            with self.assertRaises(gemini_api.GeminiApiError):
                gemini_api.generate(KEY, MODEL, "x", opener=opener)
        for key, model in (("corta", MODEL), (KEY, "Modello Con Spazi"), (KEY, "../x")):
            with self.assertRaises(gemini_api.GeminiApiError):
                gemini_api.generate(key, model, "x", opener=blocked)


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

    def post(self, **body):
        return self.client.post("/api/gemini-api", json=body)

    def test_it_is_off_by_default_and_the_key_is_never_returned(self):
        status = self.client.get("/api/gemini-api").json()
        self.assertEqual(status, {"configured": False, "model": "", "enabled": False, "acknowledged": False})
        self.assertEqual(self.post(key=KEY, model=MODEL, acknowledged=True).status_code, 200)
        self.assertNotIn(KEY, self.client.get("/api/gemini-api").text)
        self.assertNotIn(KEY, self.post(model=MODEL).text)

    def test_the_key_is_stored_encrypted_in_the_vault(self):
        self.post(key=KEY, model=MODEL, acknowledged=True)
        for root, _dirs, files in os.walk(self.dir):
            for name in files:
                with open(os.path.join(root, name), "rb") as f:
                    self.assertNotIn(KEY.encode(), f.read(), name)

    def test_it_cannot_be_enabled_without_key_model_and_the_notice_being_read(self):
        self.assertEqual(self.post(enabled=True).status_code, 400)
        self.post(key=KEY, model=MODEL)
        self.assertEqual(self.post(enabled=True).status_code, 400)           # notice not acknowledged
        self.post(acknowledged=True)
        self.assertEqual(self.post(enabled=True).status_code, 200)
        self.assertTrue(self.client.get("/api/gemini-api").json()["enabled"])

    def test_removing_the_key_switches_it_off(self):
        self.post(key=KEY, model=MODEL, acknowledged=True)
        self.post(enabled=True)
        self.post(key="")
        status = self.client.get("/api/gemini-api").json()
        self.assertFalse(status["enabled"])
        self.assertFalse(status["configured"])

    def test_bad_key_or_model_formats_are_refused(self):
        self.assertEqual(self.post(key="troppo corta").status_code, 400)
        self.assertEqual(self.post(model="Modello Con Spazi").status_code, 400)

    def test_execution_through_the_api_restores_the_real_data_after_the_usual_check(self):
        text = "Il Sig. Mario Rossi firma.".encode()
        up = self.client.post("/api/upload", files=[("files", ("atto.txt", text, "text/plain"))]).json()
        sid = up["session_id"]
        self.post(key=KEY, model=MODEL, acknowledged=True)
        self.post(enabled=True)
        sent = {}

        def fake_generate(key, model, prompt, **kwargs):
            sent["prompt"] = prompt
            return "Risposta su [PERSONA_1]."

        body = {"session_id": sid, "provider": "gemini_api", "instruction": "riassumi", "confirmed_suspects": []}
        with mock.patch.object(gemini_api, "generate", fake_generate):
            r = self.client.post("/api/execute", json=body).json()
            if r.get("status") == "needs_confirmation":
                body["confirmed_suspects"] = r["suspects"]
                r = self.client.post("/api/execute", json=body).json()
        self.assertEqual(r["status"], "success", r)
        self.assertNotIn("Mario Rossi", sent["prompt"])
        self.assertIn("Mario Rossi", r["result"]["deanonymized_response"])

    def test_it_does_not_run_when_it_is_not_enabled(self):
        up = self.client.post("/api/upload", files=[("files", ("atto.txt", b"Testo.", "text/plain"))]).json()
        r = self.client.post("/api/execute", json={"session_id": up["session_id"], "provider": "gemini_api",
                                                     "instruction": "x", "confirmed_suspects": []}).json()
        self.assertEqual(r["status"], "error")


if __name__ == "__main__":
    unittest.main()
