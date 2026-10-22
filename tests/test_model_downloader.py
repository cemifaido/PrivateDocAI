"""Model download with a SIMULATED network: no connection is ever made."""
import hashlib
import os
import shutil
import tempfile
import threading
import unittest

from backend.model_downloader import ModelDownloader, DownloadError, default_opener, FILE_SIZES, TOTAL_BYTES, REVISION, BASE_URL

FILES = {"a.bin": b"alpha-" * 5000, "b.json": b'{"k": 1}', "c.txt": b"gamma" * 2000}
EXPECTED = {n: hashlib.sha256(c).hexdigest() for n, c in FILES.items()}
SIZES = {n: len(c) for n, c in FILES.items()}


class FakeResponse:
    def __init__(self, status, body, headers=None, fail_after=None):
        self.status, self.headers, self._body, self._pos, self._fail_after = status, headers or {}, body, 0, fail_after

    def read(self, n):
        if self._fail_after is not None and self._pos >= self._fail_after:
            raise OSError("connessione persa")
        end = min(self._pos + n, len(self._body))
        if self._fail_after is not None:
            end = min(end, self._fail_after)
        block, self._pos = self._body[self._pos:end], end
        return block

    def close(self):
        pass


class FakeServer:
    """Serves FILES; behaviour switches simulate a flaky or misbehaving server."""

    def __init__(self, files=None):
        self.files = dict(files or FILES)
        self.requests = []          # (name, Range header or None)
        self.drop_first_after = None        # cut the first transfer of this file after N bytes
        self.ignore_range = False           # answer 200 with the whole body to a Range request
        self.bad_content_range = False
        self.block = None                   # threading.Event: waits before the first byte (cancel test)
        self._dropped = False

    def __call__(self, url, headers):
        assert url.startswith("https://"), url
        name = url.rsplit("/", 1)[1]
        rng = headers.get("Range")
        self.requests.append((name, rng))
        if self.block is not None:
            self.block.wait(5)
        body = self.files[name]
        if rng:
            start = int(rng.split("=")[1].rstrip("-"))
            if self.ignore_range:
                return FakeResponse(200, body)
            cr = f"bytes {start + 1}-{len(body) - 1}/{len(body)}" if self.bad_content_range \
                else f"bytes {start}-{len(body) - 1}/{len(body)}"
            return FakeResponse(206, body[start:], {"Content-Range": cr})
        fail = None
        if self.drop_first_after is not None and not self._dropped and name == "a.bin":
            self._dropped, fail = True, self.drop_first_after
        return FakeResponse(200, body, fail_after=fail)


class TestDownloader(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.model_dir = os.path.join(self.root, "models", "rizzo")
        self.server = FakeServer()
        self.installed = []

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, **kwargs):
        return ModelDownloader(self.model_dir, on_installed=lambda: self.installed.append(True),
                               opener=self.server, base_url="https://example.test/m/", sizes=SIZES,
                               expected=EXPECTED, sleep=lambda _s: None, check_space=False, **kwargs)

    def run_download(self, downloader):
        self.assertTrue(downloader.start())
        downloader.wait(20)
        return downloader.status()

    def test_a_complete_download_is_installed_and_the_detector_is_told(self):
        status = self.run_download(self.make())
        self.assertEqual(status["state"], "done")
        for name, content in FILES.items():
            with open(os.path.join(self.model_dir, name), "rb") as f:
                self.assertEqual(f.read(), content)
        self.assertFalse(os.path.exists(self.model_dir + ".staging"))
        self.assertEqual(self.installed, [True])

    def test_one_wrong_file_discards_everything_and_activates_nothing(self):
        self.server.files["b.json"] = b'{"k": 2}'                 # same size, different content
        status = self.run_download(self.make())
        self.assertEqual(status["state"], "error")
        self.assertIn("impronta", status["error"])
        self.assertFalse(os.path.exists(self.model_dir))
        self.assertFalse(os.path.exists(self.model_dir + ".staging"))
        self.assertEqual(self.installed, [])

    def test_an_interrupted_transfer_resumes_with_a_range_request(self):
        self.server.drop_first_after = 7000
        status = self.run_download(self.make())
        self.assertEqual(status["state"], "done")
        resumed = [r for r in self.server.requests if r[0] == "a.bin" and r[1]]
        self.assertEqual(resumed, [("a.bin", "bytes=7000-")])
        with open(os.path.join(self.model_dir, "a.bin"), "rb") as f:
            self.assertEqual(f.read(), FILES["a.bin"])

    def test_a_server_that_ignores_range_never_gets_its_answer_appended(self):
        self.server.drop_first_after = 7000
        self.server.ignore_range = True
        status = self.run_download(self.make())
        self.assertEqual(status["state"], "done")                 # restarted from zero, not corrupted
        with open(os.path.join(self.model_dir, "a.bin"), "rb") as f:
            self.assertEqual(f.read(), FILES["a.bin"])

    def test_an_inconsistent_content_range_is_refused(self):
        self.server.drop_first_after = 7000
        self.server.bad_content_range = True
        status = self.run_download(self.make())
        self.assertEqual(status["state"], "error")
        self.assertFalse(os.path.exists(self.model_dir))

    def test_a_file_bigger_than_declared_is_refused(self):
        self.server.files["c.txt"] = FILES["c.txt"] + b"extra"
        status = self.run_download(self.make())
        self.assertEqual(status["state"], "error")
        self.assertFalse(os.path.exists(self.model_dir))

    def test_cancel_stops_cleans_the_staging_folder_and_changes_nothing(self):
        self.server.block = threading.Event()
        downloader = self.make()
        self.assertTrue(downloader.start())
        downloader.cancel()
        self.server.block.set()
        downloader.wait(20)
        self.assertEqual(downloader.status()["state"], "cancelled")
        self.assertFalse(os.path.exists(self.model_dir))
        self.assertFalse(os.path.exists(self.model_dir + ".staging"))
        self.assertEqual(self.installed, [])

    def test_a_second_start_while_running_is_refused(self):
        self.server.block = threading.Event()
        downloader = self.make()
        self.assertTrue(downloader.start())
        self.assertFalse(downloader.start())
        downloader.cancel()
        self.server.block.set()
        downloader.wait(20)

    def test_a_damaged_folder_is_replaced_only_after_the_new_one_is_verified(self):
        os.makedirs(self.model_dir)
        with open(os.path.join(self.model_dir, "a.bin"), "wb") as f:
            f.write(b"damaged")
        self.server.files["b.json"] = b'{"k": 2}'
        self.run_download(self.make())                            # fails: the old folder must survive
        with open(os.path.join(self.model_dir, "a.bin"), "rb") as f:
            self.assertEqual(f.read(), b"damaged")
        self.server.files["b.json"] = FILES["b.json"]
        self.assertEqual(self.run_download(self.make())["state"], "done")
        with open(os.path.join(self.model_dir, "a.bin"), "rb") as f:
            self.assertEqual(f.read(), FILES["a.bin"])
        self.assertFalse(os.path.exists(self.model_dir + ".old"))

    def test_only_https_addresses_are_ever_opened(self):
        with self.assertRaises(DownloadError):
            default_opener("http://example.test/model.bin", {})

    def test_the_pinned_source_is_one_immutable_commit(self):
        self.assertRegex(REVISION, r"^[0-9a-f]{40}$")
        self.assertIn(REVISION, BASE_URL)
        self.assertEqual(TOTAL_BYTES, 1_264_687_643)
        self.assertEqual(sum(FILE_SIZES.values()), TOTAL_BYTES)


class TestDownloadThroughTheApi(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import app as app_module
        from backend.vault import Vault
        from backend.ner import NerDetector
        self.app_module, self.root = app_module, tempfile.mkdtemp()
        self.service = app_module.doc_service
        self._saved = (self.service.vault, self.service.ner, self.service.model_downloader, self.service.model_dir)
        self.service.vault = Vault(os.path.join(self.root, "vault"))
        self.service.vault.setup("password-di-prova")
        self.service.model_dir = os.path.join(self.root, "models", "rizzo")
        self.service.ner = NerDetector(model_dir=self.service.model_dir)
        self.server = FakeServer()
        self.service.model_downloader = ModelDownloader(
            self.service.model_dir, on_installed=self.service.reload_detector, opener=self.server,
            base_url="https://example.test/m/", sizes=SIZES, expected=EXPECTED, sleep=lambda _s: None,
            check_space=False)
        self.client = TestClient(app_module.app, base_url="http://127.0.0.1:8765",
                                 headers={"X-PrivateDoc-Token": app_module.APP_TOKEN})

    def tearDown(self):
        (self.service.vault, self.service.ner, self.service.model_downloader, self.service.model_dir) = self._saved
        self.service.sessions.clear()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_nothing_is_downloaded_without_explicit_consent(self):
        self.assertEqual(self.client.post("/api/model/download", json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/model/download", json={"consent": False}).status_code, 400)
        self.assertEqual(self.server.requests, [])

    def test_info_tells_size_license_and_the_pinned_commit(self):
        info = self.client.get("/api/model/info").json()
        self.assertEqual(info["license"], "MIT")
        self.assertEqual(info["total_bytes"], sum(SIZES.values()))
        self.assertEqual(info["revision"], REVISION)

    def test_download_with_consent_installs_and_replaces_the_detector(self):
        before = self.service.ner
        self.assertEqual(self.client.post("/api/model/download", json={"consent": True}).status_code, 200)
        self.service.model_downloader.wait(20)
        status = self.client.get("/api/model/status").json()
        self.assertEqual(status["state"], "done")
        self.assertIsNot(self.service.ner, before)               # a fresh detector over the new folder
        self.assertTrue(os.path.isdir(self.service.model_dir))
        # the test files are not the real model files: the fresh detector does not accept them
        self.assertEqual(self.client.get("/api/ner/status").json()["state"], "missing")

    def test_an_installed_model_is_not_downloaded_again(self):
        self.service.ner = type("Ready", (), {"status": lambda self: {"state": "ready"}})()
        self.assertEqual(self.client.post("/api/model/download", json={"consent": True}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
