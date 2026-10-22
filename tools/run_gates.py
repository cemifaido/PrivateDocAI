# -*- coding: utf-8 -*-
"""
Script unificato di controllo e validazione dei Quality Gate per PrivateDoc AI.

Esegue in sequenza:
  1. Linter e stile del codice (ruff check . --no-cache)
  2. Suite completa di test unitari con directory dati isolata e temporanea
  3. Benchmark di regressione sul corpus gold sintetico (zero-fughe su colonna 'Regole + modello')

Uso:
  python tools/run_gates.py
  python tools/run_gates.py --quick                # esegue solo ruff e unittest
  python tools/run_gates.py --corpus CARTELLA      # specifica cartella corpus custom
  python tools/run_gates.py --gold FILE.json       # specifica file gold custom
  python tools/run_gates.py --model-dir CARTELLA   # percorso opzionale modello NER
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def find_project_root() -> Path:
    current = Path(__file__).resolve().parent
    while current.parent != current:
        if (current / "backend").is_dir() and (current / "tests").is_dir():
            return current
        current = current.parent
    return Path(__file__).resolve().parent.parent


def run_command(cmd, cwd, env=None):
    started = time.time()
    res = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.time() - started
    return res.returncode, res.stdout, res.stderr, elapsed


def run_gate_ruff(root: Path):
    print("[1/3] Esecuzione Linter (ruff check . --no-cache)...", flush=True)
    code, out, err, elapsed = run_command(
        [sys.executable, "-m", "ruff", "check", ".", "--no-cache"],
        cwd=root,
    )
    passed = code == 0
    details = "Tutti i controlli superati" if passed else (err.strip() or out.strip())
    return {
        "name": "Ruff Linter",
        "passed": passed,
        "code": code,
        "details": details,
        "elapsed": elapsed,
        "raw_out": out + err,
    }


def run_gate_unittest(root: Path):
    print("[2/3] Esecuzione Test Suite (unittest con data dir isolata)...", flush=True)
    with tempfile.TemporaryDirectory(prefix="privatedoc_test_data_") as tmp_dir:
        env = os.environ.copy()
        env["PRIVATEDOC_DATA_DIR"] = tmp_dir
        env["PRIVATE_DOC_DATA_DIR"] = tmp_dir
        code, out, err, elapsed = run_command(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            cwd=root,
            env=env,
        )

    passed = code == 0
    output = out + err
    m = re.search(r"Ran (\d+) tests in", output)
    n_tests = m.group(1) if m else "?"
    m_skip = re.search(r"skipped=(\d+)", output)
    skipped = m_skip.group(1) if m_skip else "0"

    if passed:
        details = f"{n_tests} test eseguiti con successo (saltati: {skipped})"
    else:
        details = f"Fallimento nei test unitari (codice {code})"

    return {
        "name": "Suite Test Unitari",
        "passed": passed,
        "code": code,
        "details": details,
        "elapsed": elapsed,
        "raw_out": output,
    }


def run_gate_benchmark(
    root: Path,
    corpus_dir: Path,
    gold_file: Path,
    model_dir: str = None,
    extended: bool = False,
):
    print(
        "[3/3] Esecuzione Benchmark di Regressione (zero-fughe su colonna 'Regole + modello')...",
        flush=True,
    )
    bench_script = root / "tools" / "benchmark_detectors.py"
    if not bench_script.is_file():
        return {
            "name": "Benchmark Regressione",
            "passed": False,
            "code": 1,
            "details": f"Script {bench_script} non trovato",
            "elapsed": 0.0,
            "raw_out": "",
        }

    cmd = [
        sys.executable,
        str(bench_script),
        str(corpus_dir),
        "--gold",
        str(gold_file),
        "--counts-only",
    ]
    if model_dir:
        cmd += ["--model-dir", str(model_dir)]
    if extended:
        cmd += ["--extended"]

    code, out, err, elapsed = run_command(cmd, cwd=root)
    output = out + err

    # Parsa rigorosamente la seconda colonna: 'Regole + modello'
    # Tabella markdown: | Occorrenze ancora leggibili | <col1> | <col2> |
    m_leak = re.search(
        r"\|\s*Occorrenze ancora leggibili\s*\|\s*[^|]+\|\s*(\d+)\s*/\s*(\d+)\s*\(([\d.]+)%\)\s*\|",
        output,
    )
    m_f1 = re.search(
        r"\|\s*F1\s*\|\s*[^|]+\|\s*([\d.]+)\s*\|",
        output,
    )

    if m_leak:
        leaks = int(m_leak.group(1))
        total = int(m_leak.group(2))
        pct = float(m_leak.group(3))
        f1_score = m_f1.group(1) if m_f1 else "N/D"
        passed = code == 0 and leaks == 0
        if passed:
            details = f"ZERO fughe su lista gold ({leaks}/{total} leggibili, F1: {f1_score})"
        else:
            details = f"Rilevate {leaks}/{total} ({pct}%) fughe nel corpus gold (codice {code})"
    else:
        # Fail closed: se l'output non e' parsabile o il benchmark fallisce, e' sempre FAIL
        passed = False
        details = f"FAIL: Metriche non individuate nell'output del benchmark (codice {code})"

    return {
        "name": "Benchmark Regressione",
        "passed": passed,
        "code": code,
        "details": details,
        "elapsed": elapsed,
        "raw_out": output,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validatore automatico dei Quality Gate per PrivateDoc AI."
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Esegue solo linter e test unitari (salta benchmark)",
    )
    parser.add_argument(
        "--corpus",
        help="Cartella del corpus di regressione (default: tools/corpus_regressione)",
    )
    parser.add_argument(
        "--gold",
        help="File gold.json di riferimento (default: tools/corpus_regressione/gold.json)",
    )
    parser.add_argument("--model-dir", help="Cartella opzionale del modello NER")
    parser.add_argument(
        "--extended", action="store_true", help="Attiva profilo esteso nel benchmark"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Stampa l'output completo dei comandi",
    )
    args = parser.parse_args()

    root = find_project_root()
    # Rendi sempre assoluti i percorsi per evitare anomalie relative alla cwd
    corpus_dir = (
        Path(args.corpus).resolve()
        if args.corpus
        else (root / "tools" / "corpus_regressione").resolve()
    )
    gold_file = (
        Path(args.gold).resolve()
        if args.gold
        else (corpus_dir / "gold.json").resolve()
    )
    model_dir = str(Path(args.model_dir).resolve()) if args.model_dir else None

    print("=" * 72)
    print("           PRIVATEDOC AI - ESECUZIONE QUALITY GATE CONGIUNTI")
    print(f" Progetto: {root}")
    print("=" * 72)

    results = []

    r1 = run_gate_ruff(root)
    results.append(r1)
    if not r1["passed"] and args.verbose:
        print(r1["raw_out"])

    r2 = run_gate_unittest(root)
    results.append(r2)
    if not r2["passed"] and args.verbose:
        print(r2["raw_out"])

    if not args.quick:
        if corpus_dir.is_dir() and gold_file.is_file():
            r3 = run_gate_benchmark(
                root, corpus_dir, gold_file, model_dir, args.extended
            )
            results.append(r3)
            if not r3["passed"] and args.verbose:
                print(r3["raw_out"])
        else:
            # Se corpus o gold mancano senza flag --quick, e' un FAIL bloccante (fail closed)
            missing = []
            if not corpus_dir.is_dir():
                missing.append(f"cartella corpus non trovata: {corpus_dir}")
            if not gold_file.is_file():
                missing.append(f"file gold non trovato: {gold_file}")
            r3 = {
                "name": "Benchmark Regressione",
                "passed": False,
                "code": 1,
                "details": f"FAIL bloccante: {'; '.join(missing)} (usa --quick per saltare intenzionalmente)",
                "elapsed": 0.0,
                "raw_out": "",
            }
            results.append(r3)

    print()
    print("=" * 72)
    print("                         RIEPILOGO GATE")
    print("=" * 72)

    all_passed = True
    total_time = 0.0
    for r in results:
        status_str = "[PASS]" if r["passed"] else "[FAIL]"
        total_time += r["elapsed"]
        print(f"* {r['name']:<26} {status_str} in {r['elapsed']:>5.2f}s | {r['details']}")
        if not r["passed"]:
            all_passed = False

    print("-" * 72)
    if all_passed:
        print(f"ESITO: TUTTI I GATE SUPERATI CON SUCCESSO (Tempo totale: {total_time:.2f}s)")
        print("=" * 72)
        sys.exit(0)
    else:
        print(f"ESITO: UNO O PIU' GATE SONO FALLITI (Tempo totale: {total_time:.2f}s)")
        print("=" * 72)
        sys.exit(1)


if __name__ == "__main__":
    main()
