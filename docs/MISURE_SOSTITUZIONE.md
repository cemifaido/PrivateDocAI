# Report Prestazioni: Sostituzione e Ripristino Entità (DeterministicAnonymizer)

**Data**: 22 Ottobre 2026 (Revisione R1)
**Autore**: Gemini (`feat/analisi-prestazioni`)
**Script di misura**: `tools/bench_replace.py` (seed 42, `re.purge()` per misurazioni cold reali)
**Dataset**: Dati sintetici controllati
**Ambiente di test**: Python 3.14 (Windows x64, CPU desktop office senza GPU)

---

## 1. Executive Summary & Verdetto su Aho-Corasick

> [!IMPORTANT]
> **Verdetto Architetturale**:
> 1. **Per il ripristino (`de_anonymize_with_report`)**: **Aho-Corasick NON SERVE**.
>    Il ripristino è un processo puramente deterministico: effettua una scansione lineare del testo cercando i token (`[CATEGORIA_ID]` e bare token) con lookup $O(1)$ su tabella hash (`reverse_map`). La latenza è **inferiore a 2.7 ms** su documenti da 50 KB sia con 100 che con **20.000 entità registrate**.
> 2. **Per il mascheramento (`mask_text`)**:
>    - **Caso d'uso reale desktop (N ≤ 1.000 entità)**: L'approccio regex corrente è **veloce e reattivo** (warm mask tra 2 e 84 ms per documenti da 10–50 KB, throughput fino a 5,1 MB/s). Non richiede alcuna modifica per l'uso ordinario dell'applicazione.
>    - **Comportamento alle scale estreme (N ≥ 5.000 – 20.000 entità)**: L'unico vero collo di bottiglia è il **muro di compilazione della regex** (da 1,6 s a N=5.000 fino a oltre 7–10 s cold a N=20.000).
> 3. **Raccomandazione**:
>    - Per il prodotto attuale (Milestone 2/3) **si mantiene la regex standard**, senza aggiungere dipendenze esterne.
>    - Il modulo [`tools/aho_corasick.py`](../tools/aho_corasick.py) realizzato in puro Python rimane confinato in `tools/` come **prototipo di riserva (non equivalente a `mask_text`: non normalizza gli spazi multipli, non gestisce il punto finale facoltativo né insieme voci case-sensitive e case-insensitive)** e dimostratore di scaling per future estensioni aziendali su cataloghi di grandi dimensioni.

---

## 2. Metodologia di Misura e Riproducibilità

Il benchmark [`tools/bench_replace.py`](file:///D:/Share/py/CRYPTO-IDE/tools/bench_replace.py) garantisce riproducibilità numerica:
- **Seed deterministico**: `seed=42` per la generazione sintetica di testi ed entità.
- **Misura Cold autentica**: invocazione di `re.purge()` prima della run cold per garantire che la regex venga effettivamente compilata da zero senza beneficiare della cache interna del modulo `re`.
- **Misura Warm**: minimo su 3 ripetizioni a regex già compilata e caricata.
- **Memoria Heap Python**: picco di allocazione heap tracciato tramite `tracemalloc` (distinto dal resident set size dell'intero processo OS).

---

## 3. Tabella dei Risultati Sperimentali (Seed 42)

| Entità ($N$) | Doc | Compilazione Regex | Mask Cold (con purge) | Mask Warm | De-Anonymize Warm | Heap Peak (`tracemalloc`) | Throughput Mask Warm |
|:---|:---|:---|:---|:---|:---|:---|:---|
| **100** | 1 KB | 35.21 ms | 34.08 ms | **0.41 ms** | **0.06 ms** | 426 KB | 2.646 KB/s |
| **100** | 10 KB | 39.15 ms | 36.18 ms | **2.39 ms** | **0.67 ms** | 426 KB | 4.284 KB/s |
| **100** | 50 KB | 34.92 ms | 44.06 ms | **9.72 ms** | **2.71 ms** | 426 KB | **5.146 KB/s** |
| **1.000** | 1 KB | 347.37 ms | 347.88 ms | **4.01 ms** | **0.06 ms** | 4.118 KB | 270 KB/s |
| **1.000** | 10 KB | 328.50 ms | 342.85 ms | **17.61 ms** | **0.52 ms** | 4.118 KB | 569 KB/s |
| **1.000** | 50 KB | 338.28 ms | 405.52 ms | **83.89 ms** | **2.59 ms** | 4.118 KB | 599 KB/s |
| **5.000** | 1 KB | 1.723.06 ms | 1.716.12 ms | **21.84 ms** | **0.07 ms** | 21.090 KB | 50.0 KB/s |
| **5.000** | 10 KB | 1.656.97 ms | 1.878.21 ms | **97.18 ms** | **0.63 ms** | 21.090 KB | 103.0 KB/s |
| **5.000** | 50 KB | 1.645.96 ms | 2.031.51 ms | **432.12 ms** | **3.73 ms** | 21.090 KB | 116.3 KB/s |
| **20.000** | 1 KB | 6.853.10 ms | 6.869.73 ms | **104.92 ms** | **0.13 ms** | 85.607 KB | 10.3 KB/s |
| **20.000** | 10 KB | 7.029.59 ms | 6.925.85 ms | **538.93 ms** | **0.52 ms** | 85.607 KB | 19.0 KB/s |
| **20.000** | 50 KB | 7.412.72 ms | 10.416.82 ms | **1.961.04 ms** | **2.50 ms** | 85.607 KB | 25.5 KB/s |

---

## 4. Analisi Critica dei Dati

### 4.1 Ripristino (`de_anonymize_with_report`): Complessità $O(|Testo|)$
I dati confermano in modo inequivocabile che il tempo di ripristino dipende **esclusivamente dalla lunghezza del testo** e non dal numero di entità registrate nel registro:
- A $N = 100$ su 50 KB: **2.71 ms**
- A $N = 20.000$ su 50 KB: **2.50 ms**
La ricerca dei token non scansiona i nomi originali ma le sole parentesi quadre/etichette categoria. Non esiste alcun motivo tecnico per modificare questo algoritmo.

### 4.2 Mascheramento (`mask_text`): Il Muro della Compilazione Regex
- A $N \le 1.000$, la compilazione richiede ~330 ms una tantum e le sostituzioni warm impiegano da 2 ms a 84 ms.
- A $N = 5.000$, la compilazione sale a **1,7 secondi**.
- A $N = 20.000$, la compilazione impiega **~7,4 secondi** e la prima esecuzione cold su 50 KB supera i **10 secondi**.

---

## 5. Ruolo del Prototipo Aho-Corasick in `tools/`

Il modulo [`tools/aho_corasick.py`](../tools/aho_corasick.py) è stato corretto per garantire **piena idempotenza di `build()`** (nessuna duplicazione di uscite in caso di chiamate multiple).

Confronto a $N = 20.000$ entità su documento da 50 KB:
- **Motore Regex attuale**: Compilazione **7.412 ms** + Sostituzione **1.961 ms** = **Totale ~9,4 s**
- **Automa Aho-Corasick puro Python**: Costruzione Trie **162 ms** + Sostituzione **9,3 ms** = **Totale ~0,17 s**

**Conclusione per il team**:
Il prototipo dimostra la fattibilità di un fallback ad alte prestazioni a costo zero in termini di dipendenze. Tuttavia, poiché in una normale sessione di PrivateDoc AI le entità non superano 100–300 elementi, **il modulo rimane in `tools/` e non viene integrato in `backend/anonymizer.py` nella Milestone 2**, mantenendo l'applicazione snella e priva di codice superfluo.
