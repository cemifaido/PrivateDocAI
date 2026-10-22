# Documentazione Progetto: PrivateDoc AI
**Data:** 21 Ottobre 2026  
**Stato:** documentazione tecnica del progetto (architettura, scelte, limiti, sicurezza)

---

## 1. Vision & Obiettivi
Permettere a un utente **non addetto ai lavori** (privo di IDE, terminale o competenze di sviluppo) di:
1. **Analizzare e confrontare documenti riservati** (contratti, offerte, scambi email, fogli di calcolo) tramite modelli linguistici (Gemini, ChatGPT, Claude).
2. **Pseudonimizzazione Assistita con Revisione (Conforme a EDPB Guidelines 01/2025)**: prima che il testo esca dal computer locale, tutti i dati sensibili (nomi, società, codici fiscali, IBAN, date, importi, email, telefoni) vengono sostituiti con identificatori pseudonimi coerenti. La schermata di revisione permette all'utente di verificare ed integrare i filtri prima della trasmissione.
3. **Mantenere la Coerenza Cross-Documentale**: se "Mario Rossi" o "Acme S.r.l." compaiono in più documenti o allegati diversi (es. Contratto Word, foglio Excel e messaggio di posta), ricevono **lo stesso identico token** (es. `[PERSONA_1]`, `[SOCIETA_A]`, `[IMPORTO_1]`), consentendo all'LLM di eseguire confronti semantici, incrociare scadenze e individuare incongruenze.
4. **Nessuna Chiave API (No-API-Key)**: l'utente accede semplicemente con la propria **username e password** (o account Google/SSO) al provider prescelto tramite sessione browser persistente, oppure sfrutta la modalità "Copia & Decifra in 1-Click" senza installazioni.
5. **De-anonimizzazione Locale Istantanea**: una volta ricevuta la risposta del modello, l'app ripristina all'istante i dati reali in chiaro e consente di esportare il report in Word (`.docx`).

---

## 2. Architettura del Sistema

```
                      ┌───────────────────────────────────────────┐
                      │    Interfaccia Grafica Utente (Web UI)    │
                      │  Drag & Drop, Anteprima Dati, Toggle Dati │
                      └─────────────────────┬─────────────────────┘
                                            │
                        ┌───────────────────┴───────────────────┐
                        │      FastAPI Local Server (app.py)     │
                        └───────┬───────────────────────┬───────┘
                                │                       │
            ┌───────────────────┴──────────┐ ┌──────────┴──────────────────┐
            │ DocumentExtractor            │ │ DeterministicAnonymizer     │
            │ - Auto-unzip limitato (.zip) │ │ - Riconoscimento PII/Entità │
            │ - Email (.eml, .msg)         │ │ - Token univoci coerenti    │
            │ - Excel (.xlsx, .xls)        │ │ - Sostituzione ordinata     │
            │ - Word / ODT (.docx, .odt)   │ │ - De-anonimizzazione revers │
            │ - PDF (PyMuPDF + OCR ready)  │ └─────────────────────────────┘
            └──────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │ BrowserBridge         │
                    │ - Playwright Profile  │
                    │ - Login con user/pwd  │
                    │ - Gemini/ChatGPT/Cl.  │
                    │ - Fallback 1-Click    │
                    └───────────────────────┘
```

---

## 3. Moduli Implementati

| File | Responsabilità |
| :--- | :--- |
| [`start.bat`](start.bat) | Avviatore rapido Windows a doppio clic per utenti finali. |
| [`run.py`](run.py) | Script di avvio che lancia il server Uvicorn e apre in automatico il browser su `http://127.0.0.1:8765`. |
| [`app.py`](app.py) | API REST FastAPI per upload, gestione entità, generazione prompt, esecuzione, export Word, archivio protetto da password (`/api/vault/*`) e pratiche salvate (`/api/pratiche/*`). Finché l'archivio è bloccato le API rispondono 423. L'upload gira in un thread a parte (`/api/upload/progress` e `/api/upload/cancel` per avanzamento e interruzione). |
| [`backend/vault.py`](backend/vault.py) | Archivio cifrato delle pratiche: password principale → chiave scrypt → AES-256-GCM; scrittura atomica; un file `.enc` per pratica in `data/pratiche/`. |
| [`backend/runtime.py`](backend/runtime.py) | Percorsi per l'esecuzione da sorgente e da eseguibile (risorse nel pacchetto, dati accanto all'`.exe`), rilevamento di Chrome e dei modelli OCR inclusi. |
| [`PrivateDocAI.spec`](PrivateDocAI.spec) / [`build_exe.bat`](build_exe.bat) | Creazione dell'eseguibile PyInstaller in cartella (non onefile), con pagina web e modelli OCR inclusi. |
| [`backend/extractor.py`](backend/extractor.py) | Ingestione multi-formato per archivi `.zip` ricorsivi, messaggi `.eml`/`.msg`, fogli `.xlsx`/`.xls`, documenti `.docx`/`.odt` e PDF, con OCR opzionale e limiti cumulativi sugli archivi. `extract_with_report` restituisce anche i file non considerati (nome, percorso completo, motivo) e accetta percorsi di cartelle; ignora i file di servizio (`Thumbs.db`, `.DS_Store`, `~$…`, `__MACOSX`). OCR delle pagine scansionate in parallelo (fino a 4 lettori EasyOCR, a gruppi di pagine), con avanzamento e interruzione. |
| [`backend/anonymizer.py`](backend/anonymizer.py) | Motore deterministico con normalizzazione canonica, dizionario biunivoco in memoria locale e de-anonimizzazione con tolleranza sintattica. Mascheramento in un'unica regex combinata; cognomi da soli agganciati al nome completo; nomi con particelle, apostrofi e trattini; controllo pre-invio (`verify_masking_coverage`, `find_unmasked_suspects`). |
| [`backend/browser_bridge.py`](backend/browser_bridge.py) | Gestore sessioni Playwright con profili in `profiles/`. Invio automatico solo per Gemini; ChatGPT e Claude (`MANUAL_ONLY`) sono bloccati dalla verifica anti-bot e si usano con Copia & Decifra. Stato di connessione reale (connesso, non connesso, login aperto, bloccato, errore). Da eseguibile usa il Chrome installato. |
| [`backend/document_service.py`](backend/document_service.py) | Coordinamento della sessione documentale, assemblaggio prompt strutturato (anche il testo fisso viene mascherato), `preflight_report` (dati ancora in chiaro), salvataggio/apertura/rinomina/eliminazione delle pratiche cifrate e generazione report docx. |
| [`static/index.html`](static/index.html) | Markup moderno in 4 passi (Upload, Scudo Privacy, Elabora, Risultato). |
| [`static/style.css`](static/style.css) | Design premium dark-mode, glassmorphism, responsive con palette HSL/indaco/smeraldo. |
| [`static/guida.html`](static/guida.html) | Guida in-app (`/guida`, link nella barra laterale): uso passo per passo, limiti, avvertenze sul provider e tabella dei riferimenti normativi (GDPR, linee guida EDPB 01/2025, WP29 WP216, Codice privacy, segreto professionale, L. 132/2025, AI Act) con l'effetto di ciascuno sul programma. Fonti ufficiali verificate il 21/10/2026; EDPB 01/2025 è indicata correttamente come versione 1 adottata per consultazione. |
| [`static/app.js`](static/app.js) | Logica client per drag-and-drop, gestione entità in tempo reale, toggle prima/dopo, download, riquadro del controllo pre-invio (blocco, avvisi, protezione con un clic), menu col tasto destro per mascherare testo selezionato nell'anteprima, avviso dei file non considerati, finestra della password e elenco delle pratiche salvate. |
| [`test_pipeline.py`](test_pipeline.py) | Suite di test end-to-end automatizzata su archivio ZIP reale multi-formato. |
| [`tests/test_full_suite.py`](tests/test_full_suite.py) | 71 test `unittest`: estrattore, cartelle caricate con sottocartelle e ZIP annidati, OCR in parallelo e interruzione, file non considerati, anonimizzatore, metadati del prompt, carte/targhe, limiti upload, API, archivio cifrato, race di blocco e pratiche salvate. |

---

## 4. Esito Collaudo End-to-End (`test_pipeline.py`)

Il test simula un caso reale aziendale:
1. Viene creato un archivio `Pacchetto_Completo.zip` contenente un contratto Word, un foglio Excel con prezzi e scadenze, e un'email `.eml`.
2. L'estrattore decomprime l'archivio e normalizza tutti i 3 documenti.
3. L'anonimizzatore individua 15 entità sensibili nel campione corrente.
4. **Verifica coerenza**: `Mario Rossi` riceve `[PERSONA_1]` sia nel Word, sia nell'Excel, sia nell'Email. `Acme S.r.l.` riceve `[SOCIETA_A]`. L'importo `150.000 €` riceve `[IMPORTO_1]`.
5. **Verifica de-anonimizzazione**: La risposta simulata dell'LLM (contenente solo i token) viene decifrata con successo, ripristinando integralmente i dati reali originali.
6. **Esito**: `100% Superato con successo (Exit code 0)`.

Dopo le revisioni interne (21/10/2026), il test controlla anche che nessuna entità rilevata resti in chiaro nel testo mascherato. La suite `unittest` (`python -m unittest discover -s tests`) esegue 71 test, inclusi casi di regressione per nomi file, carte di pagamento, targhe, ZIP annidati, upload eccessivi, file non considerati, archivio cifrato e operazioni concorrenti al blocco; `ruff` non segnala nulla. I test dell'archivio usano una cartella temporanea: la vera `data/` non viene toccata.

---

## 5. Controllo Pre-invio e Limiti Noti

**Come funziona.** Prima di inviare o copiare il prompt, `preflight_report` esamina l'esatto prompt già assemblato e mascherato:
- `leaks`: entità registrate ancora leggibili. Se non è vuoto, `/api/execute` non invia nulla e la copia del prompt viene bloccata.
- `suspects`: parole con la maiuscola a metà frase non riconosciute dal rilevatore, più i cognomi condivisi da persone diverse. Non bloccano: l'interfaccia le mostra come pulsanti e un clic le aggiunge come PERSONA.
- I nomi originali di file e archivi non sono trasmessi: ogni sezione usa soltanto un indice, il formato e l'indicazione generica dell'eventuale archivio.

**Scelte di progetto.**
- Un cognome da solo (`Rossi`) riusa il token del nome completo solo se appartiene a una persona sola. Con due persone che hanno lo stesso cognome resta in chiaro e viene segnalato, per non attribuire frasi alla persona sbagliata.
- Le parole comuni dei documenti (`Pagina`, `Tribunale`, `Civile`, inizi di frase come `Poi`) sono in `STOPWORDS` e non diventano persone.
- Carte di pagamento valide secondo Luhn e targhe italiane standard vengono pseudonimizzate con categorie dedicate.
- L'API legge gli upload a blocchi: massimo 50 MB per file e 100 MB per richiesta. Gli ZIP condividono un unico budget ricorsivo di 50 MB non compressi, 100 elementi e 3 livelli.

**Limiti noti.**
- Il rilevamento è a espressioni regolari, senza NER: nomi insoliti o scritti in minuscolo possono sfuggire. Il controllo pre-invio è un aiuto, non una garanzia.
- Caricamento a lotti con contatore (elaborati / mancanti, tempo stimato, pulsante «Interrompi»): una cartella con centinaia di file viene inviata a gruppi (max 8 file o 15 MB; i PDF uno alla volta). L'OCR gira su CPU e legge tutte le pagine scansionate, a gruppi e in parallelo (fino a 4 lavoratori, ciascuno con il proprio lettore): su questo PC circa 9,4 s a pagina con un lavoratore e 6,2 s con quattro; abbassare la risoluzione non cambia i tempi in modo apprezzabile. Durante la lettura l'interfaccia mostra «pagine OCR X di Y»; «Interrompi» ferma anche un PDF a metà e le pagine non lette sono elencate tra i file non considerati.
- EasyOCR è il motore preferito. Il fallback `pytesseract` richiede il programma Tesseract e le lingue `ita`/`eng` installati nel sistema; se nessun motore è disponibile, la pagina viene segnalata come scansionata ma non produce testo OCR.
- Il Browser Bridge dipende dai selettori delle interfacce web dei provider e può rompersi. ChatGPT e Claude mostrano una verifica anti-bot (Cloudflare) ai browser automatici e il login Google li rifiuta: per loro l'app apre il sito nel browser normale e si lavora con Copia & Decifra, che è il percorso più solido. Gemini funziona con l'invio automatico. Per ChatGPT e Claude l'app non visita più i siti con il browser automatico (stato «uso manuale»), e non usa più tecniche per nascondere l'automazione (`--disable-blink-features=AutomationControlled` rimosso). Alternative valutate con Codex: CDP su Chrome personale sconsigliato (porta di debug = accesso ampio al profilo, nessuna garanzia contro l'anti-bot né sui termini d'uso); da valutare per ChatGPT «Sign in with ChatGPT» (OAuth/PKCE, richiede registrazione) o le API ufficiali con chiave dell'utente; per Claude manuale o API ufficiale.
- I profili browser in `profiles/` sono esclusi da Git ma non cifrati dall'applicazione: devono essere protetti dai permessi dell'account Windows.
- Le pratiche sono salvate automaticamente e cifrate in `data/pratiche/`; ricaricando la pagina o riavviando il PC si riaprono dall'elenco inserendo la password. **La password non è recuperabile**: se viene dimenticata le pratiche non sono più leggibili. L'interfaccia non mostra ancora la cronologia delle analisi passate (le risposte decifrate sono salvate, le richieste no).
- I file non considerati (formati non supportati, percorsi non sicuri, limiti degli archivi) sono elencati nel passo 1 con nome, percorso e motivo. Le immagini incorporate dentro Word, PDF con testo o email non sono file separati e non vengono lette.
- Complessità: nessuna funzione dell'anonimizzatore supera il grado C; le più complesse restano `_extract_excel` (C, 17), `_process_zip` (C, 15) e `execute_prompt` (C, 12).

---

## 6. Archivio Protetto e Pratiche Salvate

- **Prima apertura:** l'app chiede una password (due volte, minimo 12 caratteri) e avvisa di annotarla. Non esiste recupero.
- **Cifratura:** AES-256-GCM, chiave derivata con scrypt (N=2^16, r=8, p=2) e sale casuale in `data/vault.json`. Ogni pratica v2 è un file `data/pratiche/<id>.enc` autenticato anche con il proprio identificativo (AAD), con nonce casuale; la scrittura è atomica con `fsync`. La chiave resta solo in memoria.
- **Contenuto di una pratica:** testi estratti, entità e token (quindi `[PERSONA_1]` resta lo stesso nelle analisi successive), elenco dei file non considerati e risposte decifrate. Le modifiche ravvicinate vengono aggregate per un massimo di 3 secondi; risposte, blocco e chiusura forzano il salvataggio.
- **Uso:** "Pratiche salvate" nel passo 1 (Apri / Elimina), nome modificabile, "Nuova Pratica", "Blocca archivio" (svuota i dati decifrati dalla memoria).
- **Non cifrati:** i profili browser in `profiles/` (cookie di Gemini).

## 7. Eseguibile (PyInstaller, cartella)

- Build: `build_exe.bat` (o `python -m PyInstaller --noconfirm --clean PrivateDocAI.spec`) crea `dist\PrivateDocAI` (circa 1,3 GB con EasyOCR/PyTorch e modelli inclusi). Si distribuisce l'intera cartella.
- Dati e profili stanno accanto all'`.exe` (`data\`, `profiles\`), quindi la cartella deve essere scrivibile.
- Per Gemini serve Google Chrome installato (il Chromium di Playwright non è incluso).
- Variabili utili: `PRIVATEDOC_PORT` (porta, default 8765), `PRIVATEDOC_NO_BROWSER=1` (non apre il browser), `PRIVATEDOC_DATA_DIR` (cartella dati).
- L'`.exe` non è firmato: SmartScreen o l'antivirus possono avvisare.
- **Stato della verifica:** la build è terminata correttamente, ma l'esecuzione dell'`.exe` non è stata provata dall'ambiente di sviluppo (avvio negato dal sistema). Va collaudata su un PC reale.

## 8. Caricamento di Cartelle e Documenti Lunghi

- **Cartelle:** si possono trascinare nella zona di caricamento o scegliere con «Scegli una cartella». Sottocartelle e ZIP (anche annidati) sono letti; ogni file mantiene il percorso, mostrato negli avvisi (`Fascicolo/atti/allegati.zip > logo.png`).
- **Lotti e contatore:** il browser invia i file a gruppi (massimo 8 file o 15 MB; i PDF uno alla volta) e mostra «Elaborati X di Y · mancano Z · tempo stimato · in corso: …». Per i PDF scansionati si aggiunge «lettura pagine (OCR): X di Y». «Interrompi» ferma i gruppi successivi e l'OCR in corso; quanto già letto resta nella pratica.
- **Analisi incrementale:** a ogni lotto le entità si cercano solo nei file appena aggiunti, non sull'intero archivio.
- **OCR:** nessun limite di pagine. Misurato su questo PC (12 core, EasyOCR su CPU): 9,4 s a pagina con un lettore, 6,2 s con quattro (1,6 volte più veloce); più di 4 lettori non aiutano e la risoluzione (100 dpi) incide poco sui tempi. Un PDF di 100 pagine scansionate richiede circa 10 minuti. Ogni lettore occupa alcune centinaia di MB di RAM.
- **Sicurezza di rete:** ChatGPT e Claude non vengono più visitati dal browser automatico (stato «uso manuale») e il parametro che nasconde l'automazione è stato rimosso, su indicazione di Codex.

## 9. Scelta, Rimozione e Interruzione dei Documenti

- **Numerazione fissa:** ogni documento ha un numero («Documento 3») che non cambia quando altri vengono rimossi; il testo inviato usa gli stessi numeri e i nomi dei file non escono dal computer.
- **Selezione:** nel passo 3 caselle per ogni documento e «Seleziona tutti» (anche parziale). Solo i documenti spuntati vengono mascherati, controllati e inviati; con zero documenti l'invio è rifiutato. La scelta è salvata nella pratica.
- **Aggiungere** documenti a una pratica aperta mantiene i codici già assegnati; i nuovi sono selezionati per impostazione predefinita.
- **Rimuovere** un documento (passo 1 o 3, con conferma) elimina il suo testo dalla pratica; i dati protetti restano nell'elenco del passo 2 per non cambiare i codici e si tolgono da lì.
- **Interrompere un caricamento:** «Interrompi e tieni quanto caricato» oppure «Interrompi e scarta» (rimuove solo ciò che quell'operazione ha aggiunto, o l'intera pratica se era stata creata da quel caricamento). L'interruzione non attende le pagine OCR in lettura (fino a ~25 s per pagina con 4 lettori): i lettori occupati vengono abbandonati e ricreati alla lettura successiva.
- **Chiusura ordinata:** «⏻ Chiudi programma» (barra laterale) interrompe un caricamento in corso, salva, blocca l'archivio e ferma il server (`/api/shutdown`). Ctrl+C non stampa più i traceback di annullamento.

## 10. Revisione di Sicurezza (21/10/2026) e Correzioni

Rischi segnalati dalla revisione critica e stato:
- **Sito esterno che pilota l'app (CSRF / DNS rebinding) — corretto.** Ogni richiesta deve avere come `Host` solo `127.0.0.1` o `localhost`; le API richiedono un **token casuale generato a ogni avvio** (inserito solo nella pagina servita, non nel JS statico) e, se presente, un `Origin` uguale all'app. Test con host e origine ostili.
- **Invio/copia non uniformi — corretto.** Copia, copia dall'anteprima e invio automatico seguono la stessa regola: dati riconosciuti ancora in chiaro = bloccato; parole sospette = conferma esplicita (`needs_confirmation` / `confirmed_suspects`). Il server accetta solo la conferma dell'insieme esatto appena mostrato, così una conferma obsoleta non autorizza nuovi sospetti. Le frasi della guida sono state rese prudenti (il rilevamento è euristico).
- **Caricamenti sovrapposti — corretto.** Un solo caricamento alla volta (409 altrimenti); ogni lavoro ha il proprio evento di interruzione e il proprio avanzamento; l'evento precedente non viene mai riazzerato, quindi i lettori OCR abbandonati si fermano da soli; le impostazioni di PyTorch si fissano una volta. Blocco (`RLock`) sulle modifiche e i salvataggi delle sessioni.
- **Archivio cifrato — rafforzato.** File con formato versionato (`PDV2`) e dati autenticati legati all'identificativo della pratica (AAD): un file copiato su un'altra pratica viene rifiutato. scrypt N=2^16, r=8, p=2 (circa 64 MiB) con parametri **letti dal file e limitati**; password di almeno 12 caratteri; rallentamento esponenziale dopo 3 tentativi sbagliati; `fsync` prima della sostituzione; file danneggiati mostrati nell'elenco (non nascosti). Compatibile in lettura con gli archivi della prima versione. **Limite dichiarato:** la sostituzione di un file con una copia più vecchia della stessa pratica non è rilevabile senza un'ancora esterna (DPAPI/TPM/servizio).
- **Numeri e rimozione — corretto.** Contatore dei numeri documento monotono e salvato nella pratica; lo scarto di un'operazione interrotta usa un identificativo di operazione generato dal server/client (non più una lunghezza fornita dal client) e dimentica anche le entità trovate da quell'operazione; «Rimuovi documento» chiede se eliminare anche i dati protetti presenti solo in quel documento (le risposte già salvate che li usano non si decifrano più).
- **Salvataggi — migliorato senza cambiare formato.** Le pratiche restano in un unico file cifrato (più semplice e sicuro per casi di dimensioni normali); le modifiche ravvicinate si scrivono insieme al massimo ogni 3 secondi e subito prima di bloccare, chiudere, elencare le pratiche o salvare una risposta. Il salvataggio a blocchi per documento non è stato adottato: ha senso solo con pratiche molto grandi (centinaia di MB).
- **Distribuzione — controllo automatico.** `build_exe.bat` esegue `check_dist.py` e fallisce se in `dist\PrivateDocAI` compaiono `data`, `profiles`, `vault.json`, file `.enc` o file tipici dei profili del browser. Non avviare mai l'eseguibile dentro la cartella da distribuire. La firma Authenticode dell'`.exe` resta da fare.
- **Guida legale — aggiornata.** EDPB 01/2025 descritta come «versione 1 adottata per consultazione» (consultazione chiusa, ancora v1 sulla pagina ufficiale al 21/10/2026); L. 132/2025 con link a Gazzetta Ufficiale e senza «secondo i commenti»; art. 28 CDF e art. 622 c.p. in righe separate con fonti ufficiali; claim assoluti sostituiti da formulazioni prudenti.
- **Seconda revisione — corretto.**
  - Il blocco dell'archivio durante un invio in corso rendeva possibile far riapparire in memoria la sessione decifrata: ora blocco, salvataggio e svuotamento sono un'unica operazione (`lock_all`) con un contatore di «epoca». Preparazione del prompt e commit della risposta usano lo stesso lock; verifica dell'epoca, decifratura e salvataggio sono atomici e non ricreano sessioni mancanti. Anche il commit di un upload iniziato prima del blocco viene scartato (423). Le modifiche alle entità usano lo stesso lock del servizio.
  - Il token delle API non si accetta più nell'indirizzo (query string): solo nell'intestazione; il report Word si scarica con `fetch` + Blob.
  - Il controllo pre-invio usa `POST` con il corpo JSON, perché la richiesta dell'utente può contenere dati personali e non deve finire nell'indirizzo o nei log.
  - La conferma sulle parole sospette riguarda l'elenco esatto di quel momento (`confirmed_suspects`): un «sì» vecchio non autorizza parole comparse dopo.
  - L'archivio v2 richiede che l'identificativo dentro il file coincida con quello della pratica.

## 11. Termini Definiti negli Atti

Negli atti le parti sono definite con formule del tipo `Delta Mutual Insurance Europe SE (d'ora in avanti, “Compagnia” o “Delta”)`. La regola (deterministica, in `backend/anonymizer.py`) è:
- **Un nome** (marchio, sigla, altro nome proprio, con o senza virgolette) ricevuto in una definizione ottiene **lo stesso codice** della parte definita: `[SOCIETA_1] (d'ora in avanti denominata [SOCIETA_1])` mantiene un solo soggetto nel ragionamento.
- **Una parola di ruolo** d'uso comune (`LEGAL_ROLE_WORDS`: Compagnia, Contraente, Società, Polizza, Socio di Maggioranza, Attrice, Convenuta…) **non si maschera e non diventa un'entità**: la frase di definizione resta nel testo e il modello capisce da sola chi è.
- **«rispettivamente»:** solo l'ultimo gruppo di termini si lega alla parte subito prima della parentesi; i termini degli altri gruppi, se sembrano nomi, finiscono tra i sospetti da decidere.
- **Sigle** (es. `TI`): si cercano solo con le maiuscole esatte, per non toccare parole come «ti».
- **Nome senza forma societaria** (`Zeta Holding` per `Zeta Holding s.p.a.`): stesso codice della società, non una persona.
- Un termine scelto dall'utente a mano non viene mai ripreso dalla regola; le definizioni si salvano nella pratica.
- **Ambito:** il codice di una parte vale in tutta la pratica, ma il legame con un nome definito vale **solo nel documento che lo definisce**; nello stesso atto o con il nome presente in un altro atto senza definizione, il nome viene segnalato come sospetto invece di essere presunto. Le definizioni di un documento rimosso o scartato spariscono con lui.
- **Formule coperte:** d'ora in avanti/innanzi, di seguito, qui di seguito, in seguito, nel seguito, nel prosieguo (anche), in appresso, per brevità, c.d., denominata/detta/definita/chiamata, «anche», definizioni senza parentesi, sigle in parentesi o «con sigla».
- **Nuovi dati con regole:** R.G., polizza, sinistro, pratica, protocollo, REA, SDI, CIG, CUP, estremi catastali, telaio/VIN, documento d'identità, BIC, matricola.
- Limiti: non si gestiscono i plurali («le Compagnie») né le definizioni scritte senza virgolette fuori dalle parentesi. Si è scelta una regola e non un modello linguistico perché è prevedibile, verificabile con test e non può «dimenticare» in silenzio un dato.
