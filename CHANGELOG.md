# Changelog

Formato ispirato a [Keep a Changelog](https://keepachangelog.com/it/1.1.0/); le date sono nel formato AAAA-MM-GG.

## [Non rilasciato]

### Aggiunto
- **Riconoscimento avanzato facoltativo** (`backend/ner.py`): un modello locale (rizzo-pii 0.3B, MIT, su CPU) usato *in aggiunta* alle regole per nomi in contesto, società, numeri di ruolo, dati catastali e documenti d'identità. Non è incluso: può essere installato dalla UI soltanto dopo consenso esplicito, oppure copiato manualmente in `models/`; i file sono verificati con SHA-256 e caricati solo da disco, senza download impliciti. La barra laterale mostra sempre se è attivo, non installato o rifiutato, con un «profilo esteso» (città, CAP, età, sesso, ora) spento per impostazione predefinita. Regole e codici a forma fissa hanno la precedenza; senza modello tutto funziona come prima. Verifica SHA-256 di tutti i file del modello (in sottofondo, prima dell'uso), fusione con le regole documento per documento, un guasto del modello non blocca il caricamento (il documento resta con le sole regole e lo segnala), letture oltre i 512 token a finestre, `requirements-ner.txt`, build che fallisce se mancano le librerie del modello e `PrivateDocAI.exe --self-test`.
- `tools/benchmark_detectors.py`: confronto locale tra sole regole e regole + modello, documento per documento, con un elenco opzionale di dati che non devono sopravvivere (fughe misurate con e senza modello); esempio inventato in `tools/esempio_benchmark/`.
- `NOTICE.md` con le attribuzioni dei componenti di terzi facoltativi.
- Nuovi dati riconosciuti con regole: numeri di ruolo (R.G.), polizza, sinistro, pratica, protocollo, REA, codice destinatario/SDI, CIG, CUP, estremi catastali completi (foglio, particella, subalterno), telaio/VIN, documento d'identità (carta, passaporto, patente), BIC/SWIFT e matricola.
- Altre formule di definizione negli atti: «d'ora innanzi», «qui di seguito», «nel seguito», «in appresso», «per brevità», «nel prosieguo anche», definizioni senza parentesi («..., di seguito “X”,»), sigle tra parentesi o con «con sigla».

- **Ripristino tollerante dei segnaposto:** se la risposta dell'LLM altera un codice (`[persona_1]`, `[ PERSONA 2 ]`, `PERSONA_1` senza parentesi), il programma lo ripristina lo stesso, ma solo per i codici di quella pratica, e te lo segnala nel passo del risultato; un codice di una categoria nota che non esiste (`[PERSONA_9]`) resta com'è e viene segnalato. Il testo già ripristinato non viene riletto.
- **Validatori di formato** (`backend/validators.py`): IBAN (modulo 97 e lunghezza per paese), codice fiscale (carattere di controllo, omocodia) e partita IVA (cifra di controllo). Servono ad **ampliare** il riconoscimento (IBAN scritti a gruppi di quattro, partita IVA con prefisso `IT` senza etichetta) e mai a togliere maschere: un refuso o un errore di lettura non rende leggibile un dato.
- `tools/corpus_regressione/` (tre atti inventati con elenco dei dati attesi) e `tools/run_gates.py`: un solo comando che esegue ruff, i test e il benchmark e fallisce se un dato del corpus resta leggibile.
- **Download su richiesta del modello locale:** consenso esplicito in interfaccia, sorgente a revisione immutabile, download riprendibile in staging, verifica di dimensione e SHA-256 per ogni file, installazione atomica, annullamento, proxy/CA aziendali e fallback manuale. Il modello non viene mai scaricato implicitamente.
- **Categorie personalizzate riutilizzabili:** ricerca tollerante nell'elenco, creazione dalla selezione con il tasto destro o dalle parole sospette, identificatori sicuri e libreria condivisa tra le pratiche ma cifrata nel vault.
- **Esportazione PDF con censura reale:** riquadro nero o etichetta del codice; rimozione di testo, immagini e grafica sovrapposte, metadati, XMP, annotazioni, link, allegati, moduli, outline, JavaScript, livelli nascosti e vecchie revisioni incrementali. L'originale viene ricaricato ma non entra nella pratica e non viene conservato dall'applicazione. Il file viene consegnato esclusivamente dopo un secondo controllo fail-closed; PDF scansionati e contenuti non verificabili vengono rifiutati. Limiti per esportazione: 50 MB, 500 pagine, 5.000 dati protetti; risposta non memorizzabile nella cache.
- Corpus PDF interamente sintetico con casi avversari e verificatore indipendente per testo spezzato, contenuti nascosti, superfici accessorie, font anomali e revisioni incrementali.
- Strumenti e rapporti della Milestone 2 per misurare sostituzioni ad alto volume, prototipare Aho-Corasick e ONNX FP32/INT8, analizzare i falsi positivi contestuali e il rischio di rollback del vault.

### Modificato
- L'attesa della verifica del modello rispetta l'annullamento e la disattivazione; un caricamento durante la verifica attende il modello invece di usare le sole regole, e un modello rifiutato è indicato nella scheda del documento.
- I termini definiti valgono **nel documento che li definisce**: in un altro atto la stessa parola non viene presunta (se compare senza definizione viene segnalata come sospetta); le definizioni di un documento rimosso spariscono con lui.
- Termini definiti negli atti («d'ora in avanti», «di seguito», «in seguito», «nel prosieguo», «detta/denominata…»): un nome, una sigla o un secondo nome della stessa parte riceve **lo stesso codice** della parte definita, anche senza virgolette (`Zeta Holding s.p.a. (d'ora in avanti denominata Omega)`); le parole di ruolo di uso comune (Compagnia, Contraente, Società, Socio di Maggioranza…) restano leggibili e non diventano mai entità. Con «rispettivamente» si lega solo l'ultimo gruppo; le sigle si cercano solo con le maiuscole esatte. Il nome di una società scritto senza la forma societaria non è più una seconda entità. Le definizioni sopravvivono al salvataggio e alla riapertura della pratica.
- Le locuzioni `Catasto Fabbricati` e `The Service` non vengono più scambiate per nomi di persona; il corpus di regressione raggiunge precisione, richiamo e F1 pari a 1,00.

### Decisioni tecniche
- **ONNX INT8 non adottato:** accelera l'inferenza e riduce memoria e spazio, ma nel corpus raro dimezza il richiamo sulle carte di pagamento (da 2/3 a 1/3). In un'applicazione di privacy il gate per classe prevale sulla metrica aggregata; resta il backend FP32.
- **Aho-Corasick non adottato:** la regex corrente è già rapida per le decine/centinaia di entità ordinarie e fino a circa 1.000. Il prototipo diventa utile solo su volumi molto superiori e non replica ancora tutte le semantiche di `mask_text`; integrarlo ora aggiungerebbe complessità senza un beneficio d'uso normale.
- **Anti-rollback del vault rimandato:** un'ancora DPAPI locale rileverebbe soprattutto il ripristino accidentale della sola cartella dati, ma non un ripristino congiunto né un amministratore locale; inoltre non deve introdurre lockout o ostacolare il recupero. L'analisi resta come riferimento per un futuro scenario multiutente o di rischio concreto.
- **Installer firmato rimandato:** servono identità di firma, certificato, gestione della reputazione SmartScreen e collaudi su installazioni Windows reali. L'eseguibile portabile resta il canale attuale.

## [0.1.0] - 2026-10-21

Prima versione pubblicata.

### Aggiunto
- Lettura di PDF (anche scansionati, con OCR), Word, ODT, Excel, email `.eml`/`.msg`, testo, archivi ZIP annidati e cartelle intere con sottocartelle.
- Pseudonimizzazione deterministica (persone, società, codice fiscale, partita IVA, IBAN, email, telefoni, indirizzi, date, importi, carte, targhe): lo stesso dato riceve sempre lo stesso codice in tutti i documenti; cognomi da soli, nomi con particelle, apostrofi e trattini.
- Controllo pre-invio sul testo in uscita: i dati riconosciuti ancora in chiaro bloccano copia e invio; le parole sospette richiedono una conferma esplicita; menu col tasto destro per mascherare altro testo selezionato.
- Pratiche salvate e cifrate (AES-256-GCM, chiave derivata con scrypt) con password iniziale di almeno 12 caratteri; riapertura dopo il riavvio con gli stessi codici.
- Selezione dei documenti da includere nella richiesta («Seleziona tutti»), numerazione fissa, aggiunta e rimozione di documenti, interruzione del caricamento tenendo o scartando quanto già caricato, elenco dei file non considerati con nome, percorso e motivo.
- Caricamento a lotti con contatore (file elaborati e mancanti, tempo stimato, pagine OCR) e OCR in parallelo.
- Invio automatico a Gemini; «Copia & Decifra» per ChatGPT e Claude, che bloccano i browser automatici.
- Ripristino locale dei dati reali nella risposta ed esportazione in Word.
- Guida in-app (`/guida`) con uso, limiti e riferimenti normativi.
- Eseguibile per Windows (PyInstaller, cartella) con controllo automatico che la cartella da distribuire non contenga dati di lavoro.

### Sicurezza
- Il server risponde solo a richieste dirette a `localhost`, con un token casuale per avvio (difesa da siti esterni e DNS rebinding), mai nell'indirizzo.
- Archivio cifrato con dati autenticati legati alla pratica, parametri di derivazione limitati, rallentamento dopo tentativi sbagliati e scrittura atomica con `fsync`.
- Il blocco dell'archivio invalida invii e caricamenti già in corso: risposte o documenti arrivati tardi vengono scartati con controllo atomico, senza ricreare sessioni decifrate in memoria.

### Limiti noti
- Il riconoscimento dei dati è a regole e non è infallibile: serve sempre la verifica di una persona.
- Le immagini incorporate in documenti non vengono lette; i profili dei browser (`profiles/`) non sono cifrati dal programma.
- Una pratica sostituita con una copia più vecchia non viene riconosciuta; l'eseguibile non è firmato.
