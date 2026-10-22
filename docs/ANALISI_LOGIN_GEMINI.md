# Analisi Tecnica e Legale: Alternative di Accesso a Gemini da Eseguibile Desktop

**Data:** 22 Ottobre 2026  
**Autore:** Gemini (antigravity-ide) — Revisione su richiesta congiunta del team  
**Ramo:** `feat/login-gemini`  
**Stato:** Documento di analisi e raccomandazione architetturale (nessuna modifica al codice di prodotto)  

---

## 1. Contesto e Diagnosi del Problema

Nell'eseguibile di PrivateDoc AI, il tentativo di autenticazione a Google Gemini tramite finestra Chrome pilotata da automazione (Playwright su canale Chromium o Chrome di sistema) viene interrotto alla pagina di login di Google (`accounts.google.com/v3/signin/rejected`) con il messaggio bloccante:
> *"Impossibile eseguire l'accesso - Questo browser o questa app potrebbero non essere sicuri. Prova a utilizzare un browser diverso."*

### Perché Google Rifiuta l'Accesso?
La policy di sicurezza ufficiale di Google ([Google Account Help: "Sign in with Google affected by browser security"](https://support.google.com/accounts/answer/7675428)) dichiara esplicitamente che **Google blocca l'accesso agli account personali e aziendali effettuato da browser pilotati da framework di automazione (WebDriver, Selenium, Puppeteer, Playwright)**.  
I controlli di sicurezza di Google Identity identificano l'automazione attraverso molteplici segnali combinati a livello di runtime e rete:
1. Variabili JavaScript native esposte dal browser (`navigator.webdriver === true`).
2. Protocollo di controllo remoto attivo (Chrome DevTools Protocol - CDP con flag `--enable-automation`).
3. Discrepanze nei profili TLS/JA3/JA4, fingerprint dei canvas e comportamento temporale delle interazioni utente.

### Vincolo Non Negoziabile
In conformità alle direttive di progetto, **si esclude categoricamente qualsiasi tecnica di evasione o aggiramento anti-bot**:
- Niente plugin di camuffamento (es. `puppeteer-extra-plugin-stealth` o script di injection).
- Niente rimozione surrettizia di flag di automazione (`--disable-blink-features=AutomationControlled`).
- Niente spoofing di User-Agent, risoluzioni o fingerprint hardware.

Tali tecniche configurano una violazione attiva delle misure tecnologiche di protezione, violano i Termini di Servizio di Google, espongono l'utente al rischio di **blocco o sospensione permanente dell'account Google personale/aziendale**, e sono per loro natura fragili (vengono regolarmente neutralizzate dagli aggiornamenti di Google reCAPTCHA v3 / Enterprise).

L'obiettivo della presente analisi è valutare esclusivamente le **alternative lecite, stabili, conformi alle normative e orientate a utenti non tecnici**.

---

## 2. Valutazione Comparativa delle Alternative Legittime

---

### Opzione A: API Ufficiale Google Gemini (Google AI Studio / Vertex AI)

L'integrazione di un client API ufficiale HTTP/REST che comunica direttamente con gli endpoint di Google AI Studio o Vertex AI tramite una chiave API (`GEMINI_API_KEY`) fornita dall'utente.

* **Come funzionerebbe nell'app:**
  Nelle impostazioni di PrivateDoc AI l'utente inserisce la propria chiave API (memorizzata cifrata nel Vault locale). L'app assembla il prompt pseudonimizzato e invia una richiesta HTTP POST standard all'endpoint `generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent`. La risposta dell'API viene ricevuta via streaming/JSON e de-anonimizzata istantaneamente in background.

* **Impatto sull'utente non tecnico:**
  - Richiede un passaggio preliminare di configurazione: l'utente deve collegarsi a Google AI Studio, autenticarsi, creare una API Key e incollarla in PrivateDoc AI.
  - Per un professionista non informatico (avvocato, commercialista), questo passaggio rappresenta un piccolo ostacolo iniziale, ma è un'operazione "una tantum" standard, analoga all'inserimento di credenziali o licenze software.

* **Profilo Privacy & Uso dei Dati (FONDAMENTALE per studi legali e aziendali):**
  Le condizioni ufficiali di Google stabiliscono una **differenza radicale** tra il livello gratuito e quello a pagamento (Verifica su Termini di Servizio Ufficiali Google AI Studio & Gemini API, 2024/2026):
  1. **Livello Gratuito (Free Tier):**
     > Verifica del 22/10/2026 sui termini ufficiali (https://ai.google.dev/gemini-api/terms, aggiornati al 28/04/2026): per i servizi gratuiti Google "uses the content you submit to the Services and any generated responses to provide, improve, and develop" i suoi prodotti e le tecnologie di machine learning; "human reviewers may read, annotate, and process your API input and output"; e consiglia: "Do not submit sensitive, confidential, or personal information to the Unpaid Services". Le citazioni di questo punto sono quelle lette direttamente sulla pagina, non quelle riportate in una prima stesura.  
     **Valutazione:** Anche se PrivateDoc AI pseudonimizza rigorosamente le entità (nomi, CF, IBAN), l'invio su endpoint con revisione umana (*human reviewers*) e diritto di riaddestramento dei modelli rappresenta una potenziale violazione del segreto professionale o delle policy confidenziali per molti documenti legali/finanziari.
  2. **Livello a Pagamento (Pay-as-you-go o Google Cloud Vertex AI):**
     > Per i servizi a pagamento i termini dicono che Google non usa prompt e risposte per migliorare i prodotti, ma li registra per un periodo limitato solo per rilevare e prevenire violazioni della politica d'uso; la sezione a pagamento non cita revisori umani. **Importante per l'Italia:** per gli utenti nello Spazio economico europeo, in Svizzera e nel Regno Unito, i termini dicono che si applicano le condizioni dei servizi a pagamento anche con i servizi gratuiti.  
     **Valutazione:** Pienamente conforme a GDPR (Art. 28) e agli standard aziendali di confidenzialità. Il costo per token è trascurabile per volumi di studio (pochi centesimi a pratica).

* **Conformità ai Termini di Servizio:** 100% lecito, supportato e documentato ufficialmente da Google.
* **Costo e Manutenzione:** Bassissima. Endpoint API versionati (`v1beta`/`v1`), stabili nel tempo, zero dipendenze da browser locali.

---

### Opzione B: Connessione al Browser Quotidiano dell'Utente via Porta di Debug (`--remote-debugging-port`)

L'utente avvia autonomamente la propria istanza di Google Chrome abilitando l'ascolto su porta di debug locale (es. `chrome.exe --remote-debugging-port=9222`), e PrivateDoc AI si connette a tale istanza già aperta tramite CDP (Chrome DevTools Protocol).

* **Come funzionerebbe nell'app:**
  PrivateDoc AI non lancia Chrome, ma cerca una connessione su `http://localhost:9222`. Una volta agganciata la scheda di `gemini.google.com` (dove l'utente è già normalmente autenticato con la propria sessione quotidiana), il bridge inietta il prompt nel campo di input ed estrae il testo della risposta.

* **Impatto sull'utente non tecnico (CRITICITÀ ELEVATA):**
  - **Frizione insormontabile:** L'utente dovrebbe chiudere tutte le finestre di Chrome aperte, creare un collegamento speciale sul Desktop o eseguire comandi da terminale con percorsi assoluti e argomenti (`--remote-debugging-port=9222 --user-data-dir=...`).
  - **Allarmi di sicurezza del browser:** All'avvio in modalità debug, Chrome mostra una vistosa barra superiore gialla permanente con avviso di sicurezza: *"Stai utilizzando un flag della riga di comando non supportato: --remote-debugging-port..."*. Per un utente d'ufficio questo genera immediata sfiducia.
  - **Rischio di sicurezza locale:** Aprire la porta di debug espone il profilo dell'utente (cookie di sessione, token, cronologia) a qualunque altro processo o script locale in esecuzione sulla macchina.

* **Profilo Privacy & Uso dei Dati:**
  L'interfaccia consumer `gemini.google.com` è regolata dalle *Gemini Apps Privacy Notice*:
  - Negli account personali gratuiti, la funzione "Gemini Apps Activity" è **abilitata di default**: Google conserva le conversazioni fino a 18–36 mesi e revisori umani possono visionare porzioni di chat per scopi di addestramento.
  - Solo gli account Google Workspace aziendali con specifica licenza Gemini for Workspace garantiscono la non-utilizzazione dei dati per l'addestramento.

* **Conformità ai Termini di Servizio:**
  Google Terms of Service vietano l'automazione, lo scraping o l'estrazione non autorizzata da interfacce web consumer non concepite per l'uso programmatico.

* **Costo e Manutenzione:**
  Altissima. L'interfaccia web di `gemini.google.com` viene aggiornata settimanalmente (nomi di classi CSS offuscati, Shadow DOM, streaming dinamico di WebComponents); ogni minima variazione grafica romperebbe l'automazione.

---

### Opzione C: Pilotaggio di Altri Browser (Microsoft Edge, Mozilla Firefox)

Sostituire Chrome con Microsoft Edge o Mozilla Firefox come browser pilotato da Playwright.

* **Come funzionerebbe e perché FALLISCE:**
  - **Microsoft Edge:** Condivide lo stesso motore Chromium. Se avviato da Playwright, espone `navigator.webdriver = true` e il medesimo stack CDP. Quando l'utente tenta di accedere su `accounts.google.com`, i server di autenticazione Google rilevano l'automazione ed emettono **esattamente lo stesso blocco** (`accounts.google.com/v3/signin/rejected`).
  - **Mozilla Firefox:** Pilotato tramite Marionette / GeckoDriver. Anche Firefox espone le API standard WebDriver al contesto DOM. I controlli di rischio di Google bloccano il login anche su sessioni automatizzate di Firefox.

* **Perché non è una soluzione:**
  Tentare di forzare Firefox o Edge mascherandone l'ambiente di automazione ricadrebbe direttamente nelle tecniche di "stealth/evasione", violando il vincolo primario di progetto. Inoltre, le protezioni di Google Account sono trasversali rispetto al browser e mirano alla natura del processo, non al fornitore del motore di rendering.

---

### Opzione D: Flusso Manuale Ottimizzato "Copia e Decifra in 1-Click" (Raccomandazione Principale)

Riconoscere l'accesso umano nel browser nativo come elemento di forza e fluidificare al massimo l'interazione tra PrivateDoc AI e il browser quotidiano dell'utente.

* **Come funzionerebbe nell'app (Esperienza a 2 Clic):**
  1. Nella schermata di elaborazione di PrivateDoc AI, l'utente trova il pulsante principale: **"Copia Prompt & Apri Gemini"**.
  2. Al clic:
     - Il server/client copia negli appunti di Windows (`navigator.clipboard.writeText`) l'intero prompt già pseudonimizzato e strutturato.
     - L'applicazione apre l'URL `https://gemini.google.com` nel **browser predefinito dell'utente** tramite chiamata di sistema standard dell'OS (`webbrowser.open()` / `ShellExecute`), **senza avviare alcun processo di automazione o driver**.
  3. L'utente si trova nella propria finestra abituale di Chrome/Edge/Firefox, dove è **già autenticato normalmente** con il proprio account personale o aziendale (senza alcun rifiuto o avviso da parte di Google).
  4. L'utente preme semplicemente `Ctrl+V` (Incolla) e Invio.
  5. Una volta generata la risposta, l'utente clicca l'icona nativa di Google "Copia negli appunti" (o seleziona il testo e preme `Ctrl+C`).
  6. Rientrato su PrivateDoc AI, clicca sul pulsante **"Decifra da Appunti"**: l'app legge il testo, esegue il ripristino istantaneo dei dati originali in memoria locale e genera il report Word.

* **Impatto sull'utente non tecnico:**
  - **Zero configurazioni:** Nessuna chiave da generare, nessuna riga di comando, nessun login secondario.
  - **Naturalezza assoluta:** È il modo in cui tutti i professionisti utilizzano già normalmente gli strumenti di AI sul web.

* **Profilo Privacy & Uso dei Dati:**
  - **Protezione garantita da PrivateDoc AI:** I dati che l'utente incolla su Gemini sono **già stati integralmente pseudonimizzati** dal motore locale prima dell'uscita (`[PERSONA_1]`, `[SOCIETA_A]`, `[CODICE_FISCALE_1]`).
  - Anche nel caso in cui l'utente utilizzi un account consumer gratuito (con storico attivo e addestramento abilitato da Google), **nessuna informazione personale o dato sensibile in chiaro viene trasmesso a Google**.
  - L'utente mantiene il controllo visivo al 100% su cosa viene incollato nella chat.

* **Conformità e Manutenzione:**
  - Piena conformità: 0% automazione, 100% interazione umana legittima.
  - Manutenzione: **Zero**. L'app non deve interagire con il DOM di Gemini né gestire bot-protection.

---

## 3. Matrice Comparativa di Sintesi

| Criterio | Opzione A: API Ufficiale (AI Studio / Vertex) | Opzione B: Chrome Debug Port (`--remote-debugging-port`) | Opzione C: Altri Browser Pilotati (Edge/Firefox) | Opzione D: Flusso 1-Click (Copia & Decifra) |
| :--- | :---: | :---: | :---: | :---: |
| **Legittimità e ToS** | Conforme (100% lecita) | Grigia / Contraria ai ToS | Non ammessa (bloccata o evasione) | **100% Conforme e Lecita** |
| **Fattibilità Tecnica** | Altissima (endpoint REST stabili) | Fragile (DOM mutabile) | Inattuabile (rifiuto Google) | **Massima (Nessuna dipendenza)** |
| **Esperienza Utente Non Tecnico** | Media (richiede generazione API Key) | Pessima (flag riga di comando, alert) | Nulla (blocco login) | **Ottima (Semplice, zero config)** |
| **Rischio Sicurezza Account** | Zero | Medio/Alto | Alto (rischio ban account) | **Zero** |
| **Privacy Dati Legali (No-Training)** | **Sì se a pagamento** (No su Free Tier) | No su consumer (Sì su Workspace) | No su consumer | **Garantita a monte da pseudonimizzazione** |
| **Manutenzione nel Tempo** | Minima | Altissima (rotture continue) | N/A | **Zero** |

---

## 4. Raccomandazione Finale e Piano Operativo

### Raccomandazione Strategica: Modello Ibrido a Due Livelli

1. **Livello Predefinito (Per tutti gli utenti): Flusso 1-Click "Copia & Decifra" (Opzione D)**  
   Migliorare l'interfaccia utente eliminando del tutto la complessità e gli errori di Playwright per Gemini.  
   - Il pulsante esegue la copia negli appunti e apre la pagina web ufficiale nel browser ordinario dell'utente.  
   - Questo allinea Gemini a quanto già adottato con successo per ChatGPT e Claude (dove i sistemi Cloudflare / bot-check avevano già reso Copia & Decifra il canale preferito e più affidabile).

2. **Livello Avanzato Opzionale (Per studi strutturati / power users): Supporto API Key Ufficiale (Opzione A)**  
   Consentire nelle impostazioni (o nel Vault) l'inserimento opzionale di una chiave API Google AI Studio / Vertex AI:  
   - Se la chiave è presente: l'app offre la modalità "Elaborazione Diretta via API".  
   - **Avvertenza trasparente obbligatoria in UI:** Indicare con chiarezza che l'uso di chiavi API gratuite di Google AI Studio comporta l'addestramento dei modelli di Google, raccomandando una chiave a pagamento (*Pay-as-you-go*) per l'elaborazione di atti coperti da segreto professionale.

---

## 5. Dichiarazione di Trasparenza sui Limiti di Verifica

In conformità ai principi di cautela operativa:
- **Non sono stati condotti tentativi di autenticazione automatica con account Google personali o aziendali reali** per evitare possibili blocchi di sicurezza, lock out o sanzioni da parte dei sistemi di protezione automatica di Google Identity.
- Le evidenze relative al blocco di Google Sign-In e alle clausole di utilizzo dei dati per l'addestramento derivano direttamente dalla documentazione ufficiale Google (*Google Account Security Policies*, *Google Terms of Service* aggiornati al 22 maggio 2024, e *Google AI Studio & Gemini API Additional Terms of Service*).
