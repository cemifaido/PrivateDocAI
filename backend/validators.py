"""Pure, dependency-free validators for structured identifiers.

The checks in this module establish formal validity only.  They do not prove
that an identifier was assigned or that it belongs to a particular subject.

References:
- SWIFT IBAN Registry, release 103 (September 2026), and ISO 13616/7064.
- Italian Ministry of Finance decree of 23 December 1976, articles 7 and 9
  (tax-code structure and check character).
"""

import re


# Fixed national lengths from the SWIFT ISO 13616 IBAN Registry, release 103.
# Keeping this table explicit also rejects plausible-looking identifiers for
# countries that have not registered an IBAN format.
_IBAN_LENGTHS = {
    "AD": 24,
    "AE": 23,
    "AL": 28,
    "AT": 20,
    "AZ": 28,
    "BA": 20,
    "BE": 16,
    "BG": 22,
    "BH": 22,
    "BI": 27,
    "BR": 29,
    "BY": 28,
    "CH": 21,
    "CR": 22,
    "CY": 28,
    "CZ": 24,
    "DE": 22,
    "DJ": 27,
    "DK": 18,
    "DO": 28,
    "EE": 20,
    "EG": 29,
    "ES": 24,
    "FI": 18,
    "FK": 18,
    "FO": 18,
    "FR": 27,
    "GB": 22,
    "GE": 22,
    "GI": 23,
    "GL": 18,
    "GR": 27,
    "GT": 28,
    "HN": 28,
    "HR": 21,
    "HU": 28,
    "IE": 22,
    "IL": 23,
    "IQ": 23,
    "IS": 26,
    "IT": 27,
    "JO": 30,
    "KW": 30,
    "KZ": 20,
    "LB": 28,
    "LC": 32,
    "LI": 21,
    "LT": 20,
    "LU": 20,
    "LV": 21,
    "LY": 25,
    "MC": 27,
    "MD": 24,
    "ME": 22,
    "MK": 19,
    "MN": 20,
    "MR": 27,
    "MT": 31,
    "MU": 30,
    "NI": 28,
    "NL": 18,
    "NO": 15,
    "OM": 23,
    "PK": 24,
    "PL": 28,
    "PS": 29,
    "PT": 25,
    "QA": 29,
    "RO": 24,
    "RS": 22,
    "RU": 33,
    "SA": 24,
    "SC": 31,
    "SD": 18,
    "SE": 24,
    "SI": 19,
    "SK": 24,
    "SM": 27,
    "SO": 23,
    "ST": 25,
    "SV": 28,
    "TL": 23,
    "TN": 24,
    "TR": 26,
    "UA": 29,
    "VA": 22,
    "VG": 24,
    "XK": 20,
    "YE": 30,
}

_CF_PATTERN = re.compile(
    r"^[A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST]"
    r"[0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]$"
)

# Values assigned by the decree to characters in odd positions (1-based).
_CF_ODD_VALUES = {
    **dict(zip("0123456789", (1, 0, 5, 7, 9, 13, 15, 17, 19, 21))),
    **dict(
        zip(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            (
                1,
                0,
                5,
                7,
                9,
                13,
                15,
                17,
                19,
                21,
                2,
                4,
                18,
                20,
                11,
                3,
                6,
                8,
                12,
                14,
                16,
                10,
                22,
                25,
                24,
                23,
            ),
        )
    ),
}


def is_valid_iban(value: object) -> bool:
    """Return whether *value* has a registered length and a valid MOD-97 checksum.

    Both electronic form and the usual whitespace-separated print form are
    accepted.  Punctuation and non-ASCII alphanumeric characters are rejected.
    """
    if not isinstance(value, str):
        return False
    iban = "".join(value.split()).upper()
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]+", iban):
        return False
    if len(iban) != _IBAN_LENGTHS.get(iban[:2]):
        return False

    remainder = 0
    for character in iban[4:] + iban[:4]:
        digits = (
            character if character.isdigit() else str(ord(character) - ord("A") + 10)
        )
        for digit in digits:
            remainder = (remainder * 10 + int(digit)) % 97
    return remainder == 1


def is_valid_codice_fiscale(value: object) -> bool:
    """Return whether a 16-character Italian personal tax code is well formed.

    Omocodia letters are accepted in all seven numeric positions.  This is a
    structural/check-character validation, not an Anagrafe Tributaria lookup.
    """
    if not isinstance(value, str):
        return False
    code = value.strip().upper()
    if not _CF_PATTERN.fullmatch(code):
        return False

    total = 0
    for index, character in enumerate(code[:15]):
        if index % 2 == 0:
            total += _CF_ODD_VALUES[character]
        elif character.isdigit():
            total += int(character)
        else:
            total += ord(character) - ord("A")
    return code[-1] == chr(ord("A") + total % 26)


def is_valid_partita_iva(value: object) -> bool:
    """Return whether an Italian VAT number has a valid check digit.

    The optional ``IT`` prefix is accepted.  Assignment and current activity
    can only be established through the official registry service.
    """
    if not isinstance(value, str):
        return False
    number = value.strip().upper()
    if number.startswith("IT"):
        number = number[2:]
    if not re.fullmatch(r"[0-9]{11}", number) or len(set(number)) == 1:
        return False

    total = sum(int(number[index]) for index in range(0, 10, 2))
    for index in range(1, 10, 2):
        doubled = int(number[index]) * 2
        total += doubled - 9 if doubled > 9 else doubled
    expected = (10 - total % 10) % 10
    return int(number[-1]) == expected


__all__ = ["is_valid_iban", "is_valid_codice_fiscale", "is_valid_partita_iva"]
