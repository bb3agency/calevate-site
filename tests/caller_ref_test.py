"""The caller-memory subject key: durable, unlinkable, and reachable across a KEK rotation.

These are the tests for the ONE property cross-call memory cannot be built without and
cannot be retro-fitted: a fact learned on Monday's call must still be findable on next
month's call, AND must still be findable by a DPDP §12 erasure that arrives after the call
row has been scrubbed in place. `compliance/caller_ref.py`'s header argues the design; this
file pins the three ways it can silently fail.

1. **It reverses.** An unsalted digest of an Indian mobile is a ~10^9 enumeration — the
   repository's own reason for clearing `campaign_contacts.dedupe_hash` on erasure. A
   memory row keyed by one is a phone number with a fact attached.
2. **It links across tenants.** One person ringing two of our clients must not share a key
   between them, or a dump joins two clients' caller memories into a profile nobody agreed
   to. RLS stops the query; only the key construction stops the correlation existing.
3. **A KEK rotation hides rows from the erasure.** This is the expensive one, because
   nothing reports it: the erasure derives a ref under the new key, matches zero rows, and
   the certificate says "removed" over data that is still there.

No database, by construction — the module takes a UUID and a string.
"""

from __future__ import annotations

import base64
import hashlib
import os
import uuid

import pytest
from apps.api.compliance.caller_ref import (
    CALLER_REF_INFO,
    REF_HEX_CHARS,
    CallerRefError,
    active_caller_ref,
    caller_refs,
    ring_covers,
)
from apps.api.core.envelope import KekRing, build_ring

#: A real Indian mobile shape. Never a live number: the value is only ever MAC'd here, but
#: a test fixture that looks like somebody's phone ends up pasted somewhere it should not.
CALLER = "+919812345678"
OTHER_CALLER = "+919812345679"


def _kek() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def _ring(kek: str, retired: str | None = None) -> KekRing:
    return build_ring(kek=kek, retired=retired, app_env="local")


# ------------------------------------------------------------------ it is a stable key


def test_the_same_caller_at_the_same_tenant_gets_the_same_ref() -> None:
    """The whole feature. Two calls a month apart resolve to one subject."""
    ring = _ring(_kek())
    tenant = uuid.uuid4()
    assert active_caller_ref(tenant, CALLER, ring=ring) == active_caller_ref(
        tenant, CALLER, ring=ring
    )


def test_the_ref_is_thirty_two_hex_characters() -> None:
    ref = active_caller_ref(uuid.uuid4(), CALLER, ring=_ring(_kek())).ref
    assert len(ref) == REF_HEX_CHARS
    assert set(ref) <= set("0123456789abcdef")


def test_two_callers_do_not_collide() -> None:
    ring = _ring(_kek())
    tenant = uuid.uuid4()
    assert (
        active_caller_ref(tenant, CALLER, ring=ring).ref
        != active_caller_ref(tenant, OTHER_CALLER, ring=ring).ref
    )


# ------------------------------------------------------------------ it does not reverse


def test_the_ref_is_not_a_digest_anybody_can_recompute() -> None:
    """The property `dedupe_hash` did not have.

    An attacker holding the memory table and nothing else can enumerate every Indian
    mobile and hash it. What they cannot do is HMAC it, because the key is HKDF of
    `PLATFORM_KEK`, which is env-only by construction. Spelled as an inequality against
    the two unkeyed digests somebody would actually try — including `retention._hash`'s
    exact construction, which is what `calls.erased_subject_ref` holds.
    """
    ref = active_caller_ref(uuid.uuid4(), CALLER, ring=_ring(_kek())).ref
    assert ref != hashlib.sha256(CALLER.encode()).hexdigest()[:REF_HEX_CHARS]
    assert ref != hashlib.sha256(CALLER.encode()).hexdigest()[:16]


def test_a_different_kek_yields_a_different_ref() -> None:
    """i.e. the key genuinely participates. Without this the test above passes for a
    construction that merely salts with a constant nobody rotates."""
    tenant = uuid.uuid4()
    assert (
        active_caller_ref(tenant, CALLER, ring=_ring(_kek())).ref
        != active_caller_ref(tenant, CALLER, ring=_ring(_kek())).ref
    )


# ------------------------------------------------------------------ it does not link


def test_the_same_person_at_two_tenants_has_two_unrelated_refs() -> None:
    """One caller, two of our clients, no shared column. The tenant id is inside the MAC
    input precisely so this join cannot be written even by someone holding a dump."""
    ring = _ring(_kek())
    assert (
        active_caller_ref(uuid.uuid4(), CALLER, ring=ring).ref
        != active_caller_ref(uuid.uuid4(), CALLER, ring=ring).ref
    )


def test_the_domain_string_is_versioned() -> None:
    """A construction change must be a NEW `info`, never an edit of this one — refs
    already in the table have to stay derivable. Pinned so the change is deliberate."""
    assert CALLER_REF_INFO == b"calevate/caller-memory-subject/v1"


# ------------------------------------------------------------- rotation is not an erasure gap


def test_a_ref_written_before_a_rotation_is_still_derivable_after_it() -> None:
    """THE ERASURE TEST, at the key level.

    A fact is filed on Monday under KEK A. The KEK rotates. A DPDP §12 request arrives
    for that caller. `caller_refs` must still produce the Monday value, or the erasure
    matches nothing and reports nothing — the failure mode that looks exactly like a
    caller who was never remembered.
    """
    old, new = _kek(), _kek()
    tenant = uuid.uuid4()
    before = active_caller_ref(tenant, CALLER, ring=_ring(old)).ref

    after_ring = _ring(new, retired=old)
    assert active_caller_ref(tenant, CALLER, ring=after_ring).ref != before
    assert before in caller_refs(tenant, CALLER, ring=after_ring)


def test_the_active_generation_is_first_and_is_what_a_write_uses() -> None:
    """`KekRing.all_keys`' rule — a retired key unwraps and never wraps — so a WRITE may
    only ever use element 0. A write that walked the ring would eventually stamp a row
    with a generation about to be decommissioned."""
    old, new = _kek(), _kek()
    tenant = uuid.uuid4()
    ring = _ring(new, retired=old)
    assert (
        caller_refs(tenant, CALLER, ring=ring)[0]
        == active_caller_ref(tenant, CALLER, ring=ring).ref
    )


def test_an_unrotated_deployment_derives_exactly_one_ref() -> None:
    """The common case costs one value in the erasure predicate, not two."""
    assert len(caller_refs(uuid.uuid4(), CALLER, ring=_ring(_kek()))) == 1


# ------------------------------------------------------ the stranded-generation alarm surface


def test_ring_covers_accepts_both_live_generations() -> None:
    ring = _ring(_kek(), retired=_kek())
    for key in ring.all_keys:
        assert ring_covers(key.kek_id, ring=ring)


def test_ring_covers_refuses_a_generation_this_deployment_lost() -> None:
    """`build_ring` DROPS an undecodable `PLATFORM_KEK_RETIRED` rather than refusing to
    boot. Right for availability, and the rows stamped with that generation are then
    unreachable by erasure — so it has to be a fact a sweep can check, not a surprise.
    """
    stamped = active_caller_ref(uuid.uuid4(), CALLER, ring=_ring(_kek())).kek_id
    assert not ring_covers(stamped, ring=_ring(_kek()))


def test_the_stamped_generation_is_the_one_that_minted_the_ref() -> None:
    """Otherwise `ring_covers` answers a question about the wrong row."""
    ring = _ring(_kek(), retired=_kek())
    assert active_caller_ref(uuid.uuid4(), CALLER, ring=ring).kek_id == ring.active.kek_id


# ------------------------------------------------------------------ it refuses rather than guesses


@pytest.mark.parametrize(
    "value",
    [
        "9812345678",  # no country code — `normalize_phone`'s job, not this module's
        "+91 98123 45678",  # separators
        "++919812345678",
        "",
        "not a number",
        "+0919812345678",  # E.164 country codes do not start with 0
    ],
)
def test_a_number_that_is_not_canonical_e164_is_refused(value: str) -> None:
    """No normalisation here, deliberately: the write path and the erasure path must
    agree on the canonical form of one person, and a forgiving parser is how they stop
    agreeing. Every caller hands over a value that is already `phone_e164` in the DB.
    """
    with pytest.raises(CallerRefError):
        active_caller_ref(uuid.uuid4(), value, ring=_ring(_kek()))


def test_the_anonymized_placeholder_is_refused() -> None:
    """`_LEAD_SQL` writes `ANONYMIZED_PHONE[:9] || substr(id::text, 1, 8)` over an erased
    lead's number. Deriving a ref from one would mint a pseudonym every erased lead in
    the tenant collides on — a bucket that reads like a person and is not one.
    """
    with pytest.raises(CallerRefError):
        active_caller_ref(uuid.uuid4(), "+910000000abc1234"[:13], ring=_ring(_kek()))


def test_the_refusal_reaches_the_erasure_side_too() -> None:
    """`caller_refs` validates identically. A one-sided check would let a malformed value
    be written and then be unerasable."""
    with pytest.raises(CallerRefError):
        caller_refs(uuid.uuid4(), "9812345678", ring=_ring(_kek()))


def test_surrounding_whitespace_is_tolerated_on_both_sides() -> None:
    """A `.strip()` and nothing more — the one forgiveness that cannot change WHICH
    person the value denotes, and the one a column read can plausibly carry."""
    ring = _ring(_kek())
    tenant = uuid.uuid4()
    assert (
        active_caller_ref(tenant, f"  {CALLER} ", ring=ring).ref
        == active_caller_ref(tenant, CALLER, ring=ring).ref
    )


def test_an_erased_leads_placeholder_number_is_refused_rather_than_given_a_ref() -> None:
    """The one number in the system that is not a person, and must not become one.

    `retention.ANONYMIZED_PHONE` is what a lead's number becomes after an erasure. Deriving
    a ref from it would be arithmetically fine and semantically catastrophic: every erased
    lead in the tenant lands on ONE shared pseudonym, which then reads like a single very
    active caller — rows about different people accumulating under one key, in the exact
    store whose whole purpose is to be erasable per person.

    Imported from the worker rather than retyped, so the day that constant moves this test
    moves with it instead of quietly guarding a string nothing writes any more.
    """
    from apps.workers.retention import ANONYMIZED_PHONE

    ring = _ring(_kek())
    with pytest.raises(CallerRefError, match="anonymized placeholder"):
        active_caller_ref(uuid.uuid4(), ANONYMIZED_PHONE, ring=ring)

    with pytest.raises(CallerRefError, match="anonymized placeholder"):
        caller_refs(uuid.uuid4(), ANONYMIZED_PHONE, ring=ring)
