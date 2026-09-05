"""The durable identity of a REPEAT CALLER, and the only key caller memory may be filed under.

Cross-call memory ("the agent knows this person asked about IVF pricing last month") needs
a subject key that OUTLIVES the call it was learned on. That single sentence is what makes
this module necessary and what makes it dangerous, so both halves are argued here.

═══ WHY NOT THE COLUMNS WE ALREADY HAVE ═══

`calls.from_e164` is NULLed by `execute_deletion_request`. `leads.phone_e164` is
overwritten with `ANONYMIZED_PHONE`. Both are the correct behaviour and both make those
columns useless as a memory key: the feature's whole point is that the row survives the
call, and a key that is erased leaves an ORPHANED fact about a person nothing can find
again — the worst of both worlds, since the fact remains and the erasure cannot reach it.

`calls.erased_subject_ref` is closer — it is a hash, it is deliberately durable, and
`execute_deletion_request` already re-derives it from the number to find calls a PREVIOUS
erasure scrubbed (D-310). But it is `sha256(phone)[:32]` with NO KEY, and this repository
has already written down why that is not good enough for a live store: `_erase_campaign_
contacts` clears `dedupe_hash` because "it holds `sha256(phone)[:16]` — unsalted, and
Indian mobile E.164 is a ~10^9 space anyone can enumerate in seconds, so leaving it is
leaving the number in a form that reverses". An unsalted digest sitting in the same row as
a durable fact about the person is not a pseudonym; it is a re-identifiable profile with
one `for` loop in front of it. `erased_subject_ref` gets away with it because it is a
tombstone on a call whose personal data is already gone — nothing is filed under it.

═══ WHAT THIS IS ═══

`caller_ref = hmac-sha256(K, "caller-memory/v1" || tenant_id || "\\0" || e164)[:32]`, where
`K` is HKDF-SHA-256 of `PLATFORM_KEK` under an `info` string of its own (RFC 5869 §3.2 key
separation, exactly as `authn/hashing.PEPPER_INFO` and `authn/codes.CODE_KEY_INFO` — one
`derived_ring` so the three constructions cannot drift, three `info` strings so none can
be traded for another).

Two properties follow, and they are the design:

* **It does not reverse.** `PLATFORM_KEK` is env-only by construction (`ENV_ONLY_KEYS`,
  `check_bootstrap_keys`) — "a database holding both the lock and the key is theatre" —
  so a stolen dump of the memory table is 32 unknown bytes away from being a list of
  phone numbers with facts attached.
* **It does not link across tenants.** `tenant_id` is INSIDE the MAC input, so the same
  person ringing two of our clients has two unrelated refs. Without that, an operator (or
  anyone holding a dump) could join two clients' caller memories on one column and build a
  profile neither client's caller ever agreed to. RLS stops the QUERY; this stops the
  correlation from being expressible at all.

═══ THE ROTATION HAZARD, WHICH IS AN ERASURE HAZARD ═══

A derived key rotates when the KEK rotates. For passwords that is benign — `verify_password`
walks the ring and re-hashes lazily. Here it is not benign in the same way, because the
thing that must never miss is the ERASURE: a DPDP §12 request derives the ref from the
number, and if it derives it under the new key while the rows were written under the old
one, the certificate says "removed" over data that is still there.

So the module is asymmetric on purpose, mirroring `KekRing.all_keys` ("a retired key
unwraps and never wraps"):

* `active_caller_ref` returns ONE ref and its `kek_id`. It is the only thing a WRITE may
  use, and the `kek_id` is stored beside the row so an auditor (and `ring_covers`) can
  tell which generation minted it.
* `caller_refs` returns EVERY generation, newest first. Erasure and recall use it, so a
  rotation degrades into "the predicate matches two values" rather than into a silent
  miss.

`ring_covers` is the third piece and the one that turns the remaining gap into an alarm
rather than a surprise. `build_ring` DROPS an undecodable `PLATFORM_KEK_RETIRED` with a
log line rather than refusing to boot — right for a deployment that must keep serving, and
fatal here, because the dropped generation is exactly the one whose rows an erasure can no
longer address. A caller-memory row whose `kek_id` this ring cannot produce is UNREACHABLE
BY ERASURE, and that is a fact the sweep can check on every tick.

═══ WHAT IT REFUSES ═══

Every failure raises rather than returning a plausible ref, because a wrong ref is not a
degraded answer: on the write path it files a fact under a stranger, and on the erasure
path it silently matches nothing. `E.164 only` and `never the anonymized placeholder` are
both enforced — `ANONYMIZED_PHONE` is what an erased lead's number becomes, so deriving a
ref from one would mint a shared pseudonym that every erased lead in the tenant collides
on.

**NO DATABASE, NO SETTINGS READ IN THE HOT PATH, NO ASYNC.** A string and a UUID go in, a
string comes out, so every branch is testable without Postgres — `authn/hashing.py`'s
closing paragraph, and the reason that module is the one this borrows its shape from.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from apps.api.authn.hashing import derived_ring
from apps.api.core.envelope import KekRing, kek_ring

#: HKDF domain separation, distinct from `hashing.PEPPER_INFO` and `codes.CODE_KEY_INFO`.
#: Versioned for their reason: a construction change is a NEW `info`, so refs minted under
#: the old one stay derivable for as long as a reader needs them rather than becoming
#: unaddressable the moment somebody edits this file.
CALLER_REF_INFO: Final = b"calevate/caller-memory-subject/v1"

#: Prefixed onto the MAC input, so a value from this function can never be mistaken for —
#: or replayed as — a MAC of something else derived from the same key in future.
_DOMAIN: Final = b"caller-memory/v1"

#: Hex characters kept. 32, i.e. 128 bits, matching `retention._hash`'s width so the two
#: subject handles look alike in a proof and are still far past any collision concern at
#: the scale of one tenant's callers.
REF_HEX_CHARS: Final = 32

#: E.164, spelled exactly as `ingest.service._E164` spells it. Duplicated rather than
#: imported: `ingest.service` imports `compliance.service`, so a compliance module reaching
#: back into it is the cycle `compliance/dnc.py`'s header already routes around, and this
#: is one regex rather than a normalisation policy.
_E164: Final = re.compile(r"^\+[1-9]\d{7,14}$")

#: `retention.ANONYMIZED_PHONE`, and the prefix `_LEAD_SQL` / `_CAMPAIGN_CONTACT_ERASE_SQL`
#: actually write (`ANONYMIZED_PHONE[:9]` plus eight characters of row id). Matched on the
#: PREFIX for that reason — the full constant never appears in a lead row.
_ANONYMIZED_PREFIX: Final = "+91000000"


class CallerRefError(ValueError):
    """A ref could not be derived. Never caught to substitute a default — see the header."""


@dataclass(frozen=True, slots=True)
class ActiveCallerRef:
    """The ref a write files a fact under, and the KEK generation that minted it.

    Carried together because storing the ref without the `kek_id` makes `ring_covers`
    unanswerable: a bare ref cannot say which key produced it, so an operator holding a
    deployment whose retired key was dropped has no way to tell which rows an erasure can
    still reach.
    """

    ref: str
    kek_id: int


def _mac_input(tenant_id: UUID, phone_e164: str) -> bytes:
    """The MAC message. NUL-separated, so no two (tenant, number) pairs can concatenate
    into the same byte string — a tenant id is fixed-width today and the separator costs
    nothing, but the pair is exactly the shape where a missing delimiter becomes a
    cross-tenant collision the day either side's format changes."""
    return b"\x00".join((_DOMAIN, str(tenant_id).encode(), phone_e164.encode()))


def _checked(phone_e164: str) -> str:
    """The number, or a refusal. Does NOT normalise, and that is deliberate.

    `ingest.normalize_phone` exists and is the one way a raw string becomes E.164 — but
    every caller of THIS function is handing over a value that is already `phone_e164` in
    the database (`calls.from_e164`, `deletion_requests.phone_e164`). Forgiving a
    malformed one here would let the write path and the erasure path disagree about the
    canonical form of the same person, which is the one divergence this module cannot
    survive. So a value that is not already canonical is an error, loudly, at both ends.
    """
    candidate = phone_e164.strip()
    if not _E164.match(candidate):
        raise CallerRefError("caller ref requires an E.164 number")
    if candidate.startswith(_ANONYMIZED_PREFIX):
        # An erased lead's placeholder. Deriving a ref from it would mint one shared
        # pseudonym that every erased lead in the tenant lands on — a bucket that reads
        # like a person and is not one.
        raise CallerRefError("caller ref refused for an anonymized placeholder number")
    return candidate


def _ref_under(key: bytes, tenant_id: UUID, phone_e164: str) -> str:
    return hmac.new(key, _mac_input(tenant_id, phone_e164), hashlib.sha256).hexdigest()[
        :REF_HEX_CHARS
    ]


def active_caller_ref(
    tenant_id: UUID, phone_e164: str, *, ring: KekRing | None = None
) -> ActiveCallerRef:
    """The ref a NEW caller-memory row is filed under, plus the generation that minted it.

    One value, from the active key only — `KekRing.all_keys`' rule, and the reason
    `caller_refs` below exists separately. A write that walked the ring would have to
    choose a generation anyway, and choosing a retired one is how a deployment ends up
    with rows nobody can rotate off.
    """
    checked = _checked(phone_e164)
    # ONE ring for both halves. Resolving it twice — once for the derived key, once for
    # the `kek_id` — would let a rotation landing between the two stamp a row with a
    # generation that did not mint it, which is precisely the lie `ring_covers` reads.
    resolved = ring or kek_ring()
    derived = derived_ring(CALLER_REF_INFO, resolved)
    return ActiveCallerRef(
        ref=_ref_under(derived[0], tenant_id, checked), kek_id=resolved.all_keys[0].kek_id
    )


def caller_refs(
    tenant_id: UUID, phone_e164: str, *, ring: KekRing | None = None
) -> tuple[str, ...]:
    """Every ref this person's rows could have been written under, newest first.

    THE ERASURE AND RECALL PREDICATE, and it is a tuple rather than a string for one
    reason: a KEK rotation must not be able to hide a row from a DPDP §12 request. With
    `subject_ref = ANY(:refs)` a rotation costs one extra value in an index scan; with a
    single active ref it costs the erasure everything written before the rotation, and
    nothing would report it — the certificate would simply say zero.
    """
    checked = _checked(phone_e164)
    derived = derived_ring(CALLER_REF_INFO, ring or kek_ring())
    return tuple(_ref_under(key, tenant_id, checked) for key in derived)


def ring_covers(kek_id: int, *, ring: KekRing | None = None) -> bool:
    """Can this deployment still derive refs minted under `kek_id`?

    False means the rows stamped with it are UNREACHABLE BY ERASURE: `caller_refs` cannot
    produce the value they are filed under, so a §12 request for that person matches
    nothing and reports nothing. It happens for exactly one reason —
    `envelope.build_ring` DROPS an undecodable `PLATFORM_KEK_RETIRED` with a log line
    rather than refusing to boot, which is right for availability and wrong for this
    table — and the remedy is an operator one (restore the retired value, or scrub the
    stranded rows). Hence a predicate a sweep can call, not an exception at derivation
    time: the derivation is fine, it is the OLD rows that are stranded.
    """
    return any(key.kek_id == kek_id for key in (ring or kek_ring()).all_keys)


__all__ = [
    "CALLER_REF_INFO",
    "REF_HEX_CHARS",
    "ActiveCallerRef",
    "CallerRefError",
    "active_caller_ref",
    "caller_refs",
    "ring_covers",
]
