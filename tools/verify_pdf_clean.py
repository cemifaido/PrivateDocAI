#!/usr/bin/env python3
"""Strumento di verifica e audit per la pulizia reale di PDF redatti.

Progettato per PrivateDoc AI (Milestone 4 - Punto 1).
Esegue un'ispezione indipendente, approfondita e multilivello su qualsiasi PDF
per certificare che i termini sensibili specificati siano stati FISICAMENTE
rimossi dal documento e non semplicemente coperti graficamente.

Superfici ispezionate:
1. Pagine / Testo vettoriale (tolleranza spazi, ritorni a capo, sillabazioni e bianco-su-bianco)
2. Pagine scansionate / Immagini pure (segnalate come NON VERIFICABILI senza OCR, mai falsi puliti)
3. Annotazioni (Sticky note, FreeText, evidenziazioni, commenti, pop-up)
4. Collegamenti / Link (URI, destinazioni e file link)
5. Metadati documento (dizionario Info: autore, titolo, oggetto, parole chiave, ecc.)
6. Pacchetto metadati XMP (XML packet)
7. Segnalibri / Sommario / Outline TOC
8. File incorporati / Allegati (Embedded Files) con decompressione del contenuto
9. Campi modulo / AcroForm (valori, etichette, nomi campo, tooltip)
10. Livelli / Strati opzionali (OCG - Optional Content Groups)
11. Tutti gli oggetti PDF e dizionari (Catalog, Names, Azioni JS, ecc.) con decodifica hex e literal
12. Stream decompressi di tutti gli oggetti PDF (xref streams con decodifica hex <...> e literal)
13. Scansione binaria grezza del file completo (anti-revisioni incrementali e trailer residui)

Codice di uscita:
- 0: Pulito al 100% (nessun residuo trovato per i termini specificati)
- 1: Trovati residui dei termini sensibili o pagine scansionate non verificabili
- 2: Errore di argomenti, input non valido, PDF corrotto o protetto da password
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


def _normalise(value: str) -> str:
    """Casefold rigoroso e rimozione di ogni spaziatura (contratto di matching PrivateDoc AI)."""
    if not value or not isinstance(value, str):
        return ""
    return "".join(c for c in value.casefold() if not c.isspace())


def _normalize_hyphen(text: str) -> str:
    """Rimuove trattini a fine riga per unire parole spezzate."""
    return re.sub(r"-\s*\n\s*", "", text)


def _decode_pdf_literal(raw: bytes) -> str:
    """Decodifica sequenze di escape ottali e speciali in stringhe letterali PDF."""
    def replace_octal(match: re.Match[bytes]) -> bytes:
        oct_val = int(match.group(1), 8)
        return bytes([oct_val])

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
    """Estrae e decodifica tutte le stringhe esadecimali <...> presenti in uno stream o dizionario PDF."""
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


def scan_page_text_and_images(doc: fitz.Document, terms: list[str]) -> list[dict[str, Any]]:
    """Scansiona il livello testo di tutte le pagine e rileva pagine immagine non verificabili."""
    findings = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        raw_text = page.get_text("text")
        norm_text = _normalise(raw_text)
        hyphen_norm_text = _normalise(_normalize_hyphen(raw_text))

        # Controllo anti-falso pulito: se la pagina contiene immagini ma zero testo vettoriale
        # la scansione grafica non puo' essere garantita senza OCR.
        if page.get_images(full=True) and not norm_text:
            findings.append({
                "surface": "scanned_image_unverifiable",
                "page": page_idx + 1,
                "type": "missing_text_layer",
                "detail": f"Pagina {page_idx + 1} contiene immagini senza livello testo: non verificabile senza OCR",
            })

        for term in terms:
            term_norm = _normalise(term)
            if not term_norm:
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

            # 2. Ricerca nel testo normalizzato (casefold + spazi ignorati, intercetta a capo)
            if term_norm in norm_text:
                findings.append({
                    "surface": "page_text",
                    "term": term,
                    "page": page_idx + 1,
                    "type": "normalized_text_wrap",
                    "detail": "Termine trovato nel testo normalizzato (probabile ritorno a capo)",
                })
            elif term_norm in hyphen_norm_text:
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
        annots = page.annots()
        if not annots:
            continue
        for annot in annots:
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

            norm_annot = _normalise(annot_text)
            for term in terms:
                term_norm = _normalise(term)
                if term_norm and term_norm in norm_annot:
                    findings.append({
                        "surface": "annotation",
                        "term": term,
                        "page": page_idx + 1,
                        "type": annot.type[1] if hasattr(annot, "type") else "unknown",
                        "detail": annot_text[:120],
                    })
    return findings


def scan_links(doc: fitz.Document, terms: list[str]) -> list[dict[str, Any]]:
    """Scansiona i link presenti su tutte le pagine (URI, file, destinazioni)."""
    findings = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        for link in page.get_links():
            link_text = " ".join(str(v) for v in link.values() if v)
            norm_link = _normalise(link_text)
            for term in terms:
                term_norm = _normalise(term)
                if term_norm and term_norm in norm_link:
                    findings.append({
                        "surface": "link",
                        "term": term,
                        "page": page_idx + 1,
                        "detail": link_text[:120],
                    })
    return findings


def scan_metadata(doc: fitz.Document, terms: list[str], errors: list[str]) -> list[dict[str, Any]]:
    """Scansiona il dizionario Info e i metadati XMP."""
    findings = []
    meta = doc.metadata or {}
    for key, val in meta.items():
        if not val or not isinstance(val, str):
            continue
        norm_val = _normalise(val)
        for term in terms:
            term_norm = _normalise(term)
            if term_norm and term_norm in norm_val:
                findings.append({
                    "surface": "metadata_info",
                    "term": term,
                    "key": key,
                    "detail": val[:120],
                })

    try:
        xmp = doc.get_xml_metadata() or ""
        norm_xmp = _normalise(xmp)
        for term in terms:
            term_norm = _normalise(term)
            if term_norm and term_norm in norm_xmp:
                findings.append({
                    "surface": "metadata_xmp",
                    "term": term,
                    "detail": "Termine presente nel pacchetto XMP XML",
                })
    except Exception as exc:
        errors.append(f"Errore lettura XMP: {exc}")

    return findings


def scan_outline(doc: fitz.Document, terms: list[str], errors: list[str]) -> list[dict[str, Any]]:
    """Scansiona l'indice dei segnalibri (TOC / Outlines)."""
    findings = []
    try:
        toc = doc.get_toc(simple=False) or []
        for item in toc:
            title = str(item[1]) if len(item) > 1 else ""
            norm_title = _normalise(title)
            for term in terms:
                term_norm = _normalise(term)
                if term_norm and term_norm in norm_title:
                    findings.append({
                        "surface": "outline_bookmark",
                        "term": term,
                        "detail": title[:100],
                    })
    except Exception as exc:
        errors.append(f"Errore lettura TOC/outline: {exc}")
    return findings


def scan_embedded_files(doc: fitz.Document, terms: list[str], errors: list[str]) -> list[dict[str, Any]]:
    """Scansiona i file incorporati (Embedded Files / Allegati)."""
    findings = []
    try:
        count = doc.embfile_count()
        for i in range(count):
            name = doc.embfile_info(i).get("filename", f"embfile_{i}")
            content = doc.embfile_get(i)
            text_cand = content.decode("utf-8", errors="replace") + " " + content.decode("latin-1", errors="replace")
            norm_content = _normalise(name + " " + text_cand)
            for term in terms:
                term_norm = _normalise(term)
                if term_norm and term_norm in norm_content:
                    findings.append({
                        "surface": "embedded_file",
                        "term": term,
                        "filename": name,
                        "detail": f"Trovato nell'allegato incorporato '{name}'",
                    })
    except Exception as exc:
        errors.append(f"Errore lettura file incorporati: {exc}")
    return findings


def scan_widgets(doc: fitz.Document, terms: list[str]) -> list[dict[str, Any]]:
    """Scansiona i campi modulo (AcroForm Widgets)."""
    findings = []
    for page_idx in range(len(doc)):
        page = doc[page_idx]
        widgets = page.widgets()
        if not widgets:
            continue
        for w in widgets:
            widget_text = " ".join([
                str(w.field_name or ""),
                str(w.field_value or ""),
                str(w.field_label or ""),
            ])
            norm_w = _normalise(widget_text)
            for term in terms:
                term_norm = _normalise(term)
                if term_norm and term_norm in norm_w:
                    findings.append({
                        "surface": "form_field",
                        "term": term,
                        "page": page_idx + 1,
                        "field_name": w.field_name,
                        "detail": widget_text[:120],
                    })
    return findings


def scan_ocgs(doc: fitz.Document, terms: list[str], errors: list[str]) -> list[dict[str, Any]]:
    """Scansiona i nomi dei livelli opzionali (OCG)."""
    findings = []
    try:
        ocgs = doc.get_ocgs() or {}
        for xref, info in ocgs.items():
            name = info.get("name", "")
            norm_name = _normalise(name)
            for term in terms:
                term_norm = _normalise(term)
                if term_norm and term_norm in norm_name:
                    findings.append({
                        "surface": "ocg_layer_name",
                        "term": term,
                        "xref": xref,
                        "detail": name,
                    })
    except Exception as exc:
        errors.append(f"Errore lettura OCG: {exc}")
    return findings


def scan_objects_and_streams(doc: fitz.Document, terms: list[str], errors: list[str]) -> list[dict[str, Any]]:
    """Scansiona dizionari e stream decompressi di tutti gli oggetti PDF."""
    findings = []
    term_bytes_map = {}
    term_hex_variants = {}
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
        term_hex_variants[term] = [
            t_clean.encode("utf-8").hex().casefold(),
            t_clean.encode("utf-16-be").hex().casefold(),
            t_clean.encode("utf-16-le").hex().casefold(),
        ]

    for xref in range(1, doc.xref_length()):
        try:
            # 1. Scansione dizionario oggetto non compresso
            obj_str = doc.xref_object(xref, compressed=False)
            norm_obj = _normalise(obj_str)
            obj_lower = obj_str.casefold()

            for term in terms:
                term_norm = _normalise(term)
                if term_norm and term_norm in norm_obj:
                    findings.append({
                        "surface": "object_dictionary",
                        "term": term,
                        "xref": xref,
                        "type": "dictionary_text_match",
                    })

                # Ricerca stringhe hex nei dizionari
                for h_var in term_hex_variants.get(term, []):
                    if h_var in obj_lower:
                        findings.append({
                            "surface": "object_dictionary",
                            "term": term,
                            "xref": xref,
                            "type": "dictionary_hex_match",
                        })

            # 2. Scansione stream decompressi
            if doc.xref_is_stream(xref):
                stream = doc.xref_stream(xref)
                if stream:
                    stream_lower = stream.lower()
                    # Ricerca diretta nei byte dello stream
                    for term, patterns in term_bytes_map.items():
                        found_direct = any(p in stream or p in stream_lower for p in patterns)
                        if found_direct:
                            findings.append({
                                "surface": "decompressed_stream",
                                "term": term,
                                "xref": xref,
                                "type": "direct_byte_match",
                            })

                    # Ricerca nelle stringhe esadecimali <...> decodificate
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

                    # Ricerca nelle stringhe letterali (...) con escape ottali
                    literal_matches = re.findall(rb"\((.*?)\)", stream, re.DOTALL)
                    for lit in literal_matches:
                        decoded_lit = _decode_pdf_literal(lit)
                        norm_lit = _normalise(decoded_lit)
                        for term in terms:
                            term_norm = _normalise(term)
                            if term_norm and term_norm in norm_lit:
                                findings.append({
                                    "surface": "decompressed_stream",
                                    "term": term,
                                    "xref": xref,
                                    "type": "decoded_literal_string",
                                })
        except Exception as exc:
            errors.append(f"Errore ispezione oggetto xref {xref}: {exc}")

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
            t_clean.encode("utf-8").hex().encode("ascii"),
            t_clean.encode("utf-16-be").hex().encode("ascii"),
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

    Valida rigorosamente gli input e ritorna un dizionario con l'esito di pulizia.
    Solleva ValueError se i termini sono vuoti o il PDF non e' leggibile/protetto.
    """
    if not isinstance(terms, (list, tuple, set)):
        raise ValueError("L'argomento 'terms' deve essere una lista di stringhe.")
    valid_terms = [t.strip() for t in terms if isinstance(t, str) and _normalise(t)]
    if not valid_terms:
        raise ValueError("Nessun dato valido specificato da verificare (termini vuoti o composti da soli spazi).")

    if isinstance(pdf_source, (str, Path)):
        p = Path(pdf_source)
        if not p.is_file():
            raise FileNotFoundError(f"File PDF non trovato: {p}")
        pdf_bytes = p.read_bytes()
        pdf_name = p.name
    elif isinstance(pdf_source, (bytes, bytearray)):
        pdf_bytes = bytes(pdf_source)
        pdf_name = "<in-memory-bytes>"
    else:
        raise ValueError("pdf_source deve essere un percorso di file o una sequenza di byte.")

    if not pdf_bytes:
        raise ValueError("Il PDF specificato è vuoto (0 byte).")

    try:
        doc = fitz.open("pdf", pdf_bytes)
    except Exception as exc:
        raise ValueError(f"File non riconosciuto come PDF valido: {exc}") from exc

    try:
        if doc.needs_pass:
            raise ValueError("I PDF protetti da password non sono supportati.")
        if doc.page_count == 0:
            raise ValueError("Il PDF non contiene pagine.")

        errors: list[str] = []
        findings: list[dict[str, Any]] = []

        findings.extend(scan_page_text_and_images(doc, valid_terms))
        findings.extend(scan_annotations(doc, valid_terms))
        findings.extend(scan_links(doc, valid_terms))
        findings.extend(scan_metadata(doc, valid_terms, errors))
        findings.extend(scan_outline(doc, valid_terms, errors))
        findings.extend(scan_embedded_files(doc, valid_terms, errors))
        findings.extend(scan_widgets(doc, valid_terms))
        findings.extend(scan_ocgs(doc, valid_terms, errors))
        findings.extend(scan_objects_and_streams(doc, valid_terms, errors))

        if not ignore_raw_binary:
            findings.extend(scan_file_binary(pdf_bytes, valid_terms))
    finally:
        doc.close()

    # Rimuove duplicati esatti per pulizia del report
    seen = set()
    unique_findings = []
    for f in findings:
        key = (f.get("surface"), f.get("term"), f.get("page"), f.get("xref"), f.get("type"), f.get("key"))
        if key not in seen:
            seen.add(key)
            unique_findings.append(f)

    is_clean = (len(unique_findings) == 0 and len(errors) == 0)
    return {
        "pdf_name": pdf_name,
        "clean": is_clean,
        "terms_checked": valid_terms,
        "findings_count": len(unique_findings),
        "findings": unique_findings,
        "errors": errors,
    }


def self_test() -> int:
    """Suite di auto-test interna per validare rilevazione, anti-falso pulito ed eccezioni."""
    print("Avvio self-test approfondito di verify_pdf_clean...")

    # 1. Rilevazione su PDF contaminato
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((50, 50), "Testo con Mario Rossi presente.")
    p.add_text_annot((100, 100), "Nota con Mario Rossi")
    doc.set_metadata({"author": "Mario Rossi"})
    dirty_bytes = doc.tobytes()
    doc.close()

    res_dirty = verify_pdf(dirty_bytes, ["Mario Rossi"])
    assert not res_dirty["clean"], "PDF contaminato doveva fallire!"
    surfaces = {f["surface"] for f in res_dirty["findings"]}
    assert "page_text" in surfaces
    assert "annotation" in surfaces
    assert "metadata_info" in surfaces
    print("  + Rilevazione contaminazioni standard: PASS")

    # 2. Validazione su PDF pulito
    doc_clean = fitz.open()
    p_c = doc_clean.new_page()
    p_c.insert_text((50, 50), "Testo purificato e anonimizzato.")
    clean_bytes = doc_clean.tobytes()
    doc_clean.close()

    res_clean = verify_pdf(clean_bytes, ["Mario Rossi"])
    assert res_clean["clean"], "PDF pulito doveva passare!"
    assert res_clean["findings_count"] == 0
    print("  + Validazione documento pulito: PASS")

    # 3. Anti-falso pulito su scansioni (immagini senza testo)
    from PIL import Image as PilImage
    import io as pyio
    img = PilImage.new("RGB", (100, 100), color=(200, 200, 200))
    buf = pyio.BytesIO()
    img.save(buf, format="PNG")
    doc_scan = fitz.open()
    p_s = doc_scan.new_page()
    p_s.insert_image(fitz.Rect(50, 50, 250, 250), stream=buf.getvalue())
    scan_bytes = doc_scan.tobytes()
    doc_scan.close()

    res_scan = verify_pdf(scan_bytes, ["Mario Rossi"])
    assert not res_scan["clean"], "Scansione grafica doveva essere segnalata come NON verificabile!"
    assert any(f["surface"] == "scanned_image_unverifiable" for f in res_scan["findings"])
    print("  + Anti-falso pulito su scansioni senza OCR: PASS")

    # 4. Validazione input vuoto
    try:
        verify_pdf(clean_bytes, ["", "   "])
        assert False, "Doveva sollevare ValueError per termini vuoti!"
    except ValueError:
        print("  + Rifiuto termini vuoti/spazi: PASS")

    # 5. Matching casefold e spazi ignorati (contratto PrivateDoc AI)
    doc_ws = fitz.open()
    doc_ws.new_page().insert_text((50, 50), "M a r i o   R o s s i")
    res_ws = verify_pdf(doc_ws.tobytes(), ["Mario Rossi"])
    doc_ws.close()
    assert not res_ws["clean"], "Doveva intercettare 'M a r i o   R o s s i' con spazi multipli/interni!"
    print("  + Matching tollerante spazi interni: PASS")

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

    # Modalita' verifica tramite manifest.json
    if args.manifest:
        if not args.manifest.is_file():
            print(f"Errore: manifest non trovato: {args.manifest}", file=sys.stderr)
            return 2
        try:
            with open(args.manifest, encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception as exc:
            print(f"Errore lettura manifest: {exc}", file=sys.stderr)
            return 2

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

            try:
                report = verify_pdf(pdf_path, terms)
            except Exception as exc:
                print(f"  [ERRORE] {item['filename']}: {exc}", file=sys.stderr)
                overall_clean = False
                continue

            report["guaranteed"] = guaranteed
            results.append(report)

            status_badge = "[PULITO]" if report["clean"] else f"[RESIDUI/NON VERIFICABILE: {report['findings_count']}]"
            print(f"  * {item['filename']:32s} {status_badge}")
            if not report["clean"]:
                for f in report["findings"][:3]:
                    surface = f.get("surface")
                    term = f.get("term", "")
                    detail = f.get("detail", f.get("type", ""))
                    print(f"      - {surface}: {term} ({detail})")
                if len(report["findings"]) > 3:
                    print(f"      ... e altri {len(report['findings']) - 3} riscontri")
                overall_clean = False

        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))

        return 0 if overall_clean else 1

    # Modalita' singolo PDF
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
        print("Errore: nessun termine specificato (usare --terms o --terms-file)", file=sys.stderr)
        return 2

    try:
        report = verify_pdf(args.pdf, terms)
    except FileNotFoundError as exc:
        print(f"Errore file: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Errore validazione: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Errore imprevisto durante l'ispezione: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Esito ispezione PDF: {report['pdf_name']}")
        print(f"Termini controllati ({len(report['terms_checked'])}): {', '.join(report['terms_checked'])}")
        if report["clean"]:
            print("[VERIFICA SUPERATA] Nessun residuo rilevato su alcuna superficie.")
        else:
            print(f"[VERIFICA FALLITA] Rilevati {report['findings_count']} riscontri:")
            for f in report["findings"]:
                detail = f.get("detail", f.get("type", ""))
                pg_str = f" (pag. {f['page']})" if "page" in f else ""
                term_str = f" Termine '{f['term']}':" if "term" in f else ""
                print(f"  - [{f['surface']}{pg_str}]{term_str} {detail}")

    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
