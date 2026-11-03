# 🛡️ PrivateDoc AI

🇮🇹 [Italiano](README.md) · 🇬🇧 English

**Analyse and compare deeds, contracts and emails with a language model without sending the names, codes and amounts the program recognises outside your computer.**

PrivateDoc AI is a local Windows application for people who work with confidential documents (law firms, accountants, consultants). It masks personal data *before* anything is sent, lets the model work on the masked text, and rebuilds the answer locally with the real data. No API keys are required.

> ⚠️ **It reduces the risk, it does not remove it.** This is *pseudonymisation*, not anonymisation: under the GDPR, pseudonymised data is still personal data. Detection is heuristic (rule-based) and **not infallible**: a person must always re-read the text that is about to leave. This is not legal advice. See [Known limitations](#known-limitations).
>
> The user interface and the in-app guide are currently in Italian only, and the detection rules target Italian documents and identifiers (codice fiscale, partita IVA, Italian IBANs, cadastral data, court case numbers).

## How it works

```
documents ──► local reading ──► data detection ──► text with codes ──► model (Gemini / ChatGPT / Claude)
(PDF, Word,    (OCR included)    (names, companies,  [PERSONA_1]            │
 Excel, email,                    tax IDs, IBANs,     [SOCIETA_A]            ▼
 ZIP, folders)                    amounts, dates…)                      answer with the codes
                                                                             │
                       answer with the real data  ◄──── local restoration ◄──┘
```

1. **Load** files, whole folders (subfolders included) or ZIP archives.
2. **Privacy Shield:** every detected item gets a code, *always the same one* across all documents, so the model can compare them without knowing who the parties are. You can correct, remove or add items (also by selecting text and right-clicking).
3. **Pre-send check** on the exact outgoing text: detected data still in clear blocks sending; suspicious words ask for confirmation.
4. **Sending:** with Gemini, ChatGPT and Claude you use "Copy and open" (it copies the anonymous text, opens the site in your normal browser, then you paste the answer back). Google, OpenAI and Anthropic reject automated browsers and the program does not try to get around that check. Optional and off by default: the official Gemini API with your own key (see the in-app guide for the data-handling conditions).
5. **Result** with the real data, exportable to Word. From the protected-data screen you can also create a truly redacted copy of an original PDF.

## Features

- **Formats:** PDF (scanned too, with OCR), Word, ODT, Excel, `.eml`/`.msg` email, text, nested ZIPs, folders.
- **Saved, encrypted cases:** initial password, AES-256-GCM archive; reopen your work after a restart and ask new questions with the same codes.
- **Choice of documents** to include in a request ("compare Document 3 with 7"), with fixed numbering; file names are not sent.
- **Large uploads:** counter of remaining files, interruption (keeping or discarding what was loaded), parallel OCR.
- **Unsupported files** (photos, for example) are listed with name, path and reason instead of being silently ignored.
- **Optional advanced recogniser:** a local model (MIT, CPU) works alongside the rules for names in context, companies, case numbers and cadastral data. If it is missing, the sidebar lets you download it only after explicit consent; every file is verified with SHA-256 before activation. Restoring the answer tolerates codes altered by the model and reports them; IBAN, codice fiscale and VAT number have format validators. See [`NOTICE.md`](NOTICE.md) and sections 12-14 of [`PROGETTO_PRIVATEDOC_AI.md`](PROGETTO_PRIVATEDOC_AI.md) (Italian).
- **Custom categories:** from the protection menu you can search categories with fuzzy matching or create a new one (for example "Protocol number"). The library is shared across cases and stored encrypted in the vault.
- **Real PDF redaction:** select the original PDF again and get a copy with black boxes or codes such as `[PERSONA_1]`. Text and ancillary surfaces are removed from the file, not just covered; the output is reopened and verified before delivery. The original is not added to the case nor kept by the application.
- **In-app guide** (`/guida`, Italian) with usage, limits and legal references.

## Quick start

### With the installer (recommended)

Download `PrivateDocAI-<version>-Setup.exe` from the [Releases](../../releases) page and run it. The setup wizard:

- **asks where to install** the program, and whether to install it for you only or for all users of the PC;
- offers to create a **desktop shortcut** with the shield icon (a Start menu entry is always created);
- can launch the program as soon as it finishes.

The program **opens no black console window**: it starts and the browser opens at `http://127.0.0.1:8765`. On first launch choose the archive password (at least 12 characters) and **write it down: it cannot be recovered**. Right after that, if the local model is not installed yet, the program **prominently offers to download it** (see the advanced recogniser under [Features](#features)); you can also do it later from the sidebar.

**How to quit.** Closing the browser tab does **not** stop the program: it keeps running in the background. In that case a notice appears with two hints:
- to **get back in**, open `http://127.0.0.1:8765` in the browser (or launch the program again from its icon);
- to **switch it off**, open the page and click **"Chiudi programma"** at the bottom of the sidebar (the notice also lets you switch it off right away).

Working data (encrypted cases, browser profiles, the downloaded model) lives in `%LOCALAPPDATA%\PrivateDocAI`, not in the program folder. **Uninstalling does not delete it** unless you confirm: it asks explicitly first.

### With the portable folder (ZIP)

Alternatively, the Release ZIP contains the **entire** `PrivateDocAI` folder: extract it anywhere and run `PrivateDocAI.exe`. Here `data`, `profiles` and `models` are created **next to the `.exe`**: do not distribute a folder that has already been used (`build_exe.bat` checks that it is clean).

#### Unsigned executable (first release)

This is a first release and the installer and the executable are **not yet digitally signed**: Windows does not know the publisher and may show warnings. This does not mean there is a problem with the file. What to do:

1. **If you downloaded a file** (Setup or ZIP), before running it: right-click the file → *Properties* → tick **Unblock** → *OK*. For the ZIP, then extract the **whole** folder.
2. **On first launch** you may see "Windows protected your PC" (SmartScreen): click **More info**, then **Run anyway**. The warning usually appears only once.
3. **If your antivirus blocks or quarantines the file**, this is a common false positive for programs built with PyInstaller: restore it from quarantine and add the folder to the exclusions, or ask your system administrator.
4. **Check that the file is the original** by comparing its SHA-256 hash with the one on the Release page:
   ```powershell
   Get-FileHash .\PrivateDocAI-<version>-Setup.exe -Algorithm SHA256
   ```
   If it does not match, do not run it.

Code signing is planned for later versions.

### Building the installer

`build_exe.bat` builds the executable, checks that the folder is clean and, if [Inno Setup 6](https://jrsoftware.org/isdl.php) is installed, creates the installer in `release\` (script: [`installer/PrivateDocAI.iss`](installer/PrivateDocAI.iss)). The icon is regenerated with `python tools/make_icon.py`.

### From source

```bash
pip install -r requirements.txt
python -m playwright install chromium     # only for automatic sending to Gemini
python run.py
```

Useful variables: `PRIVATEDOC_PORT`, `PRIVATEDOC_DATA_DIR`, `PRIVATEDOC_NO_BROWSER=1`.

## Security

- Everything runs on your computer; the server listens only on `127.0.0.1` and accepts only requests addressed to `localhost`, with a random per-launch token (protection against external websites).
- Cases are encrypted with a key derived from the password (scrypt) and bound to their own identifier; the archive can be locked.
- The *masked* text still leaves for the provider you choose: check its terms of use and your account settings.
- Browser cookies in `profiles/` are **not** encrypted by the program.

## Known limitations

- Detection relies on rules (and, if installed, on an optional local model): unusual names or data written in an odd way may slip through. Facts described in the text can identify people even without names.
- **ChatGPT and Claude cannot be automated:** their sites block automated browsers (and the program does not try to circumvent the checks). Use "Copy & Decrypt".
- OCR runs on the CPU: roughly 6-10 seconds per page; 100 scanned pages take about 10 minutes.
- A case replaced with an older copy of itself is not detected. An external anchor was analysed but is not implemented for now: it would add complexity and the risk of locking the user out without protecting against joint restoration or a local administrator.
- Images embedded in Word files, PDFs with text, or emails are not read.
- PDF redaction needs a reliable text layer: PDFs made only of scans are rejected. Text inside images and non-extractable fonts requires OCR and cannot be guaranteed in this version. If even one requested item remains detectable, the PDF is not delivered.
- The program does not handle the notice to the client, the legal basis, contracts with the AI provider or the impact assessment: these remain the responsibility of the user.

## Legal references

GDPR (art. 4(5), recital 26, arts. 5, 25, 28, 32, 35, 44-49), EDPB Guidelines 01/2025 on pseudonymisation (consultation version), WP29 Opinion 05/2014 (WP216), Italian Legislative Decree 196/2003, art. 28 of the Italian bar's code of conduct and art. 622 of the Italian Criminal Code on professional secrecy, Italian Law 132/2025 (art. 13), Regulation (EU) 2024/1689 (AI Act). Details, links and how each influenced the program are in the in-app guide and in [`PROGETTO_PRIVATEDOC_AI.md`](PROGETTO_PRIVATEDOC_AI.md) (Italian). Always check the texts currently in force.

## Development

```bash
python -m unittest discover -s tests     # unit tests
python test_pipeline.py                  # end-to-end check on a multi-format ZIP
ruff check .
python tools/run_gates.py                # ruff + tests + benchmark on the invented corpus (fails if any item stays readable)
```

Layout: `app.py` (FastAPI API) · `backend/` (extraction, anonymisation, encrypted archive, service, browser bridge) · `static/` (interface and guide) · `tests/` · `PrivateDocAI.spec` and `build_exe.bat` (executable) · `check_dist.py` (pre-distribution check) · `tools/` (benchmarks and automatic checks, invented test corpus).

Full technical documentation (architecture, decisions, security review) is in [`PROGETTO_PRIVATEDOC_AI.md`](PROGETTO_PRIVATEDOC_AI.md) (Italian). The installer is implemented; code signing is deferred because it requires a signing identity, a certificate and SmartScreen reputation management.

## Licence

Copyright © 2026 Signor P.

Distributed under the **GNU AGPL-3.0** (see [`LICENSE`](LICENSE)). This matches the dependencies: PyMuPDF is AGPL-3.0 (or commercial) and `extract-msg` is GPL-3.0. Anyone who distributes the program, or offers it as a network service, must make the corresponding source code available under the same terms. The other dependencies (FastAPI, EasyOCR, Playwright, etc.) keep their own licences.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) (Italian).
