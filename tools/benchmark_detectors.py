"""
Local benchmark: rules alone vs rules + optional model, on YOUR documents, document by document.

Nothing leaves the computer and nothing is written inside the project. What it measures
(on the FINAL result of the fusion, exactly what the program would send):

  * occurrence-level leak rate: of all the places where a gold item appears in a document, how
    many are still readable after masking (and the share of documents with at least one leak);
  * exact precision / recall / F1 per category and micro/macro, comparing the gold items with the
    entities the program registered (extra masks = candidates for false positives, listed);
  * what the model finds that the rules miss, and the reverse (for review);
  * time per document (p50 / p95).

Usage
  python tools/benchmark_detectors.py CARTELLA [--gold gold.json] [--out report.md]
                                      [--extended] [--counts-only] [--model-dir DIR]

  gold.json: {"nome_file.pdf": ["Mario Rossi", {"text": "2210/2026", "category": "RIFERIMENTO"}, ...], ...}
  (a bare string has no category; items with a category also feed the per-category numbers)

Privacy: the report contains text taken from the documents; keep it where the documents are kept.
--counts-only prints numbers only, BUT the file names are still shown: use neutral names if they
can contain personal data. A real corpus must stay local and is never committed.
"""
import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.anonymizer import DeterministicAnonymizer  # noqa: E402
from backend.extractor import DocumentExtractor  # noqa: E402
from backend.ner import NerDetector  # noqa: E402

SKIP_FOR_REVIEW = {"DATA", "IMPORTO"}  # too numerous to review by eye


def collect_documents(folder, ignore=()):
    extractor = DocumentExtractor()
    docs, skipped = [], []
    ignored = {os.path.abspath(p) for p in ignore}
    for root, _dirs, files in os.walk(folder):
        for name in sorted(files):
            path = os.path.join(root, name)
            if os.path.abspath(path) in ignored:
                continue  # the gold list is not a document
            with open(path, "rb") as f:
                found, left_out = extractor.extract_with_report(os.path.relpath(path, folder), f.read())
            docs.extend(found)
            skipped.extend(left_out)
    return docs, skipped


def normalise_gold(items):
    out = []
    for item in items:
        out.append(item if isinstance(item, dict) else {"text": item, "category": None})
    return out


def count_occurrences(text, phrase):
    return text.lower().count(phrase.lower())


def percentile(values, q):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def analyse(doc, ner, use_model):
    text, key = doc.get("text", ""), doc["filename"]
    started = time.time()
    model_items = ner.detect(text) if use_model else []
    anonymizer = DeterministicAnonymizer()
    anonymizer.analyze_documents([{"id": key, "filename": key, "text": text}],
                                 extra_candidates={key: model_items} if use_model else None)
    masked = anonymizer.mask_text(text, doc_key=key)
    return anonymizer, masked, model_items, time.time() - started


def prf(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def evaluate_gold(gold_items, anonymizer, text, masked):
    """Per-document numbers against the gold items."""
    registered = {r["canonical"]: r["category"] for r in anonymizer.get_registry()}
    tp = fn = 0
    leaked_occurrences = total_occurrences = 0
    per_category = defaultdict(lambda: [0, 0, 0])   # tp, fn, (fp counted globally)
    missed = []
    for item in gold_items:
        phrase = item["text"]
        total = count_occurrences(text, phrase)
        left = count_occurrences(masked, phrase)
        total_occurrences += total
        leaked_occurrences += min(left, total)
        masked_somewhere = left < total
        covered = any(phrase.lower() in canon or canon in phrase.lower() for canon in registered)
        if masked_somewhere or covered:
            tp += 1
            if item["category"]:
                per_category[item["category"]][0] += 1
        else:
            fn += 1
            missed.append(phrase)
            if item["category"]:
                per_category[item["category"]][1] += 1
    gold_lower = [g["text"].lower() for g in gold_items]
    extras = [r["original"] for r in anonymizer.get_registry()
              if not any(g in r["canonical"] or r["canonical"] in g for g in gold_lower)]
    return {"tp": tp, "fn": fn, "fp": len(extras), "leaked": leaked_occurrences, "occurrences": total_occurrences,
            "per_category": per_category, "missed": missed, "extras": extras}


def run(folder, gold, counts_only, model_dir, extended, gold_path=None):
    docs, skipped = collect_documents(folder, ignore=[gold_path] if gold_path else [])
    ner = NerDetector(model_dir=model_dir)
    ner.extended = extended
    ner.start_verification()
    if ner._verify_thread is not None:
        ner._verify_thread.join()
    model_ready = ner.status()["active"]
    lines = [f"# Benchmark: {len(docs)} documenti ({len(skipped)} file non letti)", "",
             f"Modello: {ner.status()['reason']}" + (" · profilo esteso" if extended else "")]
    times = {"rules": [], "both": []}
    totals = {"rules": Counter(), "both": Counter()}
    summary = {mode: {"tp": 0, "fn": 0, "fp": 0, "leaked": 0, "occ": 0, "docs_leaking": 0, "docs": 0,
                      "cat": defaultdict(lambda: [0, 0])} for mode in ("rules", "both")}

    for doc in docs:
        key = doc["filename"]
        rules_a, rules_masked, _, t_rules = analyse(doc, ner, False)
        both_a, both_masked, model_items, t_both = analyse(doc, ner, model_ready)
        times["rules"].append(t_rules)
        times["both"].append(t_both)
        rule_set = {(r["canonical"], r["category"]) for r in rules_a.get_registry()}
        both_set = {(r["canonical"], r["category"]) for r in both_a.get_registry()}
        totals["rules"].update(c for _, c in rule_set)
        totals["both"].update(c for _, c in both_set)
        only_model = sorted(x for x in both_set if x[0] not in {r[0] for r in rule_set})
        only_rules = sorted(x for x in rule_set if x[0] not in {b[0] for b in both_set})

        lines += ["", f"## {key}", f"- entità: solo regole {len(rule_set)} · regole + modello {len(both_set)} · "
                      f"aggiunte dal modello {len(only_model)} · perse con il modello {len(only_rules)}"]
        if not counts_only:
            for label, items in (("Aggiunte dal modello", only_model), ("Perse con il modello", only_rules)):
                shown = [f"`{v}` ({c})" for v, c in items if c not in SKIP_FOR_REVIEW][:25]
                if shown:
                    lines.append(f"- {label}: " + ", ".join(shown))
            suspects = both_a.find_unmasked_suspects(both_masked)
            if suspects:
                lines.append("- Parole sospette rimaste: " + ", ".join(f"`{w}`" for w in suspects[:25]))

        if key in gold:
            items = normalise_gold(gold[key])
            for mode, (a, masked) in (("rules", (rules_a, rules_masked)), ("both", (both_a, both_masked))):
                res = evaluate_gold(items, a, doc.get("text", ""), masked)
                s = summary[mode]
                s["tp"] += res["tp"]
                s["fn"] += res["fn"]
                s["fp"] += res["fp"]
                s["leaked"] += res["leaked"]
                s["occ"] += res["occurrences"]
                s["docs"] += 1
                s["docs_leaking"] += 1 if res["leaked"] else 0
                for cat, (ctp, cfn, _) in res["per_category"].items():
                    s["cat"][cat][0] += ctp
                    s["cat"][cat][1] += cfn
                if mode == "both":
                    lines.append(f"- Con regole + modello: {res['leaked']} occorrenze su {res['occurrences']} ancora leggibili; "
                                 f"dati mancati {res['fn']}, maschere in più da controllare {res['fp']}")
                    if not counts_only and res["missed"]:
                        lines.append("  - non mascherati: " + ", ".join(f"`{m}`" for m in res["missed"][:25]))
                    if not counts_only and res["extras"]:
                        lines.append("  - maschere in più: " + ", ".join(f"`{m}`" for m in res["extras"][:25]))

    lines += ["", "## Riepilogo", "", "| Categoria rilevata | Solo regole | Regole + modello |", "|---|---:|---:|"]
    for category in sorted(set(totals["rules"]) | set(totals["both"])):
        lines.append(f"| {category} | {totals['rules'][category]} | {totals['both'][category]} |")

    if summary["rules"]["docs"]:
        lines += ["", "### Contro la lista gold", "",
                  "| | Solo regole | Regole + modello |", "|---|---:|---:|"]

        def cell(mode, f):
            return f(summary[mode])

        for label, f in (
            ("Occorrenze ancora leggibili", lambda s: f"{s['leaked']} / {s['occ']} ({s['leaked'] / s['occ']:.1%})" if s["occ"] else "-"),
            ("Documenti con almeno una fuga", lambda s: f"{s['docs_leaking']} / {s['docs']}"),
            ("Precisione", lambda s: f"{prf(s['tp'], s['fp'], s['fn'])[0]:.2f}"),
            ("Richiamo", lambda s: f"{prf(s['tp'], s['fp'], s['fn'])[1]:.2f}"),
            ("F1", lambda s: f"{prf(s['tp'], s['fp'], s['fn'])[2]:.2f}"),
        ):
            lines.append(f"| {label} | {cell('rules', f)} | {cell('both', f)} |")
        categories = sorted(set(summary["rules"]["cat"]) | set(summary["both"]["cat"]))
        if categories:
            lines += ["", "| Categoria gold | Richiamo solo regole | Richiamo regole + modello |", "|---|---:|---:|"]
            for cat in categories:
                def rec(mode):
                    tp, fn = summary[mode]["cat"][cat]
                    return f"{tp / (tp + fn):.2f} ({tp}/{tp + fn})" if tp + fn else "-"
                lines.append(f"| {cat} | {rec('rules')} | {rec('both')} |")
        macro = [prf(*summary["both"]["cat"][c], 0)[1] for c in categories if sum(summary["both"]["cat"][c])]
        if macro:
            lines.append(f"\nRichiamo medio per categoria (macro, regole + modello): {statistics.mean(macro):.2f}")

    lines += ["", f"Tempo per documento (p50 / p95): solo regole {percentile(times['rules'], .5):.2f}s / "
                  f"{percentile(times['rules'], .95):.2f}s · con modello {percentile(times['both'], .5):.2f}s / "
                  f"{percentile(times['both'], .95):.2f}s",
              "Nota: la memoria di picco non è misurata qui; misurala nel processo reale prima di promettere requisiti."]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder")
    parser.add_argument("--gold", help="JSON {file: [strings or {text, category}]}")
    parser.add_argument("--out", help="write the report here instead of printing it")
    parser.add_argument("--counts-only", action="store_true", help="numbers only, no text from the documents")
    parser.add_argument("--extended", action="store_true", help="model's extended profile (city, ZIP, age...)")
    parser.add_argument("--model-dir", default=os.environ.get("PRIVATEDOC_NER_DIR")
                        or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "rizzo-pii-0.3B"))
    args = parser.parse_args()
    gold = {}
    if args.gold:
        with open(args.gold, encoding="utf-8") as f:
            gold = json.load(f)
    report = run(args.folder, gold, args.counts_only, args.model_dir, args.extended, args.gold)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Report scritto in {args.out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
