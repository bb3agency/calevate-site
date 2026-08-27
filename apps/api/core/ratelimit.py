"""Named rate-limit profiles, and the fixed-window counter every surface shares.

WHAT THIS IS FOR. nginx already applies per-real-IP `limit_req` zones at the edge
(`infra/nginx/rate-zones.conf.template`: auth 20r/m, admin 180r/m, client 120r/m,
webhooks 600r/m burst 200, health 60r/m). That is a real defence and this module ADDS to
it rather than replacing it, because there are three things the edge structurally cannot
do:

1. **Per-tenant.** nginx keys on `$binary_remote_addr`. One Indian SMB behind one NAT is
   the ordinary case, so per-IP alone punishes the wrong party — every user of a tenant
   shares a bucket with every other user of that tenant AND with anyone else on that
   ISP's CGNAT. The tenant is only knowable after authentication (see
   `core/auth.py::charge_tenant_quota`), which is inside the app.
2. **Per-family isolation.** The edge sees one `/hooks` vhost. Our `/hooks` routes are
   lead intake, Meta intake (GET verify + POST) and the Razorpay payment callback;
   sharing one bucket means a lead-intake flood 429s the PAYMENT webhook. They get
   separate profiles here, and ingest is keyed on the
   `webhook_id` in the path — the natural per-tenant dimension for a surface with no
   session.
3. **Cost weighting.** A 1-row read and a 20,000-row CSV export are one request each to
   nginx. `bulk_read`, `bulk_write` and `costly` below are the difference.

This paragraph used to claim the edge also applies "a 2 MiB body cap", and it does not:
`infra/nginx/calevate.conf.template` sets `client_max_body_size` to **25m** on the api and
console vhosts and 10m on `/hooks`. The 2 MiB cap is `core/middleware.MAX_BODY_BYTES`,
ours, and the correction is load-bearing rather than pedantic — the same sentence was the
reason nobody worried that `BodyLimitMiddleware` read `Content-Length` and therefore saw
nothing at all of a `Transfer-Encoding: chunked` body (D-135).

WHY FIXED WINDOW AND NOT A TOKEN BUCKET. A fixed window admits up to 2x the nominal rate
across a boundary, which a sliding window or GCRA would not. It is kept because the
expensive surfaces (call dispatch, campaign launch) are additionally guarded by
idempotency and spend caps, so this only has to stop obvious abuse — and because a
counter that is one INCR is a counter nobody has to reason about at 3am. If that stops
being true, the replacement is a Lua GCRA script, not a second counter alongside this one.

THE PROFILE TABLE IS ENFORCED. `tests/rate_limit_census_test.py` walks
`rbac.iter_api_routes(app)` and fails if any route resolves to no rule, so a new route
cannot be born unlimited; it also fails if a rule matches NO route, so a typo in a
pattern cannot leave a cost weight silently inert.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis

log = get_logger(__name__)

#: The Redis key namespace. Everything under it is ephemeral and expiring — a limiter
#: bucket is never a system of record (`core/redis.py`).
KEY_PREFIX = "calevate:rl"

#: How long a key outlives its window before Redis reclaims it.
_TTL_SLACK_S = 1


@dataclass(frozen=True, slots=True)
class LimitProfile:
    """One named cost class.

    `per_client` is the ceiling for ONE caller — the bearer-token fingerprint when the
    request carries one, else the client IP. `per_tenant` is the ceiling for the whole
    tenant across all of its callers, or None where the surface has no tenant (signup,
    the identity mirror).

    WHICH OF THE TWO IS LARGER IS A PROPERTY OF THE SURFACE, not an invariant. On `/v1`
    the tenant ceiling is the larger one, because many callers share one tenant. On
    `webhook_ingest` it is the smaller one, because the relationship inverts: Meta
    delivers every tenant's leads from Facebook's own addresses, so the IP dimension is a
    near-global ceiling and the per-`webhook_id` dimension is the tenant's own.

    `tenant_from_last_path_segment` is how a surface with no session still gets a tenant
    dimension: the `webhook_id` trailing `/hooks/v1/ingest/...` identifies the lead
    source, and therefore the tenant, without authenticating anything.
    """

    name: str
    per_client: int
    per_tenant: int | None
    window_s: int = 60
    tenant_from_last_path_segment: bool = False


#: The one place a number is chosen. Sized against what a real screen does: the client
#: dashboard polls every 20s and a screen fans out to ~6 queries, so ~18 req/min/user is
#: ordinary and 240 is ~13x that; a tenant ceiling of 900 is ~50 concurrent users, well
#: past any SMB and still a stop on a runaway client-side loop.
PROFILES: dict[str, LimitProfile] = {
    # No app-level limit. `/healthz` must answer an uptime monitor and a load balancer
    # even while the platform is refusing everything else, and the edge's `health` zone
    # (60r/m) is the ceiling that applies. The detail behind `/healthz/ready` is gated by
    # `ops:manage`, not by volume.
    "exempt": LimitProfile("exempt", per_client=0, per_tenant=None),
    # Sign-in and account creation. The tightest profile, matching the edge's `auth`
    # zone. `tenancy/signup.py` additionally spends a per-identity and per-IP hourly
    # quota — this is the per-minute floor under it, not a replacement.
    "auth": LimitProfile("auth", per_client=20, per_tenant=None),
    "client_api": LimitProfile("client_api", per_client=240, per_tenant=900),
    # The operator console fans out harder than a client screen (a tenant list plus a
    # health strip plus a queue view), and there are few operators. No tenant dimension:
    # an operator acting on tenant X must not be throttled by tenant X's own dashboard
    # traffic, and the per-operator ceiling is the one that means anything here.
    "admin_api": LimitProfile("admin_api", per_client=300, per_tenant=None),
    # A vendor round trip, an LLM call or an email send. Each one costs money or a
    # third-party quota, and no human clicks these 30 times a minute.
    "costly": LimitProfile("costly", per_client=30, per_tenant=60),
    # Bulk data OUT: the 20,000-row export, the DPDP subject export, an invoice
    # recomputed over usage_events. The tightest non-auth profile because this is the
    # shape data exfiltration takes.
    "bulk_read": LimitProfile("bulk_read", per_client=6, per_tenant=12),
    # Bulk data IN: a chunked CSV upload is several requests by design, so this is looser
    # than `bulk_read` while still bounding the write amplification.
    "bulk_write": LimitProfile("bulk_write", per_client=20, per_tenant=40),
    # Lead intake from a client's own web forms and CRMs. Keyed per `webhook_id`, which
    # IS the tenant dimension on a surface with no session, so one client's form flood
    # cannot 429 another client's leads — nor the payment and identity webhooks below.
    "webhook_ingest": LimitProfile(
        "webhook_ingest",
        per_client=600,
        per_tenant=300,
        tenant_from_last_path_segment=True,
    ),
    # The payment provider's callback. Its own bucket because losing one of these means
    # a client paid and was not credited until the reconciliation sweep.
    "webhook_payment": LimitProfile("webhook_payment", per_client=300, per_tenant=None),
    # Anything the table does not name: 404 probes, a path that has not been routed yet.
    # NOT reachable from a mounted API route — the census test fails the build first —
    # so this exists purely so that scanning for unrouted paths is not free.
    "unmatched": LimitProfile("unmatched", per_client=60, per_tenant=None),
}


def _compile(pattern: str) -> re.Pattern[str]:
    """`/v1/leads/*/call` → a regex matching BOTH `/v1/leads/018f.../call` (what the
    middleware sees, before routing) and `/v1/leads/{lead_id}/call` (what the census test
    and the post-auth charge see, after routing).

    One matcher for both is the point: a `{lead_id}` segment is a non-empty run of
    non-slash characters, exactly like a concrete id, so the same pattern answers for the
    live path and for the route template. A second table keyed by template would be a
    second answer to "which profile is this route", and the two would drift the first
    time somebody renamed a path parameter.

    `**` is a trailing wildcard meaning "this prefix and anything under it, including
    nothing" — so `/v1/**` covers `/v1` itself.
    """
    segments = [s for s in pattern.split("/") if s]
    parts: list[str] = []
    for index, segment in enumerate(segments):
        if segment == "**":
            if index != len(segments) - 1:
                raise ValueError(f"`**` must be the last segment: {pattern}")
            parts.append("(?:/.*)?")
            break
        parts.append("/" + ("[^/]+" if segment == "*" else re.escape(segment)))
    return re.compile("^" + "".join(parts) + "$")


@dataclass(frozen=True, slots=True)
class Rule:
    """A path pattern (plus optionally the methods it applies to) → a profile name."""

    pattern: str
    profile: str
    methods: frozenset[str] | None = None

    @property
    def matcher(self) -> re.Pattern[str]:
        return _matcher(self.pattern)

    @property
    def specificity(self) -> tuple[int, int, int]:
        """How specific this rule is, so resolution never depends on table ORDER.

        Declaration-order-wins is what this table did when it was five prefixes, and it
        is the kind of coupling that turns "add a rule" into "add a rule in the right
        place, and nothing tells you where that is". Ranked by: segments matched before
        any `**`, then literal (non-wildcard) segments, then whether the rule names
        methods. `tests/rate_limit_census_test.py` asserts no two rules tie for any live
        route, so "most specific" is always a single answer.
        """
        segments = [s for s in self.pattern.split("/") if s and s != "**"]
        literals = sum(1 for s in segments if s != "*")
        return (len(segments), literals, 1 if self.methods else 0)

    def matches(self, path: str, method: str) -> bool:
        if self.methods is not None and method.upper() not in self.methods:
            return False
        return self.matcher.match(path) is not None


_COMPILED: dict[str, re.Pattern[str]] = {}


def _matcher(pattern: str) -> re.Pattern[str]:
    compiled = _COMPILED.get(pattern)
    if compiled is None:
        compiled = _compile(pattern)
        _COMPILED[pattern] = compiled
    return compiled


def _m(*methods: str) -> frozenset[str]:
    return frozenset(methods)


#: Path → profile. Order here is for the READER; resolution uses `Rule.specificity`.
#:
#: Adding a route under an existing family needs no entry — `/v1/**` and the two admin
#: prefixes cover it. An entry is needed when the route is MORE expensive than its
#: family, and the census test's "every rule matches at least one route" assertion is
#: what stops one of those entries from quietly becoming a fossil after a rename.
RULES: tuple[Rule, ...] = (
    # --- unauthenticated surfaces -------------------------------------------------
    Rule("/healthz/**", "exempt"),
    # Served outside prod only (`core/bootstrap.py`), but the limiter must still know
    # what they are in the environments that do serve them.
    Rule("/openapi.json", "exempt"),
    Rule("/docs/**", "exempt"),
    Rule("/redoc/**", "exempt"),
    Rule("/v1/auth/**", "auth"),
    Rule("/hooks/v1/ingest/**", "webhook_ingest"),
    Rule("/hooks/v1/razorpay", "webhook_payment"),
    # --- families -----------------------------------------------------------------
    Rule("/v1/**", "client_api"),
    Rule("/v1/admin/**", "admin_api"),
    Rule("/v1/ops/**", "admin_api"),
    # --- cost-weighted: bulk data out ---------------------------------------------
    Rule("/v1/leads/export.csv", "bulk_read", _m("GET")),
    Rule("/v1/compliance/subject-export", "bulk_read", _m("POST")),
    Rule("/v1/billing/invoice", "bulk_read", _m("GET")),
    Rule("/v1/admin/tenants/*/invoice", "bulk_read", _m("GET")),
    # --- cost-weighted: bulk data in ----------------------------------------------
    Rule("/v1/leads/bulk", "bulk_write", _m("POST")),
    Rule("/v1/campaigns/*/contacts", "bulk_write", _m("POST")),
    # --- cost-weighted: a vendor round trip, an LLM call, or an email --------------
    Rule("/v1/leads/*/call", "costly", _m("POST")),
    # The dashboard assist (D-127). `costly` for the reason that profile names — it is
    # literally "an LLM call" — and it is the one route in this family that also holds a
    # pooled Postgres connection for the length of the vendor round trip, because the
    # tenant GUC is transaction-local (`crm/assist.py` argues the whole departure).
    Rule("/v1/calls/*/assist", "costly", _m("POST")),
    # The in-app copilot (`apps/api/copilot/`). `costly` for the reason that profile names
    # — it is literally "an LLM call" — and this one is the only route in the family that
    # can make SEVERAL of them for one click (`copilot/service.MAX_TURNS`). It is also the
    # route with no `Idempotency-Key` in front of it: `copilot/routes.py` argues why a
    # stream has nothing to replay, and names this profile as what bounds a double-click
    # instead.
    Rule("/v1/copilot/ask", "costly", _m("POST")),
    Rule("/v1/campaigns/*/launch", "costly", _m("POST")),
    Rule("/v1/numbers/purchase", "costly", _m("POST")),
    Rule("/v1/billing/topups/intent", "costly", _m("POST")),
    Rule("/v1/kb/sources", "costly", _m("POST")),
    Rule("/v1/invitations", "costly", _m("POST")),
    # Accepting an agreement (migration a9d4e70c31b8). `costly` is not about money here —
    # nothing is spent — but about what the profile's own comment says: "no human clicks
    # these 30 times a minute". There are four agreements and each is accepted once, so a
    # caller doing this at `client_api` rates is stuffing an append-only contract ledger,
    # and every row of it is evidence somebody has to read later.
    Rule("/v1/legal/acceptances", "costly", _m("POST")),
    Rule("/v1/lead-sources/*/test", "costly", _m("POST")),
    Rule("/v1/lead-sources/*/meta/**", "costly", _m("POST")),
    Rule("/v1/integrations/endpoints/**", "costly", _m("POST")),
    Rule("/v1/admin/tenants/*/invitations", "costly", _m("POST")),
    Rule("/v1/admin/tenants/*/agents/*/publish", "costly", _m("POST")),
    Rule("/v1/admin/tenants/*/agents/*/apply", "costly", _m("POST")),
    Rule("/v1/admin/tenants/*/agents/*/undo", "costly", _m("POST")),
    Rule("/v1/admin/tenants/*/agents/*/intake/draft", "costly", _m("POST")),
    Rule("/v1/ops/secrets/*/test", "costly", _m("POST")),
    Rule("/v1/ops/secrets/kek/rewrap", "costly", _m("POST")),
)


def resolve_rule(path: str, method: str) -> Rule | None:
    """The most specific rule for this (path, method), or None when the table names none.

    None is what the census test refuses for a mounted route. At runtime it means an
    unrouted path, which `profile_for` gives the `unmatched` profile.

    A linear scan of the whole table, MEASURED at 9-14µs on this machine for the two
    shapes that matter (a deep `/v1` path, a `/hooks` path). It runs at most twice per
    request — once in the middleware on the concrete path, once in the post-auth tenant
    charge on the route template — against a request that is about to do at least one
    round trip to Postgres. A prefix trie would be faster and would be the wrong trade:
    ~35 rules is not a data structure problem, and the flat tuple is what makes the table
    readable to the next person deciding where a new route belongs.
    """
    candidates = [rule for rule in RULES if rule.matches(path, method)]
    if not candidates:
        return None
    return max(candidates, key=lambda rule: rule.specificity)


def profile_for(path: str, method: str) -> LimitProfile:
    rule = resolve_rule(path, method)
    return PROFILES[rule.profile if rule is not None else "unmatched"]


#: The longest a caller-supplied bucket key may be. Redis keys are memory, and every
#: dimension below is derived from something a stranger controls — a path segment, a
#: header. An unbounded key space is a way to spend our RAM without authenticating.
_MAX_SUBJECT = 64
_SUBJECT_SAFE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def bucket_subject(raw: str | None) -> str:
    """A caller-supplied value, made safe to put in a Redis key.

    Anything too long, empty or carrying an unexpected character collapses to one shared
    `invalid` bucket rather than being rejected: this is a limiter, and the right answer
    to a weird key is "you share a small bucket with the other weird keys", not a 500.
    """
    if raw is None:
        return "none"
    candidate = raw.strip()
    if not candidate or len(candidate) > _MAX_SUBJECT or not _SUBJECT_SAFE.match(candidate):
        return "invalid"
    return candidate


def fingerprint(value: str) -> str:
    """A stable pseudonym for a LIVE CREDENTIAL, and for nothing else.

    ONE CALLER, ON PURPOSE: the bearer token in `core.middleware.RateLimitMiddleware.
    _subjects`. A token is the one bucket subject in this platform that must not reach
    Redis in the clear, because a Redis dump would then be a set of usable sessions.
    Identifiers and addresses are NOT that — they go through `bucket_subject` — and the
    signup quota used to hash both of its subjects here on a privacy argument that could
    not hold: an unkeyed hash of an IPv4 address is an encoding of a 32-bit space, and the
    same address is written in the clear by the caller dimension of this very module and
    kept permanently in `audit_log.ip` (SEC-COMP §5). See `tenancy/signup.py::_consume`.

    `blake2s`, NOT the builtin `hash()`. `str.__hash__` is salted per PROCESS (PEP 456,
    on by default since 3.3), and this deployment runs uvicorn with two workers: one
    token therefore occupied one bucket per worker, so the effective limit was N times
    the declared one and changed on every restart. The old key also truncated to 32 bits,
    which is ~77k tokens to a 50% collision by the birthday bound — one tenant consuming
    another tenant's limiter bucket.

    `digest_size=16` — 128 bits, so the birthday bound is 2^64 distinct live tokens
    before an even chance of one collision, against a bucket population bounded by the
    limiter's own window. Not 32 bytes: the digest is a Redis key component on every
    request, and doubling it buys nothing the threat model can use.

    Unkeyed rather than an HMAC: the input is a high-entropy credential, so there is no
    dictionary to walk, and a key here would be a fourth secret to rotate for no gain in
    the threat model this defends (BACKEND-PATTERNS §4 keys the IDEMPOTENCY fingerprint
    because that one pseudonymises a low-entropy tenant/user id). That argument is a
    property of the INPUT, which is why the docstring now names the one input it is true
    of rather than the shape of a caller.
    """
    return hashlib.blake2s(value.encode("utf-8"), digest_size=16).hexdigest()


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    retry_after_s: int
    #: `over_limit` and `unavailable` are different refusals and the caller must be able
    #: to say so: one is 429 "you are going too fast", the other is 503 "we cannot tell".
    #: Collapsing them would put "the counter is down" in front of a user as a rate limit
    #: they did not hit.
    reason: str = "ok"
    #: True when this call CREATED the counter — the first request in this window for
    #: this bucket. `RateLimitMiddleware` charges the MINTING of a per-token bucket to the
    #: address that minted it (see `_subjects` there), which is what stops a stranger
    #: opting out of the per-caller dimension by inventing a credential. Reported as a
    #: boolean rather than as the raw count on purpose: the counter's value is this
    #: module's business, "was this bucket new" is the only part a caller may act on.
    first_in_window: bool = False


#: The answer when NOTHING WAS COUNTED — an unlimited profile, or a counter we could not
#: reach. `first_in_window` is false here by construction: no bucket was created, so
#: nothing may be charged for having created one.
_ALLOWED = Decision(allowed=True, retry_after_s=0)


async def consume(
    profile: LimitProfile,
    dimension: str,
    subject: str,
    limit: int,
    *,
    fail_open: bool = True,
) -> Decision:
    """Count one request against `(profile, dimension, subject)` and say whether it may
    proceed.

    ONE COUNTER FOR THE WHOLE PLATFORM, with the failure policy as a parameter rather
    than as a second implementation. Request limiting fails OPEN: Redis is not a system
    of record here, a limiter outage must never 500 the platform, and the edge's
    `limit_req` zones are still standing. The signup quota (`tenancy/signup.py`) passes
    `fail_open=False`, because nothing else bounds an unattended tenant factory — losing
    Redis there means the endpoint is unavailable, not unguarded. Those two policies used
    to be two copies of this INCR/EXPIRE pair, which is how they drift.
    """
    if limit <= 0:
        return _ALLOWED
    window = profile.window_s
    now = time.time()
    key = f"{KEY_PREFIX}:{profile.name}:{dimension}:{subject}:{int(now // window)}"
    retry_after = max(1, window - int(now % window))
    try:
        redis = get_redis()
        pipe = redis.pipeline()
        pipe.incr(key)
        # Set the TTL in the SAME round trip, and only if the key has none. The previous
        # shape — INCR, then EXPIRE when the count came back 1 — leaves an immortal key
        # if the process dies in between, and an immortal counter is a bucket that is
        # 429 forever. `EXPIRE ... NX` is Redis 7.0+; docker-compose, CI and the VPS all
        # pin redis:7.
        pipe.expire(key, window + _TTL_SLACK_S, nx=True)
        count = int((await pipe.execute())[0])
    except Exception:
        log.warning("ratelimit_unavailable", extra={"profile": profile.name})
        if fail_open:
            return Decision(allowed=True, retry_after_s=0, reason="unavailable")
        return Decision(allowed=False, retry_after_s=retry_after, reason="unavailable")

    if count <= limit:
        return Decision(allowed=True, retry_after_s=0, first_in_window=count == 1)
    return Decision(allowed=False, retry_after_s=retry_after, reason="over_limit")


def too_many_requests(decision: Decision) -> ProblemError:
    """One refusal shape for every dimension.

    The body never names WHICH dimension was exhausted: telling an unauthenticated caller
    "you hit the per-tenant limit" tells them a tenant exists and that their neighbours
    are busy. The operator gets that detail in the log line instead.
    """
    return ProblemError(
        kind="transient",
        code="rate_limited",
        title="Too many requests",
        detail="Rate limit exceeded for this endpoint.",
        status=429,
        remediation=f"Retry in {decision.retry_after_s}s.",
        headers={"Retry-After": str(decision.retry_after_s)},
    )


__all__ = [
    "KEY_PREFIX",
    "PROFILES",
    "RULES",
    "Decision",
    "LimitProfile",
    "Rule",
    "bucket_subject",
    "consume",
    "fingerprint",
    "profile_for",
    "resolve_rule",
    "too_many_requests",
]
