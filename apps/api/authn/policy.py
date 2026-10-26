"""What a string has to be before it is allowed to become somebody's password.

`hashing.py` is the KDF and `credentials.py` is the store. Neither has an opinion about
whether a password is a GOOD one; this module does. The rules below follow NIST SP
800-63B-4 §3.1.1.2, quoted from the publication's source repository — `usnistgov/800-63-4`
at commit `4f2487bb81adecdc84ccaac6920bf0b500b379ae` (committed 2025-08-26), file
`sp800-63b/authenticators/index.html`, read 2026-08-26 — in every respect but one.

═══ MINIMUM LENGTH: 8 ON EVERY REALM (D-765) ═══

The founder decided on 13 Oct 2026 that eight characters is the minimum across Calevate,
on the client and admin realms alike. That is a deliberate departure from §3.1.1.2:

    "Verifiers and CSPs SHALL require passwords that are used as a single-factor
    authentication mechanism to be a minimum of 15 characters in length. Verifiers and
    CSPs MAY allow passwords that are only used as part of multi-factor authentication
    processes to be shorter but SHALL require them to be a minimum of eight characters
    in length."

The admin realm's password is one factor of two (`service.MFA_REQUIRED_REALMS` is
`{"admin"}`, D-170), so 8 is within the standard there. The client realm has no second
factor, so its password is single-factor and 8 is under the 15 the standard requires. The
founder accepted that. What stands between an 8-character client password and an online
guesser is:

  - the blocklist in this module (SecLists' 100k most-used passwords, context words,
    keyboard walks, repetition — see below);
  - `throttle.PASSWORD_BUDGET`: ten consecutive failures per account and source per fifteen
    minutes, under `PASSWORD_ACCOUNT_CEILING` (100 an hour) for the account as a whole;
  - `service.SIGN_IN_FAILURE_FLOOR_S`: every failed sign-in takes at least that long.

None of these protects a stolen database dump; the Argon2id cost and the KEK-derived
pepper in `hashing.py` are what do.

`min_password_chars(realm)` stays the single reader, so a realm can be given its own floor
again without touching any caller.

═══ THE BLOCKLIST ═══

    "When processing a request to establish or change a password, verifiers SHALL
    compare the prospective secret against a blocklist that contains known commonly
    used, expected, or compromised passwords. The entire password SHALL be subject to
    comparison, not substrings or words that might be contained therein."

    "If the chosen password is found on the blocklist, the CSP SHALL require the
    subscriber to select a different secret and SHALL provide the reason for rejection."

**"The entire password SHALL be subject to comparison, not substrings"** constrains in
BOTH directions. It forbids rejecting anything CONTAINING "calevate" or the user's name —
that refuses `calevate-is-where-i-work-now`, a fine passphrase — so every predicate below
consumes the whole normalized string and nothing less.

**THE BREACH CORPUS.** NIST's list of what a blocklist "may include" has three entries —
passwords from previous breach corpuses, dictionary words, and context-specific words.
Context words and the structural rules (walks, repetition) are predicates below; the
breach corpus is SecLists' `100k-most-used-passwords-NCSC.txt`, vendored byte-exact under
`blocklist/` and hash-pinned (`COMMON_PASSWORDS_SHA256`). It is a file in the image rather
than HIBP's range API because a sign-up must not send any derivative of a password to a
third party, and the online check would add a subprocessor and a network dependency to
the one path that must never be down. The appendix notes a blocklist "only needs to
include entries that meet that requirement", so entries shorter than the lowest realm
floor are dropped at load; the rest are compared whole, NFC and casefolded, exactly like
the candidate.

The appendix's own limit argues against gold-plating:

    "Excessively large blocklists are of little incremental security benefit because the
    blocklist is used to defend against online attacks, which are already limited by the
    throttling requirements described in Sec. 3.2.2."

═══ NORMALIZATION ═══

    "If Unicode characters are accepted in passwords, the verifier SHOULD apply the
    normalization process for stabilized strings using the Normalization Form Canonical
    Composition (NFC) normalization defined in Sec. 12.1 of Unicode Normalization Forms
    [UAX15]. This process is applied before hashing the byte string that represents the
    password."

**NFC, not NFKC.** The -3 revision allowed NFKC/NFKD and most implementations still carry
it; -4 names NFC. NFKC is the COMPATIBILITY composition, which folds `ﬁ` to `fi` and can
rewrite characters a person typing Indic script entered deliberately. NFC only composes
canonical equivalents, which is all the requirement is for: the same keystrokes on an
Android IME and on a desktop keyboard produce the same bytes.

It is applied in `hashing._peppered`, not here, because it must happen on the VERIFY path
as well as the SET path and `hashing` is the only thing both go through. This module
normalizes too, so its length count and blocklist comparison see the string the KDF will.
NFC is the identity on pure ASCII.

═══ WHERE THIS IS ENFORCED ═══

`credentials.set_password` — the ONE writer of `auth_credentials.password_hash` — calls
`assert_password_allowed` before it hashes. Enforcing at the store rather than at each
route that reaches it (invitation accept, reset confirm, sign-up, admin bootstrap, password
change, the dev seed) means no route can forget it.

**IT IS NOT ENFORCED ON VERIFY, AND MUST NOT BE.** A rule that arrives after a password
was set must never turn a correct sign-in into a refusal (`credentials.authenticate_subject`
carries the argument): the policy governs what may be STORED, not what may be PRESENTED.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Final

from apps.api.authn.hashing import MAX_PASSWORD_CHARS, MIN_PASSWORD_CHARS
from apps.api.authn.models import AUTHN_REALMS
from apps.api.core.errors import ProblemError

#: The minimum on every realm (D-765). Below SP 800-63B-4's single-factor 15 on the client
#: realm, by founder decision — see the module docstring for what compensates.
PASSWORD_MIN_CHARS: Final = 8

#: Per-realm minimum length, read only through `min_password_chars`.
MIN_CHARS_BY_REALM: Final[dict[str, int]] = {
    "client": PASSWORD_MIN_CHARS,
    "admin": PASSWORD_MIN_CHARS,
}

#: Context-specific words NIST names explicitly ("the name of the service"). Compared as
#: whole passwords and as whole DERIVATIVES (see `_context_tokens`), never as substrings.
SERVICE_WORDS: Final[frozenset[str]] = frozenset({"calevate", "calevate.tech"})

#: Keyboard walks, as full rows. A password is refused when it is a contiguous slice of
#: one of these (or of one reversed) — that is a whole-password test, not a substring
#: test: `qwertyuiopasdfgh` is refused, `my-qwerty-mug-fell` is not.
_KEYBOARD_ROWS: Final[tuple[str, ...]] = (
    "`1234567890-=",
    "qwertyuiop[]\\",
    "asdfghjkl;'",
    "zxcvbnm,./",
    # The rows read as one continuous walk, which is how `qwertyuiopasdfghjkl` is typed.
    "qwertyuiop[]\\asdfghjkl;'zxcvbnm,./",
    "1234567890qwertyuiopasdfghjklzxcvbnm",
    "abcdefghijklmnopqrstuvwxyz",
    "01234567890123456789",
)

#: Trailing decoration a person adds to reach a length requirement. Used ONLY to decide
#: whether a whole password is a bare context word wearing a suffix — `calevate2026!`
#: is `calevate` plus this, `calevate-runs-my-clinic` is not.
_DECORATION_RE: Final = re.compile(r"^[\W\d_]*$", re.UNICODE)


def normalize(password: str) -> str:
    """NFC, per SP 800-63B-4 §3.1.1.2. The identity on pure ASCII.

    Shared with `hashing._peppered` so that the string this module measures and compares
    is byte-for-byte the string the KDF consumes. A policy that judged one form and
    hashed another would refuse passwords it had just accepted, and vice versa.
    """
    return unicodedata.normalize("NFC", password)


#: SecLists `Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt` at commit
#: `3a5f62f0e18a1b8a36b25399aff0077f3706e5af` (MIT; `blocklist/LICENSE-SecLists-MIT.txt`),
#: 99,840 lines, fetched 13 Oct 2026. The hash makes a truncated or edited copy fail at
#: import, so the image cannot start with a blocklist that silently matches less.
COMMON_PASSWORDS_PATH: Final = (
    Path(__file__).parent / "blocklist" / "100k-most-used-passwords-NCSC.txt"
)
COMMON_PASSWORDS_SHA256: Final = "c2e5696882c603b76bb67a47ee970897e5a76fc4c3f5547abe3d0ca340c576e0"


def load_common_passwords(path: Path, *, sha256: str) -> frozenset[str]:
    """The corpus as comparable entries: NFC, casefolded, at least the lowest realm floor."""
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise RuntimeError(f"{path.name} does not match its pinned sha256; restore it from git")
    floor = min(MIN_CHARS_BY_REALM.values())
    entries = (normalize(line).casefold() for line in raw.decode("utf-8").splitlines())
    return frozenset(entry for entry in entries if len(entry) >= floor)


COMMON_PASSWORDS: Final = load_common_passwords(
    COMMON_PASSWORDS_PATH, sha256=COMMON_PASSWORDS_SHA256
)


def min_password_chars(realm: str) -> int:
    """This realm's minimum password length.

    An unknown realm raises rather than defaulting: a new realm gets a floor by decision,
    not by inheriting one.
    """
    if realm not in AUTHN_REALMS:
        raise ValueError(f"{realm!r} is not an authentication realm ({', '.join(AUTHN_REALMS)})")
    return MIN_CHARS_BY_REALM[realm]


def _context_tokens(email: str | None) -> frozenset[str]:
    """The words THIS subject is likely to reach for: the service, and their own address.

    NIST names "the name of the service, the username, and derivatives thereof". The
    username here is the email address — the only identifier this product signs anyone in
    with — so the local part, the full address, and each label of the domain all count.

    Short labels are dropped: a two-letter domain label like `in` would make every
    password that happens to equal a decorated `in` refused, which is noise rather than
    defence, and the length floor already excludes anything that short on its own.
    """
    tokens = set(SERVICE_WORDS)
    if email:
        address = normalize(email).strip().casefold()
        local, _, domain = address.partition("@")
        candidates = {address, local, domain, *domain.split(".")}
        tokens |= {token for token in candidates if len(token) >= 4}
    return frozenset(tokens)


def _is_decorated(candidate: str, token: str) -> bool:
    """Is `candidate` exactly `token` with padding added to reach a length rule?

    Whole-password by construction: the candidate must START with the token and every
    remaining character must be a digit, a symbol or an underscore. `calevate2026!` and
    `calevate________` are refused; `calevatecalevate` and `calevate-my-clinic` are not,
    because letters after the token make it a different word rather than a decorated one.
    """
    if not candidate.startswith(token):
        return False
    return bool(_DECORATION_RE.match(candidate[len(token) :]))


def _is_keyboard_walk(candidate: str) -> bool:
    """Is the whole password a straight run along one of `_KEYBOARD_ROWS`?"""
    return any(candidate in row or candidate in row[::-1] for row in _KEYBOARD_ROWS)


def _is_repetition(candidate: str) -> bool:
    """Is the whole password one short unit repeated — `aaaa…`, `abcabcabc…`, `12341234`?

    The unit is bounded at four characters: beyond that the "repetition" is a passphrase
    with a repeated word in it, which is a different (and much stronger) thing.
    """
    for size in range(1, 5):
        unit = candidate[:size]
        if len(candidate) <= size:
            continue
        if (unit * (len(candidate) // size + 1))[: len(candidate)] == candidate:
            return True
    return False


def _reason_blocked(password: str, *, email: str | None) -> str | None:
    """Which blocklist rule this password trips, or `None`.

    Returns the REASON rather than a bool because §3.1.1.2 requires one: "the CSP SHALL
    ... provide the reason for rejection", and a bare "not allowed" is the refusal that
    sends people to `Password1!`.
    """
    candidate = normalize(password).casefold()
    for token in _context_tokens(email):
        if _is_decorated(candidate, token):
            return (
                "It is built from your email address or the name of this service, which "
                "is the first thing an attacker tries."
            )
    if candidate in COMMON_PASSWORDS:
        return "It is one of the most common passwords, so it is among the first ones guessed."
    if _is_keyboard_walk(candidate):
        return "It is a straight run of keys along the keyboard."
    if _is_repetition(candidate):
        return "It is one short sequence repeated."
    return None


def assert_password_allowed(password: str, *, realm: str, email: str | None = None) -> None:
    """The whole policy, as one refusal a person can act on. Raises `ProblemError`.

    Called by `credentials.set_password` and by nothing else — see the module docstring
    on why the store and not the routes above it.

    Both refusals carry `remediation` naming what to do next, which §3.1.1.2 also
    requires ("Verifiers SHALL offer guidance to the subscriber to help the subscriber
    choose a strong password. This is particularly important following the rejection of a
    password on the blocklist as it discourages trivial modifications of listed weak
    passwords"). Neither says what was WRONG with the specific characters, because that
    is the guidance that produces `Password1!`; both say "longer, and not built out of
    something guessable", which is the advice that produces a passphrase.
    """
    floor = min_password_chars(realm)
    normalized = normalize(password)
    # Code points, not bytes and not grapheme clusters: "Each Unicode code point SHALL be
    # counted as a single character when evaluating password length" (§3.1.1.2). `len` on
    # a Python `str` is exactly that.
    if not floor <= len(normalized) <= MAX_PASSWORD_CHARS:
        raise ProblemError(
            kind="validation",
            code="password_length",
            title="That password cannot be used",
            detail=f"A password must be between {floor} and {MAX_PASSWORD_CHARS} characters.",
            remediation=(
                f"Use a passphrase of at least {floor} characters — three or four "
                "unrelated words is enough. There are no other rules: no required "
                "symbols, digits or capitals."
            ),
            fields=[{"field": "password", "rule": "min_length", "message": f"at least {floor}"}],
        )
    reason = _reason_blocked(password, email=email)
    if reason is None:
        return
    raise ProblemError(
        kind="validation",
        code="password_unacceptable",
        title="Choose a different password",
        detail=f"That password cannot be used. {reason}",
        remediation=(
            "Pick three or four unrelated words instead — they are far harder to guess "
            "and much easier to remember than a short password with symbols in it."
        ),
        fields=[{"field": "password", "rule": "blocklist", "message": reason}],
    )


__all__ = [
    "MIN_CHARS_BY_REALM",
    "PASSWORD_MIN_CHARS",
    "SERVICE_WORDS",
    "assert_password_allowed",
    "min_password_chars",
    "normalize",
]

# `MIN_PASSWORD_CHARS` is imported for this assertion and for nothing else: it is the
# ABSOLUTE bound `hashing._refuse_unusable` applies at the KDF, and it must stay at or
# below every realm's floor or the two layers would disagree about the same password —
# the boundary would accept what the store then refuses, or the store would hash
# something the KDF guard rejects. Checked at import so the drift cannot ship.
assert min(MIN_CHARS_BY_REALM.values()) >= MIN_PASSWORD_CHARS, (
    "hashing.MIN_PASSWORD_CHARS must be <= every realm's floor in MIN_CHARS_BY_REALM"
)
assert set(MIN_CHARS_BY_REALM) == set(AUTHN_REALMS), (
    "every authentication realm needs a password floor"
)
