"""Fail-closed redaction of recognized terms from text-based PDF files.

This module deliberately does not perform OCR.  A page which contains images but
no extractable text is rejected: painting a rectangle over an image would not
prove that the underlying pixels no longer contain personal data.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Iterable

import fitz


class PdfRedactionError(ValueError):
    """Base class for PDF redaction failures."""


class UnsupportedPdf(PdfRedactionError):
    """The input cannot be inspected safely without OCR or another parser."""


class RedactionIncomplete(PdfRedactionError):
    """At least one requested term is still observable in the output."""

    def __init__(self, report: dict[str, Any]):
        super().__init__("La verifica del PDF ha trovato dati residui: esportazione annullata.")
        self.report = report


def _normalise(value: str) -> str:
    """Casefold and ignore spacing, including line breaks."""
    return "".join(char for char in value.casefold() if not char.isspace())


def _count(text: str, term: str) -> int:
    needle = _normalise(term)
    haystack = _normalise(text)
    if not needle:
        return 0
    count = start = 0
    while (start := haystack.find(needle, start)) >= 0:
        count += 1
        start += max(1, len(needle))
    return count


def _page_characters(page: fitz.Page) -> list[tuple[str, fitz.Rect | None, int]]:
    """Return characters in reading order, retaining boxes and line identity."""
    raw = page.get_text("rawdict", flags=fitz.TEXT_DEHYPHENATE | fitz.TEXT_PRESERVE_WHITESPACE)
    result: list[tuple[str, fitz.Rect | None, int]] = []
    line_number = 0
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    value = char.get("c", "")
                    if value:
                        result.append((value, fitz.Rect(char["bbox"]), line_number))
            result.append(("\n", None, line_number))
            line_number += 1
    return result


def _searchable_page(page: fitz.Page) -> tuple[str, list[tuple[fitz.Rect, int]]]:
    """Build normalised text and a map from each character back to its PDF box."""
    source = _page_characters(page)
    text: list[str] = []
    positions: list[tuple[fitz.Rect, int]] = []
    for index, (char, rect, line) in enumerate(source):
        if char.isspace():
            continue
        # A hyphen at the physical end of a line is layout, not semantic text.
        if char in ("-", "\u00ad") and index + 1 < len(source) and source[index + 1][0] == "\n":
            continue
        folded = char.casefold()
        for item in folded:
            if not item.isspace() and rect is not None:
                text.append(item)
                positions.append((rect, line))
    return "".join(text), positions


def _find_rectangles(page: fitz.Page, term: str) -> list[list[fitz.Rect]]:
    haystack, positions = _searchable_page(page)
    needle = _normalise(term)
    if not needle:
        return []
    hits: list[list[fitz.Rect]] = []
    start = 0
    while (start := haystack.find(needle, start)) >= 0:
        by_line: dict[int, fitz.Rect] = {}
        for rect, line in positions[start:start + len(needle)]:
            by_line[line] = rect if line not in by_line else by_line[line] | rect
        hits.append(list(by_line.values()))
        start += len(needle)
    return hits


def _surface_text(document: fitz.Document) -> str:
    """Collect non-page-text surfaces before they are scrubbed."""
    values: list[str] = []
    values.extend(str(value) for value in document.metadata.values() if value)
    try:
        values.append(document.get_xml_metadata() or "")
    except (RuntimeError, ValueError):
        pass
    for row in document.get_toc(simple=True):
        values.extend(str(value) for value in row if value)
    for name in document.embfile_names():
        values.append(name)
        try:
            payload = document.embfile_get(name)
            values.append(payload.decode("utf-8", errors="ignore"))
            values.append(payload.decode("latin-1", errors="ignore"))
        except (RuntimeError, ValueError):
            pass
    for page in document:
        for link in page.get_links():
            values.extend(str(value) for value in link.values() if value)
        annotations = page.annots()
        if annotations:
            for annotation in annotations:
                values.extend(str(value) for value in annotation.info.values() if value)
        widgets = page.widgets()
        if widgets:
            for widget in widgets:
                for attribute in ("field_name", "field_label", "field_value"):
                    value = getattr(widget, attribute, None)
                    if value:
                        values.append(str(value))
    return "\n".join(values)


def _delete_annotations(document: fitz.Document) -> None:
    for page in document:
        annotations = list(page.annots() or [])
        for annotation in annotations:
            page.delete_annot(annotation)
        widgets = list(page.widgets() or [])
        for widget in widgets:
            page.delete_widget(widget)


def _raw_pdf_text(document: fitz.Document, pdf_bytes: bytes) -> str:
    """Decode objects and streams conservatively for the independent final gate."""
    values = [pdf_bytes.decode("latin-1", errors="ignore"), pdf_bytes.decode("utf-8", errors="ignore")]
    for xref in range(1, document.xref_length()):
        try:
            values.append(document.xref_object(xref, compressed=False))
            if document.xref_is_stream(xref):
                stream = document.xref_stream(xref)
                values.append(stream.decode("utf-8", errors="ignore"))
                values.append(stream.decode("latin-1", errors="ignore"))
        except (RuntimeError, ValueError):
            raise PdfRedactionError(
                "La struttura interna del PDF non può essere verificata completamente."
            )
    return "\n".join(values)


def _verification_text(document: fitz.Document, pdf_bytes: bytes) -> str:
    values = [_surface_text(document), _raw_pdf_text(document, pdf_bytes)]
    for page in document:
        values.append(page.get_text("text"))
    return "\n".join(values)


def _encoded_count(text: str, term: str) -> int:
    """Find common PDF hex-string encodings not visible in decoded stream text."""
    folded = text.casefold()
    variants = {
        term.encode("utf-8").hex(),
        term.encode("utf-16-be").hex(),
        term.encode("utf-16-le").hex(),
    }
    return sum(folded.count(value.casefold()) for value in variants if value)


def _validate_terms(terms: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in terms:
        if not isinstance(value, str) or not _normalise(value):
            raise PdfRedactionError("Ogni dato da censurare deve essere una stringa non vuota.")
        key = _normalise(value)
        if key not in seen:
            cleaned.append(value)
            seen.add(key)
    if not cleaned:
        raise PdfRedactionError("Non è stato indicato alcun dato da censurare.")
    return cleaned


def redact_pdf(
    data: bytes,
    terms: list[str],
    mode: str = "nero",
    labels: dict[str, str] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Remove terms and sensitive auxiliary surfaces, then verify the saved PDF.

    Matching is Unicode case-insensitive and ignores whitespace.  A hyphen at a
    physical line ending is ignored, so ``Ros-\nsi`` matches ``Rossi``.
    """
    if mode not in {"nero", "etichetta"}:
        raise PdfRedactionError("La modalità deve essere 'nero' oppure 'etichetta'.")
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise PdfRedactionError("Il PDF è vuoto o non valido.")
    selected = _validate_terms(terms)
    label_map = labels or {}
    try:
        document = fitz.open(stream=bytes(data), filetype="pdf")
    except (RuntimeError, ValueError) as exc:
        raise PdfRedactionError("Il file non è un PDF leggibile.") from exc
    try:
        if document.needs_pass:
            raise UnsupportedPdf("I PDF protetti da password non sono supportati.")
        if document.page_count == 0:
            raise UnsupportedPdf("Il PDF non contiene pagine.")

        report: dict[str, Any] = {
            "mode": mode,
            "pages": document.page_count,
            "terms": {term: {"removed": 0, "residual": 0} for term in selected},
            "limitations": [
                "Le immagini con testo richiedono OCR e non sono censurabili in questa versione.",
                "Font privi di una mappatura Unicode affidabile possono impedire il riconoscimento del testo.",
            ],
        }
        auxiliary = _surface_text(document)
        for term in selected:
            report["terms"][term]["removed"] += _count(auxiliary, term)

        for page_number, page in enumerate(document):
            extracted = page.get_text("text")
            if page.get_images(full=True) and not _normalise(extracted):
                raise UnsupportedPdf(
                    f"Pagina {page_number + 1}: sembra una scansione; serve OCR prima della censura."
                )
            if "\ufffd" in extracted or "\x00" in extracted:
                raise UnsupportedPdf(
                    f"Pagina {page_number + 1}: il testo non ha una mappatura Unicode affidabile."
                )
            for term in selected:
                hits = _find_rectangles(page, term)
                report["terms"][term]["removed"] += len(hits)
                for rectangles in hits:
                    for rectangle_number, rectangle in enumerate(rectangles):
                        if mode == "nero":
                            page.add_redact_annot(rectangle, fill=(0, 0, 0), cross_out=False)
                        else:
                            text = str(label_map.get(term, "[OMESSO]")) if rectangle_number == 0 else None
                            page.add_redact_annot(
                                rectangle,
                                text=text,
                                fontsize=8,
                                fill=(1, 1, 1),
                                text_color=(0, 0, 0),
                                cross_out=False,
                            )
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_REMOVE,
                graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                text=fitz.PDF_REDACT_TEXT_REMOVE,
            )

        _delete_annotations(document)
        document.set_toc([])
        document.scrub(
            attached_files=True,
            clean_pages=True,
            embedded_files=True,
            hidden_text=True,
            javascript=True,
            metadata=True,
            redactions=True,
            redact_images=fitz.PDF_REDACT_IMAGE_REMOVE,
            remove_links=True,
            reset_fields=True,
            reset_responses=True,
            thumbnails=True,
            xml_metadata=True,
        )
        output = BytesIO()
        document.save(
            output,
            garbage=4,
            clean=True,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            incremental=False,
            preserve_metadata=False,
        )
        result = output.getvalue()
    finally:
        document.close()

    verified = fitz.open(stream=result, filetype="pdf")
    try:
        verification = _verification_text(verified, result)
        for term in selected:
            report["terms"][term]["residual"] = (
                _count(verification, term) + _encoded_count(verification, term)
            )
    finally:
        verified.close()
    if any(item["residual"] for item in report["terms"].values()):
        raise RedactionIncomplete(report)
    report["verified"] = True
    return result, report
