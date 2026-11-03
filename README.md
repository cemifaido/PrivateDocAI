# 🛡️ PrivateDoc AI

🇮🇹 Italiano · 🇬🇧 [English](README.en.md)

**Analizza e confronta atti, contratti ed email con un modello linguistico senza mandare fuori dal computer i nomi, i codici e gli importi che il programma riconosce.**

PrivateDoc AI è un'applicazione locale per Windows pensata per chi lavora su documenti riservati (studi legali, commercialisti, consulenti). Maschera i dati personali *prima* dell'invio, lascia lavorare il modello sul testo mascherato e ricompone la risposta in locale con i dati veri. Non servono chiavi API.

> ⚠️ **Riduce il rischio, non lo elimina.** È una *pseudonimizzazione*, non una anonimizzazione: per il GDPR i dati pseudonimizzati restano dati personali. Il riconoscimento è euristico (a regole) e **non è infallibile**: il testo che sta per uscire va sempre riletto da una persona. Non costituisce consulenza legale. Vedi [Limiti](#limiti-noti).

## Come funziona

```
documenti ──► lettura locale ──► riconoscimento dati ──► testo con codici ──► modello (Gemini / ChatGPT / Claude)
(PDF, Word,    (OCR incluso)      (nomi, società, CF,      [PERSONA_1]            │
 Excel, email,                     IBAN, importi, date…)   [SOCIETA_A]            ▼
 ZIP, cartelle)                                                              risposta con i codici
                                                                                  │
                         risposta con i dati veri  ◄──── ricomposizione locale ◄──┘
```

1. **Carichi** file, cartelle intere (anche con sottocartelle) o archivi ZIP.
2. **Scudo Privacy:** ogni dato riconosciuto riceve un codice, *sempre lo stesso* in tutti i documenti, così il modello può confrontarli senza sapere chi sono le parti. Puoi correggere, togliere o aggiungere dati (anche selezionando un testo e premendo il tasto destro).
3. **Controllo pre-invio** sull'esatto testo in uscita: i dati riconosciuti ancora in chiaro bloccano l'invio; le parole sospette chiedono una conferma.
4. **Invio:** con Gemini, ChatGPT e Claude si usa «Copia e apri» (copia il testo anonimo, apre il sito nel tuo browser normale, poi incolli la risposta); Google, OpenAI e Anthropic rifiutano i browser automatici e il programma non cerca di aggirare il controllo. Facoltativa e spenta di default: l'API ufficiale di Gemini con la tua chiave (vedi la guida in-app per le condizioni sui dati).
5. **Risultato** con i dati reali, esportabile in Word. Dalla schermata dei dati protetti puoi anche creare una copia realmente censurata di un PDF originale.

## Caratteristiche

- **Formati:** PDF (anche scansionati, con OCR), Word, ODT, Excel, email `.eml`/`.msg`, testo, ZIP annidati, cartelle.
- **Pratiche salvate e cifrate:** password iniziale, archivio AES-256-GCM, riapri il lavoro dopo il riavvio e fai nuove domande con gli stessi codici.
- **Scelta dei documenti** da includere nella richiesta («confronta il Documento 3 con il 7»), con numerazione fissa; i nomi dei file non vengono inviati.
- **Caricamenti grandi:** contatore dei file mancanti, interruzione (tenendo o scartando quanto caricato), OCR in parallelo.
- **File non supportati** (ad esempio le foto) elencati con nome, percorso e motivo, invece di essere ignorati in silenzio.
- **Riconoscimento avanzato facoltativo:** un modello locale (MIT, su CPU) si affianca alle regole per nomi in contesto, società, numeri di ruolo e dati catastali. Se manca, la barra laterale permette di scaricarlo solo dopo consenso esplicito; ogni file è verificato con SHA-256 prima dell'attivazione. Il ripristino della risposta tollera i codici alterati dal modello e li segnala; IBAN, codice fiscale e partita IVA hanno validatori di formato. Vedi [`NOTICE.md`](NOTICE.md) e le sezioni 12-14 di [`PROGETTO_PRIVATEDOC_AI.md`](PROGETTO_PRIVATEDOC_AI.md).
- **Categorie personalizzate:** dal menu di protezione puoi cercare le categorie con corrispondenza tollerante o crearne una nuova (per esempio «Numero di protocollo»). La libreria è condivisa tra le pratiche e salvata cifrata nel vault.
- **Censura reale dei PDF:** scegli nuovamente il PDF originale e ottieni una copia con riquadri neri oppure codici come `[PERSONA_1]`. Il testo e le superfici accessorie vengono rimossi dal file, non semplicemente coperti; prima della consegna l'output viene riaperto e verificato. L'originale non viene aggiunto alla pratica né conservato dall'applicazione.
- **Guida in-app** (`/guida`) con uso, limiti e riferimenti normativi.

## Avvio rapido

### Con l'eseguibile (consigliato)

Costruiscilo con `build_exe.bat` (richiede Python e le dipendenze) e copia l'**intera cartella** `dist\PrivateDocAI` sul PC. Avvia `PrivateDocAI.exe`: si apre il browser su `http://127.0.0.1:8765`. Al primo avvio scegli la password dell'archivio (almeno 12 caratteri) e **annotala: non è recuperabile**.

- Le cartelle `data` e `profiles` si creano accanto all'`.exe`: non distribuire una cartella già usata (`build_exe.bat` controlla che sia pulita).

#### Eseguibile non firmato (prima release)

Questa è una prima release e l'eseguibile **non è ancora firmato digitalmente**: Windows non conosce l'editore e può mostrare degli avvisi. Non indica un problema nel file. Cosa fare:

1. **Se hai ricevuto uno ZIP**, prima di estrarlo: clic destro sul file → *Proprietà* → spunta **Annulla blocco** (o *Sblocca*) → *OK*. Poi estrai l'**intera** cartella.
2. **Al primo avvio** può comparire «Windows ha protetto il PC» (SmartScreen): clic su **Ulteriori informazioni**, poi su **Esegui comunque**. L'avviso compare di solito una volta sola.
3. **Se l'antivirus blocca o mette in quarantena il file**, è un falso positivo frequente per i programmi creati con PyInstaller: ripristinalo dalla quarantena e aggiungi la cartella alle eccezioni, oppure chiedi all'amministratore di sistema.
4. **Verifica che il file sia quello originale** confrontando l'impronta SHA-256 con quella indicata da chi te lo ha consegnato:
   ```powershell
   Get-FileHash .\PrivateDocAI.exe -Algorithm SHA256
   ```
   Se non coincide, non avviarlo.
5. Il browser si apre su `http://127.0.0.1:8765`; la finestra nera che compare con il programma deve restare aperta finché lo usi.

La firma del codice e un installer sono previsti nelle versioni successive.

### Da sorgente

```bash
pip install -r requirements.txt
python -m playwright install chromium     # solo per l'invio automatico a Gemini
python run.py
```

Variabili utili: `PRIVATEDOC_PORT`, `PRIVATEDOC_DATA_DIR`, `PRIVATEDOC_NO_BROWSER=1`.

## Sicurezza

- Tutto gira sul tuo computer; il server ascolta solo su `127.0.0.1` e accetta solo richieste dirette a `localhost`, con un token casuale per avvio (difesa da siti esterni).
- Le pratiche sono cifrate con una chiave derivata dalla password (scrypt) e legate al proprio identificativo; l'archivio si può bloccare.
- Il testo *mascherato* esce comunque verso il provider scelto: verifica le sue condizioni d'uso e le impostazioni dell'account.
- I cookie dei browser in `profiles/` **non** sono cifrati dal programma.

## Limiti noti

- Il rilevamento si basa su regole (e, se installato, su un modello locale facoltativo): nomi insoliti o dati scritti in modo anomalo possono sfuggire. I fatti descritti nel testo possono identificare le persone anche senza nomi.
- **ChatGPT e Claude non sono automatizzabili:** i loro siti bloccano i browser automatici (e il programma non cerca di aggirare i controlli). Si usa «Copia & Decifra».
- L'OCR gira su CPU: circa 6-10 secondi a pagina; 100 pagine scansionate richiedono circa 10 minuti.
- Una pratica sostituita con una copia più vecchia della stessa non viene riconosciuta. Un'ancora esterna è stata analizzata ma non viene implementata ora: aumenterebbe complessità e rischio di blocco senza proteggere dal ripristino congiunto o da un amministratore locale.
- Le immagini incorporate in Word, PDF con testo o email non vengono lette.
- La censura PDF richiede un livello di testo affidabile: i PDF costituiti soltanto da scansioni vengono rifiutati. Il testo dentro immagini e font non estraibili richiede OCR e non può essere garantito in questa versione. Se anche un solo dato richiesto resta rilevabile, il PDF non viene consegnato.
- Il programma non gestisce l'informativa al cliente, la base giuridica, i contratti con il fornitore di IA né la valutazione d'impatto: restano a carico di chi lo usa.

## Riferimenti normativi

GDPR (art. 4 n. 5, considerando 26, artt. 5, 25, 28, 32, 35, 44-49), linee guida EDPB 01/2025 sulla pseudonimizzazione (versione per consultazione), parere WP29 05/2014 (WP216), D.Lgs. 196/2003, art. 28 del codice deontologico forense e art. 622 c.p. sul segreto professionale, L. 132/2025 (art. 13), Regolamento (UE) 2024/1689 (AI Act). Dettagli, link e come ciascuno ha influito sul programma sono nella guida in-app e in [`PROGETTO_PRIVATEDOC_AI.md`](PROGETTO_PRIVATEDOC_AI.md). Verifica sempre i testi vigenti.

## Sviluppo

```bash
python -m unittest discover -s tests     # 182 test al 22/10/2026
python test_pipeline.py                  # collaudo end-to-end su uno ZIP multi-formato
ruff check .
python tools/run_gates.py                # ruff + test + benchmark sul corpus inventato (fallisce se un dato resta leggibile)
```

Struttura: `app.py` (API FastAPI) · `backend/` (estrazione, anonimizzazione, archivio cifrato, servizio, bridge browser) · `static/` (interfaccia e guida) · `tests/` · `PrivateDocAI.spec` e `build_exe.bat` (eseguibile) · `check_dist.py` (controllo pre-distribuzione) · `tools/` (benchmark e controlli automatici, corpus di prova inventato).

La documentazione tecnica completa (architettura, scelte, revisione di sicurezza) è in [`PROGETTO_PRIVATEDOC_AI.md`](PROGETTO_PRIVATEDOC_AI.md).

Le analisi della Milestone 2 sono conservate in [`docs/ANALISI_VAULT.md`](docs/ANALISI_VAULT.md), [`docs/PROTOTIPO_ONNX_INT8.md`](docs/PROTOTIPO_ONNX_INT8.md), [`docs/MISURE_SOSTITUZIONE.md`](docs/MISURE_SOSTITUZIONE.md), [`docs/MISURE_CONTESTO.md`](docs/MISURE_CONTESTO.md) e [`docs/DISEGNO_DOWNLOAD_MODELLO.md`](docs/DISEGNO_DOWNLOAD_MODELLO.md). In sintesi: INT8 non entra nel prodotto perché perde richiamo sulle carte di pagamento; Aho-Corasick non entra perché la regex è già rapida alle dimensioni normali e il prototipo non è semanticamente equivalente; l'anti-rollback è rimandato perché un'ancora locale non copre ripristini congiunti o amministratori locali e non deve rischiare di bloccare l'utente. Il download manager è invece implementato; installer e firma restano rimandati perché richiedono identità di firma, certificato, gestione della reputazione SmartScreen e collaudo su installazioni Windows reali.

## Licenza

Copyright © 2026 Signor P.

Distribuito con licenza **GNU AGPL-3.0** (vedi [`LICENSE`](LICENSE)). È la scelta coerente con le dipendenze: PyMuPDF è AGPL-3.0 (o commerciale) ed `extract-msg` è GPL-3.0. Chi distribuisce il programma, o lo offre come servizio in rete, deve rendere disponibile il codice sorgente corrispondente alle stesse condizioni. Le altre dipendenze (FastAPI, EasyOCR, Playwright, ecc.) mantengono le loro licenze.

## Cronologia delle versioni

Vedi [`CHANGELOG.md`](CHANGELOG.md).
