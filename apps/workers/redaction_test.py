"""Redaction behaviour tests — one file per behaviour (BACKEND-PATTERNS §9).

These are compliance tests, not unit-test hygiene: `text_redacted` is what every API
response returns by default (hard rule 5), so a false negative here is a PII leak and
a false positive silently destroys the transcript a client paid for.
"""

from __future__ import annotations

from apps.workers.redaction import is_valid_aadhaar, is_valid_luhn, redact, spoken_digit_runs

# Verhoeff-valid Aadhaar-shaped test number (not a real allocation).
VALID_AADHAAR = "234123412346"
VALID_CARD = "4111111111111111"  # Luhn-valid Visa test number


def test_valid_aadhaar_is_redacted() -> None:
    result = redact(f"Naa aadhaar {VALID_AADHAAR} andi")
    assert VALID_AADHAAR not in result.text
    assert "aadhaar" in result.kinds


def test_twelve_digits_that_fail_verhoeff_survive() -> None:
    """A booking reference is not an Aadhaar. Without the checksum every long number
    in every transcript would be destroyed."""
    not_aadhaar = "234123412345"
    assert not is_valid_aadhaar(not_aadhaar)
    assert not_aadhaar in redact(f"Reference {not_aadhaar}").text


def test_luhn_valid_card_is_redacted_and_invalid_one_is_not() -> None:
    assert is_valid_luhn(VALID_CARD)
    assert VALID_CARD not in redact(f"card {VALID_CARD}").text
    assert "4111111111111112" in redact("card 4111111111111112").text


def test_pan_shape_is_redacted() -> None:
    result = redact("PAN ABCDE1234F kavali")
    assert "ABCDE1234F" not in result.text
    assert "pan" in result.kinds


def test_indian_mobile_keeps_only_last_two_digits() -> None:
    """Staff must still be able to recognise the caller they are looking at, so the
    mask keeps two digits and nothing else."""
    result = redact("Naa number 9876543210 andi")
    assert "9876543210" not in result.text
    assert "••10" in result.text


def test_a_grouped_number_is_still_one_number() -> None:
    """The mask survives the widening: separators change the spelling, not the tail.

    `PHONE_MASK` keeps the last two NATIONAL digits, and the widened matcher has to
    recover those from a number whose digits are split across groups — `9876-543-210`
    ends in a group of three, so a naive "last two characters of the match" would print
    `••10` only by luck and `••89` for a landline written `040-23456789` not at all.
    """
    assert redact("Naa number 98765 43210 andi").text == "Naa number [phone ••10] andi"
    assert redact("9876-543-210 ki call cheyandi").text == "[phone ••10] ki call cheyandi"
    assert redact("clinic 040-23456789").text == "clinic [phone ••89]"


def test_the_earlier_validated_patterns_still_win_over_the_wider_phone_rule() -> None:
    """Order of the pass is load-bearing and the widening did not disturb it.

    Aadhaar and card substitution run BEFORE phone precisely so a 12- or 16-digit number
    is classified by its checksum rather than by its shape. Both are written in groups in
    real life, which is exactly the spelling the phone rule now also accepts, so this
    pins that the checksummed rules still get there first — an Aadhaar redacted as a
    phone would leak its last two digits.
    """
    aadhaar = redact("aadhaar 2341 2341 2346 andi")
    assert VALID_AADHAAR[-2:] not in aadhaar.text
    assert aadhaar.kinds == ["aadhaar"], aadhaar.kinds

    card = redact("card 4111 1111 1111 1111")
    assert card.kinds == ["card"], card.kinds
    assert "••11" not in card.text


def test_otp_is_redacted_even_though_it_is_short() -> None:
    result = redact("Mee OTP 458213 chepandi")
    assert "458213" not in result.text
    assert "otp" in result.kinds


def test_spoken_digits_in_english_and_telugu_are_caught() -> None:
    """The case a regex alone cannot see — callers read numbers aloud, code-mixed."""
    runs = spoken_digit_runs("naa number nine eight seven six tommidi enimidi andi")
    assert runs, "a six-word digit run must be detected"
    assert runs[0][2] == "987698"

    result = redact("number nine eight seven six five four three two one zero")
    assert "spoken_digits" in result.kinds


def test_spoken_digits_in_hindi_are_caught_too() -> None:
    """The leak this replaces: Telugu was mapped and Hindi was not, so the SAME caller
    reading the SAME number was masked in one language and printed in the other — into
    `text_redacted`, the field every API response defaults to. Found by the red-team
    eval set, not by inspection, because nothing in the tree stated the map's scope.
    """
    result = redact("mera number nau nau aath saat chhe paanch chaar teen do ek hai")
    assert "spoken_digits" in result.kinds
    assert "nau nau" not in result.text

    # Transliteration is not standardised, so the common variants map to the same digit.
    assert spoken_digit_runs("tin char panch che sat ath")[0][2] == "345678"


def test_a_run_of_refusals_is_not_mistaken_for_a_number() -> None:
    """`no` is a colloquial nine and is deliberately unmapped. Six of the other English
    collisions in a row means somebody is reading out a number; six `no`s means somebody
    is saying no — and masking that turn would hide the sentence a DNC opt-out lives in.
    """
    assert not spoken_digit_runs("no no no no no no mujhe nahi chahiye")
    assert not spoken_digit_runs("do you want me to do this or do that")


def test_short_number_words_are_left_alone() -> None:
    """'rendu three o'clock' is speech, not a phone number."""
    assert not spoken_digit_runs("rendu three o'clock ki vasthanu")


def test_email_and_upi_are_redacted() -> None:
    result = redact("mail ravi@example.com or pay ravi@okaxis")
    assert "ravi@example.com" not in result.text
    assert "ravi@okaxis" not in result.text


def test_clean_transcript_is_untouched() -> None:
    clean = "Namaskaram, ee roju evening 6 gantalaku doctor available unnaru."
    result = redact(clean)
    assert result.text == clean
    assert not result.changed
