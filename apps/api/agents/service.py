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
pushing whatever unapproved script sat in `system_prompt_id`.

The COALESCE is safe rather than lenient, and the invariant that makes it safe lives
in `prompts.insert_prompt_version`: the one statement that can create a divergence
between the two pointers also materializes `live_prompt_id` in the same UPDATE. So
`live_prompt_id IS NULL` only ever means "the two pointers agree", never "the draft is
ahead" — which is also true of every row that predates the pointer (migration
a4e7b2c95d18 backfilled them).

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
allowed to differ because a voice written to the row reaches the engine only at the next
publish — so "does a republish change what callers hear?" is
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
`_to_config` fills `AgentConfig.max_call_duration_s` from the agent row. The field and its
vendor mapping already existed in the engine adapter — and nothing filled it, so every
agent on the platform published the Pydantic default and no client could change it.
Publish time is where the guard is enforced because the engine is the only party that can
hang up a call: we are not in the audio path (hard rule 3), and an inbound runaway is never
dispatched by us at all, so a dispatch-side check would leave the receptionist motion
unguarded.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import (
    Any,
    Final,
    Literal,
    NotRequired,
    Protocol,
    TypedDict,
    TypeGuard,
    cast,
    runtime_checkable,
)
from uuid import UUID

from calevate_shared.call_script import (
    CallScript,
    Capabilities,
    NativeStep,
    call_backs_withheld,
    native_steps,
    substitute_variables,
    without_outline,
)
from calevate_shared.calling_window import IST
from calevate_shared.carrier import ENGINE_NUMBER_PROVIDER
from calevate_shared.engine import (
    AgentConfig,
    CallContext,
    DisclosurePosture,
    EngineAgentRef,
    HandoffSpec,
    ModelConfig,
    NumberSeries,
    ProvisionedNumber,
    TurnDetection,
    VoiceEngine,
    compose_engine_prompt,
    compose_opening_line,
    introduces_itself,
    join_first_words,
    notice_fields,
    spoken_ai_notice,
    truthful_answer_directive,
)
from calevate_shared.engine_scope import scope_of
from calevate_shared.spoken_style import thinking_lines, trial_call_opening
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import assignment, call_outcomes, field_suggestions, hot_facts
from apps.api.agents import handoff as handoff_module
from apps.api.agents.call_handling import (
    AGENT_SETTING_COLUMNS,
    ORG_SETTING_COLUMNS,
    SETTING_FIELDS,
    CallSettings,
    opening_wait_available,
    resolve_settings,
    settings_from_row,
    turn_detection_of,
)
from apps.api.agents.engine_choice import (
    byok_in_force,
    engine_rate_key_for,
    in_call_default_model,
)
from apps.api.agents.engine_facts import sync_business_facts
from apps.api.agents.engine_limits import refuse_over_engine_limits, refuse_unpriced_engine
from apps.api.agents.hosted_voices import parse_hosted_voice_id
from apps.api.agents.languages import published_extra_languages, refuse_unoffered_language
from apps.api.agents.models import (
    AGENT_DIRECTIONS,
    CALL_CAP_DEFAULT_S,
    CALL_CAP_MAX_S,
    CALL_CAP_MIN_S,
    FILLER_LINES_MAX,
    AgentDirection,
    number_on_hold_sql,
    series_for_e164,
)
from apps.api.agents.own_model import (
    ensure_own_model_in,
    own_model_for,
    own_model_of_choice,
    own_model_on,
    own_model_rate_key,
    refuse_unofferable_own_model,
    require_developer_own_model,
)
from apps.api.agents.reconciliation import TRUTHFUL_ANSWER_MISSING
from apps.api.agents.reply_length import resolve_max_reply_tokens
from apps.api.agents.t0_block import block_of, with_knowledge_of, without_block
from apps.api.agents.verification import verify_publish
from apps.api.agents.voice_stamp import stamp_of
from apps.api.agents.voice_tuning import TUNING_COLUMNS, config_speaking_speed, config_tuning
from apps.api.agents.voices import get_voice, speech_for_voice_id, voice_id_of
from apps.api.agents.write_guard import archived_refusal, assert_agent_writable
from apps.api.billing.engine_minutes import (
    ATTESTED_MINUTE_ENGINES,
    BYOK_VOICE_RATE_KEY,
    EngineRateKey,
    attested_rate_keys,
    record_engine_rate_key,
)
from apps.api.compliance.caller_memory import MEMORY_ON_SQL, recall
from apps.api.compliance.platform_dnc import PLATFORM_DNC_BLOCK_CODE, platform_dnc_refusal
from apps.api.compliance.trial_access import (
    TRIAL_MIN_CALL_SECONDS,
    refuse_on_trial,
    refuse_trial_numbers,
    refuse_trial_studio_over_cap,
    restricting_trial,
    trial_line_horizon,
)
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.ownership import assert_visible
from apps.api.db.result import rowcount_of
from apps.api.db.session import session_tenant, tenant_session
from apps.api.engine import get_engine, require_capability
from apps.api.engine.capabilities import ENGINE_COMPLIANCE_FLOOR_ABSENT
from apps.api.engine.catalogue import HostsVoices
from apps.api.engine.dial_lines import (
    CARRIER_LINES_LOCK_KEY,
    ENGINE_LINE_HORIZON,
    LINES_BUSY_RULE,
    dial_backoff_remaining_s,
    engine_backoff_refusal,
    engine_concurrency_cap,
    lines_busy,
    outbound_line_pool,
    start_dial_backoff,
)
from apps.api.engine.hosted_platform import hosted_agent_limits
from apps.api.engine.thinnest_workspace import (
    trial_agent_in_developer_workspace,
    workspace_not_provisioned,
)
from apps.api.engine.vendor_http import (
    NUMBER_DAILY_LIMIT_CODE,
    RECIPIENT_OPTED_OUT_CODE,
    EngineRateLimitedError,
    EngineRejectedError,
)
from apps.api.forwarding.service import has_forwarded_line
from apps.api.ingest.lead_policy import machine_detection_on
from apps.api.legal.service import assert_agreements_accepted
from apps.api.ops.maintenance import read_open_window
from apps.api.reliability.engine_actions import (
    ACTION_ENGINES,
    ensure_agent_actions,
    retire_agent_actions,
)
from apps.api.reliability.engine_lookups import ensure_call_start_quietly
from apps.api.reliability.engine_webhooks import ensure_agent_webhook
from apps.api.tenancy.business_profile import assert_ready_to_go_live
from apps.api.tenancy.engine_workspace import engine_has_workspaces, resolve_workspace
from apps.api.tenancy.lifecycle import assert_account_open

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
#: vendor token, or on historical rows the former owned runtime's
#: `pipecat:<tenant>:<call>`; neither carries
#: this prefix, so nothing outside this module writes this shape.
UNCONFIRMED_ENGINE_CALL_PREFIX = "local:"

#: The refusal when a campaign's chosen number stopped being one its agent can call from
#: between the tick's `dispatch_blockers` and the dial (`resolve_caller_id`).
CAMPAIGN_NUMBER_UNAVAILABLE_CODE: Final = "campaign_number_unavailable"

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
#: What would let us do better STILL is a vendor-side idempotency key on the dial request:
#: with one, a retry is safe whatever the failure was, including the 5xx half. No adapter
#: sends one, which is why the 5xx half stays "the phone may be ringing".
DIAL_NOT_PLACED_CODES = frozenset(
    {
        # 429 with the ladder exhausted. The adapter's own note says a throttle "says
        # nothing about the request", and it is raised instead of sending it on.
        "engine_rate_limited",
        # All of these are raised BEFORE any HTTP request leaves this process.
        "engine_not_configured",
        "engine_capability_absent",
        # The campaign's chosen number is no longer one its agent can call from
        # (`resolve_caller_id`). Raised before the intent row, so no line was seized.
        CAMPAIGN_NUMBER_UNAVAILABLE_CODE,
        # The dial arrived without the truthful-answer rule on it, or reached an engine
        # that has nowhere to put one (D-282). Refused inside the adapter before the
        # request is built, so no line was seized and the contact keeps its place — the
        # same standing as a missing caller id, and for the same reason.
        ENGINE_COMPLIANCE_FLOOR_ABSENT,
        # The engine account's call ceiling (`engine/dial_lines.py`): every outbound line is
        # in use, raised by `dispatch_call` before the intent row is written.
        LINES_BUSY_RULE,
        # The calling number used its daily allowance at the voice platform (a 429 the
        # vendor documents as nothing placed, `engine/vendor_http.number_daily_limit_error`).
        NUMBER_DAILY_LIMIT_CODE,
        # The voice platform refused to call this person (opted out with it, or on its own
        # do-not-call list): refused before dialling, and person-level
        # (`compliance.service.PERSON_LEVEL_REFUSALS`), so the contact is settled.
        RECIPIENT_OPTED_OUT_CODE,
        # The same refusal when only the voice platform's shared list blocks the person
        # (D-691, `compliance/platform_dnc.py`).
        PLATFORM_DNC_BLOCK_CODE,
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


def call_cap_max_s(engine: VoiceEngine | None = None) -> int:
    """The longest cap an agent may be given on the engine that will run it: our own
    ceiling, lowered to the engine's where it has one (ThinnestAI runs at most 20 minutes,
    so a longer cap could be saved and then refused at publish)."""
    limit = hosted_agent_limits(engine or get_engine()).call_seconds_max
    return CALL_CAP_MAX_S if limit is None else min(CALL_CAP_MAX_S, limit)


def refuse_call_cap_out_of_range(max_call_duration_s: int | None) -> None:
    """The cap's range check for every writer: the CHECK on the column is the floor, this
    is the sentence (and the engine's lower ceiling, which no CHECK can know)."""
    ceiling = call_cap_max_s()
    if max_call_duration_s is None or CALL_CAP_MIN_S <= max_call_duration_s <= ceiling:
        return
    raise ProblemError(
        kind="business_rule",
        code="call_cap_out_of_range",
        title="Call length cap out of range",
        detail=(
            f"A maximum call length must be between {CALL_CAP_MIN_S // 60} and "
            f"{ceiling // 60} minutes."
        ),
        remediation=(
            "Choose a length in that range, or leave it empty to use the standard "
            f"{CALL_CAP_DEFAULT_S // 60} minutes. Empty means the standard length, never "
            "unlimited."
        ),
        fields=[
            {
                "field": "max_call_duration_s",
                "rule": "out_of_range",
                "message": (
                    f"Must be {CALL_CAP_MIN_S}-{ceiling} seconds, or null for the platform default."
                ),
            }
        ],
    )


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
    #: The OTHER languages the agent may answer in, as the intake stored them (NULL is
    #: none). `languages.published_extra_languages` narrows them at publish.
    languages_extra: list[str] | None
    #: The legacy bundled sentence (D-163). Still read for the drift comparison; never
    #: composed into a new `opening_line`.
    disclosure_line: str | None
    stt_provider: str | None
    stt_model: str | None
    #: What was configured ON THIS AGENT, or NULL to inherit the account's default.
    llm_model: str | None
    #: The ACCOUNT's default, read from `organizations` in the same statement so the
    #: middle rung of the fallback cannot be resolved against a different transaction's
    #: view of the row. NULL means the account never chose.
    organization_llm_model: str | None
    tts_provider: str | None
    tts_voice: str | None
    #: A voice and a model from the engine's OWN catalogue (D-678), NULL for its default.
    #: Reach `AgentConfig` only on an engine that dictates the leg (`_engine_choice`).
    engine_voice_id: str | None
    engine_model_id: str | None
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
    #: Sentence three and its switch (D-507). No third `*_enabled` field for the sentence
    #: itself: it is spoken exactly when `caller_memory_enabled` is true.
    caller_memory_notice_line: str
    caller_memory_enabled: bool
    #: DOES THIS AGENT HAND CALLERS TO A PERSON, and when should it (D-533)? Read on this
    #: one path, beside the roster the publish resolves, so a publish and the drift read
    #: cannot disagree about the posture — the same argument the four disclosure columns
    #: above make.
    handoff_enabled: bool
    #: The client's own trigger wording, or NULL for `handoff.HANDOFF_TRIGGER_DEFAULT`.
    handoff_trigger: str | None
    #: WHEN THIS BUSINESS IS OPEN, in the shape `agents/business_hours.py` reads. Carried
    #: here because "who is on duty" is answered from it and from the roster together, and
    #: fetching it separately would let an hours edit land between the two reads — a
    #: publish whose destination and whose hours came from different moments.
    business_hours: dict[str, Any] | None
    #: False while the account is a restricted free trial (`compliance/trial_access`).
    callbacks_offered: NotRequired[bool]
    detect_machines: NotRequired[bool]
    #: The client forwards a published number to its Calevate number (D-746).
    forwarded_line: NotRequired[bool]
    #: The applied version's authored `CallScript`, or NULL for a freeform one.
    structured_script: NotRequired[dict[str, Any] | None]
    #: The agent's call handling values and the account's (D-751); NULL inherits.
    turn_silence_ms: NotRequired[int | None]
    end_call_on_finish: NotRequired[bool | None]
    organization_turn_silence_ms: NotRequired[int | None]
    organization_end_call_on_finish: NotRequired[bool | None]
    #: Every call setting, the agent's own and the account's (D-751, F3, F9); None inherits.
    call_settings: NotRequired[CallSettings]
    organization_call_settings: NotRequired[CallSettings]
    #: An engine number is attached to this agent (F1).
    has_phone_number: NotRequired[bool]
    #: The Studio voice tuning columns, in `voice_tuning.TUNING_COLUMNS` order.
    voice_tuning: NotRequired[tuple[object, ...]]
    #: The reply ceiling an operator set (D-769); NULL inherits the console's.
    max_reply_tokens: NotRequired[int | None]
    #: The business the agent speaks for (`organizations.name`), for the role sentence.
    business_name: NotRequired[str | None]
    #: The opening waits for the person who picked up to speak (D-871).
    opening_waits_for_caller: NotRequired[bool]
    # The facts the agent knows by heart, in rank order (D-896, `agents/hot_facts`).
    hot_facts: NotRequired[tuple[str, ...]]
    #: An operator's turn detection for this agent alone (D-901); None follows the console.
    turn_detection: NotRequired[TurnDetection | None]


#: Where `_load_agent`'s call settings start, the account's follow, and the columns after them.
_OWN: Final = 29
_ORG: Final = _OWN + len(SETTING_FIELDS)
_AFTER: Final = _ORG + len(SETTING_FIELDS)


def _is_agent_direction(value: object) -> TypeGuard[AgentDirection]:
    """Is this database value one of the three directions an agent can have?

    A `TypeGuard` rather than a `cast` because the two are opposites in the only way that
    matters: a cast asserts and moves on, while this ASKS — the runtime check is real, and
    the checker's narrowing is a consequence of the check rather than a substitute for it.
    One place, so the vocabulary cannot be re-spelled at a second call site.
    """
    return value in AGENT_DIRECTIONS


def holds_a_number(
    *, status: str, direction: str, engine_agent_ref: object, number_refs: list[object]
) -> bool:
    """Does the voice platform hold one of these numbers for this agent, as its answering
    line or lent to it for calling out?

    Exactly when our number sync makes it so (`campaigns/engine_numbers.wanted_attachment`):
    a live agent with a number in its own workspace. Both count, because the platform takes
    `phone` on an agent with "a number to answer or call from" and refuses it otherwise
    (F1), and places calls only from an agent that has it (`calling_not_set_up`; docs.
    thinnest.ai agents/update-agent `voice.surfaces` and calls/place-call, read 15 Oct 2026).
    The shared trial number is lent per call without a row here, so it gets `phone` at the
    dial instead (`engine_numbers.lend_platform_line`)."""
    from apps.api.campaigns.engine_numbers import wanted_attachment

    if not isinstance(engine_agent_ref, str) or not engine_agent_ref:
        return False
    agent, calling = wanted_attachment(
        released=False,
        direction=direction,
        status=status,
        engine_agent_ref=engine_agent_ref,
        archived=False,
    )
    held = agent or calling
    return held is not None and any(
        scope_of(str(ref)) == scope_of(held) for ref in number_refs if ref
    )


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
                # Whether it remembers callers NOW: its switch AND the current statement
                # accepted (D-900, `MEMORY_ON_SQL`), so publish, drift and recall agree.
                f"a.caller_memory_notice_line, {MEMORY_ON_SQL}, "
                # The hours are the BUSINESS's, from its one profile (D-695): every agent of a
                # client is judged against them.
                "a.handoff_enabled, a.handoff_trigger, bp.hours, "
                # The ACCOUNT's model default, joined rather than fetched separately: the
                # fallback is decided from these two columns together, and two statements
                # would let a concurrent change to the account default land between them —
                # a published config whose two halves came from different moments.
                # The reply languages after the main one are the AGENT's own (D-815).
                "o.default_llm_model, a.languages_extra, a.engine_voice_id, a.engine_model_id, "
                # The authored form of the applied version, for an engine that takes the
                # script's stages as its own step list (`_steps_for`).
                "pv.structured_script, "
                # The call handling settings and the account defaults they inherit (D-751,
                # F3, F9), in this statement for `default_llm_model`'s reason.
                f"{AGENT_SETTING_COLUMNS}, {ORG_SETTING_COLUMNS}, "
                # The engine numbers bound to the agent, for `holds_a_number` (F1).
                "ARRAY(SELECT n.engine_number_ref FROM phone_numbers n WHERE n.agent_id = a.id "
                "AND n.released_at IS NULL AND n.engine_number_ref IS NOT NULL "
                f"AND n.provider = :number_provider AND NOT {number_on_hold_sql('n')}), "
                # How a Studio voice sounds on this agent (`agents/voice_tuning`).
                f"{TUNING_COLUMNS}, "
                # The reply ceiling an operator set (`agents/reply_length`).
                "a.max_reply_tokens, "
                # The business the prompt's role sentence names (`role_sentence`).
                "o.name, "
                # Whether the opening waits for the person's first words (D-871).
                "a.opening_waits_for_caller, "
                # An operator's turn detection for this agent alone (D-901).
                "a.turn_detection "
                "FROM agents a LEFT JOIN prompt_versions pv "
                # The APPLIED pointer, not the draft one — see the module docstring.
                "ON pv.id = COALESCE(a.live_prompt_id, a.system_prompt_id) "
                # LEFT, not INNER, so an agent whose organization row is somehow invisible
                # still publishes on the platform default rather than vanishing: this
                # statement's job is to find the agent, and RLS has already decided which
                # organization row is legible (the policy matches on `id`).
                "LEFT JOIN organizations o ON o.id = a.tenant_id "
                "LEFT JOIN business_profiles bp ON bp.tenant_id = a.tenant_id "
                "WHERE a.id = :aid AND a.deleted_at IS NULL"
                + (" FOR UPDATE OF a" if for_update else "")
            ),
            {"aid": agent_id, "number_provider": ENGINE_NUMBER_PROVIDER.get(get_settings().engine)},
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
        "caller_memory_notice_line": row[19],
        "caller_memory_enabled": row[20],
        "handoff_enabled": row[21],
        "handoff_trigger": row[22],
        "business_hours": row[23],
        "organization_llm_model": row[24],
        "languages_extra": row[25],
        "engine_voice_id": row[26],
        "engine_model_id": row[27],
        "structured_script": row[28],
        "turn_silence_ms": row[_OWN],
        "end_call_on_finish": row[_OWN + 1],
        "organization_turn_silence_ms": row[_ORG],
        "organization_end_call_on_finish": row[_ORG + 1],
        "call_settings": settings_from_row(tuple(row[_OWN:_ORG])),
        "organization_call_settings": settings_from_row(tuple(row[_ORG:_AFTER])),
        "has_phone_number": holds_a_number(
            status=str(row[12]),
            direction=str(direction),
            engine_agent_ref=row[11],
            number_refs=list(row[_AFTER] or ()),
        ),
        "voice_tuning": tuple(row[_AFTER + 1 : _AFTER + 6]),
        "max_reply_tokens": row[_AFTER + 6],
        "business_name": row[_AFTER + 7],
        "opening_waits_for_caller": bool(row[_AFTER + 8]),
        "turn_detection": turn_detection_of(row[_AFTER + 9]),
        # A restricted free trial never places a call back (D-697), so its agents must not
        # offer one (founder decision 1, 10 Oct 2026).
        "callbacks_offered": await restricting_trial(session, tenant_id=tenant_id) is None,
        # The client's answering-machine switch (founder decision 14, D-716).
        "detect_machines": await machine_detection_on(session),
        # The hidden-caller instruction is carried only by a client with a forwarded number.
        "forwarded_line": await has_forwarded_line(session),
        # The facts this agent knows by heart, in rank order (D-896, `agents/hot_facts`).
        "hot_facts": await hot_facts.load_texts(session, agent_id=agent_id),
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
        # Sentence three (D-507), whose switch IS the memory switch — there is no third
        # `*_enabled` column to read, and that is the decision rather than an omission.
        caller_memory_notice_line=str(agent["caller_memory_notice_line"]),
        caller_memory_enabled=bool(agent["caller_memory_enabled"]),
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
    ordering being skipped, and the honest answer is a refusal naming the missing thing —
    in the reader's words, not the process's: see the comment at the raise. The
    disclosure line gets this treatment already (non-null by schema, hard rule 5); the
    script had no equivalent guard because the default hid the case.

    NOT a check for a *good* script — that is step 7's test call, which is pilot-gated
    and outside this function. This is the floor: there is one, and it is the client's.
    """
    prompt = agent.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt
    # WRITTEN FOR THE OWNER OF THE BUSINESS, because they are the reader who arrives here
    # most often and the one with least to work with. Two doors reach this: the operator's
    # `POST /v1/admin/tenants/{id}/agents/{id}/publish`, and the CLIENT's own
    # `POST /v1/agents/{id}/activate` (`org:manage`, client realm) — the "Put this agent
    # on the phone" button. The sentence used to be "Publishing it would put a generic
    # placeholder on the client's phone line … complete the intake step for this client",
    # which speaks ABOUT the client TO the client: their word is "my agent", not "the
    # client", they have never heard of a prompt version, and an intake step is our
    # process, not a control on their screen. The operator's vocabulary moves to the log
    # line below, which is also the first time this refusal was traceable at all.
    log.info("agent_publish_refused_no_script", extra={"agent_id": str(agent["id"])})
    raise ProblemError(
        kind="business_rule",
        code="agent_has_no_script",
        title="This agent has nothing to say yet",
        detail=(
            "Nothing has been written for this agent to say, so there is nothing to put "
            "on the phone. Putting it live now would answer your callers with a greeting "
            "that knows nothing about your business — no hours, no prices, no names."
        ),
        remediation=(
            "Open this agent's script, write what it should say, and save it. Then put "
            "it on the phone."
        ),
    )


def _model_legs(agent: AgentRow, *, engine: VoiceEngine) -> dict[str, Any]:
    """The speech fields of `ModelConfig`, for the legs this engine lets us choose.

    A leg the engine DICTATES (ThinnestAI's transcriber, model and voice, D-678) is sent as
    the row holds it — `require_speech_leg` refuses any value there, and no writer fills
    those columns — and the voice is cleared. On an engine whose voice leg is ours the
    row's catalogue id is split into model and speaker by `speech_for_voice_id`, with the
    catalogue's display name beside them (`ModelConfig.tts_voice_label`).
    """
    legs: dict[str, Any] = {
        "stt_provider": agent["stt_provider"],
        "stt_model": agent["stt_model"],
        "stt_autodetect": False,
    }
    if engine.capabilities.is_ours("tts"):
        voice_id = agent["tts_voice"]
        tts_model, speaker = speech_for_voice_id(voice_id)
        catalogued = get_voice(voice_id) if voice_id else None
        legs.update(
            tts_provider=agent["tts_provider"],
            tts_model=tts_model,
            tts_voice=speaker,
            tts_voice_label=catalogued.label if catalogued is not None else None,
        )
    return legs


def _call_settings_fields(agent: AgentRow, *, languages: Sequence[str]) -> dict[str, Any]:
    """The `AgentConfig` fields of the call settings, resolved agent -> account -> Calevate
    (`agents/call_handling`). The sentinels a client chooses become the config's own: never
    asking is no `nudge_after_seconds`, the platform's question is no `nudge_phrase`, and no
    sound is no `ambience`. The platform's filler lines are ours in the agent's `languages`
    (`spoken_style.thinking_lines`, founder 23 Oct 2026), so a Telugu call is never covered by
    the engine's English one; a language with none leaves the engine's own. `.get`: test
    fixtures build partial rows, which hold only the first two settings."""
    own = agent.get("call_settings") or CallSettings(
        turn_silence_ms=agent.get("turn_silence_ms"),
        end_call_on_finish=agent.get("end_call_on_finish"),
    )
    organization = agent.get("organization_call_settings") or CallSettings(
        turn_silence_ms=agent.get("organization_turn_silence_ms"),
        end_call_on_finish=agent.get("organization_end_call_on_finish"),
    )
    v = resolve_settings(own, organization).values
    after = v.nudge_after_seconds
    return {
        "turn_silence_ms": v.turn_silence_ms,
        "end_call_on_finish": v.end_call_on_finish,
        "nudge_after_seconds": after if after else None,
        "nudge_count": v.nudge_count,
        "nudge_phrase": v.nudge_phrase or None,
        "end_after_silence_seconds": v.end_after_silence_seconds,
        "filler_lines": v.filler_lines or thinking_lines(languages)[:FILLER_LINES_MAX],
        "ambience": None if v.ambience == "off" else v.ambience,
        "ambience_volume_pct": v.ambience_volume_pct,
        # None while the console has no wait: the field is then never sent (D-901).
        "opening_wait_ms": v.opening_wait_ms if opening_wait_available() else None,
    }


def _to_config(
    tenant_id: UUID,
    agent: AgentRow,
    *,
    engine: VoiceEngine,
    handoff: HandoffSpec | None = None,
) -> AgentConfig:
    settings = get_settings()
    hosted = _engine_voice_fields(agent, engine=engine)
    steps, body = _steps_for(
        engine, agent, _script_for(engine, _assert_has_a_script(agent)), handoff=handoff
    )
    config = AgentConfig(
        tenant_id=str(tenant_id),
        agent_id=str(agent["id"]),
        name=str(agent["name"]),
        # Not `str(...)`: the row narrowed this to the same Literal `AgentConfig`
        # declares (`_is_agent_direction`), and re-widening it here would put the
        # unchecked hop back in the one place it mattered.
        direction=agent["direction"],
        language_primary=str(agent["language_primary"]),
        business=str(agent.get("business_name") or ""),
        # The prompt names them and the worker's transcriber stops pinning the primary, so
        # a caller in one of them is heard and answered in it (D-666).
        languages_extra=published_extra_languages(
            str(agent["language_primary"]), agent["languages_extra"], tenant_id=tenant_id
        ),
        system_prompt=body,
        script_steps=steps,
        facts_in_knowledge=hosted_agent_limits(engine).facts_in_knowledge,
        knowledge_tool=hosted_agent_limits(engine).knowledge_tool,
        # The account must be able to keep a call back (a restricted trial cannot) and the
        # script must not withhold them. `.get`: test fixtures build partial rows.
        callbacks_offered=bool(agent.get("callbacks_offered", True))
        and not call_backs_withheld(agent.get("prompt")),
        # The engine's own hand-over and lead sentences left out, ours in the prompt (D-847).
        engine_own_rules=engine.name == "thinnest" and settings.thinnest_own_rules,
        # Our call rules in place of the engine's default call rules (D-850).
        engine_call_instructions=engine.name == "thinnest" and settings.thinnest_call_instructions,
        detect_machines=bool(agent.get("detect_machines", False)),
        opening_waits_for_caller=bool(agent.get("opening_waits_for_caller", False)),
        **_call_settings_fields(
            agent,
            languages=(
                str(agent["language_primary"]),
                *published_extra_languages(
                    str(agent["language_primary"]), agent["languages_extra"], tenant_id=tenant_id
                ),
            ),
        ),
        max_reply_tokens=resolve_max_reply_tokens(agent.get("max_reply_tokens")),
        # An operator's per-agent trial (D-901) over the console's mode for every agent.
        turn_detection=agent.get("turn_detection") or settings.thinnest_turn_detection,
        acknowledgements=settings.thinnest_acknowledgements,
        early_answers=settings.thinnest_early_answers,
        interrupt_words=settings.thinnest_interrupt_words,
        has_phone_number=bool(agent.get("has_phone_number", False)),
        forwarded_line=bool(agent.get("forwarded_line", False)),
        # THE NOTICES THE AGENT VOLUNTEERS BEFORE ITS OPENING LINE, composed from this
        # agent's two toggles by the one composer (D-163). The opening line itself (the
        # greeting) stays in the script and is never replaced by these (D-708). Empty is a
        # legitimate answer — both notices switched off, the agent opens on its opening
        # line — and is NOT the old "missing disclosure" state: the AI sentence is still
        # NOT NULL on the row, the compliance gate still refuses an agent without one,
        # and the answer to a caller who ASKS is `truthful_answer_directive`, which no
        # column on this row can reach. The recording sentence is spoken only where the
        # engine records audio — the same fact the floor's clause 2 is composed from below.
        **notice_fields(posture_of(agent), call_is_recorded=engine.capabilities.records_audio),
        # FROM THE ENGINE THAT WILL RUN THIS AGENT, not from any column — no column decides
        # whether audio is captured. It composes clause 2 of the truthful-answer floor, so
        # an agent on a leg that records nothing stops telling callers otherwise
        # (`calevate_shared.engine.truthful_answer_directive`).
        call_is_recorded=engine.capabilities.records_audio,
        # DOES THIS AGENT REMEMBER ITS CALLERS (D-507/D-513)? It reaches the engine as a
        # PROMPT SECTION and nothing else — the facts are per-call and ride the dial or the
        # worker's inbound caller-memory read, because a fact about ONE person may not be written
        # onto an agent object every caller shares. The same column also governs
        # auto-reschedule callbacks (D-514): one switch, one reader.
        caller_memory_enabled=bool(agent["caller_memory_enabled"]),
        caller_memory_in_engine=hosted_agent_limits(engine).remembers_callers,
        models=ModelConfig(
            **_model_legs(agent, engine=engine),
        ),
        engine_voice_id=hosted.voice_id,
        engine_byok_voice_id=hosted.byok_voice_id,
        engine_byok_voice_tuning=config_tuning(
            agent.get("voice_tuning") or (None,) * 5, byok_voice_id=hosted.byok_voice_id
        ),
        engine_speaking_speed=config_speaking_speed(
            agent.get("voice_tuning") or (None,) * 5, byok_voice_id=hosted.byok_voice_id
        ),
        engine_own_voice_key=hosted.own_voice_key,
        engine_model_id=hosted.model_id,
        engine_own_model=hosted.own_model,
        webhook_url=f"{settings.webhook_base_url}/hooks/v1/engine/{settings.engine}",
        # The cost-runaway guard. Resolved here rather than defaulted in the model, so
        # an agent that has never been given a cap is still published with one.
        max_call_duration_s=effective_call_cap(agent["max_call_duration_s"]),
        # WHO THIS AGENT HANDS A CALLER TO RIGHT NOW (D-533) — a PARAMETER rather than a
        # field read off the row, for the reason the knowledge-base handles are one, and
        # for one more.
        #
        # It is not a column: it is the answer to "which member of the roster is on duty at
        # this instant", which needs a second query and a clock. Reading it here would make
        # this function async and would put a roster read on the prompt-composition path
        # that does not want one.
        #
        # **AND `None` IS A VALID, COMMON, LOAD-BEARING ANSWER, NOT A MISSING VALUE.**
        # Outside every roster member's hours, `agents/handoff.on_duty` returns nobody,
        # this is None, the adapter emits no transfer tool at all, and the model has
        # nothing to fire — which is the only way "never transfer outside business hours"
        # can be enforced on an engine where the destination is fixed at publish time. A
        # caller that forgets to pass this therefore publishes an agent that cannot
        # escalate, which is the safe direction to be wrong in; `_variant_config` and the
        # drift path both pass it deliberately rather than by default.
        handoff=handoff,
    )
    # The facts this agent knows by heart, cut to fit (D-896); a no-op on every engine that
    # holds the facts in the prompt already.
    return hot_facts.with_known_facts(config, agent.get("hot_facts") or (), engine)


def _call_prompt_for(
    engine: VoiceEngine,
    tenant_id: UUID,
    agent: AgentRow,
    *,
    merge_values: dict[str, str | None] | None = None,
) -> str | None:
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
    prompt = compose_engine_prompt(_to_config(tenant_id, agent, engine=engine))
    if merge_values:
        # DIAL-TIME merge of the structured builder's `{{ }}` fields, applied to the
        # composed prompt so the platform-rules block underneath is substituted too (it
        # holds no `{{ }}`, so this is a no-op there, but running it over the whole string
        # means there is one substitution pass, not one per section). Unresolved fields are
        # removed, never spoken — `keep_unresolved` defaults False.
        prompt = substitute_variables(prompt, merge_values)
    return prompt


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


async def _ensure_results_webhook(
    engine: VoiceEngine,
    *,
    ref: str,
    agent_id: UUID,
    reclaim: bool,
    session: AsyncSession,
    rate_key: EngineRateKey,
    own_model: str | None = None,
) -> None:
    """Register (or confirm) the endpoint this vendor agent reports its calls to (D-678).

    A no-op on an engine that does not sign deliveries per endpoint. Called after the
    `engine_agent_routes` row is written, in the same transaction, because the endpoint's
    sealed secret is stored on that row. A failure fails the publish rather than leaving an
    agent live whose calls never report back; with `reclaim`, the vendor agent this publish
    created is deleted first, for `_reclaim_orphan`'s reason. On an engine metered by the
    minute it also stamps the rate key the agent's minutes are metered at
    (`billing/engine_minutes`).
    """
    try:
        await ensure_agent_webhook(session, engine=engine.name, engine_agent_ref=ref)
    except Exception:
        if reclaim:
            await _reclaim_orphan(engine, agent_id, ref, "results_webhook_not_registered")
        raise
    if engine.name in ATTESTED_MINUTE_ENGINES:
        # The chosen voice's band, or the base rate (`agents/engine_choice.py`).
        await record_engine_rate_key(
            session,
            engine=engine.name,
            engine_agent_ref=ref,
            rate_key=rate_key,
            own_model=own_model,
        )


async def _ensure_in_call_actions(
    engine: VoiceEngine,
    session: AsyncSession,
    *,
    agent_id: UUID,
    ref: str,
    reclaim: bool,
) -> None:
    """Register (or converge) the vendor agent's in-call actions — opt-out, call-back,
    call-back cancel — on an engine that reaches our tools that way
    (`reliability/engine_actions.py`). A no-op elsewhere. A failure fails the publish, with
    `reclaim` deleting a vendor agent this publish created, for `_reclaim_orphan`'s reason:
    an agent live without its opt-out tool is one a caller cannot be removed from mid-call."""
    try:
        await ensure_agent_actions(session, engine=engine.name, engine_agent_ref=ref)
    except Exception:
        if reclaim:
            await _reclaim_orphan(engine, agent_id, ref, "in_call_actions_not_registered")
        raise
    # The caller lookup (D-716). Never fails the publish: without it a call still goes
    # ahead, only without the caller's name; the drift sweep converges it.
    await ensure_call_start_quietly(
        session, engine=engine.name, engine_agent_ref=ref, agent_id=agent_id
    )


async def _publish_business_facts(
    engine: VoiceEngine,
    session: AsyncSession,
    *,
    agent_id: UUID,
    ref: str,
    reclaim: bool,
    script: str | None,
    variant_id: UUID | None = None,
) -> None:
    """Push the script's [T0 FACTS] block as the vendor agent's facts document, on an engine
    that keeps facts out of the prompt, and the client's published knowledge
    (`agents/engine_facts.py`); `variant_id` names the experiment arm `ref` speaks. A failure
    fails the publish, with `reclaim` deleting a vendor agent this publish created, for
    `_reclaim_orphan`'s reason."""
    try:
        await sync_business_facts(
            session,
            engine,
            agent_id=agent_id,
            ref=ref,
            facts=block_of(script),
            variant_id=variant_id,
        )
    except Exception:
        if reclaim:
            await _reclaim_orphan(engine, agent_id, ref, "business_facts_not_published")
        raise


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
    return await _apply_inbound_bindings(
        session, engine, agent_id=agent_id, ref=ref, answers=answers, rows=rows
    )


async def _apply_inbound_bindings(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    agent_id: UUID | None,
    ref: str,
    answers: bool,
    rows: Sequence[Any],
) -> InboundRouting:
    """Tell the engine about EACH of `rows`, count what happened, alarm on what did not.

    Extracted from `route_inbound_numbers` when `attach_number_to_agent` needed the same
    work over ONE number instead of over every number an agent holds (D-576). It is the
    same loop, the same capability question, the same per-number alarm and the same log
    line — hoisted rather than copied, because two implementations of "what the engine was
    told" is the shape that lets one of them stop alarming (CLAUDE.md: one way per
    problem, and migrate rather than accumulate).

    The row shape is `_AGENT_NUMBERS_SQL`'s, in that order. `ref` is unused on the release
    arm and that is the Protocol's shape, not an oversight: `unbind_inbound_number` names
    the NUMBER, because "nothing of ours answers this" is not a claim about an agent.

    `agent_id` is nullable for the same reason and is only ever a LABEL here — the agent an
    operator should be told about. A detach of a number that was attached to nobody has no
    such agent, and `"none"` is written rather than an invented id: an alarm naming a row
    that is not an agent would send an operator to the wrong screen.
    """
    subject = str(agent_id) if agent_id is not None else "none"
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
            extra={"agent_id": subject, "engine": engine.name, "numbers": len(rows)},
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
                agent_id=subject,
                number_id=str(number_id),
            )
    log.info(
        "agent_inbound_numbers_routed",
        extra={
            "agent_id": subject,
            "engine": engine.name,
            "bound": bound,
            "released": released,
            "failed": failed,
        },
    )
    return InboundRouting(bound=bound, released=released, failed=failed, unsupported=0)


async def retire_in_call_actions(*, agent_id: UUID, ref: str | None) -> int:
    """Remove the vendor agent's in-call actions when the agent stops being published.

    A failure alarms and does not undo the pause or archive, `route_inbound_numbers`'
    contract: the actions would still reach our endpoint, which keeps answering for the
    route, so what is left is a vendor object to tidy rather than a caller misled.
    """
    engine = get_engine()
    try:
        return await retire_agent_actions(engine=engine.name, engine_agent_ref=ref)
    except ProblemError as exc:
        alert(
            "CORE_LOGIC",
            "engine_actions_not_retired",
            detail=(
                "an unpublished agent's in-call actions are still on the voice platform; "
                f"remove them in its console or republish and pause again. Refusal: {exc.code}."
            ),
            agent_id=str(agent_id),
        )
        return 0


# --- the credit cutover: what a caller hears when the wallet is empty (8 Sep 2026) ------
#
# THE PROBLEM THIS CLOSES. `compliance.check_dispatch` refuses OUTBOUND at a balance of
# zero or below and inbound passes through none of it, so a client whose top-up lapsed
# went on having their phone answered — and `workers/pipeline.py` went on debiting every
# answered minute against a wallet that could only get more negative. Nothing bounded it.
#
# THE FOUNDER'S DECISION, taken 8 Sep 2026 and implemented here rather than re-opened:
# at a balance of ZERO OR BELOW the agent stops doing business and the caller hears one
# short neutral line instead. No grace overdraft and no grace period — the warning already
# fired at Rs.250 and again at Rs.150 (`workers/wallet_alerts.py`), so the client was told
# twice before anything changed.
#
# WHY IT IS ENGINE-SIDE STATE AND NOT A GATE OF OURS. An inbound call reaches nothing of
# ours before it is answered: the engine picks up, and we hear about the call only by
# webhook afterwards (`apps/voice-runtime/webhook_routes.py` — a hint, and the fetch is the
# truth). There is no pre-answer hook to refuse from, so the enforcement is durable state
# AT the engine, applied by `override_call_script`. On ThinnestAI that PAUSES the line
# (`engine/thinnest.py::ThinnestEngine.override_call_script`: `answersCalls: false` with
# `voice.unavailableMessage`): the phone provider reads one reasonless sentence and the
# call ends, so no AI speaks, nothing records and no conversation is billed. Unbinding the
# number instead would leave the caller whatever the carrier does with an unanswered
# number, which the founder refused for the maintenance window ("play a message instead of
# the call not connecting"). An engine without `script_override` reports `unsupported`
# (`reconcile_inbound_answering`) rather than failing silently on a live call.

#: What a caller hears when the client's calling credit has run out.
#:
#: **IT GIVES NO REASON, AND EVERY WORD OF THAT IS DELIBERATE.** The caller is our client's
#: customer, and they must not be able to work out from this call that the business has not
#: paid a bill — that is a reputational harm WE would be inflicting on the client, on their
#: own customer, at the moment they are least able to answer for it. So:
#:
#: * NOT "we are closed" / "outside business hours". The clinic may well be open and full
#:   of people; that is a false statement about our client, made in their own voice.
#: * NOT "there is a technical problem" / "the line is busy". Also untrue, and an
#:   invitation to keep redialling.
#: * NOT one syllable about the account, the balance, a payment, a subscription or a
#:   service — the caller has no business knowing any of it and the client did not consent
#:   to us telling them.
#:
#: What is left is the true, reasonless sentence the founder asked for: we cannot take the
#: call, try again later. "Later" is the only promise in it and it is one we keep — the
#: moment a top-up lands the agent answers properly again, with no human in the loop.
CREDIT_STOP_MESSAGE: Final = "Sorry, we cannot take your call right now. Please try again later."


def credit_stop_greeting(posture: DisclosurePosture, *, call_is_recorded: bool) -> str:
    """The notices the agent has switched on, then the neutral message. Not the script's
    opening line (D-708): its greeting offers help this call cannot give.

    PREPENDED, NOT REPLACED — `workers/maintenance._maintenance_greeting` argues this and
    the argument is the same one, so it is followed rather than re-decided. `opening_line`
    is what the agent VOLUNTEERS: the AI disclosure and the recording notice, each on its
    own client-set switch (D-163). Replacing it would switch both off, silently, for every
    client whose credit ran out.

    **ON AN ENGINE THAT RECORDS AUDIO THIS IS LOAD-BEARING RATHER THAN MERELY TIDY.**
    Overriding the script changes the welcome message and the task prompt and nothing
    else, so a silenced agent there records this call exactly as it records any other. A
    DPDP notice-and-consent obligation attaches to a recording that is actually made;
    dropping the notice because "there is no real conversation" would be reasoning our way
    out of an obligation we are still incurring. `call_is_recorded` is that engine fact
    (`EngineCapabilities.records_audio`); where it is False, `compose_opening_line` drops
    the recording sentence because no recording is made.
    """
    opening = compose_opening_line(posture, call_is_recorded=call_is_recorded).strip()
    return f"{opening} {CREDIT_STOP_MESSAGE}".strip()


def credit_stop_prompt(*, call_is_recorded: bool) -> str:
    """What the agent is told to do while its client's wallet is empty: say the line, say
    nothing else, end the call.

    ═══ HARD RULE 5 IS UNTOUCHED, IN BOTH ITS HALVES ═══

    The truthful-answer floor is appended, composed for THIS engine's recording fact, so a
    caller who asks whether they are talking to an AI, or whether the call is recorded,
    gets the same true answer here as on an ordinary call. It would have been easy to argue
    the floor away — "no conversation happens, so nothing attaches" — and it would have
    been wrong: the call IS answered, and on an engine that records audio it IS recorded
    (see `credit_stop_greeting`). The floor is preserved rather than reasoned around, and
    `scripts/check_compliance_invariants.py` reads the composer.

    ═══ WHAT IS FORBIDDEN, AND WHY IT IS SPELLED OUT TO THE MODEL ═══

    A language model handed "you cannot take this call" and an insistent caller will
    improvise a reason, and every reason available to it is one we must not give: that the
    business is closed (false, and about our client), that there is a fault (false), or —
    worst — the true one. The prompt therefore forbids each by name rather than trusting
    the model to be incurious, and forbids taking a message: nothing behind this call is
    going to act on one, and a promise the platform cannot keep is what the founder's
    maintenance correction already refused once.
    """
    return "\n\n".join(
        (
            "You are answering a call that this business cannot take right now. Saying the "
            "sentence below is the ONLY thing you do on this call.",
            f'Say this, in the caller\'s own language: "{CREDIT_STOP_MESSAGE}"',
            "Give NO reason, and invent none if you are pressed. Do NOT say the business "
            "is closed, is busy, is having a technical problem, or anything at all about "
            "its account, its billing or its subscription. If the caller asks why, say "
            "only that you are not able to say, and ask them to try again later.",
            "Do NOT take a booking, a message, an order, a complaint, a call-back request "
            "or any of the caller's details, and do NOT promise that anyone will ring "
            "them back.",
            "Then end the call politely. Keep the whole call under twenty seconds.",
            truthful_answer_directive(call_is_recorded=call_is_recorded),
        )
    )


#: Live agents of ONE tenant that can answer a call, with the handle the engine knows them
#: by, the six disclosure columns `compose_opening_line` needs, and what we last told the
#: engine to say. Outbound-only agents are excluded: nobody ever rings them, so overriding
#: their script would change nothing a caller can hear and would spend a vendor round trip
#: saying so. The shape is `workers/maintenance._ANSWERING_AGENTS_SQL`'s, one column wider.
#: The six columns `_posture_of_row` reads positionally, plus the id, the vendor handle,
#: the silence pair (`inbound_silenced_at`, `inbound_silence_reason`) and the direction —
#: eleven, in this order and only in this order. Named because
#: TWO queries need them in the SAME ORDER — the sweep below and the single-agent read —
#: and two hand-written SELECTs that must agree is how a positional constructor silently
#: starts reading the wrong field. Written as a literal and concatenated: `check_raw_sql`
#: vouches for a `+` of literals but cannot trace a `.split()` of one, and deriving the
#: second query that way is exactly the shortcut it caught.
_ANSWERING_AGENT_COLUMNS = (
    "SELECT id, engine_agent_ref, ai_disclosure_line, ai_disclosure_enabled, "
    "recording_notice_line, recording_notice_enabled, caller_memory_notice_line, "
    "caller_memory_enabled, inbound_silenced_at, inbound_silence_reason, direction "
    "FROM agents"
)

_ANSWERING_AGENTS_SQL = (
    _ANSWERING_AGENT_COLUMNS + " WHERE status = 'live' AND engine_agent_ref IS NOT NULL"
    " AND direction IN ('inbound', 'both') AND deleted_at IS NULL AND archived_at IS NULL"
    " ORDER BY id"
)

#: The same columns for ONE agent, so the stamp read and `_posture_of_row` are served by a
#: single row rather than by two fetches of the same row.
_ONE_ANSWERING_AGENT_SQL = _ANSWERING_AGENT_COLUMNS + " WHERE id = :aid"


@dataclass(frozen=True, slots=True)
class InboundCutover:
    """What one reconciliation pass actually achieved, per tenant.

    Counts rather than a bool for `InboundRouting`'s reason: a caller that wants to tell an
    operator what happened needs numbers, and a test that wants to prove a phone went quiet
    (or came back) needs something to assert.
    """

    #: Agents newly switched to the neutral message.
    silenced: int
    #: Agents put back to saying their own words.
    restored: int
    #: Agents already in the state they should be in. No vendor call was made for these.
    unchanged: int
    #: Agents the engine could not be reached about. Each one has raised an alarm.
    failed: int
    #: True when this engine cannot override a script at all, so nothing was attempted.
    unsupported: bool = False
    #: Agents this pass deliberately did not touch because a STRONGER silence holds them
    #: (D-564): the drift sweep proved they cannot tell a caller they are an AI, and a
    #: wallet top-up does not end that. Counted apart from `unchanged` because they are
    #: the one case where the client has paid and their phone still does not answer, and
    #: an operator asked "why is this line dead after a top-up" needs the number that
    #: answers it rather than one that hides inside "nothing to do".
    withheld: int = 0


def _posture_of_row(row: Any) -> DisclosurePosture:
    """`_ANSWERING_AGENTS_SQL`'s six disclosure columns as the composer's one value.

    Positional rather than by name because the query is a dozen lines above it; the SELECT
    and this constructor are read together or not at all.
    """
    return DisclosurePosture(
        ai_disclosure_line=str(row[2]),
        ai_disclosure_enabled=bool(row[3]),
        recording_notice_line=str(row[4]),
        recording_notice_enabled=bool(row[5]),
        caller_memory_notice_line=str(row[6]),
        caller_memory_enabled=bool(row[7]),
    )


#: WHY an agent's inbound answering is not its own (D-564). The vocabulary
#: `agents.inbound_silence_reason` holds, and the CHECK in migration `f4a2c7e19d63`
#: spells the same two words.
#:
#: TWO MECHANISMS, NOT TWO LABELS ON ONE. `credits` means the engine is holding the
#: credit-stop SCRIPT and the call is still answered; `truthful_answer_missing` means the
#: agent's numbers are UNBOUND and nothing answers them at all. They differ in what a
#: caller experiences, in what ends them, and in which one wins when both apply — see
#: `INBOUND_SILENCE_PRECEDENCE`.
INBOUND_SILENCE_CREDITS: Final = "credits"
#: Spelled as the VERDICT it mirrors rather than as a word of its own: this reason exists
#: exactly when `engine_agent_routes.drift_state` is that value, and one fact with two
#: spellings is where drift starts.
INBOUND_SILENCE_TRUTHFUL_ANSWER: Final = TRUTHFUL_ANSWER_MISSING
#: The auto-healer took this agent's line off because its real calls were failing and a
#: repair did not fix them (D-701). Only the healer lifts it (`lift_healer_silence`), after
#: its own checks pass or a person restores the line; neither a top-up nor a republish may.
INBOUND_SILENCE_HEALER: Final = "healer"

#: STRONGEST FIRST. An agent can be both broke and non-compliant, and the engine can hold
#: only one state, so the order is a decision rather than an accident: a compliance
#: silence outranks a credit one because they fail in different currencies. Coming out of
#: a credit silence wrongly costs the client one metered call; coming out of a compliance
#: silence wrongly puts a caller in front of an agent that has been PROVEN unable to tell
#: them it is a machine, which is hard rule 5's floor and not a cost at all.
#: The healer's silence sits between them: a broken agent must not answer whatever the
#: wallet says, and it never outranks the compliance silence, which unbinds the numbers.
INBOUND_SILENCE_PRECEDENCE: Final = (
    INBOUND_SILENCE_TRUTHFUL_ANSWER,
    INBOUND_SILENCE_HEALER,
    INBOUND_SILENCE_CREDITS,
)

#: The whole vocabulary, derived from the precedence order rather than retyped beside it —
#: `tests/inbound_compliance_silence_test.py` asserts this set equals the CHECK's, so a
#: third reason added here cannot silently fail a constraint at 03:00.
INBOUND_SILENCE_REASONS: Final[frozenset[str]] = frozenset(INBOUND_SILENCE_PRECEDENCE)


async def _stamp_inbound_silence(
    session: AsyncSession, *, agent_id: UUID, reason: str | None
) -> None:
    """Record what the ENGINE now holds for this agent, not what we wish it held.

    Written only AFTER the vendor call returned, for the reason `live_tts_voice` is: a
    column that claims a script the engine was never observed to take is worse than no
    column, because the reconciler reads it to decide whether to act and would then decide
    to do nothing for ever.

    ONE STATEMENT WRITES BOTH COLUMNS (D-564), which is what lets the table CHECK them as
    an equivalence: `reason=None` clears the pair, a reason sets it. No caller can produce
    a stamp with no reason, and the database refuses one anyway.
    """
    await session.execute(
        text(
            # CAST because both uses of `:reason` are in positions PostgreSQL cannot
            # infer a type for (a CASE predicate and, on the NULL path, a bare parameter),
            # and it answers `AmbiguousParameter` rather than guessing.
            "UPDATE agents SET inbound_silenced_at = "
            "CASE WHEN CAST(:reason AS text) IS NULL THEN NULL ELSE now() END, "
            "inbound_silence_reason = CAST(:reason AS text), updated_at = now() "
            "WHERE id = :aid AND deleted_at IS NULL"
        ),
        {"aid": agent_id, "reason": reason},
    )


async def reconcile_inbound_answering(
    session: AsyncSession, engine: VoiceEngine, *, tenant_id: UUID, exhausted: bool
) -> InboundCutover:
    """Make what this tenant's answering agents SAY agree with whether they have credit.

    THE ONE PLACE THE CUTOVER AND THE RECOVERY ARE DECIDED, and they are one function on
    purpose: "apply" and "undo" written apart is how a platform ends up able to silence a
    phone and unable to bring it back. Both edges are the same read of the same predicate
    (`compliance.service.credits_exhausted`, asked by the caller and passed in so this
    function cannot ask a different question than the caller acted on), and the only
    difference is which way the comparison went.

    IDEMPOTENT, and cheap when there is nothing to do. `agents.inbound_silenced_at` records
    what the engine was last observed to hold, so an agent already in the right state costs
    zero vendor round trips — which is what lets this be called on every edge and from every
    publish without turning a fleet into a rate-limit incident.

    THE RESTORE GOES THROUGH `publish_agent`, NOT THROUGH THE OVERRIDE, and the asymmetry
    is `workers/maintenance._restore_scripts`' — followed rather than re-argued. The
    override is a partial write from strings this module composed and is deliberately not
    read back; coming out of it, an agent still apologising to its client's customers after
    the client has paid is the failure nobody would notice for days, so the restore comes
    from our own row through the one path that verifies (D-64).

    PER-AGENT ISOLATION. One agent's vendor failure must not cost the others theirs: it is
    counted, alarmed, its column left saying what the engine is still believed to hold, and
    the walk continues. The next pass retries it.

    ═══ AND WHAT HAPPENS INSIDE A MAINTENANCE WINDOW, WHICH OVERRIDES THE SAME TWO FIELDS ═══

    Nothing here special-cases one, and the ordering already resolves it in the right
    direction both ways. A wallet that empties DURING a window replaces the maintenance
    message with this one — both say "we cannot take your call", and the credit one is the
    one that will still be true when the window closes. A top-up during a window cannot
    restore: `publish_agent` refuses while a window is draining or active (D-544), so the
    restore is counted as a failure, alarmed and retried — and the window's own
    `_restore_scripts` republishes every live answering agent at the end, which runs
    `_settle_inbound_silence` and lands the agent on whichever script its wallet now
    earns. The client's phone therefore comes back when the platform does, and not before,
    which is the same promise every other client gets.
    """
    if not engine.capabilities.has("script_override"):
        # NOT a silent no-op and not a fallback to unbinding the number. An engine that
        # cannot change what an agent says cannot deliver the founder's decision at all,
        # and the honest report of that is a count the caller alerts on.
        return InboundCutover(silenced=0, restored=0, unchanged=0, failed=0, unsupported=True)

    rows = (await session.execute(text(_ANSWERING_AGENTS_SQL))).all()
    silenced = restored = unchanged = failed = withheld = 0
    for row in rows:
        agent_id, ref, reason = row[0], str(row[1]), row[9]
        if reason == INBOUND_SILENCE_TRUTHFUL_ANSWER:
            # THE WALLET DOES NOT GET TO END A COMPLIANCE SILENCE (D-564), in either
            # direction. Restoring here would put a caller in front of an agent the sweep
            # has PROVEN cannot tell them it is a machine, decided by a money question
            # that knows nothing about it; and silencing an agent whose numbers are
            # already unbound would spend a vendor round trip overwriting the script of
            # something nobody can ring. `INBOUND_SILENCE_PRECEDENCE` is the order, and
            # `reconcile_inbound_truthful_answer` is the only thing that lifts this one.
            withheld += 1
            continue
        if reason == INBOUND_SILENCE_HEALER:
            # The line is already off for a stronger reason; the wallet neither restores it
            # nor needs to silence it again (`lift_healer_silence` hands it back).
            withheld += 1
            continue
        # `reason` is now `credits` or NULL, so the stamp and the predicate compare
        # directly — the shape this loop always had, with the third state taken out above.
        if (reason is not None) == exhausted:
            unchanged += 1
            continue
        try:
            # One savepoint per agent: a failure part-way through one agent's writes is
            # rolled back to here, and a database error does not leave the shared
            # transaction aborted for every agent after it.
            async with session.begin_nested():
                if exhausted:
                    recorded = engine.capabilities.records_audio
                    await engine.override_call_script(
                        ref,
                        opening_line=credit_stop_greeting(
                            _posture_of_row(row), call_is_recorded=recorded
                        ),
                        system_prompt=credit_stop_prompt(call_is_recorded=recorded),
                    )
                    await _stamp_inbound_silence(
                        session, agent_id=agent_id, reason=INBOUND_SILENCE_CREDITS
                    )
                else:
                    # `publish_agent` clears the stamp itself through
                    # `_settle_inbound_silence`, so there is no second writer of the column.
                    await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
            if exhausted:
                silenced += 1
            else:
                restored += 1
        except Exception as exc:
            failed += 1
            alert(
                "CORE_LOGIC",
                "inbound_credit_cutover_failed",
                detail=(
                    "the voice platform was not told what this agent should say, so an "
                    "incoming call on its number reaches "
                    + (
                        "an ordinary agent this client has no credit to pay for"
                        if exhausted
                        else "a message telling the caller we cannot take their call, "
                        "even though the client has topped up"
                    )
                    + f". Refusal: {exc.__class__.__name__}."
                ),
                tenant_id=str(tenant_id),
                agent_id=str(agent_id),
            )
    log.info(
        "inbound_credit_cutover",
        extra={
            "tenant_id": str(tenant_id),
            "exhausted": exhausted,
            "silenced": silenced,
            "restored": restored,
            "unchanged": unchanged,
            "failed": failed,
            "withheld": withheld,
        },
    )
    return InboundCutover(
        silenced=silenced,
        restored=restored,
        unchanged=unchanged,
        failed=failed,
        withheld=withheld,
    )


#: What a forwarding agent says before handing the caller to the client's own phone. No
#: reason, for `CREDIT_STOP_MESSAGE`'s reasons.
HEALER_FORWARD_LINE: Final = "Please hold while I put you through to the team."

HealerHold = Literal["paused", "forwarded", "unsupported", "not_answering", "gone", "held"]


@runtime_checkable
class ForwardsLine(Protocol):
    """An adapter that can hand every caller of an agent to another phone by the agent's own
    hand-over. ThinnestAI forwards the number instead (`apply_healer_silence`, D-743)."""

    async def forward_line(
        self,
        ref: EngineAgentRef,
        *,
        phone_e164: str,
        line: str,
        opening_line: str,
        system_prompt: str,
    ) -> None: ...


def healer_forward_greeting(posture: DisclosurePosture, *, call_is_recorded: bool) -> str:
    """The notices the agent has switched on (D-163), then the hand-over line. Not the
    script's opening line (D-708): this call is handed to a person at once, so the agent's
    usual greeting would promise help it is not going to give."""
    opening = compose_opening_line(posture, call_is_recorded=call_is_recorded).strip()
    return f"{opening} {HEALER_FORWARD_LINE}".strip()


def healer_forward_prompt(*, call_is_recorded: bool) -> str:
    """Hand the caller to a person at once. The truthful-answer floor is appended exactly
    as `credit_stop_prompt` appends it (hard rule 5)."""
    return "\n\n".join(
        (
            "You are answering a call that this business wants a person to take. After the "
            "greeting, hand the caller to a person straight away using your hand-over tool. "
            "That is the only thing you do on this call.",
            "Do NOT answer questions, take a booking, a message, an order or any of the "
            "caller's details, and give no reason for the hand-over.",
            truthful_answer_directive(call_is_recorded=call_is_recorded),
        )
    )


async def apply_healer_silence(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    forward_to: str | None,
) -> HealerHold:
    """Take a broken agent's line off (D-701): hand callers to `forward_to` where the engine
    can, otherwise answer with the neutral can't-take-your-call sentence. Stamped only after
    the vendor accepted the write, for `_stamp_inbound_silence`'s reason. Vendor errors
    propagate to the healer, which records and retries them."""
    row = (await session.execute(text(_ONE_ANSWERING_AGENT_SQL), {"aid": agent_id})).first()
    if row is None:
        return "gone"
    if not agent_answers_inbound(cast(AgentDirection, str(row[10]))):
        return "not_answering"
    if row[9] == INBOUND_SILENCE_TRUTHFUL_ANSWER:
        # Its numbers are already unbound; nothing reaches it to hold.
        return "held"
    ref, recorded = str(row[1]), engine.capabilities.records_audio
    posture = _posture_of_row(row)
    from apps.api.campaigns.engine_numbers import forward_agent_numbers, numbers_can_forward

    if forward_to and numbers_can_forward() and engine.capabilities.has("script_override"):
        # A number-level forward (D-743): every call to the agent's numbers rings the
        # client's own phone, whether or not the agent answers (OPERATIONS gate T-26). The
        # agent is paused first, so a number the platform refuses to forward still answers
        # with the polite sentence rather than the broken agent.
        await engine.override_call_script(
            ref,
            opening_line=credit_stop_greeting(posture, call_is_recorded=recorded),
            system_prompt=credit_stop_prompt(call_is_recorded=recorded),
        )
        forwarded = await forward_agent_numbers(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=forward_to
        )
        held: HealerHold = "forwarded" if forwarded else "paused"
    elif forward_to and isinstance(engine, ForwardsLine):
        await engine.forward_line(
            ref,
            phone_e164=forward_to,
            line=HEALER_FORWARD_LINE,
            opening_line=healer_forward_greeting(posture, call_is_recorded=recorded),
            system_prompt=healer_forward_prompt(call_is_recorded=recorded),
        )
        held = "forwarded"
    elif engine.capabilities.has("script_override"):
        await engine.override_call_script(
            ref,
            opening_line=credit_stop_greeting(posture, call_is_recorded=recorded),
            system_prompt=credit_stop_prompt(call_is_recorded=recorded),
        )
        held = "paused"
    else:
        return "unsupported"
    await _stamp_inbound_silence(session, agent_id=agent_id, reason=INBOUND_SILENCE_HEALER)
    log.warning(
        "healer_line_held",
        extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "mode": held},
    )
    return held


async def lift_healer_silence(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> bool:
    """Give the line back. False when the healer was not holding it (a stronger silence
    took over, or it was already lifted).

    The restore is a verified publish, `reconcile_inbound_answering`'s asymmetry. An account
    whose wallet emptied meanwhile keeps a credit silence: the stamp is handed over rather
    than cleared, so the publish's own settle re-applies the credit stop."""
    from apps.api.compliance.service import credits_exhausted

    next_reason = (
        INBOUND_SILENCE_CREDITS if await credits_exhausted(session, tenant_id=tenant_id) else None
    )
    moved = (
        await session.execute(
            text(
                "UPDATE agents SET inbound_silenced_at = CASE WHEN CAST(:next AS text) IS NULL "
                "THEN NULL ELSE inbound_silenced_at END, inbound_silence_reason = "
                "CAST(:next AS text), updated_at = now() WHERE id = :aid "
                "AND inbound_silence_reason = :healer AND deleted_at IS NULL RETURNING id"
            ),
            {"aid": agent_id, "next": next_reason, "healer": INBOUND_SILENCE_HEALER},
        )
    ).first()
    if moved is None:
        return False
    from apps.api.campaigns.engine_numbers import clear_agent_forwards, numbers_can_forward

    if numbers_can_forward():
        # The healer's forward (D-743) goes before the publish switches the agent back on.
        await clear_agent_forwards(session, tenant_id=tenant_id, agent_id=agent_id)
    # take_calls=False: a live agent is republished live, and one the owner switched off
    # while it was held stays off rather than coming back on the phone.
    await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id, take_calls=False)
    return True


async def _reapply_healer_silence(
    session: AsyncSession, engine: VoiceEngine, *, tenant_id: UUID, agent_id: UUID
) -> None:
    """`_settle_inbound_silence`'s healer arm. A vendor refusal clears the stamp so the
    healer's next tick sees an unheld line and holds it again, rather than the column
    claiming a hold the engine no longer has."""
    from apps.api.healer.protection import forward_target

    try:
        await apply_healer_silence(
            session,
            engine,
            tenant_id=tenant_id,
            agent_id=agent_id,
            forward_to=await forward_target(session, agent_id=agent_id),
        )
    except Exception as exc:
        await _stamp_inbound_silence(session, agent_id=agent_id, reason=None)
        alert(
            "CORE_LOGIC",
            "healer_line_hold_failed",
            detail=(
                "an agent the healer had taken off its line was republished and the voice "
                "platform refused the hold, so it is answering again. Refusal: "
                f"{type(exc).__name__}."
            ),
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
        )


async def reconcile_inbound_truthful_answer(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    truthful_answer_applied: bool | None,
) -> str:
    """THE INBOUND HALF OF D-562 (D-564). An agent PROVEN to be running a prompt with no
    truthful-answer directive in it stops answering incoming calls, and answers again when
    it is proven to be carrying one.

    ═══ WHAT WAS OPEN ═══

    D-562 made the drift sweep's `truthful_answer_missing` verdict a DIAL refusal
    (`compliance.service.truthful_answer_drift_blocker`). Outbound stopped; inbound did
    not. The same agent, on the same vendor object, went on picking up its number and
    telling anyone who asked whether they were talking to a machine whatever the vendor's
    own console was last used to write. Hard rule 5's floor — the ANSWER, §2.0's
    unconditional one — is not an outbound rule; it is louder on inbound, where the caller
    is our client's customer and did not choose to be in the conversation.

    ═══ WHY IT CANNOT BE A GATE, AND WHY IT IS THIS INSTRUMENT ═══

    An inbound call reaches nothing of ours before it is answered — the vendor's
    orchestrator picks up on the number bound by `POST /inbound/setup` and the first we
    hear is a webhook after the fact — so the enforcement has to be durable state AT the
    engine. That is D-551's pattern and it is followed rather than re-invented. Where this
    departs from D-551 is WHICH of the two instruments is used, and the departure is the
    whole decision:

      * D-551 (no credit) overrides the SCRIPT and the call is answered with a neutral
        line, because the founder refused a dead line for an account problem: the agent is
        sound, the wallet is not, and a caller deserves a sentence.
      * HERE THE AGENT ITSELF IS THE THING THAT IS UNSOUND, so the numbers are UNBOUND and
        nothing answers at all (`route_inbound_numbers(answers=False)`).

    Three reasons, and the first is decisive. (1) `override_call_script` is a partial write
    that is DELIBERATELY NOT READ BACK (`reconcile_inbound_answering` says so), and what
    the sweep just proved is that this vendor object is NOT holding the text we published.
    Answering a failure-to-hold-our-text by writing more text down the same unverified
    channel, and then stamping the agent as handled, would be manufacturing compliance out
    of a write nobody confirmed — hard rule 11's shape, applied to a wire value. (2) Even a
    PATCH that lands leaves every other attribute of that object as the editor left it
    (`patch_update.md:19-31` writes exactly two), so the message would be spoken by an
    agent we know somebody else has been editing. (3) A neutral apology is a sentence
    delivered BY the agent; a caller who then asks "am I talking to a person?" is asking
    the very prompt that has been proven not to answer that honestly. There is no message
    we can compose that does not have to be spoken through the fault.

    A dead line is a real cost to the client and it is the smaller one. It is bounded and
    self-healing: one republish rebinds the numbers, and the client is told exactly that
    (`compliance.service.TRUTHFUL_ANSWER_DRIFT_REASON`, the launch gate's blocker row and
    the alert the sweep already raises).

    ═══ THE ARGUMENT IS TRI-STATE ON PURPOSE ═══

    `truthful_answer_applied` is the verdict's own field, and `None` — "we could not tell"
    — does NOTHING here. That is the `AgentSnapshot` doctrine held to the end of the line:
    an unreadable answer is not evidence of a missing directive, and a phone that goes
    dead because a vendor was briefly slow is the failure that gets an enforcement disarmed.
    Passed in rather than re-read, for `reconcile_inbound_answering`'s reason: this
    function must not be able to act on a different measurement than its caller recorded.

    IDEMPOTENT, and free when there is nothing to do — `agents.inbound_silence_reason` is
    the mirror, so an agent already in the right state costs no vendor round trip. A
    failure to reach the engine leaves the mirror UNSTAMPED and is retried by the next
    sweep tick, which is what stops a failed unbind from being recorded as a silence.
    """
    if truthful_answer_applied is None:
        return "indeterminate"
    row = (await session.execute(text(_ONE_ANSWERING_AGENT_SQL), {"aid": agent_id})).first()
    if row is None:
        # Deleted between the sweep's read and this write. Not an error — the same
        # non-outcome `record_drift` reports when a route vanishes under it.
        return "gone"
    ref, reason = str(row[1]), row[9]
    silenced_for_compliance = reason == INBOUND_SILENCE_TRUTHFUL_ANSWER
    if not agent_answers_inbound(cast(AgentDirection, str(row[10]))):
        # Nobody can ring it, so there is nothing to take away. Its outbound is already
        # refused per dial by `check_dispatch`, which is the whole of the rule for an
        # agent that only places calls.
        return "unchanged"
    if not truthful_answer_applied:
        if silenced_for_compliance:
            return "unchanged"
        if not engine.capabilities.has("inbound_binding"):
            # NOT a silent no-op and NOT a fallback to the script override — see the
            # docstring for why that fallback would be worse than doing nothing loudly.
            alert(
                "CORE_LOGIC",
                "inbound_truthful_answer_silence_unsupported",
                detail=(
                    f"the {engine.name} adapter cannot unbind a number, so an agent proven "
                    "to be running a prompt without the truthful-answer rule is still "
                    "answering incoming calls. Its outgoing calls are already refused."
                ),
                tenant_id=str(tenant_id),
                agent_id=str(agent_id),
            )
            return "unsupported"
        routing = await route_inbound_numbers(
            session, engine, agent_id=agent_id, ref=ref, answers=False
        )
        if routing.failed:
            # `route_inbound_numbers` has already alarmed per number. NOT STAMPED: the
            # engine was not observed to stop answering, and a mirror that claims it did
            # is a mirror that stops this function ever retrying.
            return "failed"
        await _stamp_inbound_silence(
            session, agent_id=agent_id, reason=INBOUND_SILENCE_TRUTHFUL_ANSWER
        )
        log.warning(
            "inbound_truthful_answer_silenced",
            extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)},
        )
        return "silenced"
    if not silenced_for_compliance:
        return "unchanged"
    # THE RESTORE, and it goes through the NUMBERS rather than through `publish_agent` —
    # the one place this departs from D-551's restore asymmetry, and it departs because
    # the reason for that asymmetry is absent here. There, the engine was holding a script
    # this module composed and never read back, so only a verified publish could be
    # trusted to end it. Here the engine has just been READ, by the sweep, and found to be
    # carrying the directive: the prompt needs no repair, only the numbers need giving
    # back. Republishing from a sweep would also overwrite whatever the vendor console
    # holds, which is precisely what D-121 refuses to do on a schedule.
    routing = await route_inbound_numbers(session, engine, agent_id=agent_id, ref=ref, answers=True)
    if routing.failed:
        return "failed"
    await _settle_inbound_silence(
        session,
        engine,
        tenant_id=tenant_id,
        agent_id=agent_id,
        ref=ref,
        answers=True,
        truthful_answer_proven=True,
    )
    log.info(
        "inbound_truthful_answer_restored",
        extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)},
    )
    return "restored"


async def _settle_inbound_silence(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    ref: str,
    answers: bool,
    truthful_answer_proven: bool,
) -> None:
    """The last act of every publish: leave this agent saying the right thing for the
    account it belongs to, and SILENT if it has been proven unable to say the one thing it
    must always be able to say.

    ═══ WHY IT IS HERE, IN `publish_agent`, AND NOT ONLY IN THE RECONCILERS ═══

    THIRTEEN call sites republish an agent — a voice change, a cap change, a prompt
    rollback, a script apply, an LLM default write, the ops intake flow, the maintenance
    window's own restore — and every one of them writes the agent's REAL script to the
    engine and rebinds its numbers. Each is therefore an undo of a cutover, performed by an
    author who could not see it: a client with no credit whose agent is republished for any
    reason at all would quietly go back to taking bookings we are not being paid for, and —
    since D-564 — an agent proven unable to tell a caller it is an AI would quietly go back
    to answering the phone. Putting the re-application at the one statement that ends a
    publish makes both a property of publishing rather than a rule thirteen callers have to
    remember. (The count was ELEVEN when this function was written and is not any more,
    which is the argument for the placement rather than against it.)

    ═══ THE ONE THING THAT MAY END A COMPLIANCE SILENCE, AND IT IS EVIDENCE ═══

    `truthful_answer_proven` is `verdict.truthful_answer_applied is True` from the publish's
    OWN read-back, and nothing else in this codebase may pass True. A publish that proved
    the directive is present has, as a side effect, fixed the exact fault the silence
    exists for — the agent demonstrably carries the floor again — and keeping the phone
    dead after it would be the failure D-551 spends its restore argument on, with the
    client having done precisely what we told them to do
    (`TRUTHFUL_ANSWER_DRIFT_REASON`: "Publishing the agent again restores the rule").

    Every OTHER publish preserves it, and the distinction is not a technicality: a publish
    whose read-back came back `unreadable` or `unreachable` has proven nothing, and an
    engine with no read-back at all proves nothing on every publish it ever does. Those all
    take the preserve branch, which RE-UNBINDS the numbers `route_inbound_numbers` rebound
    a few lines earlier in `publish_agent`. Leaving them bound would be a publish that
    silently ended a compliance silence while our own column still claimed it — the worst
    of the three outcomes, because it looks handled.

    ⚠ The outbound refusal is NOT ended here and cannot be: `record_drift` is the sole
    writer of the verdict the dial gate reads, and it is the sweep's. So a republished
    agent answers its phone again immediately and resumes DIALLING when the sweep next
    reaches it (`TRUTHFUL_ANSWER_VERDICT_TTL_S` bounds the wait). The asymmetry is in the
    safe direction and is deliberate: inbound is restored on evidence we hold in our hand,
    outbound on evidence only the sweep can produce.

    ═══ IT PRESERVES A CREDIT CUTOVER; IT NEVER STARTS ONE, AND THAT LINE IS THE DESIGN ═══

    An agent that is NOT already silenced is left alone here even when the wallet is empty.
    Starting a cutover is an EDGE — `reconcile_inbound_answering`, reached from the ledger's
    crossing of zero or the pipeline's backstop — and letting a publish start one would make
    an unrelated console action (a voice change, a cap change, a prompt rollback) silently
    change what a client's callers hear, decided by a money question its author never asked.
    That is the same class of surprise this function exists to prevent, pointing the other
    way. What it costs is bounded and stated: an agent published for an account that has
    been at zero all along keeps answering until the next edge — at most one metered call,
    which enqueues a reconciliation itself (`workers/pipeline.py`) — and no rupee is at risk
    meanwhile, because the meter refuses the debit either way.

    An agent coming OUT of a compliance silence into an empty wallet is not an exception to
    that: it WAS silenced on the way in, so landing it on the credit-stop script is
    preserving a silence rather than starting one, and the alternative would hand a client
    with no credit a fully working phone as a reward for republishing.

    A VENDOR FAILURE HERE DOES NOT FAIL THE PUBLISH, for `route_inbound_numbers`' reason:
    the agent itself is already published and verified, this is a separate engine fact, and
    raising would make an unrelated console action fail on an account that has merely run
    out of money. The stamp is not written, so the next reconciliation pass retries it.
    """
    # Imported at call time: `compliance.service` imports THIS module at import time, so a
    # module-level import here is a cycle. `workers/maintenance._restore_scripts` takes the
    # same escape for the same reason.
    from apps.api.compliance.service import credits_exhausted

    if not answers:
        # An outbound-only agent has no caller to hear anything. Clear any stamp it is
        # carrying — it answered inbound when it was silenced and does not now — so the
        # column never claims something about an agent nobody can ring.
        await _stamp_inbound_silence(session, agent_id=agent_id, reason=None)
        return
    # ONE READ, IN `_ANSWERING_AGENTS_SQL`'s OWN SHAPE. It used to be two — this scalar for
    # the stamp, and `_disclosure_posture_of` fetching the same row again further down —
    # which cost a round trip on every publish and, worse, carried a `row is None` arm that
    # the caller (holding the agent it has just published) can never reach. An unreachable
    # defensive branch on a zero-tolerance ratchet surface is a suppression waiting to
    # happen, and the honest fix is to stop fetching twice rather than to excuse the arm.
    # `.one()` because the row is guaranteed: absence here is a bug in the caller, not a
    # case to handle, and SQLAlchemy says so more clearly than a raise of ours would.
    row = (await session.execute(text(_ONE_ANSWERING_AGENT_SQL), {"aid": agent_id})).one()
    was_silenced = row[8] is not None
    reason = row[9]
    if reason == INBOUND_SILENCE_TRUTHFUL_ANSWER and not truthful_answer_proven:
        # PRESERVED — see the docstring. `publish_agent` has just rebound this agent's
        # numbers, so preserving means putting them back down rather than doing nothing.
        # If the vendor refuses, the numbers may be answering and the mirror must not go
        # on claiming otherwise: the stamp is cleared, `route_inbound_numbers` has already
        # alarmed per number, and the next sweep tick re-silences from a fresh verdict.
        routing = await route_inbound_numbers(
            session, engine, agent_id=agent_id, ref=ref, answers=False
        )
        if routing.failed:
            await _stamp_inbound_silence(session, agent_id=agent_id, reason=None)
        return
    if reason == INBOUND_SILENCE_HEALER:
        # A publish while the healer holds the line (a client's voice change, a prompt
        # rollback it proposed) has just put the ordinary script back; put the hold back.
        await _reapply_healer_silence(session, engine, tenant_id=tenant_id, agent_id=agent_id)
        return
    if not await credits_exhausted(session, tenant_id=tenant_id):
        # THE RESTORE, and it lands here rather than in the reconciler because THIS is the
        # publish that put the agent's own words back. Unconditional: clearing a stamp that
        # was already clear costs one indexed UPDATE and removes the branch where a
        # forgotten arm leaves a paid-up client's agent recorded as silent for ever.
        await _stamp_inbound_silence(session, agent_id=agent_id, reason=None)
        return
    if not was_silenced:
        return
    if not engine.capabilities.has("script_override"):
        return
    recorded = engine.capabilities.records_audio
    try:
        await engine.override_call_script(
            ref,
            opening_line=credit_stop_greeting(_posture_of_row(row), call_is_recorded=recorded),
            system_prompt=credit_stop_prompt(call_is_recorded=recorded),
        )
    except Exception as exc:
        alert(
            "CORE_LOGIC",
            "inbound_credit_cutover_failed",
            detail=(
                "an agent was republished for a client with no calling credit and the "
                "voice platform did not take the message that should replace its script, "
                "so it is back to taking calls this client cannot pay for. Refusal: "
                f"{exc.__class__.__name__}."
            ),
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
        )
        return
    await _stamp_inbound_silence(session, agent_id=agent_id, reason=INBOUND_SILENCE_CREDITS)


#: The job that deletes the vendor agent an agent was recreated FROM (D-693), after the
#: publish that recreated it committed (`apps/workers/engine_workspaces.py`).
RETIRE_MOVED_AGENT_JOB = "retire_moved_engine_agent"


async def _in_client_workspace(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    tenant_id: UUID,
    agent: AgentRow,
    config: AgentConfig,
    trial: bool = False,
) -> AgentConfig:
    """`config` with the client's own workspace, where a NEW vendor agent is made, and the
    voice as that workspace names it (one of our clones is its shared clone, D-797).
    Unchanged on an engine without customer
    workspaces. A tenant whose workspace is not active is refused: nothing of a client's is
    created in our developer workspace, except a FREE-TRIAL account's agent (D-697), which
    has no workspace until the account pays and calls from the shared trial number there.
    Its first publish after payment recreates it in the client's own workspace."""
    if not engine_has_workspaces(engine.name) or trial:
        return config
    workspace = await resolve_workspace(session, tenant_id)
    if workspace is None:
        raise workspace_not_provisioned()
    from apps.api.agents.shared_clones import voice_in_workspace

    return await voice_in_workspace(
        session,
        engine,
        catalogue_voice=agent.get("engine_voice_id"),
        config=config.model_copy(update={"engine_workspace": workspace}),
        workspace=workspace,
    )


async def _studio_in_client_workspace(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    tenant_id: UUID,
    rate_key: str,
    config: AgentConfig,
    trial: bool,
) -> None:
    """A Studio voice speaks on our Cartesia key, switched on in the workspace the agent lives
    in. Checked before the vendor write, because `PUT /agents/{id}/byok-voice` answers `409`
    in a workspace not on its own keys, and re-read live on every Studio publish. A paying
    client's workspace is switched on here, idempotently (D-717). A free-trial agent lives in
    our developer workspace (D-697), which the operator's Studio ready switches on (D-727); a
    trial publish only verifies it."""
    if rate_key != BYOK_VOICE_RATE_KEY or not isinstance(engine, HostsVoices):
        return
    if trial:
        from apps.api.agents.studio_voices import require_developer_studio

        await require_developer_studio(engine)
        return
    if config.engine_workspace is None:
        raise workspace_not_provisioned()
    from apps.api.agents.studio_voices import ensure_studio_in

    await ensure_studio_in(session, engine, tenant_id=tenant_id, workspace=config.engine_workspace)


def own_model_unpriced() -> ProblemError:
    return ProblemError(
        kind="business_rule",
        code="own_model_minute_unpriced",
        title="This voice has not been priced yet",
        detail="Calls on this voice with this account's language model have no price yet, so "
        "the agent was not published.",
        remediation="Choose another voice, or contact us.",
    )


async def _own_model_in_workspace(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    tenant_id: UUID,
    rate_key: EngineRateKey,
    config: AgentConfig,
) -> tuple[AgentConfig, EngineRateKey]:
    """An agent on OUR model (D-764) answers on our Google key in the workspace it lives in,
    checked before the vendor write, because the agent's `byok` scope is refused with `409`
    in a workspace without the key (bring-your-own-keys.md:92-97). A paying client's own
    workspace is switched on here and read back; our developer workspace, where a free-trial
    agent lives (D-697), is only verified (D-834), as a trial Studio publish verifies our
    Cartesia key there (D-727). Its rate key moves to the own-voice-and-model minute on a
    Studio voice, and must be attested (hard rule 7), a trial's minute too: the developer
    workspace's calls are billed to our balance at the plan's rate (ThinnestAI email, 18 Oct
    2026, item 3), so its cost is recorded like any other."""
    if config.engine_own_model is None:
        return config, rate_key
    if not isinstance(engine, HostsVoices):
        return config.model_copy(update={"engine_own_model": None}), rate_key
    refuse_unofferable_own_model(config.engine_own_model)
    own_rate = own_model_rate_key(rate_key)
    if own_rate != rate_key and own_rate not in await attested_rate_keys(
        session, engine=engine.name, at=datetime.now(UTC)
    ):
        raise own_model_unpriced()
    if config.engine_workspace is None:
        state = await require_developer_own_model(engine)
    else:
        state = await ensure_own_model_in(
            session, engine, tenant_id=tenant_id, workspace=config.engine_workspace
        )
    if own_rate != rate_key:
        # A Studio agent on our model names `llm_voice`, which the vendor refuses unless the
        # workspace holds BOTH keys verified (bring-your-own-keys.md:92-97). The Cartesia key
        # was switched on and read back just before (`_studio_in_client_workspace`); this
        # last read must still show it beside the Google key, so the agent write never names
        # a scope the workspace cannot run.
        from apps.api.agents.hosted_voices import own_voice_key_ready
        from apps.api.agents.studio_voices import studio_account_not_ready

        if not own_voice_key_ready(state):
            log.warning(
                "own_model_studio_voice_key_not_ready",
                extra={"tenant_id": str(tenant_id), "scope": state.scope},
            )
            raise studio_account_not_ready()
    return config, own_rate


def _moves_workspace(existing_ref: str | None, config: AgentConfig) -> bool:
    """Does the vendor agent behind `existing_ref` live outside the workspace `config` is for?
    An agent cannot move between workspaces, so it is recreated in the right one."""
    return (
        bool(existing_ref)
        and config.engine_workspace is not None
        and scope_of(existing_ref) != config.engine_workspace
    )


async def _after_workspace_move(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, old_ref: str
) -> None:
    """The agent now answers from its client's own workspace under a new vendor id. In the
    publish's transaction, before its knowledge converges:

    * the claims on the OLD agent's knowledge copies go — those copies are deleted with the
      old agent (`DELETE /agents/{id}` "takes the agent's knowledge with it", agents.md:82) —
      so the D-689 catch-up this publish runs attaches every live source to the new one. An
      experiment arm's claims are its own vendor agent's and go when that arm moves
      (`publish_variant`);
    * the old agent's deletion is owed through the outbox, so it runs only after this
      transaction commits. Its route stays active until then, so a late delivery for a call
      it took before the move still verifies; the retire job switches it off.
    """
    await session.execute(
        text(
            "DELETE FROM engine_kb_routes WHERE agent_id = :aid AND tenant_id = :tid "
            "AND variant_id IS NULL"
        ),
        {"aid": agent_id, "tid": tenant_id},
    )
    log.warning("engine_agent_moved_to_client_workspace", extra={"agent_id": str(agent_id)})
    if scope_of(old_ref) is None and not await _has_any_number(session, agent_id=agent_id):
        # FOUNDER OPTION A (D-859): the developer-workspace copy stays, so the owner's test
        # calls can ring through the shared trial line until the client has its own number;
        # its route stays active so those calls report back. The hourly sweep retires it
        # once the client has a number or it sits unused (`workers/agent_moves`).
        await _record_test_copy(session, None, tenant_id=tenant_id, agent_id=agent_id, ref=old_ref)
        return
    await retire_engine_agent(session, tenant_id=tenant_id, agent_id=agent_id, ref=old_ref)


async def retire_engine_agent(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, ref: str
) -> None:
    """Owe the deletion of a vendor agent this agent no longer answers through, after the
    caller's transaction commits (`workers/engine_workspaces.retire_moved_engine_agent`, which
    waits out a live call). Keyed by the handle, so owing it twice queues it once."""
    from apps.api.reliability.service import enqueue_outbox_once

    await enqueue_outbox_once(
        session,
        job=RETIRE_MOVED_AGENT_JOB,
        payload={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "old_ref": ref},
        dedupe_key=f"retire-engine-agent:{ref}",
    )


async def _has_any_number(session: AsyncSession, *, agent_id: UUID) -> bool:
    """Is any number of the client's attached to this agent, in any workspace?"""
    return bool(
        (
            await session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM phone_numbers WHERE agent_id = :aid "
                    "AND released_at IS NULL)"
                ),
                {"aid": agent_id},
            )
        ).scalar()
    )


async def test_copy_ref(session: AsyncSession, agent_id: UUID) -> str | None:
    """The agent's developer-workspace test copy (D-859, option A), if it has one."""
    value = (
        await session.execute(
            text("SELECT engine_agent_ref FROM agent_test_copies WHERE agent_id = :aid"),
            {"aid": agent_id},
        )
    ).scalar()
    return None if value is None else str(value)


def _vendor_says_gone(exc: BaseException) -> bool:
    """The vendor no longer holds the agent written to (a 404, or our not-found)."""
    if isinstance(exc, EngineRejectedError):
        return exc.vendor_status == 404
    return isinstance(exc, ProblemError) and exc.kind == "not_found"


async def _record_test_copy(
    session: AsyncSession,
    engine: VoiceEngine | None,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    ref: str,
) -> None:
    """Record `ref` as the agent's test copy, with its active route; a copy it held under
    another handle is retired. `engine` names the route's engine (the active one if None)."""
    previous = await test_copy_ref(session, agent_id)
    await session.execute(
        text(
            "INSERT INTO agent_test_copies (id, tenant_id, agent_id, engine_agent_ref) "
            "VALUES (:id, :tid, :aid, :ref) ON CONFLICT (agent_id) DO UPDATE SET "
            "engine_agent_ref = EXCLUDED.engine_agent_ref, updated_at = now()"
        ),
        {"id": uuid7(), "tid": tenant_id, "aid": agent_id, "ref": ref},
    )
    await session.execute(
        text(
            "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
            "active, created_at, updated_at) VALUES (:engine, :ref, :tid, :aid, true, now(), "
            "now()) ON CONFLICT (engine, engine_agent_ref) DO UPDATE SET "
            "tenant_id = EXCLUDED.tenant_id, agent_id = EXCLUDED.agent_id, active = true, "
            "updated_at = now()"
        ),
        {"engine": (engine or get_engine()).name, "ref": ref, "tid": tenant_id, "aid": agent_id},
    )
    if previous is not None and previous != ref:
        await retire_engine_agent(session, tenant_id=tenant_id, agent_id=agent_id, ref=previous)


async def retire_developer_workspace_agents(session: AsyncSession, *, tenant_id: UUID) -> int:
    """Owe the deletion of every agent this closing account still has in OUR developer
    workspace (D-697): a free-trial account's agents, and any made before D-693. The
    account's own workspace is offboarded whole (`queue_workspace_offboarding`); these are
    not in it, so without this they would stay at the vendor. Through the same outbox job a
    move uses, which waits while a call is connected. In the caller's transaction."""
    if not engine_has_workspaces():
        return 0
    from apps.api.reliability.service import enqueue_outbox

    routes = (
        await session.execute(
            text(
                "SELECT engine_agent_ref, agent_id FROM engine_agent_routes "
                "WHERE tenant_id = :tid AND engine = :engine AND active ORDER BY engine_agent_ref"
            ),
            {"tid": tenant_id, "engine": get_engine().name},
        )
    ).all()
    owed = 0
    for ref, agent_id in routes:
        if scope_of(str(ref)) is not None:
            continue
        await enqueue_outbox(
            session,
            job=RETIRE_MOVED_AGENT_JOB,
            payload={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "old_ref": str(ref)},
        )
        owed += 1
    return owed


async def _resync_agent_numbers(session: AsyncSession, *, agent_id: UUID) -> None:
    """Point every number bound to a recreated agent at its new vendor id. A number in the
    agent's new workspace now answers it; a number left in the platform account cannot."""
    from apps.api.campaigns.engine_numbers import sync_number_attachment

    numbers = (
        await session.execute(
            text(
                "SELECT id FROM phone_numbers WHERE agent_id = :aid AND released_at IS NULL "
                "ORDER BY created_at, id"
            ),
            {"aid": agent_id},
        )
    ).scalars()
    for number_id in list(numbers):
        await sync_number_attachment(session, number_id=UUID(str(number_id)))


#: The publish refusal while another transaction is changing the tenant's knowledge.
KNOWLEDGE_PUBLISH_IN_PROGRESS: Final = "kb_publish_in_progress"


async def _hold_tenant_knowledge(session: AsyncSession, *, tenant_id: UUID) -> None:
    """Take the tenant's knowledge lock BEFORE `_load_agent` locks the agent row.

    LOCK ORDER IS TENANT KNOWLEDGE, THEN AGENTS. A knowledge publish holds
    `kb/service.lock_tenant_knowledge` and then writes every agent row (`recompile_t0`, the
    pack refresh); a publish that locked its agent row first and then waited for the tenant
    lock (`engine_facts.sync_business_facts`) closed a cycle, PostgreSQL aborted one side
    with 40P01, and nothing retried it — an aborted knowledge publish leaves the vendor
    holding copies our rows do not record.

    TRY, NOT WAIT: a caller that already wrote the agent row in this transaction (the
    settings writers in `agents/publishing.py`) would otherwise still wait while holding
    the row. The lock is re-entrant, so a caller that took it first — `agents/lifecycle`'s
    movers, a knowledge publish republishing its agents — passes straight through; any
    other caller meeting a publish in flight is refused as retryable, and its rollback
    releases the row the publish needs.
    """
    # Imported here: `kb.service` imports `agents.t0`, which imports this module.
    from apps.api.kb.service import try_lock_tenant_knowledge

    if await try_lock_tenant_knowledge(session, tenant_id=tenant_id):
        return
    raise ProblemError.conflict(
        KNOWLEDGE_PUBLISH_IN_PROGRESS,
        "This account's knowledge is being updated on the voice platform right now.",
        remediation="Try again in a minute, once the update has finished.",
    )


async def publish_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    take_calls: bool = True,
    onto_test_copy: bool = False,
) -> str:
    """Create or update the agent on the engine, VERIFY it, then record the mapping.

    `take_calls=False` is "Ready, not taking calls" (D-838): the agent is published and read
    back like any other, so the Try it chat talks to it, but its status is left as it is, no
    number is bound to it and the go-live checks are not asked. An agent already live is
    republished as live whatever this says, so no caller can unbind a working line with it.

    `onto_test_copy=True` (D-859, founder option A) publishes the same config onto the
    agent's TEST COPY in our developer workspace instead (`agent_test_copies`), made again if
    it is gone: the engine agent a paying client's test call rings through on the shared trial
    line before the client has a number. The agent's own row, numbers, status and arms are not
    touched; the copy gets its route, results webhook, facts document and in-call actions.
    Knowledge documents are converged on the agent's own engine agent only
    (`engine_facts.sync_business_facts`), so the copy keeps those it held when it moved.

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
    `set_call_cap`, `apply_to_live` or `lifecycle.update_agent` republish, all of which reach
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
    await _hold_tenant_knowledge(session, tenant_id=tenant_id)

    # AND THE PLATFORM MUST NOT BE IN A MAINTENANCE WINDOW (D-544).
    #
    # ═══ WHY IT IS HERE, IN THE ONE FUNCTION, AND NOT ON THE PUBLISH ROUTE ═══
    #
    # Eleven call sites reach this function and not one of them is only "publish": a call
    # cap change, a voice change, a disclosure toggle, a T0 recompile, a prompt rollback,
    # a script apply, `activate_agent`, `update_agent`, the LLM default writer and the ops
    # intake flow all republish the agent as their last act, because that is how a column
    # becomes a fact at the vendor. They therefore all do the SAME THING to the engine, and
    # during a window that thing is destructive in a way none of their authors could see:
    # `workers/maintenance._speak_maintenance` has replaced this agent's greeting and prompt
    # with the maintenance message, and a publish overwrites them with the agent's real
    # script. The result is one client's callers quietly getting ordinary service — booking
    # appointments, being promised call-backs — over a platform whose database is being
    # worked on, with every screen reporting the window as active.
    #
    # So the refusal belongs where the engine write is, which is here. A route-level guard
    # would have covered one of the eleven.
    #
    # ═══ WHICH STATES REFUSE, AND WHICH DELIBERATELY DO NOT ═══
    #
    # `draining` and `active` refuse; `scheduled` does not. During `scheduled` the platform
    # is running normally, nothing has been overridden, and there is nothing for a publish
    # to damage — refusing then would take the console away from clients for the whole
    # notice period, which is not maintenance, it is a longer outage.
    #
    # `accepting_new_work` is the predicate rather than the load-shed mode, for the reason
    # the dial gate gives: the two-state model means DRAINING refuses while `mode` is still
    # `normal`, and reading the mode here would leave the whole drain unguarded — which is
    # precisely the interval `_speak_maintenance` runs in.
    #
    # ═══ AND THE WINDOW'S OWN RESTORE IS NOT CAUGHT BY THIS ═══
    #
    # `workers/maintenance._restore_scripts` republishes every live agent through this
    # function at the END of a window — and by then `complete_window` has committed, so no
    # window is open and `accepting_new_work` is true. That is guaranteed by ordering rather
    # than by an exemption (`_complete` transitions first, restores second), which is the
    # safer of the two: an exemption would be a hole somebody could later widen.
    #
    # READ ON THE CALLER'S SESSION, AND NOT THROUGH `get_platform_status`. The cached
    # status carries the same three facts and reaching for it here was the first attempt;
    # `scripts/check_session_nesting` refused it, correctly. That read falls through to
    # `untenanted_session`, and three of this function's callers are already two sessions
    # deep (`set_disclosure_posture`, `set_caller_memory`, `apply_to_live` — each a route
    # holding `Depends(db)`), so a third connection puts the whole chain past the pool's
    # overflow: under saturation every task at that depth waits for a connection only
    # another task at that depth can release.
    #
    # `platform_maintenance_windows` carries no RLS (it is platform state — see
    # `db/registry.RLS_EXEMPT_TENANT_COLUMNS`), so the tenant session already in hand can
    # read it. One query on an open connection, never stale, and no new connection at all —
    # the same argument `ops/service.read_halt_state` makes for reading the halt on the
    # caller's session rather than through the hot-path cache.
    window = await read_open_window(session)
    if window is not None and window.state in ("draining", "active"):
        raise ProblemError(
            kind="business_rule",
            code="platform_maintenance",
            title="Calevate is in a maintenance window",
            # THE OPERATOR'S OWN SENTENCE AND THE WINDOW'S OWN END, never a generic error:
            # this is read by a client who pressed Publish, and "try again later" with no
            # later in it is the refusal that generates a support call.
            detail=(
                f"{window.reason} Publishing an agent changes what it says to callers, so "
                f"it has to wait until the window closes (about "
                f"{window.ends_at.astimezone(UTC) + IST:%H:%M} IST). Nothing you have "
                "saved is lost — your changes are still here and will publish afterwards. "
                "Your agents keep answering calls throughout."
            ),
            status=409,
            remediation="Publish again once the maintenance window has finished.",
        )

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

    # AND THE CLIENT MUST HAVE AGREED TO SOMETHING. Publishing puts an agent on the phone:
    # it starts recording this client's callers, collecting their numbers and extracting
    # their details, and the document that makes us their processor for any of it is the
    # DPA nobody had ever been asked to accept.
    #
    # AFTER `_load_agent`, NOT BESIDE `assert_account_open`, AND THE PLACEMENT IS THE
    # POINT. This ran first, on the reasoning that an account-level fact is cheapest to ask
    # early — which is true of `assert_account_open`, whose refusals (`account_closed`,
    # `tenant_erased`) an operator holding a hand-typed uuid can already read off the admin
    # console. It is NOT true of this one. `_load_agent` is where existence and OWNERSHIP
    # are decided, and it answers 404 for an agent belonging to a tenant the caller cannot
    # see; asking the agreements question in front of it made that path answer 409
    # `agreements_not_accepted` instead — which confirms the tenant exists AND discloses
    # the state of its paperwork, to a caller who was supposed to learn neither.
    # `tests/onboarding_to_live_test.py::test_a_promptless_agent_of_another_tenant_is_
    # absent_rather_than_refused` is the assertion that named it. Same ordering
    # `campaigns/provisioning.py` argues for KYC-behind-capability, and the same reason
    # `admin.service.assert_agent_visible` exists at all.
    #
    # Nothing is given up by the move: it is still one indexed read, still inside the same
    # transaction, and still BEFORE the vendor — so a refusal here leaves no agent at the
    # engine with nothing pointing at it, which was the property the early placement was
    # actually protecting.
    #
    # Raises rather than returning a blocker because this is a single action with a single
    # answer; the campaign gates return `agreements_not_accepted` as a to-do row under the
    # same rule name from the same implementation.
    await assert_agreements_accepted(session, tenant_id=tenant_id)
    # A FREE-TRIAL ACCOUNT'S AGENT PLACES TEST CALLS AND ANSWERS NOTHING (D-697): it has no
    # number until it pays, so an answer-only agent is refused with the step that unlocks it.
    trial_account = await restricting_trial(session, tenant_id=tenant_id) is not None
    # A trial's agent and a paying client's test copy are made in our developer workspace.
    in_developer = trial_account or onto_test_copy
    takes_calls = (take_calls or agent["status"] == "live") and not onto_test_copy
    if trial_account and takes_calls and agent["direction"] == "inbound":
        await refuse_on_trial(session, tenant_id=tenant_id, locked="inbound")

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
        raise archived_refusal("published")
    # GOING LIVE NEEDS THE BUSINESS'S FACTS (D-695): hours for after-hours handling, an
    # address, a service and someone to hand a caller to. Asked only on the transition to
    # live, so a profile edit can never knock a working agent off the phone on its next
    # re-publish.
    if takes_calls and agent["status"] != "live":
        await assert_ready_to_go_live(
            session,
            tenant_id=tenant_id,
            needs_contact=bool(agent["handoff_enabled"])
            or agent_answers_inbound(agent["direction"]),
        )
    # WHO TAKES A CALL THIS AGENT HANDS OVER, right now (D-533). Resolved BEFORE the
    # config is built rather than patched on afterwards like the action tools, because
    # `None` is a real answer here — outside every roster member's hours the agent is
    # published with no transfer tool at all, which is the only place "never transfer
    # outside business hours" can be enforced (see `agents/handoff.py`).
    handoff, duty = await handoff_module.spec_for(session, dict(agent))
    if duty.member is None and agent["handoff_enabled"]:
        # NOT A REFUSAL. An agent whose roster is closed for the night is a correctly
        # configured agent, and refusing its publish would make a 9pm republish impossible
        # for every client who has this feature on. It is logged so the reason a live agent
        # is not escalating is answerable without opening a screen — ids and OUR own reason
        # code, never the number (hard rule 6).
        log.info(
            "agent_publish_handoff_unavailable",
            extra={"agent_id": str(agent_id), "reason": duty.reason},
        )
    # A staged language (D-855) reaches a caller only once clients may choose it.
    refuse_unoffered_language(str(agent["language_primary"]), tenant_id=tenant_id)
    config = _to_config(tenant_id, agent, engine=engine, handoff=handoff)
    # The ACTIONS feature: attach this agent's during-call tools to the config the adapter
    # renders, so publish is where a tool change reaches live calls (the "Apply to live
    # calls" action, same mechanism as a voice or cap change). Empty tuple when the master
    # switch is off or no during-call tool is enabled, in which case the adapter emits no
    # `api_tools` at all. Imported here rather than at module top to keep the actions
    # package off the agents-service import path except where publish actually needs it.
    from apps.api.actions import service as actions_service

    config = config.model_copy(
        update={
            "action_tools": await actions_service.declare(
                session, agent_id=agent_id, direction=agent["direction"]
            )
        }
    )

    # Before the vendor write: an engine whose fields cannot hold this agent as composed
    # refuses here rather than truncating (see `agents/engine_limits.py`). A no-op on an
    # engine that declares no limits.
    refuse_over_engine_limits(engine, config)
    await refuse_unpriced_engine(session, engine)
    voice_choice, model_choice = _engine_choice(agent, engine=engine)
    rate_key = await engine_rate_key_for(
        session, engine, voice_id=voice_choice, model_id=model_choice
    )

    config = await _in_client_workspace(
        session, engine, tenant_id=tenant_id, agent=agent, config=config, trial=in_developer
    )
    await _studio_in_client_workspace(
        session, engine, tenant_id=tenant_id, rate_key=rate_key, config=config, trial=in_developer
    )
    config, rate_key = await _own_model_in_workspace(
        session, engine, tenant_id=tenant_id, rate_key=rate_key, config=config
    )
    existing_ref = (
        await test_copy_ref(session, agent_id) if onto_test_copy else agent["engine_agent_ref"]
    )
    # AN AGENT MADE IN OUR DEVELOPER WORKSPACE BEFORE D-693 is recreated in its client's own
    # workspace on this publish, under a new vendor id. The old one keeps answering until
    # this transaction commits, and is deleted only after (`_after_workspace_move`).
    moved_from: str | None = None
    if isinstance(existing_ref, str) and _moves_workspace(existing_ref, config):
        moved_from, existing_ref = existing_ref, None
    created = not (isinstance(existing_ref, str) and existing_ref)
    if isinstance(existing_ref, str) and existing_ref:
        try:
            await engine.update_agent(existing_ref, config)
            ref = existing_ref
        except Exception as gone:
            # A test copy deleted at the vendor (by hand, or retired while idle) is made
            # again; anything else, and any other agent, is the publish's failure.
            if not (onto_test_copy and _vendor_says_gone(gone)):
                raise
            created = True
            with trial_agent_in_developer_workspace():
                ref = await engine.create_agent(config)
    elif in_developer:
        with trial_agent_in_developer_workspace():
            ref = await engine.create_agent(config)
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
                "handoff_applied": verdict.handoff_applied,
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

    # From here on a failure rolls back every row that names `ref`, so a vendor agent this
    # publish created is reclaimed by the handler at the end of this block.
    try:
        if onto_test_copy:
            await _record_test_copy(
                session, engine, tenant_id=tenant_id, agent_id=agent_id, ref=ref
            )
            await _ensure_results_webhook(
                engine,
                ref=ref,
                agent_id=agent_id,
                reclaim=False,
                session=session,
                rate_key=rate_key,
                own_model=config.engine_own_model,
            )
            await _publish_business_facts(
                engine, session, agent_id=agent_id, ref=ref, reclaim=False, script=agent["prompt"]
            )
            await _ensure_in_call_actions(
                engine, session, agent_id=agent_id, ref=ref, reclaim=False
            )
            log.info("agent_test_copy_published", extra={"agent_id": str(agent_id)})
            return ref
        result = await session.execute(
            text(
                (
                    "UPDATE agents SET engine_agent_ref = :ref, engine = :engine, status = 'live', "
                    if takes_calls
                    else "UPDATE agents SET engine_agent_ref = :ref, engine = :engine, "
                )
                + "live_tts_voice = :live_voice, live_tts_provider = :live_provider, "
                "live_verify_state = :verify_state, live_verified_at = :verified_at, "
                # What each call will run on, for the reply-time split (D-896).
                "voice_settings = CAST(:voice_settings AS jsonb), "
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
                # re-read here would record whatever a concurrent voice write
                # committed in between — a mirror that claims the engine holds a voice it
                # was never sent. Written inside the same transaction as `engine_agent_ref`
                # and after the vendor call, so a vendor failure rolls the mirror back with
                # it and our row never over-promises (the `kb.publish_source` ordering).
                # RECOMPOSED FROM THE CONFIG, not re-read from the row and not the bare
                # speaker. `ModelConfig` carries the SPLIT pair the vendor's two keys take;
                # this column, `agents.tts_voice` and `publishing.py::voice_diverged` are all
                # written in catalogue IDs, so recording `config.models.tts_voice` alone here
                # would record the bare speaker against a configured `<model>:<speaker>` and report
                # every published agent as permanently diverged.
                "live_voice": voice_id_of(config.models.tts_model, config.models.tts_voice),
                "live_provider": config.models.tts_provider,
                "voice_settings": json.dumps(stamp_of(config, engine)),
                "verify_state": verdict.stored_state,
                # NULL unless something was actually proven. A timestamp on an `unreachable`
                # would let a screen render "confirmed just now" over an answer nobody read.
                "verified_at": datetime.now(UTC) if verdict.proven else None,
            },
        )
        if rowcount_of(result) == 0:
            raise ProblemError.conflict(
                "agent_deleted_during_publish",
                "This agent was deleted or archived while it was being published.",
                remediation=(
                    "Nothing was recorded as live. Restore the agent, or recreate it if it is "
                    "still needed."
                ),
            )
        # D-836: its own call outcomes, drafted once, queued in this transaction so a failed
        # publish queues nothing. A no-op for an agent that has them or was drafted before.
        await call_outcomes.queue_draft(session, tenant_id=tenant_id, agent_id=agent_id)
        # D-889: the first look at whether its lead details fit the business, once.
        await field_suggestions.queue_first_pass(session, tenant_id=tenant_id, agent_id=agent_id)
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
        if moved_from is not None:
            await _after_workspace_move(
                session, tenant_id=tenant_id, agent_id=agent_id, old_ref=moved_from
            )
        await _ensure_results_webhook(
            engine,
            ref=ref,
            agent_id=agent_id,
            reclaim=False,
            session=session,
            rate_key=rate_key,
            own_model=config.engine_own_model,
        )
        await _publish_business_facts(
            engine, session, agent_id=agent_id, ref=ref, reclaim=False, script=agent["prompt"]
        )
        await _ensure_in_call_actions(
            engine,
            session,
            agent_id=agent_id,
            ref=ref,
            reclaim=False,
        )
        if moved_from is not None:
            await _resync_agent_numbers(session, agent_id=agent_id)
        # THE INBOUND HALF OF PUBLISHING (D-420). Publishing is "make the engine hold what our
        # database says", and until now that covered the agent and stopped short of the one
        # fact that decides whether a client's number rings anything at all. It runs AFTER the
        # routing row so the two engine-side facts about this agent — who it is, and which
        # numbers it answers — are written in one transaction's worth of intent; it cannot fail
        # the publish (see the function) because the agent itself is already verified live.
        answers_inbound = takes_calls and agent_answers_inbound(agent["direction"])
        routing = await route_inbound_numbers(
            session, engine, agent_id=agent_id, ref=ref, answers=answers_inbound
        )
        await _warn_if_answering_nothing(
            session, agent_id=agent_id, answers_inbound=answers_inbound, routing=routing
        )
        # AND THE LAST WORD ON WHAT IT SAYS, AND ON WHETHER IT SAYS ANYTHING AT ALL (8 Sep
        # 2026; D-564). A publish writes the agent's REAL script and rebinds its numbers,
        # which for a client whose calling credit has run out — or for an agent the drift
        # sweep has proven cannot tell a caller it is an AI — is an undo of a cutover
        # performed by whichever of this function's thirteen callers happened to run. See
        # `_settle_inbound_silence` for why the re-application belongs here and not in the
        # reconcilers alone. AFTER `route_inbound_numbers`, because an agent that is not bound
        # to a number has nothing to be silent on.
        await _settle_inbound_silence(
            session,
            engine,
            tenant_id=tenant_id,
            agent_id=agent_id,
            ref=ref,
            answers=answers_inbound,
            # THE ONLY TRUE THIS ARGUMENT EVER TAKES (D-564), and it is the read-back's own
            # word rather than an inference from "the publish did not raise". `publish_agent`
            # refuses only `not_applied`; `unreadable` and `unreachable` reach this line
            # having proven nothing, and a compliance silence must outlive a publish that
            # proved nothing.
            truthful_answer_proven=verdict.truthful_answer_applied is True,
        )
        await republish_running_variants(session, tenant_id=tenant_id, agent_id=agent_id)
    except Exception as exc:
        # One handler for every step after the create: the three engine seams are called
        # with `reclaim=False` so the agent is deleted once, and the steps after them (the
        # arms' republish, the number resync) and the database writes are covered too.
        if created:
            reason = exc.code if isinstance(exc, ProblemError) else type(exc).__name__
            await _reclaim_orphan(engine, agent_id, ref, reason)
        raise
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


def _steps_for(
    engine: VoiceEngine, agent: AgentRow, body: str, *, handoff: HandoffSpec | None
) -> tuple[tuple[NativeStep, ...], str]:
    """The script's stages as the engine's own steps, and the body without the same outline.

    Only on an engine with a native step list (ThinnestAI, `HostedAgentLimits.native_steps`)
    and only for a structured script whose stages fit it; anything else keeps its outline in
    the instructions and sends no steps, so the model never reads the outline twice.
    """
    structured = agent.get("structured_script")
    if not hosted_agent_limits(engine).native_steps or not structured:
        return (), body
    try:
        script = CallScript.model_validate(structured)
    except ValidationError:
        log.warning("structured_script_unreadable", extra={"agent_id": str(agent["id"])})
        return (), body
    # A "hand over" or "call back" branch becomes what this account can do right now.
    can = Capabilities(
        call_backs=bool(agent.get("callbacks_offered", True)) and not call_backs_withheld(body),
        hand_over=handoff is not None,
    )
    steps = native_steps(script, can=can)
    return (steps, without_outline(body)) if steps else ((), body)


def _script_for(engine: VoiceEngine, body: str) -> str:
    """The script as `engine` holds it: without the [T0 FACTS] block where the engine keeps
    the business facts in its knowledge base (`agents/engine_facts.py`), unchanged otherwise."""
    return without_block(body) if hosted_agent_limits(engine).facts_in_knowledge else body


def _engine_choice(agent: AgentRow, *, engine: VoiceEngine) -> tuple[str | None, str | None]:
    """The engine-catalogue voice and model, each only on a leg the engine dictates.

    On a leg that is ours the engine takes our catalogue's ids (`_model_legs`), so a stored
    engine-catalogue id is not sent there: it would name a voice or model in the wrong
    vocabulary. `.get` because test fixtures build partial rows.
    """
    if byok_in_force(engine):
        # The workspace's own keys run every leg; a stored catalogue choice is kept on the
        # row and not sent (`Settings.thinnest_byok_enabled`).
        return None, None
    caps = engine.capabilities
    model = None if caps.is_ours("llm") else agent.get("engine_model_id")
    # A choice of OUR model (`byok:<id>`, D-764) is not one of the engine's models.
    if own_model_of_choice(model) is not None:
        model = None
    return (None if caps.is_ours("tts") else agent.get("engine_voice_id"), model)


@dataclass(frozen=True, slots=True)
class _EngineVoiceFields:
    voice_id: str | None = None
    byok_voice_id: str | None = None
    own_voice_key: bool | None = None
    model_id: str | None = None
    own_model: str | None = None


def _engine_voice_fields(agent: AgentRow, *, engine: VoiceEngine) -> _EngineVoiceFields:
    """The `AgentConfig` fields for the engine-hosted voice and model (D-687).

    The stored voice is OUR catalogue id (`agents/hosted_voices.py`); what the engine is
    sent is its own voice id, in the slot its source takes — an engine voice as the agent's
    voice, a voice of our own key through the own-key voice route — and whether the agent
    speaks on our own voice key at all (D-688). That switch is stated for EVERY agent on an
    engine whose voice leg it dictates, not only for Studio ones: with the workspace on
    voice-only BYOK, an agent that left it unsaid would speak Cartesia at the Studio rate.
    Not sent while the whole workspace runs on its own keys (`byok_in_force`), where no
    per-agent voice applies. An id that is not a hosted one is sent as nothing; publish
    refuses it first (`engine_choice.require_engine_choice`).
    """
    voice, model = _engine_choice(agent, engine=engine)
    # An agent that chose no model is sent the console's in-call default, so a change of
    # default reaches each agent at its next publish and never mid-call. Checked when the
    # setting is written (`engine_choice.assert_in_call_default_usable`), not here: the
    # per-agent price ground does not apply to a model included in the voice band's minute.
    model = model or in_call_default_model(engine, voice_id=voice)
    ref = parse_hosted_voice_id(voice)
    states_key = not (byok_in_force(engine) or engine.capabilities.is_ours("tts"))
    own_voice_key = (ref is not None and ref.source == "byok") if states_key else None
    # OUR model (D-764): the agent's own choice of a Google model, else the console default.
    # A free-trial agent gets it too (D-834): its publish verifies our developer workspace.
    own_model = (
        own_model_for(agent.get("engine_model_id")) if states_key and own_model_on(engine) else None
    )
    if ref is None:
        return _EngineVoiceFields(own_voice_key=own_voice_key, model_id=model, own_model=own_model)
    return _EngineVoiceFields(
        voice_id=ref.vendor_id if ref.source == "engine" else None,
        byok_voice_id=ref.vendor_id if ref.source == "byok" else None,
        own_voice_key=own_voice_key,
        model_id=model,
        own_model=own_model,
    )


def in_call_model(agent: AgentRow, *, engine: VoiceEngine) -> str | None:
    """The language model a publish puts this agent on: our own model (D-764), else the
    engine model it chose or the console's in-call default; None is the engine's own
    default. The test loop reads it to judge with a model of another family."""
    fields = _engine_voice_fields(agent, engine=engine)
    return fields.own_model or fields.model_id


def _arm_script(agent: AgentRow, body: str) -> str:
    """An experiment arm's script: its own frozen body carrying the pinned facts and the
    [T0 FACTS] block of the agent's applied version, which every knowledge change recompiles
    (D-689, D-806). An arm is republished whenever its agent is (`republish_running_variants`),
    so it carries what the agent carries."""
    return with_knowledge_of(agent["prompt"], body, identity=f"{agent['name']}.")


def _variant_config(
    tenant_id: UUID,
    agent: AgentRow,
    variant_id: UUID,
    label: str,
    body: str,
    disclosure: str,
    *,
    engine: VoiceEngine,
    handoff: HandoffSpec | None = None,
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
    it names. No adapter reads this field to correlate anything back to us —
    `fake.py` derives its deterministic ref from it — so
    passing the agent's id would give the fake ONE ref for both arms and silently publish
    the second script over the first. The bridge back to the real agent is
    `engine_agent_routes`, which is written below and is the only mapping any inbound
    path consults.

    The script is the arm's with the client's knowledge sections taken from the agent
    (`_arm_script`), so a fact pinned or published while the test runs reaches the arms.
    """
    arm = _to_config(tenant_id, agent, engine=engine, handoff=handoff).model_copy(
        update={
            "agent_id": str(variant_id),
            "name": f"{agent['name']} [variant {label}]",
            "system_prompt": _script_for(engine, _arm_script(agent, body)),
            # The arm's body keeps its own outline; the agent's steps are not the arm's.
            "script_steps": (),
            # THE ARM'S OWN AI SENTENCE, THROUGH THE AGENT'S OWN TOGGLES (D-163). A
            # variant carries its own `disclosure_line` (NOT NULL, non-empty) because an
            # A/B test of a script legitimately tests its opening; the arm's opening line
            # comes from its own script body above (D-708). The POSTURE — whether
            # either notice is volunteered at all — is a property of the agent and is not
            # forked per arm. Recomposing here rather than substituting the raw sentence
            # is what makes a toggle flip reach the arms: `republish_running_variants`
            # rebuilds every arm from the agent, so an arm cannot go on greeting callers
            # with a notice its agent has withdrawn.
            # ONE FIELD SWAPPED ON THE AGENT'S OWN POSTURE, not a second construction of
            # it. This used to re-list every field by hand, which is precisely the drift
            # `posture_of` was written to prevent — and it proved the point: a third
            # sentence added to the posture (D-507) would have reached the agent and not
            # its experiment arms, so an arm would greet callers without saying the agent
            # remembers them while the agent said it.
            **notice_fields(
                posture_of(agent).model_copy(update={"ai_disclosure_line": disclosure}),
                call_is_recorded=engine.capabilities.records_audio,
            ),
        }
    )
    # The arm's own body replaced the agent's above, so its known facts are spliced again:
    # an arm carries the client's knowledge like the agent (D-689).
    return hot_facts.with_known_facts(arm, agent.get("hot_facts") or (), engine)


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
    # AN ARM ESCALATES TO THE SAME PEOPLE AS ITS AGENT (D-533). Resolved through the one
    # resolver rather than left to default to None, and the reason is the same one
    # `_variant_config` is built on `_to_config` at all: an arm that differs from its agent
    # in a field nobody listed is a confound the experiment cannot survive — and here the
    # confound would be that half the callers who ask for a person get one.
    handoff, _duty = await handoff_module.spec_for(session, dict(agent))
    refuse_unoffered_language(str(agent["language_primary"]), tenant_id=tenant_id)
    config = _variant_config(
        tenant_id,
        agent,
        variant_id,
        label,
        body,
        disclosure_line,
        engine=engine,
        handoff=handoff,
    )
    # An arm's script lands in the same engine fields as its agent's, so it fits the same
    # ceilings or is refused before the write (`agents/engine_limits.py`).
    refuse_over_engine_limits(engine, config)
    await refuse_unpriced_engine(session, engine)
    voice_choice, model_choice = _engine_choice(agent, engine=engine)
    rate_key = await engine_rate_key_for(
        session, engine, voice_id=voice_choice, model_id=model_choice
    )
    config = await _in_client_workspace(
        session, engine, tenant_id=tenant_id, agent=agent, config=config
    )
    await _studio_in_client_workspace(
        session, engine, tenant_id=tenant_id, rate_key=rate_key, config=config, trial=False
    )
    config, rate_key = await _own_model_in_workspace(
        session, engine, tenant_id=tenant_id, rate_key=rate_key, config=config
    )
    # An arm made in our developer workspace is recreated in the client's own, as its agent
    # is (D-693); the old arm is deleted after this transaction commits.
    moved_from: str | None = None
    if existing_ref and _moves_workspace(existing_ref, config):
        moved_from, existing_ref = existing_ref, None
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
    if moved_from is not None:
        from apps.api.reliability.service import enqueue_outbox

        # The old arm's knowledge copies go with it (`_after_workspace_move`), so the
        # catch-up below attaches every live source to the new one.
        await session.execute(
            text("DELETE FROM engine_kb_routes WHERE variant_id = :vid AND tenant_id = :tid"),
            {"vid": variant_id, "tid": tenant_id},
        )
        await enqueue_outbox(
            session,
            job=RETIRE_MOVED_AGENT_JOB,
            payload={
                "tenant_id": str(tenant_id),
                "agent_id": str(agent_id),
                "old_ref": moved_from,
            },
        )
    # An arm is its own vendor agent and its calls report through their own endpoint.
    await _ensure_results_webhook(
        engine,
        ref=ref,
        agent_id=agent_id,
        reclaim=not existing_ref,
        session=session,
        rate_key=rate_key,
        own_model=config.engine_own_model,
    )
    # The arm's own vendor agent holds the client's facts and published knowledge.
    await _publish_business_facts(
        engine,
        session,
        agent_id=agent_id,
        ref=ref,
        reclaim=not existing_ref,
        script=_arm_script(agent, body),
        variant_id=variant_id,
    )
    await _ensure_in_call_actions(
        engine,
        session,
        agent_id=agent_id,
        ref=ref,
        reclaim=not existing_ref,
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


#: The numbers an agent can place calls from: bound to it and, when the engine presents only
#: numbers it holds (`:carrier` set), held there and set up for outgoing calls. A caller id
#: the dialling account does not hold is one it cannot present, and a number bought for
#: inbound only is not one to place calls from; `:carrier` is NULL on an engine with no such
#: rule (`outbound_number_provider`).
#:
#: `dlt_status` is not asked (D-793): no client registers on DLT since D-692, every number
#: is inserted `pending` and nothing outbound requires `registered`, so filtering on it hid
#: every client number from the dial.
_AGENT_CALLER_ID_SQL = (
    "SELECT id, e164 FROM phone_numbers "
    "WHERE agent_id = :aid "
    "AND (CAST(:carrier AS text) IS NULL "
    "     OR (provider = :carrier AND direction IN ('outbound', 'both'))) "
    "ORDER BY created_at, id"
)

#: The rules the dial gate refuses a header under when the engine presents only its numbers.
NUMBER_NOT_ON_CARRIER_RULE: Final = "number_not_on_carrier"
NUMBER_INBOUND_ONLY_RULE: Final = "number_inbound_only"

#: How an operator may have typed a number provider's name into `phone_numbers.provider`,
#: mapped to the name (`calevate_shared.carrier.NumberProvider`). Any other name records NULL.
CARRIER_SPELLINGS: Final[dict[str, str]] = {
    # A number rented and attached in ThinnestAI's console (migration a3d9e6f1c204).
    "thinnest": "thinnest",
    "thinnestai": "thinnest",
    "thinnest.ai": "thinnest",
}


def carrier_of_provider(provider: str | None) -> str | None:
    """The carrier a recorded provider names, or None when it names none we dial on.

    None is what the column holds for a number on any other operator, and the dial gate
    reads it as "not on the active carrier" (`NUMBER_NOT_ON_CARRIER_RULE`).
    """
    if provider is None:
        return None
    return CARRIER_SPELLINGS.get(provider.strip().lower())


def outbound_number_provider() -> str | None:
    """The provider an outbound header must be recorded under, or None when unconstrained.

    The engine places the call on its own account, so only a number it holds can be
    presented (`calevate_shared.carrier.ENGINE_NUMBER_PROVIDER`): on ThinnestAI, a ThinnestAI
    number. None for an engine with no such rule.
    """
    return ENGINE_NUMBER_PROVIDER.get(get_settings().engine)


# The client-facing wording of the two ways a number cannot carry outgoing calls on an
# engine that dials only its own numbers. The campaign gate
# (`campaigns.service.number_dial_refusal`) and its number picker speak them.
NUMBER_NOT_ON_CARRIER_REASON = (
    "This agent's calling number is not on the phone line Calevate places calls through, so "
    "it cannot be shown to the person being called. Ask Calevate to record which carrier "
    "holds the number, or assign a number on the active carrier to this agent."
)
NUMBER_INBOUND_ONLY_REASON = (
    "This agent's calling number is set up for incoming calls only, so it cannot place "
    "outbound calls. Assign a number set up for outgoing calls to this agent."
)


async def agent_outbound_numbers(
    session: AsyncSession, *, agent_id: UUID
) -> list[tuple[UUID, str]]:
    """`(id, e164)` of every number this agent can place calls from, oldest first."""
    rows = (
        await session.execute(
            text(_AGENT_CALLER_ID_SQL), {"aid": agent_id, "carrier": outbound_number_provider()}
        )
    ).all()
    return [(UUID(str(row[0])), str(row[1])) for row in rows]


async def resolve_caller_id(
    session: AsyncSession, *, agent_id: UUID, number_id: UUID | None = None
) -> str | None:
    """The number this dial rings from, or None to let the engine use the agent's own line.

    The candidates are the agent's outbound numbers (`agent_outbound_numbers`, D-793):

    * `number_id` (a campaign's chosen number) is presented when it is one of them. When it
      no longer is — unassigned or changed since the tick's `dispatch_blockers` — the dial
      is refused with `CAMPAIGN_NUMBER_UNAVAILABLE_CODE` rather than sent from another
      number, because the campaign gate promises the calls come from the number it names;
    * otherwise exactly one candidate is presented;
    * otherwise (none, or several and nothing chose) None: ThinnestAI then rings from the
      agent's own line (`place-call.md:708-715,971-977`), which beats the old
      `agent_caller_id_ambiguous` refusal — that guarded a 140/160 DLT class choice nobody
      makes since D-692, and refusing would stop every dial of a multi-number agent.

    Ids and counts in the log line, never a number (hard rule 6).
    """
    rows = await agent_outbound_numbers(session, agent_id=agent_id)
    if number_id is not None:
        chosen = next((e164 for row_id, e164 in rows if row_id == number_id), None)
        if chosen is None:
            log.warning(
                CAMPAIGN_NUMBER_UNAVAILABLE_CODE,
                extra={"agent_id": str(agent_id), "number_id": str(number_id)},
            )
            raise ProblemError.business_rule(
                CAMPAIGN_NUMBER_UNAVAILABLE_CODE,
                "This campaign's calling number is no longer one its agent can place calls from.",
                remediation=(
                    "Assign the number to the campaign's agent for outgoing calls, or pick "
                    "another of the agent's numbers for the campaign."
                ),
            )
        return chosen
    return rows[0][1] if len(rows) == 1 else None


async def _recall_for_dial(
    session: AsyncSession,
    tenant_id: UUID,
    *,
    agent: AgentRow,
    phone_e164: str,
) -> tuple[str, ...]:
    """What this agent remembers about the person about to be dialled. Empty is normal.

    **IT FAILS OPEN, AND THAT IS THE DECISION.** A returning caller greeted generically is
    a missed nicety; a dial that did not happen because a memory lookup raised is a broken
    product, and the failure would land on the one path a client watches. So every failure
    here — a number that is not canonical E.164 (`CallerRefError`), a KEK ring that cannot
    derive, a slow read — becomes an empty tuple and a log line, never an exception through
    the dial. `CALLER_MEMORY_GUIDANCE` tells the model that an empty block means a caller it
    does not know, so the degraded state is a correct call rather than a confused one.

    THE SWITCH IS READ OFF THE ROW WE ALREADY HAVE, so an agent that does not remember its
    callers — every agent by default — costs this path nothing at all, not even a query.
    `recall()` checks again for itself; that arm is the one that matters if the switch moves
    between `_load_agent` and here, and a read-side check is not redundant with a write-side
    one (`compliance/caller_memory.recall`'s own argument).

    HARD RULE 6: ids and a count. Never the number, never a fact.
    """
    if not bool(agent["caller_memory_enabled"]):
        return ()
    try:
        facts = await recall(session, tenant_id, agent_id=agent["id"], phone_e164=phone_e164)
    except Exception:
        log.warning(
            "caller_memory_recall_failed_open",
            extra={"agent_id": str(agent["id"])},
        )
        return ()
    log.info(
        "caller_memory_recalled_for_dial",
        extra={"agent_id": str(agent["id"]), "facts": len(facts)},
    )
    return facts


async def _assert_dialling_tenant_owns_the_session(
    session: AsyncSession, *, tenant_id: UUID
) -> None:
    """Refuse a dial whose reads and writes would belong to two different tenants.

    `dispatch_call` is the one function in this tree that takes BOTH a tenant-scoped
    session and a `tenant_id`, and it uses them for different halves of the same call:
    the agent row, the caller ID and the caller memory are read under the SESSION's
    `app.tenant_id`, while the `calls` intent row, the experiment assignment and the
    unplaced-dial settlement are written under `tenant_session(tenant_id)`. RLS cannot
    notice the difference — each half is individually legal — so a mismatch dials tenant
    A's published agent, presents tenant A's DLT-registered header, and books the call,
    its minutes and its wallet debit to tenant B. `calls.agent_id` is a plain foreign key
    and PostgreSQL validates it with row security bypassed (`db/ownership.py`), so the
    row lands rather than erroring, and the complaint trail then names the wrong
    Principal Entity.

    No caller does this today; the point is that nothing stopped one. Hard rule 1 wants
    the boundary enforced rather than conventional, and this is the whole platform's
    outbound chokepoint (`scripts/check_compliance_invariants.py` §1), so one assertion
    here covers the campaign dispatcher, the lead-callback button and the ingest path.

    Rejected: drop the `tenant_id` parameter and read the session's GUC instead, which is
    the doctrine `db/session.session_tenant` states. It is the better shape and it is a
    change to four callers in three packages plus the AST guardrail, none of which this
    change owns; the assertion makes the drift detectable in the meantime and is what
    that refactor would delete.

    Costs one `current_setting` round trip on a path that already makes several queries
    and a vendor HTTP call.
    """
    scoped_to = await session_tenant(session)
    if scoped_to != tenant_id:
        # Ids only (hard rule 6), and an operator-actionable line: the caller passed a
        # tenant that is not the one its own session can read.
        log.error(
            "dial_tenant_binding_mismatch",
            extra={
                "session_tenant_id": str(scoped_to),
                "requested_tenant_id": str(tenant_id),
            },
        )
        raise RuntimeError(
            "dispatch_call was given a tenant-scoped session for a different tenant "
            "than the dial it was asked to place"
        )


@dataclass(frozen=True, slots=True)
class TrialDial:
    """A free-trial test call (D-697): rung from the shared trial number and cut off at
    `max_call_seconds`. Built only by `agents/trial_calls.place_trial_call`."""

    from_e164: str
    max_call_seconds: int
    #: The developer-workspace engine agent to ring through, when it is not the agent's own:
    #: a paying client's test copy (D-859, option A).
    agent_ref: str | None = None


@dataclass(frozen=True, slots=True)
class OwnerTestDial:
    """A paying account's test call to the owner's own phone (D-859): rung from the agent's
    own number, billed like any call, cut off at `max_call_seconds`, at most `daily_cap` a
    day (IST). Built only by `agents/trial_calls.place_trial_call`."""

    max_call_seconds: int
    daily_cap: int
    day_start: datetime


async def _hold_paid_test_slot(
    session: AsyncSession, *, tenant_id: UUID, test: OwnerTestDial
) -> None:
    """Refuse the test call once today's cap is reached, counted with this call's own row in
    the intent transaction under a per-tenant lock, so two at once cannot both pass."""
    from apps.api.agents.paid_test_calls import (
        DAILY_CAP_RULE,
        PLACED_TODAY_SQL,
        paid_daily_cap_reason,
    )

    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"paid-test-call:{tenant_id}"},
    )
    placed = int(
        (
            await session.execute(
                text(PLACED_TODAY_SQL), {"tid": tenant_id, "since": test.day_start}
            )
        ).scalar_one()
    )
    if placed > test.daily_cap:
        raise ProblemError.conflict(
            DAILY_CAP_RULE,
            paid_daily_cap_reason(test.daily_cap),
            remediation="You can place more tomorrow.",
        )


def trial_call_first_words(agent: AgentRow, *, call_is_recorded: bool) -> str | None:
    """What an agent that only answers calls says first when it rings its owner on a test
    call (founder, 23 Oct 2026): who it is, from which business, why it rings and whether now
    suits, then the notices its switches turn on, in the order its greeting carries them
    (D-861). When its AI notice introduces it (D-865), the line after the introduction says
    only why it rings and whether now suits. None for an agent that calls out (its greeting
    already does) or a language with no such line (its greeting is spoken)."""
    if agent["direction"] != "inbound":
        return None
    posture = posture_of(agent)
    language = str(agent["language_primary"])
    ai_notice = spoken_ai_notice(posture)
    line = trial_call_opening(
        language,
        name=str(agent["name"]),
        business=str(agent.get("business_name") or ""),
        introduced=introduces_itself(ai_notice=ai_notice, language=language),
    )
    if line is None:
        return None
    notices = compose_opening_line(posture, call_is_recorded=call_is_recorded)
    return join_first_words(notices, line, ai_notice=ai_notice, language=language)


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
    trial: TrialDial | None = None,
    number_id: UUID | None = None,
    owner_test: OwnerTestDial | None = None,
    rings_at_any_hour: bool = False,
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

    A `trial` dial (D-697) rings from the shared trial number, holds the one trial line from
    the intent row until the call ends (`_hold_trial_line`), lends that number to the agent
    before dialling, carries the per-call time limit, and takes part in no experiment.

    `number_id` is the number a campaign chose to call from (`campaigns.number_id`); see
    `resolve_caller_id` for how the caller id is decided with and without it.

    An `owner_test` dial (D-859) is a paying account's test call: marked `paid_test_call`, it
    holds the account's daily test-call cap in the intent transaction, carries the per-call
    time limit, and takes part in no experiment. Alone it rings from the agent's own number;
    with `trial` too it takes the shared trial line exactly as a trial call does (option A),
    through `trial.agent_ref` when that is the agent's developer-workspace test copy.

    `rings_at_any_hour` is the owner's own-number test call (D-866), the one dial the gate
    lets ring outside the window; every other dial carries the window to the engine (D-872).
    """
    if rings_at_any_hour and trial is None and owner_test is None:
        # Only a test call can be exempt from the window; a campaign, callback or lead dial
        # that asked for it would be a night call to the public.
        raise ValueError("rings_at_any_hour is for a test call only")
    await _assert_dialling_tenant_owns_the_session(session, tenant_id=tenant_id)

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
    # ever see this tenant's numbers; and BEFORE the intent row, so a refusal costs one
    # indexed read and leaves no `queued` call behind for a dial that was never placed.
    from_e164 = (
        trial.from_e164
        if trial is not None
        else await resolve_caller_id(session, agent_id=agent_id, number_id=number_id)
    )

    # The stable unit: the lead when there is one, the destination otherwise. See
    # `agents/assignment.py` for why it is not the call id.
    arm = (
        None
        if trial is not None or owner_test is not None
        else await assignment.assign(
            session, agent_id=agent_id, unit_key=str(lead_id) if lead_id else phone_e164
        )
    )
    # An arm that has never been published has no engine agent to dial. Falling back to
    # the agent's own ref rather than failing: the client's call is the thing that
    # matters, and a call that ran the control is a call, whereas a refused dial is an
    # outage caused by an experiment. It is not recorded as assigned — see below.
    dial_ref = (
        trial.agent_ref
        if trial is not None and trial.agent_ref
        else arm.arm.engine_agent_ref
        if arm and arm.arm.engine_agent_ref
        else ref
    )

    # THE ENGINE ACCOUNT'S TWO LIMITS (ThinnestAI): the vendor's hold-off after a 429, then
    # its call ceiling under the line lock. Both are refused before the intent row exists,
    # so nothing is left `queued` for a dial that was never placed.
    engine_capped = engine_concurrency_cap() is not None
    if engine_capped and await dial_backoff_remaining_s() > 0:
        raise engine_backoff_refusal()

    call_id = uuid7()
    intent_engine_call_id = unconfirmed_engine_call_id(call_id)
    async with tenant_session(tenant_id) as intent:
        if trial is not None:
            await _hold_trial_line(intent)
            studio_left = await refuse_trial_studio_over_cap(
                intent, tenant_id=tenant_id, agent_id=agent_id
            )
            if studio_left is not None:
                # A Studio test call stops where the trial's Studio minutes do, not at the
                # general free minutes' limit; never under the platform's 60-second minimum
                # (snapshots/2026-10-15/pages/api-reference/calls/place-call.md:1264-1268).
                trial = replace(
                    trial,
                    max_call_seconds=min(
                        trial.max_call_seconds, max(TRIAL_MIN_CALL_SECONDS, studio_left)
                    ),
                )
        if engine_capped:
            await _hold_engine_line(intent)
        await intent.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, from_e164, "
                "to_e164, trial_call, paid_test_call, status, created_at, updated_at) VALUES (:id, "
                ":tid, :aid, :ecid, 'outbound', :from_e, :to_e, :trial, :owner_test, 'queued', "
                "now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": intent_engine_call_id,
                # Our number when we chose it, so a call still ringing can say where it rings
                # from (D-885); null leaves it to the engine's report at the end.
                "from_e": from_e164,
                "to_e": phone_e164,
                "trial": trial is not None,
                "owner_test": owner_test is not None,
            },
        )
        if owner_test is not None:
            await _hold_paid_test_slot(intent, tenant_id=tenant_id, test=owner_test)
        # The arm rides the row it describes, in the row's own transaction. There is no
        # `ON CONFLICT` to lose any more: the id is ours and fresh, so this INSERT cannot
        # race the poller. The invariant that mattered — an assignment never MOVES — is
        # `assignment.record`'s own `ON CONFLICT (call_id) DO NOTHING`.
        if arm is not None and arm.arm.engine_agent_ref:
            await assignment.record(intent, tenant_id=tenant_id, call_id=call_id, assignment=arm)
        if on_reserved is not None:
            await on_reserved(intent, call_id)

    if trial is not None:
        await _lend_trial_line(tenant_id, call_id=call_id, agent_ref=dial_ref)
    from apps.api.actions.pre_dial import CallerPrefill, pre_dial_lookup

    engine = get_engine()
    # The client's caller lookup, BEFORE the dial on an engine that takes a name and call
    # variables (D-700): the person is greeted by name with no wait on the line.
    prefill = (
        await pre_dial_lookup(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone_e164
        )
        if engine.name in ACTION_ENGINES and trial is None
        else CallerPrefill()
    )
    try:
        handle = await engine.start_outbound_call(
            dial_ref,
            phone_e164,
            CallContext(
                lead_id=str(lead_id) if lead_id else None,
                lead_name=lead_name or prefill.name,
                fields=prefill.variables,
                context_note=context_note,
                # WHAT THIS AGENT ALREADY KNOWS ABOUT THE PERSON BEING DIALLED (D-513).
                # Resolved HERE because this function is the platform's single outbound
                # entry point — the property `scripts/check_compliance_invariants` asserts
                # — so the campaign dispatcher, the D-21 "call this lead" button and the
                # callback path all get it without any of them knowing the feature exists.
                caller_memory=await _recall_for_dial(
                    session, tenant_id, agent=agent, phone_e164=phone_e164
                ),
                # The per-call prompt with `{{ }}` merge fields resolved from THIS lead's
                # data (structured builder, D-script). Only the values known at dial time
                # are supplied; an unfilled field collapses to nothing rather than being
                # spoken as a literal `{{ }}` (see `substitute_variables`). On an engine
                # that holds the prompt as agent state (`control_plane`)
                # this returns None, so the merge only runs on engines that carry the
                # prompt per call.
                system_prompt=_call_prompt_for(
                    engine,
                    tenant_id,
                    agent,
                    merge_values={"lead_name": lead_name, "phone": phone_e164},
                ),
                from_e164=from_e164,
                # Our intent row's id, for an engine whose carrier calls back into our
                # routes with it in the path (`calevate_shared.carrier.answer_path`).
                call_id=str(call_id),
                max_call_seconds=(
                    trial.max_call_seconds
                    if trial is not None
                    else owner_test.max_call_seconds
                    if owner_test is not None
                    else None
                ),
                opening=trial_call_first_words(
                    agent, call_is_recorded=engine.capabilities.records_audio
                )
                if trial is not None or owner_test is not None
                else None,
                rings_at_any_hour=rings_at_any_hour,
            ),
        )
    except Exception as exc:
        # `Exception`, NOT `BaseException`. A `CancelledError` through this await is a
        # worker being shut down or a job overrunning `job_timeout`; arq retries the job
        # for it, so it must keep propagating as itself. The intent row and whatever
        # `on_reserved` wrote are already committed, which is precisely what makes that
        # cancellation survivable — the contact stays `dialing` pointing at an
        # unconfirmed call, and `_reap_stuck_dialing` settles it without a second ring.
        platform_block = await platform_dnc_refusal(
            session, exc, tenant_id=tenant_id, phone_e164=phone_e164
        )
        if platform_block is not None:
            # Only the voice platform's shared list blocks this person (D-691): nothing
            # rang, and our own list is left as it is.
            await _close_unplaced_dial(
                tenant_id,
                call_id=call_id,
                code=platform_block.code,
                vendor_status=exc.vendor_status if isinstance(exc, EngineRejectedError) else None,
            )
            raise platform_block from exc
        code = exc.code if isinstance(exc, ProblemError) else type(exc).__name__
        if engine_capped and isinstance(exc, EngineRateLimitedError):
            await start_dial_backoff(exc.retry_after_s)
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

    # THE VENDOR HAS ACCEPTED THE CALL, so from here nothing may raise: a raise reads to
    # every caller as "not placed", and the campaign and call-back loops then ring the
    # person again (D-841). Both writes below are bookkeeping; each one that fails is
    # logged and alarmed, and the handle is returned.
    await _confirm_dial(tenant_id, call_id=call_id, handle=handle)
    if lead_id is not None:
        await _link_dial_to_lead(session, call_id=call_id, lead_id=lead_id)
    return handle


async def _link_dial_to_lead(session: AsyncSession, *, call_id: UUID, lead_id: UUID) -> None:
    """Point the intent row at its lead, through the CALLER's session: the lead can be
    uncommitted in that very transaction, and the FK would otherwise wait on it.

    Inside a SAVEPOINT, so a failure here rolls back only this statement and leaves the
    caller's transaction usable for the writes that settle its dial. The link is not the
    only one: the post-call pipeline files the call under its lead again (`_upsert_lead`).
    """
    try:
        async with session.begin_nested():
            await session.execute(
                text("UPDATE calls SET lead_id = :lid, updated_at = now() WHERE id = :id"),
                {"lid": lead_id, "id": call_id},
            )
    except Exception as exc:
        _alarm_unconfirmed_bookkeeping(call_id, step="lead_link", exc=exc)


def _alarm_unconfirmed_bookkeeping(call_id: UUID, *, step: str, exc: BaseException) -> None:
    """A dial the vendor accepted whose bookkeeping did not land. Ids and the error's type
    only (hard rule 6)."""
    log.error(
        "dial_bookkeeping_failed",
        extra={"call_id": str(call_id), "step": step, "error": type(exc).__name__},
    )
    alert(
        "CORE_LOGIC",
        "dial_bookkeeping_failed",
        detail=(
            f"a call the voice platform accepted could not be recorded ({step}, "
            f"{type(exc).__name__}); it was not dialled again"
        ),
        call_id=str(call_id),
    )


async def _platform_scalar(session: AsyncSession, statement: Any, params: dict[str, Any]) -> int:
    """A platform-wide count read on a session that may be a TENANT session.

    `dispatch_scan()` enumerates tenants from
    `engine_agent_routes`, whose policy shows every row only while `app.tenant_id` is
    unset; inside a tenant session it saw that one tenant, so a dial counted its own
    account's lines against a platform-wide cap and the cap could be overrun. The setting
    is cleared for the count and put back, inside the caller's transaction.
    """
    entry = (await session.execute(text("SELECT current_setting('app.tenant_id', true)"))).scalar()
    await session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
    try:
        return int((await session.execute(statement, params)).scalar_one())
    finally:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": entry or ""}
        )


#: Outbound rows holding a line on an engine-capped account, platform-wide: the sum of
#: `dispatch_scan()`'s per-tenant count (migration d8f31a7c2409), which loops the tenants
#: under each one's own policies and restores the caller's GUC, read without a migration.
#: Outbound only: the engine's
#: inbound calls reach us when they end, which is what the inbound reserve is for.
_ENGINE_LINES_IN_USE_SQL = text(
    "SELECT coalesce(sum(active_outbound), 0) FROM dispatch_scan(:statuses, "
    "make_interval(secs => :horizon))"
)
_ENGINE_LINE_STATUSES = ["queued", "ringing", "in_progress"]


async def _hold_engine_line(session: AsyncSession) -> None:
    """Refuse the dial unless an outbound line is free under the engine's call ceiling.

    The advisory lock serialises every dial's count-then-insert, so two dials cannot both
    see one free line and both go out; `lines_busy` is a refusal every caller treats as not
    placed. The row's status IS the hold: a call that ends releases it, and a row whose end
    was never reported ages out at `ENGINE_LINE_HORIZON` (`engine_concurrency_cap`).
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": CARRIER_LINES_LOCK_KEY}
    )
    in_use = await _platform_scalar(
        session,
        _ENGINE_LINES_IN_USE_SQL,
        {"statuses": _ENGINE_LINE_STATUSES, "horizon": ENGINE_LINE_HORIZON.total_seconds()},
    )
    pool = outbound_line_pool()
    if in_use >= pool:
        log.info(
            "dial_refused_lines_busy",
            extra={"engine": get_engine().name, "lines_in_use": in_use, "outbound_pool": pool},
        )
        raise lines_busy()


#: Serialises every free-trial test call's "is the shared number free?" count with its
#: intent row (D-697). Its own key: a trial dial must not queue behind every client's dials.
TRIAL_LINE_LOCK_KEY: Final = 0x5452_4941_4C4C_494E
TRIAL_LINE_BUSY_RULE: Final = "trial_line_busy"
TRIAL_LINE_UNAVAILABLE_RULE: Final = "trial_line_unavailable"


async def _hold_trial_line(session: AsyncSession) -> None:
    """Refuse a test call while another one is live anywhere on the platform (D-697).

    Every test call rings from ONE shared number, lent to one agent at a time
    (`update-phone-number.md:144-145`), and what re-pointing it does to a call in progress
    is not documented. So the line is held for the WHOLE call: the lock serialises the
    count with this intent row, and from commit the row's own status is the hold, exactly
    as `_hold_engine_line` works. A call whose end is never reported ages out at
    `trial_line_horizon()` (the call limit plus a margin), so a lost delivery cannot lock
    trials out for good.
    """
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": TRIAL_LINE_LOCK_KEY})
    in_use = int(
        (
            await session.execute(
                text("SELECT trial_lines_in_use(make_interval(secs => :horizon))"),
                {"horizon": trial_line_horizon().total_seconds()},
            )
        ).scalar_one()
    )
    # A forwarding test rings from the same number under the same lock (D-746).
    from apps.api.forwarding.testing import forwarding_legs_in_use

    in_use += await forwarding_legs_in_use(session)
    if in_use > 0:
        log.info("trial_call_refused_line_busy", extra={"trial_lines_in_use": in_use})
        raise ProblemError.conflict(
            TRIAL_LINE_BUSY_RULE,
            "Another test call is in progress.",
            remediation="Try again in a minute.",
        )


async def _lend_trial_line(tenant_id: UUID, *, call_id: UUID, agent_ref: str) -> None:
    """Lend the shared trial number to the agent about to dial, or close the dial unplaced."""
    from apps.api.campaigns.engine_numbers import lend_trial_line

    if await lend_trial_line(agent_ref):
        return
    await _close_unplaced_dial(tenant_id, call_id=call_id, code=TRIAL_LINE_UNAVAILABLE_RULE)
    raise ProblemError.business_rule(
        TRIAL_LINE_UNAVAILABLE_RULE,
        "Test calls are not available right now.",
        remediation="Try again in a few minutes.",
    )


async def _confirm_dial(tenant_id: UUID, *, call_id: UUID, handle: str) -> None:
    """Stamp the vendor's handle onto the intent row, in its own transaction.

    Guarded by `NOT EXISTS` rather than left to the unique index: the poller can already
    have created a row for this execution (it does that for calls it discovers), and a
    duplicate-key error here would abort a transaction whose only job is bookkeeping for
    a call that is by now really ringing. When the guard bites, OUR row keeps its local
    id — visible, `queued`, and settled by the same reaper as any other unconfirmed dial
    — and the vendor's row is the one the pipeline uses. `IntegrityError` is still
    caught, because the guard and the insert can interleave.

    Any other failure (the database unreachable, a pool timeout) leaves the row in the same
    state, unconfirmed and reaped the same way, and is alarmed rather than raised: the call
    is ringing, and a raise would be read as "not placed" (`dispatch_call`).
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
    except Exception as exc:
        _alarm_unconfirmed_bookkeeping(call_id, step="handle_stamp", exc=exc)
        return
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
    engine_number_ref: str | None = None,
    engine_owned: bool = False,
    direction: str = "inbound",
    purchase_price_usd: Decimal | None = None,
    monthly_rental_usd: Decimal | None = None,
) -> UUID:
    """Record a number the tenant may dial from and be answered on (DATA-MODEL §6).

    RECORD, not obtain, and that is still true of this function under Model A: it writes a
    row. Where the number CAME from is the caller's business — a client's own connection on
    their own carrier account (Model B, `docs/legal/LEGAL-OPS-PLAYBOOK.md`
    §9), or a purchase `campaigns/number_supply.buy_number` has already made at the engine
    (Model A, D-537). Nothing here talks to a carrier and nothing here spends money.

    **`engine_number_ref` IS THE COLUMN THAT HAD NO WRITER, AND ITS ABSENCE BROKE EVERY
    INBOUND PUBLISH (GAP-1).** It is declared on `phone_numbers`, it is READ by
    `route_inbound_numbers` → `bind_inbound_number` (the rented engine's adapter resolved it
    to the vendor's number id; D-639 deleted it), and until now the only INSERT in
    production code omitted it, no request body carried it (`ProvisionNumberIn` is
    `extra="forbid"`) and no screen set it — a repo-wide grep found it written only in test
    fixtures. The consequence, on every publish of an inbound agent with a recorded number:
    `engine_number_not_linked`, one `CORE_LOGIC` alarm per number, and a publish that
    reports SUCCESS. It is optional here rather than required because it is genuinely
    unknown at the moment a client's own connection is first recorded — the operator learns
    the vendor's handle when the number is introduced to the voice platform, which is a
    later step — and `set_number_engine_ref` is where it lands then. What is not acceptable,
    and was the state before D-537, is that there was no later step at all.

    **`engine_owned` DECIDES WHAT A RELEASE MEANS** and defaults to False, which is what
    every client-brought connection is: releasing one at the vendor would do nothing there
    and would lose our record of it here.

    The two USD prices are the vendor's own quote and are recorded only for a number we
    bought. They are what `billing/number_rental.py` meters against; the rupee is struck
    monthly, never here (hard rule 7).

    `series` is the load-bearing field: it is what the campaign launch gate matches
    against the campaign's classification, so getting it wrong here is a DLT violation
    later. `dlt_status` starts `pending` and is a separate deliberate step — a number
    is not registered because we typed it in.

    **AND IT IS NOW CHECKED AGAINST THE NUMBER, because it was an operator's typed word
    and nothing else.** The 140/160 gate enforces on this column, and this INSERT took
    it verbatim: a `+91 98…` mobile typed `"140"` passed and unlocked promotional
    dialling; a real 140 number typed `"standard"` passed and unlocked
    service/transactional dialling. `series_for_e164` reads the answer out of the E.164
    prefix that was in the same request all along (DoT/PIB PRID 2022249 — see that
    function), and a disagreement is refused BY NAME rather than corrected silently: the
    operator has two facts in front of them and one of them is wrong, and which one is
    not ours to guess. Misclassification here is what the ₹2/₹5/₹10 lakh ladder under the
    2025 TCCCPR amendments is for (`docs/legal/phone-number-research.md:23`).

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
    # A free-trial account records no number until it pays (D-697). Here, the one function
    # every record path ends in, so neither an admin route nor a purchase can skip it.
    await refuse_trial_numbers(session, tenant_id=tenant_id)
    if agent_id is not None:
        # Binding a number to a DELETED agent would undo the one thing deleting does at the
        # vendor: `lifecycle.archive_agent` RELEASES the agent's numbers, because inbound is
        # answered by whatever the vendor has bound to a number and nothing in our database
        # is consulted. The agent arrives in the body, so the route-level guard cannot see it.
        await assert_agent_writable(session, agent_id, verb="given a phone number")
    declared = series_for_e164(e164)
    if declared is None:
        # 140 and 160 are Indian numbering series. A number outside +91 cannot be one,
        # and claiming it is would put a foreign header on regulated Indian traffic.
        if series != "standard":
            raise ProblemError.business_rule(
                "number_series_mismatch",
                f"{e164} is not an Indian number, so it cannot be a {series}-series connection.",
                remediation=(
                    "Record a non-Indian number as 'standard', or check the number. "
                    "The 140 and 160 series exist only within +91."
                ),
            )
    elif declared != series:
        raise ProblemError.business_rule(
            "number_series_mismatch",
            f"This number's own prefix makes it a {declared} number, but it was recorded "
            f"as {series}.",
            remediation=(
                "The series is fixed when the operator issues the number: 140xxxxxxx is "
                "telemarketing/promotional, 160xxxxxxx is service/transactional, and "
                "anything else is standard. Correct whichever of the two is wrong — the "
                "campaign launch gate matches a campaign's classification against this "
                "field, so a number filed under the wrong series dials the wrong traffic."
            ),
        )
    number_id = uuid7()
    try:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, provider, "
                "direction, dlt_status, purpose, engine_number_ref, engine_owned, "
                "purchase_price_usd, monthly_rental_usd, created_at, updated_at) VALUES (:id, "
                ":tid, :aid, :e, :s, :prov, :direction, 'pending', :purpose, :ref, :owned, "
                ":buy_usd, :rent_usd, now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "aid": agent_id,
                "e": e164,
                "s": series,
                # The column holds a carrier name or NULL (migration c8f5d1b74a30); any other
                # operator's name is NULL, which the dial gate reads as "not on our carrier".
                "prov": carrier_of_provider(provider),
                "direction": direction,
                "purpose": purpose,
                "ref": engine_number_ref,
                "owned": engine_owned,
                "buy_usd": purchase_price_usd,
                "rent_usd": monthly_rental_usd,
            },
        )
    except IntegrityError as exc:
        raise ProblemError.conflict(
            "number_taken",
            "This number is already recorded against an account.",
            remediation=(
                "Numbers are unique across the platform. Check which account already "
                "holds this connection before recording it again."
            ),
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


async def set_number_engine_ref(
    session: AsyncSession, *, number_id: UUID, engine_number_ref: str
) -> InboundRouting:
    """Tell us the voice platform's own handle for a number, and route it immediately.

    **THE OTHER HALF OF GAP-1.** A number bought through the engine gets its ref at
    purchase; a number the CLIENT holds gets one only when an operator introduces it to the
    voice platform account, which is a step outside this system. Without a route that
    accepts the answer, every such number stayed unbindable for ever and every publish of
    the agent answering it raised a `CORE_LOGIC` alarm while reporting success.

    **IT ROUTES IN THE SAME CALL RATHER THAN WAITING FOR THE NEXT PUBLISH**, for
    `provision_number`'s reason: an assignment that works only if somebody happens to edit
    the agent afterwards is a screen with nothing behind it, which is the whole class of
    defect D-420 closed. If the number is attached to no agent, or to one that is not live,
    the routing is a no-op and `activate` picks it up — the ordinary onboarding order.

    THE REF IS NOT VALIDATED, and that is deliberate and documented at the adapter: the
    vendor's own pages type this field three different ways (dashed uuid, bare hex, a
    ULID-looking string), so a format check here would refuse the very value the vendor
    issued. It is stored verbatim and handed back verbatim.
    """
    result = await session.execute(
        text(
            "UPDATE phone_numbers SET engine_number_ref = :ref, updated_at = now() "
            "WHERE id = :id RETURNING agent_id"
        ),
        {"ref": engine_number_ref, "id": number_id},
    )
    row = result.first()
    if row is None:
        raise ProblemError.not_found("Number")
    agent_id = row[0]
    if agent_id is None:
        return InboundRouting(bound=0, released=0, failed=0, unsupported=0)
    published = (
        await session.execute(
            text(
                "SELECT engine_agent_ref, direction, status FROM agents "
                "WHERE id = :aid AND deleted_at IS NULL"
            ),
            {"aid": agent_id},
        )
    ).first()
    if published is None or not published[0] or str(published[2]) != "live":
        return InboundRouting(bound=0, released=0, failed=0, unsupported=0)
    direction = published[1]
    return await route_inbound_numbers(
        session,
        get_engine(),
        agent_id=agent_id,
        ref=str(published[0]),
        answers=_is_agent_direction(direction) and agent_answers_inbound(direction),
    )


#: Numbers this client HOLDS that no agent answers. The signature of the defect D-576
#: closes: a recorded, un-released connection attached to nobody, while a receptionist is
#: being published as live.
_UNATTACHED_NUMBERS_SQL = (
    "SELECT count(*) FROM phone_numbers WHERE agent_id IS NULL AND released_at IS NULL"
)


async def _warn_if_answering_nothing(
    session: AsyncSession, *, agent_id: UUID, answers_inbound: bool, routing: InboundRouting
) -> None:
    """Make a publish that answers NO number loud, when the client has one to answer (D-576).

    **THIS IS THE ALARM THAT WOULD HAVE CAUGHT BOTH D-420 AND D-576.** Each was a
    `bound=0` that reported success: the first because nothing reached the engine, the
    second because `phone_numbers.agent_id` had no writer after the INSERT. In both, an
    operator published a receptionist, read "published", and the client's phone did not
    ring — with nothing anywhere saying so.

    **IT IS NOT A PUBLISH REFUSAL, and that is a decision rather than caution.** An
    inbound agent with no number yet is the ORDINARY onboarding order — `provision_number`
    says so in its own docstring, which is why `agent_id` is nullable — so refusing on
    `bound == 0` would refuse the first publish of every client this platform ever
    onboards, and the first thing an operator would learn is which flag turns it off.
    A publish is also not the only thing that would break: thirteen callers reach
    `publish_agent`, including the drift sweep and `activate`, so a refusal here would
    turn a missing attachment into a failed reconciliation.

    **NOR IS IT A WARNING ON THE PUBLISH RESPONSE.** `publish_agent` returns the engine
    ref and its callers are mostly workers; a field on the one HTTP route would be read by
    the one screen that publishes, which is not where an operator onboarding a client is
    looking. The console's answer to the same question is on the numbers screen, where
    every unattached number says so on its own row and the fix is on that row.

    **THE CONDITION IS NARROW ON PURPOSE.** It fires only when the agent ANSWERS inbound,
    NOTHING was bound, nothing FAILED (a failure has already alarmed, per number, with the
    vendor's refusal — a second alarm would say less), the engine can bind at all
    (`unsupported` is a deployment property, already reported once), and this client holds
    at least one recorded, un-released number attached to no agent. That last clause is
    what separates the defect from the legitimate state: a client with no number yet is
    not a fault, and paging about them would train an operator to ignore this code.

    **THE ONE FALSE POSITIVE IT KNOWINGLY KEEPS**, stated rather than tuned away: a client
    with a second inbound agent that is deliberately answering nothing — a backup desk —
    raises this every time that agent is published, while any number of theirs sits
    unattached. Narrowing it to "this client has no answering agent at all" would delete
    the case that matters: the FIRST agent published for a client whose number was recorded
    and never attached is exactly a tenant with one unattached number and one inbound agent.
    The repeat suppression in `core/alerting` bounds the noise at one per fingerprint per
    fifteen minutes, and the remedy an operator takes — open the numbers screen and look —
    is the right thing to do in both cases.
    """
    if not answers_inbound or routing.bound or routing.failed or routing.unsupported:
        return
    orphaned = (await session.execute(text(_UNATTACHED_NUMBERS_SQL))).scalar() or 0
    if not orphaned:
        return
    alert(
        "CORE_LOGIC",
        "agent_published_answering_no_number",
        detail=(
            "this agent answers incoming calls and is now live, but no number is attached "
            f"to it — while this client holds {orphaned} recorded number(s) attached to no "
            "agent at all. Nothing rings it. The publish itself succeeded."
        ),
        agent_id=str(agent_id),
        unattached_numbers=str(orphaned),
    )


#: The one number this attach/detach is about, locked so two operators cannot both decide
#: which agent answers it. The first five columns are `_AGENT_NUMBERS_SQL`'s, in its order,
#: because the same `_apply_inbound_bindings` consumes both.
_NUMBER_FOR_ATTACH_SQL = (
    "SELECT id, e164, series, provider, engine_number_ref, agent_id, released_at "
    "FROM phone_numbers WHERE id = :nid FOR UPDATE"
)

#: What decides whether attaching to this agent makes the phone ring NOW. `deleted_at IS
#: NULL` is in the predicate rather than checked afterwards so an erased agent is a 404
#: and not a 409 about an archive.
_AGENT_FOR_ATTACH_SQL = (
    "SELECT direction, status, engine_agent_ref FROM agents WHERE id = :aid AND deleted_at IS NULL"
)


async def attach_number_to_agent(
    session: AsyncSession, *, number_id: UUID, agent_id: UUID | None
) -> InboundRouting:
    """Point a recorded number at an agent — or at nothing — and tell the engine (D-576).

    **THE MISSING HALF OF `phone_numbers.agent_id`.** That column had exactly one writer
    and it was the INSERT: `provision_number` took it in the body, the release set it back
    to NULL, and nothing in this tree ever moved it to a value afterwards. Neither console
    hook supplied it at create time either, so every number this platform holds was
    attached to no agent — `_AGENT_NUMBERS_SQL` returned zero rows, `route_inbound_numbers`
    returned `bound=0`, and `publish_agent` reported SUCCESS while the phone never rang.
    That is verbatim the D-420 defect, reintroduced one layer up from the function written
    to close it.

    **AND IT WAS UNRECOVERABLE THROUGH THE PRODUCT**, which is what made it urgent rather
    than merely wrong. `campaigns/number_supply.release_number` refuses a client-owned
    connection by name (`number_not_ours_to_release`) and its own remediation says *"Detach
    it from the agent instead"* — a capability that did not exist. `phone_numbers.e164`
    carries an unconditional global UNIQUE, so the row could not be re-recorded either.
    One wrong `agent_id` at create time burned that E.164 on this platform for good.

    **DETACH RELEASES THE BINDING AT THE ENGINE, it does not merely null the column.**
    Inbound is answered by whatever the vendor holds against the number and nothing of ours
    is consulted, so a detach that stopped at our database would leave a client's line
    answered by an agent our own screen says is not on it — a mirror that lies, which is
    the class D-564 exists for. Same reason a re-point to an agent that is not LIVE
    releases: `deactivate_agent` reaches the engine precisely to take a paused agent off a
    client's line, and attaching a number to it must not put it back.

    A number the engine has never been given a handle for is the one case where nothing is
    sent on the release arm. `engine_number_not_linked` would be counted as a failure and
    would page an operator about a state that is already correct: the engine cannot be
    answering a number it has never heard of. The BIND arm still alarms on it, which is
    D-537's whole subject.

    **REFUSALS, each of which is a wrong answer somebody would otherwise get silently:**
    a number this tenant cannot see, or an agent it cannot see, is a 404 from
    `assert_visible` — that is the D-331 cross-tenant check, and it is the database's
    answer under RLS rather than a comparison of two values the caller supplied. A deleted
    agent is `agent_archived` (`assert_agent_writable`, the same guard `provision_number`
    asks). A released number is refused: it is a record kept for a closed month's costs,
    not a connection. An agent that does not answer inbound calls is refused BY NAME rather
    than attached-and-released, because "saved, and nothing happened" is exactly the report
    this defect was made of.

    Returns what the engine was told, so the console reports a binding that failed instead
    of implying one that did not happen. Ids and counts only; no phone number (hard rule 6).
    """
    # BEFORE the lock: naming a neighbour's row must not make us hold a lock on their
    # behalf (`db/ownership.assert_visible` argues the ordering). There is deliberately no
    # second `assert_visible` for the NUMBER — the locking read below runs under the same
    # RLS and answers the same question, and asking twice would add a branch no test could
    # reach (hard rule 10's worked remedy: delete the redundant fetch, not cover it).
    await assert_visible(session, "agent", agent_id)
    if agent_id is not None:
        await assert_agent_writable(session, agent_id, verb="given a phone number")

    row = (await session.execute(text(_NUMBER_FOR_ATTACH_SQL), {"nid": number_id})).first()
    if row is None:
        raise ProblemError.not_found("Number")
    number_row, current_agent_id, released_at = row[:5], row[5], row[6]
    if released_at is not None:
        raise ProblemError.business_rule(
            "number_released",
            "This number has been given back to the voice platform, so no agent can answer it.",
            remediation=(
                "The record is kept because a closed month's costs still refer to it. "
                "Record the client's current number instead."
            ),
        )

    answers = False
    ref = ""
    if agent_id is not None:
        agent = (await session.execute(text(_AGENT_FOR_ATTACH_SQL), {"aid": agent_id})).first()
        if agent is None:
            raise ProblemError.not_found("Agent")
        direction, status, engine_agent_ref = agent
        if not (_is_agent_direction(direction) and agent_answers_inbound(direction)):
            raise ProblemError.business_rule(
                "agent_does_not_answer_inbound",
                "This agent only makes outgoing calls, so attaching a number to it would "
                "not make that number ring anywhere.",
                remediation=(
                    "Set the agent to answer incoming calls as well (its direction), or "
                    "attach the number to a receptionist agent."
                ),
            )
        # LIVE AND PUBLISHED, or the engine is told to release rather than to bind. An
        # agent that has never been published has no ref to bind to, and a paused or
        # deleted one was deliberately taken off its numbers; `activate` republishes and
        # routes every attached number, so the attachment starts working the moment it
        # comes back. This is `provision_number`'s D-440 reasoning, on the later step.
        answers = bool(engine_agent_ref) and str(status) == "live"
        ref = str(engine_agent_ref or "")

    # No rowcount check: the row is held under `FOR UPDATE` from the read above, so the
    # "it vanished" arm is unreachable — and an unreachable defensive branch is a coverage
    # failure, not a safety net (hard rule 10).
    await session.execute(
        text("UPDATE phone_numbers SET agent_id = :aid, updated_at = now() WHERE id = :nid"),
        {"aid": agent_id, "nid": number_id},
    )

    if not answers and number_row[4] is None:
        # Nothing to release: the engine has never been given a handle for this number, so
        # it cannot be answering it. Sending anyway would raise `engine_number_not_linked`,
        # count as a failure and page an operator about a correct state.
        routing = InboundRouting(bound=0, released=0, failed=0, unsupported=0)
    else:
        # ONE call, not a reconcile of either agent's whole set: the other numbers of the
        # agent this one is leaving must not be released, and `bind_inbound_number` is
        # last-write-wins by contract, so a re-point needs no unbind first (an unbind
        # between the two would leave the number answering nothing in the meantime).
        routing = await _apply_inbound_bindings(
            session,
            get_engine(),
            # The agent an operator would need to look at: the one being bound, or — on a
            # release — the one the number is being taken away from.
            agent_id=agent_id if answers else current_agent_id,
            ref=ref,
            answers=answers,
            rows=[number_row],
        )
    log.info(
        "number_agent_attachment_changed",
        extra={
            "number_id": str(number_id),
            "from_agent_id": str(current_agent_id) if current_agent_id else None,
            "to_agent_id": str(agent_id) if agent_id else None,
            "bound": routing.bound,
            "released": routing.released,
            "failed": routing.failed,
        },
    )
    return routing


__all__ = [
    "CAMPAIGN_NUMBER_UNAVAILABLE_CODE",
    "CARRIER_SPELLINGS",
    "CREDIT_STOP_MESSAGE",
    "DIAL_NOT_PLACED_CODES",
    "HEALER_FORWARD_LINE",
    "INBOUND_SILENCE_CREDITS",
    "INBOUND_SILENCE_HEALER",
    "INBOUND_SILENCE_PRECEDENCE",
    "INBOUND_SILENCE_REASONS",
    "INBOUND_SILENCE_TRUTHFUL_ANSWER",
    "KNOWLEDGE_PUBLISH_IN_PROGRESS",
    "NUMBER_INBOUND_ONLY_REASON",
    "NUMBER_INBOUND_ONLY_RULE",
    "NUMBER_NOT_ON_CARRIER_REASON",
    "NUMBER_NOT_ON_CARRIER_RULE",
    "UNCONFIRMED_ENGINE_CALL_PREFIX",
    "ArmToPublish",
    "DialUnconfirmedError",
    "ForwardsLine",
    "HealerHold",
    "InboundCutover",
    "InboundRouting",
    "agent_outbound_numbers",
    "apply_healer_silence",
    "attach_number_to_agent",
    "carrier_of_provider",
    "credit_stop_greeting",
    "credit_stop_prompt",
    "dial_was_not_placed",
    "dispatch_call",
    "effective_call_cap",
    "healer_forward_greeting",
    "healer_forward_prompt",
    "in_call_model",
    "lift_healer_silence",
    "outbound_number_provider",
    "provision_number",
    "publish_agent",
    "publish_variant",
    "publish_variants",
    "reconcile_inbound_answering",
    "reconcile_inbound_truthful_answer",
    "republish_running_variants",
    "resolve_caller_id",
    "route_inbound_numbers",
    "set_number_dlt_status",
    "set_number_engine_ref",
    "unconfirmed_engine_call_id",
]
