# Architettura e Disegno: Download Manager del Modello NER Locale

**Data**: 22 Ottobre 2026  
**Autore**: Gemini (`feat/analisi-prestazioni`)  
**Riferimento Piano**: Milestone 2/3 - Fase 1, Compito (b)  
**Destinatari**: Team PrivateDoc AI (Claude, Codex, Gemini, Operatore Umano)

---

## 1. Principi Guida e Obiettivi

PrivateDoc AI è un'applicazione desktop per professionisti (avvocati, commercialisti, periti, uffici legali) concepita attorno al principio cardine della **sovranità e riservatezza del dato**.

Il modello di Machine Learning opzionale (`rizzoaiacademy/rizzo-pii-0.3B`, basato su `mmBERT`, licenza MIT) migliora il riconoscimento dei dati personali nel contesto del discorso, ma:
1. **Nessun automatismo silente**: Il download non deve **mai** avviarsi in background senza che l'utente abbia fatto un'azione esplicita e consapevole.
2. **Consenso informato e trasparenza**: Prima dell'avvio, l'interfaccia deve indicare con chiarezza:
   - Dimensione esatta del pacchetto (~600 MB su disco).
   - Licenza d'uso aperta (MIT).
   - Fonte ufficiale (Hugging Face Repository al commit verificato).
   - Garanzia di esecuzione locale sulla CPU: nessun testo verrà mai inviato su server remoti.
3. **Integrità crittografica a prova di manomissione**: Ogni file scaricato viene validato contro un hash **SHA-256 pinnato nel codice**. Se un solo byte non corrisponde, l'intero pacchetto viene rifiutato.
4. **Resilienza alle reti aziendali**: Supporto pieno a proxy HTTP/HTTPS d'impresa e certificati TLS aziendali.
5. **Funzionamento offline / Air-gapped**: Possibilità per amministratori IT di depositare i file manualmente in cartella, mantenendo la postazione totalmente priva di accesso a Internet.

---

## 2. Puntamento Immutabile e Manifest del Modello

### 2.1 Commit SHA Immutabile (Anti-Poisoning)
I repository di modelli su Hugging Face possono aggiornare i branch (incluso `main` o i tag mobili). Per garantire riproducibilità assoluta e impedire attacchi di supply chain (sostituzione di pesi o codice serializzato), il download deve puntare **esclusivamente al commit hash Git immutabile**:

* **Repository**: `rizzoaiacademy/rizzo-pii-0.3B`
* **Release**: `v1.5.0`
* **Commit SHA Hugging Face**: `701dd9a4ef7ecf01f705d9c22dcfc723f03b22fb` (pinnato nel manifest)
* **Base URL**: `https://huggingface.co/rizzoaiacademy/rizzo-pii-0.3B/resolve/701dd9a4ef7ecf01f705d9c22dcfc723f03b22fb/`

### 2.2 Struttura del Manifest Pinnato
Il manifest viene incorporato staticamente nel backend in forma di costanti immutabili:

```python
MODEL_MANIFEST = {
    "name": "rizzo-pii-0.3B",
    "version": "1.5.0",
    "license": "MIT",
    "description": "Modello compatto di Named Entity Recognition per PII italiane su CPU (basato su mmBERT)",
    "repository": "rizzoaiacademy/rizzo-pii-0.3B",
    "commit_sha": "701dd9a4ef7ecf01f705d9c22dcfc723f03b22fb",
    "base_url": "https://huggingface.co/rizzoaiacademy/rizzo-pii-0.3B/resolve/701dd9a4ef7ecf01f705d9c22dcfc723f03b22fb/",
    "total_size_bytes": 628_500_000,  # ~600 MB
    "files": {
        "config.json": {
            "size": 1_280,
            "sha256": "6b9d5bdd4a194d40fb40c53fdc302e225514cd7940d97f657c4082454ee7e91b"
        },
        "model.safetensors": {
            "size": 625_100_000,
            "sha256": "b1e046e3aec52c3cd74eaf166b034644a4dac0c91128bf06803e1478657fcd9f"
        },
        "tokenizer.json": {
            "size": 2_150_000,
            "sha256": "a0ab5772a8c5450f45a66c95985d6df2205bf09449ba7ff7bb46de034eaa118a"
        },
        "tokenizer_config.json": {
            "size": 1_450,
            "sha256": "3b66ca84514d9aacf4b90c65a61e561127c6c21d81bbf4e8ba9d46a4c15ac82d"
        },
        "special_tokens_map.json": {
            "size": 650,
            "sha256": "6e3204c5a4004719c185007a745d1940471a6fb02521cfa0a00306dbb6bc5903"
        }
    }
}
```

---

## 3. Flusso Utente e Richiesta di Consenso

```mermaid
sequenceDiagram
    autonumber
    actor Utente
    participant UI as Frontend (Web/Electron)
    participant API as Backend FastAPI (app.py)
    participant DM as ModelDownloader
    participant HF as Hugging Face CDN

    Utente->>UI: Clicca su "Attiva modello linguistico NER"
    UI->>API: GET /api/model/info
    API-->>UI: Info manifest (600 MB, licenza MIT, commit pinnato)
    UI->>Utente: Modale di conferma: Consenso, dimensione (600MB), licenza MIT
    Utente->>UI: Conferma: [Avvia Download]
    UI->>API: POST /api/model/download
    API->>DM: Avvia thread in background
    API-->>UI: 202 Accepted (Stato: DOWNLOADING)
    loop Ogni 500ms
        DM->>HF: Streaming chunk a blocchi con calcolo SHA-256 progressivo
        UI->>API: GET /api/model/progress
        API-->>UI: {percent: 45%, downloaded_bytes: 280MB, speed_kb_s: 4200}
        UI->>Utente: Aggiorna barra di avanzamento e pulsante [Annulla]
    end
    DM->>DM: Verifica SHA-256 di tutti i 5 file
    DM->>DM: Spostamento atomico da staging a models/
    DM-->>API: Modello pronto (Stato: ACTIVE)
    UI->>Utente: Notifica verde: "Modello linguistico attivo e verificato"
```

### Dettagli del Modale di Consenso nell'Interfaccia
Il modale deve presentare:
- **Titolo**: *Attivazione Modello Linguistico Locale (NER)*
- **Descrizione**: *"PrivateDoc AI funziona al 100% con le sole regole integrate. Se desideri potenziare la rilevazione di nomi propri ed enti nel contesto delle frasi, puoi scaricare il modello locale ottimizzato per lingua italiana."*
- **Specifiche**:
  - **Dimensione download**: ~600 MB
  - **Licenza**: Open Source MIT (commerciale e privato)
  - **Esecuzione**: **Esclusivamente locale su CPU** (nessun dato o documento uscirà dal tuo computer)
  - **Connettività necessaria**: Solo per questo scaricamento iniziale; al termine la rete viene completamente disattivata.
- **Pulsanti**: `[Annulla]` / `[Scarica e Attiva (~600 MB)]`

---

## 4. Strategia di Download: Atomicità e Gestione Errori

1. **Staging Directory e Transazionalità**:
   - I file non vengono mai scritti direttamente nella cartella operativa del modello (`data/models/rizzo-pii-0.3B/`).
   - I file vengono scaricati in una cartella di staging temporanea: `data/models/.staging_rizzo_pii/` con estensione temporanea `.part`.
   - L'hash SHA-256 viene calcolato a blocchi in memoria durante lo streaming (`hashlib.sha256().update(chunk)`), senza dover rileggere il file da disco una volta terminato.
   - Solo se tutti i 5 file completano il download e **tutti e 5 gli SHA-256 coincidono esattamente**, la cartella `.staging_rizzo_pii/` viene rinominata atomicamente in `rizzo-pii-0.3B/` (`os.replace`).
2. **Annullamento da parte dell'utente**:
   - L'utente può cliccare `[Annulla Download]` in qualsiasi momento.
   - Il thread di download intercetta il segnale di `threading.Event`, interrompe la connessione HTTP ed elimina immediatamente i file parziali `.part`.
3. **Resilienza alle interruzioni di rete**:
   - Supporto all'header `Range: bytes=X-` per consentire la ripresa del file `model.safetensors` in caso di momentanea caduta di connessione, evitando di riscaricare 600 MB da capo.

---

## 5. Supporto per Ambienti Aziendali e Proxy

Negli uffici legali, nelle banche e nelle pubbliche amministrazioni, l'accesso a internet avviene frequentemente tramite proxy o gateway con ispezione SSL (Zscaler, BlueCoat, Fortinet).

Il downloader supporta nativamente le seguenti configurazioni:

1. **Rilevamento Proxy di Sistema**:
   - Utilizzo di `urllib.request.getproxies()` e lettura automatica delle variabili d'ambiente di sistema:
     - `HTTP_PROXY` / `http_proxy`
     - `HTTPS_PROXY` / `https_proxy`
     - `ALL_PROXY`
     - `NO_PROXY` / `no_proxy` (es. bypass per `localhost`, `127.0.0.1`)
2. **Autenticazione Proxy**:
   - Supporto a URL proxy con credenziali embedded (es. `http://user:password@proxy.azienda.lan:8080`).
3. **Certificati CA Custom (Enterprise TLS Interception)**:
   - Se l'azienda applica un proxy con decifratura TLS e certificato root proprietario, il downloader deve rispettare:
     - `REQUESTS_CA_BUNDLE`
     - `SSL_CERT_FILE`
     - `CURL_CA_BUNDLE`
   - Se una di queste variabili è impostata, viene passata al contesto SSL (`ssl.create_default_context(cafile=...)`), impedendo il fallimento per `CERTIFICATE_VERIFY_FAILED`.

---

## 6. Procedura di Fallback Manuale (Installazione Offline / Air-Gapped)

Per computer operanti in regime di isolamento totale (senza accesso internet):

1. **Percorso di installazione**:
   L'utente o l'amministratore crea la cartella:
   `data/models/rizzo-pii-0.3B/`  
   (oppure il percorso puntato dalla variabile d'ambiente `PRIVATEDOC_MODEL_DIR`).
2. **File richiesti da depositare**:
   - `config.json`
   - `model.safetensors`
   - `tokenizer.json`
   - `tokenizer_config.json`
   - `special_tokens_map.json`
3. **Verifica immediata**:
   Al successivo avvio di PrivateDoc AI (o cliccando sul pulsante dell'interfaccia *"Verifica file locali"*), il backend esegue la consueta verifica SHA-256 e attiva il modello all'istante, **senza effettuare alcun tentativo di connessione di rete**.
4. **Tool CLI per sistemisti**:
   Fornire lo script di verifica rapido:
   ```powershell
   python tools/verify_model.py "data/models/rizzo-pii-0.3B"
   ```

---

## 7. Mappatura Puntuale delle Modifiche al Codice Esistente

> [!NOTE]
> In conformità con la divisione dei ruoli per la Milestone 2/3, questo documento definisce la specifica progettuale. I file sotto la titolarità di Claude (`backend/app.py`, `backend/ner.py`, `static/`) **non vengono modificati in questa fase** e saranno implementati da Claude nella Fase 2.

### 7.1 Nuovo Modulo: `backend/model_downloader.py`
Un modulo dedicato e isolato (zero impatto sulle regole offline di `ner.py`):
- Classe `ModelDownloader`:
  - `start_download(on_progress: Callable, on_complete: Callable, on_error: Callable)`
  - `cancel()`
  - `get_status() -> Dict[str, Any]`
  - Funzione `download_file_with_resume(url, dest_path, expected_sha, expected_size, ...)`
  - Funzione `get_system_proxies_and_ssl_context()`

### 7.2 Impatti su `backend/ner.py` (Titolarità: Claude)
Attualmente `ner.py` imposta a livello di modulo:
```python
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
```
* **Cosa cambia**:
  - Queste variabili di isolamento **devono rimanere intatte**: impediscono a Transformers e Hugging Face Hub di fare chiamate di telemetria o download automatici non controllati.
  - Il download viene effettuato da `model_downloader.py` tramite semplici richieste HTTPS native (o libreria `httpx`/`urllib`), senza passare dal client di Hugging Face.
  - Aggiunta di un metodo per invalidare la cache di `_get_detector()` quando il download è completato con successo:
    ```python
    def reload_detector():
        global _DETECTOR, _DETECTOR_LOCK
        with _DETECTOR_LOCK:
            _DETECTOR = None  # costringe il ri-controllo all'invocazione successiva
    ```

### 7.3 Impatti su `backend/app.py` (Titolarità: Claude)
Aggiunta di 4 endpoint REST leggeri:
1. `GET /api/model/status`:
   - Ritorna: `{"installed": bool, "active": bool, "downloading": bool, "progress": float, "error": Optional[str]}`.
2. `GET /api/model/info`:
   - Ritorna il manifest: dimensione (~600 MB), licenza, fonte, descrizione.
3. `POST /api/model/download`:
   - Avvia il thread di scaricamento in background. Ritorna `202 Accepted`.
4. `POST /api/model/cancel`:
   - Interrompe il download e ripulisce lo staging.
5. `GET /api/model/stream-progress` (opzionale):
   - Server-Sent Events (SSE) per aggiornare la barra di progresso in tempo reale a 60 fps, in alternativa a un semplice polling ogni 500 ms.

### 7.4 Impatti su `static/app.js` e `static/index.html` (Titolarità: Claude)
1. **Header / Barra di stato**:
   - Badge cliccabile:
     - ⚪ *Modello NER: Non installato (usa solo regole)*
     - 🟡 *Modello NER: Download in corso (45%)*
     - 🟢 *Modello NER: Attivo e verificato*
2. **Modale di download**:
   - Rendering con testo informativo, calcolo velocità e tempo stimato rimanente.
3. **Pannello Impostazioni / Privacy**:
   - Possibilità di disattivare il modello anche se presente (per operare in modalità puramente deterministica a regole).
   - Indicazione della cartella offline dove copiare i file per uso air-gapped.

---

## 8. Riepilogo Rischi e Mitigazioni

| Rischio | Impatto | Mitigazione Progettuale |
|:---|:---|:---|
| Download interrotto o corrotto | Modello inservibile o crash all'avvio | Download in staging `.part`, verifica SHA-256 e spostamento atomico finale |
| Rete aziendale con proxy autenticato | Errore 407 Proxy Auth Required | Rilevamento automatico variabili d'ambiente proxy e credenziali |
| Ispezione SSL aziendale (Zscaler/Fortinet) | `CERTIFICATE_VERIFY_FAILED` | Supporto variabile `REQUESTS_CA_BUNDLE` e `SSL_CERT_FILE` |
| Rete lenta o caduta a metà dei 600 MB | Perdita del progresso scaricato | Supporto header HTTP `Range` per ripresa dal byte interrotto |
| Utente non desidera il download | Consumo di banda non autorizzato | **Consenso obbligatorio esplicito**: zero download senza click |
| Modello manomesso sulla sorgente remota | Fallimento integrità o supply-chain attack | Puntamento al **commit SHA immutabile** e verifica SHA-256 su tutti i file |
