"""
Measurement only (nothing here is used by the program): would GLiNER, a zero-shot recogniser that takes
the labels at run time, find what the rules + the rizzo model do not?

Run with a SEPARATE Python that has `gliner` installed (not the one that runs the program):
    <venv>/Scripts/python.exe tools/prova_gliner.py [--model-dir DIR_OF_CHECKPOINT]

The checkpoint is downloaded once, at a pinned commit, from a repository declared Apache-2.0, and loaded
from disk. All texts are invented. Nothing is written in the project.
"""
import argparse
import ctypes
import os
import statistics
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPOSITORY = "urchade/gliner_multi-v2.1"          # Apache-2.0 on the model card
REVISION = "443d26d654e0324125a96bebd8e796c14ff2efe6"
THRESHOLD = 0.5   # overridden by --threshold

# invented sentences; each tuple: text, {label: [exact strings that must be found]}
CUSTOM = [
    ("Si veda la nota prot. n. Zx-8841/2026 inviata il 3 marzo.", {"numero di protocollo": ["Zx-8841/2026"]}),
    ("La comunicazione reca il protocollo QW-120/B del fascicolo.", {"numero di protocollo": ["QW-120/B"]}),
    ("In allegato la richiesta con prot. 55-ABC-2026, già evasa.", {"numero di protocollo": ["55-ABC-2026"]}),
    ("Il cliente è registrato con codice cliente CL-004571 dal 2024.", {"codice cliente": ["CL-004571"]}),
    ("Usare il codice cliente KX9921 per la fatturazione.", {"codice cliente": ["KX9921"]}),
    ("L'anagrafica riporta cod. cliente 77-ROMEO-3 come attivo.", {"codice cliente": ["77-ROMEO-3"]}),
    ("Il progetto Aquila Blu è in ritardo di due settimane.", {"nome del progetto": ["Aquila Blu"]}),
    ("Nel progetto Delta Orione sono coinvolti tre reparti.", {"nome del progetto": ["Delta Orione"]}),
    ("Il progetto denominato Cielo Aperto non è stato approvato.", {"nome del progetto": ["Cielo Aperto"]}),
    ("Pratica interna n. 77/B-2026 aperta dallo studio.", {"numero di pratica": ["77/B-2026"]}),
    ("Il fascicolo pratica 4410-LM è stato archiviato.", {"numero di pratica": ["4410-LM"]}),
    ("Richiamo la pratica n. 12/XC/2025 per i dettagli.", {"numero di pratica": ["12/XC/2025"]}),
    ("Il progetto Aquila Blu usa il codice cliente CL-004571 e la pratica 77/B-2026.",
     {"nome del progetto": ["Aquila Blu"], "codice cliente": ["CL-004571"], "numero di pratica": ["77/B-2026"]}),
]
# no custom datum at all: everything found here is a false positive
NEGATIVES = [
    "La riunione si terrà martedì alle dieci nella sala grande.",
    "Il contratto prevede una penale in caso di ritardo nella consegna.",
    "Si allega la relazione tecnica sull'andamento dei lavori.",
    "Il termine per il pagamento decorre dalla ricezione della fattura.",
    "La parte attrice contesta quanto affermato dalla convenuta.",
    "Il giudice ha rinviato l'udienza per la precisazione delle conclusioni.",
]
CUSTOM_LABELS = ["numero di protocollo", "codice cliente", "nome del progetto", "numero di pratica"]
CORPUS_LABELS = ["persona", "società", "indirizzo", "codice fiscale", "partita IVA", "IBAN", "e-mail",
                 "telefono", "numero di protocollo", "numero di ruolo generale", "importo"]


class _Counters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("a", ctypes.c_size_t), ("b", ctypes.c_size_t),
                ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def memory_mb():
    """(working set, peak working set) of this process in MB."""
    c = _Counters()
    c.cb = ctypes.sizeof(c)
    kernel, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return c.WorkingSetSize / 2 ** 20, c.PeakWorkingSetSize / 2 ** 20


def load_model(model_dir):
    from gliner import GLiNER
    if not model_dir:
        from huggingface_hub import snapshot_download
        model_dir = snapshot_download(REPOSITORY, revision=REVISION,
                                      allow_patterns=["gliner_config.json", "model.safetensors"])
    return GLiNER.from_pretrained(model_dir)


def custom_labels_test(model):
    tp = fp = fn = 0
    per_label = {label: [0, 0, 0] for label in CUSTOM_LABELS}      # tp, fp, fn
    misses, wrong = [], []
    for text, expected in CUSTOM:
        found = {(e["label"], e["text"]) for e in model.predict_entities(text, CUSTOM_LABELS, threshold=THRESHOLD)}
        want = {(label, s) for label, strings in expected.items() for s in strings}
        for item in want & found:
            tp += 1
            per_label[item[0]][0] += 1
        for item in found - want:
            fp += 1
            per_label[item[0]][1] += 1
            wrong.append(item)
        for item in want - found:
            fn += 1
            per_label[item[0]][2] += 1
            misses.append(item)
    for text in NEGATIVES:
        for e in model.predict_entities(text, CUSTOM_LABELS, threshold=THRESHOLD):
            fp += 1
            per_label[e["label"]][1] += 1
            wrong.append((e["label"], e["text"]))
    return tp, fp, fn, per_label, misses, wrong


def corpus_test(model, folder):
    """What GLiNER marks in the regression corpus that the rules (without the model) do not register."""
    from backend.anonymizer import DeterministicAnonymizer
    extra, timings = [], []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".txt"):
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            text = f.read()
        anonymizer = DeterministicAnonymizer()
        anonymizer.analyze_documents([{"id": name, "filename": name, "text": text}])
        known = [r["canonical"] for r in anonymizer.get_registry()]
        words = max(len(text.split()), 1)
        started = time.time()
        found = model.predict_entities(text, CORPUS_LABELS, threshold=THRESHOLD)
        timings.append((time.time() - started) * 120 / words)
        for e in found:
            low = " ".join(e["text"].lower().split())
            if not any(low in k or k in low for k in known):
                extra.append((name, e["label"], e["text"], round(e["score"], 2)))
    return extra, timings


def main():
    global THRESHOLD
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-dir", help="folder with the checkpoint (otherwise it is downloaded once)")
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    parser.add_argument("--corpus", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus_regressione"))
    args = parser.parse_args()
    THRESHOLD = args.threshold

    started = time.time()
    model = load_model(args.model_dir)
    load_seconds = time.time() - started
    print(f"Checkpoint {REPOSITORY} @ {REVISION[:12]} caricato in {load_seconds:.1f}s; "
          f"memoria {memory_mb()[0]:.0f} MB (picco {memory_mb()[1]:.0f})")

    tp, fp, fn, per_label, misses, wrong = custom_labels_test(model)
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    print(f"\n== Etichette libere (soglia {THRESHOLD}) su {len(CUSTOM)} frasi con dato + {len(NEGATIVES)} senza ==")
    print(f"trovati {tp} corretti, {fp} sbagliati, {fn} mancati -> precisione {precision:.2f}, richiamo {recall:.2f}")
    for label, (t, f, m) in per_label.items():
        print(f"  {label:22} corretti {t}  sbagliati {f}  mancati {m}")
    print("mancati:", misses)
    print("sbagliati:", wrong)

    extra, timings = corpus_test(model, args.corpus)
    print(f"\n== Corpus di regressione: indicazioni di GLiNER NON registrate dalle regole ({len(extra)}) ==")
    for item in extra:
        print("  ", item)
    print(f"\nTempo ogni 120 parole: mediana {statistics.median(timings):.2f}s, massimo {max(timings):.2f}s")
    working, peak = memory_mb()
    print(f"Memoria finale {working:.0f} MB, picco {peak:.0f} MB")


if __name__ == "__main__":
    main()
