import os
import unittest

from backend.anonymizer import DeterministicAnonymizer
from backend.ner import (NerDetector, aggregate_bio, chunk_text, join_neighbours, merge_overlaps, sha256_of)


class FakeBackend:
    """Stands in for the model: finds the strings it was told about, with a given tag and score."""

    def __init__(self, known):
        self.known = known  # {"text": ("TAG", score)}

    def predict(self, texts):
        out = []
        for chunk in texts:
            spans = []
            for needle, (tag, score) in self.known.items():
                start = chunk.find(needle)
                while start != -1:
                    spans.append((start, start + len(needle), tag, score))
                    start = chunk.find(needle, start + 1)
            out.append(spans)
        return out


class TestPureFunctions(unittest.TestCase):

    def test_bio_labels_become_spans(self):
        tokens = [(0, 5, "B-FULLNAME", 0.99), (6, 12, "I-FULLNAME", 0.97), (13, 15, "O", 0.99),
                  (16, 20, "B-CITY", 0.9), (21, 25, "B-CITY", 0.8)]
        spans = aggregate_bio(tokens)
        self.assertEqual([(s[0], s[1], s[2]) for s in spans], [(0, 12, "FULLNAME"), (16, 20, "CITY"), (21, 25, "CITY")])
        self.assertAlmostEqual(spans[0][3], 0.98)

    def test_chunks_overlap_and_keep_global_offsets(self):
        text = " ".join(f"parola{i}" for i in range(300))
        chunks = chunk_text(text, max_words=120, overlap=20)
        self.assertGreater(len(chunks), 2)
        for piece, offset in chunks:
            self.assertEqual(text[offset:offset + len(piece)], piece)
        self.assertIn("parola100", chunks[0][0])
        self.assertIn("parola100", chunks[1][0])  # the overlap repeats it

    def test_same_entity_found_in_two_chunks_becomes_one(self):
        merged = merge_overlaps([(10, 20, "FULLNAME", 0.9), (15, 24, "FULLNAME", 0.95), (30, 35, "CITY", 0.9)])
        self.assertEqual([(s[0], s[1], s[2]) for s in merged], [(10, 24, "FULLNAME"), (30, 35, "CITY")])

    def test_cadastral_figures_and_street_number_are_joined(self):
        text = "Foglio 21, particella 345, sub. 6. Via dei Mille 14."
        def span(piece, tag):
            start = text.index(piece)
            return (start, start + len(piece), tag, 0.99)

        spans = [span("21", "CATASTO"), span("345", "CATASTO"), span("6.", "CATASTO"),
                 span("Via dei Mille", "STREET"), span("14", "BUILDINGNUM")]
        spans[2] = (spans[2][0], spans[2][0] + 1, "CATASTO", 0.99)  # just the "6", not the full stop
        joined = join_neighbours(text, spans)
        self.assertEqual([(text[s[0]:s[1]], s[2]) for s in joined],
                         [("21, particella 345, sub. 6", "CATASTO"), ("Via dei Mille 14", "STREET")])


class TestDetector(unittest.TestCase):
    TEXT = "Il Sig. Giuseppe Esposito abita a Bergamo, età 42 anni, R.G. 2210/2026. Contatto: Zorbax SRL."

    def _detector(self, extended=False, known=None):
        known = known or {"Giuseppe Esposito": ("FULLNAME", 0.99), "Bergamo": ("CITY", 0.99), "42": ("AGE", 0.99),
                          "2210/2026": ("DOCID", 0.99), "Zorbax SRL": ("ORG", 0.60)}
        detector = NerDetector(backend=FakeBackend(known), expected_sha256=None)
        detector.extended = extended
        return detector

    def test_default_profile_leaves_city_and_age_readable(self):
        found = {(c["category"], c["raw"]) for c in self._detector().detect(self.TEXT)}
        self.assertIn(("PERSONA", "Giuseppe Esposito"), found)
        self.assertIn(("RIFERIMENTO", "2210/2026"), found)
        self.assertNotIn("CITTA", {c for c, _ in found})
        self.assertNotIn("ETA", {c for c, _ in found})

    def test_extended_profile_adds_the_context_categories(self):
        found = {c["category"] for c in self._detector(extended=True).detect(self.TEXT)}
        self.assertTrue({"CITTA", "ETA"} <= found)

    def test_low_confidence_guesses_are_dropped(self):
        found = [c["raw"] for c in self._detector().detect(self.TEXT)]
        self.assertNotIn("Zorbax SRL", found)  # score 0.60 < threshold

    def test_cancel_stops_the_work(self):
        import threading
        cancel = threading.Event()
        cancel.set()
        self.assertEqual(self._detector().detect(self.TEXT, cancel=cancel), [])

    def test_missing_model_is_reported_not_silent(self):
        detector = NerDetector(model_dir=os.path.join(os.getcwd(), "non_esiste"))
        self.assertFalse(detector.active)
        self.assertIn("non installato", detector.status()["reason"])
        self.assertEqual(detector.detect(self.TEXT), [])

    def test_weights_that_do_not_match_the_pinned_hash_are_refused(self):
        import tempfile
        from backend.ner import MODEL_FILES
        folder = tempfile.mkdtemp()
        for name in MODEL_FILES:
            with open(os.path.join(folder, name), "wb") as f:
                f.write(b"x")
        detector = NerDetector(model_dir=folder)  # the real pinned hashes
        self.assertEqual(detector.detect(self.TEXT), [])
        status = detector.status()
        self.assertEqual(status["state"], "rejected")
        self.assertFalse(status["active"])
        self.assertIn("non corrispondono", status["reason"])

    def test_the_state_is_verifying_until_the_files_have_been_checked(self):
        import threading
        import tempfile
        from backend import ner as ner_module
        folder = tempfile.mkdtemp()
        for name in ner_module.MODEL_FILES:
            with open(os.path.join(folder, name), "wb") as f:
                f.write(b"x")
        gate = threading.Event()
        real_hash = ner_module.sha256_of
        ner_module.sha256_of = lambda path: (gate.wait(5), real_hash(path))[1]
        try:
            detector = NerDetector(model_dir=folder)
            self.assertEqual(detector.status()["state"], "verifying")   # never "active" before the check
            self.assertFalse(detector.active)
            gate.set()
            detector._verify_thread.join()
            self.assertEqual(detector.status()["state"], "rejected")
        finally:
            ner_module.sha256_of = real_hash

    def test_status_does_not_reveal_the_folder_path(self):
        self.assertNotIn("model_dir", self._detector().status())

    def test_a_failure_in_the_middle_drops_everything_and_is_visible(self):
        class Breaks(FakeBackend):
            calls = 0

            def predict(self, texts):
                Breaks.calls += 1
                if Breaks.calls > 1:
                    raise RuntimeError("memoria esaurita")
                return super().predict(texts)

        text = " ".join(["parola"] * 400 + ["Giuseppe Esposito"])
        detector = NerDetector(backend=Breaks({"Giuseppe Esposito": ("FULLNAME", 0.99)}))
        self.assertEqual(detector.detect(text * 3), [])      # first batch fine, then the error
        status = detector.status()
        self.assertEqual(status["state"], "error")
        self.assertIn("RuntimeError", status["reason"])

    def test_model_only_guesses_for_fixed_shape_identifiers_must_look_right(self):
        known = {"parola": ("EMAIL", 0.99), "x@y": ("EMAIL", 0.99), "mario@studio.it": ("EMAIL", 0.99),
                 "piano": ("PIVA", 0.99), "garbo": ("EMAIL", 0.30)}
        found = {c["raw"] for c in self._detector(known=known).detect(
            "Scrivere a mario@studio.it e non a parola, x@y, piano o garbo.")}
        self.assertEqual(found, {"mario@studio.it"})

    def test_a_setting_changed_during_the_run_applies_from_the_next_one(self):
        detector = self._detector()

        class Toggler(FakeBackend):
            def predict(self, texts):
                detector.extended = True        # the user ticks the box while the model is working
                return super().predict(texts)

        detector._backend = Toggler({"Bergamo": ("CITY", 0.99), "Giuseppe Esposito": ("FULLNAME", 0.99)})
        detector.extended = False
        self.assertNotIn("CITTA", {c["category"] for c in detector.detect(self.TEXT)})   # snapshot at the start
        self.assertIn("CITTA", {c["category"] for c in detector.detect(self.TEXT)})      # the next run uses it

    def test_overlapping_spans_of_different_tags_keep_the_more_confident_one(self):
        merged = merge_overlaps([(0, 10, "FULLNAME", 0.90), (5, 15, "ORG", 0.99), (12, 20, "FULLNAME", 0.95)])
        self.assertEqual([s[2] for s in merged], ["ORG"])   # the ORG beats both overlapping guesses
        for first, second in zip(merged, merged[1:]):
            self.assertLessEqual(first[1], second[0])       # nothing is left half-overlapping


class TestMergeWithRules(unittest.TestCase):

    def _analyse(self, text, model_items):
        a = DeterministicAnonymizer()
        a.analyze_documents([{"id": "d0", "filename": "a.txt", "text": text}], extra_candidates={"d0": model_items})
        return a, a.mask_text(text, doc_key="d0")

    def test_a_surname_is_no_longer_left_in_clear_when_the_model_sees_the_whole_name(self):
        text = "Testimone: Anna Maria Colombo, di anni 42."
        a, masked = self._analyse(text, [{"raw": "Anna Maria Colombo", "category": "PERSONA", "score": 1.0}])
        self.assertNotIn("Colombo", masked)
        self.assertNotIn("Maria", masked)

    def test_model_category_replaces_a_capital_letter_guess(self):
        a, masked = self._analyse("L'atto è al Catasto Fabbricati.",
                                  [{"raw": "Catasto Fabbricati", "category": "SOCIETA", "score": 1.0}])
        self.assertEqual({r["category"] for r in a.registry if r["canonical"] == "catasto fabbricati"}, {"SOCIETA"})

    def test_structured_identifiers_keep_the_rule_category(self):
        a, _ = self._analyse("IBAN IT60X0542811101000000123456 indicato.",
                             [{"raw": "IT60X0542811101000000123456", "category": "PERSONA", "score": 1.0}])
        self.assertEqual([r["category"] for r in a.registry], ["IBAN"])

    def test_a_long_name_in_one_document_does_not_unmask_the_short_form_in_another(self):
        a = DeterministicAnonymizer()
        docs = [{"id": "A", "filename": "a.txt", "text": "Anna Maria firma il verbale."},
                {"id": "B", "filename": "b.txt", "text": "Anna Maria Colombo testimonia."}]
        a.analyze_documents(docs, extra_candidates={
            "A": [], "B": [{"raw": "Anna Maria Colombo", "category": "PERSONA", "score": 1.0}]})
        self.assertNotIn("Anna Maria", a.mask_text(docs[0]["text"], doc_key="A"))
        self.assertNotIn("Colombo", a.mask_text(docs[1]["text"], doc_key="B"))

    def test_two_people_sharing_a_first_name_and_one_short_mention(self):
        a = DeterministicAnonymizer()
        text = "Anna Maria Colombo e Anna Maria Verdi. Poi Anna Maria ha detto la verità."
        a.analyze_documents([{"id": "A", "filename": "a.txt", "text": text}], extra_candidates={"A": [
            {"raw": "Anna Maria Colombo", "category": "PERSONA", "score": 1.0},
            {"raw": "Anna Maria Verdi", "category": "PERSONA", "score": 1.0}]})
        masked = a.mask_text(text, doc_key="A")
        for word in ("Anna", "Maria", "Colombo", "Verdi"):
            self.assertNotIn(word, masked)

    def test_role_words_from_the_model_are_ignored_even_without_a_definition(self):
        a, masked = self._analyse("La Compagnia contesta e il Tribunale decide.",
                                  [{"raw": "Compagnia", "category": "SOCIETA", "score": 1.0},
                                   {"raw": "Tribunale", "category": "ORG", "score": 1.0}])
        self.assertIn("La Compagnia contesta", masked)
        self.assertEqual(a.registry, [])

    def test_a_confident_model_corrects_only_a_weak_guess_of_the_rules(self):
        weak = "Il documento è di Mario Rossi."               # two capital letters, nothing else
        strong = "Il documento è dell'Avv. Mario Rossi."      # a title in front: strong evidence
        for text, expected in ((weak, "SOCIETA"), (strong, "PERSONA")):
            a, _ = self._analyse(text, [{"raw": "Mario Rossi", "category": "SOCIETA", "score": 0.99}])
            self.assertEqual({r["category"] for r in a.registry if r["canonical"] == "mario rossi"},
                             {expected}, text)
        a, _ = self._analyse(weak, [{"raw": "Mario Rossi", "category": "SOCIETA", "score": 0.90}])
        self.assertEqual({r["category"] for r in a.registry if r["canonical"] == "mario rossi"}, {"PERSONA"})

    def test_the_same_word_defined_for_two_parties_in_two_acts_is_not_guessed(self):
        a = DeterministicAnonymizer()
        docs = [{"id": "A", "filename": "a.txt",
                 "text": "Zeta Holding s.p.a. (d'ora in avanti denominata Omega) decide."},
                {"id": "B", "filename": "b.txt",
                 "text": "Kappa Servizi s.r.l. (d'ora in avanti denominata Omega) risponde."}]
        a.analyze_documents(docs)
        self.assertNotIn("Omega", a.mask_text(docs[0]["text"], doc_key="A"))   # inside its own act: bound
        request = a.mask_text("Confronta Omega con le altre parti.")            # no act: ambiguous, not guessed
        self.assertIn("Omega", request)
        self.assertIn("Omega", a.find_unmasked_suspects(request))

    def test_unassigned_names_survive_the_next_upload_and_a_reopen(self):
        text = "Kappa Servizi s.r.l. (d'ora in avanti, rispettivamente, “Alfonso” e “Kappa”). Alfonso risponde."
        a = DeterministicAnonymizer()
        a.analyze_documents([{"id": "A", "filename": "a.txt", "text": text}])
        a.analyze_documents([{"id": "B", "filename": "b.txt", "text": "Un altro atto qualunque."}])  # next upload
        self.assertIn("Alfonso", a.unassigned_terms)
        reopened = DeterministicAnonymizer.from_dict(a.to_dict())
        self.assertIn("Alfonso", reopened.unassigned_terms)
        reopened.forget_document("A")
        self.assertNotIn("Alfonso", reopened.unassigned_terms)

    def test_without_the_model_nothing_changes(self):
        text = "Mario Rossi firma."
        a = DeterministicAnonymizer()
        a.analyze_documents([{"id": "d0", "filename": "a.txt", "text": text}])
        b = DeterministicAnonymizer()
        b.analyze_documents([{"id": "d0", "filename": "a.txt", "text": text}], extra_candidates={"d0": []})
        self.assertEqual(a.get_registry(), b.get_registry())


class TestModelThroughTheApi(unittest.TestCase):
    """End to end with a stand-in model: visible status, masking of what only the model finds, settings."""

    def setUp(self):
        import shutil
        import tempfile
        from fastapi.testclient import TestClient
        import app as app_module
        from backend.vault import Vault
        self.app_module = app_module
        self.dir = tempfile.mkdtemp()
        self._shutil = shutil
        self.service = app_module.doc_service
        self._saved = (self.service.vault, self.service.ner, self.service.save_delay)
        self.service.vault = Vault(self.dir)
        self.service.vault.setup("password-di-prova")
        self.service.save_delay = 0
        self.service.ner = NerDetector(
            backend=FakeBackend({"Colombo Anna Maria": ("FULLNAME", 0.99), "2210/2026": ("DOCID", 0.99)}),
            expected_sha256=None)
        self.client = TestClient(app_module.app, base_url="http://127.0.0.1:8765",
                                 headers={"X-PrivateDoc-Token": app_module.APP_TOKEN})

    def tearDown(self):
        self.service.vault, self.service.ner, self.service.save_delay = self._saved
        self.service.sessions.clear()
        self._shutil.rmtree(self.dir, ignore_errors=True)

    def test_status_is_visible_and_settings_can_be_changed(self):
        status = self.client.get("/api/ner/status").json()
        self.assertTrue(status["active"])
        self.assertEqual(self.client.post("/api/ner/settings", json={"extended": True}).json()["extended"], True)
        off = self.client.post("/api/ner/settings", json={"enabled": False}).json()
        self.assertFalse(off["active"])
        self.assertIn("disattivato", off["reason"])

    def test_without_the_model_the_status_says_so(self):
        self.service.ner = NerDetector(model_dir=os.path.join(self.dir, "assente"))
        status = self.client.get("/api/ner/status").json()
        self.assertFalse(status["available"])
        self.assertIn("non installato", status["reason"])

    def test_a_model_that_breaks_never_breaks_the_upload(self):
        class Broken:
            def predict(self, texts):
                raise RuntimeError("memoria esaurita")

        self.service.ner = NerDetector(backend=Broken(), expected_sha256=None)
        up = self.client.post("/api/upload", files=[
            ("files", ("atto.txt", "Mario Rossi, IBAN IT60X0542811101000000123456.".encode(), "text/plain"))])
        self.assertEqual(up.status_code, 200)
        doc = up.json()["documents"][0]
        self.assertEqual(doc["model"], "errore")                       # shown to the user
        prompt = self.client.post("/api/prompt/generate",
                                  json={"session_id": up.json()["session_id"], "instruction": "x"}).json()["prompt"]
        self.assertNotIn("IT60X0542811101000000123456", prompt)        # the rules still did their job
        self.assertEqual(self.client.get("/api/ner/status").json()["state"], "error")

    def test_cancelling_during_the_model_keeps_the_document_with_rules_only(self):
        service = self.service

        class CancelsWhileReading(FakeBackend):
            def predict(self, texts):
                service.extractor.cancel_event.set()
                return super().predict(texts)

        service.ner = NerDetector(backend=CancelsWhileReading({"Colombo Anna Maria": ("FULLNAME", 0.99)}),
                                  expected_sha256=None)
        up = self.client.post("/api/upload", files=[
            ("files", ("atto.txt", b"Testimone Colombo Anna Maria.", "text/plain"))]).json()
        self.assertEqual(up["documents"][0]["model"], "interrotto")     # honest: not fully analysed
        prompt = self.client.post("/api/prompt/generate",
                                  json={"session_id": up["session_id"], "instruction": "x"}).json()["prompt"]
        self.assertIn("Colombo", prompt)                                # the model's finding was dropped: rules only

    def _detector_over_files(self, content, expected):
        from backend import ner as ner_module
        folder = os.path.join(self.dir, "modello")
        os.makedirs(folder)
        for name in ner_module.MODEL_FILES:
            with open(os.path.join(folder, name), "wb") as f:
                f.write(content)
        return NerDetector(model_dir=folder, expected_sha256={n: expected for n in ner_module.MODEL_FILES},
                           backend_factory=lambda _dir: FakeBackend({"Colombo Anna Maria": ("FULLNAME", 0.99)}))

    def test_an_upload_during_the_verification_waits_for_the_model(self):
        import hashlib
        import threading
        from backend import ner as ner_module
        gate = threading.Event()
        real_hash = ner_module.sha256_of
        ner_module.sha256_of = lambda path: (gate.wait(5), real_hash(path))[1]
        try:
            self.service.ner = self._detector_over_files(b"x", hashlib.sha256(b"x").hexdigest())
            self.assertEqual(self.service.ner.status()["state"], "verifying")
            threading.Timer(0.3, gate.set).start()      # the check ends while the upload is waiting
            up = self.client.post("/api/upload", files=[
                ("files", ("atto.txt", b"Testimone Colombo Anna Maria.", "text/plain"))]).json()
        finally:
            gate.set()
            ner_module.sha256_of = real_hash
        self.assertEqual(up["documents"][0]["model"], "ok")             # not silently rules-only
        prompt = self.client.post("/api/prompt/generate",
                                  json={"session_id": up["session_id"], "instruction": "x"}).json()["prompt"]
        self.assertNotIn("Colombo", prompt)

    def test_files_that_fail_the_check_are_reported_as_rules_only(self):
        self.service.ner = self._detector_over_files(b"x", "0" * 64)
        up = self.client.post("/api/upload", files=[
            ("files", ("atto.txt", b"Testimone Colombo Anna Maria.", "text/plain"))]).json()
        self.assertEqual(up["documents"][0]["model"], "rifiutato")
        self.assertEqual(self.client.get("/api/ner/status").json()["state"], "rejected")

    def test_a_cancel_during_the_hashing_does_not_wait_for_the_end_of_the_check(self):
        import hashlib
        import threading
        import time
        from backend import ner as ner_module
        gate = threading.Event()
        real_hash = ner_module.sha256_of
        ner_module.sha256_of = lambda path: (gate.wait(10), real_hash(path))[1]
        try:
            detector = self._detector_over_files(b"x", hashlib.sha256(b"x").hexdigest())
            cancel = threading.Event()
            threading.Timer(0.3, cancel.set).start()
            started = time.time()
            self.assertEqual(detector.detect("Testimone Colombo Anna Maria.", cancel=cancel), [])
            self.assertLess(time.time() - started, 3)        # returned long before the 10 s of hashing
        finally:
            gate.set()
            ner_module.sha256_of = real_hash

    def test_a_model_switched_off_during_the_verification_is_off_and_never_waited_for(self):
        import hashlib
        import threading
        import time
        from backend import ner as ner_module
        gate = threading.Event()
        real_hash = ner_module.sha256_of
        ner_module.sha256_of = lambda path: (gate.wait(10), real_hash(path))[1]
        try:
            detector = self._detector_over_files(b"x", hashlib.sha256(b"x").hexdigest())
            detector.enabled = False
            self.assertEqual(detector.status()["state"], "off")
            started = time.time()
            self.assertEqual(detector.detect("Testimone Colombo Anna Maria."), [])
            self.assertLess(time.time() - started, 3)
        finally:
            gate.set()
            ner_module.sha256_of = real_hash

    def test_a_failure_wins_over_a_backend_loaded_before_it(self):
        detector = NerDetector(backend=FakeBackend({}), expected_sha256=None)
        detector._failure = "RuntimeError: memoria esaurita"
        self.assertFalse(detector._load())

    def test_what_only_the_model_finds_is_masked_in_the_prompt(self):
        text = b"Testimone Colombo Anna Maria nel giudizio 2210/2026."
        up = self.client.post("/api/upload", files=[("files", ("atto.txt", text, "text/plain"))]).json()
        prompt = self.client.post("/api/prompt/generate",
                                  json={"session_id": up["session_id"], "instruction": "x"}).json()["prompt"]
        self.assertNotIn("Colombo", prompt)
        self.assertNotIn("2210/2026", prompt)


@unittest.skipUnless(os.environ.get("PRIVATEDOC_NER_DIR_TEST"), "needs the real model (set PRIVATEDOC_NER_DIR_TEST)")
class TestRealModel(unittest.TestCase):
    def test_finds_what_the_rules_miss(self):
        detector = NerDetector(model_dir=os.environ["PRIVATEDOC_NER_DIR_TEST"])
        text = ("R.G. n. 2210/2026. Il Sig. Giuseppe Esposito, C.F. TQXGBN71C12H703A, abita in Via dei Mille 14. "
                "Testimone: Anna Maria Colombo. Carta d'identità n. CA12345AB.")
        found = {c["raw"] for c in detector.detect(text)}
        for expected in ("Giuseppe Esposito", "Anna Maria Colombo", "CA12345AB", "TQXGBN71C12H703A"):
            self.assertIn(expected, found)
        self.assertEqual(len(sha256_of(os.path.join(os.environ["PRIVATEDOC_NER_DIR_TEST"], "model.safetensors"))), 64)


if __name__ == "__main__":
    unittest.main()
