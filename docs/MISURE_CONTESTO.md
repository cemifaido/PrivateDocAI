# Report Misure e Analisi: Falsi Positivi, Profilo Base e Context Boosting

**Data**: 22 Ottobre 2026 (Revisione R1)
**Autore**: Gemini (`feat/analisi-prestazioni`)
**Riferimento Piano**: Milestone 2/3 - Fase 1, Compito (c)
**Destinatari**: Team PrivateDoc AI (Claude, Codex, Gemini, Operatore Umano)

---

## 1. Executive Summary

L'analisi del corpus di regressione sintetico con il benchmark [`tools/benchmark_detectors.py`](file:///D:/Share/py/CRYPTO-IDE/tools/benchmark_detectors.py) a sole regole deterministiche (senza modello neurale) attesta le seguenti metriche di base:

* **Occorrenze gold ancora leggibili**: **0 / 54 (0.0% fughe)**
* **Documenti con almeno una fuga**: **0 / 3**
* **Richiamo (Recall)**: **1.00 (100%)**
* **Precisione (Precision)**: **0.96 (96.4%)**
* **F1 Score**: **0.98 (98.2%)**

L'analisi di dettaglio chiarisce due aspetti fondamentali:
1. **Falsi Positivi reali**: Nel corpus attuale emergono **2 maschere spurie** (`Catasto Fabbricati` e `The Service`), causate dall'euristica generica che scambia due parole maiuscole contigue per un nome di persona. La loro eliminazione è affidata all'intervento di Claude su `backend/anonymizer.py`.
2. **Toponimi lasciati in chiaro (scelta di progetto, non errore)**: I nomi di città isolate (`Monza`, `Bergamo`, `Milano`, `London`) **non sono falsi negativi o fughe della lista gold**. La loro esclusione dal profilo base è una scelta deliberata di prodotto per preservare la leggibilità e il contesto geografico degli atti legali; sono invece catturate dal "profilo esteso" opzionale.

---

## 2. Diagnosi Puntuale dei 2 Falsi Positivi Reali

### Caso 1: `Catasto Fabbricati` (`contratto_appalto.txt`)
* **Testo nel documento**:
  ```text
  ...censito al Catasto Fabbricati, Foglio 14, particella 280, sub. 3.
  ```
* **Comportamento attuale**:
  - Classificato come `PERSONA_1`: `[PERSONA_1], Foglio 14, particella 280, sub. 3`.
* **Causa tecnica**:
  - La regola per `PERSONA` cattura due parole contigue con iniziale maiuscola (`Catasto Fabbricati`).
* **Risoluzione prevista**:
  - Aggiunta di locuzioni catastali e amministrative standard a una lista di esclusione per `PERSONA`.

### Caso 2: `The Service` (`service_agreement_en.txt`)
* **Testo nel documento**:
  ```text
  The Service Provider agrees to deliver the consulting deliverables...
  ```
* **Comportamento attuale**:
  - Classificato come `PERSONA_4`: `[PERSONA_4] Provider agrees to deliver...`.
* **Causa tecnica**:
  - L'articolo determinativo `The` a inizio periodo maiuscolo seguito dal sostantivo `Service` (ruolo contrattuale).
* **Risoluzione prevista**:
  - Esclusione da `PERSONA` per articoli e determinativi inglesi iniziali seguiti da termini di ruolo contrattuale.

---

## 3. Analisi dei Toponimi: Profilo Base vs Profilo Esteso

Il benchmark segnala come *Parole sospette rimaste* i termini `Monza`, `Bergamo`, `Milano` e `London`.

* **Natura dei dati**: Si tratta di toponimi indicanti sedi legali o luoghi di nascita.
* **Scelta architetturale di PrivateDoc AI**:
  - Il profilo base disattiva intenzionalmente le categorie generiche (`CITTA`, `CAP`, `PROVINCIA`, `ETA`, `SESSO`, `ORA`) per non alterare eccessivamente la comprensione dei contratti e degli atti notarili.
  - Tali categorie appartengono al **profilo esteso** (`--extended`), attivabile su richiesta dell'utente quando il livello di riservatezza richiesto impone l'anonimizzazione anche del comune o della sede.

---

## 4. Specifiche per il Context Boosting

Il **Context Boosting** consiste nell'utilizzare parole spia (trigger words) nel raggio di ±3 token per disambiguare l'assegnazione delle categorie:

1. **Trigger Positivi per Città e Sedi (utilizzabili nel profilo esteso o mirato)**:
   - `(?:avente\s+sede|con\s+sede|sede\s+legale|registered\s+office)\s+in\s+([A-Z][a-z]+)` -> categoria `CITTA` / `SEDE`
   - `(?:nato|nata)\s+a\s+([A-Z][a-z]+)` -> categoria `CITTA`
2. **Trigger Negativi (Soppressione Falsi Positivi in `PERSONA`)**:
   - Locuzioni catastali: `(?:censito\s+al|iscritto\s+al|presso\s+il)\s+Catasto\s+(?:Fabbricati|Terreni)` -> categorizzazione in `CATASTO` o esclusione da `PERSONA`.
   - Formule di ruolo in lingua inglese: `(?:The|This|An|A)\s+(?:Service|Agreement|Company|Court|Contract|Parties)` -> esclusione da `PERSONA`.

---

## 5. Simulazione Teorica dei Benefici

Eliminando i 2 falsi positivi reali (`Catasto Fabbricati` e `The Service`) tramite i trigger negativi:
- **Precisione**: sale da **0.96 a 1.00**
- **Richiamo**: confermato a **1.00** (0 fughe)
- **F1 Score**: sale da **0.98 a 1.00**
- **Ripristino**: la sostituzione inversa con `de_anonymize_with_report` è puramente deterministica e non risente dell'ambiguità delle etichette eliminate.
