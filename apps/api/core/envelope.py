"""Envelope encryption for platform and tenant secrets (PLATFORM-CONFIG §3).

    PLATFORM_KEK            32 bytes, env var on the VPS — NEVER in the database
       │  wraps
       ├── DEK per secret   32 bytes, AES-256-GCM, fresh per secret VERSION
       │      │  encrypts
       │      └── the secret value
       └── PLATFORM_KEK_RETIRED   unwraps, never wraps (mirrors D-86)

This module is the ONLY place in the repo that encrypts anything, and that is
deliberate: PLATFORM-CONFIG §11 makes `tenant_secrets` reuse this module rather than
grow a second implementation, "because two ways to encrypt a secret is how one of them
ends up wrong". Nothing here knows what a secret IS — no table, no key names, no
session. It takes a string and a context and hands back bytes.

WHY ENVELOPE ENCRYPTION AT ALL, given the value could simply be encrypted under the
KEK. Because rotation is the operation this has to survive. Re-keying under a direct
scheme means decrypting and re-encrypting every secret with the new key — every
plaintext back in memory, one transaction, and a half-finished run leaves rows nobody
can read. With an envelope, a rotation re-wraps DEKs: 60 bytes per row, no plaintext
anywhere, and a row that has not been re-wrapped yet still opens under the retired key.
That is what makes §13 phase 5 a job rather than an outage.

## The library

`cryptography` (pyca) — `AESGCM` from `cryptography.hazmat.primitives.ciphers.aead`.
It is ALREADY in this tree: `apps/api/pyproject.toml` depends on `pyjwt[crypto]`, whose
`crypto` extra is exactly this package, and `uv.lock` pins it at 50.0.0. So this adds no
dependency, no new lockfile entry and no new postinstall surface (CLAUDE.md rule 9).
It is the de-facto standard for AES-GCM in Python, is FIPS-validated through OpenSSL,
and its AEAD API refuses to hand back plaintext whose tag did not verify — which is the
property every failure branch below is built on.

REJECTED: `pycryptodome` (a second crypto library beside the one PyJWT already pulls in),
`nacl`/libsodium XChaCha20-Poly1305 (a fine primitive, but a third dependency to solve a
problem AES-GCM solves with hardware acceleration on every CPU we deploy to), and
hand-rolling anything at all.

## The parameter choices, each with the authority

- **AES-256-GCM.** NIST SP 800-38D. 256-bit keys because the KEK is a long-lived key
  protecting long-lived credentials, and the cost difference is noise at this volume.
- **96-bit nonces** (SP 800-38D §5.2.1.1: 96 bits is the recommended IV length; anything
  else goes through GHASH and buys nothing). Generated from `os.urandom` per encryption,
  never reused, never derived from a counter we would have to persist.
- **The random-nonce birthday bound.** SP 800-38D §8.3 caps a single key at 2^32
  invocations when nonces are random. A DEK is used for exactly ONE encryption ever, so
  it is nowhere near the bound by construction; the KEK is used once per secret VERSION
  written, so 2^32 wraps is not a number this platform can reach. Stated rather than
  assumed, because "we generate a random nonce" is only safe with a bound attached.
- **AAD is REQUIRED, not optional** — see `seal`. It is the difference between "the
  ciphertext is intact" and "the ciphertext is intact AND belongs in this row".

## What this module refuses, and why each refusal is separate

- `platform_kek_unusable` — absent OR too short OR not decodable. To a caller those are
  one condition, "there is no usable key here", which is D-86's argument reproduced:
  failing closed on absence while accepting a weak key guards the easier half of one
  mistake.
- `platform_secret_unwrappable` — no key in the ring opens the wrapped DEK. The KEK is
  wrong, or the wrapped DEK was tampered with. Operator action: check the environment.
- `platform_secret_corrupt` — the DEK opened but the payload's tag failed. The row was
  edited, or it was moved from another key's row (the AAD catches that). Operator
  action: this is an incident, not a configuration problem.

Telling the last two apart matters. One says "you deployed with the wrong environment",
the other says "somebody wrote to your database". A single `decryption_failed` would
send an operator hunting the wrong one at the worst possible moment.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache

from calevate_shared.config import Settings
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings

log = get_logger(__name__)

#: AES-256. Exactly 32 bytes — a KEY LENGTH, not a floor.
#:
#: This is where the KEK's rule differs from `settings.MIN_HMAC_KEY_BYTES`, and the
#: difference is worth naming because the two look alike. HMAC accepts any key and gets
#: weaker as it shortens, so 32 there is a MINIMUM with three standards behind it. AES
#: accepts three key sizes and nothing else: 33 bytes is not a stronger AES-256 key, it
#: is not a key. So the check is equality, and `KEK_BYTES` is not "at least".
KEK_BYTES = 32
#: The DEK is the same primitive with the same key size.
DEK_BYTES = 32
#: 96 bits — NIST SP 800-38D §5.2.1.1's recommended IV length for GCM.
NONCE_BYTES = 12

#: The local-only KEK, for the same reason `resolve_hmac_key` has a local fallback and
#: with the same scoping: under `APP_ENV=local` a dev box must run offline with no
#: configuration, and anywhere else the absence of this variable is a loud, recoverable
#: refusal rather than a silent downgrade.
#:
#: It is PUBLIC — it is printed here — and that is exactly why it may only ever apply
#: under `local`. A fallback that applied everywhere would not be a development
#: convenience, it would be a production key with a development name.
_LOCAL_KEK_SEED = b"calevate-local-dev-platform-kek/"

# How the value is spelled in the environment. Base64 of 32 random bytes, e.g.
#   python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
#
# ONE encoding, on purpose. Accepting "base64 or hex or raw" means a 64-character hex
# string is also valid base64 (the hex alphabet is a subset), so it would decode to 48
# bytes and be refused with a message about length rather than about encoding — the
# operator would then lengthen a value that was never in the right alphabet. With one
# accepted form the refusal can say the one true thing: it must be base64 of 32 bytes,
# and here is the command that produces one.
_KEK_GENERATE_HINT = (
    'generate one with: python -c "import base64,os; '
    'print(base64.b64encode(os.urandom(32)).decode())"'
)


#: Everything "this does not open" can look like coming out of `AESGCM.decrypt`.
#:
#: `InvalidTag` is the expected one: right shape, wrong key or edited bytes. `ValueError`
#: is the one that is easy to miss and was found by a test rather than by reading — a row
#: whose `nonce` is not 8..128 bytes raises BEFORE any tag is checked, and an uncaught
#: `ValueError` there does not refuse one credential, it kills the refresh that was
#: loading ALL of them. A single malformed row (a hand-written INSERT, a truncated
#: restore) would then freeze every process's configuration, which is the failure
#: direction §6 exists to forbid.
#:
#: `ValueError` also covers the third case for free — `UnicodeDecodeError` is a subclass
#: of it, and that is what a payload decrypting to non-UTF-8 bytes raises at `.decode()`.
_UNOPENABLE = (InvalidTag, ValueError)


@dataclass(frozen=True, slots=True)
class Kek:
    """One key-encryption key and the id that names it wherever a DEK is stored.

    `kek_id` IS A FINGERPRINT OF THE KEY, not a counter an operator maintains, and this
    is the one place this module departs from the spec's wording (§5 calls the column
    `kek_version`). The reasoning, recorded because the alternative is the obvious one:

    A counter has to be bumped by hand in the same deploy that rotates the key. Forget
    it, and every row written after the rotation is stamped with the PREVIOUS
    generation's number — so §13 phase 5's rewrap job reads those rows as already
    current and skips them, and the next rotation makes them permanently unreadable.
    That is silent, unrecoverable data loss gated on somebody remembering a second
    environment variable.

    A fingerprint cannot be wrong: it is derived from the key material, so the row is
    labelled with the key that actually wrapped it, whatever anyone typed. It answers
    the question the column exists for ("which KEK wrapped this DEK?") and the question
    the rewrap job asks ("is this row under the active KEK?") exactly. What it gives up
    is ORDER — you cannot tell from two ids which is newer — and nothing here needs
    that: unwrapping tries the ring, and rewrapping compares against the active id.

    Derivation: SHA-256 over a domain-separated copy of the key, truncated to 31 bits so
    it is a positive value in a Postgres `integer`. Truncation is not a weakness here —
    a collision (~1 in 2 billion between any two keys we ever hold) would MISLABEL a row,
    and unwrapping tries every key in the ring regardless, so no row becomes unreadable.
    A preimage of the id does not yield the key: it is a 256-bit uniformly random input
    to SHA-256.
    """

    kek_id: int
    material: bytes

    def __post_init__(self) -> None:
        # A construction-time invariant rather than a check at every use: everything
        # downstream may then assume a 32-byte key without re-asking.
        if len(self.material) != KEK_BYTES:
            raise ValueError(f"a KEK is exactly {KEK_BYTES} bytes")


@dataclass(frozen=True, slots=True)
class KekRing:
    """The keys this deployment can unwrap with, and the one it wraps with.

    Same shape and same argument as the audit chain's key ring (BACKEND-PATTERNS §7):
    a chain — or here, a ciphertext — outlives the key that made it, and a verifier that
    knows only the current key reports the whole history as broken. `PLATFORM_KEK_RETIRED`
    unwraps and never wraps, exactly as `AUDIT_CHAIN_SECRET_RETIRED` verifies and never
    signs. One way per problem: the rotation story was already written, so it is reused.
    """

    active: Kek
    #: Newest first. One entry today (there is one retired slot); a tuple because §13
    #: phase 5 may want to carry two generations through a rewrap without a schema
    #: change, and a list would invite mutation of a key ring.
    retired: tuple[Kek, ...] = ()

    @property
    def all_keys(self) -> tuple[Kek, ...]:
        """Every key an unwrap may try, newest first — the active one is tried first
        because on a healthy deployment it is the one that will work."""
        return (self.active, *self.retired)


@dataclass(frozen=True, slots=True)
class Envelope:
    """One sealed secret: ciphertext, its nonce, the wrapped DEK, and which KEK wrapped it.

    The field names are the `platform_secrets` column names (§5) so phase 4's INSERT is
    a transcription rather than a translation. `kek_id` lands in the `kek_version`
    column — see `Kek` for why the value is a fingerprint.
    """

    ciphertext: bytes
    nonce: bytes
    dek_wrapped: bytes
    dek_nonce: bytes
    kek_id: int


def _decode_kek(raw: str, *, env_var: str) -> bytes:
    """Base64 → exactly 32 bytes, or a refusal an operator can act on.

    `validate=True` on the decode, so a value with stray characters is an ENCODING
    failure rather than one that silently decodes to a shorter key: the default decoder
    discards anything outside the alphabet, which would turn a mistyped key into a valid
    short one and take this branch's whole point away.
    """
    try:
        material = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise _unusable_kek(
            env_var,
            "is not valid base64",
        ) from None
    if len(material) != KEK_BYTES:
        # Length is part of being configured (D-86): a present-but-short key is refused
        # with the SAME code as an absent one, because to a caller they are one
        # condition — "there is no usable key here".
        raise _unusable_kek(
            env_var,
            f"decodes to {len(material)} bytes, and AES-256 takes exactly {KEK_BYTES}",
        )
    return material


def _unusable_kek(env_var: str, what: str) -> ProblemError:
    # Never logged with the value, and never with anything derived from it: a length or
    # a prefix is a search-space reduction on a key. The env var name is the whole
    # actionable content.
    log.error("platform_kek_unusable", extra={"env_var": env_var, "reason": what})
    return ProblemError(
        kind="dependency",
        code="platform_kek_unusable",
        title="This deployment has no usable platform key",
        detail="The key that unlocks stored credentials is missing or unusable.",
        remediation=(
            f"{env_var} {what}. It must be base64 of exactly {KEK_BYTES} random bytes — "
            f"{_KEK_GENERATE_HINT} (DEV-SETUP §4)."
        ),
    )


def _fingerprint(material: bytes) -> int:
    """A stable, positive 31-bit id for one key. See `Kek` for why this is not a counter."""
    digest = hashlib.sha256(b"calevate/platform-kek-id/v1\x00" + material).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def build_ring(*, kek: str | None, retired: str | None, app_env: str) -> KekRing:
    """The ring, from raw configured strings. PURE — a function of its arguments only.

    Pure for the reason `resolve_hmac_key` is: the caller has already loaded settings,
    and a second read here would be a second thing to keep consistent under test. Every
    failure mode in the test suite is reachable through this signature without touching
    the process environment.

    THE RETIRED KEY IS DELIBERATELY NOT LENGTH-CHECKED THE SAME WAY — it is, but the
    consequence differs and is worth stating: a retired key that cannot be decoded is
    DROPPED with a log line rather than refused, because refusing would take the whole
    deployment down over a key that only ever helps. The active key is the one whose
    absence must stop the process. (This is the same asymmetry `audit_chain_secret_retired`
    has for the same reason: you cannot lengthen a key that is already in the ledger.)
    """
    if kek:
        material = _decode_kek(kek, env_var="PLATFORM_KEK")
    elif app_env == "local":
        # Deterministic, public, and scoped to `local` — see `_LOCAL_KEK_SEED`.
        material = hashlib.sha256(_LOCAL_KEK_SEED + app_env.encode()).digest()
    else:
        raise _unusable_kek("PLATFORM_KEK", "is not set")

    retired_keys: tuple[Kek, ...] = ()
    if retired:
        try:
            retired_material = _decode_kek(retired, env_var="PLATFORM_KEK_RETIRED")
        except ProblemError:
            # Loud, and survivable. A deployment with a broken retired key can still
            # serve everything wrapped under the active one; taking the process down
            # would convert a typo in a decommissioned value into an outage.
            log.error("platform_kek_retired_unusable", extra={"env_var": "PLATFORM_KEK_RETIRED"})
        else:
            retired_keys = (Kek(kek_id=_fingerprint(retired_material), material=retired_material),)

    active = Kek(kek_id=_fingerprint(material), material=material)
    return KekRing(active=active, retired=retired_keys)


@lru_cache(maxsize=4)
def _ring_for(kek: str | None, retired: str | None, app_env: str) -> KekRing:
    """Cached on the CONFIGURED STRINGS, so a rotation produces a different ring rather
    than a stale one, and so `seal` does not run a base64 decode per call."""
    return build_ring(kek=kek, retired=retired, app_env=app_env)


def kek_ring(settings: Settings | None = None) -> KekRing:
    """This process's ring.

    The KEK is a §4 bootstrap key and can NEVER resolve from `platform_settings` — the
    store it unlocks cannot hold the key that opens it. That is enforced structurally
    rather than by this call site remembering: `core.settings.apply_platform_overrides`
    refuses every key in `ENV_ONLY_KEYS`, so a `Settings` object cannot carry a
    store-sourced `platform_kek` in the first place.
    """
    cfg = settings or get_settings()
    return _ring_for(cfg.platform_kek, cfg.platform_kek_retired, cfg.app_env)


def seal(plaintext: str, *, context: str, ring: KekRing | None = None) -> Envelope:
    """Encrypt one secret under a fresh DEK, wrapped under the active KEK.

    `context` IS REQUIRED AND IS AUTHENTICATED (it is GCM's additional authenticated
    data). It binds the ciphertext to where it belongs — `platform_secret:bolna_api_key`,
    `tenant_secret:<tenant_id>:meta_page_token` — so a row cannot be MOVED. Without it,
    an attacker with database write access could copy the ciphertext of a key they
    control into the Sarvam key's row: every tag would verify, every check would pass,
    and the platform would authenticate to a vendor account that is not ours. That is
    the AWS Encryption SDK's "encryption context" and it is the cheapest control in this
    file, which is why it is a required keyword rather than an optional one somebody
    forgets at the second call site.

    A fresh DEK per call, per §3 rule 1: the DEK belongs to a secret VERSION, and
    versions are append-only, so re-reading never re-wraps and no DEK is ever used for a
    second encryption. That is also what puts the random-nonce reuse question out of
    reach — see the module docstring's bound.
    """
    active = (ring or kek_ring()).active
    dek = os.urandom(DEK_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    dek_nonce = os.urandom(NONCE_BYTES)
    aad = context.encode()
    return Envelope(
        ciphertext=AESGCM(dek).encrypt(nonce, plaintext.encode(), aad),
        nonce=nonce,
        dek_wrapped=AESGCM(active.material).encrypt(dek_nonce, dek, aad),
        dek_nonce=dek_nonce,
        kek_id=active.kek_id,
    )


def unseal(envelope: Envelope, *, context: str, ring: KekRing | None = None) -> str:
    """Recover one secret, or refuse by name.

    The ring is tried NEWEST FIRST and the stored `kek_id` is a hint, never the
    instruction. Trial decryption is sound here for the same reason the audit chain
    dispatches per entry on which key reproduces it: AES-GCM's tag is a 128-bit MAC, so
    the wrong key fails with probability 1 - 2^-128, and "which key opened it" is an
    answer the ciphertext itself gives. Trusting the stored id instead would mean a row
    mislabelled by a bad rewrap becomes permanently unreadable, which is exactly the
    failure the fingerprint id was chosen to prevent.

    The plaintext returned here is a §3 rule 6 value: in memory, for this request, never
    logged, never traced, never in a response body. This function does not enforce that
    — nothing can, at this level — but every caller is bound by it.
    """
    keys = (ring or kek_ring()).all_keys
    aad = context.encode()
    dek: bytes | None = None
    for candidate in keys:
        try:
            dek = AESGCM(candidate.material).decrypt(envelope.dek_nonce, envelope.dek_wrapped, aad)
            break
        except _UNOPENABLE:
            continue
    if dek is None:
        log.error("platform_secret_unwrappable", extra={"keys_tried": len(keys)})
        raise ProblemError(
            kind="dependency",
            code="platform_secret_unwrappable",
            title="A stored credential could not be unwrapped",
            detail="No configured platform key opens this credential.",
            remediation=(
                "The deployment's PLATFORM_KEK is not the key this value was written "
                "under. If it was rotated, put the outgoing value in "
                "PLATFORM_KEK_RETIRED and redeploy; the rewrap job then moves the rows "
                "onto the new key."
            ),
        )
    try:
        return AESGCM(dek).decrypt(envelope.nonce, envelope.ciphertext, aad).decode()
    except _UNOPENABLE:
        # The DEK opened, so the KEK is right and the wrapping is intact — but the
        # payload's tag did not verify. Either the row was edited, or this envelope came
        # from a different context and was moved here. Both are incidents.
        log.error("platform_secret_corrupt", extra={"context": context})
        raise ProblemError(
            kind="dependency",
            code="platform_secret_corrupt",
            title="A stored credential failed its integrity check",
            detail="This credential's stored value does not verify against its own key.",
            remediation=(
                "The row was modified outside the application, or moved from another "
                "key's row. Do not overwrite it — capture it and treat this as a "
                "security incident (PLATFORM-CONFIG §10)."
            ),
        ) from None


def rewrap(envelope: Envelope, *, context: str, ring: KekRing | None = None) -> Envelope:
    """Re-wrap one envelope's DEK under the ACTIVE KEK. The payload is not touched.

    This is the operation the whole envelope design exists for (§3 rule 3): a KEK
    rotation re-wraps 32 bytes per secret version rather than re-encrypting every
    credential, so it is cheap, it needs no plaintext anywhere, and a row that has not
    been reached yet still opens under the retired key while the run is in flight.

    `ciphertext` and `nonce` are copied through UNREAD. There is deliberately no code
    path here that could decrypt a credential: a rotation must be safe to run against a
    live platform by an operator who is not entitled to read what they are re-wrapping.

    Returns a NEW envelope with a fresh `dek_nonce` — never the old one. Re-using the
    nonce while re-wrapping the same DEK under a DIFFERENT key would be harmless, and
    re-wrapping under the SAME key with the same nonce would encrypt identical plaintext
    under an identical (key, nonce) pair, which is AES-GCM's one catastrophic misuse.
    Drawing fresh removes the question rather than reasoning about which case applies.
    """
    keys = ring or kek_ring()
    aad = context.encode()
    dek: bytes | None = None
    for candidate in keys.all_keys:
        try:
            dek = AESGCM(candidate.material).decrypt(envelope.dek_nonce, envelope.dek_wrapped, aad)
            break
        except _UNOPENABLE:
            continue
    if dek is None:
        log.error("platform_secret_unwrappable", extra={"keys_tried": len(keys.all_keys)})
        raise ProblemError(
            kind="dependency",
            code="platform_secret_unwrappable",
            title="A stored credential could not be unwrapped",
            detail="No configured platform key opens this credential.",
            remediation=(
                "This row was written under a KEK this deployment no longer has. Put the "
                "outgoing value in PLATFORM_KEK_RETIRED and run the rewrap again; until "
                "then this row must not be treated as re-wrapped."
            ),
        )
    dek_nonce = os.urandom(NONCE_BYTES)
    return Envelope(
        ciphertext=envelope.ciphertext,
        nonce=envelope.nonce,
        dek_wrapped=AESGCM(keys.active.material).encrypt(dek_nonce, dek, aad),
        dek_nonce=dek_nonce,
        kek_id=keys.active.kek_id,
    )


#: Below this length a "last four" IS the secret, so there is nothing to show.
_LAST_FOUR_MIN = 8
MASKED = "••••"


def last_four(plaintext: str) -> str:
    """The ONLY plaintext fragment that may touch disk (§5), computed in ONE place.

    It exists so the console can show WHICH key is installed without being able to show
    the key. The length floor is the part that is easy to get wrong: for a short value
    the last four characters are most of it — for a four-character value they are all of
    it — so anything under eight characters is masked entirely rather than published as
    a "fragment". A stored credential that short is a misconfiguration anyway, and the
    console showing `••••` for it is a truthful answer.
    """
    return plaintext[-4:] if len(plaintext) >= _LAST_FOUR_MIN else MASKED


__all__ = [
    "DEK_BYTES",
    "KEK_BYTES",
    "MASKED",
    "NONCE_BYTES",
    "Envelope",
    "Kek",
    "KekRing",
    "build_ring",
    "kek_ring",
    "last_four",
    "rewrap",
    "seal",
    "unseal",
]
