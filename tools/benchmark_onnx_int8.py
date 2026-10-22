"""Prototype CPU benchmark for the optional NER model: PyTorch FP32 vs ONNX INT8.

This tool is deliberately outside the application. It never downloads a model and
does not change runtime dependencies. It can:

1. measure the verified local model through the same ``NerDetector`` used by the app;
2. export a separate FP32 ONNX graph and dynamically quantize it to INT8;
3. compare recall by category, latency normalized to 120 words, and process RAM.

Examples::

    python tools/benchmark_onnx_int8.py --model-dir MODELS/rizzo-pii-0.3B
    python tools/benchmark_onnx_int8.py --model-dir MODEL --prepare-onnx C:/tmp/ner-onnx
    python tools/benchmark_onnx_int8.py --model-dir MODEL --onnx-int8 C:/tmp/ner-onnx/model.int8.onnx

The legacy exporter used for ModernBERT requires ``onnx``; quantization requires
``onnx`` plus ``onnxruntime``. Missing packages are reported and never installed by
this script.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.ner import (  # noqa: E402
    MAX_TOKENS,
    TOKEN_STRIDE,
    NerDetector,
    aggregate_bio,
    merge_overlaps,
)


SYNTHETIC_CASES = [
    ("La società Nebula Restauri S.r.l. ha presentato l'offerta.", "Nebula Restauri S.r.l.", "SOCIETA"),
    ("Il contratto è sottoscritto da Quasar Logistica S.p.A.", "Quasar Logistica S.p.A.", "SOCIETA"),
    ("Controparte: Officine Boreali Società Cooperativa.", "Officine Boreali Società Cooperativa", "SOCIETA"),
    ("La sede operativa usa il CAP 00144.", "00144", "CAP"),
    ("Spedire la comunicazione al codice postale 20121.", "20121", "CAP"),
    ("Recapito estero con ZIP code 10115.", "10115", "CAP"),
    ("Carta di test numero 4111 1111 1111 1111.", "4111 1111 1111 1111", "CARTA_PAGAMENTO"),
    ("Addebito simulato sulla carta 5555-5555-5555-4444.", "5555-5555-5555-4444", "CARTA_PAGAMENTO"),
    ("Numero carta per collaudo: 378282246310005.", "378282246310005", "CARTA_PAGAMENTO"),
]
ADOPTION_CATEGORIES = ("SOCIETA", "CAP", "CARTA_PAGAMENTO", "PERSONA")


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def read_corpus(corpus_dir: Path, gold_path: Path) -> list[dict[str, Any]]:
    with gold_path.open(encoding="utf-8") as stream:
        gold = json.load(stream)
    documents = []
    for filename, items in sorted(gold.items()):
        path = corpus_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"documento gold non trovato: {path}")
        normalized = [item if isinstance(item, dict) else {"text": item, "category": None} for item in items]
        documents.append({"name": filename, "text": path.read_text(encoding="utf-8"), "gold": normalized})
    synthetic = defaultdict(list)
    for index, (text, entity, category) in enumerate(SYNTHETIC_CASES):
        name = f"synthetic-{index:02d}"
        synthetic[name].append({"text": entity, "category": category})
        documents.append({"name": name, "text": text, "gold": synthetic[name]})
    return documents


def matches(candidate: dict[str, Any], gold: dict[str, Any]) -> bool:
    if gold.get("category") and candidate.get("category") != gold["category"]:
        return False
    actual = " ".join(str(candidate.get("raw", "")).casefold().split())
    expected = " ".join(str(gold["text"]).casefold().split())
    return actual == expected or actual in expected or expected in actual


def process_memory_mb(*, peak: bool = False) -> float | None:
    """Current working set, without adding psutil as a prototype dependency."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        ok = psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        value = counters.PeakWorkingSetSize if peak else counters.WorkingSetSize
        return value / (1024 * 1024) if ok else None
    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return rss / (1024 if sys.platform != "darwin" else 1024 * 1024)
    except (ImportError, OSError):
        return None


class OnnxBackend:
    """Small adapter with the same ``predict`` contract as ``backend.ner.TorchBackend``."""

    def __init__(self, model_dir: Path, onnx_path: Path):
        import numpy as np
        import onnxruntime as ort
        from transformers import AutoTokenizer

        self._np = np
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_dir, local_files_only=True, trust_remote_code=False
        )
        config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
        self.id2label = {int(key): value for key, value in config["id2label"].items()}
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(onnx_path), sess_options=options, providers=["CPUExecutionProvider"])
        self.input_names = {item.name for item in self.session.get_inputs()}

    def predict(self, texts: list[str]) -> list[list[tuple[int, int, str, float]]]:
        enc = self.tokenizer(
            texts,
            return_tensors="np",
            padding=True,
            truncation=True,
            max_length=MAX_TOKENS,
            stride=TOKEN_STRIDE,
            return_overflowing_tokens=True,
            return_offsets_mapping=True,
        )
        owner = enc.pop("overflow_to_sample_mapping").tolist()
        offsets = enc.pop("offset_mapping")
        feeds = {name: self._np.asarray(value, dtype=self._np.int64) for name, value in enc.items()
                 if name in self.input_names}
        logits = self.session.run(None, feeds)[0]
        logits -= logits.max(axis=-1, keepdims=True)
        probabilities = self._np.exp(logits)
        probabilities /= probabilities.sum(axis=-1, keepdims=True)
        best_id = probabilities.argmax(axis=-1)
        best_probability = probabilities.max(axis=-1)
        result = [[] for _ in texts]
        for row, sample in enumerate(owner):
            tokens = []
            for token_index, (start, end) in enumerate(offsets[row]):
                if int(end) <= int(start):
                    continue
                tokens.append((int(start), int(end), self.id2label[int(best_id[row, token_index])],
                               float(best_probability[row, token_index])))
            result[sample].extend(aggregate_bio(tokens))
        return [merge_overlaps(spans) for spans in result]


def prepare_onnx(model_dir: Path, destination: Path) -> tuple[Path, Path]:
    missing = [name for name in ("onnx", "onnxruntime") if not module_available(name)]
    if missing:
        raise RuntimeError("export/quantizzazione non disponibili; moduli mancanti: " + ", ".join(missing))

    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    destination.mkdir(parents=True, exist_ok=True)
    fp32_path = destination / "model.fp32.onnx"
    int8_path = destination / "model.int8.onnx"
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False)
    model = AutoModelForTokenClassification.from_pretrained(
        model_dir, local_files_only=True, trust_remote_code=False
    ).eval()
    sample = tokenizer("Documento di esportazione.", return_tensors="pt")
    input_names = [name for name in ("input_ids", "attention_mask") if name in sample]
    dynamic_axes = {name: {0: "batch", 1: "sequence"} for name in input_names}
    dynamic_axes["logits"] = {0: "batch", 1: "sequence"}
    torch.onnx.export(
        model,
        tuple(sample[name] for name in input_names),
        fp32_path,
        input_names=input_names,
        output_names=["logits"],
        dynamic_axes=dynamic_axes,
        opset_version=18,
        # The dynamo exporter currently records ModernBERT's local-attention
        # padding with the example sequence length even when dynamic_axes is
        # requested. The legacy exporter preserves the two dynamic axes here.
        dynamo=False,
        external_data=True,
    )
    quantize_dynamic(
        str(fp32_path),
        str(int8_path),
        weight_type=QuantType.QInt8,
        # Per-channel QInt8 made this ModernBERT checkpoint unusable in the
        # prototype (near-zero recall). Per-tensor remains measurable, although
        # its quality must still pass the report's adoption gate.
        per_channel=False,
        use_external_data_format=True,
    )
    return fp32_path, int8_path


def benchmark(
    name: str,
    detector_factory: Callable[[], NerDetector],
    documents: list[dict[str, Any]],
    repeats: int,
) -> dict[str, Any]:
    before_load = process_memory_mb()
    detector = detector_factory()
    # Warm-up excludes one-time graph/model initialization from steady-state latency.
    detector.detect("Il documento di prova è firmato da Mario Rossi.")
    if detector.status()["state"] == "error":
        raise RuntimeError(f"{name}: warm-up fallito: {detector.status()['reason']}")
    after_load = process_memory_mb()
    latencies = []
    found_by_document = {}
    for document in documents:
        samples = []
        found = []
        for _ in range(repeats):
            started = time.perf_counter()
            found = detector.detect(document["text"])
            if detector.status()["state"] == "error":
                raise RuntimeError(f"{name}: inferenza fallita: {detector.status()['reason']}")
            elapsed = time.perf_counter() - started
            words = max(1, len(document["text"].split()))
            samples.append(elapsed * 120 / words)
        latencies.append(statistics.median(samples))
        found_by_document[document["name"]] = found
    after = process_memory_mb()
    peak = process_memory_mb(peak=True)

    category_hits = defaultdict(lambda: [0, 0])
    for document in documents:
        found = found_by_document[document["name"]]
        for gold in document["gold"]:
            category = gold.get("category") or "SENZA_CATEGORIA"
            category_hits[category][1] += 1
            if any(matches(candidate, gold) for candidate in found):
                category_hits[category][0] += 1
    recalls = {
        category: {"hit": hit, "total": total, "recall": round(hit / total, 4)}
        for category, (hit, total) in sorted(category_hits.items())
    }
    return {
        "backend": name,
        "documents": len(documents),
        "recall_by_category": recalls,
        "latency_120_words_seconds": {
            "median": round(statistics.median(latencies), 4),
            "p95": round(sorted(latencies)[min(len(latencies) - 1, round(0.95 * (len(latencies) - 1)))], 4),
        },
        "working_set_mb": None if after is None else round(after, 1),
        "peak_working_set_mb": None if peak is None else round(peak, 1),
        "load_delta_mb": (None if before_load is None or after_load is None
                          else round(max(0.0, after_load - before_load), 1)),
        "run_delta_mb": (None if after_load is None or after is None
                         else round(max(0.0, after - after_load), 1)),
    }


def make_detector(model_dir: Path, onnx_path: Path | None = None) -> NerDetector:
    if onnx_path is None:
        detector = NerDetector(model_dir=str(model_dir))
    else:
        detector = NerDetector(backend=OnnxBackend(model_dir, onnx_path), expected_sha256=None)
    detector.extended = True  # required to evaluate ZIPCODE -> CAP
    return detector


def adoption_gate(fp32: dict[str, Any], int8: dict[str, Any]) -> dict[str, Any]:
    """The aggregate score cannot hide a regression in a privacy-critical class."""
    regressions = {}
    for category in ADOPTION_CATEGORIES:
        baseline = fp32["recall_by_category"][category]
        candidate = int8["recall_by_category"][category]
        if candidate["recall"] < baseline["recall"]:
            regressions[category] = {"fp32": baseline, "int8": candidate}
    return {"passed": not regressions, "regressions": regressions}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-dir", type=Path, required=True, help="verified local Hugging Face model folder")
    parser.add_argument("--corpus", type=Path, default=ROOT / "tools" / "corpus_regressione")
    parser.add_argument("--gold", type=Path, default=ROOT / "tools" / "corpus_regressione" / "gold.json")
    parser.add_argument("--prepare-onnx", type=Path, help="export/quantize into this external directory")
    parser.add_argument("--onnx-int8", type=Path, help="benchmark an existing INT8 ONNX graph")
    parser.add_argument("--backend", choices=("fp32", "int8", "both"), default="both",
                        help="run backends separately for meaningful RAM numbers")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out", type=Path, help="optional JSON output (may contain local performance data)")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats deve essere almeno 1")

    if args.prepare_onnx:
        try:
            _, args.onnx_int8 = prepare_onnx(args.model_dir, args.prepare_onnx)
        except RuntimeError as exc:
            print(f"BLOCCATO: {exc}", file=sys.stderr)
            return 2

    documents = read_corpus(args.corpus, args.gold)
    report = {
        "method": "model-only exact/containment recall; extended profile; CPU; warm-up excluded",
        "fp32": None,
        "int8": None,
    }
    if args.backend in ("fp32", "both"):
        report["fp32"] = benchmark(
            "pytorch-fp32", lambda: make_detector(args.model_dir), documents, args.repeats
        )
    if args.backend in ("int8", "both") and args.onnx_int8:
        if not args.onnx_int8.is_file():
            parser.error(f"file ONNX INT8 non trovato: {args.onnx_int8}")
        report["int8"] = benchmark(
            "onnxruntime-int8",
            lambda: make_detector(args.model_dir, args.onnx_int8),
            documents,
            args.repeats,
        )
    elif args.backend in ("int8", "both"):
        report["int8_blocker"] = "grafo INT8 non fornito; usare --prepare-onnx quando onnx e onnxruntime sono disponibili"
    if report["fp32"] is not None and report["int8"] is not None:
        report["int8_adoption_gate"] = adoption_gate(report["fp32"], report["int8"])

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(payload + "\n", encoding="utf-8")
        print(f"Report scritto in {args.out}")
    else:
        print(payload)
    gate = report.get("int8_adoption_gate")
    return 3 if gate is not None and not gate["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
