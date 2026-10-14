"""The password policy (`apps/api/authn/policy.py`).

The standard is quoted in that module with its source (usnistgov/800-63-4 @
4f2487bb81adecdc84ccaac6920bf0b500b379ae, `sp800-63b/authenticators/index.html`, read
2026-08-26). The length floor is 8 on every realm by founder decision (D-765); the rest
follows SP 800-63B-4 §3.1.1.2: a whole-password blocklist with a reason, NFC
normalization, code-point counting, no composition rules.
"""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from pathlib import Path

import pytest
from apps.api.authn import policy
from apps.api.authn.credentials import authenticate_subject, set_password
from apps.api.authn.hashing import (
    MAX_PASSWORD_CHARS,
    hash_password_blocking,
    verify_password_blocking,
)
from apps.api.authn.models import AUTHN_REALMS
from apps.api.core.errors import ProblemError
from apps.api.db.session import credential_session, untenanted_session
from sqlalchemy import text

# Long enough for every realm's floor and not a blocklist entry — the baseline these
# tests vary one thing away from.
GOOD_PASSWORD = "harbour-lantern-rhubarb"


# ── the floor ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("realm", AUTHN_REALMS)
def test_eight_characters_is_enough_on_every_realm(realm: str) -> None:
    """D-765: eight characters, not on the blocklist, is accepted on client and admin."""
    assert policy.min_password_chars(realm) == 8
    policy.assert_password_allowed("rhubarb9", realm=realm)


@pytest.mark.parametrize("realm", AUTHN_REALMS)
def test_seven_characters_is_refused_with_the_floor_in_the_message(realm: str) -> None:
    with pytest.raises(ProblemError) as caught:
        policy.assert_password_allowed("rhubarb", realm=realm)
    assert caught.value.code == "password_length"
    assert str(policy.min_password_chars(realm)) in caught.value.detail


def test_the_ceiling_is_unchanged_and_is_still_refused_above() -> None:
    """§3.1.1.2 asks verifiers to "permit a maximum password length of at least 64
    characters". 128 clears that; what is asserted here is that the bound still bites,
    since an unbounded password on an unauthenticated route is a free CPU sink."""
    # Not a repeated unit: `"q" * 128` clears the length bound and is then refused by the
    # blocklist, which would make this test pass for the wrong reason.
    at_ceiling = ("harbour-lantern-rhubarb-oxen-" * 8)[:MAX_PASSWORD_CHARS]
    assert len(at_ceiling) == MAX_PASSWORD_CHARS
    policy.assert_password_allowed(at_ceiling, realm="client")
    with pytest.raises(ProblemError) as caught:
        policy.assert_password_allowed(at_ceiling + "x", realm="client")
    assert caught.value.code == "password_length"


def test_an_unknown_realm_raises_rather_than_defaulting() -> None:
    """A default would be a silent guess about whether a second factor exists, which is
    the guess that exempts a new realm from the SHALL."""
    with pytest.raises(ValueError):
        policy.min_password_chars("partner")


# ── the blocklist ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "password",
    [
        "calevate2026!!!!",  # the service name, decorated to reach the floor
        "calevate________",
        "qwertyuiopasdfghjkl",  # a walk along the keyboard
        "1234567890123456",
        "abcdefghijklmnopqrst",
        "aaaaaaaaaaaaaaaaa",  # one unit repeated
        "abcabcabcabcabcabc",
    ],
)
def test_a_guessable_password_is_refused_with_a_reason(password: str) -> None:
    """§3.1.1.2: "If the chosen password is found on the blocklist, the CSP SHALL require
    the subscriber to select a different secret and SHALL provide the reason for
    rejection." Every one of these clears the length floor, so before the blocklist
    existed every one of them was accepted."""
    with pytest.raises(ProblemError) as caught:
        policy.assert_password_allowed(password, realm="client")
    assert caught.value.code == "password_unacceptable"
    # The reason is required, and it must reach the field so the form can show it.
    assert caught.value.fields, "SHALL provide the reason for rejection"
    assert caught.value.fields[0]["message"]
    # And guidance, which the same paragraph also requires.
    assert caught.value.remediation


@pytest.mark.parametrize("realm", AUTHN_REALMS)
@pytest.mark.parametrize("password", ["password", "iloveyou", "Sunshine1", "PASSWORD1"])
def test_a_common_password_is_refused_on_every_realm(realm: str, password: str) -> None:
    """The corpus is compared whole and casefolded, so a capital does not slip past it."""
    with pytest.raises(ProblemError) as caught:
        policy.assert_password_allowed(password, realm=realm)
    assert caught.value.code == "password_unacceptable"
    assert caught.value.fields
    assert "most common passwords" in caught.value.fields[0]["message"]


def test_the_corpus_is_compared_whole_not_as_substrings() -> None:
    """`password` is listed; a passphrase that merely contains it is not."""
    assert "password" in policy.COMMON_PASSWORDS
    policy.assert_password_allowed("password-for-the-harbour-office", realm="client")


def test_the_loader_drops_entries_below_the_lowest_floor(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.txt"
    corpus.write_bytes("short\nCAFÉ-AU-LAIT\nlongenough\n".encode())
    digest = hashlib.sha256(corpus.read_bytes()).hexdigest()

    loaded = policy.load_common_passwords(corpus, sha256=digest)

    assert loaded == frozenset({unicodedata.normalize("NFC", "café-au-lait"), "longenough"})


def test_the_loader_refuses_a_corpus_that_does_not_match_its_pin(tmp_path: Path) -> None:
    """An edited or truncated copy must stop the api, not quietly match less."""
    corpus = tmp_path / "corpus.txt"
    corpus.write_bytes(b"longenough\n")
    with pytest.raises(RuntimeError, match="pinned sha256"):
        policy.load_common_passwords(corpus, sha256="0" * 64)


def test_the_users_own_address_is_context_the_blocklist_knows() -> None:
    """NIST names "the username, and derivatives thereof" among what a blocklist holds.
    The address is the only identifier this product signs anyone in with."""
    with pytest.raises(ProblemError):
        policy.assert_password_allowed(
            "ramesh.kumar99", realm="client", email="ramesh.kumar@sunrisedental.in"
        )
    with pytest.raises(ProblemError):
        policy.assert_password_allowed(
            "sunrisedental2026", realm="client", email="ramesh.kumar@sunrisedental.in"
        )


@pytest.mark.parametrize(
    "password",
    [
        "correct-horse-battery-staple",
        "calevate-is-where-i-work",  # CONTAINS the service name and is fine
        "my-qwerty-keyboard-broke",  # CONTAINS a keyboard run and is fine
        "ramesh-took-the-bus-home",  # CONTAINS the local part and is fine
        "CalevateDev!2026",  # what `scripts/seed_dev.py` installs
    ],
)
def test_a_passphrase_that_merely_contains_a_blocked_word_is_allowed(password: str) -> None:
    """THE OTHER HALF OF THE SHALL, and the half that makes blocklists tolerable.

    "The entire password SHALL be subject to comparison, not substrings or words that
    might be contained therein." A containment check would refuse every passphrase here
    — and refusing `calevate-is-where-i-work-now` is precisely the behaviour that teaches
    people to type `Password1!` instead.
    """
    policy.assert_password_allowed(password, realm="client", email="ramesh.kumar@sunrisedental.in")


def test_a_short_domain_label_is_not_treated_as_context() -> None:
    """`in` would otherwise make every decorated two-letter string a refusal, which is
    noise rather than defence."""
    policy.assert_password_allowed("in-the-back-garden", realm="client", email="x@shop.co.in")


# ── normalization ────────────────────────────────────────────────────────────


def test_the_two_unicode_spellings_of_one_passphrase_are_one_password() -> None:
    """§3.1.1.2: the normalization "is applied before hashing the byte string that
    represents the password".

    `é` has two encodings — precomposed U+00E9, and `e` + U+0301 — and an Android IME and
    a desktop keyboard can produce different ones for the same keystrokes. Before this,
    the two were different passwords and the person could not sign in from their phone.
    """
    composed = "café-lantern-rhubarb"
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed, "the fixture must actually differ in encoding"

    stored = hash_password_blocking(composed)
    assert verify_password_blocking(decomposed, stored).ok


def test_normalization_is_nfc_and_not_the_compatibility_form() -> None:
    """NFC, not NFKC — the -4 revision names NFC and the -3 revision named NFKC.

    The difference matters on this product: NFKC is the COMPATIBILITY composition, which
    rewrites characters rather than merely composing canonical equivalents. `ﬁ` (U+FB01)
    and `fi` are DIFFERENT passwords under NFC and the same one under NFKC.
    """
    ligature = "ﬁreside-lantern-rhubarb"
    spelled = "fireside-lantern-rhubarb"
    assert unicodedata.normalize("NFKC", ligature) == spelled
    stored = hash_password_blocking(ligature)
    assert not verify_password_blocking(spelled, stored).ok


def test_length_is_counted_in_code_points() -> None:
    """ "Each Unicode code point SHALL be counted as a single character when evaluating
    password length" (§3.1.1.2). Eight astral-plane characters is eight, not 32 bytes;
    seven is seven, and short."""
    # DISTINCT characters: a repeated one would clear the length rule and then be refused
    # as a repetition, proving nothing about the count.
    eight = "🙂🌧🎧🥭🚲🪔🐘🎈"
    assert len(eight) == 8 and len(eight.encode()) > 8
    policy.assert_password_allowed(eight, realm="client")
    with pytest.raises(ProblemError) as caught:
        policy.assert_password_allowed(eight[:7], realm="client")
    assert caught.value.code == "password_length"


# ── enforcement placement ────────────────────────────────────────────────────


async def test_the_store_refuses_a_blocklisted_password() -> None:
    """The policy is applied by `credentials.set_password`, which is the ONE writer of
    `auth_credentials.password_hash` — so no route can forget it.

    This is the placement that matters more than the rule: `subjects.py` documents the
    reference implementation shipping a careful generic response on one endpoint and an
    enumeration oracle on another, because the property was enforced per-endpoint by
    whoever remembered.
    """
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    async with credential_session() as session:
        with pytest.raises(ProblemError) as caught:
            await set_password(
                session, realm="client", subject_id=user_id, password="calevate2026!!!!"
            )
    assert caught.value.code == "password_unacceptable"

    # And nothing was stored, so the account still has no password at all.
    async with credential_session() as session:
        row = (
            await session.execute(
                text("SELECT 1 FROM auth_credentials WHERE realm = 'client' AND subject_id = :s"),
                {"s": user_id},
            )
        ).first()
    assert row is None


async def test_a_stricter_rule_never_locks_an_existing_account_out() -> None:
    """`credentials.authenticate_subject`: a rule that arrives after a password was set
    must not turn a correct sign-in into a refusal. A client password stored before the
    blocklist refused it still signs in; the policy governs what may be STORED, not what
    may be presented.
    """
    user_id = uuid.uuid4()
    legacy = "abcdefghijkl"
    with pytest.raises(ProblemError):
        policy.assert_password_allowed(legacy, realm="client")
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    # Written the way a pre-policy row was: straight to the store, past the policy.
    async with credential_session() as session:
        await session.execute(
            text(
                "INSERT INTO auth_credentials (id, realm, subject_id, password_hash, "
                "password_set_at, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'client', :s, :h, now(), now(), now())"
            ),
            {"s": user_id, "h": hash_password_blocking(legacy)},
        )
        assert await authenticate_subject(
            session, realm="client", subject_id=user_id, password=legacy
        )
