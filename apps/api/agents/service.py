"""Agent configuration + the two paths that touch the engine.

`publish_agent` is where our world and the vendor's are married, and it is the reason
`engine_agent_routes` exists: the routing row and `agents.engine_agent_ref` are written
in the SAME transaction, so an inbound webhook can never arrive for an agent the
resolver cannot map.

`dispatch_call` is the single outbound entry point. Everything that places a call —
the D-21 Leads button today, campaigns and lead-callback webhooks in M2 — goes through
it, so the pre-dispatch call row, the metering hook and the audit trail exist exactly
once rather than three times.

WHICH PROMPT A PUBLISH SENDS (SURFACES §2b two-speed publishing)
---------------------------------------------------------------
`_load_agent` reads the APPLIED pointer, `COALESCE(live_prompt_id, system_prompt_id)`,
not the draft one. That single change is what makes a fast lane expressible at all:
this function sends ONE `AgentConfig` carrying script and voice and cap together, so
before `live_prompt_id` existed there was no way to push a voice change without also
pushing whatever unapproved script sat in `system_prompt_id`. It is exactly why
`voice_routes.py` refuses to publish and returns `republish_required` instead.

The COALESCE is safe rather than lenient, and the invariant that makes it safe lives
in `prompts.insert_prompt_version`: the one statement that can create a divergence
between the two pointers also materializes `live_prompt_id` in the same UPDATE. So
`live_prompt_id IS NULL` only ever means "the two pointers agree", never "the draft is
ahead" — which is also true of every row that predates the pointer (migration
a4e7b2c95d18 backfilled them) and of every row `admin/intake.py` writes.

WHAT "LIVE" IS ALLOWED TO MEAN (migration c1f6a94d2b07)
-------------------------------------------------------
`publish_agent` used to finish at "the vendor call returned without raising" and then
write four claims about the ENGINE — `status = 'live'`, `engine_agent_ref`,
`live_tts_voice`, and (through `apply_to_live`) `live_prompt_id`. All four were derived
from one fact about OURSELVES. D-64 put `VoiceEngine.get_agent` on the Protocol to close
exactly that, and nothing called it.

Now every publish reads the agent back and scores it (`agents/verification.py`). A PROVEN
mismatch is a refusal — the transaction rolls back, and nothing claims a script the
engine was observed not to be running. An UNPROVEN one (the adapter could not read the
field, or the read-back itself failed) is recorded in `live_verify_state` and rendered,
never rounded up. The four values and why `not_applied` is not one of them are in the
migration.

WHICH VOICE THE ENGINE IS HOLDING (migration c8b3f14e7a29)
----------------------------------------------------------
`publish_agent` is the ONLY place a voice reaches the engine, so it is the only place
that can say what the engine has. It records `agents.live_tts_voice` /
`live_tts_provider` from the `AgentConfig` it just sent, in the same UPDATE as
`engine_agent_ref`. `agents.tts_voice` stays the CONFIGURED voice, and the two are
allowed to differ because `voice_routes.set_agent_voice` writes the row without
publishing — so "does a republish change what callers hear?" is
`live_tts_voice IS DISTINCT FROM tts_voice`, which `agents/publishing.py` reads and
`GET /v1/agents/{agent_id}/pending` answers.

One known imprecision, in the safe direction: `publish_variant` sends the agent's
CONFIGURED voice to an experiment arm, and starting an experiment publishes arms
without publishing the agent. The arms can therefore be speaking the configured voice
while the agent's own engine object is not, and this mirror reports the agent — so the
answer is "republish required" when part of the traffic already moved. Over-reporting a
divergence costs one harmless publish; under-reporting one is a false claim about a live
phone line, which is the direction that must never happen.

THE CALL CAP (SURFACES §2b:107)
-------------------------------
`_to_config` fills `AgentConfig.max_call_duration_s` from the agent row. The field and
its vendor mapping already existed — `engine/bolna.py` renders it as the vendor's
`task_config.call_terminate` — and nothing filled it, so every agent on the platform
published the Pydantic default and no client could change it. Publish time is where
the guard is enforced because the engine is the only party that can hang up a call:
we are not in the audio path (hard rule 3), and an inbound runaway is never dispatched
by us at all, so a dispatch-side check would leave the receptionist motion unguarded.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NotRequired, TypedDict, TypeGuard, cast
from uuid import UUID

from calevate_shared.engine import (
    AgentConfig,
    CallContext,
    DisclosurePosture,
    LlmProvider,
    ModelConfig,
    NumberSeries,
    ProvisionedNumber,
    VoiceEngine,
    azure_openai_base_url,
    bind_model,
    compose_engine_prompt,
    compose_opening_line,
    leg_for_model,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import assignment
from apps.api.agents.llm_models import (
    UNAVAILABLE_REASON,
    ResolvedLlmModel,
    deployment_for,
    platform_default_model,
    resolve_llm_model,
)
from apps.api.agents.models import AGENT_DIRECTIONS, CALL_CAP_DEFAULT_S, AgentDirection
from apps.api.agents.verification import verify_publish
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.ownership import assert_visible
from apps.api.db.result import rowcount_of
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine, require_capability
from apps.api.engine.capabilities import ENGINE_COMPLIANCE_FLOOR_ABSENT
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.tenancy.lifecycle import assert_account_open

# THE ONE READER OF THE THREE `azure_openai_*` CREDENTIAL FIELDS, imported rather than
# re-derived (D-410). It lives beside the dashboard-AI client because that is where the
# first caller was, and it is not an extraction fact: it answers "does this deployment
# hold an Azure OpenAI credential", which since D-410 is ONE question with ONE answer for
# both LLM surfaces — they share a resource, a key and a deployment. A second read here
# would be the second place that decides what "configured" means, which is the D-103 /
# D-105 defect class, and it would also lose the half-set/unset distinction that function
# already draws (`azure_credential_incomplete`). `apps/api` importing `apps/workers` is
# the established direction here (`crm/assist.py`, `crm/service.py`, `admin/health.py`),
# and `workers/extraction.py` imports only `apps/api/core/*`, so there is no cycle.
from apps.workers.extraction import azure_credentials

log = get_logger(__name__)

#: The `calls.engine_call_id` of a dial WE have decided to place and the vendor has not
#: yet named. `engine_call_id` is `NOT NULL UNIQUE` and it is the key every reconciliation
#: path joins on, so the pre-dial intent row needs a value in it before the only party
#: that can supply the real one has answered — this prefix is that value's namespace.
#:
#: A NAMESPACED LOCAL ID RATHER THAN A NULLABLE COLUMN, and the choice is deliberate.
#: Making `engine_call_id` nullable would put "no id yet" and "we lost the id" into the
#: same NULL, and every reader that joins on the column (the poller's `_upsert_call`, the
#: drift sweep, `link_callback`) would need a NULL branch it has no way to resolve. A
#: value that is unmistakably OURS keeps the column NOT NULL, keeps the unique index
#: doing its job, and makes "the vendor never told us what it called this" a state you
#: can SELECT for — which is what `_reap_stuck_dialing` does with it.
#:
#: Collision with a vendor id is what the prefix rules out: an engine id is an opaque
#: vendor token (Bolna's is a uuid4 execution id, Cartesia's a `call_…` handle) and
#: neither can be minted by us, so nothing outside this module writes this shape.
UNCONFIRMED_ENGINE_CALL_PREFIX = "local:"

#: Engine failures that mean **no line was seized** — the dial can be retried, and the
#: contact keeps its place on the ladder.
#:
#: Everything NOT in this set is treated as "the phone may be ringing right now", which
#: is the conservative reading and is chosen on the cost asymmetry: a wrongly-retried
#: dial is a second unsolicited call to a real person (the behaviour the whole compliance
#: gate exists to bound), while a wrongly-abandoned dial is one contact a human has to
#: look at.
#:
#: THIS IS A SET OF CODES AND THE DECISION IS NOT — read `dial_was_not_placed`, which is
#: what callers use. `engine_rejected` used to be the uncomfortable member of the
#: "unconfirmed" side, because the ladder collapsed every 4xx AND 5xx into one code and
#: nothing downstream could tell "the vendor refused this request" from "a proxy answered
#: 502 after the vendor had committed". The ladder now carries the status
#: (`vendor_http.EngineRejectedError`), so the four statuses the vendor documents as refusals
#: are separated from the ambiguous rest — by the exception, not by adding four codes here.
#:
#: What would let us do better STILL is a vendor-side idempotency key on `POST /call`:
#: with one, a retry is safe whatever the failure was, including the 5xx half. **Bolna
#: documents none** — no idempotency key, no client request id, no dedupe window anywhere
#: in their 333 published pages (searched: `idempoten`, `request-id`, `dedup` — zero
#: hits). That is a stated negative, not an assumption (D-31/D-32's rule), and it is why
#: the 5xx half stays "the phone may be ringing".
DIAL_NOT_PLACED_CODES = frozenset(
    {
        # 429 with the ladder exhausted. The adapter's own note says a throttle "says
        # nothing about the request", and it is raised instead of sending it on.
        "engine_rate_limited",
        # All of these are raised BEFORE any HTTP request leaves this process.
        "engine_not_configured",
        "engine_capability_unverified",
        "engine_capability_absent",
        "engine_caller_id_not_configured",
        # This agent has more than one registered header and nothing here may pick
        # (`resolve_caller_id`). Raised before the adapter is touched, so no line was
        # seized — same standing as the two above.
        "agent_caller_id_ambiguous",
        # The dial arrived without the truthful-answer rule on it, or reached an engine
        # that has nowhere to put one (D-282). Refused inside the adapter before the
        # request is built, so no line was seized and the contact keeps its place — the
        # same standing as a missing caller id, and for the same reason.
        ENGINE_COMPLIANCE_FLOOR_ABSENT,
    }
)


def dial_was_not_placed(exc: BaseException) -> bool:
    """Did this failure PROVE that no line was seized? The one place that decides.

    Two ways to be sure, and both are read from the vendor rather than guessed:

    * the failure has one of `DIAL_NOT_PLACED_CODES` — a throttle, or one of the
      pre-flight refusals raised before any request left this process;
    * the vendor answered with a status its own documentation defines as a refusal of the
      REQUEST (`vendor_http.REQUEST_REFUSED_STATUSES` carries the four rows and their
      citations).

    THE SECOND ARM IS NEW AND IT CLOSES A REAL DEFECT, not a theoretical one. Before it,
    a `400 agent_id is required` — the vendor's own first worked example for `POST /call`
    — reached the campaign dispatcher as `DialUnconfirmedError`, which settles the contact
    TERMINALLY (`_settle_unconfirmed_dial`), escalates to the client, and never dials them
    again, on the grounds that their phone may have rung. It had not. One stale
    `engine_agent_ref` or one revoked API key therefore consumed a whole contact list,
    irreversibly, with an escalation per contact telling the client a human should check
    calls that were never placed. On the two CRM buttons it produced the same sentence to
    a tenant's face — *"it may have started the call anyway ... calling again could ring
    them twice"* — about a request the vendor threw away unread.

    Anything else is still "the phone may be ringing": every 5xx, every transport failure,
    and every 4xx the vendor does not document. See `REQUEST_REFUSED_STATUSES` for why
    that default cannot be relaxed by reasoning about which statuses feel safe.
    """
    if isinstance(exc, EngineRejectedError):
        return exc.request_refused
    return isinstance(exc, ProblemError) and exc.code in DIAL_NOT_PLACED_CODES


class DialUnconfirmedError(Exception):
    """The vendor may have started this call and we cannot prove it either way.

    The third outcome beside "dialled" and "refused". It carries the `calls.id` of the
    intent row — which is COMMITTED before the engine is asked, so the possible charge is
    on record — and the engine's error code for the operator log. Callers must treat it
    as "this person may have been rung": never as a reason to dial them again.
    """

    def __init__(self, *, call_id: UUID, code: str) -> None:
        super().__init__(f"dial outcome unknown (call_id={call_id}, code={code})")
        self.call_id = call_id
        self.code = code


def unconfirmed_engine_call_id(call_id: UUID) -> str:
    """The placeholder `engine_call_id` a pre-dial intent row carries."""
    return f"{UNCONFIRMED_ENGINE_CALL_PREFIX}{call_id}"


def effective_call_cap(max_call_duration_s: int | None) -> int:
    """The cap an agent is actually published with.

    NULL on the column means "the platform default", NEVER "unlimited" — the whole
    point of the guard is that there is no way to express an uncapped agent. The
    resolution lives here, in one function, so that a second reader cannot decide the
    sentinel means something else.
    """
    return CALL_CAP_DEFAULT_S if max_call_duration_s is None else max_call_duration_s


class AgentRow(TypedDict):
    """The agent record as the config builders below need it — declared, not `object`.

    **WHY THIS EXISTS, and it is not tidiness.** `_load_agent` returned
    `dict[str, object]`, and `_to_config` fed those values straight into `AgentConfig` and
    `ModelConfig` — including `direction`, whose field is
    `Literal["inbound", "outbound", "both"]`. Nothing checked the hop. mypy could not:
    `object` is not `str`, but `AgentConfig`'s Pydantic-synthesised `__init__` took `Any`
    for every argument until `[tool.pydantic-mypy] init_typed = true` was turned on, so
    the checker was verifying that arguments were PRESENT and never what they held. So a
    `direction` the CHECK constraint somehow admitted, or a column renamed under a
    SELECT that still parses, would have reached the vendor payload unexamined, and the
    first symptom would have been a Pydantic `ValidationError` inside a publish — or, for
    a value Pydantic also accepts, no symptom at all.
    Same instrument and same argument as `apps/api/engine/fake.py::_StoredCall`.

    **A TypedDict IS NOT A CAST**, and the difference is `_load_agent`'s `direction` line.
    Annotating a row that is built from `row[i]` (SQLAlchemy hands back `Any`) would move
    the unchecked hop rather than close it — the values would be *declared* rather than
    *known*. So the ONE field that lands on a `Literal` is narrowed by a real predicate
    with a real refusal at the read, and the rest are widths a `TEXT NOT NULL` column
    genuinely guarantees.

    Consumers take `AgentRow` rather than `dict[str, object]` for the same reason: a
    TypedDict is deliberately not assignable to `dict[str, X]`, so the type cannot be
    widened back to `object` halfway along the path by accident.
    """

    id: UUID
    name: str
    direction: AgentDirection
    language_primary: str
    #: The legacy bundled sentence (D-163). Still read for the drift comparison; never
    #: composed into a new `opening_line`.
    disclosure_line: str | None
    stt_provider: str | None
    stt_model: str | None
    #: What was configured ON THIS AGENT, or NULL to inherit the account's default. On an
    #: Azure leg the resolved value is deliberately ignored — `in_call_llm` explains why
    #: the endpoint and the identifier cannot be split.
    llm_model: str | None
    #: The ACCOUNT's default, read from `organizations` in the same statement so the
    #: middle rung of the fallback cannot be resolved against a different transaction's
    #: view of the row. NULL means the account never chose.
    organization_llm_model: str | None
    tts_provider: str | None
    tts_voice: str | None
    engine: str
    #: NULL until the first successful publish, which is what `agent_not_published` means.
    engine_agent_ref: str | None
    status: str
    #: The APPLIED prompt body, or NULL when no version has been applied —
    #: `_assert_has_a_script` is the one place that refusal is worded.
    prompt: str | None
    #: NULL means "the platform default", never "unlimited" (`effective_call_cap`).
    max_call_duration_s: int | None
    ai_disclosure_line: str
    ai_disclosure_enabled: bool
    recording_notice_line: str
    recording_notice_enabled: bool


def _is_agent_direction(value: object) -> TypeGuard[AgentDirection]:
    """Is this database value one of the three directions an agent can have?

    A `TypeGuard` rather than a `cast` because the two are opposites in the only way that
    matters: a cast asserts and moves on, while this ASKS — the runtime check is real, and
    the checker's narrowing is a consequence of the check rather than a substitute for it.
    One place, so the vocabulary cannot be re-spelled at a second call site.
    """
    return value in AGENT_DIRECTIONS


async def _load_agent(
    session: AsyncSession, tenant_id: UUID, agent_id: UUID, *, for_update: bool = False
) -> AgentRow:
    """The agent as an `AgentConfig` needs it, optionally under a row lock.

    `for_update` is the publish path's, and only the publish path's. The read alone is a
    read-then-write over `engine_agent_ref` — read "no ref", call `create_agent`, write
    the ref back — and two publishes interleaving there produce TWO vendor-side agents
    for one row, of which we can record exactly one. The other is an orphan: an object we
    are billed for, cannot address, and have no record of. BACKEND-PATTERNS §5 wants CAS
    or a lock; a CAS cannot serve here because the value being decided (the vendor's id)
    does not exist until after the side effect, so the lock is the only instrument that
    covers the window.

    `FOR UPDATE` on `agents` only — not on the LEFT JOINed `prompt_versions`, which
    `agents/prompts.py` keeps immutable and which a lock would needlessly block a
    concurrent version WRITE against. `OF a` is what says so.

    Deliberately NOT the default: `dispatch_call` reads through here on the outbound hot
    path and takes no lock, because it decides nothing about the row — it reads a ref and
    dials it, and a publish landing mid-dial changes which script the NEXT call speaks,
    never this one.
    """
    row = (
        await session.execute(
            text(
                "SELECT a.id, a.name, a.direction, a.language_primary, a.disclosure_line, "
                "a.stt_provider, a.stt_model, a.llm_model, a.tts_provider, a.tts_voice, "
                "a.engine, a.engine_agent_ref, a.status, pv.body, a.max_call_duration_s, "
                # The four columns that decide what this agent OPENS with (D-163). Read
                # here, on the one path that builds an `AgentConfig`, so a publish and
                # the drift read can never disagree about the posture.
                "a.ai_disclosure_line, a.ai_disclosure_enabled, "
                "a.recording_notice_line, a.recording_notice_enabled, "
                # The ACCOUNT's model default, joined rather than fetched separately: the
                # fallback is decided from these two columns together, and two statements
                # would let a concurrent change to the account default land between them —
                # a published config whose two halves came from different moments.
                "o.default_llm_model "
                "FROM agents a LEFT JOIN prompt_versions pv "
                # The APPLIED pointer, not the draft one — see the module docstring.
                "ON pv.id = COALESCE(a.live_prompt_id, a.system_prompt_id) "
                # LEFT, not INNER, so an agent whose organization row is somehow invisible
                # still publishes on the platform default rather than vanishing: this
                # statement's job is to find the agent, and RLS has already decided which
                # organization row is legible (the policy matches on `id`).
                "LEFT JOIN organizations o ON o.id = a.tenant_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
                + (" FOR UPDATE OF a" if for_update else "")
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    direction = row[2]
    if not _is_agent_direction(direction):
        # UNREACHABLE THROUGH THE FRONT DOOR, and asked anyway. `ck_agents_direction_enum`
        # renders from the same Literal this narrows to, so the column cannot hold
        # anything else while that constraint is attached — and "while that constraint is
        # attached" is the whole reason this is a check rather than a cast. A migration
        # that drops and rebuilds the table, a restore that lands without constraints
        # (`runbooks/restore-drill.md` walks exactly that path), or a hand-run UPDATE by
        # an operator all produce a row this narrowing refuses. Refusing costs one agent's
        # publish and names the cause; the alternative is a direction the engine has never
        # heard of on an agent that answers a client's phone.
        log.error(
            "agent_direction_unrecognised",
            extra={"agent_id": str(agent_id), "tenant_id": str(tenant_id)},
        )
        raise ProblemError.business_rule(
            "agent_direction_unrecognised",
            "This agent's calling direction is not one we recognise, so it cannot be "
            "published or dialled.",
            remediation="Set the agent to inbound, outbound or both and try again.",
        )
    return {
        "id": row[0],
        "name": row[1],
        "direction": direction,
        "language_primary": row[3],
        "disclosure_line": row[4],
        "stt_provider": row[5],
        "stt_model": row[6],
        "llm_model": row[7],
        "tts_provider": row[8],
        "tts_voice": row[9],
        "engine": row[10],
        "engine_agent_ref": row[11],
        "status": row[12],
        "prompt": row[13],
        "max_call_duration_s": row[14],
        "ai_disclosure_line": row[15],
        "ai_disclosure_enabled": row[16],
        "recording_notice_line": row[17],
        "recording_notice_enabled": row[18],
        "organization_llm_model": row[19],
    }


def posture_of(agent: AgentRow) -> DisclosurePosture:
    """The agent row's four disclosure columns as the one value the composer takes.

    Here rather than inline in `_to_config` because `_variant_config` needs the same
    posture with ONE field swapped (an experiment arm may carry its own AI sentence), and
    two hand-rolled constructions of the same dataclass is where an arm silently starts
    disclosing on a different setting from the agent it is testing.
    """
    return DisclosurePosture(
        ai_disclosure_line=str(agent["ai_disclosure_line"]),
        ai_disclosure_enabled=bool(agent["ai_disclosure_enabled"]),
        recording_notice_line=str(agent["recording_notice_line"]),
        recording_notice_enabled=bool(agent["recording_notice_enabled"]),
    )


def _assert_has_a_script(agent: AgentRow) -> str:
    """The agent's applied script, or a refusal — never a stand-in.

    `_to_config` used to read `str(agent["prompt"] or "You are a helpful receptionist.")`,
    and that default is reachable in the ONE state the wizard leaves an agent in before
    step 3: `admin/service.create_organization` mints the receptionist row with no
    `prompt_versions` row at all. Pressing Publish there answered 200 `status: live`,
    wrote the routing row, and put a hardcoded ENGLISH sentence on a Telugu clinic's
    phone line — with no hours, no prices, no staff names and nothing to tell a caller
    which business they had reached. Every screen downstream then read `live`.

    A missing script is not a value to substitute. It is FLOWS §1's step-3-before-step-7
    ordering being skipped, and the honest answer is a refusal naming the step. The
    disclosure line gets this treatment already (non-null by schema, hard rule 5); the
    script had no equivalent guard because the default hid the case.

    NOT a check for a *good* script — that is step 7's test call, which is pilot-gated
    and outside this function. This is the floor: there is one, and it is the client's.
    """
    prompt = agent.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt
    raise ProblemError(
        kind="business_rule",
        code="agent_has_no_script",
        title="This agent has no script yet",
        detail=(
            "The agent has no prompt version, so there is nothing to publish. Publishing "
            "it would put a generic placeholder on the client's phone line."
        ),
        remediation=(
            "Complete the intake step for this client, or write a prompt version, then publish."
        ),
    )


class InCallLLM(TypedDict):
    """The three `ModelConfig` LLM fields `in_call_llm` decides, as a shape.

    `llm_provider` and `llm_base_url` are `NotRequired` because the two arms genuinely
    differ in ARITY, not just in value: an unconfigured deployment returns the model alone
    and leaves the other two at `ModelConfig`'s defaults, which is what "no Azure leg"
    means. Spelling them `| None` instead would make the difference invisible to a reader
    and would let a future arm send `llm_provider=None` beside a real `llm_base_url`.
    """

    llm_model: str | None
    llm_provider: NotRequired[LlmProvider]
    llm_base_url: NotRequired[str]


def resolved_llm_model(agent: AgentRow) -> ResolvedLlmModel:
    """Which model this agent runs, and which level said so (D-454).

    ONE resolver for the whole product — `agents/routes.py` reports it, `llm_routes.py`
    reports the account's half of it, and `_to_config` sends it. A second `or` chain at
    any of those is how the screen and the phone line start disagreeing about which model
    is running, which is the class of defect D-103/D-105 exist for.

    A thin wrapper over `resolve_llm_model` on purpose: that function takes two nullable
    strings and no row type, so it stays testable without a database, and this one is
    where the row's column NAMES are spelled — once.
    """
    return resolve_llm_model(
        agent_model=agent["llm_model"], organization_model=agent["organization_llm_model"]
    )


def chosen_llm_model(agent: AgentRow) -> str | None:
    """The model somebody EXPLICITLY chose for this agent, or `None` if nobody did.

    Not the same question as `resolved_llm_model`, and the difference is what `_to_config`
    needs: the resolver always answers, because the platform rung is always there, while
    an engine leg that has no Azure credentials needs to be able to say "no model
    configured, use your own default". Derived FROM the resolver rather than by a second
    `or` chain, so the two can never disagree about which level won.
    """
    resolved = resolved_llm_model(agent)
    return None if resolved.source == "platform" else resolved.model


def in_call_llm(configured_model: str | None) -> InCallLLM:
    """The LLM leg's three `ModelConfig` fields for one agent — D-410's one decision point.

    THE WHOLE SWITCH LIVES HERE, and that is the reason this function exists rather than
    three expressions inline. D-400 made the canonical in-call LLM a paid one; D-410
    re-aimed it at Azure OpenAI in `AZURE_LOCATION`. Between a decision and its delivery
    there is always a temptation to leave the decision as prose and the code as it was —
    and then nobody can say what "when it lands, flip it" actually means. It means this
    function, and nothing else.

    THREE CONDITIONS, AND EVERY ONE IS NECESSARY — resource, key, deployment. They are
    not three settings that happen to travel together; each names a different way the leg
    fails, and each fails at a different, worse moment:

    1. **A RESOURCE** (`azure_openai_resource`). It is the first label of the hostname, so
       without it there is no endpoint to name at all.
    2. **A KEY** (`azure_openai_api_key`). **This is D-404's condition in its Azure form,
       and it is still the one a reviewer would drop.** The resource and the deployment
       are enough to BUILD a URL, so a leg configured from those two alone looks complete
       and points every agent at an endpoint nothing can authenticate against. That does
       not fail at publish time, where somebody would see it. It fails as a 401 from
       Azure, mid-sentence, on a client's live phone call.
    3. **A DEPLOYMENT** (`azure_openai_deployment`). Azure serves a model under a
       deployment ID the operator chose, and the v1 surface addresses THAT. A resource
       with no deployment addresses a host and no model.

    ⚠ **WHAT THE KEY CHECK CAN AND CANNOT PROVE, AND THE GAP GOT WIDER RATHER THAN
    NARROWER WHEN THE VENDOR'S DOCS WERE READ.** It proves WE hold a key. It does not
    prove the ENGINE holds it: Bolna authenticates from its own credential store, which
    `VoiceEngine.set_llm_credential` writes. The store's field NAMES are no longer a
    guess — their Azure OpenAI provider documents FOUR required entries
    (`apps/api/engine/bolna.py::_AZURE_PROVIDER_KEYS`), and
    `Settings.bolna_llm_credential_name` now defaults to the first of them,
    `AZURE_OPENAI_API_KEY`. But the platform can only PUSH that one: the endpoint, the
    deployment and an api-version whose value nothing here can derive are the operator's
    to install, so "the engine is configured" is further from "we hold a key" than it was
    when this comment believed one entry was the whole of it. The condition stays "this
    deployment holds a key it could install", which is the strongest thing a publish path
    can check without doing the vendor's bookkeeping for it, and OPERATIONS §2 gate 16f
    is where the rest is observed.

    WHAT D-410 DELETED FROM THIS LADDER, said plainly rather than left as an absence:
    the founder's constant (`VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE`) is gone with the
    Vertex leg, and the switch is now the configuration itself — a deployment holding no
    Azure credential publishes exactly as it did before. And **the D-404 hazard the third
    condition guarded against has changed shape rather than survived**: under Vertex, the
    dashboard AI needed only a project id while the in-call leg needed a mintable bearer,
    so turning the assistant on could silently move the phone line. Under D-410 both
    surfaces read the SAME three fields, so configuring the dashboard assistant does move
    the in-call leg — deliberately, because it is one credential to one resource in one
    region, which is D-410's whole argument. What must never happen is a HALF-configured
    move, which is what `azure_credentials()` refuses.

    THE MODEL IDENTIFIER MOVES WITH THE ENDPOINT, and this is the half a reviewer would
    wave through. An Azure leg never sends a model NAME: the wire value is a deployment id,
    so `agents.llm_model` cannot be pasted onto it. **This paragraph used to end "and the
    column is deliberately ignored", which was right while nothing could write the column
    and became a money defect the moment something could** (D-454): ignoring a choice means
    quoting the model the client picked and running the one the single deployment serves.
    The column is not ignored and it is not pasted through either — it SELECTS, via
    `deployment_for()`, and the paragraph below is that rule.

    **THE CHOSEN MODEL PICKS THE DEPLOYMENT, WHICH IS THE WHOLE OF D-454'S WIRE HALF.**
    `configured_model` is what somebody CHOSE for this agent — its own column, or its
    account's default (`chosen_llm_model`) — or `None` when nobody chose, which on this
    arm means the platform's own model. It is not decorative and it is not only a pricing
    key: `deployment_for()` turns it into the deployment id that actually serves it, so a
    client who selects `gpt-4.1-mini` gets an agent published against the `gpt-4.1-mini`
    deployment. Before that, a selection could be recorded and quoted at 2.7x while every
    call ran the default deployment — charging for something we did not deliver, with
    nothing in a transcript or an execution payload to show it.

    ⚠ **AND IT REFUSES RATHER THAN FALLING BACK when no deployment serves the chosen
    model.** The API cannot normally produce that state (`validate_llm_model` refuses the
    selection at the write path, from the SAME `addressable_models()` predicate), so this
    is the arm for the one way it can still arise: an operator removing a deployment entry
    from `Settings.azure_openai_deployments` under accounts that already chose. Falling
    back to the default deployment there is precisely the silent wrong-model charge this
    exists to prevent, and falling back to "no model" would put a client's agent on the
    engine's own default. A refusal costs one publish and names what an operator must do;
    it does not touch agents that are already live, which keep the deployment they were
    published against.

    ⚠ **`llm_model` IS THE DEPLOYMENT ID HERE, NOT `Settings.azure_openai_model`**, and
    on every other OpenAI-compatible provider those would be the same string. The model
    name records which model the deployment was made from; it is what
    `LLM_MODELS[model].price` prices and it never goes on the wire.
    `ModelConfig.llm_model` says the same thing at the other end of this seam.

    **THE PROVIDER NAME AND THE MODEL BINDING BOTH COME FROM THE DECLARED POSTURE (D-432)**
    rather than being spelled here. This function is still the ONE decision point for the
    leg; what moved is that it no longer re-states WHICH posture is in force. `"azure_openai"`
    was a third spelling of a decision that had no first — the posture is declared once, in
    `calevate_shared.engine.DECLARED_POSTURE_NAME`, and `scripts/check_model_residency.py`
    fails the build when the declaration and the tree disagree in either direction. A caller
    reading `binding.addressed` gets the right string under every posture, which is what
    stops the wire/price distinction being a convention two settings apart.

    Returns a dict rather than a `ModelConfig` because the caller is building one with the
    speech legs alongside, and two `ModelConfig`s merged is a second place for the LLM
    fields to be decided. `InCallLLM` rather than `dict[str, object]`, so that dict stays
    CHECKED where it is splatted into `ModelConfig`: an `object` value unpacked through
    `**` widens EVERY keyword at that call site, which is how these three fields and the
    four speech fields beside them all became unverified together.
    """
    credentials = azure_credentials()
    if credentials is None:
        return {"llm_model": configured_model}
    # THE THIRD ELEMENT IS DELIBERATELY DROPPED. `azure_credentials()` answers "is this
    # leg configured at all", and the deployment it returns is the PLATFORM model's —
    # which is the right one only when nobody chose. Which deployment serves the model
    # this agent actually runs is `deployment_for()`'s question, and it is the only
    # function permitted to answer it. (For an agent on the platform model the two are the
    # same string, read from the same field, so there is no second source of truth here.)
    resource, _api_key, _platform_deployment = credentials
    # The platform's own model is the last rung of `agent -> organization -> platform`,
    # applied HERE because this is the arm where it means something: on the passthrough
    # arm above there is no Azure leg for it to name. `platform_default_model()` is the
    # same function the API's resolver uses for the same rung, so the model this publishes
    # and the model the screen reports are one decision.
    model = configured_model or platform_default_model()
    deployment = deployment_for(model)
    if deployment is None:
        log.error(
            "agent_llm_model_has_no_deployment",
            # The MODEL, never a client's own values: it is a platform configuration
            # constant and it is the whole of what an operator has to act on.
            extra={"llm_model": model},
        )
        raise ProblemError(
            kind="business_rule",
            code="llm_model_not_deployed",
            title="This agent's language model is not switched on for this platform",
            detail=(
                f"The agent is set to run {model}, and {UNAVAILABLE_REASON}. Publishing it "
                "against a different model's deployment would run — and bill — a model "
                "nobody chose."
            ),
            remediation=(
                "Choose a model this platform runs, or ask support to switch this one on."
            ),
        )
    # THE TWO MODEL STRINGS, BOUND UNDER THE DECLARED POSTURE rather than picked apart
    # here (D-432). `bind_model` is what knows that on this posture the API addresses a
    # DEPLOYMENT and the model name is only the cost model's key; a posture that addresses
    # the model by its own name binds both to one string and refuses a stray deployment id.
    # Reading `.addressed` (never `.priced`) is what makes the wire/pricing distinction a
    # property of a type instead of a comment two settings apart.
    #
    # `model` rather than `Settings.azure_openai_model` on the priced half: the deployment
    # above was chosen BECAUSE it serves this model, so the pair cannot describe two
    # different models — which is the wrong-invoice failure this whole seam exists for.
    binding = bind_model(deployment=deployment, model=model)
    return {
        "llm_model": binding.addressed,
        # From the MODEL, not the posture (D-456): three legs are declared, so the
        # provider follows the model that was actually resolved above. Reading it off the
        # posture would have named one vendor for every leg the day a second was declared.
        "llm_provider": leg_for_model(model).provider,
        "llm_base_url": azure_openai_base_url(resource),
    }


def _to_config(tenant_id: UUID, agent: AgentRow) -> AgentConfig:
    settings = get_settings()
    return AgentConfig(
        tenant_id=str(tenant_id),
        agent_id=str(agent["id"]),
        name=str(agent["name"]),
        # Not `str(...)`: the row narrowed this to the same Literal `AgentConfig`
        # declares (`_is_agent_direction`), and re-widening it here would put the
        # unchecked hop back in the one place it mattered.
        direction=agent["direction"],
        language_primary=str(agent["language_primary"]),
        system_prompt=_assert_has_a_script(agent),
        # WHAT THE AGENT VOLUNTEERS FIRST, composed from this agent's two toggles by the
        # one composer (D-163). Empty is a legitimate answer — both notices switched off
        # — and is NOT the old "missing disclosure" state: the AI sentence is still
        # NOT NULL on the row, the compliance gate still refuses an agent without one,
        # and the answer to a caller who ASKS is `TRUTHFUL_ANSWER_DIRECTIVE`, which no
        # column on this row can reach.
        opening_line=compose_opening_line(posture_of(agent)),
        models=ModelConfig(
            stt_provider=agent["stt_provider"],
            stt_model=agent["stt_model"],
            # The LLM leg is resolved, not read: see `in_call_llm` for why the endpoint
            # and the identifier it addresses cannot be configured apart (D-410).
            #
            # THE CHOSEN MODEL, WHICH IS THE AGENT'S OR THE ACCOUNT'S — never the
            # platform rung, and that omission is the decision. On a deployment with an
            # Azure leg this argument is ignored outright (the wire value is the
            # deployment id), so the only leg it reaches is the one with NO Azure
            # credentials, where `None` means "whatever the engine's own default is" —
            # the body every agent row in this repository has always produced. Sending
            # the platform rung there would substitute an Azure model identifier into a
            # request aimed at a provider we have not configured, changing live agent
            # bodies on an unanswered vendor question, which is exactly what
            # `engine/bolna.py::_llm_routing` refuses to do. An EXPLICIT choice is
            # different: somebody asked for it, so it goes.
            **in_call_llm(chosen_llm_model(agent)),
            tts_provider=agent["tts_provider"],
            tts_voice=agent["tts_voice"],
        ),
        webhook_url=f"{settings.webhook_base_url}/hooks/v1/engine/{settings.engine}",
        # The cost-runaway guard. Resolved here rather than defaulted in the model, so
        # an agent that has never been given a cap is still published with one.
        max_call_duration_s=effective_call_cap(agent["max_call_duration_s"]),
    )


def _call_prompt_for(engine: VoiceEngine, tenant_id: UUID, agent: AgentRow) -> str | None:
    """The prompt this dial must CARRY, or None when the engine already holds it.

    THE PRODUCTION WRITER OF `CallContext.system_prompt` (D-282), and the reason the field
    is not a fixture. On a `control_plane` engine the prompt is agent-record state that
    `publish_agent` wrote and `verification.judge` PROVED the engine is running, so a
    second copy per call would be one string with two authorities — the drift this repo
    treats as a defect even when both copies agree. On an `external_deployment` engine
    there is no agent record, so this is the only vehicle hard rule 5 has and every dial
    carries it.

    IT GOES THROUGH `_to_config` AND `compose_engine_prompt`, never a second rendering.
    That is the argument `engine_drift_for` already makes for reusing `_to_config`: a
    prompt built here by hand would be a second expression of our intent, and the two
    would diverge on the part nobody reads — which on this path is the platform-rules
    block underneath the script, i.e. exactly the part that may not be lost.

    The adapter still checks what it received (`require_call_compliance_floor`). A guard
    here and a guard there is not two ways to do one thing: this composes, that refuses,
    and the refusal is the one that has to survive a future caller reaching
    `start_outbound_call` without coming through this function.
    """
    if engine.capabilities.hosts_agents():
        return None
    return compose_engine_prompt(_to_config(tenant_id, agent))


async def _reclaim_orphan(engine: VoiceEngine, agent_id: UUID, ref: str, reason: str) -> None:
    """A vendor-side agent we created and then could not record. DELETE IT, or log it.

    THE SHAPE OF THE PROBLEM. `create_agent` is a side effect at a third party; our write
    of `engine_agent_ref` is a side effect in our database. There is no transaction
    spanning both, so a failure in the window between them — the read-back proving the
    engine is not running what we sent, the row being soft-deleted underneath us — rolls
    OUR half back and leaves theirs standing. The result is an agent object we are billed
    for and can never address again, because the only copy of its id was in the
    transaction that rolled back.

    **THE COMPENSATION, AND WHY IT IS INLINE.** `VoiceEngine.delete_agent` now exists, so
    the remedy is a call rather than a note. It happens HERE, synchronously, before the
    caller raises — NOT through the outbox and not through an arq enqueue — because the
    ref lives only in this frame. The outbox is transactional (BACKEND-PATTERNS §4) and
    this transaction is about to roll back, so an outbox row would roll back with it and
    take the only copy of the ref down; a direct enqueue would survive but adds a second
    thing that can fail while we are already holding the failure. One vendor round trip on
    a path that is already failing is a cost worth paying to not leak a billed object.

    **BEST-EFFORT, and the log line is still the floor.** If the delete raises — the
    vendor is the thing that was misbehaving a moment ago, so it might — we are exactly
    where we were before this function grew a remedy: an ERROR carrying the ref, which is
    the operator's copy. `ref` is a vendor-issued opaque id, not a phone number, not
    transcript text, not an extraction payload, so hard rule 6 permits it. Nothing is
    re-raised: this is compensation for a failure the caller is about to report, and
    failing the publish a second way would replace an actionable error with a confusing
    one.

    **`delete_agent` IS NOT CALLED ON A HUMAN'S SOFT-DELETE**, and that is deliberate.
    Bolna's delete destroys the agent's executions with it, and a soft-deleted agent's
    call history is a retention obligation of ours (SECURITY-COMPLIANCE §4). The subject
    here is an agent minted seconds ago that has never taken a call, which is the only
    population for which "remove it entirely" is the right answer.

    Why a `lock` makes this rare rather than routine: `_load_agent(for_update=True)`
    serializes publishes on one agent, so the common cause — two concurrent publishes
    both seeing "no ref" and both creating — cannot happen at all.
    """
    ids = {
        "agent_id": str(agent_id),
        "engine": engine.name,
        "engine_agent_ref": ref,
        "reason": reason,
    }
    try:
        await engine.delete_agent(ref)
    except Exception as exc:
        # Broad on purpose: the remedy must never become a new way for the publish to
        # fail. `exc.__class__.__name__` and nothing from the exception's text — an
        # adapter normalizes to `ProblemError`, but a transport error could arrive raw.
        log.error(
            "engine_agent_orphaned",
            extra={**ids, "reclaim_failed": exc.__class__.__name__},
        )
        return
    log.warning("engine_agent_orphan_reclaimed", extra=ids)


#: Every number an admin has pointed at this agent (`phone_numbers.agent_id`), with the
#: engine's own handle for each. `dlt_status` is NOT filtered: inbound answering is not a
#: DLT-header question — that regime governs what a number may be used to SEND — and a
#: receptionist that refuses to answer until the outbound paperwork clears would be a
#: compliance rule invented here.
_AGENT_NUMBERS_SQL = (
    "SELECT id, e164, series, provider, engine_number_ref FROM phone_numbers "
    "WHERE agent_id = :aid ORDER BY created_at, id"
)


@dataclass(frozen=True, slots=True)
class InboundRouting:
    """What reaching the engine about this agent's numbers actually achieved (D-420).

    Returned rather than logged-and-forgotten because "the console said it worked" is the
    defect being closed: a caller that wants to tell an operator what happened needs the
    counts, and a test that wants to prove a number was routed needs something to assert.
    """

    #: Numbers the engine will now answer with this agent.
    bound: int
    #: Numbers the engine will no longer answer with this agent — an outbound-only agent.
    released: int
    #: Numbers that could not be reached about. Each one has raised an alarm.
    failed: int
    #: Numbers not attempted because this engine cannot route them at all.
    unsupported: int


def agent_answers_inbound(direction: AgentDirection) -> bool:
    """Does an agent with this direction pick up an incoming call?

    One place, so `publish_agent` and `agents/lifecycle.py` cannot disagree about what
    `both` means. It is the whole content of `route_inbound_numbers`' `answers` argument
    and it used to be computed inside that function from a `direction: str` — which forced
    the deactivate path to pass the word "outbound" to mean "stop answering", a value that
    is true of the release it wants and false of the agent it is releasing.
    """
    return direction in ("inbound", "both")


async def route_inbound_numbers(
    session: AsyncSession, engine: VoiceEngine, *, agent_id: UUID, ref: str, answers: bool
) -> InboundRouting:
    """Make the engine agree with `phone_numbers.agent_id` (D-420).

    **THE STEP THAT WAS MISSING BETWEEN OUR DATABASE AND A RINGING PHONE.** Assigning an
    agent to a number wrote `phone_numbers.agent_id` — with real care, including D-331's
    cross-tenant FK check — and stopped there. The vendor's own instruction is not
    ambiguous: *"You will need to assign a phone number to your Bolna Voice AI agent for
    automatically answering all incoming calls on that phone number"*, and the route that
    does it (`POST /inbound/setup`) was called nowhere in this repository. So an admin
    assigned a receptionist, the console said it worked, and the number answered with
    whatever was last set in the vendor's dashboard — or did not answer at all. Inbound is
    half this product, and its first configuration step was a screen with nothing behind it.
    `engine_agent_routes` was never this wire: it maps `engine_agent_ref → (tenant, agent)`
    so an INCOMING webhook can be attributed, which is the opposite direction.

    **`answers=False` RELEASES THE NUMBERS RATHER THAN BEING SKIPPED**, and that is the
    half a symmetry-free implementation would have missed. `agents.direction` is editable:
    an agent that was `both` and is republished as `outbound` must STOP answering, and
    leaving the engine's binding in place would keep a receptionist live on a number whose
    owner has just switched it off in our console — the same class of lie in the opposite
    direction. This is also `unbind_inbound_number`'s production caller, which is why the
    Protocol has both halves rather than only the one this function needed first. The same
    arm is what `agents/lifecycle.py` uses to take a deactivated or archived agent off the
    numbers it was answering, which is why the argument is the ANSWER rather than the
    direction it is usually derived from (`agent_answers_inbound`).

    **A FAILURE ALARMS AND DOES NOT FAIL THE PUBLISH**, deliberately, and it is not
    swallowing. The agent itself published and verified; the number binding is a separate
    engine fact, and whether a non-Twilio Indian number binds through that route at all is
    an OPEN vendor question (OPERATIONS §2 gate 25). Raising here would make every publish
    on this platform depend on an endpoint nobody has yet exercised against an Indian
    number — turning a known-unknown into an outage — while a named alarm per number tells
    an operator exactly which one is not answering and why. What is NOT acceptable, and was
    the state before this function, is neither.

    Ids and counts in every log line and every alarm; no phone number (hard rule 6).
    """
    rows = (await session.execute(text(_AGENT_NUMBERS_SQL), {"aid": agent_id})).all()
    if not rows:
        return InboundRouting(bound=0, released=0, failed=0, unsupported=0)
    # ASKED ONCE, not per number. An engine that cannot route numbers at all is a
    # deployment fact, not an incident: it refuses at the console through the same
    # capability, and one alarm per number per publish would page about a platform
    # property rather than an event. NOT unreachable, and this comment used to say it was:
    # no `external_deployment` engine can reach here THROUGH `publish_agent` (it has no
    # agent of ours to publish), but the arm is a property of the ENGINE, not of that one
    # path — `EXTERNAL_DEPLOYMENT_CAPABILITIES` answers `inbound_binding=False` and
    # `caller_id_and_inbound_routing_test` drives this line with it directly.
    if not engine.capabilities.has("inbound_binding"):
        log.info(
            "engine_inbound_binding_unsupported",
            extra={"agent_id": str(agent_id), "engine": engine.name, "numbers": len(rows)},
        )
        return InboundRouting(bound=0, released=0, failed=0, unsupported=len(rows))

    bound = released = failed = 0
    for number_id, e164, series, provider, engine_number_ref in rows:
        # The DB's own CHECK constraint is what makes this cast safe: `phone_numbers.series`
        # is `IN ('140', '160', 'standard')`, which is `NumberSeries` exactly.
        spec = ProvisionedNumber(
            e164=str(e164),
            provider=provider,
            engine_number_ref=engine_number_ref,
            series=cast(NumberSeries, str(series)),
        )
        try:
            if answers:
                await engine.bind_inbound_number(ref, spec)
                bound += 1
            else:
                await engine.unbind_inbound_number(spec)
                released += 1
        except ProblemError as exc:
            failed += 1
            alert(
                "CORE_LOGIC",
                "engine_inbound_binding_failed",
                detail=(
                    "the voice platform was not told which agent answers this number, so "
                    "an incoming call on it reaches whatever the vendor console was last "
                    f"set to — or nothing. Intent: {'answer' if answers else 'stop answering'}. "
                    f"Refusal: {exc.code}."
                ),
                agent_id=str(agent_id),
                number_id=str(number_id),
            )
    log.info(
        "agent_inbound_numbers_routed",
        extra={
            "agent_id": str(agent_id),
            "engine": engine.name,
            "bound": bound,
            "released": released,
            "failed": failed,
        },
    )
    return InboundRouting(bound=bound, released=released, failed=failed, unsupported=0)


async def publish_agent(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> str:
    """Create or update the agent on the engine, VERIFY it, then record the mapping.

    The routing row is written HERE, in the same transaction as `engine_agent_ref`,
    because the alternative — writing it from a webhook handler on first sight — means
    the first call for a new agent is the one that gets lost.

    THE READ-BACK (D-64, `agents/verification.py`). This used to end at "the vendor call
    returned without raising", and then wrote `status = 'live'`, `engine_agent_ref` and
    the voice mirror — four claims about the ENGINE, all derived from one fact about
    OURSELVES. Now the agent is read back through `VoiceEngine.get_agent` and scored; a
    PROVEN mismatch is a refusal (the transaction rolls back and no column claims a
    script the engine was observed not to hold), and an unproven one is recorded as
    `live_verify_state` rather than rounded up to success.

    THE LOCK. `for_update=True` — see `_load_agent`. It closes the create/create race
    that manufactures orphans and it serializes a publish against a concurrent
    `set_call_cap`, `apply_to_live` or `set_agent_voice` republish, all of which reach
    this function and all of which read-then-write the same row.
    """
    # THE ACCOUNT MUST STILL BE OPEN (D-194). Publishing is what puts an agent on the
    # phone, and this asked nothing about the organisation it belongs to — so an operator
    # with a hand-typed uuid could put a CHURNED or ERASED client's agent back into
    # service: answering calls, collecting caller numbers, against a tenant on a retention
    # clock and, after an erasure, under a certificate saying that data is gone. Every
    # other key-minting surface already asked (`admin.service` at both ends of an
    # invitation); this one is the loudest of them and was the one that did not.
    #
    # FIRST, before the lock and before the vendor: a refusal here costs one indexed read
    # and leaves the engine untouched, whereas refusing after `create_agent` would leave an
    # agent at the vendor with nothing pointing at it. `suspended` is deliberately allowed
    # through — see the predicate, which argues why a billing stop is not an access stop.
    await assert_account_open(session, tenant_id=tenant_id)

    engine = get_engine()
    # SECOND, and still before the lock and the vendor (D-281). Publishing IS
    # creating-an-agent-and-proving-what-it-holds, and on an engine whose agents are
    # programs deployed elsewhere neither half exists: there is no `create_agent` to call
    # and no prompt to read back. Asking the capability here turns that from a 404 arriving
    # mid-transaction — indistinguishable from a vendor outage, so an operator retries it
    # for ever — into one named refusal with a remediation, raised before anything has been
    # written or dialled.
    #
    # NOT a softer "record it as pending". Nothing about this agent is pending: no future
    # publish on this deployment can succeed, and a status that implies otherwise is the
    # silent success this refusal exists to remove. What the console shows instead comes
    # from the same capability (`agents/publishing._verification_state`), so the button is
    # not offered in the first place.
    require_capability("agent_hosting", engine=engine)

    agent = await _load_agent(session, tenant_id, agent_id, for_update=True)
    # AN ARCHIVED AGENT IS NEVER RESURRECTED BY A REPUBLISH (D-440), and the guard is here
    # rather than only in `agents/lifecycle.py` because this function ends in
    # `status = 'live'` and has seven callers — the lifecycle activate, the admin publish
    # route, `apply_to_live`, `set_call_cap`, `set_disclosure_posture`, a prompt write and
    # the experiment republish. Each of the last five guards itself with its own "is this
    # agent live?" read, which is a rule spelled five times and therefore a rule with five
    # chances to be forgotten by the sixth. Refusing at the one statement that writes the
    # claim makes "an archived agent does not go live" a property of the write instead.
    #
    # The predicate on the UPDATE below is the RACE half of the same rule — an archive
    # committed between this read and that write. Both are needed for the reason the
    # soft-delete guard gives there: the lock makes the window small, the predicate makes
    # it closed. This one exists so the common case gets a sentence a client can act on
    # rather than a bare conflict.
    if agent["status"] == "archived":
        raise ProblemError.conflict(
            "agent_archived",
            "This agent is archived, so it cannot be published.",
            remediation="Restore the agent first, then try again.",
        )
    config = _to_config(tenant_id, agent)

    existing_ref = agent["engine_agent_ref"]
    created = not (isinstance(existing_ref, str) and existing_ref)
    if isinstance(existing_ref, str) and existing_ref:
        await engine.update_agent(existing_ref, config)
        ref = existing_ref
    else:
        ref = await engine.create_agent(config)

    # AFTER the write and BEFORE any column claims it landed. Never raises for a vendor
    # failure — an unreachable read-back is a verdict, not a second way to fail a publish
    # whose write has already happened.
    verdict = await verify_publish(engine, ref, config)
    if verdict.state == "not_applied":
        if created:
            await _reclaim_orphan(engine, agent_id, ref, "read_back_proved_not_applied")
        log.error(
            "agent_publish_not_applied",
            extra={
                "agent_id": str(agent_id),
                "engine": engine.name,
                "prompt_applied": verdict.prompt_applied,
                "disclosure_applied": verdict.disclosure_applied,
                "prompt_disclosure_applied": verdict.prompt_disclosure_applied,
                "truthful_answer_applied": verdict.truthful_answer_applied,
                "voice_applied": verdict.voice_applied,
            },
        )
        raise ProblemError(
            kind="dependency",
            code="engine_publish_not_applied",
            title="The voice platform is not running this change",
            detail=verdict.detail,
            remediation=(
                "Nothing was recorded as live. Try publishing again; if it keeps failing "
                "the agent may have been edited directly on the voice platform."
            ),
        )

    result = await session.execute(
        text(
            "UPDATE agents SET engine_agent_ref = :ref, engine = :engine, status = 'live', "
            "live_tts_voice = :live_voice, live_tts_provider = :live_provider, "
            "live_verify_state = :verify_state, live_verified_at = :verified_at, "
            # THE SOFT-DELETE GUARD, and it is not belt-and-braces. `_load_agent` filters
            # on `deleted_at IS NULL`, but this UPDATE used to name the id alone — so a
            # delete committed between the two would be silently undone here, resurrecting
            # a deleted agent to `status = 'live'` AND writing it a routing row that makes
            # the vendor's next inbound webhook resolve to it. The lock above makes the
            # window small; the predicate makes it closed. Zero rows is a refusal.
            #
            # `status <> 'archived'` is the same guard for the same window on the state a
            # client can reach without an erasure (D-440): archiving takes the agent off
            # the numbers it answers, and a publish landing a moment later would put it
            # back on them as `live`. The early refusal above words it; this closes it.
            "updated_at = now() WHERE id = :aid AND deleted_at IS NULL "
            "AND status <> 'archived'"
        ),
        {
            "ref": ref,
            "engine": engine.name,
            "aid": agent_id,
            # Read off the config we JUST handed the engine, not re-read from the row.
            # This statement is the only moment the two are provably equal, and a
            # re-read here would record whatever a concurrent `set_agent_voice`
            # committed in between — a mirror that claims the engine holds a voice it
            # was never sent. Written inside the same transaction as `engine_agent_ref`
            # and after the vendor call, so a vendor failure rolls the mirror back with
            # it and our row never over-promises (the `kb.publish_source` ordering).
            "live_voice": config.models.tts_voice,
            "live_provider": config.models.tts_provider,
            "verify_state": verdict.stored_state,
            # NULL unless something was actually proven. A timestamp on an `unreachable`
            # would let a screen render "confirmed just now" over an answer nobody read.
            "verified_at": datetime.now(UTC) if verdict.proven else None,
        },
    )
    if rowcount_of(result) == 0:
        if created:
            await _reclaim_orphan(engine, agent_id, ref, "agent_deleted_during_publish")
        raise ProblemError.conflict(
            "agent_deleted_during_publish",
            "This agent was deleted or archived while it was being published.",
            remediation=(
                "Nothing was recorded as live. Restore the agent, or recreate it if it is "
                "still needed."
            ),
        )
    await session.execute(
        text(
            "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
            "active, created_at, updated_at) VALUES (:engine, :ref, :tid, :aid, true, now(), "
            "now()) ON CONFLICT (engine, engine_agent_ref) DO UPDATE SET "
            "tenant_id = EXCLUDED.tenant_id, agent_id = EXCLUDED.agent_id, active = true, "
            "updated_at = now()"
        ),
        {"engine": engine.name, "ref": ref, "tid": tenant_id, "aid": agent_id},
    )
    # THE INBOUND HALF OF PUBLISHING (D-420). Publishing is "make the engine hold what our
    # database says", and until now that covered the agent and stopped short of the one
    # fact that decides whether a client's number rings anything at all. It runs AFTER the
    # routing row so the two engine-side facts about this agent — who it is, and which
    # numbers it answers — are written in one transaction's worth of intent; it cannot fail
    # the publish (see the function) because the agent itself is already verified live.
    await route_inbound_numbers(
        session,
        engine,
        agent_id=agent_id,
        ref=ref,
        answers=agent_answers_inbound(agent["direction"]),
    )
    await republish_running_variants(session, tenant_id=tenant_id, agent_id=agent_id)
    log.info(
        "agent_published",
        extra={
            "agent_id": str(agent_id),
            "engine": engine.name,
            # The verdict, not the prompt. What an operator needs from this line is
            # whether "live" was CONFIRMED, and that is one word (hard rule 6).
            "verify_state": verdict.state,
        },
    )
    return ref


_VARIANT_CONFIG_SQL = (
    "SELECT v.id, v.label, v.disclosure_line, pv.body, v.engine_agent_ref "
    "FROM prompt_experiment_variants v "
    "JOIN prompt_experiments e ON e.id = v.experiment_id "
    "JOIN prompt_versions pv ON pv.id = v.prompt_version_id "
    "WHERE e.agent_id = :aid AND e.status = 'running' ORDER BY v.label"
)


def _variant_config(
    tenant_id: UUID,
    agent: AgentRow,
    variant_id: UUID,
    label: str,
    body: str,
    disclosure: str,
) -> AgentConfig:
    """The agent's own config with the arm's identity, script and disclosure substituted.

    Built from `_to_config` rather than beside it, deliberately: an arm must differ from
    its agent in exactly the three fields below. If a future config field (a new model
    slot, a new cap) is added to `_to_config` and NOT to a hand-rolled variant builder,
    the arms silently run a different configuration from the agent and every measured
    difference is confounded by it — which is the one bug an A/B test cannot survive.

    `agent_id` becomes the VARIANT's id, and that is a statement of fact rather than a
    trick: on the engine, an arm IS its own agent object with its own ref and its own
    routing row, and the identity we hand the vendor has to be one-to-one with the thing
    it names. Neither adapter reads this field to correlate anything back to us —
    `bolna.py` never touches it, `fake.py` derives its deterministic ref from it — so
    passing the agent's id would give the fake ONE ref for both arms and silently publish
    the second script over the first. The bridge back to the real agent is
    `engine_agent_routes`, which is written below and is the only mapping any inbound
    path consults.
    """
    return _to_config(tenant_id, agent).model_copy(
        update={
            "agent_id": str(variant_id),
            "name": f"{agent['name']} [variant {label}]",
            "system_prompt": body,
            # THE ARM'S OWN AI SENTENCE, THROUGH THE AGENT'S OWN TOGGLES (D-163). A
            # variant carries its own `disclosure_line` (NOT NULL, non-empty) because an
            # A/B test of a script legitimately tests its opening; the POSTURE — whether
            # either notice is volunteered at all — is a property of the agent and is not
            # forked per arm. Recomposing here rather than substituting the raw sentence
            # is what makes a toggle flip reach the arms: `republish_running_variants`
            # rebuilds every arm from the agent, so an arm cannot go on greeting callers
            # with a notice its agent has withdrawn.
            "opening_line": compose_opening_line(
                DisclosurePosture(
                    ai_disclosure_line=disclosure,
                    ai_disclosure_enabled=bool(agent["ai_disclosure_enabled"]),
                    recording_notice_line=str(agent["recording_notice_line"]),
                    recording_notice_enabled=bool(agent["recording_notice_enabled"]),
                )
            ),
        }
    )


async def publish_variant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    variant_id: UUID,
    label: str,
    body: str,
    disclosure_line: str,
    existing_ref: str | None,
) -> str:
    """Create or update the engine agent that speaks ONE arm.

    **CALL `publish_variants` UNLESS YOU REALLY MEAN ONE ARM** (D-382). Every production
    caller publishes a SET of arms in one transaction, and this function can only reclaim
    the object IT created — a sibling failing afterwards rolls this arm's `engine_agent_ref`
    and its routing row away and leaves its vendor object behind, named by nothing. The
    plural owns that compensation; reaching past it reintroduces the leak.

    Why an engine agent per arm rather than a per-call prompt override: the portability
    contract carries the script on the AGENT (`AgentConfig.system_prompt`) and
    `start_outbound_call` takes a ref and a `CallContext` of variables — there is no
    prompt slot on a call, in our protocol or in Bolna's. Inventing one would mean
    widening `VoiceEngine` for a feature one adapter can serve, which is the vendor leak
    hard rule 2 exists to stop.

    The routing row is written here for the same reason `publish_agent` writes one: an
    inbound webhook naming the arm's ref must resolve to a tenant and an agent, or the
    reconciliation poller cannot map the call at all.
    """
    agent = await _load_agent(session, tenant_id, agent_id)
    engine = get_engine()
    config = _variant_config(tenant_id, agent, variant_id, label, body, disclosure_line)
    if existing_ref:
        await engine.update_agent(existing_ref, config)
        ref = existing_ref
    else:
        ref = await engine.create_agent(config)
    # An ARM answers real callers with its own script and its own disclosure line, so it
    # gets the same read-back as the agent — verifying the agent and trusting the arms
    # would leave the traffic actually under test as the one path nobody checked.
    verdict = await verify_publish(engine, ref, config)
    if verdict.state == "not_applied":
        if not existing_ref:
            await _reclaim_orphan(engine, agent_id, ref, "variant_read_back_proved_not_applied")
        log.error(
            "agent_variant_publish_not_applied",
            extra={
                "agent_id": str(agent_id),
                "variant_id": str(variant_id),
                "engine": engine.name,
                "prompt_applied": verdict.prompt_applied,
                "disclosure_applied": verdict.disclosure_applied,
                "prompt_disclosure_applied": verdict.prompt_disclosure_applied,
                "truthful_answer_applied": verdict.truthful_answer_applied,
            },
        )
        raise ProblemError(
            kind="dependency",
            code="engine_publish_not_applied",
            title="The voice platform is not running this change",
            detail=verdict.detail,
            remediation=(
                "Nothing was recorded as live for this experiment arm. Try publishing again."
            ),
        )
    await session.execute(
        text(
            "UPDATE prompt_experiment_variants SET engine_agent_ref = :ref, updated_at = now() "
            "WHERE id = :vid"
        ),
        {"ref": ref, "vid": variant_id},
    )
    await session.execute(
        text(
            "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
            "active, created_at, updated_at) VALUES (:engine, :ref, :tid, :aid, true, now(), "
            "now()) ON CONFLICT (engine, engine_agent_ref) DO UPDATE SET "
            "tenant_id = EXCLUDED.tenant_id, agent_id = EXCLUDED.agent_id, active = true, "
            "updated_at = now()"
        ),
        {"engine": engine.name, "ref": ref, "tid": tenant_id, "aid": agent_id},
    )
    log.info(
        "agent_variant_published",
        extra={"agent_id": str(agent_id), "variant_id": str(variant_id), "label": label},
    )
    return ref


@dataclass(frozen=True, slots=True)
class ArmToPublish:
    """One arm of a script test, as `publish_variants` needs it.

    A record rather than five positional arguments because the two call sites assemble it
    from different places — `_VARIANT_CONFIG_SQL` on the republish path,
    `experiments.start`'s own INSERTs on the first publish — and a mis-ordered
    `(label, body, disclosure)` triple would publish an arm whose AI-disclosure sentence
    is its script. mypy cannot see that in three `str` positionals; it can here.
    """

    variant_id: UUID
    label: str
    body: str
    disclosure_line: str
    #: The vendor object this arm already owns, or None to create one. Also decides
    #: whether a sibling's failure has anything of OURS to clean up at the vendor.
    existing_ref: str | None


async def publish_variants(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, arms: Sequence[ArmToPublish]
) -> int:
    """Publish every arm — and RECLAIM the ones THIS CALL created if a later one fails.

    **THE LEAK THIS CLOSES** (D-382). Both callers publish their arms inside ONE transaction, and
    `publish_variant` mints a vendor agent object per arm. When the second arm failed
    (`engine_publish_not_applied`, a vendor 5xx, a timeout), `publish_variant` reclaimed
    ITS OWN half-created object and re-raised — and the FIRST arm's object, already
    created and read back green, was left at the vendor while the transaction rolled its
    `prompt_experiment_variants.engine_agent_ref` and its `engine_agent_routes` row away.
    Nothing of ours then named it: not the variant row, not the routing table, and
    therefore NOT the drift sweep either, which claims routes. It was a billed vendor
    object no instrument in this repository could see, and the operator's next attempt
    created another one beside it.

    So the compensation is the one `_reclaim_orphan` already performs, for the reason it
    already gives: synchronously, before the caller's raise, because the ref lives only
    in this frame and an outbox row carrying it would roll back with everything else.

    ONLY REFS THIS CALL CREATED. An arm that already had one is being UPDATED — the
    object predates this transaction and is answering callers — so deleting it would take
    a live arm off the phone to tidy up after an unrelated failure.

    Returns the number of arms published (0 when nothing is running), which is what the
    caller logs.
    """
    engine = get_engine()
    created: list[str] = []
    try:
        for arm in arms:
            ref = await publish_variant(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                variant_id=arm.variant_id,
                label=arm.label,
                body=arm.body,
                disclosure_line=arm.disclosure_line,
                existing_ref=arm.existing_ref,
            )
            if arm.existing_ref is None:
                created.append(ref)
    except Exception:
        for ref in created:
            await _reclaim_orphan(engine, agent_id, ref, "sibling_variant_publish_failed")
        raise
    return len(arms)


async def republish_running_variants(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> int:
    """Push the agent's CURRENT configuration onto every running arm.

    Called from `publish_agent`, so the fast lane keeps working during an experiment.
    Without it, setting a call cap or a voice while a test runs updates the agent object
    the engine is no longer dialling and leaves both arms on the old config — a
    cost-runaway guard that silently stops guarding is the worst possible shape for that
    bug. Each arm keeps its OWN script and disclosure; everything else follows the agent.

    Returns the number of arms republished (0 when nothing is running), which is what
    the caller logs.
    """
    rows = (await session.execute(text(_VARIANT_CONFIG_SQL), {"aid": agent_id})).all()
    return await publish_variants(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        arms=[
            ArmToPublish(
                variant_id=UUID(str(row[0])),
                label=str(row[1]),
                disclosure_line=str(row[2]),
                body=str(row[3]),
                existing_ref=row[4],
            )
            for row in rows
        ],
    )


#: The header an agent dials from: its own bound, DLT-REGISTERED number (D-420).
#:
#: `dlt_status = 'registered'` IS PART OF THE QUERY, not a check afterwards, and that is
#: what makes this resolution and `campaigns.service._channel_blockers` the same fact
#: rather than two opinions: the gate refuses a campaign whose number is not `registered`,
#: so a number this query would skip is a number no campaign can be dialling on.
#: `pending` and `blocked` headers are invisible here for the same reason.
#:
#: ORDERED so that the AMBIGUOUS case below is deterministic across connections — a
#: refusal that depended on the planner's row order would be a refusal that came and went.
_AGENT_CALLER_ID_SQL = (
    "SELECT e164 FROM phone_numbers "
    "WHERE agent_id = :aid AND dlt_status = 'registered' ORDER BY created_at, id"
)


async def resolve_caller_id(session: AsyncSession, *, agent_id: UUID) -> str | None:
    """The number this agent's calls must present to the callee, or None (D-420).

    **THE MISSING HOP THAT MADE A COMPLIANCE CONTROL DECORATIVE.**
    `campaigns.service._channel_blockers` refuses a launch — and every dispatch tick —
    unless the campaign's number carries the right 140/160 series for its classification
    and `dlt_status = 'registered'`. The dial then carried no caller ID at all, so the
    engine answered from its own pool and the callee, the TSP and the complaint trail saw
    the vendor's number while our gate reported the client's registered header approved.
    Every half of that was correct in isolation; nothing stated that the GATED number and
    the DIALLED number are the same number, because there was no seam at which to state it.
    This function and `_channel_blockers`' `number_not_bound_to_agent` rule are that seam,
    and they are two halves of one claim: the gate proves the campaign's approved number is
    the one bound to the campaign's agent, and this resolves the header FROM that binding.

    **NONE IS A LEGITIMATE ANSWER AND MUST STAY ONE.** An agent with no registered header
    dials on the engine's own number, which is what happens today for every call and is
    fine for the paths where it is fine: a D-21 "call this lead" click, a CRM callback, an
    account whose DLT paperwork is still in flight. Refusing those would be a self-inflicted
    outage on a rule that governs CAMPAIGNS. What must never happen is a campaign dial
    resolving to None, and that is closed on the campaign side — a campaign cannot launch
    or tick without a registered number bound to its own agent — rather than by a guess here
    about which caller this is.

    **MORE THAN ONE REGISTERED HEADER IS A REFUSAL, NOT A CHOICE**, and this is the one
    place the honest answer is unwelcome. An agent may legitimately end up bound to a
    140-series and a 160-series number (promotional and transactional traffic), and nothing
    in this function's inputs says which campaign is dialling — so any pick is a coin toss
    between a promotional header and a transactional one, i.e. a DLT misclassification with
    the client's Principal Entity on the complaint. Refusing costs an operator one
    configuration change (an agent per classification, which is what the 140/160 split means
    anyway); picking costs the client their registration. The refusal is in
    `DIAL_NOT_PLACED_CODES`, so nothing was seized and the contact keeps its place on the
    ladder.

    Ids and counts in the log line, never a number (hard rule 6).
    """
    rows = (await session.execute(text(_AGENT_CALLER_ID_SQL), {"aid": agent_id})).all()
    if not rows:
        return None
    if len(rows) > 1:
        log.error(
            "agent_caller_id_ambiguous",
            extra={"agent_id": str(agent_id), "registered_numbers": len(rows)},
        )
        raise ProblemError.business_rule(
            "agent_caller_id_ambiguous",
            "This agent has more than one registered calling number, so we cannot tell "
            "which one its calls should come from.",
            remediation=(
                "Give this agent a single registered number — a campaign's number class "
                "(140 for promotional, 160 for transactional and service) decides which — "
                "and use a separate agent for the other class."
            ),
        )
    return str(rows[0][0])


async def dispatch_call(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    lead_id: UUID | None,
    phone_e164: str,
    lead_name: str | None = None,
    context_note: str | None = None,
    on_reserved: Callable[[AsyncSession, UUID], Awaitable[None]] | None = None,
) -> str:
    """Place ONE outbound call. The caller has already passed the compliance gate.

    THE INTENT ROW IS WRITTEN AND COMMITTED BEFORE THE ENGINE IS ASKED TO DIAL, and this
    used to be a promise the shape of the function could not keep: the INSERT bound
    `engine_call_id` to the vendor's return value, so it could not possibly precede the
    call that produced it. A response lost on the way back — a read timeout at 10s, a
    reset connection, a proxy 502 after the vendor committed — left a ringing phone, a
    vendor charge and no row of ours: no metering, no wallet debit, and (on the campaign
    path) a contact the dispatcher returned to `pending` and rang a SECOND time, because
    `resolve_campaign_contact` joins a call to its contact through
    `campaign_contacts.last_call_id`, which was never set.

    So the row exists first, keyed on an id WE mint (`unconfirmed_engine_call_id`), and
    the vendor's handle is stamped onto it afterwards. What that buys, in the order the
    failures actually happen:

    * **A lost response** leaves a `queued` row whose `engine_call_id` is still ours.
      That is the durable record of a charge we may have incurred, and it is what
      `DialUnconfirmedError` points the caller at.
    * **Two dispatchers racing one contact** cannot collide on the intent row (each mints
      its own `calls.id`), and the double-dial they would otherwise cause is stopped
      where it has always been stopped — the committed `pending → dialing` CAS claim.
    * **The poller arriving later** finds the row by `engine_call_id` once the stamp
      lands, exactly as before; `_upsert_call`'s `ON CONFLICT (engine_call_id)` is what
      makes that one row rather than two.

    **Its own transaction, not the caller's.** A row written into the caller's
    transaction dies with it, which is the failure being closed here (`core/deps.py`
    rolls a request back on any exception; the campaign dispatcher runs each dial in its
    own transaction). This is `billing/payment_routes._create_order_once`'s shape — claim
    committed before the network call — applied to a dial. The second connection is held
    only for the INSERT and is released before the engine round trip, so a dial occupies
    at most two pooled connections and never one across a vendor call.

    **`lead_id` is stamped through the CALLER's session afterwards, deliberately.** The
    lead may not be committed yet: `ingest/service.py` inserts the lead and dials in one
    transaction, so an FK to it from another connection would block on that transaction —
    which is waiting on this function. A call row whose lead link is a moment late is a
    small, recoverable imprecision; a self-deadlock on the lead-callback path is not.

    **`on_reserved` runs in the intent transaction**, with the row already inserted, for
    callers that must record their own pointer to the call BEFORE it can ring — the
    campaign dispatcher's `campaign_contacts.last_call_id`, whose FK requires the row and
    whose whole value is that it is written on the safe side of the dial.

    A/B SCRIPT TESTING (ROADMAP M3) IS WIRED HERE, and here is the only place it could
    be. This function is the platform's single outbound entry point — the property
    `scripts/check_compliance_invariants` asserts in its first section — so an
    assignment made here covers the campaign dispatcher, the D-21 "call this lead"
    button and the callback path without any of them knowing an experiment exists.
    Nothing about the gate changes: the caller has already been refused or allowed
    before this line, and choosing WHICH published script to speak cannot un-refuse it.

    The arm decides which engine agent is dialled, and the assignment is written in the
    SAME transaction as the call row it describes.

    Raises `DialUnconfirmedError` when the engine call failed in a way that cannot rule out a
    ringing phone; the original `ProblemError` when the vendor refused before dialling
    (`DIAL_NOT_PLACED_CODES`), so those callers keep their retry ladder.
    """
    agent = await _load_agent(session, tenant_id, agent_id)
    ref = agent["engine_agent_ref"]
    if not isinstance(ref, str) or not ref:
        raise ProblemError.business_rule(
            "agent_not_published",
            "This agent has not been published to the voice platform yet.",
            remediation="Publish the agent from the admin console first.",
        )

    # THE HEADER THIS CALL PRESENTS, resolved before anything is written or dialled
    # (D-420). On the caller's session, so it is read under this tenant's RLS and can only
    # ever see this tenant's numbers; and BEFORE the intent row, so the ambiguity refusal
    # costs one indexed read and leaves no `queued` call behind for a dial that was never
    # going to be placed.
    from_e164 = await resolve_caller_id(session, agent_id=agent_id)

    # The stable unit: the lead when there is one, the destination otherwise. See
    # `agents/assignment.py` for why it is not the call id.
    arm = await assignment.assign(
        session, agent_id=agent_id, unit_key=str(lead_id) if lead_id else phone_e164
    )
    # An arm that has never been published has no engine agent to dial. Falling back to
    # the agent's own ref rather than failing: the client's call is the thing that
    # matters, and a call that ran the control is a call, whereas a refused dial is an
    # outage caused by an experiment. It is not recorded as assigned — see below.
    dial_ref = arm.arm.engine_agent_ref if arm and arm.arm.engine_agent_ref else ref

    call_id = uuid7()
    intent_engine_call_id = unconfirmed_engine_call_id(call_id)
    async with tenant_session(tenant_id) as intent:
        await intent.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
                "'outbound', :to_e, 'queued', now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": intent_engine_call_id,
                "to_e": phone_e164,
            },
        )
        # The arm rides the row it describes, in the row's own transaction. There is no
        # `ON CONFLICT` to lose any more: the id is ours and fresh, so this INSERT cannot
        # race the poller. The invariant that mattered — an assignment never MOVES — is
        # `assignment.record`'s own `ON CONFLICT (call_id) DO NOTHING`.
        if arm is not None and arm.arm.engine_agent_ref:
            await assignment.record(intent, tenant_id=tenant_id, call_id=call_id, assignment=arm)
        if on_reserved is not None:
            await on_reserved(intent, call_id)

    engine = get_engine()
    try:
        handle = await engine.start_outbound_call(
            dial_ref,
            phone_e164,
            CallContext(
                lead_id=str(lead_id) if lead_id else None,
                lead_name=lead_name,
                context_note=context_note,
                system_prompt=_call_prompt_for(engine, tenant_id, agent),
                from_e164=from_e164,
            ),
        )
    except Exception as exc:
        # `Exception`, NOT `BaseException`. A `CancelledError` through this await is a
        # worker being shut down or a job overrunning `job_timeout`; arq retries the job
        # for it, so it must keep propagating as itself. The intent row and whatever
        # `on_reserved` wrote are already committed, which is precisely what makes that
        # cancellation survivable — the contact stays `dialing` pointing at an
        # unconfirmed call, and `_reap_stuck_dialing` settles it without a second ring.
        code = exc.code if isinstance(exc, ProblemError) else type(exc).__name__
        if dial_was_not_placed(exc):
            await _close_unplaced_dial(
                tenant_id,
                call_id=call_id,
                code=code,
                vendor_status=exc.vendor_status if isinstance(exc, EngineRejectedError) else None,
            )
            raise
        # No number, no vendor text: ids and our own code (hard rule 6).
        log.error(
            "dial_outcome_unknown",
            extra={"call_id": str(call_id), "agent_id": str(agent_id), "code": code},
        )
        raise DialUnconfirmedError(call_id=call_id, code=code) from exc

    await _confirm_dial(tenant_id, call_id=call_id, handle=handle)
    if lead_id is not None:
        # Through the CALLER's session — see the docstring: the lead can be uncommitted
        # in that very transaction, and the FK would otherwise wait on it.
        await session.execute(
            text("UPDATE calls SET lead_id = :lid, updated_at = now() WHERE id = :id"),
            {"lid": lead_id, "id": call_id},
        )
    return handle


async def _confirm_dial(tenant_id: UUID, *, call_id: UUID, handle: str) -> None:
    """Stamp the vendor's handle onto the intent row, in its own transaction.

    Guarded by `NOT EXISTS` rather than left to the unique index: the poller can already
    have created a row for this execution (it does that for calls it discovers), and a
    duplicate-key error here would abort a transaction whose only job is bookkeeping for
    a call that is by now really ringing. When the guard bites, OUR row keeps its local
    id — visible, `queued`, and settled by the same reaper as any other unconfirmed dial
    — and the vendor's row is the one the pipeline uses. `IntegrityError` is still
    caught, because the guard and the insert can interleave.
    """
    try:
        async with tenant_session(tenant_id) as confirm:
            result = await confirm.execute(
                text(
                    "UPDATE calls SET engine_call_id = :h, updated_at = now() "
                    "WHERE id = :id AND engine_call_id = :local "
                    "AND NOT EXISTS (SELECT 1 FROM calls o WHERE o.engine_call_id = :h)"
                ),
                {"h": handle, "id": call_id, "local": unconfirmed_engine_call_id(call_id)},
            )
            stamped = rowcount_of(result)
    except IntegrityError:
        stamped = 0
    if stamped == 0:
        log.warning("dial_handle_not_stamped", extra={"call_id": str(call_id)})


async def _close_unplaced_dial(
    tenant_id: UUID, *, call_id: UUID, code: str, vendor_status: int | None = None
) -> None:
    """The vendor refused before seizing a line: finish the intent row as `failed`.

    Left `queued`, it would sit in the `in_flight` bucket forever and read as a call that
    might yet connect. `failed` is the honest terminal state, and it is only ever written
    where `dial_was_not_placed` holds — the failures that PROVE nothing rang.

    `vendor_status` rides the log line because `engine_rejected` alone no longer says
    which side of that judgement a refusal fell on, and "why was this dial abandoned" is
    a question an operator asks about one call id.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET status = 'failed', updated_at = now() "
                "WHERE id = :id AND status = 'queued'"
            ),
            {"id": call_id},
        )
    log.info(
        "dial_not_placed",
        extra={"call_id": str(call_id), "code": code, "vendor_status": vendor_status},
    )


async def provision_number(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    e164: str,
    series: str,
    agent_id: UUID | None,
    provider: str | None,
    purpose: str | None,
) -> UUID:
    """Record a number the tenant may dial from (DATA-MODEL §6, admin-only).

    `series` is the load-bearing field: it is what the campaign launch gate matches
    against the campaign's classification, so getting it wrong here is a DLT violation
    later. `dlt_status` starts `pending` and is a separate deliberate step — a number
    is not registered because we typed it in.

    The number is globally unique (`phone_numbers.e164`), and the collision is caught
    from the UNIQUE INDEX rather than by probing first — deliberately. A probe runs
    under this tenant's RLS, which hides another tenant's rows, so it would report
    "available" for exactly the number that is not, and the insert would then surface
    as a 500. The index sees all tenants because it is the database's, not the
    session's. This is the one place where letting the constraint be the authority is
    the *only* correct answer short of widening RLS for a uniqueness question.

    `agent_id` IS THE FIFTH D-193 WRITE PATH (D-331). It is a foreign key into `agents`,
    it arrives in the request body, and PostgreSQL validates a foreign key with row
    security bypassed — so `POST /v1/admin/tenants/<A>/numbers` naming tenant B's agent
    answered 201 and left tenant A holding a calling number that points at a neighbour's
    agent. `assert_visible` resolves it under THIS session's RLS first, which is why it
    must run before the INSERT rather than beside it: the check is the database's answer
    to "can this tenant see that row", not a comparison between two values the caller
    supplied. `None` stays legitimate — a number provisioned before its agent exists is
    the ordinary onboarding order.
    """
    await assert_visible(session, "agent", agent_id)
    number_id = uuid7()
    try:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, provider, "
                "dlt_status, purpose, created_at, updated_at) VALUES (:id, :tid, :aid, :e, :s, "
                ":prov, 'pending', :purpose, now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "aid": agent_id,
                "e": e164,
                "s": series,
                "prov": provider,
                "purpose": purpose,
            },
        )
    except IntegrityError as exc:
        raise ProblemError.conflict(
            "number_taken",
            "This number is already provisioned.",
            remediation="It may belong to another account — check before reassigning it.",
        ) from exc
    # AND TELL THE ENGINE, if there is anything to tell it (D-420). A number assigned to an
    # agent that is already published must start being answered NOW — waiting for the next
    # publish would mean an assignment that works only if somebody happens to edit the
    # agent afterwards, which is the "screen with nothing behind it" this closes.
    #
    # The unpublished case is a no-op rather than a refusal, and deliberately: provisioning
    # a number BEFORE the agent exists is the ordinary onboarding order (it is why
    # `agent_id` is nullable), and `publish_agent` routes every bound number when it runs.
    #
    # NOR IF THE AGENT IS NOT ON THE FRONTLINE (D-440). `engine_agent_ref` survives a
    # deactivation and an archival — those keep the vendor object and only release the
    # numbers — so "has a ref" stopped being the same question as "should answer this
    # number" the moment an agent could be switched off. Binding here on the ref alone
    # would let assigning a number silently put a paused or retired agent back on a
    # client's line, which is the exact state `deactivate_agent` reaches the engine to
    # prevent. `activate` republishes and routes every bound number, so a number attached
    # while the agent is off starts being answered the moment it comes back.
    if agent_id is not None:
        published = (
            await session.execute(
                text(
                    "SELECT engine_agent_ref, direction, status FROM agents "
                    "WHERE id = :aid AND deleted_at IS NULL"
                ),
                {"aid": agent_id},
            )
        ).first()
        if published is not None and published[0] and str(published[2]) == "live":
            direction = published[1]
            await route_inbound_numbers(
                session,
                get_engine(),
                agent_id=agent_id,
                ref=str(published[0]),
                answers=_is_agent_direction(direction) and agent_answers_inbound(direction),
            )
    return number_id


async def set_number_dlt_status(session: AsyncSession, *, number_id: UUID, dlt_status: str) -> None:
    result = await session.execute(
        text("UPDATE phone_numbers SET dlt_status = :st, updated_at = now() WHERE id = :id"),
        {"st": dlt_status, "id": number_id},
    )
    if rowcount_of(result) == 0:
        raise ProblemError.not_found("Number")


__all__ = [
    "DIAL_NOT_PLACED_CODES",
    "UNCONFIRMED_ENGINE_CALL_PREFIX",
    "ArmToPublish",
    "DialUnconfirmedError",
    "InboundRouting",
    "dial_was_not_placed",
    "dispatch_call",
    "effective_call_cap",
    "provision_number",
    "publish_agent",
    "publish_variant",
    "publish_variants",
    "republish_running_variants",
    "resolve_caller_id",
    "route_inbound_numbers",
    "set_number_dlt_status",
    "unconfirmed_engine_call_id",
]
