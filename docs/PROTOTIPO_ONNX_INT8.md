# Prototipo ONNX INT8 del modello NER

**Stato:** baseline FP32 eseguito; esportazione e confronto INT8 bloccati da
dipendenze di sviluppo assenti. Nessuna dipendenza installata e nessuna modifica
all'applicazione.

## Esito

È disponibile lo strumento isolato `tools/benchmark_onnx_int8.py`. Usa il modello
locale verificato dall'applicazione, aggiunge casi sintetici per ORG, CAP e carte di
pagamento, misura richiamo per categoria, tempo CPU normalizzato a 120 parole e
working set del processo. Può inoltre esportare FP32 ONNX, applicare quantizzazione
dinamica INT8 ed eseguire lo stesso benchmark tramite ONNX Runtime.

In questa sessione `torch`, `transformers` e `onnxruntime` erano disponibili, mentre
`onnx` e `onnxscript` non lo erano. L'importazione del quantizzatore di ONNX Runtime
richiede a sua volta `onnx`. Come richiesto, non è stato installato nulla: il comando
`--prepare-onnx` termina con un messaggio `BLOCCATO` prima di caricare il modello o
creare artefatti. Di conseguenza **non esiste ancora una misura INT8 confrontabile**.

## Metodo

- backend FP32: `NerDetector` e modello PyTorch usati dall'applicazione;
- corpus: i 3 documenti sintetici di regressione e il relativo `gold.json`;
- integrazione: 9 frasi sintetiche, 3 ciascuna per SOCIETA/ORG, CAP/ZIPCODE e
  CARTA_PAGAMENTO/CREDITCARDNUMBER;
- profilo esteso attivo, necessario perché CAP è intenzionalmente escluso dal
  profilo base;
- confronto model-only, con corrispondenza esatta o per contenimento e categoria
  uguale; non misura la successiva fusione con le regole;
- una fase di warm-up esclusa dal tempo; una misura per documento;
- latenza di ogni documento riportata a 120 parole, poi mediana e p95;
- RAM come working set dell'intero processo. Il delta è misurato dopo il warm-up e
  rappresenta solo la crescita durante le inferenze, non il costo di caricamento.

## Baseline FP32 locale

Misura del 22 ottobre 2026, CPU-only, senza riportare identificativi hardware o
percorsi locali. I numeri prestazionali sono indicativi e non costituiscono un
requisito di prodotto.

| Categoria gold | Richiamo FP32 |
|---|---:|
| CAP, sintetico | 2/3 (66,7%) |
| CARTA_PAGAMENTO, sintetico | 2/3 (66,7%) |
| CATASTO | 1/1 (100%) |
| CODICE_FISCALE | 2/2 (100%) |
| DATA | 6/6 (100%) |
| DOC_IDENTITA | 1/1 (100%) |
| EMAIL | 4/4 (100%) |
| IBAN | 2/2 (100%) |
| IMPORTO | 2/3 (66,7%) |
| INDIRIZZO | 1/1 (100%) |
| PARTITA_IVA | 2/2 (100%) |
| PERSONA | 7/7 (100%) |
| RIFERIMENTO | 2/4 (50%) |
| SOCIETA/ORG, corpus + sintetico | 11/11 (100%) |
| TARGA | 1/1 (100%) |
| TELEFONO | 2/2 (100%) |
| **Totale** | **48/53 (90,6%)** |

| Metrica | FP32 |
|---|---:|
| Tempo mediano / 120 parole | 0,654 s |
| p95 / 120 parole | 1,071 s |
| Working set processo dopo il benchmark | 886,3 MB |
| Crescita working set dopo warm-up | 17,1 MB |

Il campione è piccolo: un singolo errore vale 33 punti nelle categorie sintetiche.
Serve a intercettare regressioni nette e a rendere ripetibile il confronto, non a
stimare la qualità su documenti reali.

## Uso

Baseline FP32, con risultato JSON stampato a video:

```powershell
python tools/benchmark_onnx_int8.py --model-dir <cartella-modello>
```

Esportazione in una cartella temporanea esterna al repository e confronto INT8:

```powershell
python tools/benchmark_onnx_int8.py `
  --model-dir <cartella-modello> `
  --prepare-onnx <cartella-temporanea-onnx> `
  --out <report-locale.json>
```

Con un grafo INT8 già preparato:

```powershell
python tools/benchmark_onnx_int8.py `
  --model-dir <cartella-modello> `
  --onnx-int8 <model.int8.onnx>
```

Il JSON può contenere misure specifiche della macchina e va conservato fuori dal
repository. Anche i grafi ONNX, grandi e derivati dal modello, non vanno committati.

## Gate proposto per decidere l'adozione

Prima di modificare l'applicazione:

1. eseguire FP32 e INT8 in processi separati, con almeno 5 ripetizioni;
2. richiedere nessuna perdita sui casi ORG, CAP e carte e nessuna fuga aggiuntiva
   nel corpus di regressione;
3. ispezionare le differenze candidato per candidato, non soltanto la media;
4. adottare INT8 solo con un guadagno misurabile di latenza o RAM, includendo tempo
   di caricamento e picco del processo reale;
5. verificare licenza, riproducibilità dell'export e hash degli artefatti prima di
   distribuirli.

Finché questi gate non sono completati, il prototipo non giustifica l'aggiunta di
`onnxruntime` o di un nuovo formato modello al prodotto.
