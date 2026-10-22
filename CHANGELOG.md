# Changelog

Formato ispirato a [Keep a Changelog](https://keepachangelog.com/it/1.1.0/); le date sono nel formato AAAA-MM-GG.

## [Non rilasciato]

### Aggiunto
- **Riconoscimento avanzato facoltativo** (`backend/ner.py`): un modello locale (rizzo-pii 0.3B, MIT, su CPU) usato *in aggiunta* alle regole per nomi in contesto, società, numeri di ruolo, dati catastali e documenti d'identità. Non è incluso: si scarica a parte in `models/`, i file sono verificati con SHA-256 e caricati solo da disco (nessun download); la barra laterale mostra sempre se è attivo, non installato o rifiutato, con un «profilo esteso» (città, CAP, età, sesso, ora) spento per impostazione predefinita. Regole e codici a forma fissa hanno la precedenza; senza modello tutto funziona come prima. Verifica SHA-256 di tutti i file del modello (in sottofondo, prima dell'uso), fusione con le regole documento per documento, un guasto del modello non blocca il caricamento (il documento resta con le sole regole e lo segnala), letture oltre i 512 token a finestre, `requirements-ner.txt`, build che fallisce se mancano le librerie del modello e `PrivateDocAI.exe --self-test`.
- `tools/benchmark_detectors.py`: confronto locale tra sole regole e regole + modello, documento per documento, con un elenco opzionale di dati che non devono sopravvivere (fughe misurate con e senza modello); esempio inventato in `tools/esempio_benchmark/`.
- `NOTICE.md` con le attribuzioni dei componenti di terzi facoltativi.
- Nuovi dati riconosciuti con regole: numeri di ruolo (R.G.), polizza, sinistro, pratica, protocollo, REA, codice destinatario/SDI, CIG, CUP, estremi catastali completi (foglio, particella, subalterno), telaio/VIN, documento d'identità (carta, passaporto, patente), BIC/SWIFT e matricola.
- Altre formule di definizione negli atti: «d'ora innanzi», «qui di seguito», «nel seguito», «in appresso», «per brevità», «nel prosieguo anche», definizioni senza parentesi («..., di seguito “X”,»), sigle tra parentesi o con «con sigla».

### Modificato
- I termini definiti valgono **nel documento che li definisce**: in un altro atto la stessa parola non viene presunta (se compare senza definizione viene segnalata come sospetta); le definizioni di un documento rimosso spariscono con lui.
- Termini definiti negli atti («d'ora in avanti», «di seguito», «in seguito», «nel prosieguo», «detta/denominata…»): un nome, una sigla o un secondo nome della stessa parte riceve **lo stesso codice** della parte definita, anche senza virgolette (`Zeta Holding s.p.a. (d'ora in avanti denominata Omega)`); le parole di ruolo di uso comune (Compagnia, Contraente, Società, Socio di Maggioranza…) restano leggibili e non diventano mai entità. Con «rispettivamente» si lega solo l'ultimo gruppo; le sigle si cercano solo con le maiuscole esatte. Il nome di una società scritto senza la forma societaria non è più una seconda entità. Le definizioni sopravvivono al salvataggio e alla riapertura della pratica.

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
