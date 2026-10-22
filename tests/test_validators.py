import unittest

from backend.validators import (
    is_valid_codice_fiscale,
    is_valid_iban,
    is_valid_partita_iva,
)


class TestIbanValidator(unittest.TestCase):
    def test_accepts_valid_electronic_and_print_forms(self):
        self.assertTrue(is_valid_iban("IT60X0542811101000000123456"))
        self.assertTrue(is_valid_iban("gb82 west 1234 5698 7654 32"))

    def test_rejects_bad_checksum(self):
        self.assertFalse(is_valid_iban("IT61X0542811101000000123456"))

    def test_rejects_wrong_country_length_and_unknown_country(self):
        self.assertFalse(is_valid_iban("IT60X054281110100000012345"))
        self.assertFalse(is_valid_iban("ZZ12ABCDEFGHIJKLM"))

    def test_rejects_punctuation_and_non_string_values(self):
        self.assertFalse(is_valid_iban("IT60-X0542811101000000123456"))
        self.assertFalse(is_valid_iban(None))


class TestCodiceFiscaleValidator(unittest.TestCase):
    def test_accepts_synthetic_code_and_normalizes_case(self):
        self.assertTrue(is_valid_codice_fiscale(" abcdef00a00h000k "))

    def test_accepts_omocodia_letters_in_numeric_positions(self):
        self.assertTrue(is_valid_codice_fiscale("ABCDEFLMANNHPLLV"))

    def test_rejects_wrong_check_character(self):
        self.assertFalse(is_valid_codice_fiscale("ABCDEF00A00H000A"))

    def test_rejects_bad_shape_or_wrong_omocodia_position(self):
        self.assertFalse(is_valid_codice_fiscale("ABCDEF00Z00H000I"))
        self.assertFalse(is_valid_codice_fiscale("ABCDEF00A00H00AI"))
        self.assertFalse(is_valid_codice_fiscale("ABCDEF00A00H000"))

    def test_rejects_non_string_values(self):
        self.assertFalse(is_valid_codice_fiscale(None))


class TestPartitaIvaValidator(unittest.TestCase):
    def test_accepts_synthetic_number_with_optional_country_prefix(self):
        self.assertTrue(is_valid_partita_iva("12345678903"))
        self.assertTrue(is_valid_partita_iva(" it12345678903 "))

    def test_rejects_wrong_check_digit_and_bad_shape(self):
        self.assertFalse(is_valid_partita_iva("12345678904"))
        self.assertFalse(is_valid_partita_iva("1234567890"))
        self.assertFalse(is_valid_partita_iva("IT12345A78903"))

    def test_rejects_degenerate_or_non_string_values(self):
        self.assertFalse(is_valid_partita_iva("00000000000"))
        self.assertFalse(is_valid_partita_iva(None))


if __name__ == "__main__":
    unittest.main()
