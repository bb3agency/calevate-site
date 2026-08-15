"""The envelope's failure modes, each asserted as a REFUSAL BY NAME (PLATFORM-CONFIG §13).

Phase 1's done-when is "encrypt/decrypt round-trips and every failure mode refuses by
name", and the reason each case below is written out rather than summarised as "it
raises" is that the refusals are not interchangeable:

* `platform_kek_unusable` sends an operator to their environment;
* `platform_secret_unwrappable` sends them to their KEK rotation;
* `platform_secret_corrupt` sends them to an incident.

A test that only asserted "an exception" would pass with all three collapsed into one,
which is the version that costs an hour at 3am.

Nothing here touches the process environment: `build_ring` is pure (it takes the
configured strings and the app_env), so every branch — including "there is no KEK" on a
production deployment — is reachable without a monkeypatch that could leak into another
suite on the shared event loop.
"""

from __future__ import annotations

import base64
import os

import pytest
from apps.api.core.envelope import (
    KEK_BYTES,
    MASKED,
    Envelope,
    Kek,
    KekRing,
    build_ring,
    last_four,
    seal,
    unseal,
)
from apps.api.core.errors import ProblemError

CONTEXT = "platform_secret:bolna_api_key"
SECRET = "bn-live-8f3c9a21d4e7b6f5"


def _kek(seed: bytes = b"\x01") -> str:
    """A well-formed KEK: base64 of exactly 32 bytes, deterministic per seed."""
    return base64.b64encode(seed * KEK_BYTES).decode()


def _ring(kek: str | None = None, retired: str | None = None) -> KekRing:
    return build_ring(kek=kek or _kek(), retired=retired, app_env="prod")


# --- the happy path, and the properties it must hold --------------------------


def test_round_trip_returns_exactly_what_went_in() -> None:
    ring = _ring()
    assert unseal(seal(SECRET, context=CONTEXT, ring=ring), context=CONTEXT, ring=ring) == SECRET


def test_the_plaintext_is_nowhere_in_the_envelope() -> None:
    """The claim the whole module exists to make, asserted rather than assumed.

    A cipher misconfigured into a passthrough — or a future 'debug' field — would keep
    every other test in this file green.
    """
    envelope = seal(SECRET, context=CONTEXT, ring=_ring())
    blob = envelope.ciphertext + envelope.nonce + envelope.dek_wrapped + envelope.dek_nonce
    assert SECRET.encode() not in blob


def test_the_envelope_names_the_key_that_wrapped_it() -> None:
    ring = _ring()
    assert seal(SECRET, context=CONTEXT, ring=ring).kek_id == ring.active.kek_id


def test_the_key_id_is_a_property_of_the_key_not_of_the_ring() -> None:
    """`kek_id` is a fingerprint, so the same key has the same id however it is
    configured — which is what makes it safe to store beside a wrapped DEK. If it were
    derived from ring position, moving a key from active to retired would renumber every
    row it wrapped (see `Kek`'s docstring for why that is data loss, not cosmetics)."""
    key = _kek(b"\x07")
    as_active = build_ring(kek=key, retired=None, app_env="prod").active.kek_id
    as_retired = build_ring(kek=_kek(b"\x09"), retired=key, app_env="prod").retired[0].kek_id
    assert as_active == as_retired
    assert as_active > 0, "must be positive: it is stored in a Postgres integer column"


# --- nonce reuse resistance ---------------------------------------------------


def test_every_seal_draws_fresh_nonces_and_a_fresh_dek() -> None:
    """AES-GCM's one catastrophic misuse is a repeated (key, nonce) pair: two messages
    under one pair leak their XOR and, worse, the authentication subkey — forgery, not
    just confidentiality. NIST SP 800-38D §8.3 bounds random 96-bit nonces at 2^32
    invocations per key, and a DEK here is used exactly once, so the bound is
    unreachable by construction. This asserts the construction.
    """
    ring = _ring()
    seals = [seal(SECRET, context=CONTEXT, ring=ring) for _ in range(64)]
    assert len({s.nonce for s in seals}) == 64
    assert len({s.dek_nonce for s in seals}) == 64
    # Distinct DEKs, observed through their wrappings: identical plaintext under
    # identical context must never produce identical ciphertext.
    assert len({s.dek_wrapped for s in seals}) == 64
    assert len({s.ciphertext for s in seals}) == 64


# --- the KEK itself -----------------------------------------------------------


def test_an_absent_kek_refuses_by_name_outside_local() -> None:
    with pytest.raises(ProblemError) as raised:
        build_ring(kek=None, retired=None, app_env="prod")
    assert raised.value.code == "platform_kek_unusable"
    assert "PLATFORM_KEK" in (raised.value.remediation or "")


def test_a_short_kek_is_refused_exactly_like_an_absent_one() -> None:
    """D-86's argument, transferred: to a caller they are ONE condition. A refusal that
    fired on absence and accepted a 16-byte key would guard the easier half of one
    mistake — and the operator who pasted a short value would get no signal at all."""
    short = base64.b64encode(b"\x02" * 16).decode()
    with pytest.raises(ProblemError) as raised:
        build_ring(kek=short, retired=None, app_env="prod")
    assert raised.value.code == "platform_kek_unusable"
    assert "16 bytes" in (raised.value.remediation or "")


def test_a_long_kek_is_refused_too_because_this_is_a_length_not_a_floor() -> None:
    """The one place this differs from the HMAC ladder: AES-256 takes a key of exactly
    256 bits. A 40-byte value is not a stronger key, it is not a key."""
    with pytest.raises(ProblemError) as raised:
        build_ring(kek=base64.b64encode(b"\x03" * 40).decode(), retired=None, app_env="prod")
    assert raised.value.code == "platform_kek_unusable"
    assert "40 bytes" in (raised.value.remediation or "")


def test_a_key_of_any_other_length_cannot_be_constructed_at_all() -> None:
    """The invariant `Kek.__post_init__` exists to make, asserted at the type rather than
    at one caller.

    `build_ring` checks length on the way in, but it is not the only door: `rewrap`,
    `unseal` and every future rotation job take a `KekRing` somebody else assembled, and
    they all pass `Kek.material` straight into `AESGCM(...)`. AES accepts three key sizes
    and nothing else, so a 31-byte value is not a weaker key — it is a `ValueError` raised
    from inside the cipher, at unwrap time, on a row that was wrapped fine. Refusing at
    CONSTRUCTION is what lets everything downstream assume 32 bytes without re-asking, and
    what turns "your credentials will not open" into "this key is the wrong length".

    Both directions are asserted: the wrong lengths refuse, and exactly 32 constructs —
    a check written as `!= 32` and one written as `< 32` differ only on the long key.
    """
    for material in (b"", b"\x05" * 16, b"\x05" * 31, b"\x05" * 33, b"\x05" * 64):
        with pytest.raises(ValueError, match=str(KEK_BYTES)):
            Kek(kek_id=1, material=material)
    assert len(Kek(kek_id=1, material=b"\x05" * KEK_BYTES).material) == KEK_BYTES


def test_a_kek_that_is_not_base64_is_refused_as_an_encoding_problem() -> None:
    """`validate=True` on the decode is what makes this branch reachable: the permissive
    decoder discards characters outside the alphabet, so a mistyped key would quietly
    decode SHORT and be reported as a length problem — sending the operator to lengthen
    a value that was never in the right alphabet."""
    with pytest.raises(ProblemError) as raised:
        build_ring(kek="not a key, obviously!!", retired=None, app_env="prod")
    assert raised.value.code == "platform_kek_unusable"
    assert "base64" in (raised.value.remediation or "")


def test_local_gets_a_derived_kek_and_no_other_environment_does() -> None:
    """The same scoping `resolve_hmac_key` gives its fallback, and for the same reason:
    a constant printed in the repository is a development convenience under `local` and
    a production key with a development name anywhere else."""
    assert build_ring(kek=None, retired=None, app_env="local").active.material
    for env in ("staging", "prod"):
        with pytest.raises(ProblemError):
            build_ring(kek=None, retired=None, app_env=env)


def test_a_broken_retired_kek_is_dropped_rather_than_fatal() -> None:
    """Deliberately asymmetric with the active key. A retired key only ever HELPS, so a
    typo in a decommissioned value must not take a deployment down — it must be loud and
    survivable. (Same asymmetry, same reason, as `audit_chain_secret_retired`.)"""
    ring = build_ring(kek=_kek(), retired="!!not base64!!", app_env="prod")
    assert ring.retired == ()
    assert unseal(seal(SECRET, context=CONTEXT, ring=ring), context=CONTEXT, ring=ring) == SECRET


# --- rotation -----------------------------------------------------------------


def test_a_dek_wrapped_under_the_old_kek_still_unwraps_after_a_rotation() -> None:
    """The property that makes rotation a job rather than an outage (§13 phase 5): rows
    written before the rewrap are still readable while it runs."""
    old, new = _kek(b"\x11"), _kek(b"\x22")
    before = build_ring(kek=old, retired=None, app_env="prod")
    envelope = seal(SECRET, context=CONTEXT, ring=before)

    after = build_ring(kek=new, retired=old, app_env="prod")
    assert unseal(envelope, context=CONTEXT, ring=after) == SECRET
    assert envelope.kek_id == after.retired[0].kek_id, "the row still names the key that wrapped it"


def test_the_retired_key_never_wraps() -> None:
    """§3 rule 4. If a rotation kept writing under the outgoing key, dropping that key
    from the environment later would make rows written AFTER the rotation unreadable —
    the exact opposite of what a rotation is for."""
    old, new = _kek(b"\x11"), _kek(b"\x22")
    after = build_ring(kek=new, retired=old, app_env="prod")
    assert seal(SECRET, context=CONTEXT, ring=after).kek_id == after.active.kek_id


def test_a_key_no_longer_in_the_ring_refuses_by_name() -> None:
    """The wrong-KEK refusal: what an operator meets when they deploy with the wrong
    environment, or rotate without carrying the outgoing value forward."""
    envelope = seal(
        SECRET, context=CONTEXT, ring=build_ring(kek=_kek(b"\x11"), retired=None, app_env="prod")
    )
    stranger = build_ring(kek=_kek(b"\x99"), retired=None, app_env="prod")
    with pytest.raises(ProblemError) as raised:
        unseal(envelope, context=CONTEXT, ring=stranger)
    assert raised.value.code == "platform_secret_unwrappable"


# --- tampering ----------------------------------------------------------------


def _flip(blob: bytes, index: int = 0) -> bytes:
    return blob[:index] + bytes([blob[index] ^ 0x01]) + blob[index + 1 :]


def test_a_tampered_ciphertext_is_a_corruption_not_a_key_problem() -> None:
    ring = _ring()
    envelope = seal(SECRET, context=CONTEXT, ring=ring)
    tampered = Envelope(
        ciphertext=_flip(envelope.ciphertext),
        nonce=envelope.nonce,
        dek_wrapped=envelope.dek_wrapped,
        dek_nonce=envelope.dek_nonce,
        kek_id=envelope.kek_id,
    )
    with pytest.raises(ProblemError) as raised:
        unseal(tampered, context=CONTEXT, ring=ring)
    assert raised.value.code == "platform_secret_corrupt"


def test_a_tampered_nonce_is_caught_too() -> None:
    """The nonce is not authenticated by GCM's tag directly, but changing it changes the
    keystream, so the tag cannot verify. Asserted because 'only the ciphertext is
    protected' is a common and wrong intuition."""
    ring = _ring()
    envelope = seal(SECRET, context=CONTEXT, ring=ring)
    with pytest.raises(ProblemError) as raised:
        unseal(
            Envelope(
                ciphertext=envelope.ciphertext,
                nonce=_flip(envelope.nonce),
                dek_wrapped=envelope.dek_wrapped,
                dek_nonce=envelope.dek_nonce,
                kek_id=envelope.kek_id,
            ),
            context=CONTEXT,
            ring=ring,
        )
    assert raised.value.code == "platform_secret_corrupt"


def test_a_tampered_wrapped_dek_reads_as_unwrappable() -> None:
    """A different refusal from the one above, on purpose: the failure is in the
    WRAPPING, so no key in the ring opens it and the operator's first question is about
    their environment rather than about the row."""
    ring = _ring()
    envelope = seal(SECRET, context=CONTEXT, ring=ring)
    with pytest.raises(ProblemError) as raised:
        unseal(
            Envelope(
                ciphertext=envelope.ciphertext,
                nonce=envelope.nonce,
                dek_wrapped=_flip(envelope.dek_wrapped),
                dek_nonce=envelope.dek_nonce,
                kek_id=envelope.kek_id,
            ),
            context=CONTEXT,
            ring=ring,
        )
    assert raised.value.code == "platform_secret_unwrappable"


def test_a_ciphertext_moved_to_another_key_s_row_does_not_open() -> None:
    """THE REASON `context` IS A REQUIRED ARGUMENT.

    Without authenticated context, an attacker with database write access could copy the
    ciphertext of a vendor key THEY control into our Sarvam key's row: every tag would
    verify, every integrity check would pass, and the platform would authenticate to
    their account. The AAD makes that unexpressible — the row's own identity is part of
    what the tag covers.
    """
    ring = _ring()
    envelope = seal(SECRET, context="platform_secret:sarvam_api_key", ring=ring)
    with pytest.raises(ProblemError) as raised:
        unseal(envelope, context="platform_secret:bolna_api_key", ring=ring)
    # `unwrappable`, not `corrupt`: the AAD is checked on the DEK wrap first, so the move
    # is caught before the payload is even reached.
    assert raised.value.code == "platform_secret_unwrappable"


def test_a_structurally_malformed_row_refuses_instead_of_raising() -> None:
    """FOUND BY A TEST, NOT BY READING, and it is the difference between one bad
    credential and a frozen fleet.

    `AESGCM.decrypt` raises `ValueError` — not `InvalidTag` — when the NONCE is not
    8..128 bytes, because it never gets as far as checking a tag. An unhandled
    `ValueError` there does not refuse one row; it escapes the background refresh that
    was loading every credential, so a single malformed row (a hand-written INSERT, a
    truncated restore) would stop every process picking up any configuration at all.
    That is the failure direction §6 forbids, arrived at from an unexpected angle.
    """
    ring = _ring()
    for broken in (
        Envelope(ciphertext=b"", nonce=b"", dek_wrapped=b"", dek_nonce=b"", kek_id=0),
        Envelope(
            ciphertext=b"\x00", nonce=b"\x00", dek_wrapped=b"\x00", dek_nonce=b"\x00", kek_id=1
        ),
    ):
        with pytest.raises(ProblemError) as raised:
            unseal(broken, context=CONTEXT, ring=ring)
        assert raised.value.code == "platform_secret_unwrappable"


# --- the one fragment that may be stored --------------------------------------


def test_last_four_shows_four_and_masks_anything_too_short_to_have_four() -> None:
    assert last_four("sk-live-abcd1234") == "1234"
    # Eight characters is the floor: below it the "fragment" is most of the secret, and
    # for a four-character value it IS the secret.
    assert last_four("abcdefgh") == "efgh"
    assert last_four("abcd") == MASKED
    assert last_four("") == MASKED


def test_a_real_secret_never_reaches_disk_through_last_four() -> None:
    """A property rather than an example: whatever the value, what is stored is at most
    four characters and never the whole thing."""
    for length in range(1, 40):
        value = os.urandom(length).hex()[:length]
        fragment = last_four(value)
        assert len(fragment) <= max(len(MASKED), 4)
        assert fragment == MASKED or value.endswith(fragment)
