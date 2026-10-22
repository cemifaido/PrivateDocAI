# Architettura e Disegno: Download Manager del Modello NER Locale

**Data**: 22 Ottobre 2026 (Revisione R1)
**Autore**: Gemini (`feat/analisi-prestazioni`)
**Riferimento Piano**: Milestone 2/3 - Fase 1, Compito (b)
**Destinatari**: Team PrivateDoc AI (Claude, Codex, Gemini, Operatore Umano)

**Stato di attuazione**: implementato su `main` il 22 ottobre 2026 in `backend/model_downloader.py`, API e interfaccia, con test dedicati. Le sezioni seguenti conservano il disegno e le motivazioni delle scelte.

---

## 1. Principi Guida e Obiettivi

PrivateDoc AI è un'applicazione desktop concepita attorno al principio cardine della **sovranità e riservatezza del dato**.

Il modello linguistico opzionale (`rizzoaiacademy/rizzo-pii-0.3B`, basato su `mmBERT`, licenza MIT) potenzia il riconoscimento dei dati personali nel contesto del discorso, ma:
1. **Nessun automatismo silente**: Il download non deve **mai** avviarsi in background senza un'azione esplicita e consapevole dell'utente.
2. **Consenso informato e trasparenza**: Prima dell'avvio, l'interfaccia deve indicare con chiarezza:
   - Dimensione esatta del pacchetto: **1,265 GB** (~1,18 GiB su disco).
   - Licenza d'uso aperta (MIT).
   - Fonte ufficiale (Hugging Face Repository alla revisione `v1.5.0`).
   - Garanzia di esecuzione locale sulla CPU: nessun testo verrà mai inviato all'esterno.
3. **Integrità crittografica a prova di manomissione**: Ogni file scaricato viene validato contro un hash **SHA-256 pinnato nel codice** (allineato alle impronte ufficiali in `NOTICE.md`). Se un solo byte non corrisponde, l'intero pacchetto viene scartato.
4. **Resilienza alle reti aziendali**: Supporto pieno a proxy d'impresa (con o senza autenticazione) e certificati CA custom aziendali per gateway TLS.
5. **Funzionamento offline / Air-gapped**: Possibilità per amministratori IT di depositare i file manualmente nella cartella puntata da `PRIVATEDOC_NER_DIR`.

---

## 2. Puntamento Immutabile e Manifest del Modello

### 2.1 Commit SHA Immutabile (Anti-Poisoning)
I repository di modelli su Hugging Face possono aggiornare i branch (incluso `main` o i tag mobili). Per garantire riproducibilità assoluta e impedire attacchi di supply chain, il download deve essere agganciato al commit SHA immutabile della tag ufficiale `v1.5.0`:

* **Repository**: `rizzoaiacademy/rizzo-pii-0.3B`
* **Release di riferimento**: `v1.5.0` (rif. `NOTICE.md`)
* **Commit SHA Hugging Face**: `a1c3c83827eca22e9675e30c1111c4641caf5901` (risolto dalla tag `v1.5.0` il 22 ottobre 2026 e pinnato nell'implementazione)
* **Base URL**: `https://huggingface.co/rizzoaiacademy/rizzo-pii-0.3B/resolve/<COMMIT_SHA>/`

### 2.2 Struttura del Manifest Pinnato (Dati Reali da NOTICE.md)
Il manifest incorpora le dimensioni e gli hash crittografici esatti:

```python
MODEL_MANIFEST = {
    "name": "rizzo-pii-0.3B",
    "version": "1.5.0",
    "license": "MIT",
    "description": "Modello compatto di Named Entity Recognition per PII italiane su CPU (basato su mmBERT)",
    "repository": "rizzoaiacademy/rizzo-pii-0.3B",
    "commit_sha": "a1c3c83827eca22e9675e30c1111c4641caf5901",
    "total_size_bytes": 1_264_687_643,  # ~1.265 GB / 1.178 GiB
    "files": {
        "model.safetensors": {
            "size_bytes": 1_230_273_700,
            "sha256": "b1e046e3aec52c3cd74eaf166b034644a4dac0c91128bf06803e1478657fcd9f"
        },
        "tokenizer.json": {
            "size_bytes": 34_363_286,
            "sha256": "a0ab5772a8c5450f45a66c95985d6df2205bf09449ba7ff7bb46de034eaa118a"
        },
        "tokenizer_config.json": {
            "size_bytes": 46_469,
            "sha256": "3b66ca84514d9aacf4b90c65a61e561127c6c21d81bbf4e8ba9d46a4c15ac82d"
        },
        "config.json": {
            "size_bytes": 3_137,
            "sha256": "6b9d5bdd4a194d40fb40c53fdc302e225514cd7940d97f657c4082454ee7e91b"
        },
        "special_tokens_map.json": {
            "size_bytes": 1_051,
            "sha256": "6e3204c5a4004719c185007a745d1940471a6fb02521cfa0a00306dbb6bc5903"
        }
    }
}
```

---

## 3. Flusso Utente e Richiesta di Consenso

1. **Stato iniziale**:
   L'utente vede l'indicatore nell'interfaccia: *Modello NER opzionale non installato*.
2. **Apertura modale di consenso**:
   Cliccando su *"Attiva modello NER"* si apre un dialogo informativo con:
   - **Dimensione download**: **1,27 GB** (~1,18 GiB).
   - **Tempo stimato**: ~2 minuti con connessione a 100 Mbps (o ~10 minuti con ADSL da 15 Mbps).
   - **Licenza**: Open Source MIT.
   - **Informativa Privacy**: *"Il modello girerà esclusivamente in locale sulla tua CPU. Nessun dato personale o documento verrà mai inviato all'esterno."*
   - Pulsanti: `[Annulla]` / `[Scarica e Installa (~1,27 GB)]`.
3. **Barra di avanzamento**:
   Avanzamento progressivo in percentuale, MB scaricati su 1.265 MB, velocità in MB/s e pulsante `[Annulla]`.

---

## 4. Strategia di Download: Transazionalità e Ripresa HTTP

### 4.1 Gestione Cartelle e Transazionalità su Windows
Su sistema operativo Windows, la funzione `os.replace(src_dir, dst_dir)` fallisce con `PermissionError` o `FileExistsError` se la cartella di destinazione esiste già e non è vuota.

Per garantire un'attivazione atomica e sicura su Windows:
1. **Download in staging isolato**:
   I file vengono scaricati in una cartella di staging temporanea:
   `models/rizzo-pii-0.3B.staging/`; il file in corso usa il suffisso `.part`.
2. **Calcolo hash progressivo**:
   Lo streaming usa blocchi da 1 MiB; dimensione e SHA-256 vengono verificati sul file completato e nuovamente sull'intera staging prima dell'installazione.
3. **Attivazione atomica**:
   Al termine della verifica con successo di tutti i 5 hash:
   - Se la cartella di destinazione finale `models/rizzo-pii-0.3B/` non esiste, `os.replace` sposta la staging direttamente.
   - Se esiste già una versione precedente/corrotta, viene rinominata in `rizzo-pii-0.3B.old`, la nuova staging diventa la cartella finale e solo a esito positivo il backup viene rimosso; in caso di errore viene ripristinato.

### 4.2 Ripresa Download (HTTP Range Resume)
Dato il peso considerevole di `model.safetensors` (1,23 GB), le interruzioni temporanee di rete devono poter riprendere:
- **Richiesta con Range**: Se esiste un file parziale `.part` da $K$ byte, la richiesta HTTP invia l'header `Range: bytes=K-`.
- **Validazione rigorosa della risposta**:
  - Se il server risponde con **HTTP 206 Partial Content**: il flusso viene appeso al file parziale (`open(path, 'ab')`).
  - Se il server ignora il range o risponde con **HTTP 200 OK**: il downloader **non appende** (corromperebbe il file), ma cancella il file parziale e ricomincia da zero (`open(path, 'wb')`).
  - L'accumulatore SHA-256 riparte coerentemente ricalcolando l'hash dei byte già validati su disco.

---

## 5. Supporto per Ambienti Aziendali e Proxy

1. **Rilevamento Proxy di Sistema**:
   - Lettura automatica delle variabili d'ambiente standard:
     `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`.
   - Supporto a proxy con autenticazione (`http://utente:password@proxy.azienda.lan:8080`).
2. **Certificati CA Custom per Gateway di Sicurezza Aziendali (SSL Inspection)**:
   - Negli uffici con firewall a ispezione TLS (es. Zscaler, Fortinet), il downloader rispetta le variabili:
     - `REQUESTS_CA_BUNDLE`
     - `SSL_CERT_FILE`
     - `CURL_CA_BUNDLE`
   - Se configurate, il contesto SSL viene inizializzato con il truststore aziendale specificato, evitando l'errore `CERTIFICATE_VERIFY_FAILED`.

---

## 6. Procedura di Fallback Manuale (Air-Gapped)

Per computer operanti in totale isolamento di rete:
1. L'amministratore copia i 5 file nella cartella di destinazione:
   `models/rizzo-pii-0.3B/` accanto al programma
   (oppure nel percorso configurato tramite la variabile d'ambiente **`PRIVATEDOC_NER_DIR`**).
2. All'avvio dell'applicazione o su richiesta, il sistema valida le impronte SHA-256 e attiva il modello all'istante, **senza alcun tentativo di connessione verso la rete**.

---

## 7. Mappatura dell'Integrazione Realizzata

> [!NOTE]
> La mappatura originaria è stata realizzata nella Fase 2; resta qui come indice dei componenti.

1. **Nuovo modulo `backend/model_downloader.py`**:
   - Contiene repository, revisione, licenza, dimensioni e logica di streaming HTTP nativo con ripresa Range, verifica SHA-256 e gestione proxy/SSL.
   - Espone `info()`, `status()`, `start()`, `cancel()` e `wait()`.
2. **Integrazione in `backend/document_service.py`**:
   - `DocumentService` istanzia e detiene il detector NER (`self.ner`) e il downloader (`self.model_downloader`).
   - `reload_detector()` reinizializza il detector dopo il completamento del download, senza riavviare il server.
3. **Integrazione in `app.py` (nella radice del progetto)**:
   - Endpoint REST:
     - `GET /api/model/status`: stato (`installed`, `active`, `downloading`, `progress`).
     - `GET /api/model/info`: metadati manifest (1,27 GB, MIT, commit immutabile).
     - `POST /api/model/download`: avvio download asincrono.
     - `POST /api/model/cancel`: interruzione e pulizia staging.
4. **Interfaccia (`static/app.js`, `static/index.html`)**:
   - Badge di stato del modello NER e dialogo di download con barra di progresso e indicazione della velocità.
