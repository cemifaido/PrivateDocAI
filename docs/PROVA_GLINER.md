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

## Alternativa manuale: le categorie personalizzate

Le categorie create dall'utente (menu del tasto destro, termini sospetti, «Aggiungi dato») non richiedono nessun modello. Cinque
casi tipici di uno studio, con la categoria che l'utente può creare una volta sola (resta nell'archivio cifrato per tutte le pratiche):

1. **Protocollo interno** (`PROT-2026/004812`) -> `PROTOCOLLO`, codice `[PROTOCOLLO_1]`.
2. **Codice cliente / matricola** (`CLI-98421-X`) -> `CODICE_CLIENTE`.
3. **Nome in codice di un progetto** (`Progetto Titano`) -> `PROGETTO`.
4. **Numero di pratica o fascicolo** (`77/B-2026`) -> `FASCICOLO` (oppure il preset «Numero di protocollo / pratica»).
5. **Commessa o centro di costo** (`COMM-4509-MI`) -> `COMMESSA`.

Il dato scelto riceve lo stesso codice in tutte le occorrenze identiche (a meno di maiuscole e spazi) di tutti i documenti della
pratica, e il ripristino della risposta lo reinserisce.

### Confronto

| Dimensione | GLiNER (`gliner_multi-v2.1`) | Categorie personalizzate |
|:---|:---|:---|
| Memoria e disco | circa 1,8 GB di memoria (picco 2,8 GB) e 1,16 GB di file | nessun costo apprezzabile |
| Tempo | 0,42-0,65 s ogni 120 parole, in più rispetto al modello attuale | immediato |
| Codici di forma insolita | richiamo 0,73-0,80 nella nostra prova | quelli che l'utente indica vengono mascherati tutti |
| Chi decide cosa proteggere | il modello, con errori da controllare | l'utente: se non si accorge di un dato, nessuno lo maschera |
| Dipendenze e licenze | nuova catena da mantenere | nessuna |

**Limite onesto dell'alternativa manuale:** non cerca nulla da sola. Dà la precisione di chi seleziona, ma il richiamo dipende da
quanti dati l'utente nota; inoltre un dato scritto in un'altra forma (per esempio con una cifra diversa) è un'altra stringa e va
indicato a parte. È il motivo per cui la verifica prima dell'invio resta necessaria.

### Conclusione

Il modello attuale per i dati anagrafici più le categorie personalizzate per i dati propri dello studio coprono il caso senza
costi hardware aggiuntivi. L'introduzione di GLiNER allo stato attuale non è giustificata.
