# Prototipo ONNX INT8 del modello NER

**Stato:** export e confronto completati in ambiente isolato; INT8 non adottabile
perché peggiora il richiamo di una categoria rara. Nessuna modifica all'applicazione
o alle dipendenze principali.

## Esito

Lo strumento `tools/benchmark_onnx_int8.py` usa il modello locale verificato
dall'applicazione, aggiunge casi sintetici per ORG, CAP e carte di pagamento e
misura richiamo per categoria, tempo CPU normalizzato a 120 parole e working set.
Può esportare un grafo FP32 ONNX e applicare quantizzazione dinamica INT8.

Il grafo ONNX FP32 ha riprodotto esattamente il richiamo PyTorch in tutte le
categorie. La quantizzazione dinamica QInt8 per-tensor è più veloce e compatta, ma
ha perso una carta di pagamento che FP32 riconosceva. Il criterio deciso prima della
misura era vincolante: **nessuna perdita su ORG, CAP, carte e persone**. Pertanto
**INT8 è respinto per il prodotto nello stato attuale**.

Il richiamo totale non basta a decidere: FP32 e INT8 ottengono entrambi 48/53 perché
INT8 perde una carta ma trova un riferimento in più. Solo la tabella per classe
rende visibile la regressione privacy-rilevante.

## Ambiente e artefatti

La prova è stata eseguita in un venv separato fuori dal repository e dalle worktree.
L'ambiente principale non è stato modificato. Il venv ha riusato Torch,
Transformers e ONNX Runtime già presenti e ha installato `onnx` e `onnxscript`.
Grafi e report JSON locali sono rimasti in una cartella temporanea esterna al
repository.

Versioni usate: Python 3.14, Torch 2.10.0 CPU, Transformers 5.14.1, ONNX 1.23.2,
ONNX Runtime 1.26.0 e ONNX Script 0.7.2. Non sono riportati identificativi hardware
o percorsi locali.

Il nuovo exporter Dynamo produceva un grafo con assi dichiarati dinamici ma con un
vincolo interno di ModernBERT legato alla lunghezza d'esempio; ONNX Runtime falliva
su sequenze diverse con un errore di broadcast. Il prototipo usa quindi l'exporter
TorchScript legacy, che in questa prova ha conservato correttamente gli assi
dinamici. Il benchmark ora tratta qualsiasi errore del detector come fallimento,
invece di scambiarlo per un risultato con richiamo zero.

| Artefatto temporaneo | Dimensione |
|---|---:|
| Grafo ONNX FP32 | 1.230.861.095 byte |
| Grafo + dati QInt8 per-tensor | 308.611.743 byte |
| Riduzione su disco | 74,9% |

## Metodo

- corpus: 3 documenti sintetici di regressione con il relativo `gold.json`;
- integrazione: 9 frasi sintetiche, 3 ciascuna per SOCIETA/ORG, CAP/ZIPCODE e
  CARTA_PAGAMENTO/CREDITCARDNUMBER;
- profilo esteso attivo, necessario perché CAP è intenzionalmente escluso dal
  profilo base;
- confronto model-only, con corrispondenza esatta o per contenimento e categoria
  uguale; non misura la successiva fusione con le regole;
- warm-up escluso; 5 ripetizioni per documento;
- latenza del documento riportata a 120 parole; tabella con mediana e p95;
- backend FP32 e INT8 eseguiti in processi separati, necessario per confrontare RAM;
- RAM come working set dell'intero processo: valore finale, picco di processo,
  incremento al caricamento e incremento durante le inferenze.

Il campione è piccolo: un singolo errore vale 33 punti nelle categorie sintetiche.
Serve a intercettare regressioni nette e non stima la qualità su documenti reali.

## Richiamo per categoria

Misura CPU-only del 22 ottobre 2026:

| Categoria gold | FP32 | QInt8 per-tensor |
|---|---:|---:|
| CAP, sintetico | 2/3 (66,7%) | 2/3 (66,7%) |
| CARTA_PAGAMENTO, sintetico | **2/3 (66,7%)** | **1/3 (33,3%)** |
| CATASTO | 1/1 | 1/1 |
| CODICE_FISCALE | 2/2 | 2/2 |
| DATA | 6/6 | 6/6 |
| DOC_IDENTITA | 1/1 | 1/1 |
| EMAIL | 4/4 | 4/4 |
| IBAN | 2/2 | 2/2 |
| IMPORTO | 2/3 | 2/3 |
| INDIRIZZO | 1/1 | 1/1 |
| PARTITA_IVA | 2/2 | 2/2 |
| PERSONA | 7/7 | 7/7 |
| RIFERIMENTO | 2/4 | 3/4 |
| SOCIETA/ORG, corpus + sintetico | 11/11 | 11/11 |
| TARGA | 1/1 | 1/1 |
| TELEFONO | 2/2 | 2/2 |
| **Totale** | **48/53 (90,6%)** | **48/53 (90,6%)** |

La carta persa è il numero sintetico Amex a 15 cifre: il punteggio FP32 era appena
sopra la soglia 0,85 e dopo quantizzazione è sceso sotto soglia. Abbassare la soglia
solo per recuperare il test cambierebbe il comportamento del prodotto e non è una
correzione accettabile senza misurare i falsi positivi.

La quantizzazione QInt8 per-channel è stata provata e scartata ancora prima: ha
degradato quasi completamente il modello (solo 1/53 elementi gold trovato). Il tool
usa perciò per-tensor, la variante meno distruttiva fra quelle misurate.

## Tempo e memoria

| Metrica | FP32 PyTorch | QInt8 ONNX | Delta INT8 |
|---|---:|---:|---:|
| Tempo mediano / 120 parole | 0,937 s | 0,293 s | -68,8% (3,2× più veloce) |
| p95 / 120 parole | 1,671 s | 0,482 s | -71,1% |
| Working set finale | 880,1 MB | 587,0 MB | -293,1 MB (-33,3%) |
| Picco working set | 905,3 MB | 744,7 MB | -160,6 MB (-17,7%) |
| Incremento al caricamento | 846,9 MB | 506,0 MB | -340,9 MB (-40,3%) |
| Incremento durante le inferenze | 9,7 MB | 57,3 MB | +47,6 MB |

I numeri prestazionali sono indicativi e specifici della sessione di misura; non
costituiscono un requisito di prodotto.

## Uso

Export e quantizzazione in una cartella temporanea esterna:

```powershell
python tools/benchmark_onnx_int8.py `
  --model-dir <cartella-modello> `
  --prepare-onnx <cartella-temporanea-onnx> `
  --repeats 5 `
  --out <report-locale.json>
```

Per numeri RAM confrontabili, eseguire i backend in processi separati:

```powershell
python tools/benchmark_onnx_int8.py `
  --model-dir <cartella-modello> --backend fp32 --repeats 5

python tools/benchmark_onnx_int8.py `
  --model-dir <cartella-modello> --backend int8 `
  --onnx-int8 <model.int8.onnx> --repeats 5
```

Il JSON contiene misure specifiche della macchina e va conservato fuori dal
repository. Anche i grafi ONNX, grandi e derivati dal modello, non vanno committati.

## Decisione e sviluppi futuri

Non aggiungere oggi ONNX Runtime o il formato INT8 al prodotto. Un nuovo tentativo
ha senso soltanto con almeno una delle seguenti strategie, sempre contro un corpus
più ampio:

1. quantizzazione statica con calibrazione rappresentativa;
2. quantizzazione selettiva che lasci FP32 i layer sensibili;
3. quantization-aware training del checkpoint;
4. un checkpoint già pubblicato e validato dall'autore per INT8.

Il gate resta: nessuna perdita sulle categorie rare, ispezione candidato per
candidato e nessuna fuga aggiuntiva nella fusione finale con le regole. I vantaggi
di velocità, RAM e disco non compensano una regressione di richiamo sui dati da
proteggere. Quando entrambi i backend sono eseguiti nello stesso comando, lo
strumento registra `int8_adoption_gate` nel JSON ed esce con codice 3 se una delle
quattro categorie vincolanti regredisce.
