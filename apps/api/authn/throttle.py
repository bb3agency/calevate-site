"""Failed-attempt budgets: what stops online guessing without becoming a DoS lever.

`core/ratelimit.py` already bounds how many REQUESTS a caller may make — the `auth`
profile is 20/minute per caller and every `/v1/auth/**` path is under it. That is a
volume control and it is not enough on its own: it counts requests regardless of outcome,
so it treats a person who typed their password wrong twice exactly like an attacker
grinding a dictionary from a botnet, and it is keyed on the CALLER, which an attacker with
a thousand addresses simply spreads across.

This module adds the dimension the limiter cannot express: **consecutive FAILURES against
one account**, and a small hard budget for the one low-entropy secret this system has (the
emailed OTP code). It is a second mechanism rather than a wider profile because the two answer
different questions, and CLAUDE.md's "one way per problem" is satisfied by them not
overlapping: the limiter never looks at outcomes, and nothing here counts successes.

═══ LOCKOUT vs THROTTLING, AND WHY THIS IS A DECAYING THROTTLE ═══

OWASP's Authentication Cheat Sheet (github.com/OWASP/CheatSheetSeries,
`cheatsheets/Authentication_Cheat_Sheet.md`, read 2026-08-17) is clear that the counter
should attach to the ACCOUNT rather than the source address, because an IP-keyed counter is
defeated by any distributed attacker. It describes lockout as three parameters — threshold,
observation window, duration — and mentions exponential backoff starting at one second, and
it explicitly warns about the other side: a durable account lockout is a denial-of-service
primitive that anybody can aim at a known address. It suggests at most two or three
temporary lockouts before a permanent one.

NIST SP 800-63B (pages.nist.gov/800-63-4/sp800-63b, read 2026-08-17) puts a hard ceiling
under the same idea: a verifier SHALL limit consecutive failed attempts on one account to
no more than 100, and lower limits are permitted. It also names the mitigation for the DoS
side — an increasing wait rather than a hard stop — and requires rate limiting outright
whenever an authenticator output carries fewer than 64 bits of entropy, which is exactly
the OTP case below — and, since the OTP IS this product's second factor (D-170), the single
most important budget in this file.

**So the design here is: a decaying counter with an increasing delay, never a durable
lock.** AUTH-MIGRATION §2.3 already committed to this shape — "a durable lockout counter is
a denial-of-service primitive an attacker can aim at a known account" — and this module is
that decision implemented. Concretely:

* the counter lives in Redis with a TTL, so it decays on its own and there is nothing for
  an operator to unlock at 3am and nothing for an attacker to leave stuck;
* passing the threshold produces a 429 with `Retry-After`, not a disabled account, so the
  legitimate owner's next attempt after the window simply works;
* a SUCCESSFUL authentication clears the counter, which is what makes "consecutive" mean
  consecutive and is why a person who gets it right on the fourth try is never affected.

**Rejected: a `failed_attempts` column on `auth_credentials`.** It is the obvious
alternative and it is worse in both directions. It survives restarts, which sounds like a
feature and is the DoS: an attacker who wants an operator locked out at a known address can
achieve it permanently and we would have to build an unlock surface. And it is a row write
per failed password, on the one path an attacker controls the volume of.

**What Redis being down means, and why this one fails CLOSED.** `core/ratelimit.consume`
fails OPEN by default and that is right for it — a limiter outage must not 500 the
platform. This is the opposite case, and it takes the same `fail_open=False` escape hatch
`tenancy/signup.py` already uses for the same reason: with Redis gone, nothing else bounds
password guessing, and an authentication endpoint that is unavailable is a much smaller
incident than one that is unguarded. The other three surfaces in this repo that made this
choice made it identically, so the reader meets one policy rather than four.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis

log = get_logger(__name__)

#: Redis namespace. Distinct from `ratelimit.KEY_PREFIX` so the two mechanisms cannot
#: collide and so an operator reading `KEYS calevate:authn:*` sees exactly one thing.
KEY_PREFIX: Final = "calevate:authn:fail"


@dataclass(frozen=True, slots=True)
class Budget:
    """One failure budget: how many, over how long, and how long the penalty lasts."""

    name: str
    #: Consecutive failures tolerated before the next attempt is refused.
    threshold: int
    #: How long the counter survives without a new failure. Also the penalty duration,
    #: because a counter that has expired IS the lock being lifted — one number, one
    #: concept, nothing to keep in step.
    window_s: int


#: PASSWORD. Ten consecutive wrong passwords in fifteen minutes, per account per realm.
#:
#: Ten rather than five because the population is SMB owners on phones and a floor that
#: bites on a genuine typo run is a floor that generates support calls; ten rather than
#: NIST's ceiling of 100 because 100 online guesses against a 12-character minimum is
#: already meaningless to an attacker and 10 is meaningless to a person. Fifteen minutes
#: is the observation window AND the penalty: long enough that grinding costs an attacker
#: 40 guesses an hour, short enough that a locked-out owner is not phoning anybody.
PASSWORD_BUDGET: Final = Budget("password", threshold=10, window_s=900)

#: EMAILED OTP — AND THIS PRODUCT'S ONLY SECOND FACTOR (D-170). Five guesses per account
#: per ten minutes.
#:
#: This one is the arithmetic that matters, because the secret is ~20 bits. Five guesses
#: against 900,000 codes is a 1-in-180,000 chance per challenge; the per-challenge
#: `auth_otp_challenges.attempts` ceiling bounds it again on the row, so an attacker who
#: could reset Redis still cannot spend more than `OTP_MAX_ATTEMPTS` on one code. Two
#: independent counters for one secret, which is what NIST's SHALL is asking for.
OTP_BUDGET: Final = Budget("otp", threshold=5, window_s=600)

#: Per-CHALLENGE ceiling, enforced on the row rather than in Redis. See `OTP_BUDGET`.
OTP_MAX_ATTEMPTS: Final = 5


def _key(budget: Budget, realm: str, subject_id: UUID) -> str:
    return f"{KEY_PREFIX}:{budget.name}:{realm}:{subject_id}"


def _refused(budget: Budget, retry_after_s: int) -> ProblemError:
    """The refusal, which deliberately does NOT say whether the account exists.

    Reached only for a subject that resolved, so on its face it is already an existence
    signal — which is why `service.py` never calls `check` before it has decided to spend
    an attempt, and why the unknown-subject path in `service.py` consumes a budget against
    a STABLE PSEUDO-SUBJECT derived from the identifier instead. Both paths therefore
    produce this same 429 at the same threshold, and the difference is unobservable.
    """
    return ProblemError(
        kind="transient",
        code="too_many_attempts",
        title="Too many attempts",
        detail="Too many failed attempts. Wait before trying again.",
        status=429,
        remediation=f"Try again in about {max(1, retry_after_s // 60)} minute(s).",
        headers={"Retry-After": str(retry_after_s)},
    )


async def check(budget: Budget, *, realm: str, subject_id: UUID) -> None:
    """Refuse if this account's budget for this secret is already spent.

    Called BEFORE the expensive verification, so a spent budget does not also buy the
    attacker 30ms of Argon2 on our CPU. Reading does not count as an attempt — only
    `record_failure` counts — so a person who is refused and waits is not pushed further
    out by having asked.
    """
    try:
        redis = get_redis()
        raw = await redis.get(_key(budget, realm, subject_id))
        if raw is None:
            return
        ttl = await redis.ttl(_key(budget, realm, subject_id))
    except Exception:
        # FAIL CLOSED. See the module docstring: with no counter, nothing bounds guessing,
        # and an authentication endpoint that is down beats one that is open.
        log.warning("authn_throttle_unavailable", extra={"budget": budget.name})
        raise _refused(budget, budget.window_s) from None
    if int(raw) < budget.threshold:
        return
    log.warning(
        "authn_throttled",
        extra={"budget": budget.name, "realm": realm, "subject_id": str(subject_id)},
    )
    raise _refused(budget, max(1, ttl) if ttl and ttl > 0 else budget.window_s)


async def record_failure(budget: Budget, *, realm: str, subject_id: UUID) -> int:
    """Count one failure. Returns the new count (0 if the counter is unreachable).

    `EXPIRE ... NX` in the same round trip as the `INCR`, the shape
    `ratelimit.consume` settled on: setting the TTL in a second call leaves an immortal
    counter if the process dies between them, and an immortal counter here is an account
    that is locked out forever.

    The window is a SLIDING one only in the sense that the TTL is not refreshed on each
    failure — it is set once, when the counter is created. That is deliberate: refreshing
    it would let a slow attacker hold an account locked indefinitely by failing once every
    fourteen minutes, which is the DoS this whole design is avoiding.
    """
    key = _key(budget, realm, subject_id)
    try:
        redis = get_redis()
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, budget.window_s, nx=True)
        count = int((await pipe.execute())[0])
    except Exception:
        # A failure we could not count. Logged, not raised: the caller is already on its
        # way to refusing this attempt, and turning a wrong password into a 503 would be
        # a worse answer than a wrong password. The `check` above is where the fail-closed
        # decision belongs, because that is the call that can still prevent the guess.
        log.warning("authn_throttle_uncounted", extra={"budget": budget.name})
        return 0
    log.info(
        "authn_attempt_failed",
        extra={
            "budget": budget.name,
            "realm": realm,
            "subject_id": str(subject_id),
            "count": count,
        },
    )
    return count


async def clear(budget: Budget, *, realm: str, subject_id: UUID) -> None:
    """Forget this account's failures. Called on every SUCCESS.

    This is what makes the threshold count CONSECUTIVE failures. Without it the counter is
    a rolling total and a busy person who mistypes once a week eventually locks themselves
    out for reasons they cannot possibly connect to anything they did.

    A failure to clear is swallowed: the counter expires on its own, so the worst case is a
    person who was already authenticating successfully carrying a stale count for a few
    minutes. Raising here would turn a successful sign-in into an error.
    """
    try:
        await get_redis().delete(_key(budget, realm, subject_id))
    except Exception:
        log.warning("authn_throttle_unclearable", extra={"budget": budget.name})


def pseudo_subject(realm: str, identifier: str) -> UUID:
    """A stable, non-existent subject id for an identifier that resolved to nobody.

    THE POINT IS THAT AN UNKNOWN ACCOUNT IS THROTTLED EXACTLY LIKE A KNOWN ONE. If the
    unknown path skipped the counter, an attacker could tell real addresses from fake ones
    by whether a burst of attempts eventually produced a 429 — the enumeration oracle
    reappearing through the side door, after `subjects.py` shut the front one and
    `hashing.py` equalised the timing.

    Derived rather than random so the same unknown address maps to the same counter across
    requests and processes, and derived through the CODE KEY so the Redis keyspace does not
    become a list of attempted email addresses in plaintext (hard rule 6 applies to
    everything that leaves the process, and Redis is outside it).
    """
    from apps.api.authn.codes import code_fingerprint

    digest = code_fingerprint(identifier.strip().casefold(), domain=f"pseudo-subject:{realm}")
    return UUID(bytes=digest[:16])


def penalty_delay_s(count: int) -> float:
    """How long to wait after a failure, given how many there have been.

    OWASP's cheat sheet names exponential backoff starting at one second as an alternative
    to lockout; NIST names an increasing wait as the way to reduce the chance of locking a
    legitimate claimant out. This is that curve, and it is CAPPED, because the delay is
    served by holding an asyncio task open — an uncapped one would let an attacker convert
    failed guesses into pinned server-side coroutines, which is a slow-loris with extra
    steps.

    The first two failures cost nothing at all: those are typos, and a person who mistypes
    their password should not experience the site getting slower.
    """
    if count <= 2:
        return 0.0
    return min(2.0 ** (count - 2), 8.0)


__all__ = [
    "OTP_BUDGET",
    "OTP_MAX_ATTEMPTS",
    "PASSWORD_BUDGET",
    "Budget",
    "check",
    "clear",
    "penalty_delay_s",
    "pseudo_subject",
    "record_failure",
]
