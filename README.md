# 🛡️ PrivateDoc AI

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
4. **Invio:** automatico con Gemini; con ChatGPT e Claude si usa «Copia & Decifra» (copia il testo anonimo, incolla la risposta).
5. **Risultato** con i dati reali, esportabile in Word.

## Caratteristiche

- **Formati:** PDF (anche scansionati, con OCR), Word, ODT, Excel, email `.eml`/`.msg`, testo, ZIP annidati, cartelle.
- **Pratiche salvate e cifrate:** password iniziale, archivio AES-256-GCM, riapri il lavoro dopo il riavvio e fai nuove domande con gli stessi codici.
- **Scelta dei documenti** da includere nella richiesta («confronta il Documento 3 con il 7»), con numerazione fissa; i nomi dei file non vengono inviati.
- **Caricamenti grandi:** contatore dei file mancanti, interruzione (tenendo o scartando quanto caricato), OCR in parallelo.
- **File non supportati** (ad esempio le foto) elencati con nome, percorso e motivo, invece di essere ignorati in silenzio.
- **Riconoscimento avanzato facoltativo:** un modello locale (MIT, su CPU, scaricato a parte) si affianca alle regole per nomi in contesto, società, numeri di ruolo e dati catastali; la barra laterale mostra sempre se è attivo. Vedi [`NOTICE.md`](NOTICE.md) e la sezione 12 di [`PROGETTO_PRIVATEDOC_AI.md`](PROGETTO_PRIVATEDOC_AI.md).
- **Guida in-app** (`/guida`) con uso, limiti e riferimenti normativi.

## Avvio rapido

### Con l'eseguibile (consigliato)

Costruiscilo con `build_exe.bat` (richiede Python e le dipendenze) e copia l'**intera cartella** `dist\PrivateDocAI` sul PC. Avvia `PrivateDocAI.exe`: si apre il browser su `http://127.0.0.1:8765`. Al primo avvio scegli la password dell'archivio (almeno 12 caratteri) e **annotala: non è recuperabile**.

- Per l'invio automatico a Gemini serve Google Chrome installato.
- L'`.exe` non è firmato: Windows può mostrare un avviso.
- Le cartelle `data` e `profiles` si creano accanto all'`.exe`: non distribuire una cartella già usata (`build_exe.bat` controlla che sia pulita).

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

- Il rilevamento è a espressioni regolari, senza riconoscimento di entità (NER): nomi insoliti o dati scritti in modo anomalo possono sfuggire. I fatti descritti nel testo possono identificare le persone anche senza nomi.
- **ChatGPT e Claude non sono automatizzabili:** i loro siti bloccano i browser automatici (e il programma non cerca di aggirare i controlli). Si usa «Copia & Decifra».
- L'OCR gira su CPU: circa 6-10 secondi a pagina; 100 pagine scansionate richiedono circa 10 minuti.
- Una pratica sostituita con una copia più vecchia della stessa non viene riconosciuta (serve un'ancora esterna).
- Le immagini incorporate in Word, PDF con testo o email non vengono lette.
- Il programma non gestisce l'informativa al cliente, la base giuridica, i contratti con il fornitore di IA né la valutazione d'impatto: restano a carico di chi lo usa.

## Riferimenti normativi

GDPR (art. 4 n. 5, considerando 26, artt. 5, 25, 28, 32, 35, 44-49), linee guida EDPB 01/2025 sulla pseudonimizzazione (versione per consultazione), parere WP29 05/2014 (WP216), D.Lgs. 196/2003, art. 28 del codice deontologico forense e art. 622 c.p. sul segreto professionale, L. 132/2025 (art. 13), Regolamento (UE) 2024/1689 (AI Act). Dettagli, link e come ciascuno ha influito sul programma sono nella guida in-app e in [`PROGETTO_PRIVATEDOC_AI.md`](PROGETTO_PRIVATEDOC_AI.md). Verifica sempre i testi vigenti.

## Sviluppo

```bash
python -m unittest discover -s tests     # 71 test
python test_pipeline.py                  # collaudo end-to-end su uno ZIP multi-formato
ruff check .
```

Struttura: `app.py` (API FastAPI) · `backend/` (estrazione, anonimizzazione, archivio cifrato, servizio, bridge browser) · `static/` (interfaccia e guida) · `tests/` · `PrivateDocAI.spec` e `build_exe.bat` (eseguibile) · `check_dist.py` (controllo pre-distribuzione).

La documentazione tecnica completa (architettura, scelte, revisione di sicurezza) è in [`PROGETTO_PRIVATEDOC_AI.md`](PROGETTO_PRIVATEDOC_AI.md).

## Licenza

Copyright © 2026 Signor P.

Distribuito con licenza **GNU AGPL-3.0** (vedi [`LICENSE`](LICENSE)). È la scelta coerente con le dipendenze: PyMuPDF è AGPL-3.0 (o commerciale) ed `extract-msg` è GPL-3.0. Chi distribuisce il programma, o lo offre come servizio in rete, deve rendere disponibile il codice sorgente corrispondente alle stesse condizioni. Le altre dipendenze (FastAPI, EasyOCR, Playwright, ecc.) mantengono le loro licenze.

## Cronologia delle versioni

Vedi [`CHANGELOG.md`](CHANGELOG.md).
