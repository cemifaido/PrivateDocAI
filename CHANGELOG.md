# Changelog

Formato ispirato a [Keep a Changelog](https://keepachangelog.com/it/1.1.0/); le date sono nel formato AAAA-MM-GG.

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
