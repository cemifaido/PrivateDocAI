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

        # Simulate LLM Translation to Italian keeping tokens intact (tokens looked up, not assumed:
        # the numbering depends on the order in which the parties are registered)
        fm = self.anonymizer.forward_map
        date_t = fm["october 25, 2026"]
        global_t = fm["global tech solutions inc"]
        firm_t = fm["smith & partners law firm llp"]
        person_t = fm["john smith"]
        amount_t = fm["$ 75,000.00"]
        translated_llm_response = (
            f"IL PRESENTE CONTRATTO DI SERVIZI è stipulato in data {date_t}, tra:\n"
            f"{global_t}, società costituita secondo il diritto del Delaware,\n"
            f"e lo studio legale {firm_t}, rappresentato dall'Avv. {person_t}.\n"
            f"Il corrispettivo totale dovuto è pari a {amount_t} al raggiungimento degli obiettivi contrattuali.\n"
            f"{global_t} fornirà i prodotti concordati direttamente a {person_t}."
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


class TestDefinedTerms(unittest.TestCase):
    """Acts define short names ("d'ora in avanti ..."): names keep ONE code, role words stay readable."""

    def setUp(self):
        self.a = DeterministicAnonymizer()

    def _mask(self, text):
        self.a.analyze_documents([{"filename": "atto.txt", "text": text}])
        return self.a.mask_text(text)

    def test_short_name_gets_the_code_of_the_defined_party(self):
        masked = self._mask("Pippo Insurance s.p.a. (d'ora in avanti “Pippo”) ha pagato. Pippo contesta. "
                            "Pippo Insurance s.p.a. risponde.")
        self.assertNotIn("Pippo", masked)
        self.assertEqual(len(set(__import__("re").findall(r"\[SOCIETA_\w+\]", masked))), 1)

    def test_unquoted_second_name_is_the_same_party_not_a_new_one(self):
        masked = self._mask("Zeta Holding s.p.a. (d'ora in avanti denominata Omega) controlla. "
                            "Omega ha deciso; Zeta Holding conferma.")
        self.assertNotIn("Omega", masked)
        self.assertNotIn("Zeta", masked)
        self.assertNotIn("PERSONA", masked)  # "Zeta Holding" without the legal form is not a person
        self.assertEqual(len(self.a.registry), 1)

    def test_role_words_stay_readable_and_never_become_entities(self):
        masked = self._mask("Pippo Enterprise s.p.a. (d'ora in avanti denominata Contraente) firma. "
                            "Delta Mutual SE (d'ora in avanti “Compagnia” o “Socio di Maggioranza”) paga. "
                            "Il Contraente e la Compagnia e il Socio di Maggioranza concordano.")
        for word in ("Contraente", "Compagnia", "Socio di Maggioranza"):
            self.assertIn(word, masked)
        self.assertEqual({r["category"] for r in self.a.registry}, {"SOCIETA"})

    def test_respectively_links_only_the_last_group_and_flags_the_rest(self):
        text = ("la polizza e Gammassicura Assicurazioni s.p.a. (d'ora in avanti, rispettivamente, “Polizza” e "
                "“Gammassicura” o “Socio di Maggioranza”) e Kappa Servizi s.r.l. (d'ora in avanti, "
                "rispettivamente, “Alfonso” e “Kappa”). Alfonso risponde.")
        masked = self._mask(text)
        self.assertNotIn("Gammassicura", masked)
        self.assertIn("Polizza", masked)                 # role word of the policy, not of the company
        self.assertIn("Alfonso", masked)                 # name-like but not tied to a party: left for the user
        self.assertIn("Alfonso", self.a.find_unmasked_suspects(masked))

    def test_acronym_matches_only_its_exact_capitals(self):
        masked = self._mask("Alfaservizi Italia s.r.l. (d'ora in avanti “TI”) ricorre. Il giudice ti dice che TI deduce.")
        self.assertIn("ti dice", masked)                 # the pronoun is untouched
        self.assertNotIn(" TI ", masked)

    def test_defined_terms_survive_save_and_reopen(self):
        text = "Zeta Holding s.p.a. (d'ora in avanti denominata Omega) controlla. Omega decide."
        masked = self._mask(text)
        reopened = DeterministicAnonymizer.from_dict(self.a.to_dict())
        self.assertEqual(reopened.mask_text(text), masked)
        self.assertIn("omega", reopened._defined["atto.txt"])  # kept per document

    def test_a_term_chosen_by_the_user_is_not_taken_over(self):
        self.a.add_custom_entity("Omega", "PERSONA")
        user_token = self.a.forward_map["omega"]
        self._mask("Zeta Holding s.p.a. (d'ora in avanti denominata Omega) controlla.")
        self.assertEqual(self.a.forward_map["omega"], user_token)


class TestDefinitionFormulasAndScope(unittest.TestCase):
    """More ways acts introduce a short name, and aliases that belong to ONE document."""

    def _analyse(self, *texts):
        a = DeterministicAnonymizer()
        docs = [{"id": f"d{i}", "filename": f"d{i}.txt", "text": t} for i, t in enumerate(texts)]
        a.analyze_documents(docs)
        return a, [a.mask_text(t, doc_key=f"d{i}") for i, t in enumerate(texts)]

    def test_inline_definition_without_parentheses(self):
        _, (masked,) = self._analyse(
            "Kappa Servizi s.r.l., di seguito “Kappa”, ha agito. Poi Kappa ha pagato.")
        self.assertNotIn("Kappa", masked)

    def test_more_introducers(self):
        for formula in ("per brevità", "nel seguito", "in appresso", "qui di seguito", "nel prosieguo anche"):
            _, (masked,) = self._analyse(
                f"Lambda Costruzioni s.r.l. ({formula} “Lambda”) firma. Lambda paga.")
            self.assertNotIn("Lambda", masked, formula)

    def test_acronym_in_parentheses_or_with_sigla(self):
        for text in ("Tecnologie Italiane S.p.A. (TI) ricorre. TI deduce.",
                     "Tecnologie Italiane S.p.A., con sigla TI, ricorre. TI deduce."):
            _, (masked,) = self._analyse(text)
            self.assertNotIn("TI", masked.replace("[", "").replace("]", ""), text)

    def test_a_defined_name_belongs_to_its_own_document(self):
        a, (doc_a, doc_b) = self._analyse(
            "Zeta Holding s.p.a. (d'ora in avanti denominata Omega) controlla. Omega ha deciso.",
            "In questo altro atto Omega è un'azienda diversa e Omega risponde.")
        self.assertNotIn("Omega", doc_a)
        self.assertIn("Omega", doc_b)                     # not defined here: not guessed
        self.assertIn("Omega", a.find_unmasked_suspects(doc_b))  # but the user is told

    def test_removing_a_document_drops_its_definitions(self):
        a, _ = self._analyse("Zeta Holding s.p.a. (d'ora in avanti denominata Omega) controlla.")
        self.assertNotIn("Omega", a.mask_text("Omega ha deciso.", doc_key="d0"))
        a.forget_document("d0")
        self.assertIn("Omega", a.mask_text("Omega ha deciso.", doc_key="d0"))
        self.assertEqual(a._defined, {})

    def test_new_reference_types_are_recognised(self):
        text = ("R.G. n. 2210/2026; polizza n. ABC-123456; Foglio 21, particella 345, sub. 6; CIG 8745123ABC; "
                "carta d'identità n. CA12345AB; telaio ZFA19900000123456; BIC UNCRITMM; matricola n. A-4521.")
        a, (masked,) = self._analyse(text)
        for value in ("2210/2026", "ABC-123456", "Foglio 21", "8745123ABC", "CA12345AB",
                      "ZFA19900000123456", "UNCRITMM", "A-4521"):
            self.assertNotIn(value, masked)
        self.assertNotIn("TELEFONO", masked)              # digits inside the VIN are not a phone number

    def test_plain_words_after_a_keyword_are_not_references(self):
        a, (masked,) = self._analyse("La pratica legale è chiusa. Protocollo 7. La patente di guida è valida.")
        self.assertEqual(a.registry, [])

if __name__ == "__main__":
    unittest.main()
