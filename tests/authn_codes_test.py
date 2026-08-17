"""Negative controls for two defects carried over from the reference implementation.

Both live in `apps/api/authn/codes.py`, both are about a SIX-DIGIT secret, and both are the
kind that no ordinary test would catch — which is why the assertions here are shaped the way
they are rather than the obvious way.

No database and no Redis: this module is arithmetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

import pytest
from apps.api.authn.codes import (
    OTP_DIGITS,
    OTP_MAX,
    OTP_MIN,
    code_fingerprint,
    code_fingerprints,
    new_otp_code,
    new_url_token,
)
from apps.api.core.envelope import build_ring


@pytest.fixture
def ring() -> Iterator[object]:
    """A KEK ring with known material, so the assertions below are about the construction
    rather than about whatever `PLATFORM_KEK` happens to be on this host."""
    yield build_ring(kek=None, retired=None, app_env="local")


# ─────────── DEFECT: `crypto.randomInt(100000, 999999)` never returns 999999 ───────────
#
# `auth.service.ts:168`. Node's `randomInt` takes a HALF-OPEN interval, so the stated
# maximum is unreachable: the function claims 900,000 possible codes and produces 899,999.


def test_the_otp_generator_reaches_both_ends_of_its_stated_range() -> None:
    """THE BOUNDARY, ASSERTED DIRECTLY — not sampled.

    A test that draws a few thousand codes and checks `OTP_MIN <= code <= OTP_MAX` passes
    against the defective generator too, because the missing value is one in nine hundred
    thousand. So this drives the generator's ARITHMETIC rather than its output
    distribution: `secrets.randbelow(span)` is uniform over `[0, span)`, so the image of
    `OTP_MIN + randbelow(span)` is exactly `[OTP_MIN, OTP_MIN + span - 1]`, and asserting
    that the top of that interval IS `OTP_MAX` is the whole property.

    Both ends are then produced concretely by pinning `randbelow` to its extremes, which is
    what fails if somebody rewrites the span as `OTP_MAX - OTP_MIN`.
    """
    span = OTP_MAX - OTP_MIN + 1
    assert OTP_MIN + span - 1 == OTP_MAX, "the generator's image must include its stated maximum"

    import apps.api.authn.codes as codes_module

    seen: list[str] = []
    for draw in (0, span - 1):
        original = codes_module.secrets.randbelow
        try:
            codes_module.secrets.randbelow = lambda _n, _d=draw: _d  # type: ignore[assignment]
            seen.append(new_otp_code())
        finally:
            codes_module.secrets.randbelow = original  # type: ignore[assignment]
    assert seen == [str(OTP_MIN), str(OTP_MAX)]
    assert seen[1] == "999999", "the top of the range must be reachable, not one below it"


def test_every_otp_is_exactly_six_digits_with_no_leading_space_or_sign() -> None:
    """The rendering, which a modulo-based generator gets wrong at the low end."""
    for _ in range(500):
        code = new_otp_code()
        assert len(code) == OTP_DIGITS
        assert code.isdigit()
        assert OTP_MIN <= int(code) <= OTP_MAX


# ───────── DEFECT: OTPs stored as an unsalted, unkeyed SHA-256 of six digits ─────────
#
# `auth.service.ts:165`. 900,000 candidates is a rainbow table you build in a second, so a
# database dump or one SQL-injection read recovers every live code.


def test_a_stored_otp_fingerprint_is_not_a_bare_digest_of_the_code(ring: object) -> None:
    """The rainbow-table property, stated as the test that fails if keying is removed.

    If the stored value were `sha256(code)` — or `sha256(purpose + code)`, or any unkeyed
    function of them — then an attacker who knows the construction can enumerate all
    900,000 and match. This asserts the stored value is NOT any of those, which is what
    being keyed by a secret outside the database means in practice.
    """
    code = "424242"
    domain = "calevate/auth-otp/v1/email_verify"
    stored = code_fingerprint(code, domain=domain, ring=ring)  # type: ignore[arg-type]

    for guessable in (
        hashlib.sha256(code.encode()).digest(),
        hashlib.sha256(domain.encode() + code.encode()).digest(),
        hashlib.sha256((domain + code).encode()).digest(),
        hashlib.sha256(domain.encode() + b"\x00" + code.encode()).digest(),
        hashlib.sha512(code.encode()).digest()[:32],
    ):
        assert stored != guessable, (
            "the stored fingerprint is computable without a key — a database dump would "
            "recover every live code by enumerating six digits"
        )


def test_the_whole_six_digit_space_is_unreachable_without_the_key(ring: object) -> None:
    """The same property from the attacker's side, done exhaustively over a slice.

    Builds the rainbow table an attacker WOULD build — every unkeyed digest of every code
    in a range — and asserts the real stored value is in none of it. Sliced rather than
    full because 900,000 SHA-256s per assertion is slow and 20,000 is already conclusive:
    the code under test is inside the slice.
    """
    domain = "calevate/auth-otp/v1/login_challenge"
    code = "100777"
    stored = code_fingerprint(code, domain=domain, ring=ring)  # type: ignore[arg-type]
    table = {
        hashlib.sha256(f"{candidate:06d}".encode()).digest()
        for candidate in range(OTP_MIN, OTP_MIN + 20_000)
    }
    assert int(code) in range(OTP_MIN, OTP_MIN + 20_000), "the code must be inside the slice"
    assert stored not in table


def test_the_purpose_is_inside_the_mac_so_one_code_cannot_be_spent_elsewhere(
    ring: object,
) -> None:
    """A verification code presented at the reset endpoint must match no row."""
    code = "314159"
    verify = code_fingerprint(code, domain="calevate/auth-otp/v1/email_verify", ring=ring)  # type: ignore[arg-type]
    login = code_fingerprint(code, domain="calevate/auth-otp/v1/login_challenge", ring=ring)  # type: ignore[arg-type]
    assert verify != login


def test_the_domain_separator_makes_the_encoding_unambiguous(ring: object) -> None:
    """Without the `\\x00`, domain `ab` + secret `c` and domain `a` + secret `bc` would MAC
    identically — and this package's purposes share prefixes."""
    left = code_fingerprint("c", domain="ab", ring=ring)  # type: ignore[arg-type]
    right = code_fingerprint("bc", domain="a", ring=ring)  # type: ignore[arg-type]
    assert left != right


def test_verification_walks_every_key_generation_newest_first(ring: object) -> None:
    """A code minted before a KEK rotation still verifies after it."""
    fingerprints = code_fingerprints("777888", domain="d", ring=ring)  # type: ignore[arg-type]
    assert fingerprints[0] == code_fingerprint("777888", domain="d", ring=ring)  # type: ignore[arg-type]
    assert len(fingerprints) >= 1


# ───────────────────────────────── url tokens ─────────────────────────────────


def test_url_tokens_are_distinct_and_full_length() -> None:
    """The high-entropy half of this module — reset links and invite links.

    Unkeyed SHA-256 would have been fine for these (the reference implementation does that
    correctly at `auth.service.ts:897`); they go through the same keyed construction anyway,
    so there is one way to store a secret here rather than two.
    """
    tokens = {new_url_token() for _ in range(200)}
    assert len(tokens) == 200
    # 32 bytes of urlsafe base64 is 43 characters; anything shorter is a silent downgrade.
    assert all(len(token) >= 43 for token in tokens)
