"""Password hashing: Argon2id over a KEK-derived pepper (D-165).

═══ THE ALGORITHM, AND WHY IT IS NOT THE ONE THE REFERENCE IMPLEMENTATION USES ═══

The prior implementation this migration learns from (`raghava-organics-site`,
`backend/src/modules/auth/auth.service.ts`) uses `bcryptjs` at cost 10 in three places
and cost 12 in two others. Neither the library nor the parameter is inherited here, and
the reason is a current source rather than a preference.

OWASP's Password Storage Cheat Sheet (github.com/OWASP/CheatSheetSeries,
`cheatsheets/Password_Storage_Cheat_Sheet.md`, read 2026-08-17) ranks the choices
explicitly: **Argon2id is the first recommendation**, scrypt is the substitute "when the
former is not available", and "the bcrypt password hashing function should only be used
for password storage in legacy systems where Argon2 and scrypt are not available". This
is not a legacy system — it is a table that does not exist yet — so the legacy clause
does not apply. The same page states bcrypt's structural limit: "bcrypt has a maximum
length input length of 72 bytes [for most implementations], so you should enforce a
maximum password length of 72 bytes", and warns that the obvious workaround (pre-hashing
to get around it) carries null-byte and password-shucking hazards. Argon2 has no such
ceiling, which is also why the peppering step below is safe here and is a hazard there.

Two things are inherited from that reference, as defects to avoid rather than patterns to
copy: it hashes with TWO different cost factors depending on which function you entered
through (so the strength of a password depends on whether the account was created by
signup, by admin invite, or by password reset), and it runs bcrypt over REFRESH TOKENS —
`refresh()` compares a presented token against stored hashes in a loop, i.e. one
deliberately-slow KDF per candidate row per refresh. A 256-bit random token needs a fast
hash, not a slow one; see `sessions.token_fingerprint`.

═══ THE PARAMETERS ═══

`m=19456 KiB (19 MiB), t=2, p=1` — the SECOND of the five configurations OWASP lists,
all of which it says "provide an equal level of defense, with the only difference being
a trade-off between CPU and RAM usage". The first (`m=47104, t=1, p=1`) is the default
recommendation and is deliberately not taken: D-25 puts this on a general-purpose VPS,
production runs `--workers=${API_WORKERS:-2}` (`compose.prod.yml`), and each concurrent
verification holds its whole memory cost for the duration. At 46 MiB a modest burst of
parallel sign-ins is hundreds of megabytes of transient allocation on a box that is also
running Postgres and Redis; at 19 MiB the same burst is a third of that for the same
stated defence. **Memory is the scarce resource on this deployment, so the trade-off is
taken in the direction of memory.**

`p=1` because the process serving these is a single-threaded asyncio worker: parallelism
above 1 asks for threads the event loop does not have to spare, and OWASP's own list
pairs every configuration at `p=1`.

`argon2-cffi`'s own defaults are `m=65536, t=3, p=4` (the PHC string in its README:
`$argon2id$v=19$m=65536,t=3,p=4$…`) — stronger on paper and wrong here for the same two
reasons, so they are overridden explicitly rather than inherited. The library is
25.1.0, released 2025-06-03 (pypi.org/project/argon2-cffi, read 2026-08-17), maintained
by Hynek Schlawack, and is the de-facto Python binding to the reference Argon2
implementation. Hard rule 9: adding it pulls exactly two packages
(`argon2-cffi`, `argon2-cffi-bindings`), its only transitive requirement is `cffi`,
which `cryptography` already brings, and both ship prebuilt `cp39-abi3` manylinux wheels
so nothing is built from source on install.

**PARAMETERS ARE NOT PINNED IN THE SCHEMA.** The PHC string stores them, so
`check_needs_rehash` can tell a row written under an older configuration from a current
one, and `verify_password` reports it — the caller re-hashes inside the same request
that just proved the password. Raising the cost later is therefore a constant change and
a deploy, not a migration and a forced reset.

═══ THE PEPPER, AND WHERE IT LIVES ═══

OWASP's page again: a pepper is "shared between stored passwords, rather than being
unique to an individual password like a password salt", it "should not be stored along
with the generated hash", and it wants a secrets vault or an HSM. Its value is precise
and worth stating rather than assuming: it does nothing against an attacker who has
compromised the running application, and everything against the failure this deployment
is most likely to actually have — a stolen database dump or a leaked backup. Without a
pepper such a dump is offline-crackable at whatever rate the attacker's hardware allows;
with one it is 32 bytes of unknown key away from being useless.

**IT IS DERIVED FROM `PLATFORM_KEK`, NOT STORED AS ITS OWN SETTING**, and the two
rejected alternatives are why:

  - **A `platform_secrets` row.** Disqualified by the requirement itself: that table is
    in the same database as `auth_credentials`, so the dump that takes the hashes takes
    the pepper. Encrypted at rest under the KEK, admittedly — which makes the real key
    the KEK, one indirection later, with a false sense that the pepper is separate.
  - **A ninth bootstrap environment variable.** `.env.example` argues at length that the
    bootstrap set is eight because a key belongs there only when "a process cannot reach
    the store without it", and a pepper is not that. Adding one anyway would mean the
    stated rule for that file no longer describes its contents.

`PLATFORM_KEK` is already env-only by construction — `ENV_ONLY_KEYS` excludes it from
`apply_platform_overrides`, `check_bootstrap_keys` fails CI on any change that would let
it resolve from the console store, and `core/envelope.py` records the reason in one line:
"a database holding both the lock and the key is theatre". That is the exact property a
pepper needs, already guaranteed and already tested. So the pepper is HKDF-SHA-256 of the
KEK material under a distinct `info` string (RFC 5869; NIST SP 800-108 Rev. 1 is the same
construction from the other direction), which is key separation done the standard way
rather than key REUSE.

**What this couples, said out loud**, because `core/impersonation.py` refused a derived
key on exactly this ground: rotating the KEK now also rotates the pepper. That is
survivable here in a way it would not be there, because the KEK is a RING — the retired
key still unwraps — and `pepper_ring()` walks it in the same order. A password hashed
under the outgoing pepper still verifies, and the successful verification re-hashes it
under the incoming one, so a KEK rotation drains lazily as people sign in instead of
locking anybody out. `verify_password` reports that as `needs_rehash`, indistinguishably
from an Argon2 parameter bump, which is the point: the caller has one thing to do.

**The construction is OWASP's, spelled their way**: `argon2id(base64(hmac-sha256(pepper,
password)))`. The base64 step is theirs and is kept even though Argon2 takes raw bytes
happily, so that the value entering the KDF is printable and no future backend has to
have an opinion about embedded NULs — the hazard their bcrypt example exists to route
around. SHA-256 rather than their SHA-384 because every other HMAC in this repo is
SHA-256 and one hash family is easier to keep right than two; the pepper's strength is
its secrecy and its 256-bit length, not the digest size.

═══ WHAT THIS MODULE DOES NOT DO ═══

No rate limiting, no lockout, no credential-stuffing defence: those are decisions about a
CALLER, they need Redis and an IP, and `core/ratelimit.py` already owns that vocabulary.
No user lookup, no database at all — this module takes a string and returns a string, so
every branch in it is testable without Postgres.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from apps.api.core.envelope import KekRing, kek_ring
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: OWASP Password Storage Cheat Sheet, configuration 2 of 5. See the module docstring
#: for why this one and not `m=47104, t=1, p=1`.
ARGON2_MEMORY_KIB = 19456
ARGON2_TIME_COST = 2
ARGON2_PARALLELISM = 1
#: 32-byte output and a 16-byte salt — the sizes RFC 9106 §4 recommends for both.
ARGON2_HASH_BYTES = 32
ARGON2_SALT_BYTES = 16

#: HKDF domain separation. Versioned, so that changing the construction later is a new
#: pepper generation rather than a silent reinterpretation of the same key material.
PEPPER_INFO = b"calevate/password-pepper/v1"

#: THE ABSOLUTE FLOOR, AND NO LONGER THE POLICY. `authn/policy.py::min_password_chars`
#: is the policy, it is PER REALM, and the client realm's floor is 15.
#:
#: THE COMMENT THAT USED TO BE HERE STATED THE STANDARD BACKWARDS, which is why the
#: number is now derived somewhere else. It read: "NIST SP 800-63B-4 lowers the floor to
#: 8 and recommends 15". The publication says neither half of that. It says verifiers
#: "SHALL require passwords that are used as a single-factor authentication mechanism to
#: be a minimum of 15 characters", and MAY go as low as 8 only for passwords "only used
#: as part of multi-factor authentication processes" (usnistgov/800-63-4 @
#: 4f2487bb81adecdc84ccaac6920bf0b500b379ae, `sp800-63b/authenticators/index.html`, read
#: 2026-08-26). Fifteen is a SHALL, not a recommendation; eight is a concession, not a
#: floor. The client realm has no second factor (D-170), so it was the single-factor case
#: sitting three characters under a SHALL — the exact hard-rule-11 shape, a paraphrase of
#: an outside standard trusted because it was already in our own tree.
#:
#: What survives here is the bound `_refuse_unusable` needs at the KDF itself: this
#: module takes a string and returns a string, it is called on the re-hash path where a
#: realm is not in scope, and something has to stop a 10-megabyte body reaching the HMAC.
#: It is asserted at import to be at or below every realm's floor (`policy.py`), so the
#: two layers can never disagree about the same password. Composition rules are
#: deliberately absent — §3.1.1.2 forbids them outright ("SHALL NOT impose other
#: composition rules").
MIN_PASSWORD_CHARS = 12
#: And an upper bound, because the HMAC below is linear in input length and an unbounded
#: one is a free CPU sink on an unauthenticated route. 128 is the ceiling ASVS names, and
#: is far above any passphrase a person types.
MAX_PASSWORD_CHARS = 128

#: Verified against on an unknown subject so that "no such account" and "wrong password"
#: cost the same wall-clock time. Computed once, lazily, under the real parameters — a
#: constant string would be cheap to verify and would give the timing away.
_DUMMY_PASSWORD = "calevate/timing-equalisation/not-a-credential"


@dataclass(frozen=True, slots=True)
class PasswordVerdict:
    """The answer to "is this the password", and whether the row should be rewritten.

    Two fields rather than a bare bool because the caller has two things to do and only
    one of them is authentication. `needs_rehash` is true when the stored hash was made
    under older Argon2 parameters OR under a retired pepper generation; the caller
    re-hashes inside the request that just proved the plaintext, which is the only moment
    it legitimately holds one.
    """

    ok: bool
    needs_rehash: bool


def _hasher() -> PasswordHasher:
    """This deployment's Argon2id configuration. Cheap to construct; not cached, because
    a `PasswordHasher` holds no state and caching it would be caching four integers."""
    return PasswordHasher(
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_BYTES,
        salt_len=ARGON2_SALT_BYTES,
        type=Type.ID,
    )


# HKDF-Expand-only would be the purist's call for a uniformly random 32-byte input, but
# `HKDF` (extract-then-expand) is what `cryptography` exposes as one object and the extract
# step over an already-uniform key costs one HMAC and weakens nothing. `salt` is
# deliberately absent: the input is a 256-bit uniformly random key, which is the case
# RFC 5869 §3.1 says a salt is optional for, and a salt here would be a second value to
# keep in step across deployments for no gain. The derivation itself lives in
# `_derived_ring_for` below, because it is now shared with `codes.py`.


@lru_cache(maxsize=8)
def _derived_ring_for(
    info: bytes, kek_ids: tuple[int, ...], materials: tuple[bytes, ...]
) -> tuple[bytes, ...]:
    """Cached on the KEY MATERIAL, so a rotation produces a different ring rather than a
    stale one — the same cache discipline `core/envelope._ring_for` uses.

    `kek_ids` is in the key only to keep the cache entry legible in a debugger; the
    materials alone already determine the answer.
    """
    del kek_ids
    return tuple(
        HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(material)
        for material in materials
    )


def derived_ring(info: bytes, ring: KekRing | None = None) -> tuple[bytes, ...]:
    """Every generation of ONE derived secret the KEK ring can produce, newest first.

    Element 0 is the ACTIVE generation and is the only one anything new is written under,
    which mirrors `KekRing.all_keys` exactly: a retired key unwraps and never wraps.
    Normally length 1 — a deployment that has never rotated its KEK has no retired
    generation, so a wrong password costs exactly one Argon2 verification, not two.

    `info` is what separates one derived secret from another (RFC 5869 §3.2). It is a
    PARAMETER rather than a constant because this package now derives two independent
    secrets from the same KEK — the password pepper below and `codes.py`'s key for
    low-entropy challenge codes — and deriving them under distinct `info` strings is key
    SEPARATION, whereas reusing one value for both would be key REUSE with extra steps.
    One function so the two cannot drift in construction, one string each so they cannot
    be traded for one another.
    """
    keys = (ring or kek_ring()).all_keys
    return _derived_ring_for(
        info, tuple(key.kek_id for key in keys), tuple(key.material for key in keys)
    )


def pepper_ring(ring: KekRing | None = None) -> tuple[bytes, ...]:
    """Every pepper generation a stored password hash might have been written under."""
    return derived_ring(PEPPER_INFO, ring)


def _peppered(password: str, pepper: bytes) -> bytes:
    """OWASP's construction: `base64(hmac(pepper, password))`, fed to the KDF.

    NFC-NORMALIZED FIRST, per NIST SP 800-63B-4 §3.1.1.2: "This process is applied
    before hashing the byte string that represents the password" (usnistgov/800-63-4 @
    4f2487bb81adecdc84ccaac6920bf0b500b379ae, `sp800-63b/authenticators/index.html`, read
    2026-08-26). `authn/policy.py` carries the full quotation and the argument for NFC
    over the -3 revision's NFKC.

    IT HAPPENS HERE AND NOWHERE ELSE because this is the one function both the SET path
    and the VERIFY path go through. Normalizing at either end alone would mean a password
    that hashes one way and verifies another.

    NFC is the identity on pure ASCII, so every hash already in `auth_credentials`
    verifies exactly as it did before this line existed. What it changes is the case the
    requirement is about: a Telugu or Devanagari passphrase typed on an Android IME and
    the same passphrase typed on a desktop keyboard can differ in composition alone, and
    without this they would be two different passwords.

    `unicodedata` is in the standard library, so this is not a supply-chain decision
    (hard rule 9) — which is also why the normalization is not imported from `policy`,
    whose import of `hashing` would make the pair circular.
    """
    normalized = unicodedata.normalize("NFC", password)
    return base64.b64encode(hmac.new(pepper, normalized.encode(), hashlib.sha256).digest())


def _refuse_unusable(password: str) -> None:
    """The length bounds, as a refusal a person can act on.

    Raised BEFORE any hashing, so a 10-megabyte body never reaches the HMAC. The message
    states the requirement rather than the failure ("must be at least N" reads the same
    whether you sent 3 characters or 300 and does not need to say which).
    """
    if MIN_PASSWORD_CHARS <= len(password) <= MAX_PASSWORD_CHARS:
        return
    raise ProblemError(
        kind="validation",
        code="password_length",
        title="That password cannot be used",
        detail=(
            f"A password must be between {MIN_PASSWORD_CHARS} and {MAX_PASSWORD_CHARS} characters."
        ),
        remediation=(
            "Use a passphrase of at least "
            f"{MIN_PASSWORD_CHARS} characters. There are no other rules — no required "
            "symbols, digits or capitals."
        ),
    )


def hash_password_blocking(password: str, *, ring: KekRing | None = None) -> str:
    """The PHC string for this password. SYNCHRONOUS — see `hash_password`.

    Exposed separately because the CPU cost is the whole point of the algorithm and a
    caller that is not on an event loop (a seed script, a test, a worker) should not have
    to pay for a thread hop to say so.
    """
    _refuse_unusable(password)
    return _hasher().hash(_peppered(password, pepper_ring(ring)[0]))


def verify_password_blocking(
    password: str, stored_hash: str | None, *, ring: KekRing | None = None
) -> PasswordVerdict:
    """Does this plaintext produce this stored hash? SYNCHRONOUS — see `verify_password`.

    `stored_hash=None` means "there is no such account", and it is answered by verifying
    against a dummy hash and returning False rather than by returning early. Returning
    early is a user-enumeration oracle measurable over the network: the difference between
    a 40ms answer and a 0.2ms one tells an attacker which email addresses exist, which is
    the first step of every credential-stuffing run. The dummy is hashed under the REAL
    parameters, so the two paths cost the same by construction rather than by estimate.

    A malformed stored hash (`InvalidHashError`) is a refusal, never an exception the
    caller has to remember to catch: a row somebody hand-edited must fail closed, and it
    must fail closed in the same shape as a wrong password so it cannot be probed for.

    The pepper ring is walked newest-first. A hash that verifies under a RETIRED
    generation is correct and is reported as `needs_rehash`, which is the lazy drain a
    KEK rotation relies on.
    """
    peppers = pepper_ring(ring)
    hasher = _hasher()
    if stored_hash is None:
        # Real verifications against a real hash of a real password, discarded. Not
        # `time.sleep`, which would have to guess the cost and would drift the moment the
        # parameters above change.
        #
        # ONE PER PEPPER GENERATION, matching the loop below's WORST case rather than its
        # best. The loop runs the whole ring for a wrong password and stops early for a
        # right one, so balancing against `peppers[0]` alone would be exact today (the
        # ring is one deep) and would open a narrow oracle for the days after a KEK
        # rotation: two verifications would mean "this account exists", one would mean it
        # does not. Matching the worst case costs nothing on an unrotated deployment,
        # which is every deployment except during a drain.
        for pepper in peppers:
            hasher.verify(_dummy_hash(pepper), _peppered(_DUMMY_PASSWORD, pepper))
        return PasswordVerdict(ok=False, needs_rehash=False)

    for generation, pepper in enumerate(peppers):
        try:
            hasher.verify(stored_hash, _peppered(password, pepper))
        except VerifyMismatchError:
            continue
        except InvalidHashError:
            log.error("password_hash_unreadable")
            return PasswordVerdict(ok=False, needs_rehash=False)
        except VerificationError:
            # argon2-cffi's catch-all for "the library refused this". Distinct from a
            # mismatch and from a malformed string, and it must not escape as a 500 on a
            # sign-in route.
            log.error("password_verification_failed")
            return PasswordVerdict(ok=False, needs_rehash=False)
        stale_pepper = generation > 0
        return PasswordVerdict(
            ok=True, needs_rehash=stale_pepper or hasher.check_needs_rehash(stored_hash)
        )
    return PasswordVerdict(ok=False, needs_rehash=False)


@lru_cache(maxsize=4)
def _dummy_hash(pepper: bytes) -> str:
    """A real Argon2 hash of a known non-credential, for the unknown-subject path.

    Cached because computing it costs exactly as much as the verification it is there to
    balance, and paying twice per unknown subject would make the enumeration oracle
    reappear with the sign flipped.
    """
    return _hasher().hash(_peppered(_DUMMY_PASSWORD, pepper))


async def hash_password(password: str, *, ring: KekRing | None = None) -> str:
    """`hash_password_blocking`, off the event loop.

    Argon2id at these parameters is ~20-30ms of CPU and 19 MiB of allocation on the
    target hardware. Run inline in an `async def`, that is 20-30ms during which this
    process serves nothing — not the other sign-ins, not `/healthz`, not the engine
    webhook. `asyncio.to_thread` is the same remedy `core/auth.py::_signing_key_for`
    applies to PyJWT's blocking JWKS fetch, and for the same reason: the cost is real,
    unavoidable and belongs on a worker thread. It is deliberately NOT a process pool —
    the GIL is released by the C implementation for the duration of the hash, so a thread
    is enough, and a pool would add a fork boundary to the sign-in path.
    """
    return await asyncio.to_thread(hash_password_blocking, password, ring=ring)


async def verify_password(
    password: str, stored_hash: str | None, *, ring: KekRing | None = None
) -> PasswordVerdict:
    """`verify_password_blocking`, off the event loop. See `hash_password`."""
    return await asyncio.to_thread(verify_password_blocking, password, stored_hash, ring=ring)


__all__ = [
    "ARGON2_HASH_BYTES",
    "ARGON2_MEMORY_KIB",
    "ARGON2_PARALLELISM",
    "ARGON2_SALT_BYTES",
    "ARGON2_TIME_COST",
    "MAX_PASSWORD_CHARS",
    "MIN_PASSWORD_CHARS",
    "PEPPER_INFO",
    "PasswordVerdict",
    "derived_ring",
    "hash_password",
    "hash_password_blocking",
    "pepper_ring",
    "verify_password",
    "verify_password_blocking",
]
