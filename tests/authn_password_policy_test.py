"""The password policy: the two NIST SP 800-63B-4 §3.1.1.2 SHALLs that were unmet.

The standard is quoted in `apps/api/authn/policy.py` with its source (usnistgov/800-63-4
@ 4f2487bb81adecdc84ccaac6920bf0b500b379ae, `sp800-63b/authenticators/index.html`, read
2026-08-26). These tests assert the BEHAVIOUR, and two of them derive the requirement
from this repo's own facts rather than restating a number — see
`test_every_single_factor_realm_meets_the_nist_floor`, which is the assertion that would
have caught the original defect.

What was wrong before this module existed:

  * `MIN_PASSWORD_CHARS = 12` applied to both realms. The client realm has no second
    factor (`service.MFA_REQUIRED_REALMS == {"admin"}`), so its password is the whole of
    the authentication and §3.1.1.2's fifteen-character SHALL applies to it. The comment
    above the constant read "NIST SP 800-63B-4 lowers the floor to 8 and recommends 15",
    which inverts both halves of the sentence it was paraphrasing.
  * There was NO blocklist of any kind — "verifiers SHALL compare the prospective secret
    against a blocklist" was simply not implemented, and no test named its absence.
  * Passwords were not Unicode-normalized before hashing.
"""

from __future__ import annotations

import unicodedata
import uuid

import pytest
from apps.api.authn import policy, service
from apps.api.authn.credentials import authenticate_subject, set_password
from apps.api.authn.hashing import (
    MAX_PASSWORD_CHARS,
    MIN_PASSWORD_CHARS,
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


def test_every_single_factor_realm_meets_the_nist_floor() -> None:
    """THE ASSERTION THAT WOULD HAVE CAUGHT THE ORIGINAL DEFECT, and the reason it is
    written this way.

    §3.1.1.2: passwords "used as a single-factor authentication mechanism" SHALL be a
    minimum of 15 characters; fewer is permitted only for passwords "only used as part of
    multi-factor authentication processes", and then never below 8.

    Which realms are which is not restated here — it is READ from
    `service.MFA_REQUIRED_REALMS`, the repo's own single copy of that fact (D-170). So
    giving the client realm a second factor, or adding a third realm, moves this
    assertion with the change instead of leaving a hard-coded 15 that nobody rechecks.
    Hard-coding the realm names is exactly how the original 12 survived: the number was
    right for the realm somebody had in mind and wrong for the other one.
    """
    for realm in AUTHN_REALMS:
        floor = policy.min_password_chars(realm)
        if realm in service.MFA_REQUIRED_REALMS:
            assert floor >= 8, f"{realm} is MFA-protected; the SHALL is still 8"
        else:
            assert floor >= policy.SINGLE_FACTOR_MIN_CHARS, (
                f"{realm} has no second factor, so its password is single-factor and "
                f"SP 800-63B-4 §3.1.1.2 requires at least "
                f"{policy.SINGLE_FACTOR_MIN_CHARS} characters"
            )


def test_the_client_realm_refuses_what_the_old_shared_floor_allowed() -> None:
    """Twelve characters — legal under the old constant, three short of the SHALL."""
    twelve = "abcdefghijkl"
    assert len(twelve) == MIN_PASSWORD_CHARS
    with pytest.raises(ProblemError) as caught:
        policy.assert_password_allowed(twelve, realm="client")
    assert caught.value.code == "password_length"
    # The refusal states the CLIENT's floor, not the absolute one, or the person tries 13.
    assert str(policy.min_password_chars("client")) in caught.value.detail


def test_the_admin_realm_keeps_its_floor_because_it_has_a_second_factor() -> None:
    assert policy.min_password_chars("admin") == MIN_PASSWORD_CHARS
    # Twelve characters and not a keyboard walk — `abcdefghijkl` would clear the floor
    # and then trip the blocklist, which is correct but tests the wrong thing here.
    twelve = "rhubarb-oxen"
    assert len(twelve) == MIN_PASSWORD_CHARS
    policy.assert_password_allowed(twelve, realm="admin")


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
    password length" (§3.1.1.2). Fifteen astral-plane characters is fifteen, not
    thirty."""
    # Fifteen DISTINCT astral-plane characters: a repeated one would clear the length
    # rule and then be refused as a repetition, proving nothing about the count.
    fifteen = "🙂🌧🎧🥭🚲🪔🐘🎈🧭🛺🍋🧵🪁🦚🛕"
    assert len(fifteen) == 15 and len(fifteen.encode()) > 15
    policy.assert_password_allowed(fifteen, realm="client")


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


async def test_raising_the_floor_never_locks_an_existing_account_out() -> None:
    """THE PROPERTY THAT MAKES THIS CHANGE SAFE TO SHIP, asserted rather than argued.

    `credentials.authenticate_subject` already carried the reasoning — a rule that
    arrives after a password was set must not turn a correct sign-in into a refusal — and
    it now has to hold against a stricter rule than a length bump. A 12-character client
    password stored before the floor moved still signs in; what changed is what may be
    STORED, not what may be presented.
    """
    user_id = uuid.uuid4()
    legacy = "abcdefghijkl"
    assert len(legacy) < policy.min_password_chars("client")
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
