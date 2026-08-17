"""D-165's password hashing, with a negative control for every property it claims.

`apps/api/authn/hashing.py` makes five claims, and a test that only checks "the right
password works" proves none of them:

  1. the right password verifies, the wrong one does not;
  2. two hashes of one password differ (there is a salt);
  3. the stored hash was made with the parameters this repo chose, not the library's;
  4. an unknown subject costs the same as a wrong password (no enumeration oracle);
  5. the pepper is real — a hash made under one deployment's `PLATFORM_KEK` does not
     verify under another's, and one made under a RETIRED generation verifies while
     asking to be rewritten.

No database and no event loop: every function under test takes a string and returns a
string, which is why they live in their own module rather than inside the credential
service.
"""

from __future__ import annotations

import base64
import os
import time

import pytest
from apps.api.authn.hashing import (
    ARGON2_MEMORY_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    MAX_PASSWORD_CHARS,
    MIN_PASSWORD_CHARS,
    _peppered,
    hash_password_blocking,
    pepper_ring,
    verify_password_blocking,
)
from apps.api.core.envelope import KekRing, build_ring
from apps.api.core.errors import ProblemError
from argon2 import PasswordHasher
from argon2.low_level import Type

PASSWORD = "chinnamma-clinic-front-desk"


def _kek() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def _ring(kek: str, retired: str | None = None) -> KekRing:
    return build_ring(kek=kek, retired=retired, app_env="local")


# ------------------------------------------------------------------ the basic claim


def test_a_password_verifies_against_its_own_hash() -> None:
    ring = _ring(_kek())
    verdict = verify_password_blocking(
        PASSWORD, hash_password_blocking(PASSWORD, ring=ring), ring=ring
    )
    assert verdict.ok
    assert not verdict.needs_rehash


def test_the_wrong_password_is_refused() -> None:
    """NEGATIVE CONTROL for claim 1. Same ring, same subject, one character different."""
    ring = _ring(_kek())
    stored = hash_password_blocking(PASSWORD, ring=ring)
    assert not verify_password_blocking(PASSWORD + "!", stored, ring=ring).ok
    assert not verify_password_blocking("", stored, ring=ring).ok
    assert not verify_password_blocking(PASSWORD.upper(), stored, ring=ring).ok


def test_two_hashes_of_one_password_differ() -> None:
    """A shared salt would make the store rainbow-tableable; argon2-cffi salts per call,
    and this is the assertion that notices if a future refactor pins one."""
    ring = _ring(_kek())
    assert hash_password_blocking(PASSWORD, ring=ring) != hash_password_blocking(
        PASSWORD, ring=ring
    )


# ------------------------------------------------------------------ the parameters


def test_the_stored_hash_carries_the_parameters_this_repo_chose() -> None:
    """Claim 3, read off the PHC string rather than off the constants.

    `argon2-cffi`'s defaults are `m=65536,t=3,p=4`; the module overrides all three for
    reasons its docstring argues (19 MiB because memory is the scarce resource on the
    target VPS; `p=1` because the server is a single-threaded asyncio worker). Asserting
    the CONSTANTS would pass even if `_hasher()` stopped passing them to the library, so
    the assertion is against the output.
    """
    stored = hash_password_blocking(PASSWORD, ring=_ring(_kek()))
    assert stored.startswith("$argon2id$")
    assert f"m={ARGON2_MEMORY_KIB},t={ARGON2_TIME_COST},p={ARGON2_PARALLELISM}" in stored


def test_a_hash_made_with_weaker_parameters_asks_to_be_rehashed() -> None:
    """Claim 3's other half: an old row is upgradable without a migration.

    The stored string is doctored to a lower memory cost — which is exactly what a row
    written before a parameter bump looks like — and the verdict must still authenticate
    while asking for a rewrite.
    """
    ring = _ring(_kek())
    weak = PasswordHasher(
        time_cost=1, memory_cost=8192, parallelism=1, hash_len=32, salt_len=16, type=Type.ID
    )
    stored = weak.hash(_peppered(PASSWORD, pepper_ring(ring)[0]))

    verdict = verify_password_blocking(PASSWORD, stored, ring=ring)
    assert verdict.ok
    assert verdict.needs_rehash


# ------------------------------------------------------------------ the pepper


def test_the_pepper_is_not_the_kek_and_is_stable_for_one_kek() -> None:
    """HKDF separation, both directions.

    If the pepper were the KEK, a component that legitimately holds the KEK to unwrap a
    vendor credential would also hold the value that makes a stolen password table
    crackable. And if it were not stable, every process restart would invalidate every
    password.
    """
    kek = _kek()
    ring = _ring(kek)
    pepper = pepper_ring(ring)[0]
    assert pepper != ring.active.material
    assert len(pepper) == 32
    assert pepper_ring(_ring(kek))[0] == pepper


def test_a_hash_made_under_another_deployments_kek_does_not_verify() -> None:
    """NEGATIVE CONTROL for claim 5, and the whole point of peppering.

    This IS the stolen-database scenario: the attacker has the row and the algorithm and
    the parameters, and does not have `PLATFORM_KEK`. Correct passwords stop being
    correct.
    """
    stolen = hash_password_blocking(PASSWORD, ring=_ring(_kek()))
    assert not verify_password_blocking(PASSWORD, stolen, ring=_ring(_kek())).ok


def test_a_hash_from_a_retired_pepper_generation_verifies_and_asks_to_be_rehashed() -> None:
    """The lazy drain a KEK rotation depends on.

    Hash under the outgoing key, then rotate: the new deployment has a new active KEK and
    carries the old one in `PLATFORM_KEK_RETIRED`, exactly as `core/envelope.build_ring`
    describes. The password must still work — otherwise rotating the KEK locks every
    account out — and must be reported as needing a rewrite so the next successful
    sign-in moves it forward.
    """
    outgoing, incoming = _kek(), _kek()
    stored = hash_password_blocking(PASSWORD, ring=_ring(outgoing))

    after_rotation = _ring(incoming, retired=outgoing)
    verdict = verify_password_blocking(PASSWORD, stored, ring=after_rotation)
    assert verdict.ok
    assert verdict.needs_rehash

    # And once rewritten it is current again — the drain terminates.
    rewritten = hash_password_blocking(PASSWORD, ring=after_rotation)
    assert not verify_password_blocking(PASSWORD, rewritten, ring=after_rotation).needs_rehash


def test_a_second_rotation_drops_the_generation_that_fell_off_the_ring() -> None:
    """NEGATIVE CONTROL for the drain: the ring is two deep, not unbounded.

    A password never used across two rotations stops verifying, which is a real
    operational fact the cutover plan has to account for (AUTH-MIGRATION §4) rather than
    a defect — the alternative is a ring that keeps every key this deployment has ever
    held, which defeats retiring one.
    """
    first, second, third = _kek(), _kek(), _kek()
    stored = hash_password_blocking(PASSWORD, ring=_ring(first))
    assert not verify_password_blocking(PASSWORD, stored, ring=_ring(third, retired=second)).ok


# ------------------------------------------------------------------ enumeration & shape


@pytest.mark.parametrize("rotated", [False, True], ids=["one-pepper", "mid-rotation"])
def test_an_unknown_subject_costs_what_a_wrong_password_costs(rotated: bool) -> None:
    """NEGATIVE CONTROL for claim 4 — the user-enumeration oracle.

    `stored_hash=None` means "no such account". Returning early there is the classic
    leak: an attacker times the response and learns which addresses exist, which is step
    one of every credential-stuffing run. The bound is deliberately loose (a quarter of
    the wrong-password time) because this asserts a SHAPE, not a benchmark — an early
    return is four orders of magnitude faster than an Argon2 verification, so noise
    cannot make this pass and a real regression cannot make it fail.

    **BOTH RING DEPTHS**, because the interesting case is the one that only exists during
    a KEK rotation: a wrong password walks the whole ring while a right one stops early,
    so an unknown-subject path that balanced against the ACTIVE pepper alone would be
    exact on an unrotated deployment and would leak "this account exists" for the days a
    drain is in flight.
    """
    ring = _ring(_kek(), retired=_kek() if rotated else None)
    stored = hash_password_blocking(PASSWORD, ring=ring)

    started = time.perf_counter()
    assert not verify_password_blocking("wrong-password-entirely", stored, ring=ring).ok
    wrong_password_s = time.perf_counter() - started

    started = time.perf_counter()
    assert not verify_password_blocking(PASSWORD, None, ring=ring).ok
    unknown_subject_s = time.perf_counter() - started

    assert unknown_subject_s >= wrong_password_s * 0.25, (
        f"an unknown subject answered in {unknown_subject_s * 1000:.1f}ms against "
        f"{wrong_password_s * 1000:.1f}ms for a wrong password — that difference is "
        "measurable over the network and enumerates accounts"
    )


def test_a_malformed_stored_hash_is_a_refusal_not_an_exception() -> None:
    """A hand-edited or truncated row must fail closed, in the same shape as a wrong
    password — not as a 500 that tells a caller their row is special."""
    ring = _ring(_kek())
    for junk in ("", "not-a-hash", "$argon2id$v=19$m=19456,t=2,p=1$short", "$2b$10$abcdefgh"):
        assert not verify_password_blocking(PASSWORD, junk, ring=ring).ok


@pytest.mark.parametrize(
    "password",
    ["", "short", "a" * (MIN_PASSWORD_CHARS - 1), "a" * (MAX_PASSWORD_CHARS + 1)],
)
def test_a_password_outside_the_length_bounds_is_refused_before_hashing(password: str) -> None:
    """The floor is a policy (NIST/ASVS); the ceiling is a denial-of-service bound.

    Both are enforced at `hash_password_blocking`, i.e. when a password is SET — never at
    verification, because raising the floor later must not lock out everyone whose
    existing password is shorter than the new rule.
    """
    with pytest.raises(ProblemError) as raised:
        hash_password_blocking(password, ring=_ring(_kek()))
    assert raised.value.code == "password_length"


def test_a_long_existing_password_still_verifies_after_the_ceiling_would_reject_it() -> None:
    """The asymmetry above, driven: the bounds gate `hash`, not `verify`."""
    ring = _ring(_kek())
    stored = hash_password_blocking("a" * MAX_PASSWORD_CHARS, ring=ring)
    assert verify_password_blocking("a" * MAX_PASSWORD_CHARS, stored, ring=ring).ok
