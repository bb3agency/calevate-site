"""The in-call LLM leg's bearer, minted long and rotated on a cron (D-404).

WHAT THIS EXISTS TO PREVENT. `VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE` used to be False on
one sentence: "a regional Vertex endpoint authenticates with a Google OAuth2 access token
that expires in about an hour, and Bolna stores static strings." Both halves were true;
the conclusion was not. A store that holds a string can hold a string somebody REPLACES on
a schedule, and this file is that somebody.

WHY ROTATION AND NOT A PROXY, in one paragraph, because the proxy is what a reader will
reach for first (it is `VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE` route (B), and it is now
D-405). A broker we run in-region would hold the key and mint bearers on demand — right in
the abstract and wrong on three counts here: it sits IN the turn-latency path, so every
model token on a live phone call takes an extra hop through our VPS; it is a NEW DEPLOYABLE
(ROADMAP §6) whose whole content is `Authorization:` header rewriting; and `POST
/user/model/custom` carries no credential field, so the OpenAI-compatible endpoint we would
have to publish for the engine to reach is UNAUTHENTICATED — an open relay for our Vertex
spend, guarded by an unguessable path, which is not authentication. Rotation costs zero
added latency (the bearer travels engine→Google on a connection we are not part of), no new
deployable, and no new attack surface.

--------------------------------------------------------------------------------------
WHAT IS VERIFIED AND WHAT IS NOT — the distinction this repo is strict about
--------------------------------------------------------------------------------------
* **VERIFIED-OSS: the engine sends a plain bearer.** `bolna-ai/bolna` master, re-read
  18 Aug 2026, `bolna/llms/openai_llm.py`:

      if kwargs.get("provider", "openai") == "custom":
          base_url = kwargs.get("base_url")
          api_key = kwargs.get("llm_key", None)
          self.async_client = AsyncOpenAI(
              base_url=base_url, api_key=api_key, http_client=http_client)

  `AsyncOpenAI` sends `Authorization: Bearer <api_key>`, which is exactly what Vertex's
  OpenAI-compatible surface accepts. **This is the check the whole design hung on and it
  passes.** It is VERIFIED-OSS and NOT verified-live: the hosted platform is presumably
  built on this code, and "presumably" is the word D-31/D-32 exist because of.
  OPERATIONS §2 gate 16c is the one live call that settles it.
* **VERIFIED-OSS: the native Google provider cannot be used.** `bolna/llms/gemini_llm.py`
  is `genai.Client(api_key=api_key)` — no project, no region, no base URL, i.e. the AI
  Studio global host. `provider: "custom"` with an explicit regional URL is the ONLY route
  that honours residency, and that is WHY it is the one chosen (D-407).
* **REPORTED, NOT READ: the 12-hour lifetime.** `generateAccessToken` accepts
  `lifetime: "43200s"` for a service account named in the org policy
  `constraints/iam.allowServiceAccountCredentialLifetimeExtension`; the default cap is
  3600s. Read through the search index 18 Aug 2026 (`docs.cloud.google.com` is refused by
  this environment's proxy). **Nothing here depends on that being true**, and that is the
  design's most important property: the response's `expireTime` is ALWAYS set
  (`google/iam/credentials/v1/common.proto`, `GenerateAccessTokenResponse.expire_time`,
  "The expiration time is always set"), so what we were GRANTED is read back rather than
  assumed. A deployment whose org policy is not set gets 1-hour tokens and is REFUSED by
  name — never left running a leg that will go dark between ticks.

--------------------------------------------------------------------------------------
WHY THE MINT IS TWO CALLS AND NOT ONE
--------------------------------------------------------------------------------------
`google_oauth.access_token` already mints a bearer by the RFC 7523 JWT-bearer flow — and
that flow's assertion is capped by Google at one hour, which is the ceiling this leg cannot
live under. So the JWT-bearer token is used for what it is good for (authenticating ONE
call) and that call is `serviceAccounts:generateAccessToken`, which is the only API that
can issue a longer one.

SELF-IMPERSONATION, which is a real IAM grant and not a trick: the service account calls
`generateAccessToken` on ITSELF, which requires `roles/iam.serviceAccountTokenCreator` on
its own resource. That grant is an EXTERNAL blocker (a GCP IAM change, OPERATIONS §2 gate
16d) and its absence surfaces as a named refusal on the first tick rather than as a puzzle.

--------------------------------------------------------------------------------------
WHAT THIS MODULE PROMISES ABOUT THE CREDENTIAL
--------------------------------------------------------------------------------------
The service-account key is a secrets-manager reference (`gcp_service_account_json`,
injected at deploy time, sealed out of `platform_settings` by name) and is read only
through `vertex_credentials()`, which parses it once and returns None rather than raising.
The MINTED BEARER is never stored — not in the database, not in Redis, not in a file. It
exists in one local variable, is handed to the engine, and goes out of scope. Nothing here
logs it, no exception raised here has it in scope, and every log line below carries ids,
counts and outcomes. `_token_fingerprint` exists so an operator can correlate two rotations
without the value ever appearing: it is a truncated SHA-256, which is a one-way function of
a string that is already dead within twelve hours.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx
from calevate_shared.engine import VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE

from apps.api.core.alerting import alert
from apps.api.core.heartbeat import check_ref, ping_async
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.engine import get_engine
from apps.workers.extraction import VERTEX_SCOPE, vertex_credentials
from apps.workers.google_oauth import access_token

log = get_logger(__name__)

#: The IAM Credentials API — the only Google API that can issue an access token longer
#: than the one-hour ceiling on a JWT-bearer assertion.
#:
#: `projects/-/serviceAccounts/{email}` with a LITERAL hyphen for the project is Google's
#: own wildcard form: the account is identified by its email address, and the project in
#: the path is ignored. Spelling our real project there would be a second place for a
#: project id to be wrong, and it would break the moment a key from another project is
#: installed — which is an ordinary thing for an operator to do.
IAM_CREDENTIALS_HOST: Final = "https://iamcredentials.googleapis.com"

#: 12 hours, as a protobuf `Duration` — the JSON encoding is a string with an `s` suffix
#: (`google.protobuf.Duration`), not an integer, and sending `43200` is a 400 that names
#: the field and not the encoding.
TOKEN_LIFETIME_S: Final = 43_200
TOKEN_LIFETIME: Final = f"{TOKEN_LIFETIME_S}s"

#: How often the cron fires, in hours. **FOUR, against a twelve-hour token**, and the
#: arithmetic is the whole justification:
#:
#: * At any instant the installed bearer has at least 8 hours left, because it is replaced
#:   when it still has 8.
#: * TWO consecutive total failures still leave 4 hours of working service — so the alarm
#:   raised by the first failure has a third of a day of human lead time, which is the
#:   difference between a page somebody answers and an outage somebody discovers.
#: * A missed tick is not special-cased anywhere: the next tick mints unconditionally, so
#:   recovery needs no state, no backfill and no "was the last one ok" flag.
#:
#: Six hours (the obvious "half the lifetime") was rejected on the second bullet: it leaves
#: exactly ONE cycle of slack, and the second failure lands at the moment the old token
#: dies. The cost of the extra tick is one signature and two HTTPS round trips a day.
REFRESH_INTERVAL_HOURS: Final = 4

#: The floor a granted token must clear. A lifetime shorter than TWO refresh intervals
#: means a single missed tick is an outage, which is precisely the property the cadence
#: above was chosen to avoid — so a deployment that is being handed 1-hour tokens (the
#: org-policy constraint not set, the usual cause) is REFUSED rather than run.
MIN_GRANTED_LIFETIME_S: Final = REFRESH_INTERVAL_HOURS * 2 * 3600

#: The request budget. This is a cron with nothing waiting on it, so the number is about
#: not hanging a worker slot: two Google calls and up to three vendor calls, none of which
#: is a model inference.
MINT_TIMEOUT_S: Final = 20.0


@dataclass(frozen=True, slots=True)
class MintedBearer:
    """A bearer and the instant Google says it dies.

    `expires_at` is GOOGLE'S answer, never our arithmetic on `TOKEN_LIFETIME_S`. That is
    the field that makes an unset org policy a named refusal instead of a silent
    eight-hour hole: we ask for twelve hours and are given one, and the only place that
    difference is visible is here.

    `value` is never logged, never formatted and never returned upward past
    `refresh_in_call_llm_credential`, which hands it to the engine and lets it go.
    """

    value: str
    expires_at: datetime

    @property
    def remaining(self) -> timedelta:
        return self.expires_at - datetime.now(UTC)


def _token_fingerprint(token: str) -> str:
    """Twelve hex characters of SHA-256, so two rotations can be correlated in a log
    without the credential ever appearing in one.

    Not a security control and not pretending to be: it is a one-way function of a string
    that is dead within half a day, and its whole job is to let an operator answer "is the
    engine holding the bearer this tick minted, or the previous one" from two log lines.
    """
    return hashlib.sha256(token.encode()).hexdigest()[:12]


def _parse_expiry(raw: object) -> datetime | None:
    """Google's RFC 3339 `expireTime`, as an aware instant.

    Returns None rather than raising, and rather than defaulting to
    `now + TOKEN_LIFETIME_S`: a default here would invent the exact fact this function
    exists to read, and would do it in the optimistic direction — reporting a twelve-hour
    token for a response that never said so.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        # Google emits `Z`; `fromisoformat` accepts it from 3.11, and this repo is 3.12.
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    # An expiry compared against an aware `now()` must itself be aware — a naive one
    # raises `TypeError` at the comparison, which would turn a readable token into a
    # traceback (CLAUDE.md: timezone-aware instants, never naive ones).
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def mint_in_call_bearer(http: httpx.AsyncClient) -> MintedBearer | None:
    """A long-lived Vertex bearer for this deployment, or None with the reason logged.

    NEVER RAISES, for `google_oauth.access_token`'s reason: the one thing that must not
    happen on this path is credential material reaching a traceback. Every refusal is a
    log line naming what is missing, and the caller turns None into the page.
    """
    credentials = vertex_credentials()
    if credentials is None:
        # Already distinguished by `vertex_credentials`: absent config logs nothing (a
        # deployment without Vertex is a coherent deployment) and an unparseable key logs
        # `vertex_credential_unparseable`. Re-reporting either here would send an operator
        # to install a key they have already installed.
        log.info("vertex_bearer_no_service_account")
        return None
    account, project = credentials

    # The one-hour JWT-bearer token, used for exactly one call: asking for a longer one.
    assertion_token = await access_token(http, account, scope=VERTEX_SCOPE)
    if assertion_token is None:
        # `google_oauth` logged the status without the body. The key itself is the usual
        # cause — revoked, or minted for a deleted account.
        log.error("vertex_bearer_assertion_failed", extra={"project": project})
        return None

    url = (
        f"{IAM_CREDENTIALS_HOST}/v1/projects/-/serviceAccounts"
        f"/{account.client_email}:generateAccessToken"
    )
    try:
        response = await http.post(
            url,
            headers={"Authorization": f"Bearer {assertion_token}"},
            json={"scope": [VERTEX_SCOPE], "lifetime": TOKEN_LIFETIME},
        )
    except httpx.HTTPError as exc:
        log.error("vertex_bearer_transport_error", extra={"error": type(exc).__name__})
        return None
    if response.status_code != 200:
        # THE STATUS, NEVER THE BODY. Google's error body for this call echoes the
        # request, and a 403 here has one overwhelmingly likely cause worth naming in the
        # runbook rather than in the log: the account lacks
        # `roles/iam.serviceAccountTokenCreator` ON ITSELF.
        log.error(
            "vertex_bearer_refused",
            extra={"status": response.status_code, "project": project},
        )
        return None
    try:
        body = response.json()
        token = str(body["accessToken"])
    except (ValueError, KeyError, TypeError):
        log.error("vertex_bearer_malformed")
        return None
    if not token:
        log.error("vertex_bearer_empty")
        return None
    expires_at = _parse_expiry(body.get("expireTime"))
    if expires_at is None:
        # The proto says `expire_time` is ALWAYS set, so a response without a readable one
        # is not a Google response we recognise — and guessing an expiry would hide
        # exactly the condition the next check exists to catch.
        log.error("vertex_bearer_expiry_unreadable")
        return None
    return MintedBearer(value=token, expires_at=expires_at)


async def refresh_in_call_llm_credential(ctx: dict[str, Any]) -> str:
    """Cron, every `REFRESH_INTERVAL_HOURS`. Returns a short outcome string; arq stores it.

    THE FAILURE THIS GUARDS IS TOTAL AND SILENT. If the bearer in the engine's credential
    store goes stale, every in-call model turn gets a 401 from Vertex — on live phone
    calls, for every client, with nothing in our system having done anything wrong and
    nothing in our system noticing. It is the one job here whose failure has no other
    symptom until a caller hears silence, so every arm below that does not end in a fresh
    credential ends in a page.

    NEVER RAISES. arq would retry (`max_tries` in the registry) and then drop it, and a
    dropped cron is exactly the outcome this alarm exists to make impossible.
    """
    settings = get_settings()
    project = (settings.gcp_project_id or "").strip()

    # --- the three "this deployment is not on that leg" arms, all stated ---------------
    #
    # Skips, not failures, and each says WHICH condition is unmet. A single "not
    # configured" would send an operator to check the wrong one of three things, and this
    # job runs on every deployment including the ones that will never use Vertex.
    if not VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE:
        # Unreachable while the constant is True. Kept as a real branch rather than
        # deleted, because the constant is a switch a founder flips both ways and the
        # refresher must stop writing credentials when the leg is switched off — not keep
        # installing bearers for an endpoint no agent points at any more.
        log.info("vertex_credential_skipped", extra={"reason": "leg_not_deliverable"})
        return "skipped_not_deliverable"
    if not project:
        log.info("vertex_credential_skipped", extra={"reason": "no_gcp_project"})
        return "skipped_no_project"
    engine = get_engine(settings)
    if not engine.capabilities.is_ours("llm"):
        # The engine in use chooses its own model, so there is no credential of ours for
        # it to hold. Stated rather than silent: a deployment that switched ENGINE has a
        # cron running against a store that does not exist, and the honest report of that
        # is a log line, not a page — nothing is broken, the leg simply is not ours.
        log.info(
            "vertex_credential_skipped",
            extra={"reason": "engine_llm_not_ours", "engine": engine.name},
        )
        return "skipped_llm_not_ours"

    async with httpx.AsyncClient(timeout=MINT_TIMEOUT_S, follow_redirects=False) as http:
        bearer = await mint_in_call_bearer(http)

    if bearer is None:
        # `mint_in_call_bearer` has already logged which of the five refusals it was, and
        # the alert deliberately does NOT repeat it: the detail an operator can act on is
        # in the runbook, and a detail string assembled from a credential path is a detail
        # string one refactor away from carrying a credential.
        _page(
            "The in-call LLM bearer could not be minted. Vertex will start refusing "
            "model turns when the installed one expires.",
            project=project,
        )
        return "mint_failed"

    remaining = bearer.remaining
    if remaining.total_seconds() <= 0:
        # Already dead on arrival. The realistic cause is host clock skew rather than
        # anything Google did, and installing it would be worse than refusing: the engine
        # would hold a credential that fails on the very next call, and the NEXT tick
        # would report a healthy rotation on top of it.
        _page(
            f"Google issued an in-call LLM bearer that has already expired "
            f"(expiry {bearer.expires_at:%Y-%m-%dT%H:%M:%SZ}); check this host's clock. "
            "It was NOT installed, so the previous credential is still in place.",
            project=project,
        )
        return "expired_on_arrival"
    if remaining.total_seconds() < MIN_GRANTED_LIFETIME_S:
        # THE ORG-POLICY CHECK, and it is the reason `expireTime` is read rather than
        # assumed. Asking for 43200s and being given 3600s is silent success followed by a
        # five-hour outage between ticks. Refusing installs nothing, so the leg keeps
        # running on the credential it has while somebody sets the policy.
        _page(
            f"Google granted an in-call LLM bearer lasting only "
            f"{int(remaining.total_seconds() // 60)} minutes, less than the "
            f"{MIN_GRANTED_LIFETIME_S // 3600}h this rotation needs. The org policy "
            "constraints/iam.allowServiceAccountCredentialLifetimeExtension is almost "
            "certainly not set for this service account. NOT installed.",
            project=project,
        )
        return "lifetime_too_short"

    # NO REGION RE-CHECK HERE, AND THE ABSENCE IS THE DECISION. An earlier version of this
    # function re-derived `vertex_openai_base_url(project)` one line before handing the
    # bearer over and refused a non-Mumbai result — which reads like diligence on the one
    # property this whole decision exists to protect, and is worth nothing: that function
    # interpolates the `Final` `VERTEX_LOCATION` into both the host and the `locations/`
    # segment, so the branch is unreachable by construction, and the URL it computed was
    # then used by nothing. A defensive arm that cannot be reached is a suppression
    # pretending to be a check (CLAUDE.md hard rule 10).
    #
    # WHERE RESIDENCY IS ACTUALLY ENFORCED, three places, none of them here: the AST proof
    # that every Google model URL written in this tree names Mumbai
    # (`scripts/check_model_residency.py`), `ModelConfig`'s validator refusing a non-Mumbai
    # Vertex URL by construction on the PUBLISH path, and `_agent_models` logging
    # `engine_llm_endpoint_unrecognised` when an agent reads back holding a URL we do not
    # recognise. A rotation-time check on a URL we computed ourselves proves nothing about
    # what the engine holds; the read-back is the one that does.
    fingerprint = _token_fingerprint(bearer.value)
    try:
        placement = await engine.set_llm_credential(bearer.value)
    except Exception as exc:
        # EVERY exception, not just `ProblemError`. The vendor ladder raises those, but a
        # bug in the adapter raises whatever it raises, and both leave the engine holding
        # a credential that is one interval closer to dead. `type(exc).__name__` and never
        # `str(exc)`: this is the one call site where the argument in scope is a bearer.
        log.error(
            "vertex_credential_install_failed",
            extra={"error": type(exc).__name__, "engine": engine.name},
        )
        _page(
            "The voice platform refused the rotated in-call LLM bearer. Model turns will "
            "fail once the installed credential expires.",
            project=project,
        )
        return "install_failed"

    log.info(
        "vertex_credential_rotated",
        extra={
            "engine": engine.name,
            "project": project,
            "fingerprint": fingerprint,
            "expires_in_s": int(remaining.total_seconds()),
            "replaced_in_place": placement.replaced_in_place,
            "superseded_removed": placement.superseded_removed,
        },
    )
    await _feed_dead_man()
    return f"rotated expires_in_h={int(remaining.total_seconds() // 3600)}"


async def _feed_dead_man() -> None:
    """Tell the external monitor this rotation loop is alive (D-408).

    THE ONE FAILURE THE ALARM ABOVE CANNOT REPORT is this job not running: a stopped
    worker, a container that never came back, a Redis it cannot reach. `_page` is raised
    BY the job, so a dead job raises nothing, and the in-call LLM leg then goes dark
    within twelve hours — on live calls, for every client at once, with no signal
    anywhere. Only an observer outside this process can turn that silence into a page,
    which is `scripts/host_heartbeat.py`'s argument applied a second time; the vendor
    choice and the rejected alternatives are argued there and not repeated here.

    CALLED FROM EXACTLY ONE PLACE — after a bearer was minted, checked and installed —
    and that is the whole mechanism. The three skip arms do not reach here (a deployment
    not on this leg has no credential whose freshness anyone could assert, and should not
    arm the check), and no failure arm reaches here either. **Adding a call on any other
    path would remove this alarm rather than extend it**, because what the monitor is
    watching for is silence, and a job that pings whatever happens is never silent.

    IT NEVER RAISES AND NEVER PAGES. It runs after the credential is already safely in
    place, so nothing here can undo a good rotation; and an undelivered heartbeat needs
    no alarm of its own, because the consequence of not sending it is that the dead man
    fires — which is the correct outcome and already a page. The log line below is what
    an operator reads to understand a dead-man page that arrived while rotation was in
    fact healthy. This is also why `vertex_credential` still has exactly ONE alert code.
    """
    url = (get_settings().in_call_llm_heartbeat_url or "").strip()
    if not url:
        # Stated, not silent, and not a failure: unset is correct locally, in CI, and on
        # any deployment not running this leg. A no-op that looks armed is the defect.
        log.info("in_call_llm_heartbeat_unarmed")
        return
    # A CLIENT OF ITS OWN, deliberately. The mint's client is scoped tightly around the
    # two Google calls and is closed before the engine install; reopening that scope to
    # carry a heartbeat would widen the window a credential-bearing client is alive to
    # save one handshake, six times a day.
    async with httpx.AsyncClient(follow_redirects=False) as http:
        delivered, reason = await ping_async(http, url, agent="llm-credential-heartbeat")
    if delivered:
        log.info("in_call_llm_heartbeat_sent", extra={"check": check_ref(url), "reason": reason})
        return
    log.error(
        "in_call_llm_heartbeat_undelivered",
        extra={"check": check_ref(url), "reason": reason},
    )


def _page(detail: str, *, project: str) -> None:
    """The one alarm this module raises, so every arm above pages identically.

    ONE CODE FOR EVERY FAILURE ARM, deliberately, and the count is NOT written down here —
    a number in prose goes stale the first time an arm is added and nothing notices (the
    defect class D-103/D-105 exist for). They differ in cause and not in consequence: every
    one ends with the engine holding a credential nobody refreshed, and the operator's
    first three steps are identical. The `detail` line is what tells them which arm it was;
    splitting it per arm would divide the noise-suppression budget across codes on an alarm
    whose whole value is that it fires early and keeps firing (`core/alerting.py` bounds
    one page per `stage:code` per 15 minutes).

    `WORKER_STALL` rather than `WORKER_TERMINAL`: the next tick will try again by itself,
    and nothing has been lost yet. What is running out is TIME.
    """
    alert("WORKER_STALL", "vertex_llm_credential_refresh_failed", detail=detail, project=project)


__all__ = [
    "IAM_CREDENTIALS_HOST",
    "MINT_TIMEOUT_S",
    "MIN_GRANTED_LIFETIME_S",
    "REFRESH_INTERVAL_HOURS",
    "TOKEN_LIFETIME",
    "TOKEN_LIFETIME_S",
    "MintedBearer",
    "mint_in_call_bearer",
    "refresh_in_call_llm_credential",
]
