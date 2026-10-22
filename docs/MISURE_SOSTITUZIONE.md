# Report Prestazioni: Sostituzione e Ripristino Entità (DeterministicAnonymizer)

**Data**: 22 Ottobre 2026  
**Autore**: Gemini (`feat/analisi-prestazioni`)  
**Script di misura**: `tools/bench_replace.py`  
**Dataset**: Dati sintetici controllati (NOMI, COGNOMI, SOCIETA, INDIRIZZI, RIFERIMENTI)  
**Ambiente di test**: Python 3.14 (Windows x64, CPU desktop office senza GPU)

---

## 1. Executive Summary & Verdetto su Aho-Corasick

> [!IMPORTANT]
> **Verdetto Architetturale**:
> 1. **Per il ripristino (`de_anonymize_with_report`)**: **Aho-Corasick NON SERVE**. L'algoritmo attuale effettua una singola scansione del testo cercando i pattern sintattici dei token (`[CATEGORIA_ID]` e bare token) con lookup $O(1)$ su dizionario Python (`reverse_map`). La latenza è **inferiore a 2.6 ms** su documenti da 50 KB anche con **20.000 entità registrate**.
> 2. **Per il mascheramento (`mask_text`)**:
>    - **Per il caso d'uso target (N ≤ 1.000 entità)**: L'approccio regex corrente è **estremamente performante** (latenza 16–80 ms per contratti/atti da 10–50 KB, throughput fino a 5,6 MB/s). L'introduzione di Aho-Corasick **non è necessaria** per la versione desktop corrente.
>    - **Al limite estremo (N ≥ 5.000 – 20.000 entità)**: Emerge un collo di bottiglia specifico: la **compilazione del pattern regex** con 20.000 alternative richiede **6,4–6,6 secondi** e il throughput di sostituzione scende a ~28 KB/s.
> 3. **Raccomandazione**: Mantenere l'implementazione zero-dipendenze attuale per Milestone 2. Se in futuro l'applicazione gestirà "dizionari aziendali permanenti" con > 2.000 termini pre-caricati, implementare un automa Aho-Corasick **puro in Python** (senza librerie C esterne tipo `pyahocorasick` che complicherebbero PyInstaller su Windows) attivo solo per soglie $N > 1.000$.

---

## 2. Metodologia di Misura

Il benchmark [`tools/bench_replace.py`](file:///D:/Share/py/CRYPTO-IDE/tools/bench_replace.py) misura le prestazioni isolando le due fasi operative:
1. **Fase di Mascheramento (`mask_text`)**:
   - Costruzione del pattern regex unificato (`_build_mask_pattern`): ordinamento decrescente per lunghezza per prevenire shadowing di prefissi, escaping e compilazione regex con alternative `(?<![\w\[])(?:e1|e2|...|eN)`.
   - Esecuzione sostituzione con callback (`to_token`).
   - Distinzione tra esecuzione **Cold** (prima esecuzione con compilazione regex inclusa) e **Warm** (pattern riutilizzato o presente nella cache regex interna).
2. **Fase di Ripristino (`de_anonymize_with_report`)**:
   - Scansione con regex statica `_BRACKETED_TOKEN` / `_BARE_TOKEN`.
   - Normalizzazione e lookup su `reverse_map`.
   - Gestione delle varianti fuzzy (token con spazi, minuscoli, trattini o senza parentesi quadre).
3. **Parametri di scala**:
   - **Scale dizionario ($N$)**: 100, 1.000, 5.000, 20.000 entità registrate.
   - **Dimensioni documento**:
     - **1 KB**: Documento breve / estratto / messaggio (~150 parole).
     - **10 KB**: Contratto standard / atto giudiziario (~1.500 parole).
     - **50 KB**: Dossier multi-atto / fascicolo esteso (~7.500 parole).
   - **Memoria**: Tracciamento del picco di allocazione heap tramite modulo standard `tracemalloc`.

---

## 3. Tabella Completa dei Risultati Sperimentali

| Entità ($N$) | Doc (KB) | Compilazione Regex | Mask Cold | Mask Warm | De-Anonymize Warm | RAM Peak | Throughput Mask Warm |
|:---|:---|:---|:---|:---|:---|:---|:---|
| **100** | 1 KB | 48.27 ms | 1.32 ms | **0.40 ms** | **0.06 ms** | 20.3 KB | 2.633 KB/s |
| **100** | 10 KB | 32.24 ms | 3.30 ms | **2.07 ms** | **0.52 ms** | 24.5 KB | 4.936 KB/s |
| **100** | 50 KB | 32.42 ms | 12.07 ms | **8.89 ms** | **2.45 ms** | 114.4 KB | **5.645 KB/s** |
| **1.000** | 1 KB | 324.87 ms | 12.84 ms | **3.52 ms** | **0.05 ms** | 187.8 KB | 298 KB/s |
| **1.000** | 10 KB | 301.49 ms | 25.72 ms | **16.90 ms** | **0.90 ms** | 188.0 KB | 595 KB/s |
| **1.000** | 50 KB | 314.38 ms | 93.20 ms | **79.87 ms** | **2.52 ms** | 187.9 KB | 627 KB/s |
| **5.000** | 1 KB | 1.588.97 ms | 73.68 ms | **21.68 ms** | **0.06 ms** | 1.040 KB | 49.7 KB/s |
| **5.000** | 10 KB | 1.694.43 ms | 142.46 ms | **98.64 ms** | **0.58 ms** | 1.039 KB | 102.0 KB/s |
| **5.000** | 50 KB | 1.678.58 ms | 471.51 ms | **410.39 ms** | **2.40 ms** | 1.040 KB | 122.3 KB/s |
| **20.000** | 1 KB | 6.365.66 ms | 247.28 ms | **84.04 ms** | **0.05 ms** | 4.195 KB | 12.8 KB/s |
| **20.000** | 10 KB | 6.376.01 ms | 711.36 ms | **394.29 ms** | **0.48 ms** | 4.196 KB | 25.9 KB/s |
| **20.000** | 50 KB | 6.667.68 ms | 2.939.01 ms | **1.736.90 ms** | **2.54 ms** | 4.195 KB | 28.9 KB/s |

---

## 4. Analisi di Dettaglio

### 4.1 Il Comportamento di `de_anonymize_with_report`
Il risultato più evidente delle misure è l'**indipendenza totale di `de_anonymize_with_report` dal numero di entità $N$**:
- Con 100 entità su 50 KB: **2.45 ms**
- Con 20.000 entità su 50 KB: **2.54 ms**

**Perché accade?**  
Nel processo di de-anonimizzazione, il testo da elaborare contiene solo i token assegnati (es. `[PERSONA_1]`, `[SOCIETA_A]`) o loro varianti danneggiate generate dall'LLM. L'anonymizer non cerca nel testo i nomi originali, ma cerca i pattern sintattici `\[[A-Z]+_[A-Z0-9]+\]`. Il numero di categorie è fisso (~14) e la regex ha complessità $O(1)$ rispetto a $N$. La sostituzione avviene tramite lookup hash su dizionario Python `reverse_map` ($O(1)$ medio).

> **Conclusione**: Per il ripristino non esiste alcun problema di scalabilità.

---

### 4.2 Il Comportamento di `mask_text` e Costruzione del Pattern
Per il mascheramento, il comportamento si divide in due componenti:
1. **Compilazione del pattern (`_build_mask_pattern`)**:
   - Cresce in modo approssimativamente lineare/super-lineare con $N$:
     - $N = 100$: ~32 ms
     - $N = 1.000$: ~310 ms
     - $N = 5.000$: ~1.650 ms (1,6 s)
     - $N = 20.000$: ~6.500 ms (6,5 s)
   - A $N = 20.000$, la stringa regex supera i 450.000 caratteri e impegna oltre 4,1 MB di RAM per la sola struttura NFA del modulo `re`.
2. **Sostituzione effettiva (Warm run)**:
   - Su documenti realistici da ufficio (10 KB, circa 3–4 pagine):
     - $N = 100$: **2,07 ms** (istantaneo)
     - $N = 1.000$: **16,90 ms** (impercettibile all'utente)
     - $N = 5.000$: **98,64 ms**
     - $N = 20.000$: **394,29 ms**
   - Su dossier da 50 KB (~20 pagine):
     - $N = 100$: **8,89 ms**
     - $N = 1.000$: **79,87 ms**
     - $N = 5.000$: **410,39 ms**
     - $N = 20.000$: **1.736,90 ms**

---

## 5. Confronto Teorico e Pratico: Regex vs Aho-Corasick

| Aspetto | Regex Alternation Corrente | Aho-Corasick (Trie / Automa) |
|:---|:---|:---|
| **Tempo Costruzione** | $O(\sum |P_i|)$ con alto overhead di compilazione C ($6,5$ s a $N=20.000$) | $O(\sum |P_i|)$ rapido con inserimento in albero dei prefissi ($< 0,1$ s) |
| **Tempo Scansione Testo** | $O(|T| \times K)$ (dipendente dal matching delle alternative) | $O(|T| + \text{matches})$ **indipendente dal numero di pattern $N$** |
| **Dipendenze** | **Zero** (modulo standard `re`) | Libreria esterna C (`pyahocorasick`) OPPURE automa in puro Python |
| **Boundaries & Word Break** | Gestiti nativamente con lookbehind/lookahead `(?<![\w\[])` | Richiede post-filtro sui bordi dei match estratti |
| **Compatibilità PyInstaller** | Massima (100% stabile su Windows desktop) | Se con modulo C: rischio problemi di build/DLL mancanti |

---

## 6. Conclusioni e Raccomandazioni Operative

1. **Per PrivateDoc AI oggi**:
   - In una normale sessione di lavoro su contratti, perizie o atti giudiziari, il numero tipico di entità uniche estratte raramente supera le **100–300 entità**.
   - Con $N \le 1.000$, il tempo totale di mascheramento su documenti da 10–50 KB è compreso tra **2 ms e 80 ms**, con un consumo di RAM inferiore a **200 KB**.
   - L'esperienza utente percepita è **istantanea**.
2. **Nessun cambio per Milestone 2**:
   - L'introduzione di dipendenze esterne come `pyahocorasick` violerebbe il principio di massima semplicità, portabilità e zero-dipendenze per l'eseguibile standalone Windows.
3. **Ottimizzazione futura raccomandata (se $N$ cresce)**:
   - Se in future milestone si volesse supportare la cross-anonimizzazione di archivi completi con $N > 5.000$ entità, l'intervento ottimale consisterà nell'implementare un automa Aho-Corasick **puro in Python** (circa 70 righe di codice), mantenendo intatta la compatibilità zero-dipendenze.
