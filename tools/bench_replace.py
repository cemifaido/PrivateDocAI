# -*- coding: utf-8 -*-
"""
Benchmark di prestazioni per le operazioni di sostituzione e ripristino entità.
Misura tempi di esecuzione, scalabilità e picco di memoria di:
  1. mask_text (costruzione pattern regex + sostituzione)
  2. de_anonymize_with_report (ripristino token esatti e fuzzy)

Scale di entità testate: 100, 1.000, 5.000, 20.000
Dimensioni documento testate: 1 KB (breve), 10 KB (medio/contratto), 50 KB (dossier)
"""

import argparse
import gc
import json
import random
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Assicura import del backend
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.anonymizer import DeterministicAnonymizer  # noqa: E402

# Dati sintetici per generazione entità variegate
NOMI = ["Alessandro", "Beatrice", "Carlo", "Daniela", "Edoardo", "Francesca", "Giorgio", "Helena", "Ivan", "Laura"]
COGNOMI = ["Rossi", "Bianchi", "Ferrari", "Esposito", "Ricci", "Marino", "Greco", "Bruno", "Gallo", "Conti"]
TIPI_SOCIETA = ["S.r.l.", "S.p.A.", "S.n.c.", "S.a.s.", "Group S.p.A.", "Consulting S.r.l."]
CITTA = ["Milano", "Roma", "Torino", "Bologna", "Firenze", "Napoli", "Bergamo", "Brescia", "Verona", "Padova"]


def genera_entita_sintetiche(n: int) -> List[Tuple[str, str]]:
    """Genera n entità sintetiche uniche distribuite su più categorie."""
    entita = []
    seen = set()
    counter = 0

    while len(entita) < n:
        counter += 1
        r = counter % 6
        if r in (0, 1, 2):  # Persona (50%)
            nome = f"{random.choice(NOMI)} {random.choice(COGNOMI)} {counter}"
            cat = "PERSONA"
        elif r == 3:  # Società (17%)
            nome = f"{random.choice(COGNOMI)} & Partners {counter} {random.choice(TIPI_SOCIETA)}"
            cat = "SOCIETA"
        elif r == 4:  # Indirizzo (17%)
            nome = f"Via {random.choice(COGNOMI)} {counter}, {random.choice(CITTA)}"
            cat = "INDIRIZZO"
        else:  # Riferimento / protocollo (16%)
            nome = f"PRAT-{counter:06d}-SEC"
            cat = "RIFERIMENTO"

        key = nome.lower()
        if key not in seen:
            seen.add(key)
            entita.append((nome, cat))

    return entita


def genera_testo_sintetico(entita: List[Tuple[str, str]], target_bytes: int) -> str:
    """Genera un testo sintetico con periodi discorsivi e occorrenze delle entità."""
    frasi_base = [
        "In relazione al procedimento di verifica, le parti hanno concordato di esaminare i documenti.",
        "Il consulente incaricato ha provveduto a redigere la perizia tecnica di conformità.",
        "Ai sensi delle disposizioni vigenti in materia di riservatezza e trattamento dati.",
        "Si attesta la regolare esecuzione delle prestazioni concordate nel contratto preliminare.",
        "Le comunicazioni formali sono state inviate a mezzo raccomandata con ricevuta di ritorno.",
        "La società dichiara di aver ottemperato a tutti gli obblighi previsti dalla legge.",
    ]

    paragrafi = []
    current_bytes = 0
    campione_entita = entita[: min(len(entita), 200)]  # usa un sottoinsieme per garantire occorrenze

    while current_bytes < target_bytes:
        e1 = random.choice(campione_entita)[0]
        e2 = random.choice(campione_entita)[0]
        f1 = random.choice(frasi_base)
        f2 = random.choice(frasi_base)
        paragrafo = f"{f1} In particolare, {e1} ha formalizzato l'istanza congiuntamente a {e2}. {f2}\n"
        paragrafi.append(paragrafo)
        current_bytes += len(paragrafo.encode("utf-8"))

    return "".join(paragrafi)


def inietta_token_fuzzy(testo_mascherato: str, reverse_map: Dict[str, str]) -> str:
    """Simula risposte LLM con token danneggiati o con formattazione imperfetta."""
    tokens = list(reverse_map.keys())
    if not tokens:
        return testo_mascherato

    modificato = testo_mascherato
    for t in tokens[: min(len(tokens), 20)]:
        forma = random.choice([
            t.lower(),
            t.replace("_", " "),
            t.replace("_", "-"),
            t.strip("[]"),
            t.lower().replace("_", " "),
        ])
        modificato = modificato.replace(t, forma, 1)

    return modificato


def esegui_benchmark_singolo(n_entita: int, doc_size_kb: int, repeats: int = 3) -> Dict[str, Any]:
    """Esegue il benchmark per una data dimensione di dizionario e dimensione testo."""
    gc.collect()

    entita = genera_entita_sintetiche(n_entita)
    testo_originale = genera_testo_sintetico(entita, doc_size_kb * 1024)
    lunghezza_testo = len(testo_originale)

    # 1. Popolamento anonimizzatore
    anon = DeterministicAnonymizer()
    for nome, cat in entita:
        anon.get_or_create_token(nome, cat)

    # 2. Misura memoria e tempo di compilazione pattern regex
    tracemalloc.start()
    gc.collect()
    t0 = time.perf_counter()
    pattern, defined = anon._build_mask_pattern()
    t_compile = time.perf_counter() - t0
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    pattern_size_chars = len(pattern.pattern) if pattern else 0

    # 3. Misura mask_text (cold vs warm)
    gc.collect()
    anon_fresh = DeterministicAnonymizer()
    for nome, cat in entita:
        anon_fresh.get_or_create_token(nome, cat)

    tracemalloc.start()
    t0 = time.perf_counter()
    testo_mascherato = anon_fresh.mask_text(testo_originale)
    t_mask_cold = time.perf_counter() - t0
    _, peak_mask_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    tempi_mask_warm = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        _ = anon_fresh.mask_text(testo_originale)
        tempi_mask_warm.append(time.perf_counter() - t0)
    t_mask_warm = min(tempi_mask_warm)

    testo_per_deanom = inietta_token_fuzzy(testo_mascherato, anon_fresh.reverse_map)

    # 4. Misura de_anonymize_with_report
    tempi_deanom = []
    tracemalloc.start()
    t0 = time.perf_counter()
    testo_ripristinato, report = anon_fresh.de_anonymize_with_report(testo_per_deanom)
    t_deanom_cold = time.perf_counter() - t0
    _, peak_deanom_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    for _ in range(repeats):
        t0 = time.perf_counter()
        _, _ = anon_fresh.de_anonymize_with_report(testo_per_deanom)
        tempi_deanom.append(time.perf_counter() - t0)
    t_deanom_warm = min(tempi_deanom)

    throughput_mask_kb_s = (len(testo_originale.encode("utf-8")) / 1024.0) / t_mask_warm if t_mask_warm > 0 else 0
    throughput_deanom_kb_s = (len(testo_per_deanom.encode("utf-8")) / 1024.0) / t_deanom_warm if t_deanom_warm > 0 else 0

    return {
        "n_entita": n_entita,
        "doc_size_kb": doc_size_kb,
        "text_chars": lunghezza_testo,
        "pattern_chars": pattern_size_chars,
        "compile_ms": t_compile * 1000,
        "compile_peak_kb": peak_mem / 1024,
        "mask_cold_ms": t_mask_cold * 1000,
        "mask_warm_ms": t_mask_warm * 1000,
        "mask_peak_kb": peak_mask_mem / 1024,
        "throughput_mask_kb_s": throughput_mask_kb_s,
        "deanom_cold_ms": t_deanom_cold * 1000,
        "deanom_warm_ms": t_deanom_warm * 1000,
        "deanom_peak_kb": peak_deanom_mem / 1024,
        "throughput_deanom_kb_s": throughput_deanom_kb_s,
        "fuzzy_count": len(report.get("fuzzy", [])),
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark di sostituzione e ripristino per PrivateDoc AI")
    parser.add_argument("--scales", default="100,1000,5000,20000", help="Numero di entita' (separati da virgola)")
    parser.add_argument("--sizes", default="1,10,50", help="Dimensioni documento in KB (separati da virgola)")
    parser.add_argument("--repeats", type=int, default=3, help="Ripetizioni per run warm")
    parser.add_argument("--json", help="File opzionale per salvare i risultati in formato JSON")
    args = parser.parse_args()

    scale_list = [int(x.strip()) for x in args.scales.split(",")]
    size_list = [int(x.strip()) for x in args.sizes.split(",")]

    print("=" * 80)
    print("      BENCHMARK SOSTITUZIONE & RIPRISTINO (DeterministicAnonymizer)")
    print(f" Scale entita': {scale_list}")
    print(f" Dimensioni doc (KB): {size_list}")
    print(f" Ripetizioni: {args.repeats}")
    print("=" * 80)

    risultati = []

    for n in scale_list:
        for size in size_list:
            print(f"-> Esecuzione test: N = {n:5d} entita' | Dimensione doc = {size:2d} KB...", end="", flush=True)
            res = esegui_benchmark_singolo(n, size, repeats=args.repeats)
            risultati.append(res)
            print(f" Completato: mask_warm={res['mask_warm_ms']:6.2f}ms | deanom_warm={res['deanom_warm_ms']:5.2f}ms")

    print("\n" + "=" * 115)
    header = f"{'Entita':<8} {'Doc(KB)':<8} {'Compila(ms)':<12} {'MaskCold(ms)':<14} {'MaskWarm(ms)':<14} {'DeanomWarm(ms)':<16} {'RAM Peak(KB)':<14} {'Mask Throughput':<16}"
    print(header)
    print("-" * 115)
    for r in risultati:
        line = (
            f"{r['n_entita']:<8} "
            f"{r['doc_size_kb']:<8} "
            f"{r['compile_ms']:>10.2f}ms "
            f"{r['mask_cold_ms']:>12.2f}ms "
            f"{r['mask_warm_ms']:>12.2f}ms "
            f"{r['deanom_warm_ms']:>14.2f}ms "
            f"{r['mask_peak_kb']:>12.1f}KB "
            f"{r['throughput_mask_kb_s']:>10.1f} KB/s"
        )
        print(line)
    print("=" * 115)

    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(risultati, f, indent=2)
        print(f"\nRisultati esportati in: {p}")


if __name__ == "__main__":
    main()
