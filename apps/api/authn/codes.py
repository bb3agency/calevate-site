"""Every secret in this package that is NOT a password: how it is minted and stored.

`hashing.py` owns passwords, which are low-entropy, human-chosen and therefore need a
deliberately slow KDF. This module owns the other two kinds — emailed link tokens and
numeric OTP challenges — which are machine-generated and need something else entirely.

═══ WHY A KEYED HASH, AND WHY IT IS NOT THE SAME ANSWER FOR ALL OF THEM ═══

The reference implementation this migration learns from (`raghava-organics-site`,
`backend/src/modules/auth/auth.service.ts`) got HALF of this right and the half it got
wrong is the more dangerous half, which is why the reasoning is written out here rather
than assumed.

**What it got right (line 897):** a password-reset token is 32 bytes from a CSPRNG, and it
stores `sha256(token)`. That is correct and this module does the same thing for the same
reason — an unkeyed digest of a 256-bit random value is irreversible in the only sense
that matters, and a slow KDF would buy nothing but a lookup that cannot use an index.

**What it got wrong (line 165):** it stores `sha256(code)` — unkeyed, unsalted — for a
code that `generateOtp()` (line 168) draws from six digits. There are 900,000 six-digit
codes. Precomputing every digest takes milliseconds and fits in a few megabytes, so a
database dump, a leaked backup, or ONE successful SQL-injection read recovers every live
OTP in the system instantly. The entropy of the secret, not the speed of the hash, is what
decides whether a digest protects anything, and nothing in that codebase distinguishes the
two cases — the same `hashToken` helper serves both.

**So the rule here is explicit and is enforced by construction:** every code this module
stores goes through an HMAC keyed by a secret that is NOT IN THIS DATABASE. The key is
derived from `PLATFORM_KEK` via `hashing.derived_ring`, under an `info` string distinct
from the password pepper's — RFC 5869 §3.2 key separation, not key reuse. `PLATFORM_KEK`
is env-only by construction and by CI (`ENV_ONLY_KEYS`, `scripts/check_bootstrap_keys.py`),
so the dump that takes the `code_hash` column does not take the key, and the 900,000-entry
rainbow table cannot be built without first compromising the host.

Keying costs one extra HMAC per verification and nothing else. The high-entropy URL tokens
are keyed too, even though they do not need it: one construction for the whole module is
easier to keep right than two, and the failure mode of the alternative — a future edit that
shortens a secret from 256 bits to something typeable, under a helper that was safe only
because of the length — is exactly the failure above, arrived at by a different route.

═══ THE RING, AND WHY A CODE SURVIVES A KEK ROTATION ═══

`derived_ring` returns every generation newest-first. New codes are always written under
generation 0; verification walks the whole ring. A KEK rotation therefore does not
invalidate the reset link somebody clicked on five minutes before the deploy. Unlike a
password, there is no lazy re-hash: these are all short-lived and single-use, so they drain
by expiry within hours rather than needing to be rewritten.

═══ THE OFF-BY-ONE, WHICH IS A REAL DEFECT AND NOT A STYLE POINT ═══

The reference's `generateOtp()` is `crypto.randomInt(100000, 999999)`. Node's `randomInt`
takes a HALF-OPEN interval, so `999999` is never returned: the function's stated range is
900,000 values and its actual range is 899,999. Nobody notices, because the missing value
is one in nine hundred thousand and no test samples the boundary. It is a defect anyway —
it is a silent contradiction between what a security-relevant function claims and what it
does, and the next such contradiction may not be harmless. `new_otp_code` below covers its
full stated range INCLUSIVE, and `tests/authn_codes_test.py` asserts the boundary by
exhausting the generator's image rather than by sampling the middle.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Final

from apps.api.authn.hashing import derived_ring
from apps.api.core.envelope import KekRing

#: HKDF domain separation, distinct from `hashing.PEPPER_INFO`. Versioned for the same
#: reason: changing the construction later must be a new generation rather than a silent
#: reinterpretation of the same key material.
CODE_KEY_INFO: Final = b"calevate/auth-code-key/v1"

#: Bytes of entropy in a token that travels in a URL. 32 bytes = 256 bits, the same
#: entropy `sessions.TOKEN_ENTROPY_BYTES` uses and far past OWASP's floor. The Forgot
#: Password Cheat Sheet asks only that the token be from a CSPRNG and "long enough to
#: protect against brute-force attacks"; this is the number the rest of this repo already
#: uses, and one number is easier to keep right than two.
TOKEN_ENTROPY_BYTES: Final = 32

#: A numeric challenge's shape. Six digits is what an emailed code has to be for a person
#: to retype it, and it is ~20 bits — which is precisely why `throttle.py` and
#: `auth_otp_challenges.attempts` exist. NIST SP 800-63B is explicit that a rate-limiting
#: mechanism is REQUIRED (SHALL) whenever an authenticator output carries fewer than 64
#: bits (pages.nist.gov/800-63-4/sp800-63b, read 2026-08-17).
OTP_DIGITS: Final = 6
#: INCLUSIVE bounds. Spelled as constants rather than inlined so the test can assert
#: against the same numbers the generator reads — see the module docstring on why the
#: boundary is the interesting part.
OTP_MIN: Final = 10 ** (OTP_DIGITS - 1)
OTP_MAX: Final = 10**OTP_DIGITS - 1


def _code_key_ring(ring: KekRing | None = None) -> tuple[bytes, ...]:
    """Every generation of the code key, newest first. See the module docstring."""
    return derived_ring(CODE_KEY_INFO, ring)


def _fingerprint_under(key: bytes, *, domain: str, secret: str) -> bytes:
    """`HMAC-SHA256(key, domain || 0x00 || secret)`.

    The domain is INSIDE the MAC, never merely beside it in a column, for the reason
    `sessions.token_fingerprint` gives about the realm: a purpose you have to remember to
    filter on is one forgotten predicate away from a verification token being redeemable
    as a password reset. Here it makes that confusion arithmetic — the stored fingerprint
    of an `email_verify` token computed under `password_reset` is different 32 bytes, and
    there is no row the reset lookup could match.

    The `\\x00` separator makes the encoding unambiguous: without it, domain `"ab"` with
    secret `"c"` and domain `"a"` with secret `"bc"` would MAC identically, and the
    purposes in this package share prefixes.
    """
    return hmac.new(key, domain.encode() + b"\x00" + secret.encode(), hashlib.sha256).digest()


def code_fingerprint(secret: str, *, domain: str, ring: KekRing | None = None) -> bytes:
    """What we store instead of the code, under the ACTIVE key generation."""
    return _fingerprint_under(_code_key_ring(ring)[0], domain=domain, secret=secret)


def code_fingerprints(secret: str, *, domain: str, ring: KekRing | None = None) -> list[bytes]:
    """Every fingerprint this code could have been stored under, newest generation first.

    Verification looks the code up by EACH of these rather than re-MACing the stored value,
    which keeps the lookup an indexed equality on `code_hash`. Normally a one-element list:
    a deployment that has never rotated its KEK has exactly one generation.
    """
    return [_fingerprint_under(key, domain=domain, secret=secret) for key in _code_key_ring(ring)]


def new_url_token() -> str:
    """A fresh high-entropy secret for an emailed link. URL-safe, so it survives a query
    string unencoded."""
    return secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def new_otp_code() -> str:
    """A uniformly random 6-digit code, covering `OTP_MIN..OTP_MAX` INCLUSIVE.

    `secrets.randbelow(n)` yields `[0, n)`, so the span has to be `MAX - MIN + 1` for `MAX`
    itself to be reachable. That `+ 1` is the whole of reference defect
    `auth.service.ts:168` — `crypto.randomInt(100000, 999999)` never returns 999999,
    because Node's max is exclusive — and the test that guards it exhausts the image of
    this function rather than sampling it, because a one-in-900,000 omission is invisible
    to any sampling test anyone would actually write.

    `secrets.randbelow` rather than `random.randrange`: this is a credential, and
    `random` is a Mersenne Twister whose internal state is recoverable from its output.
    It is also rejection-sampled internally, so the distribution is uniform rather than
    modulo-biased — the defect that would otherwise make the low codes slightly likelier.
    """
    span = OTP_MAX - OTP_MIN + 1
    return f"{OTP_MIN + secrets.randbelow(span):0{OTP_DIGITS}d}"


__all__ = [
    "CODE_KEY_INFO",
    "OTP_DIGITS",
    "OTP_MAX",
    "OTP_MIN",
    "TOKEN_ENTROPY_BYTES",
    "code_fingerprint",
    "code_fingerprints",
    "new_otp_code",
    "new_url_token",
]
