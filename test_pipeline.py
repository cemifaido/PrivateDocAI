import io
import zipfile
import docx
import openpyxl
from backend.document_service import DocumentService

def create_sample_zip():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. Sample Word DOCX
        doc = docx.Document()
        doc.add_heading("Contratto di Fornitura Software", 0)
        doc.add_paragraph("Il presente accordo è stipulato tra il Dott. Mario Rossi (C.F. RSSMRA80A01H501U) residente in Via Roma 42, Milano")
        doc.add_paragraph("e la società Acme S.r.l., con sede in Milano, P.IVA 01234567890.")
        doc.add_paragraph("Il compenso concordato è pari a 150.000 € con termine fissato al 15/10/2026.")
        doc_io = io.BytesIO()
        doc.save(doc_io)
        zf.writestr("Contratto_Mario_Rossi.docx", doc_io.getvalue())

        # 2. Sample Excel XLSX
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Riepilogo Costi"
        ws.append(["Cliente", "Societa Fornitrice", "Importo Totale", "Data Scadenza"])
        ws.append(["Mario Rossi", "Acme S.r.l.", "150.000 €", "15/10/2026"])
        ws.append(["Luigi Verdi", "Beta S.p.A.", "45.000 €", "20/12/2026"])
        wb_io = io.BytesIO()
        wb.save(wb_io)
        zf.writestr("Listino_Offerta.xlsx", wb_io.getvalue())

        # 3. Sample EML email
        eml_content = """From: Mario Rossi <mario.rossi@acme.it>
To: segreteria@beta.it
Date: Mon, 20 Oct 2026 10:00:00 +0200
Subject: Conferma accordi fornitura Acme S.r.l.

Gentili colleghi,
confermo che io, Mario Rossi, in qualità di referente per Acme S.r.l.,
ho approvato il bonifico di 150.000 € sull'IBAN IT02L1234512345000000123456.
Resto a disposizione per la firma finale in data 15/10/2026.

Cordiali saluti,
Mario Rossi
Tel: +39 335 1234567
"""
        zf.writestr("Email_Conferma.eml", eml_content.encode('utf-8'))

    zip_buffer.seek(0)
    return zip_buffer.getvalue()

def run_tests():
    print(">>> 1. Creazione archivio ZIP di prova con .docx, .xlsx e .eml...")
    zip_bytes = create_sample_zip()
    
    print(">>> 2. Test Ingestione ed Estrazione Automatica con DocumentService...")
    service = DocumentService()
    session_id = "test_session_123"
    
    res = service.add_uploaded_files(session_id, [("Pacchetto_Completo.zip", zip_bytes)])
    print(f"    - Documenti estratti: {res['document_count']}")
    for d in res['documents']:
        print(f"      * {d['filename']} (tipo: {d['file_type']}, archivio: {d['source_archive']})")

    assert res['document_count'] == 3, f"Attesi 3 file estratti dallo zip, trovati {res['document_count']}"

    print("\n>>> 3. Test Riconoscimento Entità e Pseudonimizzazione Deterministica...")
    entities = res['entities']
    print(f"    - Totale entità protette: {len(entities)}")
    
    token_mario = None
    token_luigi = None
    token_acme = None
    token_importo = None
    
    for e in entities:
        print(f"      * [{e['category']}] '{e['original']}' -> {e['token']}")
        if e['canonical'] == "mario rossi":
            token_mario = e['token']
        elif e['canonical'] == "luigi verdi":
            token_luigi = e['token']
        elif "acme s.r.l" in e['canonical']:
            token_acme = e['token']
        elif "150.000" in e['original']:
            token_importo = e['token']

    assert token_mario is not None, "Mario Rossi non trovato nelle entità!"
    assert token_luigi is not None, "Luigi Verdi (standalone in tabella Excel) non trovato nelle entità!"
    assert token_acme is not None, "Acme S.r.l. non trovata nelle entità!"
    assert token_importo is not None, "Importo 150.000 € non trovato nelle entità!"

    print("\n>>> 4. Test Coerenza del Corpus Pseudonimizzato e Verifica Assenza Residui...")
    corpus = service.get_masked_corpus(session_id)
    anonymizer = service.get_or_create_session(session_id)["anonymizer"]

    for md in corpus['masked_documents']:
        print(f"\n--- Estratto Mascherato da: {md['filename']} ---")
        preview_lines = md['masked_text'].splitlines()[:5]
        for line in preview_lines:
            print(f"    {line}")
        
        # Verify no raw PII remains
        assert "Mario Rossi" not in md['masked_text'], f"Mario Rossi trovato in chiaro in {md['filename']}!"
        assert "Luigi Verdi" not in md['masked_text'], f"Luigi Verdi trovato in chiaro in {md['filename']}!"
        assert "150.000 €" not in md['masked_text'], f"150.000 € trovato in chiaro in {md['filename']}!"
        
        # Verify no awkward trailing dots like [SOCIETA_A].
        assert f"{token_acme}." not in md['masked_text'], f"Stray dot trovato dopo il token in {md['filename']}!"

        # Pre-flight coverage check
        leaks = anonymizer.verify_masking_coverage(md['masked_text'])
        assert len(leaks) == 0, f"Rilevati residui non mascherati in {md['filename']}: {leaks}"

    print("\n>>> 5. Test Anonimizzazione del Prompt Completo (inclusi Nomi File e Query)...")
    prompt = service.build_comparison_prompt(session_id, "Confronta il contratto di Mario Rossi con l'offerta per Acme S.r.l.")
    assert "Mario Rossi" not in prompt, "Mario Rossi presente nel prompt (leak nel filename o nella query)!"
    assert "Acme S.r.l." not in prompt, "Acme S.r.l. presente nel prompt!"
    print("    - Prompt verificato: metadati dei file e istruzione utente debitamente pseudonimizzati.")

    print("\n>>> 6. Test De-anonimizzazione del Risultato (Simulazione Output LLM)...")
    mock_llm_response = f"""
Sintesi del confronto tra i documenti:
1. In tutti i file, {token_mario} agisce per conto di {token_acme}.
2. L'importo concordato sia nel contratto Word, sia nel foglio Excel che nell'email è esattamente {token_importo}.
3. Per quanto riguarda {token_luigi}, il corrispettivo è differente.
4. Non risultano discrepanze tra le parti.
"""
    processed = service.process_llm_response(session_id, mock_llm_response)
    restored = processed['deanonymized_response']
    print("--- Risposta Decifrata Restituita all'Utente ---")
    print(restored.strip())

    assert "Mario Rossi" in restored, "Mario Rossi non ripristinato!"
    assert "Luigi Verdi" in restored, "Luigi Verdi non ripristinato!"
    assert "Acme S.r.l." in restored, "Acme S.r.l. non ripristinata!"
    assert token_mario not in restored, f"Il token {token_mario} è ancora presente nella risposta finale!"

    print("\n>>> 7. Test Generazione Report Word (.docx)...")
    docx_stream = service.export_report_docx(session_id)
    assert len(docx_stream.getvalue()) > 1000, "File Word non generato correttamente!"
    print(f"    - File Word generato con successo ({len(docx_stream.getvalue())} bytes)")

    print("\n[OK] TUTTI I TEST (INCLUSI TEST DI COPERTURA E CASI NEGATIVI) SUPERATI AL 100%!")

if __name__ == "__main__":
    run_tests()
