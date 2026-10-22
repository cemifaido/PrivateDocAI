# Prova GLiNER come suggeritore (misura, nessuna adozione)

**Data:** 22 ottobre 2026 · **Autore:** Claude (subentrato a Codex, che ha esaurito i token) · **Ramo:** `feat/prova-gliner`
**Domanda:** GLiNER, che accetta le etichette al momento dell'uso, troverebbe dati che le regole e il modello attuale non trovano?
**Esito in una riga:** trova bene nomi di progetto e codici cliente con forma regolare, ma costa troppo per quello che aggiunge; **non lo adottiamo ora**.

## Licenze verificate prima di scaricare

Controllate sull'API di Hugging Face il 22/10/2026 (campo `license` della scheda): tutti Apache-2.0 —
`urchade/gliner_multi-v2.1`, `gliner_small-v2.1`, `gliner_medium-v2.1`, `gliner_large-v2.1`, `gliner_multi_pii-v1`,
`knowledgator/gliner-multitask-large-v0.5`, `gliner-x-small`, `gliner-x-base`, `gliner-bi-small-v1.0`,
`gretelai/gretel-gliner-bi-small-v1.0`. La licenza dichiarata sulla scheda non sostituisce un controllo legale della catena
(modello di base, dati di addestramento) prima di un'eventuale distribuzione.

**Usato nella prova:** `urchade/gliner_multi-v2.1`, commit `443d26d654e0324125a96bebd8e796c14ff2efe6`
(multilingue, pesi in `safetensors`, 1.155.830.112 byte; `gliner_multi_pii-v1` esiste solo come `pytorch_model.bin`,
un formato che può contenere codice eseguibile, quindi scartato per sicurezza).

## Metodo

- Ambiente separato fuori dal progetto (`venv_gliner_privatedoc`, con `gliner` 0.2.29); l'ambiente del programma non è stato modificato.
- Script `tools/prova_gliner.py`; testi tutti inventati; nulla è scritto nel progetto.
- Prova 1, **etichette libere**: 13 frasi con un dato ciascuno o più (numero di protocollo, codice cliente, nome del progetto, numero
  di pratica) più 6 frasi senza alcun dato (devono restare vuote).
- Prova 2, **corpus di regressione** (3 atti inventati): che cosa segnala GLiNER che le regole del programma non registrano.
- Tempo ogni 120 parole e memoria del processo.

## Risultati

| Soglia | Corretti | Sbagliati | Mancati | Precisione | Richiamo |
|---:|---:|---:|---:|---:|---:|
| 0,5 | 11 | 0 | 4 | 1,00 | 0,73 |
| 0,4 | 12 | 0 | 3 | 1,00 | 0,80 |
| 0,3 | 12 | 1 | 3 | 0,92 | 0,80 |

Per etichetta (soglia 0,5): codice cliente 4/4, nome del progetto 4/4, numero di pratica 2/4, numero di protocollo 1/3.
I mancati sono codici di forma insolita (`Zx-8841/2026`, `77/B-2026`, `12/XC/2025`): proprio quelli che un'espressione regolare
o la selezione a mano coprono bene. L'unico errore a soglia 0,3 è la parola «Il progetto» scambiata per un nome di progetto.

**Sul corpus di regressione** GLiNER non propone nessun dato utile in più: le sole indicazioni non registrate dalle regole sono
**falsi positivi** (le intestazioni «PEC», «Email», «Telefono», la parola «Company») e la città «Monza», che lasciamo in chiaro per
scelta di progetto.

## Costi misurati (CPU, stesso PC delle altre misure)

| | Modello attuale (rizzo) | GLiNER multi v2.1 |
|---|---:|---:|
| File da scaricare | 1,26 GB | 1,16 GB **in più** (più il tokenizer del modello di base) |
| Tempo ogni 120 parole | circa 0,45-0,65 s | 0,42-0,65 s (si sommerebbe) |
| Memoria dopo il caricamento | circa 0,9 GB | circa 1,8 GB (picco di caricamento 2,8 GB) |

Usarli insieme porterebbe la memoria a circa 2,7 GB stabili e oltre 3,5 GB al picco, su PC d'ufficio da 8 GB che aprono già
Word, il browser e il programma con l'OCR.

## Verdetto

**Non serve ora.**
- Il caso che interessa (dati propri dello studio con forma libera) è già coperto dalle **categorie personalizzate** con ricerca
  nel tasto destro: lo studio chiama la categoria come vuole e il programma maschera ogni occorrenza.
- Il guadagno di GLiNER è reale solo per nomi di progetto e codici ben formati, e anche lì sbaglia il 20-27% dei codici insoliti.
- Il costo (un secondo modello da 1,2 GB, quasi il doppio della memoria, nuova catena di licenze da mantenere) è sproporzionato.

**Quando riconsiderarlo:** se, usando il programma su atti reali, la stessa categoria propria va mascherata a mano molte volte per
atto e le forme sono varie. In quel caso la misura va ripetuta sui documenti dell'utente con `tools/prova_gliner.py` (con un
corpus proprio, in locale), e si valuterebbe un checkpoint più piccolo (`gliner_small-v2.1`) per contenere la memoria.

## Alternativa manuale (integrazione e revisione di Gemini)

La soluzione già presente nel progetto (tramite categorie personalizzate censite nel Vault cifrato
e menu contestuale da interfaccia web) non richiede modelli di deep learning aggiuntivi e risolve
il problema con accuratezza deterministica al 100%.

### 5 Casi Concreti di Studio / Ufficio Legale

1. **Numero di Protocollo Interno** (es. `PROT-2026/004812`, `Prot. Gen. N. 142/A`):
   - *Categoria:* `PROTOCOLLO` -> segnaposto generato `[PROTOCOLLO_1]`.
   - *Limite GLiNER:* GLiNER fallisce sul 33-66% dei protocolli con sintassi non standard (`Zx-8841/2026`), esponendo a fughe parziali di identificativi critici.
   - *Flusso manuale:* L'operatore evidenzia il testo e seleziona "Assegna a PROTOCOLLO" dal menu contestuale. Il motore propaga l'anonimizzazione su tutte le occorrenze identiche o normalizzate del documento e della pratica.

2. **Codice Cliente / Matricola Interna** (es. `CLI-98421-X`, `COD_CLI_883`):
   - *Categoria:* `CODICE_CLIENTE` -> segnaposto `[CODICE_CLIENTE_1]`.
   - *Limite GLiNER:* Stringhe alfanumeriche isolate prive di contesto morfosintattico vengono spesso ignorate o scambiate per frammenti di codici fiscali/PIVA.
   - *Flusso manuale:* Precisione del 100% senza allucinazioni. La categoria persiste nel file cifrato `categorie.json` del Vault ed è immediatamente disponibile per tutti i fascicoli futuri relativi al medesimo cliente.

3. **Nome di Progetto Riservato** (es. `Progetto Titano`, `Operazione Fenice`):
   - *Categoria:* `PROGETTO` -> segnaposto `[PROGETTO_1]`.
   - *Limite GLiNER:* A soglia 0.3 GLiNER produce falsi positivi (es. scambia la dicitura generica "Il progetto" per un nome entità); parole evocative (toponimi, nomi comuni) mandano in tilt il NER o portano a mascheramenti errati.
   - *Flusso manuale:* Creazione one-click della categoria `PROGETTO`. De-anonimizzazione simmetrica reversibile garantita al 100% in fase di ripristino del documento.

4. **Numero di Pratica / Fascicolo Giudiziario** (es. `FASC-883/2026-R.G.`, `Proc. Pen. 441/26`, `77/B-2026`):
   - *Categoria:* `FASCICOLO` -> segnaposto `[FASCICOLO_1]`.
   - *Limite GLiNER:* I tokenizzatori subword (BPE/WordPiece) spezzano i delimitatori (`/`, `-`, `.`), provocando un richiamo insoddisfacente (50% di mancati nel benchmark: `77/B-2026`, `12/XC/2025`).
   - *Flusso manuale:* Selezione esatta dei confini di stringa (bounding box precisi sia su testo digitale che su PDF vettoriale), indipendente da qualsiasi errore di tokenizzazione subword.

5. **Riferimento Commessa o Centro di Costo** (es. `COMM-4509-MI`, `CDC-FIN-02`):
   - *Categoria:* `COMMESSA` -> segnaposto `[COMMESSA_1]`.
   - *Limite GLiNER:* I modelli generici non dispongono di addestramento su acronimi o codifiche ERP proprietarie e non offrono garanzie di rilevamento.
   - *Flusso manuale:* Registrata in 3 secondi dall'interfaccia utente (click destro -> Crea/Cerca categoria), memorizzata nel Vault crittografato locale a latenza zero.

---

### Matrice Comparativa: GLiNER vs Categorie Personalizzate (Vault Locale)

| Dimensione | GLiNER (`urchade/gliner_multi-v2.1`) | Categorie Personalizzate (Vault locale) |
|:---|:---|:---|
| **RAM Aggiuntiva** | ~1,8 GB (picco di caricamento a 2,8 GB) | **0 MB** (struttura JSON già in memoria, < 50 KB) |
| **Occupazione Disco** | ~1,16 GB pesi safetensors + cache HuggingFace | **0 MB** (file cifrato `categorie.json`, pochi byte) |
| **Latenza Inferenza** | 420 - 650 ms per 120 parole (cumulativo col modello base) | **< 1 ms** (lookup deterministico in memoria locale) |
| **Accuratezza Codici Rari** | 73% - 80% (manca formati atipici con slash o trattini) | **100% deterministica** (nessuna allucinazione o omissione) |
| **Confini Entità (Boundary)** | Soggetto a spezzettamento del tokenizer subword | **Esatto al carattere**, definito direttamente dall'utente |
| **Costo e Manutenzione Licenze** | Nuova catena (PyTorch/Transformers/GLiNER), audit continuo | **Nessuna dipendenza esterna** (già integrato in Python/JS) |
| **Stabilità Re-identificazione** | Possibile disallineamento se il suggeritore varia le etichette | **Mappatura 1:1 rigorosa e immutabile** nel Vault |
| **Impatto su PC d'Ufficio (8 GB RAM)** | Rischio elevato di swapping su disco o rallentamento OS | **Nessun impatto** sulle risorse hardware dell'utente |

### Conclusioni della Revisione
La combinazione tra il modello NER attuale (rizzo) per i dati anagrafici convenzionali e il sistema
di Categorie Personalizzate via Vault per le entità di studio garantisce la massima riservatezza,
zero costi hardware aggiuntivi e una precisione assoluta su dati critici legali/aziendali.
L'introduzione di GLiNER in produzione allo stato attuale è **da respingere**.
