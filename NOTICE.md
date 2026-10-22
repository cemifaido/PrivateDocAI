# Avvisi sulle licenze di terzi

PrivateDoc AI è distribuito con licenza **GNU AGPL-3.0** (vedi `LICENSE`).

Questo file elenca i componenti di terzi che il programma può usare **facoltativamente** e le relative licenze. Le dipendenze Python
(FastAPI, PyMuPDF, EasyOCR, Playwright, ecc.) mantengono le proprie licenze, indicate dai rispettivi pacchetti.

## Modello di riconoscimento (facoltativo, non incluso nel repository né nell'eseguibile)

Il programma può usare, se l'utente lo scarica separatamente, il modello **`rizzoaiacademy/rizzo-pii-0.3B`** (revisione `v1.5.0`):

- Pagina del modello: <https://huggingface.co/rizzoaiacademy/rizzo-pii-0.3B>
- Progetto: <https://github.com/Rizzo-AI-Academy/rizzo-pii>
- Licenza: **MIT** — Copyright (c) 2026 Simone Rizzo — Rizzo AI Academy.
- Impronte SHA-256 attese, **di tutti i file che il programma carica** (il modello non viene usato se anche uno solo è diverso):

  | File | SHA-256 |
  |---|---|
  | `config.json` | `6b9d5bdd4a194d40fb40c53fdc302e225514cd7940d97f657c4082454ee7e91b` |
  | `model.safetensors` | `b1e046e3aec52c3cd74eaf166b034644a4dac0c91128bf06803e1478657fcd9f` |
  | `tokenizer.json` | `a0ab5772a8c5450f45a66c95985d6df2205bf09449ba7ff7bb46de034eaa118a` |
  | `tokenizer_config.json` | `3b66ca84514d9aacf4b90c65a61e561127c6c21d81bbf4e8ba9d46a4c15ac82d` |
  | `special_tokens_map.json` | `6e3204c5a4004719c185007a745d1940471a6fb02521cfa0a00306dbb6bc5903` |

- Il modello è addestrato a partire da **`jhu-clsp/mmBERT-base`** (<https://huggingface.co/jhu-clsp/mmBERT-base>, JHU CLSP;
  riferimento: Marone et al., 2025, *mmBERT: a modern multilingual encoder*). **Licenza dichiarata: MIT** nella scheda del modello e nel README
  del progetto. Non risulta pubblicato un file `LICENSE` separato con un'intestazione di copyright: se ne servirà una versione formale per la
  ridistribuzione, va richiesta agli autori.
- Il progetto di Rizzo indica che i dati di addestramento includono Ai4Privacy (CC-BY-4.0) e DeepMount00: chi ridistribuisce dati o pesi
  deve rispettare le licenze di quei dati.

Il codice di `backend/ner.py` è scritto per questo progetto; la suddivisione del testo in blocchi di 120 parole con 20 di sovrapposizione
segue l'approccio descritto nel progetto di riferimento.

### Testo della licenza MIT

```
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Note sulle licenze dei binari

I programmi eseguibili che includono PyMuPDF (AGPL-3.0 o licenza commerciale) e `extract-msg` (GPL-3.0) vanno distribuiti con il relativo
codice sorgente alle stesse condizioni; per questo il progetto è AGPL-3.0.
