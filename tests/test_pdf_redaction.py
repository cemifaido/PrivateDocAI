import os
import tempfile
import unittest

import fitz

from backend.pdf_redaction import (
    PdfRedactionError,
    RedactionIncomplete,
    UnsupportedPdf,
    redact_pdf,
)


def _save(document: fitz.Document) -> bytes:
    data = document.tobytes(garbage=4, clean=True, deflate=True)
    document.close()
    return data


class PdfRedactionTests(unittest.TestCase):
    def test_removes_case_and_space_insensitive_text(self):
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Cliente: MARIO     ROSSI")

        output, report = redact_pdf(_save(document), ["Mario Rossi"])

        redacted = fitz.open(stream=output, filetype="pdf")
        try:
            self.assertNotIn("MARIO", redacted[0].get_text().upper())
            self.assertIn("Cliente", redacted[0].get_text())
        finally:
            redacted.close()
        self.assertTrue(report["verified"])
        self.assertEqual(report["terms"]["Mario Rossi"], {"removed": 1, "residual": 0})

    def test_matches_a_name_split_and_hyphenated_across_lines(self):
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Giovanni Ros-")
        page.insert_text((72, 88), "si")

        output, report = redact_pdf(_save(document), ["Giovanni Rossi"])

        redacted = fitz.open(stream=output, filetype="pdf")
        try:
            remaining = redacted[0].get_text().replace(" ", "").replace("\n", "").casefold()
            self.assertNotIn("giovannirossi", remaining)
        finally:
            redacted.close()
        self.assertEqual(report["terms"]["Giovanni Rossi"]["removed"], 1)

    def test_label_mode_writes_only_the_placeholder(self):
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Mario Rossi", fontsize=12)

        output, report = redact_pdf(
            _save(document),
            ["Mario Rossi"],
            mode="etichetta",
            labels={"Mario Rossi": "[P_1]"},
        )

        redacted = fitz.open(stream=output, filetype="pdf")
        try:
            text = redacted[0].get_text()
            self.assertNotIn("Mario", text)
            self.assertIn("[P_1]", text)
        finally:
            redacted.close()
        self.assertEqual(report["mode"], "etichetta")

    def test_scrubs_metadata_xmp_outline_annotation_attachment_and_form(self):
        term = "Segreto Alfa"
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "testo pubblico")
        document.set_metadata({"title": term, "author": term})
        document.set_xml_metadata(f"<x:xmpmeta xmlns:x='adobe:ns:meta/'>{term}</x:xmpmeta>")
        document.set_toc([[1, term, 1]])
        annotation = page.add_text_annot((100, 100), term)
        annotation.set_info(content=term, title=term)
        annotation.update()
        document.embfile_add(f"{term}.txt", term.encode("utf-8"), filename=f"{term}.txt")
        widget = fitz.Widget()
        widget.field_name = term
        widget.field_value = term
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.rect = fitz.Rect(72, 110, 220, 135)
        page.add_widget(widget)

        output, report = redact_pdf(_save(document), [term])

        cleaned = fitz.open(stream=output, filetype="pdf")
        try:
            metadata = "\n".join(str(value) for value in cleaned.metadata.values() if value)
            self.assertNotIn(term, metadata)
            self.assertEqual(cleaned.get_xml_metadata(), "")
            self.assertEqual(cleaned.get_toc(), [])
            self.assertEqual(cleaned.embfile_count(), 0)
            self.assertEqual(list(cleaned[0].annots() or []), [])
            self.assertEqual(list(cleaned[0].widgets() or []), [])
        finally:
            cleaned.close()
        self.assertTrue(report["verified"])
        self.assertGreaterEqual(report["terms"][term]["removed"], 1)

    def test_rejects_an_image_only_scanned_page(self):
        document = fitz.open()
        page = document.new_page()
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
        pixmap.clear_with(255)
        page.insert_image(fitz.Rect(72, 72, 172, 172), stream=pixmap.tobytes("png"))

        with self.assertRaisesRegex(UnsupportedPdf, "scansione"):
            redact_pdf(_save(document), ["Mario Rossi"])

    def test_removes_an_overlapping_image_and_line_art(self):
        document = fitz.open()
        page = document.new_page()
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
        pixmap.clear_with(255)
        page.insert_image(fitz.Rect(60, 50, 180, 90), stream=pixmap.tobytes("png"))
        page.draw_rect(fitz.Rect(65, 55, 150, 80), color=(1, 0, 0), width=2)
        page.insert_text((72, 72), "Mario Rossi", fontsize=12)

        output, report = redact_pdf(_save(document), ["Mario Rossi"])

        cleaned = fitz.open(stream=output, filetype="pdf")
        try:
            self.assertEqual(cleaned[0].get_images(full=True), [])
            self.assertFalse(any(drawing.get("color") == (1.0, 0.0, 0.0)
                                 for drawing in cleaned[0].get_drawings()))
        finally:
            cleaned.close()
        self.assertTrue(report["verified"])

    def test_full_save_discards_an_old_incremental_revision(self):
        term = "Mario Rossi"
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "incremental.pdf")
            document = fitz.open()
            page = document.new_page()
            page.insert_text((72, 72), term)
            document.save(path)
            document.close()
            document = fitz.open(path)
            page = document[0]
            for rectangle in page.search_for(term):
                page.add_redact_annot(rectangle)
            page.apply_redactions()
            document.saveIncr()
            document.close()
            with open(path, "rb") as source:
                incremental = source.read()

        encoded_term = term.encode("ascii").hex().encode("ascii")
        self.assertIn(encoded_term, incremental.lower())
        output, report = redact_pdf(incremental, [term])
        self.assertNotIn(encoded_term, output.lower())
        self.assertTrue(report["verified"])

    def test_validates_arguments(self):
        document = fitz.open()
        document.new_page().insert_text((72, 72), "testo")
        data = _save(document)
        with self.assertRaises(PdfRedactionError):
            redact_pdf(data, [])
        with self.assertRaises(PdfRedactionError):
            redact_pdf(data, ["Mario"], mode="sfocato")
        with self.assertRaises(PdfRedactionError):
            redact_pdf(b"non un pdf", ["Mario"])

    def test_incomplete_error_exposes_the_report(self):
        report = {"terms": {"Mario": {"removed": 0, "residual": 1}}}
        error = RedactionIncomplete(report)
        self.assertIs(error.report, report)


if __name__ == "__main__":
    unittest.main()
