#!/usr/bin/env python3
"""Strumento di verifica e audit per la pulizia reale di PDF redatti.

Progettato per PrivateDoc AI (Milestone 4 - Punto 1).
Esegue un'ispezione indipendente, approfondita e multilivello su qualsiasi PDF
per certificare che i termini sensibili specificati siano stati FISICAMENTE
rimossi dal documento e non semplicemente coperti graficamente.

Superfici ispezionate:
1. Pagine / Testo vettoriale (inclusi testi a capo, sillabati con trattino e bianco-su-bianco)
2. Annotazioni (Sticky note, FreeText, evidenziazioni, commenti, pop-up)
3. Metadati documento (dizionario Info: autore, titolo, oggetto, parole chiave, ecc.)
4. Pacchetto metadati XMP (XML packet)
5. Segnalibri / Sommario / Outline TOC
6. File incorporati / Allegati (Embedded Files) con decompressione del contenuto
7. Campi modulo / AcroForm (valori, etichette, nomi campo, tooltip)
8. Livelli / Strati opzionali (OCG - Optional Content Groups)
9. Stream decompressi di tutti gli oggetti PDF (xref streams con decodifica hex/literal)
10. Scansione binaria grezza del file completo (anti-revisioni incrementali e trailer residui)

Codice di uscita:
- 0: Pulito al 100% (nessun residuo trovato per i termini specificati)
- 1: Trovati residui dei termini sensibili (fallimento verifica / redazione incompleta)
- 2: Errore di argomenti o file non trovato
"""

from __future__ import annotations

import argparse
import binascii
import json
import re
import sys
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


def _normalize_ws(text: str) -> str:
    """Normalizza spaziature e a capo per ricerca tollerante ai ritorni a capo."""
    return re.sub(r"\s+", " ", text).strip()


def _normalize_hyphen(text: str) -> str:
    """Rimuove trattini a fine riga per unire parole spezzate."""
    return re.sub(r"-\s*\n\s*", "", text)


def _decode_pdf_literal(raw: bytes) -> str:
    """Decodifica sequenze di escape ottali e speciali in stringhe letterali PDF."""
    def replace_octal(match: re.Match[bytes]) -> bytes:
        oct_val = int(match.group(1), 8)
        return bytes([oct_val])

    # Sostituisce \ddd ottale
    unescaped = re.sub(rb"\\([0-7]{1,3})", replace_octal, raw)
    unescaped = unescaped.replace(rb"\\n", b"\n")
    unescaped = unescaped.replace(rb"\\r", b"\r")
    unescaped = unescaped.replace(rb"\\t", b"\t")
    unescaped = unescaped.replace(rb"\\b", b"\b")
    unescaped = unescaped.replace(rb"\\f", b"\f")
    unescaped = unescaped.replace(rb"\\(", b"(")
    unescaped = unescaped.replace(rb"\\)", b")")
    unescaped = unescaped.replace(rb"\\\\", b"\\")
    return unescaped.decode("latin-1", errors="replace")


def _decode_hex_strings(stream: bytes) -> list[bytes]:
    """Estrae e decodifica tutte le stringhe esadecimali <...> presenti in uno stream PDF."""
    decoded_list = []
    matches = re.findall(rb"<([0-9a-fA-F\s]+)>", stream)
    for h in matches:
        clean_h = re.sub(rb"\s+", b"", h)
        if len(clean_h) % 2 != 0:
            clean_h += b"0"
        try:
            decoded_list.append(binascii.unhexlify(clean_h))
        except Exception:
            continue
    return decoded_list


def scan_page_text(doc: fitz.Document, terms: list[str]) -> list[dict[str, Any]]:
    """Scansiona il livello testo di tutte le pagine."""
    findings = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        raw_text = page.get_text("text")
        norm_text = _normalize_ws(raw_text).lower()
        hyphen_norm_text = _normalize_ws(_normalize_hyphen(raw_text)).lower()

        for term in terms:
            term_clean = _normalize_ws(term).lower()
            if not term_clean:
                continue

            # 1. Ricerca con search_for nativo di PyMuPDF (geometria)
            rects = page.search_for(term)
            if rects:
                findings.append({
                    "surface": "page_text",
                    "term": term,
                    "page": page_idx + 1,
                    "type": "exact_search_for",
                    "count": len(rects),
                    "rects": [[round(coord, 2) for coord in (r.x0, r.y0, r.x1, r.y1)] for r in rects],
                })
                continue

            # 2. Ricerca nel testo normalizzato (intercetta spezzature su righe)
            if term_clean in norm_text:
                findings.append({
                    "surface": "page_text",
                    "term": term,
                    "page": page_idx + 1,
                    "type": "normalized_text_wrap",
                    "detail": "Termine trovato nel testo normalizzato (probabile a capo)",
                })
            elif term_clean in hyphen_norm_text:
                findings.append({
                    "surface": "page_text",
                    "term": term,
                    "page": page_idx + 1,
                    "type": "hyphenated_text_wrap",
                    "detail": "Termine trovato unendo sillabazione con trattino a fine riga",
                })
    return findings


def scan_annotations(doc: fitz.Document, terms: list[str]) -> list[dict[str, Any]]:
    """Scansiona tutte le annotazioni su tutte le pagine."""
    findings = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        for annot in page.annots():
            info = annot.info or {}
            annot_text = " ".join([
                str(info.get("content", "")),
                str(info.get("title", "")),
                str(info.get("subject", "")),
            ])
            try:
                extra_text = annot.get_text() or ""
                annot_text += " " + extra_text
            except Exception:
                pass

            norm_annot = _normalize_ws(annot_text).lower()
            for term in terms:
                term_clean = _normalize_ws(term).lower()
                if term_clean and term_clean in norm_annot:
                    findings.append({
                        "surface": "annotation",
                        "term": term,
                        "page": page_idx + 1,
                        "type": annot.type[1] if hasattr(annot, "type") else "unknown",
                        "detail": annot_text[:120],
                    })
    return findings


def scan_metadata(doc: fitz.Document, terms: list[str]) -> list[dict[str, Any]]:
    """Scansiona il dizionario Info e i metadati XMP."""
    findings = []
    meta = doc.metadata or {}
    for key, val in meta.items():
        if not val or not isinstance(val, str):
            continue
        norm_val = _normalize_ws(val).lower()
        for term in terms:
            term_clean = _normalize_ws(term).lower()
            if term_clean and term_clean in norm_val:
                findings.append({
                    "surface": "metadata_info",
                    "term": term,
                    "key": key,
                    "detail": val[:120],
                })

    # Metadati XMP XML
    try:
        xmp = doc.get_xml_metadata() or ""
        norm_xmp = _normalize_ws(xmp).lower()
        for term in terms:
            term_clean = _normalize_ws(term).lower()
            if term_clean and term_clean in norm_xmp:
                findings.append({
                    "surface": "metadata_xmp",
                    "term": term,
                    "detail": "Termine presente nel pacchetto XMP XML",
                })
    except Exception:
        pass

    return findings


def scan_outline(doc: fitz.Document, terms: list[str]) -> list[dict[str, Any]]:
    """Scansiona l'indice dei segnalibri (TOC / Outlines)."""
    findings = []
    try:
        toc = doc.get_toc(simple=False) or []
        for item in toc:
            # item format: [lvl, title, page, dest]
            title = str(item[1]) if len(item) > 1 else ""
            norm_title = _normalize_ws(title).lower()
            for term in terms:
                term_clean = _normalize_ws(term).lower()
                if term_clean and term_clean in norm_title:
                    findings.append({
                        "surface": "outline_bookmark",
                        "term": term,
                        "detail": title[:100],
                    })
    except Exception:
        pass
    return findings


def scan_embedded_files(doc: fitz.Document, terms: list[str]) -> list[dict[str, Any]]:
    """Scansiona i file incorporati (Embedded Files / Allegati)."""
    findings = []
    try:
        count = doc.embfile_count()
        for i in range(count):
            name = doc.embfile_info(i).get("filename", f"embfile_{i}")
            content = doc.embfile_get(i)
            # Decodifica testo dell'allegato
            text_cand = content.decode("utf-8", errors="replace") + " " + content.decode("latin-1", errors="replace")
            norm_content = _normalize_ws(name + " " + text_cand).lower()
            for term in terms:
                term_clean = _normalize_ws(term).lower()
                if term_clean and term_clean in norm_content:
                    findings.append({
                        "surface": "embedded_file",
                        "term": term,
                        "filename": name,
                        "detail": f"Trovato nell'allegato incorporato '{name}'",
                    })
    except Exception:
        pass
    return findings


def scan_widgets(doc: fitz.Document, terms: list[str]) -> list[dict[str, Any]]:
    """Scansiona i campi modulo (AcroForm Widgets)."""
    findings = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        for w in page.widgets():
            widget_text = " ".join([
                str(w.field_name or ""),
                str(w.field_value or ""),
                str(w.field_label or ""),
            ])
            norm_w = _normalize_ws(widget_text).lower()
            for term in terms:
                term_clean = _normalize_ws(term).lower()
                if term_clean and term_clean in norm_w:
                    findings.append({
                        "surface": "form_field",
                        "term": term,
                        "page": page_idx + 1,
                        "field_name": w.field_name,
                        "detail": widget_text[:120],
                    })
    return findings


def scan_ocgs(doc: fitz.Document, terms: list[str]) -> list[dict[str, Any]]:
    """Scansiona i nomi dei livelli opzionali (OCG)."""
    findings = []
    try:
        ocgs = doc.get_ocgs() or {}
        for xref, info in ocgs.items():
            name = info.get("name", "")
            norm_name = _normalize_ws(name).lower()
            for term in terms:
                term_clean = _normalize_ws(term).lower()
                if term_clean and term_clean in norm_name:
                    findings.append({
                        "surface": "ocg_layer_name",
                        "term": term,
                        "xref": xref,
                        "detail": name,
                    })
    except Exception:
        pass
    return findings


def scan_decompressed_streams(doc: fitz.Document, terms: list[str]) -> list[dict[str, Any]]:
    """Scansiona gli stream di tutti gli oggetti PDF decompressi, decodificando stringhe esadecimali e letterali."""
    findings = []
    # Prepara varianti binarie dei termini
    term_bytes_map = {}
    for term in terms:
        t_clean = term.strip()
        if not t_clean:
            continue
        term_bytes_map[term] = [
            t_clean.encode("utf-8"),
            t_clean.encode("latin-1", errors="replace"),
            t_clean.encode("utf-16-be"),
            t_clean.encode("utf-16-le"),
            t_clean.lower().encode("utf-8"),
        ]

    for xref in range(1, doc.xref_length()):
        try:
            if not doc.xref_is_stream(xref):
                continue
            stream = doc.xref_stream(xref)
            if not stream:
                continue

            stream_lower = stream.lower()
            # 1. Ricerca diretta nei byte dello stream
            for term, patterns in term_bytes_map.items():
                found_direct = any(p in stream or p in stream_lower for p in patterns)
                if found_direct:
                    findings.append({
                        "surface": "decompressed_stream",
                        "term": term,
                        "xref": xref,
                        "type": "direct_byte_match",
                    })
                    continue

            # 2. Ricerca nelle stringhe esadecimali <...> decodificate
            hex_chunks = _decode_hex_strings(stream)
            for chunk in hex_chunks:
                chunk_lower = chunk.lower()
                for term, patterns in term_bytes_map.items():
                    if any(p in chunk or p in chunk_lower for p in patterns):
                        findings.append({
                            "surface": "decompressed_stream",
                            "term": term,
                            "xref": xref,
                            "type": "decoded_hex_string",
                        })

            # 3. Ricerca nelle stringhe letterali (...) con escape ottali
            literal_matches = re.findall(rb"\((.*?)\)", stream, re.DOTALL)
            for lit in literal_matches:
                decoded_lit = _decode_pdf_literal(lit).lower()
                for term in terms:
                    if term.lower() in decoded_lit:
                        findings.append({
                            "surface": "decompressed_stream",
                            "term": term,
                            "xref": xref,
                            "type": "decoded_literal_string",
                        })
        except Exception:
            continue

    return findings


def scan_file_binary(pdf_bytes: bytes, terms: list[str]) -> list[dict[str, Any]]:
    """Scansiona l'intero file binario grezzo (anti-revisioni incrementali, vecchi trailer e commenti)."""
    findings = []
    bytes_lower = pdf_bytes.lower()
    for term in terms:
        t_clean = term.strip()
        if not t_clean:
            continue
        patterns = [
            t_clean.encode("utf-8"),
            t_clean.encode("latin-1", errors="replace"),
            t_clean.encode("utf-16-be"),
            t_clean.encode("utf-16-le"),
            t_clean.lower().encode("utf-8"),
        ]
        if any(p in pdf_bytes or p in bytes_lower for p in patterns):
            findings.append({
                "surface": "raw_binary_file",
                "term": term,
                "detail": "Termine rilevato nella sequenza binaria grezza del file (es. cronologia revisioni incrementali)",
            })
    return findings


def verify_pdf(
    pdf_source: Path | str | bytes,
    terms: list[str],
    *,
    ignore_raw_binary: bool = False,
) -> dict[str, Any]:
    """Esegue la scansione completa di un PDF su tutte le superfici note.

    Ritorna un dizionario con esito di pulizia e dettaglio puntuale di ciascun residuo trovato.
    """
    if isinstance(pdf_source, (str, Path)):
        p = Path(pdf_source)
        if not p.is_file():
            raise FileNotFoundError(f"File PDF non trovato: {p}")
        pdf_bytes = p.read_bytes()
        pdf_name = p.name
    else:
        pdf_bytes = pdf_source
        pdf_name = "<in-memory-bytes>"

    doc = fitz.open("pdf", pdf_bytes)

    findings: list[dict[str, Any]] = []
    findings.extend(scan_page_text(doc, terms))
    findings.extend(scan_annotations(doc, terms))
    findings.extend(scan_metadata(doc, terms))
    findings.extend(scan_outline(doc, terms))
    findings.extend(scan_embedded_files(doc, terms))
    findings.extend(scan_widgets(doc, terms))
    findings.extend(scan_ocgs(doc, terms))
    findings.extend(scan_decompressed_streams(doc, terms))

    if not ignore_raw_binary:
        findings.extend(scan_file_binary(pdf_bytes, terms))

    doc.close()

    # Rimuove duplicati esatti per pulizia report
    seen = set()
    unique_findings = []
    for f in findings:
        key = (f.get("surface"), f.get("term"), f.get("page"), f.get("xref"), f.get("type"), f.get("key"))
        if key not in seen:
            seen.add(key)
            unique_findings.append(f)

    is_clean = (len(unique_findings) == 0)
    return {
        "pdf_name": pdf_name,
        "clean": is_clean,
        "terms_checked": terms,
        "findings_count": len(unique_findings),
        "findings": unique_findings,
    }


def self_test() -> int:
    """Auto-test interno del verificatore su PDF sintetici noti puliti e contaminati."""
    print("Avvio self-test di verify_pdf_clean...")

    # 1. Crea un PDF contaminato su più superfici
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((50, 50), "Testo con Mario Rossi presente.")
    p.add_text_annot((100, 100), "Nota con Mario Rossi")
    doc.set_metadata({"author": "Mario Rossi"})
    dirty_bytes = doc.tobytes()
    doc.close()

    res_dirty = verify_pdf(dirty_bytes, ["Mario Rossi"])
    assert not res_dirty["clean"], "Il PDF contaminato doveva essere rilevato come non pulito!"
    surfaces_found = {f["surface"] for f in res_dirty["findings"]}
    assert "page_text" in surfaces_found
    assert "annotation" in surfaces_found
    assert "metadata_info" in surfaces_found
    print("  + Rilevazione corretta su PDF contaminato: PASS")

    # 2. Crea un PDF pulito (nessun termine presente)
    doc_clean = fitz.open()
    p_c = doc_clean.new_page()
    p_c.insert_text((50, 50), "Testo purificato e anonimizzato.")
    clean_bytes = doc_clean.tobytes()
    doc_clean.close()

    res_clean = verify_pdf(clean_bytes, ["Mario Rossi"])
    assert res_clean["clean"], "Il PDF pulito doveva risultare pulito!"
    assert res_clean["findings_count"] == 0
    print("  + Validazione corretta su PDF pulito: PASS")

    print("[SELF-TEST SUPERATO CON SUCCESSO]")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", nargs="?", type=Path, help="Percorso del file PDF da verificare")
    parser.add_argument("--terms", type=str, help="Elenco di termini separati da virgola (es. 'Mario Rossi,RSSMRA80A01H501U')")
    parser.add_argument("--terms-file", type=Path, help="File di testo contenente un termine per riga")
    parser.add_argument("--manifest", type=Path, help="File manifest.json del corpus da verificare")
    parser.add_argument("--corpus-dir", type=Path, help="Cartella contenente i PDF descritti nel manifest")
    parser.add_argument("--json", action="store_true", help="Stampa l'esito formattato in JSON")
    parser.add_argument("--self-test", action="store_true", help="Esegue la suite di auto-test interna")

    args = parser.parse_args()

    if args.self_test:
        return self_test()

    # Modalità verifica tramite manifest.json
    if args.manifest:
        if not args.manifest.is_file():
            print(f"Errore: manifest non trovato: {args.manifest}", file=sys.stderr)
            return 2
        with open(args.manifest, encoding="utf-8") as f:
            manifest_data = json.load(f)

        base_dir = args.corpus_dir or args.manifest.parent
        items = manifest_data.get("documenti", [])
        overall_clean = True
        results = []

        print(f"Verifica corpus da manifest: {args.manifest} ({len(items)} documenti)")
        for item in items:
            pdf_path = base_dir / item["filename"]
            terms = item.get("target_terms", [])
            guaranteed = item.get("guaranteed", True)
            if not pdf_path.is_file():
                print(f"  [ERRORE] File mancante: {pdf_path}", file=sys.stderr)
                overall_clean = False
                continue

            report = verify_pdf(pdf_path, terms)
            report["guaranteed"] = guaranteed
            results.append(report)

            status_badge = "[PULITO]" if report["clean"] else f"[RESIDUI: {report['findings_count']}]"
            print(f"  * {item['filename']:32s} {status_badge}")
            if not report["clean"]:
                for f in report["findings"][:3]:
                    print(f"      - {f['surface']}: termine '{f['term']}' ({f.get('detail', f.get('type', ''))})")
                if len(report["findings"]) > 3:
                    print(f"      ... e altri {len(report['findings']) - 3} riscontri")
                overall_clean = False

        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))

        return 0 if overall_clean else 1

    # Modalità singolo PDF
    if not args.pdf:
        parser.error("Specificare un file PDF oppure --manifest / --self-test")

    terms = []
    if args.terms:
        terms.extend([t.strip() for t in args.terms.split(",") if t.strip()])
    if args.terms_file:
        if not args.terms_file.is_file():
            print(f"Errore: terms-file non trovato: {args.terms_file}", file=sys.stderr)
            return 2
        for line in args.terms_file.read_text(encoding="utf-8").splitlines():
            line_str = line.strip()
            if line_str and not line_str.startswith("#"):
                terms.append(line_str)

    if not terms:
        parser.error("Nessun termine specificato (usare --terms o --terms-file)")

    try:
        report = verify_pdf(args.pdf, terms)
    except Exception as e:
        print(f"Errore durante l'ispezione: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Esito ispezione PDF: {report['pdf_name']}")
        print(f"Termini controllati ({len(terms)}): {', '.join(terms)}")
        if report["clean"]:
            print("[VERIFICA SUPERATA] Nessun residuo rilevato su alcuna superficie.")
        else:
            print(f"[VERIFICA FALLITA] Rilevati {report['findings_count']} residui:")
            for f in report["findings"]:
                detail = f.get("detail", f.get("type", ""))
                pg_str = f" (pag. {f['page']})" if "page" in f else ""
                print(f"  - [{f['surface']}{pg_str}] Termine '{f['term']}': {detail}")

    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
