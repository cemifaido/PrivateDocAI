import unittest
from backend.anonymizer import DeterministicAnonymizer

class TestLegalAndEnglishPseudonymization(unittest.TestCase):

    def setUp(self):
        self.anonymizer = DeterministicAnonymizer()

    def test_italian_corporate_forms_and_aliases(self):
        pleading = """
        Tribunale Ordinario di Milano - Sezione Specializzata in Materia di Impresa.
        Nel giudizio promosso da Alfaservizi s.r.l. società benefit (d’ora in avanti, “Alfaservizi”),
        rappresentata dall'Avv. Luca Bianchi e Marco de Santis,
        contro Betamedia s.r.l. (in prosieguo “Betamedia”) e Gammassicura Assicurazioni s.p.a. (“Gammassicura”).
        Con la chiamata in causa di Delta Insurance Europe SE (“Delta”).
        Si produce relazione tecnica di Epsilon Advisory s.r.l. (“Epsilon”) e Zeta Business Services s.r.l.
        Difesi da Studio Rossetti Valli e Associati e Studio Legale Omega.
        Alfaservizi contesta l'inadempimento di Betamedia. Delta eccepisce l'inoperatività della polizza.
        Gammassicura ha liquidato la somma di 150.000,00 € in data 15 ottobre 2026.
        Epsilon conferma le stime patrimoniali.
        """
        doc = {"filename": "memoria_difensiva.docx", "text": pleading}
        self.anonymizer.analyze_documents([doc])
        masked = self.anonymizer.mask_text(pleading)

        # Ensure all companies and their base brands are masked
        self.assertNotIn("Alfaservizi", masked)
        self.assertNotIn("Betamedia", masked)
        self.assertNotIn("Gammassicura", masked)
        self.assertNotIn("Delta", masked)
        self.assertNotIn("Epsilon", masked)
        self.assertNotIn("Zeta", masked)
        self.assertNotIn("Studio Legale Omega", masked)
        self.assertNotIn("Studio Rossetti Valli e Associati", masked)

        # Ensure amounts and dates are masked
        self.assertNotIn("150.000,00 €", masked)
        self.assertNotIn("15 ottobre 2026", masked)

        # De-anonymization recovers original text
        restored = self.anonymizer.de_anonymize_text(masked)
        self.assertIn("Alfaservizi", restored)
        self.assertIn("Betamedia", restored)
        self.assertIn("Delta", restored)
        self.assertIn("Epsilon", restored)

    def test_english_legal_contract_and_translation(self):
        contract_en = """
        THIS SERVICES AGREEMENT is made on October 25, 2026, by and between:
        Global Tech Solutions Inc. (hereinafter referred to as "Global Tech"), a Delaware corporation,
        and Smith & Partners Law Firm LLP, represented by John Smith, Esq.
        Total compensation payable shall be $ 75,000.00 upon milestone completion.
        Global Tech shall provide the deliverables directly to John Smith.
        """
        doc = {"filename": "agreement_en.docx", "text": contract_en}
        self.anonymizer.analyze_documents([doc])
        masked_en = self.anonymizer.mask_text(contract_en)

        # Companies & aliases masked
        self.assertNotIn("Global Tech Solutions Inc", masked_en)
        self.assertNotIn("Global Tech", masked_en)
        self.assertNotIn("Smith & Partners Law Firm LLP", masked_en)
        self.assertNotIn("John Smith", masked_en)
        self.assertNotIn("$ 75,000.00", masked_en)
        self.assertNotIn("October 25, 2026", masked_en)

        # Simulate LLM Translation to Italian keeping tokens intact
        translated_llm_response = (
            "IL PRESENTE CONTRATTO DI SERVIZI è stipulato in data [DATA_A], tra:\n"
            "[SOCIETA_A], società costituita secondo il diritto del Delaware,\n"
            "e lo studio legale [SOCIETA_B], rappresentato dall'Avv. [PERSONA_1].\n"
            "Il corrispettivo totale dovuto è pari a [IMPORTO_1] al raggiungimento degli obiettivi contrattuali.\n"
            "[SOCIETA_A] fornirà i prodotti concordati direttamente a [PERSONA_1]."
        )

        decrypted_it = self.anonymizer.de_anonymize_text(translated_llm_response)
        self.assertIn("Global Tech Solutions Inc", decrypted_it)
        self.assertIn("Smith & Partners Law Firm LLP", decrypted_it)
        self.assertIn("John Smith", decrypted_it)
        self.assertIn("$ 75,000.00", decrypted_it)
        self.assertIn("October 25, 2026", decrypted_it)

    def test_preflight_suspects_and_quick_protect(self):
        text = "L'udienza è stata fissata dal giudice. Tuttavia BrandSconosciuto non compare nei registri."
        doc = {"filename": "atto.txt", "text": text}
        self.anonymizer.analyze_documents([doc])
        masked = self.anonymizer.mask_text(text)

        # "BrandSconosciuto" is flagged as suspect because it is capitalized and not in stopwords
        suspects = self.anonymizer.find_unmasked_suspects(masked)
        self.assertIn("BrandSconosciuto", suspects)

        # User quick-protects "BrandSconosciuto" as SOCIETA
        self.anonymizer.add_custom_entity("BrandSconosciuto", "SOCIETA")
        re_masked = self.anonymizer.mask_text(text)
        self.assertNotIn("BrandSconosciuto", re_masked)
        self.assertIn("[SOCIETA_", re_masked)

if __name__ == "__main__":
    unittest.main()
