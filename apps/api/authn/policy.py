"""What a string has to be before it is allowed to become somebody's password.

`hashing.py` is the KDF and `credentials.py` is the store. Neither of them has an
opinion about whether a password is a GOOD one, and until this module existed nothing
did: the only rule in the system was `12 <= len(password) <= 128`, applied identically
to both realms, with no comparison against anything.

Two requirements of NIST SP 800-63B-4 §3.1.1.2 were unmet by that, and both are SHALLs.
The text below is quoted from the publication's own source repository — `usnistgov/
800-63-4` at commit `4f2487bb81adecdc84ccaac6920bf0b500b379ae` (committed 2025-08-26),
file `sp800-63b/authenticators/index.html`, read 2026-08-26. It is quoted rather than
paraphrased because the previous paraphrase in `hashing.py` was wrong in a way that
mattered — see MINIMUM LENGTH below.

═══ MINIMUM LENGTH: 15, NOT 12, ON EVERY REALM WITHOUT A SECOND FACTOR ═══

    "Verifiers and CSPs SHALL require passwords that are used as a single-factor
    authentication mechanism to be a minimum of 15 characters in length. Verifiers and
    CSPs MAY allow passwords that are only used as part of multi-factor authentication
    processes to be shorter but SHALL require them to be a minimum of eight characters
    in length."

`hashing.MIN_PASSWORD_CHARS` was 12 for both realms, above a comment reading "NIST SP
800-63B-4 lowers the floor to 8 and recommends 15". That reads the sentence backwards.
Eight is not a floor the publication offers freely — it is the concession for passwords
"only used as part of multi-factor authentication processes" — and fifteen is not a
recommendation, it is the SHALL for everything else.

Which of the two applies is a property of the REALM, and this repo already knows it:
`service.MFA_REQUIRED_REALMS` is `{"admin"}` (D-170), so an admin password is one factor
of two and a CLIENT password is the whole of the authentication. The client realm was
therefore the single-factor case sitting three characters under a SHALL, and the admin
realm — the one that looks stricter — was the one comfortably compliant.

So the floor is per realm, and the table below is the only place it is written down.
`tests/authn_password_policy_test.py` derives the requirement from
`service.MFA_REQUIRED_REALMS` rather than restating 15, so adding a realm, or giving the
client realm a second factor, moves the assertion with it instead of leaving a number
here that nobody rechecks.

Admin stays at 12 rather than dropping to the permitted 8: nothing requires us to spend
the concession, and 12 is what those accounts already have.

═══ THE BLOCKLIST: REQUIRED, AND PREVIOUSLY ABSENT ENTIRELY ═══

    "When processing a request to establish or change a password, verifiers SHALL
    compare the prospective secret against a blocklist that contains known commonly
    used, expected, or compromised passwords. The entire password SHALL be subject to
    comparison, not substrings or words that might be contained therein."

    "If the chosen password is found on the blocklist, the CSP SHALL require the
    subscriber to select a different secret and SHALL provide the reason for rejection."

**"The entire password SHALL be subject to comparison, not substrings"** is the sentence
that shapes every rule in this file, and it is a constraint in BOTH directions. It
forbids the tempting implementation — reject anything CONTAINING "calevate" or the
user's name — because that rejects `calevate-is-where-i-work-now`, which is a fine
passphrase, and it is the rule that makes blocklists infuriating. Every predicate below
therefore consumes the whole normalized string and nothing less.

**WHAT IS NOT HERE, SAID PLAINLY RATHER THAN IMPLIED: A BREACH CORPUS.** NIST's list of
what a blocklist "may include" has three entries — passwords from previous breach
corpuses, dictionary words, and context-specific words — and only the second and third
are implemented here. The first is not, and the reason is environmental rather than a
judgement: the two hosts that serve one are egress-blocked from this environment
(`raw.githubusercontent.com` answers 404 for SecLists' `Common-Credentials` paths and
`api.pwnedpasswords.com` answers `403` on CONNECT, both measured 2026-08-26), so a
corpus could only have been TYPED, and a hand-typed list of "the most common breached
passwords" is exactly the unverified-fact-with-an-authoritative-look that hard rule 11
exists about. Bundling a fabricated one would be worse than bundling none, because the
next reader would trust it.

⚠ **OPERATIONS: the breach-corpus half of this control is OPEN**, and there is
deliberately no placeholder for it. An empty `_CORPUS: frozenset[str] = frozenset()` with
a `candidate in _CORPUS` branch above it was written here first and then removed: it is a
container that cannot match and a branch that cannot be taken, which reads to the next
person as a control that exists, and to the coverage ratchet as an untestable line. A gap
named in prose is honest; a gap wearing an implementation is not.

What closes it is a list obtained from a named source — SecLists'
`10-million-password-list-top-*.txt` at a pinned commit, or HIBP's k-anonymity range API
— filtered to entries at or above `min_password_chars("client")`, since the appendix
notes a blocklist "only needs to include entries that meet that requirement". It lands as
one more predicate in `_reason_blocked`, beside the three that are there, with the same
whole-password discipline and its provenance in the comment above it.

The appendix's own limit is worth carrying too, because it is an argument against
gold-plating this later:

    "Excessively large blocklists are of little incremental security benefit because the
    blocklist is used to defend against online attacks, which are already limited by the
    throttling requirements described in Sec. 3.2.2."

`throttle.PASSWORD_BUDGET` is that throttling: ten consecutive failures per account per
fifteen minutes. The blocklist only has to cover what an attacker would reach inside
that budget.

═══ NORMALIZATION ═══

    "If Unicode characters are accepted in passwords, the verifier SHOULD apply the
    normalization process for stabilized strings using the Normalization Form Canonical
    Composition (NFC) normalization defined in Sec. 12.1 of Unicode Normalization Forms
    [UAX15]. This process is applied before hashing the byte string that represents the
    password."

**NFC, not NFKC.** The -3 revision said "either the NFKC or NFKD normalization" and
that older wording is what most implementations carry; -4 names NFC specifically, and
-4 is the revision in force. The difference is not cosmetic for this product's
population: NFKC is the COMPATIBILITY composition, which folds `ﬁ` to `fi` and — the one
that matters on a Telugu-first product — rewrites characters that a person typing Indic
script may have entered deliberately. NFC composes canonical equivalents and changes
nothing else, which is the whole of what the requirement is for: the same keystrokes on
an Android IME and on a desktop keyboard produce the same bytes.

It is applied in `hashing._peppered`, not here, because it must happen on the VERIFY path
as well as the SET path and `hashing` is the only thing both go through. This module
normalizes too, so that its own length count and its blocklist comparison see the same
string the KDF will.

NFC is the identity on pure ASCII, so no stored hash changes meaning: every password in
this system today verifies exactly as before.

═══ WHERE THIS IS ENFORCED ═══

`credentials.set_password` — the ONE writer of `auth_credentials.password_hash` — calls
`assert_password_allowed` before it hashes. Enforcing at the store rather than at each of
the four routes that reach it (invitation accept, reset confirm, admin bootstrap, the dev
seed) is deliberate: this is precisely the class of rule the reference implementation
applied per-endpoint by whoever remembered, which is how `subjects.py`'s enumeration
oracle happened. There is no path to a stored password that does not pass through here.

**IT IS NOT ENFORCED ON VERIFY, AND MUST NOT BE.** `credentials.authenticate_subject`
already carries the argument in full: a rule that arrives after a password was set must
never turn a correct sign-in into a refusal. Raising the client floor from 12 to 15
locks nobody out — it changes what may be STORED, not what may be PRESENTED — and the
existing re-hash guard already swallows the `ProblemError` this module can now raise on
the upgrade path.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from apps.api.authn.hashing import MAX_PASSWORD_CHARS, MIN_PASSWORD_CHARS
from apps.api.authn.models import AUTHN_REALMS
from apps.api.core.errors import ProblemError

#: The NIST single-factor floor. Applies to every realm whose password is the whole of
#: the authentication — see the module docstring.
SINGLE_FACTOR_MIN_CHARS: Final = 15

#: Per-realm minimum length. The client realm has no second factor (D-170:
#: `service.MFA_REQUIRED_REALMS` is `{"admin"}`), so its password is single-factor and
#: takes the 15-character SHALL. The admin realm's password is one factor of two and
#: could take the permitted 8; it keeps 12, which is what those accounts already have.
MIN_CHARS_BY_REALM: Final[dict[str, int]] = {
    "client": SINGLE_FACTOR_MIN_CHARS,
    "admin": 12,
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


def min_password_chars(realm: str) -> int:
    """This realm's minimum password length.

    An unknown realm raises rather than defaulting, because every default here is a
    guess about whether a second factor exists, and guessing "yes" silently exempts a new
    realm from the SHALL that this module was written to satisfy.
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
    if _is_keyboard_walk(candidate):
        return "It is a straight run of keys along the keyboard."
    if _is_repetition(candidate):
        return "It is one short sequence repeated."
    return None


def assert_password_allowed(password: str, *, realm: str, email: str | None = None) -> None:
    """The whole policy, as one refusal a person can act on. Raises `ProblemError`.

    Called by `credentials.set_password` and by nothing else — see the module docstring
    on why the store and not the four routes above it.

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
    "SERVICE_WORDS",
    "SINGLE_FACTOR_MIN_CHARS",
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
