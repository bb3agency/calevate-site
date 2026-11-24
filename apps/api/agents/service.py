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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from typing import (
    Any,
    Final,
    Literal,
    NotRequired,
    Protocol,
    TypedDict,
    TypeGuard,
    cast,
    overload,
    runtime_checkable,
)
from uuid import UUID

from calevate_shared import spoken_lines
from calevate_shared.call_script import (
    CallScript,
    Capabilities,
    NativeStep,
    call_backs_withheld,
    compile_call_script,
    native_steps,
    opening_line_of,
    outbound_opening_of,
    substitute_variables,
    without_outline,
    without_placed_opening,
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
    compose_first_utterance,
    compose_opening_line,
    introduces_itself,
    introduction_names,
    join_first_words,
    named_lead_opening,
    notice_fields,
    placed_call_first_words,
    placed_call_line,
    said_as_taught,
    said_notices,
    spoken_ai_notice,
    truthful_answer_directive,
)
from calevate_shared.engine_scope import SCOPE_SEPARATOR, is_customer_workspace, scope_of
from calevate_shared.events import NotPlacedReason
from calevate_shared.spoken_style import thinking_lines, trial_call_opening
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import (
    assignment,
    call_outcomes,
    caller_help,
    company_training,
    field_suggestions,
    hot_facts,
    voice_notes,
)
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
from apps.api.agents.engine_limits import (
    OPENING_TOO_LONG,
    refuse_over_engine_limits,
    refuse_unpriced_engine,
)
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
from apps.api.agents.opening_notices import queue_opening_notices
from apps.api.agents.own_model import (
    ensure_own_model_in,
    own_model_for,
    own_model_of_choice,
    own_model_on,
    own_model_rate_key,
    refuse_unofferable_own_model,
    require_developer_own_model,
)
from apps.api.agents.paid_test_calls import DAILY_CAP_RULE as PAID_TEST_DAILY_CAP_RULE
from apps.api.agents.reconciliation import TRUTHFUL_ANSWER_MISSING, HolderKind
from apps.api.agents.reply_length import resolve_max_reply_tokens
from apps.api.agents.t0_block import block_of, with_knowledge_of, without_block
from apps.api.agents.verification import verify_publish
from apps.api.agents.voice_stamp import stamp_of
from apps.api.agents.voice_tuning import TUNING_COLUMNS, config_speaking_speed, config_tuning
from apps.api.agents.voices import get_voice, speech_for_voice_id, voice_id_of
from apps.api.agents.workspace_slots import (
    CAMPAIGN_HOLDING_STATUSES,
    ENGINE_AGENT_ALLOWANCE_FULL_RULE,
    AllowanceContext,
    EngineAgentAllowanceFull,
    SlotHolder,
    allowance_reason,
    allowance_remediation,
    slot_holders,
    workspace_agent_allowance,
)
from apps.api.agents.write_guard import archived_refusal, assert_agent_writable
from apps.api.billing.engine_minutes import (
    ATTESTED_MINUTE_ENGINES,
    BYOK_VOICE_RATE_KEY,
    EngineRateKey,
    attested_rate_keys,
    record_engine_rate_key,
)
from apps.api.compliance.autodialer import (
    A2P_DECLARATION_MISSING_RULE,
    A2P_DECLARATION_NOT_YET_EFFECTIVE_RULE,
    A2P_NUMBER_UNDECLARED_RULE,
    a2p_declaration_blocker,
    agent_calling_numbers,
    enforcement_active,
)
from apps.api.compliance.call_notices import AI_NOTICE_SQL, RECORDING_NOTICE_SQL
from apps.api.compliance.caller_memory import MEMORY_ON_SQL
from apps.api.compliance.dnc_recall import RECALL_CAUSE_CONSENT, enqueue_dnc_recall
from apps.api.compliance.platform_dnc import PLATFORM_DNC_BLOCK_CODE, platform_dnc_refusal
from apps.api.compliance.trial_access import (
    TRIAL_MIN_CALL_SECONDS,
    TRIAL_STUDIO_MINUTES_USED_RULE,
    live_test_call_horizon,
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
from apps.api.engine.capabilities import DIAL_PRECONDITION_FAILED, ENGINE_COMPLIANCE_FLOOR_ABSENT
from apps.api.engine.catalogue import HostsVoices
from apps.api.engine.dial_lines import (
    CARRIER_LINES_LOCK_KEY,
    ENGINE_LINE_HORIZON,
    LINES_BUSY_RULE,
    TRIAL_LINE_KEY,
    DialOrigin,
    dial_backoff_refusal,
    dial_backoff_remaining_s,
    engine_concurrency_cap,
    lines_busy,
    outbound_line_pool,
    start_dial_backoff,
)
from apps.api.engine.hosted_platform import hosted_agent_limits
from apps.api.engine.publish_view import publish_digest
from apps.api.engine.thinnest_workspace import (
    trial_agent_in_developer_workspace,
    workspace_not_provisioned,
)
from apps.api.engine.vendor_http import (
    LINES_BUSY_CODE,
    NUMBER_DAILY_LIMIT_CODE,
    RECIPIENT_OPTED_OUT_CODE,
    EngineNumberDailyLimitError,
    EngineRateLimitedError,
    EngineRejectedError,
)
from apps.api.forwarding.service import has_forwarded_line
from apps.api.ingest.lead_policy import machine_detection_on
from apps.api.legal.service import assert_agreements_accepted
from apps.api.ops.halt import queue_dial_recall
from apps.api.ops.maintenance import read_open_window
from apps.api.ops.service import read_halt_state
from apps.api.reliability.engine_actions import (
    ACTION_ENGINES,
    call_connected_on,
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

#: Another test call holds the shared trial number (`_hold_trial_line`).
TRIAL_LINE_BUSY_RULE: Final = "trial_line_busy"
#: The shared trial number could not be lent to the agent about to dial (`_lend_trial_line`).
TRIAL_LINE_UNAVAILABLE_RULE: Final = "trial_line_unavailable"
#: The client's number could not be lent to the agent about to dial (`_lend_client_number`).
CLIENT_NUMBER_UNAVAILABLE_RULE: Final = "client_number_unavailable"

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
        # The number the dial would present is not covered by the client's calling-number
        # declaration (D-941, `_refuse_undeclared_caller`). Raised before the intent row; an
        # account-level fact the client fixes, so the contact keeps its place.
        A2P_DECLARATION_MISSING_RULE,
        A2P_DECLARATION_NOT_YET_EFFECTIVE_RULE,
        A2P_NUMBER_UNDECLARED_RULE,
        # The dial arrived without the truthful-answer rule on it, or reached an engine
        # that has nowhere to put one (D-282). Refused inside the adapter before the
        # request is built, so no line was seized and the contact keeps its place — the
        # same standing as a missing caller id, and for the same reason.
        ENGINE_COMPLIANCE_FLOOR_ABSENT,
        # The adapter could not build the dial (the agent's opening line unreadable or
        # missing, too many call variables) and sent no `POST /calls`.
        DIAL_PRECONDITION_FAILED,
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
        # A borrowed number could not be pointed at the agent about to dial (a vendor
        # throttle, 5xx or refusal on the re-point): the intent row is closed `failed` and no
        # `POST /calls` is sent, so a retry in a few minutes is safe.
        CLIENT_NUMBER_UNAVAILABLE_RULE,
        TRIAL_LINE_UNAVAILABLE_RULE,
        # Test-call holds refused inside the intent transaction, which rolls back.
        TRIAL_LINE_BUSY_RULE,
        PAID_TEST_DAILY_CAP_RULE,
        TRIAL_STUDIO_MINUTES_USED_RULE,
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
    #: The script language the campaign holding this agent sets over its own (D-994, D-1027).
    campaign_overrides: NotRequired[dict[str, Any] | None]
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
    #: How the owner taught the agent to sound, (language, note) (`agents/voice_notes`).
    voice_notes: NotRequired[tuple[tuple[str, str], ...]]
    #: The client's company training, the first section of every agent's script
    #: (`agents/company_training`); '' when the client has none.
    company_training: NotRequired[str]
    #: An operator's turn detection for this agent alone (D-901); None follows the console.
    turn_detection: NotRequired[TurnDetection | None]
    #: The caller follows the agent's steps on a screen of their own (D-906).
    caller_has_screen: NotRequired[bool]


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
                # What this agent OPENS with: its two sentences and the ACCOUNT's two
                # switches (D-163, D-1021). Read here, on the one path that builds an
                # `AgentConfig`, so a publish and the drift read never disagree about it.
                f"a.ai_disclosure_line, {AI_NOTICE_SQL}, "
                f"a.recording_notice_line, {RECORDING_NOTICE_SQL}, "
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
                "a.turn_detection, "
                # Whether the caller follows the agent's steps on a screen (D-906).
                "a.caller_has_screen "
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
    loaded: AgentRow = {
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
        "caller_has_screen": bool(row[_AFTER + 10]),
        # A restricted free trial never places a call back (D-697), so its agents must not
        # offer one (founder decision 1, 10 Oct 2026).
        "callbacks_offered": await restricting_trial(session, tenant_id=tenant_id) is None,
        # The client's answering-machine switch (founder decision 14, D-716).
        "detect_machines": await machine_detection_on(session),
        # The hidden-caller instruction is carried only by a client with a forwarded number.
        "forwarded_line": await has_forwarded_line(session),
        # The facts this agent knows by heart, in rank order (D-896, `agents/hot_facts`).
        "hot_facts": await hot_facts.load_texts(session, agent_id=agent_id),
        "voice_notes": await voice_notes.load(session, agent_id=agent_id),
        "company_training": await company_training.live_text(session),
    }
    # The agent's own defaults only. A campaign's settings are laid over them on the
    # campaign's own engine agent (`campaign_config`, D-1003), never on the agent's.
    return loaded


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
        # An agent has no script of its own (D-997): what it knows comes from the business,
        # and a new agent's first body is written from it (`lifecycle.first_body_from_facts`).
        remediation=(
            "Add what your business offers on What your agents know. Then put it on the phone."
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


def platform_filler_lines(languages: Sequence[str]) -> tuple[str, ...]:
    """Our filler lines for an agent speaking `languages`, at most `FILLER_LINES_MAX`, taken
    in turn from each language rather than the first languages' lines first: the engine says
    only the lines written in the caller's script, so a cut that kept the main language's
    lines alone would leave a caller in another language the engine's English one."""
    per_language = [thinking_lines((tag,)) for tag in languages]
    lines: list[str] = []
    for turn in range(max((len(own) for own in per_language), default=0)):
        for own in per_language:
            if turn < len(own) and own[turn] not in lines and len(lines) < FILLER_LINES_MAX:
                lines.append(own[turn])
    return tuple(lines)


#: The founder's "are you still on the line?" per language (`spoken_lines.json`, `on_the_line`).
ON_THE_LINE: Final[dict[str, str]] = spoken_lines.lines("on_the_line")


def platform_nudge_phrase(languages: Sequence[str]) -> str:
    """Our "are you still on the line?" for an agent speaking `languages`, or '' for the voice
    platform's own. The engine holds one question per agent (`voice.nudgePhrase`) and says it
    whatever the caller speaks, while its own question is asked in the caller's language
    (`channels/voice.md:814`, 29 Oct 2026 snapshot); so ours is set only on an agent of one
    language, where the two cannot differ."""
    if len(languages) != 1:
        return ""
    return ON_THE_LINE.get(languages[0], "")


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
    v = resolve_settings(own, organization, own_turn_detection=agent.get("turn_detection")).values
    after = v.nudge_after_seconds
    return {
        "turn_silence_ms": v.turn_silence_ms,
        "end_call_on_finish": v.end_call_on_finish,
        "nudge_after_seconds": after if after else None,
        "nudge_count": v.nudge_count,
        "nudge_phrase": v.nudge_phrase or platform_nudge_phrase(languages) or None,
        "end_after_silence_seconds": v.end_after_silence_seconds,
        "filler_lines": v.filler_lines or platform_filler_lines(languages),
        "ambience": None if v.ambience == "off" else v.ambience,
        "ambience_volume_pct": v.ambience_volume_pct,
        # None while the console has no wait: the field is then never sent (D-901).
        "opening_wait_ms": v.opening_wait_ms if opening_wait_available() else None,
        "reask_after_ms": v.reask_after_ms,
    }


def _to_config(
    tenant_id: UUID,
    agent: AgentRow,
    *,
    engine: VoiceEngine,
    handoff: HandoffSpec | None = None,
    keep_placed_opening: bool = False,
    training_gives_way: bool = True,
    holder_fields: dict[str, Any] | None = None,
) -> AgentConfig:
    """`holder_fields` are the fields a line or campaign sets over its agent's (its name,
    direction, tools), put on before the client's sections so the company training gives way
    against the prompt that holder really sends: a line's direction and call-backs change
    the platform layers. `training_gives_way=False` composes the whole training even where
    it overflows, for the training save's own measurement (`company_training.overflow_of`)."""
    settings = get_settings()
    hosted = _engine_voice_fields(agent, engine=engine)
    steps, body = _steps_for(
        engine, agent, _script_for(engine, _assert_has_a_script(agent)), handoff=handoff
    )
    if agent["direction"] != "both" and not keep_placed_opening:
        # This agent's calls open with its [OPENING] (`compose_first_utterance`), so a
        # placed-call opening in its script (kept from a time it was "both", or a campaign's
        # from a "both" voice) is not composed in, where it would read as still to say. A
        # line keeps it: it places its voice's call-backs with that opening (D-1019 D2).
        body = without_placed_opening(body)
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
        temperature=settings.thinnest_agent_temperature_tenths / 10,
        thinking_delay_ms=settings.thinnest_thinking_delay_ms,
        thinking_repeat_ms=settings.thinnest_thinking_repeat_ms,
        has_phone_number=bool(agent.get("has_phone_number", False)),
        forwarded_line=bool(agent.get("forwarded_line", False)),
        caller_has_screen=bool(agent.get("caller_has_screen", False)),
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
    if holder_fields:
        config = config.model_copy(update=holder_fields)
    return _with_client_sections(config, agent, engine, training_gives_way=training_gives_way)


def _with_client_sections(
    base: AgentConfig, agent: AgentRow, engine: VoiceEngine, *, training_gives_way: bool = True
) -> AgentConfig:
    """`base` with the client's sections every holder carries: the company training, the
    voice notes and the known facts. The training goes first, so the known facts are cut to
    fit beside it (D-896), and gives way itself where the script leaves it no room
    (`company_training.give_way`)."""

    def compose(training: str) -> AgentConfig:
        cfg = company_training.with_training(base, training)
        cfg = voice_notes.with_voice_notes(cfg, agent.get("voice_notes") or ())
        # A no-op on every engine that holds the facts in the prompt already.
        return hot_facts.with_known_facts(cfg, agent.get("hot_facts") or (), engine)

    training = str(agent.get("company_training") or "")
    if not training_gives_way:
        return compose(training)
    return company_training.give_way(compose, training, engine)


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
    test_copy: bool = False,
    inbound_line_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> None:
    """Push the script's [T0 FACTS] block as the vendor agent's facts document, on an engine
    that keeps facts out of the prompt, and the client's published knowledge
    (`agents/engine_facts.py`); `variant_id` names the experiment arm `ref` speaks, and
    `test_copy` says `ref` is the agent's test copy, `inbound_line_id` the line whose engine
    agent it is (D-997) and `campaign_id` the campaign's (D-1003). A failure fails the publish,
    with `reclaim` deleting a vendor agent this publish created, for `_reclaim_orphan`'s
    reason."""
    try:
        await sync_business_facts(
            session,
            engine,
            agent_id=agent_id,
            ref=ref,
            facts=block_of(script),
            variant_id=variant_id,
            test_copy=test_copy,
            inbound_line_id=inbound_line_id,
            campaign_id=campaign_id,
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
    "SELECT n.id, n.e164, n.series, n.provider, n.engine_number_ref, l.engine_agent_ref "
    "FROM phone_numbers n LEFT JOIN inbound_lines l ON l.id = n.inbound_line_id "
    "AND l.archived_at IS NULL AND l.published_at IS NOT NULL "
    "WHERE n.agent_id = :aid ORDER BY n.created_at, n.id"
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
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    agent_id: UUID,
    ref: str | None,
    answers: bool,
    lines_answer: bool | None = None,
) -> InboundRouting:
    """Make the engine agree with `phone_numbers.agent_id` (D-420).

    `ref` is None for an agent that holds no engine agent of its own (D-1019): its numbers
    on no live line are released whatever `answers` says, since nothing of its own could
    answer them.

    **A NUMBER ON A PUBLISHED INBOUND LINE IS ANSWERED BY THE LINE'S OWN ENGINE AGENT**
    (D-997), never by `ref`. `lines_answer` says whether those numbers answer, and defaults
    to `answers`: every silence (credit stop, healer, maintenance, voice fallback) passes
    `answers=False` and so silences the agent's lines with it, and every restore gives each
    number back to its line. `publish_agent` passes it apart, because in the new model a
    voice agent that answers on its lines need not answer as itself (its own `direction`).

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
    own = [row[:5] for row in rows if not row[5]]
    by_line: dict[str, list[Any]] = {}
    for row in rows:
        if row[5]:
            by_line.setdefault(str(row[5]), []).append(row[:5])
    totals = InboundRouting(bound=0, released=0, failed=0, unsupported=0)
    # The release arm names the number, not an agent, so an absent `ref` is never sent.
    groups: list[tuple[str, bool, list[Any]]] = (
        [(ref or "", answers and ref is not None, own)] if own else []
    )
    line_answers = answers if lines_answer is None else lines_answer
    groups += [(line_ref, line_answers, line_rows) for line_ref, line_rows in by_line.items()]
    for target, answering, group in groups:
        done = await _apply_inbound_bindings(
            session, engine, agent_id=agent_id, ref=target, answers=answering, rows=group
        )
        totals = InboundRouting(
            bound=totals.bound + done.bound,
            released=totals.released + done.released,
            failed=totals.failed + done.failed,
            unsupported=totals.unsupported + done.unsupported,
        )
    return totals


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


#: The engine agents of an agent's live inbound lines (D-997): what the callers of its lines
#: reach, so every silence that changes what the agent says changes what these say too.
_LIVE_LINE_REFS_SQL: Final = (
    "SELECT engine_agent_ref FROM inbound_lines WHERE agent_id = :aid AND archived_at IS NULL "
    "AND published_at IS NOT NULL AND engine_agent_ref IS NOT NULL ORDER BY created_at, id"
)


async def live_line_refs(session: AsyncSession, *, agent_id: UUID) -> list[str]:
    """The engine agents of `agent_id`'s live lines, oldest line first."""
    rows = await session.execute(text(_LIVE_LINE_REFS_SQL), {"aid": agent_id})
    return [str(ref) for ref in rows.scalars()]


#: An inbound line's own numbers, in `_apply_inbound_bindings`' row shape.
_LINE_NUMBERS_SQL: Final = (
    "SELECT id, e164, series, provider, engine_number_ref FROM phone_numbers "
    "WHERE inbound_line_id = :lid AND released_at IS NULL ORDER BY created_at, id"
)

#: The line's engine agent, whether it is live, its voice agent, whether anything may answer
#: (the voice live, not deleted, and not under the compliance silence, which unbinds numbers,
#: D-564), and the voice agent's own engine agent and whether it answers as itself. A credit
#: stop or a healer hold keeps the numbers bound and changes what the line's engine agent
#: says instead (`_hold_line_if_silenced`), as it does for the agent's own.
_LINE_ANSWERS_SQL: Final = (
    "SELECT l.engine_agent_ref, l.published_at IS NOT NULL AND l.archived_at IS NULL, "
    "a.id, a.status = 'live' AND a.deleted_at IS NULL "
    "AND a.inbound_silence_reason IS DISTINCT FROM :truthful, "
    "a.engine_agent_ref, a.direction IN ('inbound', 'both') "
    "FROM inbound_lines l JOIN agents a ON a.id = l.agent_id WHERE l.id = :lid"
)


async def route_line_numbers(session: AsyncSession, *, line_id: UUID) -> InboundRouting:
    """Point an inbound line's numbers at what answers them (D-997): the line's own engine
    agent once it is live, its voice agent's own engine agent while it is a draft (as the
    backfill's draft lines are answered), or nothing while the voice is off, deleted or under
    the compliance silence. Called after the line's publish committed, and after a number
    joins the line, so a number moved off another line never stays on that line's engine
    agent.

    Both engine mechanisms are driven, as for an agent's numbers: the binding an engine with
    `inbound_binding` takes, and the attachment a platform with its own number API holds
    (`engine_numbers.sync_number_attachment`, ThinnestAI), which reads the same rows."""
    from apps.api.campaigns.engine_numbers import sync_number_attachment

    found = (
        await session.execute(
            text(_LINE_ANSWERS_SQL), {"lid": line_id, "truthful": INBOUND_SILENCE_TRUTHFUL_ANSWER}
        )
    ).first()
    rows = (await session.execute(text(_LINE_NUMBERS_SQL), {"lid": line_id})).all()
    if found is None or not rows:
        return InboundRouting(bound=0, released=0, failed=0, unsupported=0)
    line_ref, live, agent_id, may_answer, agent_ref, agent_answers = found
    for row in rows:
        await sync_number_attachment(session, number_id=UUID(str(row[0])))
    if line_ref and live:
        target, answers = str(line_ref), bool(may_answer)
    elif agent_ref:
        target, answers = str(agent_ref), bool(may_answer and agent_answers)
    else:
        return InboundRouting(bound=0, released=0, failed=0, unsupported=0)
    return await _apply_inbound_bindings(
        session, get_engine(), agent_id=UUID(str(agent_id)), ref=target, answers=answers, rows=rows
    )


async def retire_in_call_actions(*, agent_id: UUID, ref: str | None) -> int:
    """Remove the vendor agent's in-call actions when the agent is archived or its engine
    agent is retired. Switching off keeps them (D-981): a switched-off agent is still ready
    and the sweeps keep its actions.

    A failure alarms and does not undo the archive, `route_inbound_numbers`'
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
    f"SELECT a.id, a.engine_agent_ref, a.ai_disclosure_line, {AI_NOTICE_SQL}, "
    f"a.recording_notice_line, {RECORDING_NOTICE_SQL}, a.caller_memory_notice_line, "
    "a.caller_memory_enabled, a.inbound_silenced_at, a.inbound_silence_reason, a.direction "
    "FROM agents a"
)

#: An agent with a live inbound line answers on it whatever its own direction (D-997), and
#: whether or not it holds an engine agent of its own (D-1019); one with no live line answers
#: only as itself, which needs its own engine agent.
_ANSWERING_AGENTS_SQL = (
    _ANSWERING_AGENT_COLUMNS + " WHERE status = 'live'"
    " AND ((engine_agent_ref IS NOT NULL AND direction IN ('inbound', 'both'))"
    " OR EXISTS (SELECT 1 FROM inbound_lines l"
    " WHERE l.agent_id = a.id AND l.archived_at IS NULL AND l.published_at IS NOT NULL"
    " AND l.engine_agent_ref IS NOT NULL))"
    " AND deleted_at IS NULL AND archived_at IS NULL ORDER BY id"
)
#: The statement itself, for `workers/maintenance`, which reads the same answering agents.
ANSWERING_AGENTS_STATEMENT = text(_ANSWERING_AGENTS_SQL)

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


def _credit_stop_words(engine: VoiceEngine, row: Any) -> dict[str, str]:
    """The credit stop's greeting and prompt for `_ANSWERING_AGENT_COLUMNS`' row."""
    recorded = engine.capabilities.records_audio
    return {
        "opening_line": credit_stop_greeting(_posture_of_row(row), call_is_recorded=recorded),
        "system_prompt": credit_stop_prompt(call_is_recorded=recorded),
    }


async def answering_refs(session: AsyncSession, *, row: Any) -> list[str]:
    """Every engine agent a caller of this agent reaches, for `_ANSWERING_AGENT_COLUMNS`'
    row: its own while it answers as itself, and each of its live lines' (D-997). A silence
    that changes what the agent says applies to all of them, or a line would go on taking
    calls the agent has stopped taking."""
    answers_as_itself = row[1] and agent_answers_inbound(cast(AgentDirection, str(row[10])))
    own = [str(row[1])] if answers_as_itself else []
    return own + await live_line_refs(session, agent_id=UUID(str(row[0])))


async def _override_answering(
    session: AsyncSession, engine: VoiceEngine, *, row: Any, opening_line: str, system_prompt: str
) -> None:
    """Say `opening_line` and `system_prompt` on every engine agent `answering_refs` names.
    Raises on the first vendor refusal, for the caller's per-agent isolation."""
    for target in await answering_refs(session, row=row):
        await engine.override_call_script(
            target, opening_line=opening_line, system_prompt=system_prompt
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
        agent_id, reason = row[0], row[9]
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
                    await _override_answering(
                        session, engine, row=row, **_credit_stop_words(engine, row)
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
    # Its own engine agent and its live lines' (D-997): a broken voice is broken on each.
    targets = await answering_refs(session, row=row)
    if not targets:
        return "not_answering"
    if row[9] == INBOUND_SILENCE_TRUTHFUL_ANSWER:
        # Its numbers are already unbound; nothing reaches it to hold.
        return "held"
    recorded = engine.capabilities.records_audio
    posture = _posture_of_row(row)
    from apps.api.campaigns.engine_numbers import forward_agent_numbers, numbers_can_forward

    if forward_to and numbers_can_forward() and engine.capabilities.has("script_override"):
        # A number-level forward (D-743): every call to the agent's numbers rings the
        # client's own phone, whether or not the agent answers (OPERATIONS gate T-26). The
        # agent is paused first, so a number the platform refuses to forward still answers
        # with the polite sentence rather than the broken agent.
        await _override_answering(session, engine, row=row, **_credit_stop_words(engine, row))
        forwarded = await forward_agent_numbers(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=forward_to
        )
        held: HealerHold = "forwarded" if forwarded else "paused"
    elif forward_to and isinstance(engine, ForwardsLine):
        for target in targets:
            await engine.forward_line(
                target,
                phone_e164=forward_to,
                line=HEALER_FORWARD_LINE,
                opening_line=healer_forward_greeting(posture, call_is_recorded=recorded),
                system_prompt=healer_forward_prompt(call_is_recorded=recorded),
            )
        held = "forwarded"
    elif engine.capabilities.has("script_override"):
        await _override_answering(session, engine, row=row, **_credit_stop_words(engine, row))
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
    # None for an agent answering only through its lines (D-1019).
    ref: str | None = str(row[1]) if row[1] else None
    reason = row[9]
    silenced_for_compliance = reason == INBOUND_SILENCE_TRUTHFUL_ANSWER
    if not await answering_refs(session, row=row):
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
    routing = await route_inbound_numbers(
        session,
        engine,
        agent_id=agent_id,
        ref=ref,
        answers=agent_answers_inbound(cast(AgentDirection, str(row[10]))),
        lines_answer=True,
    )
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
    ref: str | None,
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
    try:
        if ref and agent_answers_inbound(cast(AgentDirection, str(row[10]))):
            # Only the agent's own: its lines are republished after this and each holds the
            # stop itself (`publish_line`'s `_hold_line_if_silenced`).
            await engine.override_call_script(ref, **_credit_stop_words(engine, row))
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

    * the claims on the OLD agent's knowledge copies leave the agent, so the D-689 catch-up
      this publish runs attaches every live source to the new one. Kept as the test copy
      (below), the old agent keeps its copies and they become the copy's claims (D-964);
      otherwise they go — those copies are deleted with the old agent (`DELETE /agents/{id}`
      "takes the agent's knowledge with it", agents.md:82). An experiment arm's claims are
      its own vendor agent's and go when that arm moves (`publish_variant`);
    * the old agent's deletion is owed through the outbox, so it runs only after this
      transaction commits. Its route stays active until then, so a late delivery for a call
      it took before the move still verifies; the retire job switches it off.
    """
    log.warning("engine_agent_moved_to_client_workspace", extra={"agent_id": str(agent_id)})
    params = {"aid": agent_id, "tid": tenant_id}
    if scope_of(old_ref) is None and not await _has_any_number(session, agent_id=agent_id):
        # FOUNDER OPTION A (D-859): the developer-workspace copy stays, so the owner's test
        # calls can ring through the shared trial line until the client has its own number;
        # its route stays active so those calls report back. The hourly sweep retires it
        # once the client has a number or it sits unused (`workers/agent_moves`). Recorded
        # first, so a copy it replaces has released its claims before these become the
        # copy's. `updated_at` is left alone: it orders which digest is a source's newest.
        await _record_test_copy(session, None, tenant_id=tenant_id, agent_id=agent_id, ref=old_ref)
        await session.execute(
            text(
                "UPDATE engine_kb_routes SET test_copy = true WHERE agent_id = :aid "
                "AND tenant_id = :tid AND variant_id IS NULL AND NOT test_copy "
                "AND inbound_line_id IS NULL AND campaign_id IS NULL"
            ),
            params,
        )
        return
    await session.execute(
        text(
            "DELETE FROM engine_kb_routes WHERE agent_id = :aid AND tenant_id = :tid "
            "AND variant_id IS NULL AND NOT test_copy AND inbound_line_id IS NULL "
            "AND campaign_id IS NULL"
        ),
        params,
    )
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


#: The agent's own knowledge claims: not an arm's, a test copy's, a line's or a campaign's.
_OWN_CLAIMS_WHERE: Final = (
    "agent_id = :aid AND tenant_id = :tid AND variant_id IS NULL AND NOT test_copy "
    "AND inbound_line_id IS NULL AND campaign_id IS NULL"
)


async def hand_over_engine_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    ref: str,
    line_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> None:
    """The agent stops holding `ref` (D-1019), in the caller's transaction, after locking the
    agent row. Given to a line or a campaign that adopts it, its knowledge copies become that
    holder's claims, moved BEFORE the holder's publish so its knowledge catch-up finds them
    rather than attaching every source a second time. Given to nobody, the copies go with
    the vendor agent and its deletion is owed through the outbox (`retire_engine_agent`);
    its route stays active until then, so a late result of its last calls still lands."""
    params = {"aid": agent_id, "tid": tenant_id, "ref": ref}
    if line_id is not None or campaign_id is not None:
        await session.execute(
            text(
                # `updated_at` left alone: it orders which digest is a source's newest.
                "UPDATE engine_kb_routes SET inbound_line_id = :lid, campaign_id = :cid "
                f"WHERE {_OWN_CLAIMS_WHERE}"
            ),
            {**params, "lid": line_id, "cid": campaign_id},
        )
    else:
        await session.execute(
            text(f"DELETE FROM engine_kb_routes WHERE {_OWN_CLAIMS_WHERE}"), params
        )
        await retire_engine_agent(session, tenant_id=tenant_id, agent_id=agent_id, ref=ref)
    await session.execute(
        text(
            "UPDATE agents SET engine_agent_ref = NULL, updated_at = now() "
            "WHERE id = :aid AND engine_agent_ref = :ref"
        ),
        params,
    )


def _refuse_adoption(adopt_ref: str, *, held: str | None, config: AgentConfig) -> None:
    """A holder may adopt the agent's engine agent only while it holds none of its own (or
    already holds that one), and only in the workspace its config is for: an agent cannot
    move between workspaces, and recreating it would unbind the numbers it answers."""
    if held not in (None, adopt_ref) or _moves_workspace(adopt_ref, config):
        raise ProblemError.conflict(
            "engine_agent_not_adoptable",
            "This setup cannot take over its agent's calling setup.",
            remediation="Nothing was changed. Put it live the usual way instead.",
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


async def _copy_needs_replacing(
    session: AsyncSession, engine: VoiceEngine, *, agent_id: UUID, ref: str
) -> bool:
    """Does the test copy `ref` hold knowledge none of our claims names? See
    `kb.service.copy_holds_unrecorded_knowledge`."""
    # Imported here: `kb.service` imports `agents.t0`, which imports this module.
    from apps.api.kb.service import copy_holds_unrecorded_knowledge

    replace = await copy_holds_unrecorded_knowledge(session, engine, agent_id=agent_id, ref=ref)
    if replace:
        log.warning("agent_test_copy_replaced_unrecorded", extra={"agent_id": str(agent_id)})
    return replace


def _vendor_says_gone(exc: BaseException) -> bool:
    """The vendor no longer holds the agent written to (a 404, or our not-found)."""
    if isinstance(exc, EngineRejectedError):
        return exc.vendor_status == 404
    return isinstance(exc, ProblemError) and exc.kind == "not_found"


async def _record_published(
    session: AsyncSession, engine: VoiceEngine, *, ref: str, config: AgentConfig
) -> None:
    """Stamp `ref`'s route with what this publish sent (`engine/publish_view.publish_digest`),
    in the publish's transaction, so a publish that rolls back leaves the last one standing.

    `config` is the holder's config as composed, before the workspace placement swaps in that
    workspace's id for the same voice: the admin screen digests `line_config` /
    `campaign_config` and the rest the same way, and the two must be like for like. The
    vendor already holds this publish, so a config the view cannot render is logged and the
    previous record cleared rather than failing it; the screen then reads "not recorded"."""
    try:
        sent = publish_digest(engine, config)
    except ProblemError as refused:
        log.warning(
            "engine_publish_digest_not_recorded",
            extra={"agent_id": config.agent_id, "reason": refused.code},
        )
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET published_digest = NULL, published_at = NULL "
                "WHERE engine = :engine AND engine_agent_ref = :ref"
            ),
            {"engine": engine.name, "ref": ref},
        )
        return
    await session.execute(
        text(
            "UPDATE engine_agent_routes SET published_digest = :digest, "
            "published_instructions_chars = :instructions, published_greeting_chars = :greeting, "
            "published_payload_bytes = :bytes, published_training_cut_chars = :cut, "
            "published_at = now() WHERE engine = :engine AND engine_agent_ref = :ref"
        ),
        {
            "digest": sent.sha256,
            "instructions": sent.instructions_chars,
            "greeting": sent.greeting_chars,
            "bytes": sent.payload_bytes,
            "cut": config.training_cut_chars,
            "engine": engine.name,
            "ref": ref,
        },
    )


async def _record_test_copy(
    session: AsyncSession,
    engine: VoiceEngine | None,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    ref: str,
    business_only: bool = False,
) -> None:
    """Record `ref` as the agent's test copy, with its active route; a copy it held under
    another handle is retired, and its knowledge claims released (they belong to the vendor
    agent being deleted). `engine` names the route's engine (the active one if None);
    `business_only`, which config the copy now holds (`agents/business_only`)."""
    # Imported here: `kb.service` imports `agents.t0`, which imports this module.
    from apps.api.kb.service import release_test_copy_claims

    previous = await test_copy_ref(session, agent_id)
    if previous is not None and previous != ref:
        await release_test_copy_claims(session, tenant_id=tenant_id, agent_id=agent_id)
    await session.execute(
        text(
            "INSERT INTO agent_test_copies (id, tenant_id, agent_id, engine_agent_ref, "
            "business_only) VALUES (:id, :tid, :aid, :ref, :business) ON CONFLICT (agent_id) "
            "DO UPDATE SET engine_agent_ref = EXCLUDED.engine_agent_ref, "
            "business_only = EXCLUDED.business_only, updated_at = now()"
        ),
        {"id": uuid7(), "tid": tenant_id, "aid": agent_id, "ref": ref, "business": business_only},
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


async def write_ai_line(
    session: AsyncSession, *, agent_id: UUID, old: str, fresh: str, recording: str
) -> None:
    """Replace the agent's AI sentence `old` with `fresh`. The legacy bundle follows only
    where it is still the default bundle of the two sentences."""
    # Imported here: `compliance.disclosure` reaches this module through `optout` and ingest.
    from apps.api.compliance.disclosure import bundled_disclosure_line

    await session.execute(
        text(
            "UPDATE agents SET ai_disclosure_line = :line, "
            "disclosure_line = CASE WHEN disclosure_line = :old_bundle THEN :bundle "
            "ELSE disclosure_line END, updated_at = now() "
            "WHERE id = :aid AND deleted_at IS NULL"
        ),
        {
            "aid": agent_id,
            "line": fresh,
            "old_bundle": bundled_disclosure_line(
                ai_disclosure_line=old, recording_notice_line=recording
            ),
            "bundle": bundled_disclosure_line(
                ai_disclosure_line=fresh, recording_notice_line=recording
            ),
        },
    )


async def _ai_line_as_taught(session: AsyncSession, agent: AgentRow) -> AgentRow:
    """`agent` with its default AI sentence saying the names as the script being published
    teaches them, written to the row first (`disclosure.taught_ai_disclosure`). A publish is
    the one door every script change reaches the line through, so the sentence follows a
    newly taught name there."""
    # Imported here: both reach this module (`voice_pick` through the voice catalogue,
    # `compliance.disclosure` through `optout` and ingest).
    from apps.api.agents.voice_pick import voice_gender
    from apps.api.compliance.disclosure import taught_ai_disclosure

    old = str(agent["ai_disclosure_line"])
    fresh = taught_ai_disclosure(
        old,
        language=str(agent["language_primary"]),
        business=str(agent.get("business_name") or ""),
        name=str(agent["name"]),
        gender=await voice_gender(session, agent["engine_voice_id"]),
        body=agent["prompt"],
    )
    if fresh is None:
        return agent
    await write_ai_line(
        session,
        agent_id=UUID(str(agent["id"])),
        old=old,
        fresh=fresh,
        recording=str(agent["recording_notice_line"]),
    )
    log.info("agent_ai_line_taught_names", extra={"agent_id": str(agent["id"])})
    taught = agent.copy()
    taught["ai_disclosure_line"] = fresh
    return taught


async def _refuse_during_maintenance(session: AsyncSession) -> None:
    """Refuse an engine write of what callers hear while a maintenance window drains or is
    active (D-544): it would overwrite the maintenance message. `publish_agent` argues why
    the refusal sits at the engine write; `publish_line` asks the same for a line's agent."""
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
                f"{window.ends_at.astimezone(IST):%H:%M} IST). Nothing you have "
                "saved is lost — your changes are still here and will publish afterwards. "
                "Your agents keep answering calls throughout."
            ),
            status=409,
            remediation="Publish again once the maintenance window has finished.",
        )


@overload
async def publish_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    take_calls: bool = ...,
    onto_test_copy: Literal[True],
    business_only: bool = ...,
    first_publish: bool = ...,
    in_client: bool = ...,
) -> str:
    """Typing only: a test copy is always made, so its handle is always returned."""


@overload
async def publish_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    take_calls: bool = ...,
    onto_test_copy: bool = ...,
    business_only: bool = ...,
    first_publish: bool = ...,
    in_client: bool = ...,
) -> str | None:
    """Typing only: None for an agent published without an engine agent of its own."""


async def publish_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    take_calls: bool = True,
    onto_test_copy: bool = False,
    business_only: bool = False,
    first_publish: bool = False,
    in_client: bool = False,
) -> str | None:
    """Create or update the agent on the engine, VERIFY it, then record the mapping.

    Returns the engine agent's handle, or None for an agent that holds none of its own
    (D-1019): with `agents_hold_engine_agent` off, an agent that does not already hold one
    is published without one (`_publish_without_engine_agent`) and answers and calls only
    through its live inbound lines and running campaigns. A test copy is always made.

    `take_calls=False` is "Ready, not taking calls" (D-838): the agent is published and read
    back like any other, so the Try it chat talks to it, but its status is left as it is, no
    number is bound to it and the go-live checks are not asked. An agent already live is
    republished as live whatever this says, so no caller can unbind a working line with it.

    `onto_test_copy=True` (D-859, founder option A) publishes the same config onto the
    agent's TEST COPY in our developer workspace instead (`agent_test_copies`), made again if
    it is gone: the engine agent a paying client's test call rings through on the shared trial
    line before the client has a number. With `business_only` the copy is published as "Just
    the business" (`agents/business_only`): the company training and knowledge and no job's
    script, which the agent page's chat and test calls try. The agent's own row, numbers,
    status and arms are not touched; the copy gets its route, results webhook, facts
    document, in-call actions and the client's published knowledge as its own claimed copies
    (D-964). A copy holding knowledge no claim names (kept by a move before D-964) is
    replaced by a new one.

    `in_client` (with `onto_test_copy`, D-1020) makes the copy in the client's own workspace
    instead, for a paying account's test call from its own number: the platform places a call
    only from a number in the calling agent's workspace. A new copy there takes one of the
    workspace's few engine agents, so it is refused `engine_agent_allowance_full` when none is
    free. A copy found in the other workspace than the one asked for is made again in the
    right one and the old one retired, so one agent never has two.

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
    # deep (`set_caller_has_screen`, `set_caller_memory`, `apply_to_live` — each a route
    # holding `Depends(db)`), so a third connection puts the whole chain past the pool's
    # overflow: under saturation every task at that depth waits for a connection only
    # another task at that depth can release.
    #
    # `platform_maintenance_windows` carries no RLS (it is platform state — see
    # `db/registry.RLS_EXEMPT_TENANT_COLUMNS`), so the tenant session already in hand can
    # read it. One query on an open connection, never stale, and no new connection at all —
    # the same argument `ops/service.read_halt_state` makes for reading the halt on the
    # caller's session rather than through the hot-path cache.
    await _refuse_during_maintenance(session)

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
    #
    # Not asked of a republish of an agent already live (D-926): it puts nothing new on
    # the phone, and refusing it only keeps the agent answering on older text — older
    # call rules and notices included — while it carries on taking calls. A document
    # re-accepted at a new version still gates going live, a test copy and outbound
    # dialling (`agreements_blocker`).
    if onto_test_copy or agent["status"] != "live":
        await assert_agreements_accepted(session, tenant_id=tenant_id)
    # A FREE-TRIAL ACCOUNT'S AGENT PLACES TEST CALLS AND ANSWERS NOTHING (D-697): it has no
    # number until it pays, so an answer-only agent is refused with the step that unlocks it.
    trial_account = await restricting_trial(session, tenant_id=tenant_id) is not None
    # A trial's agent and a paying client's test copy are made in our developer workspace,
    # except a copy for a test call from the client's own number (D-1020).
    if in_client and (not onto_test_copy or trial_account):
        raise ValueError("in_client is for a paying account's test copy only")
    in_developer = trial_account or (onto_test_copy and not in_client)
    takes_calls = (take_calls or agent["status"] == "live") and not onto_test_copy
    if trial_account and takes_calls and agent["direction"] == "inbound":
        await refuse_on_trial(session, tenant_id=tenant_id, locked="inbound")

    # AN ARCHIVED AGENT IS NEVER RESURRECTED BY A REPUBLISH (D-440), and the guard is here
    # rather than only in `agents/lifecycle.py` because this function ends in
    # `status = 'live'` and has seven callers — the lifecycle activate, the admin publish
    # route, `apply_to_live`, `set_call_cap`, `set_caller_has_screen`, a prompt write and
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
    agent = await _ai_line_as_taught(session, agent)
    if onto_test_copy and business_only:
        from apps.api.agents.business_only import business_row

        agent = await business_row(session, tenant_id=tenant_id, agent=agent)
    # An agent already ready (live or paused) with no engine agent of its own stays without
    # one (D-1019), whatever `agents_hold_engine_agent` says: a settings save on it republishes
    # its lines and campaigns, and must not take one of the client's few workspace slots
    # by creating an engine agent nobody asked for. While the setting is on, a first publish
    # of a draft (`first_publish`: a caller that moved the agent out of draft in this
    # transaction says so) still creates one; once it is off, nothing does.
    holds_none = (
        not onto_test_copy
        and not agent["engine_agent_ref"]
        and (
            not get_settings().agents_hold_engine_agent
            or (not first_publish and agent["status"] in ("live", "paused"))
        )
    )
    # Getting a draft ready with nothing to say is still refused (`_to_config`,
    # `agent_has_no_script`): only an agent already ready is stamped with its name alone.
    if holds_none and not first_publish and not str(agent.get("prompt") or "").strip():
        # Nothing of the agent's own is sent anywhere: this config only stamps the voice it
        # speaks in, and each line and campaign composes its own script over the agent
        # (`line_config`, `campaign_config`). An agent with no script of its own is normal now.
        agent = cast(AgentRow, {**dict(agent), "prompt": f"{agent['name']}."})
    config = _to_config(tenant_id, agent, engine=engine, handoff=handoff)
    if onto_test_copy:
        # A test copy can sit in the same workspace as the agent's own engine agent (the
        # client's, or ours for an agent made before D-693): its own find-by-name tag, or
        # making the copy would find the agent's and write over it.
        config = config.model_copy(update={"holder": "test_copy"})
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
    composed = config

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
    if (
        onto_test_copy
        and existing_ref
        and (
            # A client-workspace copy cannot ring from the shared test line, which is ours.
            (in_developer and scope_of(existing_ref) is not None)
            or await _copy_needs_replacing(session, engine, agent_id=agent_id, ref=existing_ref)
        )
    ):
        # Made afresh below; `_record_test_copy` retires the old one.
        existing_ref = None
    if onto_test_copy and in_client and not existing_ref:
        await _refuse_if_allowance_full(
            session, tenant_id=tenant_id, workspace=config.engine_workspace, context="test_call"
        )
    if holds_none:
        # An agent holding no engine agent of its own (D-1019). `live` is still only written
        # here: what callers reach is its lines' and campaigns' engine agents, each read back
        # by its own publish in this same transaction (`_publish_without_engine_agent`), so
        # a refused read-back rolls this status back with it.
        result = await session.execute(
            text(
                (
                    "UPDATE agents SET engine_agent_ref = NULL, engine = :engine, status = 'live', "
                    if takes_calls
                    else "UPDATE agents SET engine_agent_ref = NULL, engine = :engine, "
                )
                + "live_tts_voice = :live_voice, live_tts_provider = :live_provider, "
                "voice_settings = CAST(:voice_settings AS jsonb), updated_at = now() "
                "WHERE id = :aid AND deleted_at IS NULL AND status <> 'archived'"
            ),
            {
                "engine": engine.name,
                "aid": agent_id,
                "live_voice": voice_id_of(config.models.tts_model, config.models.tts_voice),
                "live_provider": config.models.tts_provider,
                "voice_settings": json.dumps(stamp_of(config, engine)),
            },
        )
        if rowcount_of(result) == 0:
            raise _deleted_during_publish()
        await _publish_without_engine_agent(
            session,
            engine,
            tenant_id=tenant_id,
            agent=agent,
            takes_calls=takes_calls,
        )
        return None
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
            if in_developer:
                with trial_agent_in_developer_workspace():
                    ref = await engine.create_agent(config)
            else:
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
                session,
                engine,
                tenant_id=tenant_id,
                agent_id=agent_id,
                ref=ref,
                business_only=business_only,
            )
            await _record_published(session, engine, ref=ref, config=composed)
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
                engine,
                session,
                agent_id=agent_id,
                ref=ref,
                reclaim=False,
                script=agent["prompt"],
                test_copy=True,
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
            raise _deleted_during_publish()
        # D-836: its own call outcomes, drafted once, queued in this transaction so a failed
        # publish queues nothing. A no-op for an agent that has them or was drafted before.
        await call_outcomes.queue_draft(session, tenant_id=tenant_id, agent_id=agent_id)
        # D-889: the first look at whether its jobs' lead details fit the business, once each.
        await field_suggestions.queue_agent(
            session, tenant_id=tenant_id, agent_id=agent_id, first=True
        )
        # Whether its callers follow along on their phone, for an agent never judged.
        await caller_help.queue_first_pass(session, tenant_id=tenant_id, agent_id=agent_id)
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
        await _record_published(session, engine, ref=ref, config=composed)
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
            session,
            engine,
            agent_id=agent_id,
            ref=ref,
            answers=answers_inbound,
            lines_answer=takes_calls,
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
            # An agent answering only on its live lines (D-997) keeps its silence too.
            answers=answers_inbound
            or (takes_calls and bool(await live_line_refs(session, agent_id=agent_id))),
            # THE ONLY TRUE THIS ARGUMENT EVER TAKES (D-564), and it is the read-back's own
            # word rather than an inference from "the publish did not raise". `publish_agent`
            # refuses only `not_applied`; `unreadable` and `unreachable` reach this line
            # having proven nothing, and a compliance silence must outlive a publish that
            # proved nothing.
            truthful_answer_proven=verdict.truthful_answer_applied is True,
        )
        await republish_running_variants(session, tenant_id=tenant_id, agent_id=agent_id)
        # The agent's lines speak in its voice: a voice, setting, notice, action or
        # training change reaches the calls they answer too (D-997).
        await republish_lines(session, tenant_id=tenant_id, agent_id=agent_id)
        # And its running campaigns, each its own engine agent in this voice (D-1003).
        await republish_campaign_agents(session, tenant_id=tenant_id, agent_id=agent_id)
        # An opening put live without the notices switched on is rewritten to say them in
        # its own words (D-971); the stored sentences are said beside it until then.
        await queue_opening_notices(session, tenant_id=tenant_id, agent_id=agent_id)
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


def _deleted_during_publish() -> ProblemError:
    return ProblemError.conflict(
        "agent_deleted_during_publish",
        "This agent was deleted or archived while it was being published.",
        remediation=(
            "Nothing was recorded as live. Restore the agent, or recreate it if it is still needed."
        ),
    )


async def _publish_without_engine_agent(
    session: AsyncSession,
    engine: VoiceEngine,
    *,
    tenant_id: UUID,
    agent: AgentRow,
    takes_calls: bool,
) -> None:
    """The rest of `publish_agent` for an agent that holds no engine agent of its own
    (D-1019), after its row is written there.

    Every check and the config are `publish_agent`'s, so an agent its lines and campaigns
    could not carry is refused exactly as before. Nothing is written at the vendor of its
    own. Its numbers on no live line are released, because nothing of its own answers them,
    and its live lines and running campaigns are republished in its voice, each read back by
    its own publish. The voice mirror `publish_agent` wrote is the voice they are republished
    with, which clears the voice-divergence banner as any publish does.
    """
    agent_id = UUID(str(agent["id"]))
    await call_outcomes.queue_draft(session, tenant_id=tenant_id, agent_id=agent_id)
    await field_suggestions.queue_agent(session, tenant_id=tenant_id, agent_id=agent_id, first=True)
    await caller_help.queue_first_pass(session, tenant_id=tenant_id, agent_id=agent_id)
    routing = await route_inbound_numbers(
        session, engine, agent_id=agent_id, ref=None, answers=False, lines_answer=takes_calls
    )
    await _warn_if_answering_nothing(
        session,
        agent_id=agent_id,
        answers_inbound=takes_calls and agent_answers_inbound(agent["direction"]),
        routing=routing,
        through_lines_only=True,
    )
    await _settle_inbound_silence(
        session,
        engine,
        tenant_id=tenant_id,
        agent_id=agent_id,
        ref=None,
        answers=takes_calls and bool(await live_line_refs(session, agent_id=agent_id)),
        # Nothing of its own was read back, so a compliance silence outlives this publish;
        # the drift sweep of its lines' engine agents is what lifts it.
        truthful_answer_proven=False,
    )
    await republish_running_variants(session, tenant_id=tenant_id, agent_id=agent_id)
    await republish_lines(session, tenant_id=tenant_id, agent_id=agent_id)
    await republish_campaign_agents(session, tenant_id=tenant_id, agent_id=agent_id)
    await queue_opening_notices(session, tenant_id=tenant_id, agent_id=agent_id)
    log.info(
        "agent_published",
        extra={"agent_id": str(agent_id), "engine": engine.name, "verify_state": "no_engine_agent"},
    )


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
    ref = parse_hosted_voice_id(voice)
    states_key = not (byok_in_force(engine) or engine.capabilities.is_ours("tts"))
    own_voice_key = (ref is not None and ref.source == "byok") if states_key else None
    # OUR model (D-764): the agent's own choice of a Google model, else the console default.
    # A free-trial agent gets it too (D-834): its publish verifies our developer workspace.
    own_model = (
        own_model_for(agent.get("engine_model_id")) if states_key and own_model_on(engine) else None
    )
    # An agent on our model is answered by our key's model on calls whatever its `model`
    # says (`byok` `llm`/`llm_voice`, bring-your-own-keys.md:72-75 in the 2026-10-19 mirror),
    # so it is not sent the console's in-call default: that default is a vendor model for
    # agents on the vendor's, and one the vendor later drops would refuse every publish
    # (`model` "is not one we offer") for a field no call reads. Without our model, an agent
    # that chose none gets the default, so a change of it reaches each agent at its next
    # publish and never mid-call; it is checked when the setting is written
    # (`engine_choice.assert_in_call_default_usable`).
    if own_model is None:
        model = model or in_call_default_model(engine, voice_id=voice)
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
    # an arm carries the client's knowledge like the agent (D-689), and its training.
    return _with_client_sections(arm.model_copy(update={"training_cut_chars": 0}), agent, engine)


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
    composed = config
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
    await _record_published(session, engine, ref=ref, config=composed)
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

    A record rather than five positional arguments because a mis-ordered
    `(label, body, disclosure)` triple would publish an arm whose AI-disclosure sentence
    is its script. mypy cannot see that in three `str` positionals; it can here. Only
    tests already running are republished (`_VARIANT_CONFIG_SQL`); new per-agent tests
    are refused (D-1019).
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


def _line_agent_row(agent: AgentRow, script: CallScript, body: str) -> AgentRow:
    """The agent's row with an inbound line's script in place of its own, so `_to_config`
    builds the line's engine agent exactly as it builds the agent's, and a config field added
    for agents reaches lines with it (the reason `_variant_config` is built on `_to_config`).
    The pinned facts and the [T0 FACTS] block come from the agent's applied body, as an arm's
    do (`_arm_script`): the knowledge is the client's, the script alone is the line's."""
    line_agent: dict[str, Any] = dict(agent)
    line_agent["prompt"] = with_knowledge_of(agent["prompt"], body, identity=f"{agent['name']}.")
    line_agent["structured_script"] = script.model_dump(mode="json")
    return cast(AgentRow, line_agent)


async def line_config(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    line_id: UUID,
    agent: AgentRow | None = None,
    script: CallScript | None = None,
    training_gives_way: bool = True,
) -> AgentConfig:
    """An inbound line's engine agent as our tables say it should be (D-997), before any
    workspace placement: the agent's config over the line's script, named for the line, with
    the agent's actions the line switches off left out. What `publish_line` writes, and what a
    knowledge attach on the line's ref re-sends, because an attach replaces the whole agent
    on the platform (`kb/service._publish_config`, D-488), as it does for an arm.

    `script` stands in for the saved one, so a save is measured on what put-live would send
    before it is stored (`script_builder.refuse_job_if_too_long`)."""
    from apps.api.actions import service as actions_service
    from apps.api.agents.script_builder import line_collect_fields

    line = (
        await session.execute(
            text(
                "SELECT agent_id, name, script, actions_off FROM inbound_lines "
                "WHERE id = :lid AND archived_at IS NULL"
            ),
            {"lid": line_id},
        )
    ).first()
    if line is None:
        raise ProblemError.not_found("Inbound line")
    if script is None and not line.script:
        raise ProblemError.business_rule(
            "line_has_no_script",
            "This line has no script yet.",
            remediation="Write its main task and press Generate, or write the script yourself.",
        )
    agent_id = UUID(str(line.agent_id))
    if agent is None:
        agent = await _load_agent(session, tenant_id, agent_id)
    engine = get_engine()
    if script is None:
        script = CallScript.model_validate(line.script)
    body = compile_call_script(script, collect=await line_collect_fields(session, line_id))
    handoff, _duty = await handoff_module.spec_for(session, dict(agent))
    off = set(line.actions_off or ())
    tools = await actions_service.declare(session, agent_id=agent_id, direction="inbound")
    return _to_config(
        tenant_id,
        _line_agent_row(agent, script, body),
        engine=engine,
        handoff=handoff,
        keep_placed_opening=True,
        training_gives_way=training_gives_way,
        holder_fields={
            "holder": str(line_id),
            "name": f"{agent['name']} · {line.name}",
            "direction": "inbound",
            # It also places its voice's call-backs and lead calls (D-1019 D2).
            "places_call_backs": True,
            "action_tools": tuple(tool for tool in tools if tool.name not in off),
        },
    )


async def publish_line(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    line_id: UUID,
    test: bool = False,
    adopt_ref: str | None = None,
    in_client: bool = False,
) -> str:
    """Create or update an inbound line's own engine agent (D-997): its agent's config, voice,
    settings, notices and the company training, over the line's script, with the agent's
    actions the line switches off left out. Read back like every publish, routed for intake
    (`engine_agent_routes.inbound_line_id`), given its results webhook, the client's
    knowledge and the in-call actions. A vendor agent this publish created and could not
    finish is reclaimed.

    `test=True` publishes it as a TEST HOLDER, for the owner's test call of a draft line
    (Phase 3b): the same engine agent, but `published_at` is left as it was, so a draft line
    stays a draft and no number is routed to it (`route_line_numbers` routes live lines only).
    It is made in our developer workspace, where the shared test line rings (D-697, D-1018),
    unless `in_client`: a paying account with a number of its own tests from that number
    (D-1020), so the holder is made in the client's workspace, where the platform places calls
    from its numbers. There it takes one of the workspace's few engine agents while it exists,
    so a new one is refused `engine_agent_allowance_full` when none is free, and the caller
    falls back to the developer workspace. Its first live publish keeps a client-workspace
    holder in place and recreates a developer one there (`_moves_workspace`); the hourly
    sweep retires a draft's holder once idle, wherever it is.

    The line's numbers are not touched here: `inbound/publish.put_line_live` attaches them
    after this commits, so a number never points at an agent the transaction rolled away.

    `adopt_ref` is the agent's own engine agent, taken over in place by a line that holds
    none (D-1019, `agents/engine_retirement`): updated to the line's config and name tag and
    read back like any publish, so the numbers it answers stay bound to the same object and
    callers hear no gap. Never reclaimed on a failure, since it was not made here. A live
    publish only: a test holder is made in our developer workspace."""
    if not test:
        # A test holder answers no caller, so the maintenance message has nothing to lose.
        await _refuse_during_maintenance(session)
    # The tenant's knowledge lock before any row, as `lifecycle.archive_agent` takes it: the
    # two serialise, so either the archive counts this line live and refuses, or this
    # publish reads the agent archived below and refuses. Without it both read the other's
    # state from before, and a line went live in a deleted agent's voice. Imported here:
    # `kb.service` imports `agents.t0`, which imports this module.
    from apps.api.kb.service import lock_tenant_knowledge

    await lock_tenant_knowledge(session, tenant_id=tenant_id)
    line = (
        await session.execute(
            text(
                "SELECT agent_id, engine_agent_ref FROM inbound_lines "
                "WHERE id = :lid AND archived_at IS NULL FOR UPDATE"
            ),
            {"lid": line_id},
        )
    ).first()
    if line is None:
        raise ProblemError.not_found("Inbound line")
    agent_id = UUID(str(line.agent_id))
    agent = await _load_agent(session, tenant_id, agent_id)
    if agent["status"] == "archived":
        # Deleting an agent is refused while a live line speaks for it
        # (`lifecycle._assert_no_line_is_answering`); a draft line is let through there, so
        # it is refused here, before it can answer in a deleted agent's voice.
        raise ProblemError.conflict(
            "line_agent_deleted",
            "The agent this line speaks for was deleted.",
            remediation="Choose another agent for this line, or bring that agent back.",
        )
    engine = get_engine()
    refuse_unoffered_language(str(agent["language_primary"]), tenant_id=tenant_id)
    config = await line_config(session, tenant_id=tenant_id, line_id=line_id, agent=agent)
    composed = config
    refuse_over_engine_limits(engine, config)
    await refuse_unpriced_engine(session, engine)
    if test:
        # A test holder rings the owner, so the agreements are asked as for a test copy.
        await assert_agreements_accepted(session, tenant_id=tenant_id)
    in_developer = test and not in_client
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
    existing_ref: str | None = line.engine_agent_ref
    if adopt_ref is not None:
        _refuse_adoption(adopt_ref, held=existing_ref, config=config)
        existing_ref = adopt_ref
    moved_from: str | None = None
    if existing_ref and (
        _moves_workspace(existing_ref, config)
        or (in_developer and scope_of(existing_ref) is not None)
    ):
        moved_from, existing_ref = existing_ref, None
    if existing_ref is None and not in_developer:
        await _refuse_if_allowance_full(
            session,
            tenant_id=tenant_id,
            workspace=config.engine_workspace,
            context="test_call" if test else "line_live",
        )
    if existing_ref:
        try:
            await engine.update_agent(existing_ref, config)
        except Exception as gone:
            # A draft's test holder deleted at the vendor (given back for a Start, or by
            # hand) is made again, as `publish_agent` does for a test copy; a live line's
            # engine agent answers its numbers, so losing it is the publish's failure.
            if not (test and adopt_ref is None and _vendor_says_gone(gone)):
                raise
            log.warning("line_test_holder_gone", extra={"line_id": str(line_id)})
            await session.execute(
                text(
                    "UPDATE engine_agent_routes SET active = false, updated_at = now() "
                    "WHERE engine = :engine AND engine_agent_ref = :ref"
                ),
                {"engine": engine.name, "ref": existing_ref},
            )
            await session.execute(
                text(
                    "DELETE FROM engine_kb_routes WHERE inbound_line_id = :lid AND tenant_id = :tid"
                ),
                {"lid": line_id, "tid": tenant_id},
            )
            existing_ref = None
            if not in_developer:
                await _refuse_if_allowance_full(
                    session,
                    tenant_id=tenant_id,
                    workspace=config.engine_workspace,
                    context="test_call",
                )
    if existing_ref:
        ref = existing_ref
    elif in_developer:
        with trial_agent_in_developer_workspace():
            ref = await engine.create_agent(config)
    else:
        ref = await engine.create_agent(config)
    # A line answers real callers, so it gets the agent's read-back: the notices, the
    # truthful answers and the script must be what the platform holds.
    verdict = await verify_publish(engine, ref, config)
    if verdict.state == "not_applied":
        if not existing_ref:
            await _reclaim_orphan(engine, agent_id, ref, "line_read_back_proved_not_applied")
        log.error(
            "inbound_line_publish_not_applied",
            extra={"agent_id": str(agent_id), "line_id": str(line_id), "engine": engine.name},
        )
        raise ProblemError(
            kind="dependency",
            code="engine_publish_not_applied",
            title="The voice platform is not running this change",
            detail=verdict.detail,
            remediation="Callers still hear what they heard before. Try putting it live again.",
        )
    await session.execute(
        text(
            "UPDATE inbound_lines SET engine_agent_ref = :ref, "
            # A test holder's stamp is what the hourly sweep ages it by.
            + ("engine_agent_at = now(), " if test else "published_at = now(), ")
            + "updated_at = now() WHERE id = :lid"
        ),
        {"ref": ref, "lid": line_id},
    )
    await session.execute(
        text(
            "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
            "inbound_line_id, active, created_at, updated_at) VALUES (:engine, :ref, :tid, :aid, "
            ":lid, true, now(), now()) ON CONFLICT (engine, engine_agent_ref) DO UPDATE SET "
            "tenant_id = EXCLUDED.tenant_id, agent_id = EXCLUDED.agent_id, "
            "inbound_line_id = EXCLUDED.inbound_line_id, active = true, updated_at = now()"
        ),
        {"engine": engine.name, "ref": ref, "tid": tenant_id, "aid": agent_id, "lid": line_id},
    )
    await _record_published(session, engine, ref=ref, config=composed)
    if moved_from is not None:
        from apps.api.reliability.service import enqueue_outbox

        await session.execute(
            text("DELETE FROM engine_kb_routes WHERE inbound_line_id = :lid AND tenant_id = :tid"),
            {"lid": line_id, "tid": tenant_id},
        )
        await enqueue_outbox(
            session,
            job=RETIRE_MOVED_AGENT_JOB,
            payload={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "old_ref": moved_from},
        )
    await _ensure_results_webhook(
        engine,
        ref=ref,
        agent_id=agent_id,
        reclaim=not existing_ref,
        session=session,
        rate_key=rate_key,
        own_model=config.engine_own_model,
    )
    await _publish_business_facts(
        engine,
        session,
        agent_id=agent_id,
        ref=ref,
        reclaim=not existing_ref,
        script=config.system_prompt,
        inbound_line_id=line_id,
    )
    await _ensure_in_call_actions(
        engine, session, agent_id=agent_id, ref=ref, reclaim=not existing_ref
    )
    if not test:
        await _hold_line_if_silenced(
            session, engine, tenant_id=tenant_id, agent_id=agent_id, ref=ref
        )
    log.info("inbound_line_published", extra={"agent_id": str(agent_id), "line_id": str(line_id)})
    return ref


async def _hold_line_if_silenced(
    session: AsyncSession, engine: VoiceEngine, *, tenant_id: UUID, agent_id: UUID, ref: str
) -> None:
    """A line just published has its real script on the platform; while its voice agent is
    under a credit stop or a healer hold, put the neutral sentence back on it, as
    `_settle_inbound_silence` does for the agent's own. Never starts a silence. The
    compliance silence unbinds the line's numbers instead (`route_line_numbers`).

    A refusal alarms and does not fail the publish, `_settle_inbound_silence`'s contract;
    the next reconciliation pass or healer tick holds the line again."""
    reason = (
        await session.execute(
            text("SELECT inbound_silence_reason FROM agents WHERE id = :aid"), {"aid": agent_id}
        )
    ).scalar_one_or_none()
    if reason not in (INBOUND_SILENCE_CREDITS, INBOUND_SILENCE_HEALER):
        return
    if not engine.capabilities.has("script_override"):
        return
    row = (await session.execute(text(_ONE_ANSWERING_AGENT_SQL), {"aid": agent_id})).one()
    try:
        await engine.override_call_script(ref, **_credit_stop_words(engine, row))
    except Exception as exc:
        alert(
            "CORE_LOGIC",
            "inbound_line_hold_failed",
            detail=(
                "an inbound line was put live while its agent is off its calls (no calling "
                "credit, or held by the healer) and the voice platform did not take the "
                "message that should replace its script, so the line is taking calls. "
                f"Refusal: {exc.__class__.__name__}."
            ),
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
        )


async def republish_lines(session: AsyncSession, *, tenant_id: UUID, agent_id: UUID) -> int:
    """Bring every published line in `agent_id`'s voice onto the agent's current config: a
    voice, setting, notice, action or company-training change reaches the calls its lines
    answer, as `republish_running_variants` does for arms. Each line keeps its own script.
    A draft's test holder is left alone: it answers no caller, and its test call republishes
    it first (`inbound/publish.line_test_dial`), so an agent edit is never refused for it.
    One line the platform refuses does not keep the others on the old config
    (`_republish_holder`). Returns how many were republished."""
    rows = (
        await session.execute(
            text(
                "SELECT id FROM inbound_lines WHERE agent_id = :aid AND archived_at IS NULL "
                "AND engine_agent_ref IS NOT NULL AND published_at IS NOT NULL "
                "AND script IS NOT NULL ORDER BY created_at, id"
            ),
            {"aid": agent_id},
        )
    ).scalars()
    count = 0
    for line_id in list(rows):
        holder_id = UUID(str(line_id))
        if await _republish_holder(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            kind="line",
            holder_id=holder_id,
            publish=partial(publish_line, session, tenant_id=tenant_id, line_id=holder_id),
        ):
            count += 1
    return count


#: `session.info` key under which `_republish_holder` keeps each refusal it swallowed, for a
#: caller that must not report the change as applied while a line or campaign kept the old
#: config (`live_apply.converge_agent`).
HOLDER_REFUSALS_KEY: Final = "holder_refusals"


async def _republish_holder(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    kind: Literal["line", "campaign"],
    holder_id: UUID,
    publish: Callable[[], Awaitable[object]],
) -> bool:
    """Republish one line or campaign in a savepoint, so its refusal rolls back its own rows
    only and its agent's other holders still get the agent's change. A failure alarms naming
    the holder (its engine agent keeps what it held, the notices included) and its next
    republish, a drift repair or an owner's save, tries again. True when it was republished."""
    try:
        async with session.begin_nested():
            await publish()
    except Exception as exc:
        reason = exc.code if isinstance(exc, ProblemError) else type(exc).__name__
        session.info.setdefault(HOLDER_REFUSALS_KEY, []).append(exc)
        alert(
            "CORE_LOGIC",
            "holder_republish_failed",
            detail=(
                f"An {'inbound line' if kind == 'line' else 'campaign'} was not republished "
                f"with its agent's change, so it keeps its previous settings. Refusal: {reason}."
            ),
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
            holder_id=str(holder_id),
        )
        return False
    return True


#: A campaign whose engine agent it no longer needs: archived, ended, or a test holder not
#: published for `:idle` seconds while the campaign is neither dialling nor paused. Asked by
#: the hourly sweep to pick candidates and again under the row lock before one is retired,
#: so a Start that took the row meanwhile keeps its engine agent. Binds `:holding`, `:idle`.
CAMPAIGN_AGENT_UNNEEDED_WHERE: Final = (
    "engine_agent_ref IS NOT NULL AND (archived_at IS NOT NULL "
    "OR status IN ('completed', 'cancelled') OR (NOT (status = ANY(:holding)) "
    "AND (engine_agent_at IS NULL OR engine_agent_at < now() - make_interval(secs => :idle))))"
)

#: A draft line whose test holder has not been published for `:idle` seconds. Every test
#: call through a draft line publishes its holder first (`inbound/publish.line_test_dial`),
#: which is what stamps `engine_agent_at`; the route's `updated_at` would not do, the drift,
#: webhook, facts and rate sweeps rewrite it. Binds `:idle`.
LINE_HOLDER_IDLE_WHERE: Final = (
    "published_at IS NULL AND engine_agent_ref IS NOT NULL "
    "AND (engine_agent_at IS NULL OR engine_agent_at < now() - make_interval(secs => :idle))"
)

#: How long after its last publish a test holder in a client's workspace is left to the call
#: it was made for, before a Start or a line put live may take its place. The publish commits
#: before the dial writes its call row, so for these seconds no live call can be seen on it.
TEST_HOLDER_GRACE: Final = timedelta(minutes=2)

#: A call on this engine agent that may still be connected: our own row, which a test dial
#: writes before it rings, so a call still ringing counts (the vendor's connected list would
#: miss it). Bounded by the longest test call allowed (`live_test_call_horizon`, an own-number
#: test runs longer than one on the shared line), so a lost result cannot pin it.
_HOLDER_CALL_LIVE_SQL: Final = (
    "SELECT EXISTS (SELECT 1 FROM calls WHERE engine_agent_ref = :ref "
    "AND status IN ('queued', 'ringing', 'in_progress') "
    "AND created_at > now() - make_interval(secs => :horizon))"
)


@dataclass(frozen=True, slots=True)
class CampaignDial:
    """A call rung through a campaign's own engine agent (D-1003), not its agent's: the
    campaign's script and settings in the agent's voice. Built only by
    `campaigns/engine_agent.py`, from a published, read-back engine agent."""

    ref: str
    campaign_id: UUID
    #: Made in our developer workspace for a test call on the shared trial line (D-697,
    #: D-859); False for one in the client's own workspace, rung from the client's number.
    developer: bool = False
    #: The number the campaign chose to call from (`campaigns.number_id`), carried by
    #: `dial_through` so a call-back or a person's call through the campaign presents the same
    #: caller id as its own calls. None for a campaign that chose none, and where the caller
    #: already passes the number itself (the campaign dispatcher).
    number_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class _CampaignHolder:
    campaign_id: UUID
    agent_id: UUID
    name: str
    status: str
    engine_agent_ref: str | None
    archived: bool


async def _campaign_holder(
    session: AsyncSession, campaign_id: UUID, *, lock: bool = False
) -> _CampaignHolder:
    row = (
        await session.execute(
            text(
                "SELECT id, agent_id, name, status, engine_agent_ref, archived_at IS NOT NULL "
                "FROM campaigns WHERE id = :cid" + (" FOR UPDATE" if lock else "")
            ),
            {"cid": campaign_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Campaign")
    return _CampaignHolder(
        campaign_id=UUID(str(row[0])),
        agent_id=UUID(str(row[1])),
        name=str(row[2]),
        status=str(row[3]),
        engine_agent_ref=str(row[4]) if row[4] else None,
        archived=bool(row[5]),
    )


async def campaign_agent_row(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    agent: AgentRow | None = None,
    script: CallScript | None = None,
) -> AgentRow:
    """The agent's row as the campaign's engine agent speaks it (D-1003): the campaign's
    compiled script in place of the agent's own, carrying the agent's pinned facts and
    [T0 FACTS] (`_line_agent_row`, as a line's does), its script language laid over the agent's
    (`campaigns/settings.apply_overrides`, D-994, D-1027), and calling out only. The
    one reader for the config, the dial's first words and the dial gate, so the three agree.

    A campaign with no script of its own (made before D-992) speaks the agent's script,
    asking for the campaign's own list. `script` stands in for the saved one, for a save
    measured before it is stored (`script_builder.refuse_job_if_too_long`)."""
    from apps.api.agents.script_builder import campaign_collect_fields
    from apps.api.campaigns.settings import apply_overrides

    camp = (
        await session.execute(
            text("SELECT agent_id, script, settings_overrides FROM campaigns WHERE id = :cid"),
            {"cid": campaign_id},
        )
    ).first()
    if camp is None:
        raise ProblemError.not_found("Campaign")
    agent_id = UUID(str(camp.agent_id))
    if agent is None:
        agent = await _load_agent(session, tenant_id, agent_id)
    row: AgentRow = agent
    # A campaign made before D-992 has no script of its own and speaks its agent's, compiled
    # here with the campaign's list: the agent's own compile asks for nothing (D-1028).
    own = camp.script or agent.get("structured_script")
    if script is None and own:
        script = CallScript.model_validate(own)
    if script is not None:
        collect = await campaign_collect_fields(session, campaign_id)
        body = compile_call_script(script, collect=collect)
        row = _line_agent_row(agent, script, body)
    held = cast(AgentRow, apply_overrides(dict(row), camp.settings_overrides))
    # A campaign only places calls, whatever its voice answers; it answers no number, so it
    # holds none of its own and calls out on one lent to it for each call (`dispatch_call`).
    held["direction"] = "outbound"
    held["has_phone_number"] = False
    return held


async def campaign_config(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    agent: AgentRow | None = None,
    script: CallScript | None = None,
    training_gives_way: bool = True,
) -> AgentConfig:
    """A campaign's engine agent as our tables say it should be (D-1003), before any
    workspace placement: the agent's `_to_config` over `campaign_agent_row`, so every
    platform layer (hard rule 5, the confidentiality rule, the speech rules, the notices with
    the opening) and the company training compose exactly as on the agent, with the agent's
    during-call actions. What `publish_campaign_agent` writes, what the drift sweep and the
    settings repair compare, and what a knowledge attach re-sends (`kb/service`). `script`
    stands in for the saved one, as in `campaign_agent_row`."""
    from apps.api.actions import service as actions_service

    holder = await _campaign_holder(session, campaign_id)
    if agent is None:
        agent = await _load_agent(session, tenant_id, holder.agent_id)
    row = await campaign_agent_row(
        session, tenant_id=tenant_id, campaign_id=campaign_id, agent=agent, script=script
    )
    handoff, _duty = await handoff_module.spec_for(session, dict(agent))
    tools = await actions_service.declare(session, agent_id=holder.agent_id, direction="outbound")
    return _to_config(
        tenant_id,
        row,
        engine=get_engine(),
        handoff=handoff,
        training_gives_way=training_gives_way,
        holder_fields={
            "holder": f"campaign:{campaign_id}",
            "name": f"{agent['name']} · {holder.name}"[:200],
            "action_tools": tools,
        },
    )


async def engine_agents_in_workspace(
    session: AsyncSession, *, tenant_id: UUID, workspace: str
) -> int:
    """How many engine agents this client holds in its own workspace, counted from our routes:
    every live holder (the agents', arms', lines', campaigns') and every one owed a deletion
    that has not run, which the platform still counts. Read under the tenant's own id."""
    refs = (
        await session.execute(
            text(
                "SELECT engine_agent_ref FROM engine_agent_routes "
                "WHERE tenant_id = :tid AND engine = :engine AND active"
            ),
            {"tid": tenant_id, "engine": get_engine().name},
        )
    ).scalars()
    return sum(1 for ref in refs if scope_of(str(ref)) == workspace)


async def _allowance_full(
    session: AsyncSession, *, tenant_id: UUID, workspace: str | None, spare: int = 0
) -> int | None:
    """The limit, when a NEW engine agent cannot be made in this client's own workspace
    because it holds as many as its plan allows; None when there is room or no such
    workspace. ThinnestAI counts agents per workspace, 2 on pay-as-you-go and raised per
    workspace on request (VENDOR-STATED 23 Oct 2026,
    `docs/vendor/thinnest-relationship-2026-10-23.md:136-142`), so the limit is this client's
    `workspace_agent_allowance`, never a constant; the platform's own refusal still maps to
    `engine_agent_allowance_used` if the two ever disagree. `spare`: held setups the
    attempt would give back first (`idle_test_holders_in`)."""
    if workspace is None or not is_customer_workspace(workspace):
        return None
    limit = await workspace_agent_allowance(session, tenant_id)
    held = await engine_agents_in_workspace(session, tenant_id=tenant_id, workspace=workspace)
    if held - spare < limit:
        return None
    log.info(
        "campaign_engine_agent_allowance_full",
        extra={"tenant_id": str(tenant_id), "held": held, "limit": limit},
    )
    return limit


async def _refuse_if_allowance_full(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace: str | None,
    context: AllowanceContext,
) -> None:
    """Refuse a new engine agent in a full workspace, naming what holds every setup. Start
    and putting a line live first give back the test holders in the workspace that no test
    call is on (`give_back_idle_test_holders`) and count again; a test call does not, since
    it falls back to our developer workspace instead."""
    refusal = await allowance_refusal(
        session, tenant_id=tenant_id, workspace=workspace, context=context
    )
    if (
        refusal is not None
        and context != "test_call"
        and workspace is not None
        and await give_back_idle_test_holders(session, tenant_id=tenant_id, workspace=workspace)
    ):
        refusal = await allowance_refusal(
            session, tenant_id=tenant_id, workspace=workspace, context=context
        )
    if refusal is not None:
        raise refusal


async def allowance_refusal(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    workspace: str | None,
    context: AllowanceContext,
) -> ProblemError | None:
    """The refusal a new engine agent in this workspace would get, naming what holds every
    setup; None when there is room. Returned rather than raised so a screen can say it before
    the owner presses anything."""
    limit = await _allowance_full(session, tenant_id=tenant_id, workspace=workspace)
    if limit is None:
        return None
    assert workspace is not None  # `_allowance_full` answers None without one
    holders = await slot_holders(
        session, tenant_id=tenant_id, engine=get_engine().name, workspace=workspace
    )
    return ProblemError.business_rule(
        ENGINE_AGENT_ALLOWANCE_FULL_RULE,
        allowance_reason(limit, holders, context),
        remediation=allowance_remediation(holders),
        extensions=EngineAgentAllowanceFull(context=context, limit=limit, holders=holders),
    )


async def engine_agent_allowance_blocker(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID
) -> tuple[str, str, tuple[SlotHolder, ...]] | None:
    """The launch gate's form of the pre-flight (D-1003): `(rule, reason, holders)` when Start
    would have to make this campaign a new engine agent and the client's workspace has no
    room. Test holders Start would give back count as room (`idle_test_holders_in`)."""
    if not engine_has_workspaces(get_engine().name):
        return None
    ref = (
        await session.execute(
            text("SELECT engine_agent_ref FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
        )
    ).scalar_one_or_none()
    workspace = await resolve_workspace(session, tenant_id)
    if ref and scope_of(str(ref)) == workspace:
        return None
    spare = (
        await idle_test_holders_in(session, workspace=workspace)
        if workspace is not None and is_customer_workspace(workspace)
        else 0
    )
    limit = await _allowance_full(session, tenant_id=tenant_id, workspace=workspace, spare=spare)
    if limit is None:
        return None
    assert workspace is not None  # `_allowance_full` answers None without one
    holders = await slot_holders(
        session, tenant_id=tenant_id, engine=get_engine().name, workspace=workspace
    )
    return (
        ENGINE_AGENT_ALLOWANCE_FULL_RULE,
        f"{allowance_reason(limit, holders, 'start')} {allowance_remediation(holders)}",
        tuple(holders),
    )


async def _campaign_publishable(
    session: AsyncSession, *, tenant_id: UUID, holder: _CampaignHolder
) -> tuple[AgentRow, VoiceEngine, AgentConfig]:
    """What a campaign's publish refuses before it reaches the platform: an archived campaign
    or agent, a language not offered, a script or settings over the engine's limits, an
    unpriced engine. Returns the agent, the engine and the composed config."""
    if holder.archived:
        raise ProblemError.not_found("Campaign")
    agent = await _load_agent(session, tenant_id, holder.agent_id)
    if agent["status"] == "archived":
        raise archived_refusal("used for this campaign")
    engine = get_engine()
    require_capability("agent_hosting", engine=engine)
    refuse_unoffered_language(str(agent["language_primary"]), tenant_id=tenant_id)
    config = await campaign_config(
        session, tenant_id=tenant_id, campaign_id=holder.campaign_id, agent=agent
    )
    refuse_over_engine_limits(engine, config)
    await refuse_unpriced_engine(session, engine)
    return agent, engine, config


async def check_campaign_publishable(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID
) -> None:
    """Schedule's check (D-1010): every refusal `publish_campaign_agent` makes before the
    platform, run now so a campaign that could never start is refused when it is scheduled,
    while the engine agent itself is made only when the start fires."""
    holder = await _campaign_holder(session, campaign_id)
    await _campaign_publishable(session, tenant_id=tenant_id, holder=holder)


def _campaign_test_in_developer(holder: _CampaignHolder) -> bool:
    """Whether a campaign's test holder is made in our developer workspace (D-1018) when the
    account does not test from its own number: always, unless the campaign is dialling or
    paused. The client's own workspace allows only a few engine agents (`_allowance_full`);
    ours allows 100 (VENDOR-STATED 23 Oct 2026, replies §28), the call rings from our shared
    test line, and the hourly sweep retires it once idle (`workers/campaign_engine_agents`).
    A paying account with a number of its own asks for the client's workspace instead
    (`publish_campaign_agent(in_client=True)`, D-1020).

    A running or paused campaign keeps its engine agent in the client's workspace: it is the
    one its calls ring through, and moving it to ours for a test would leave the next dial
    ringing an agent that cannot use the client's numbers. Its test rings through that same
    engine agent from the client's own number, as its dials do, and needs no new one."""
    return holder.status not in CAMPAIGN_HOLDING_STATUSES


async def campaign_test_in_developer(session: AsyncSession, *, campaign_id: UUID) -> bool:
    """`publish_campaign_agent(test=True)`'s workspace decision, for the caller that dials."""
    return _campaign_test_in_developer(await _campaign_holder(session, campaign_id))


async def publish_campaign_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    test: bool = False,
    adopt_ref: str | None = None,
    in_client: bool = False,
    require_holding: bool = False,
) -> str | None:
    """Create or update a campaign's own engine agent (D-1003): `campaign_config` read back
    like every publish, routed for intake (`engine_agent_routes.campaign_id`), given its
    results webhook, the client's knowledge and the in-call actions. A vendor agent this
    publish created and could not finish is reclaimed. Never bound to a number: each dial
    lends it one (`dispatch_call`), so the number's own answering agent is never touched.

    `test=True` is the campaign's test call (`campaigns/engine_agent.campaign_test_dial`): the
    same engine agent, published whatever the campaign's state and even during maintenance,
    since it answers no caller. Unless the campaign is running or paused it is made in our
    developer workspace, where the shared trial line rings (D-697, D-1018,
    `_campaign_test_in_developer`), except with `in_client`: a paying account with a number of
    its own tests from that number (D-1020), so the holder is made in the client's workspace,
    refused `engine_agent_allowance_full` when no engine agent is free there, which the caller
    answers by falling back to ours. A holder in the wrong workspace for this publish is
    recreated in the right one (`_moves_workspace`), and the old one is retired.

    `adopt_ref` is the agent's own engine agent, taken over in place by a running campaign
    that dials through it and holds none of its own (D-1019, `agents/engine_retirement`), as
    `publish_line` adopts one. A live publish only.

    `require_holding` is for a caller that read the campaign as holding an engine agent while
    it runs or is paused (an edit, a re-woven opening): asked again under the row lock, and
    None with nothing published when it no longer does, so a campaign stopped or whose
    engine agent was given back in between is not handed a new one.

    The tenant's knowledge lock is taken first and then the campaign row, as `publish_line`
    takes them: the row lock keeps two Starts of one campaign from making two engine agents,
    and the tenant lock keeps a Start, another campaign's and a line put live from each
    counting the same free setup in the workspace and all making one."""
    if not test:
        await _refuse_during_maintenance(session)
    # Imported here: `kb.service` imports `agents.t0`, which imports this module.
    from apps.api.kb.service import lock_tenant_knowledge

    await lock_tenant_knowledge(session, tenant_id=tenant_id)
    holder = await _campaign_holder(session, campaign_id, lock=True)
    if require_holding and (
        holder.archived
        or holder.engine_agent_ref is None
        or holder.status not in CAMPAIGN_HOLDING_STATUSES
    ):
        log.info("campaign_engine_agent_no_longer_held", extra={"campaign_id": str(campaign_id)})
        return None
    agent, engine, config = await _campaign_publishable(session, tenant_id=tenant_id, holder=holder)
    composed = config
    if test:
        # A test holder rings the owner, so the agreements are asked as for a test copy.
        await assert_agreements_accepted(session, tenant_id=tenant_id)
    in_developer = test and not in_client and _campaign_test_in_developer(holder)
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
    existing_ref = holder.engine_agent_ref
    if adopt_ref is not None:
        _refuse_adoption(adopt_ref, held=existing_ref, config=config)
        existing_ref = adopt_ref
    moved_from: str | None = None
    if existing_ref and (
        _moves_workspace(existing_ref, config)
        or (in_developer and scope_of(existing_ref) is not None)
    ):
        moved_from, existing_ref = existing_ref, None
    if existing_ref is None:
        await _refuse_if_allowance_full(
            session,
            tenant_id=tenant_id,
            workspace=config.engine_workspace,
            context="test_call" if test else "start",
        )
    if existing_ref:
        try:
            await engine.update_agent(existing_ref, config)
        except Exception as gone:
            # A test holder of a campaign not started that the platform no longer has (given
            # back for another Start, or by hand) is made again, as `publish_line` does for
            # a draft's; a running or paused campaign dials through its engine agent, so
            # losing that one is the publish's failure.
            if not (
                adopt_ref is None
                and holder.status not in CAMPAIGN_HOLDING_STATUSES
                and _vendor_says_gone(gone)
            ):
                raise
            log.warning("campaign_test_holder_gone", extra={"campaign_id": str(campaign_id)})
            await session.execute(
                text(
                    "UPDATE engine_agent_routes SET active = false, updated_at = now() "
                    "WHERE engine = :engine AND engine_agent_ref = :ref"
                ),
                {"engine": engine.name, "ref": existing_ref},
            )
            await session.execute(
                text("DELETE FROM engine_kb_routes WHERE campaign_id = :cid AND tenant_id = :tid"),
                {"cid": campaign_id, "tid": tenant_id},
            )
            existing_ref = None
            await _refuse_if_allowance_full(
                session,
                tenant_id=tenant_id,
                workspace=config.engine_workspace,
                context="test_call" if test else "start",
            )
    if existing_ref:
        ref = existing_ref
    elif in_developer:
        with trial_agent_in_developer_workspace():
            ref = await engine.create_agent(config)
    else:
        ref = await engine.create_agent(config)
    created = existing_ref is None
    # It speaks to real people with its own script and opening, so it gets the agent's
    # read-back: the notices, the truthful answers and the script must be what is held.
    verdict = await verify_publish(engine, ref, config)
    if verdict.state == "not_applied":
        if created:
            await _reclaim_orphan(engine, holder.agent_id, ref, "campaign_read_back_not_applied")
        log.error(
            "campaign_engine_agent_publish_not_applied",
            extra={
                "agent_id": str(holder.agent_id),
                "campaign_id": str(campaign_id),
                "engine": engine.name,
            },
        )
        raise ProblemError(
            kind="dependency",
            code="engine_publish_not_applied",
            title="The voice platform is not running this change",
            detail=verdict.detail,
            remediation="Nothing was changed for this campaign's calls. Try again.",
        )
    try:
        await session.execute(
            text(
                "UPDATE campaigns SET engine_agent_ref = :ref, engine_agent_at = now() "
                "WHERE id = :cid"
            ),
            {"ref": ref, "cid": campaign_id},
        )
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "campaign_id, active, created_at, updated_at) VALUES (:engine, :ref, :tid, "
                ":aid, :cid, true, now(), now()) ON CONFLICT (engine, engine_agent_ref) DO "
                "UPDATE SET tenant_id = EXCLUDED.tenant_id, agent_id = EXCLUDED.agent_id, "
                "campaign_id = EXCLUDED.campaign_id, active = true, updated_at = now()"
            ),
            {
                "engine": engine.name,
                "ref": ref,
                "tid": tenant_id,
                "aid": holder.agent_id,
                "cid": campaign_id,
            },
        )
        await _record_published(session, engine, ref=ref, config=composed)
        # A campaign moved to another voice keeps its engine agent and its knowledge copies,
        # which now belong to that voice's claims.
        await session.execute(
            text(
                "UPDATE engine_kb_routes SET agent_id = :aid "
                "WHERE campaign_id = :cid AND tenant_id = :tid AND agent_id <> :aid"
            ),
            {"aid": holder.agent_id, "cid": campaign_id, "tid": tenant_id},
        )
        if moved_from is not None:
            # The copies on the old engine agent go with it when it is deleted.
            await session.execute(
                text("DELETE FROM engine_kb_routes WHERE campaign_id = :cid AND tenant_id = :tid"),
                {"cid": campaign_id, "tid": tenant_id},
            )
            await retire_engine_agent(
                session, tenant_id=tenant_id, agent_id=holder.agent_id, ref=moved_from
            )
        await _ensure_results_webhook(
            engine,
            ref=ref,
            agent_id=holder.agent_id,
            reclaim=False,
            session=session,
            rate_key=rate_key,
            own_model=config.engine_own_model,
        )
        await _publish_business_facts(
            engine,
            session,
            agent_id=holder.agent_id,
            ref=ref,
            reclaim=False,
            script=config.system_prompt,
            campaign_id=campaign_id,
        )
        await _ensure_in_call_actions(
            engine, session, agent_id=holder.agent_id, ref=ref, reclaim=False
        )
    except Exception as exc:
        if created:
            reason = exc.code if isinstance(exc, ProblemError) else type(exc).__name__
            await _reclaim_orphan(engine, holder.agent_id, ref, reason)
        raise
    log.info(
        "campaign_engine_agent_published",
        extra={
            "agent_id": str(holder.agent_id),
            "campaign_id": str(campaign_id),
            "test": test,
            "verify_state": verdict.state,
        },
    )
    return ref


async def republish_campaign_agents(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> int:
    """Bring every campaign in `agent_id`'s voice that holds an engine agent and is still
    going (`CAMPAIGN_HOLDING_STATUSES`) onto the agent's current config: a voice, setting,
    notice, action, platform-prompt or company-training change reaches the calls it places,
    as `republish_lines` does for lines. Each keeps its own script and setting overrides. A
    test holder of a campaign not started is left alone: its test call republishes it first.
    Returns how many were republished."""
    rows = (
        await session.execute(
            text(
                "SELECT id FROM campaigns WHERE agent_id = :aid AND archived_at IS NULL "
                "AND engine_agent_ref IS NOT NULL AND status = ANY(:holding) "
                "ORDER BY created_at, id"
            ),
            {"aid": agent_id, "holding": list(CAMPAIGN_HOLDING_STATUSES)},
        )
    ).scalars()
    count = 0
    for campaign_id in list(rows):
        holder_id = UUID(str(campaign_id))
        if await _republish_holder(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            kind="campaign",
            holder_id=holder_id,
            publish=partial(
                publish_campaign_agent, session, tenant_id=tenant_id, campaign_id=holder_id
            ),
        ):
            count += 1
    return count


async def _owe_holder_deletion(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    ref: str,
    campaign_id: UUID | None = None,
) -> None:
    """Owe the deletion of a campaign's, a draft line's or a client-workspace test copy's
    engine agent through the outbox, which waits out a call still on it. Not
    `retire_engine_agent`'s once-per-ref key: a holder made again finds the same vendor agent
    by its name tag, and giving it back a second time must queue a second deletion; the job
    leaves alone one that is held again by then."""
    from apps.api.reliability.service import enqueue_outbox

    payload = {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "old_ref": ref}
    if campaign_id is not None:
        payload["campaign_id"] = str(campaign_id)
    await enqueue_outbox(session, job=RETIRE_MOVED_AGENT_JOB, payload=payload)


async def _detach_campaign_agent(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID, ref: str
) -> None:
    """The campaign forgets its engine agent and its knowledge claims go (the copies are
    deleted with the vendor agent). The caller holds the campaign row."""
    await session.execute(
        text(
            "UPDATE campaigns SET engine_agent_ref = NULL, engine_agent_at = NULL "
            "WHERE id = :cid AND engine_agent_ref = :ref"
        ),
        {"cid": campaign_id, "ref": ref},
    )
    await session.execute(
        text("DELETE FROM engine_kb_routes WHERE campaign_id = :cid AND tenant_id = :tid"),
        {"cid": campaign_id, "tid": tenant_id},
    )


async def _detach_line_holder(session: AsyncSession, *, tenant_id: UUID, line_id: UUID) -> None:
    """The draft line forgets its test holder and its knowledge claims go with the vendor
    agent. The caller holds the line row."""
    await session.execute(
        text(
            "UPDATE inbound_lines SET engine_agent_ref = NULL, engine_agent_at = NULL "
            "WHERE id = :lid"
        ),
        {"lid": line_id},
    )
    await session.execute(
        text("DELETE FROM engine_kb_routes WHERE inbound_line_id = :lid AND tenant_id = :tid"),
        {"lid": line_id, "tid": tenant_id},
    )


async def retire_campaign_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    campaign_id: UUID,
    idle_seconds: float | None = None,
) -> str | None:
    """A campaign that has ended gives its engine agent back (D-1003): the campaign forgets
    it in this transaction, its knowledge claims go (the copies are deleted with the vendor
    agent), and the deletion is owed through the outbox, which waits out a call still on it
    (`workers/engine_workspaces.retire_moved_engine_agent`). Its route stays active until then,
    so the results of its last calls still land. Returns the retired ref, or None.

    With `idle_seconds` (the hourly sweep) it is retired only if it still meets
    `CAMPAIGN_AGENT_UNNEEDED_WHERE` under the row lock: the sweep picked it without one, and
    a Start or a test call that published it since keeps it."""
    holder = await _campaign_holder(session, campaign_id, lock=True)
    ref = holder.engine_agent_ref
    if ref is None:
        return None
    if idle_seconds is not None:
        unneeded = (
            await session.execute(
                text(
                    f"SELECT 1 FROM campaigns WHERE id = :cid AND {CAMPAIGN_AGENT_UNNEEDED_WHERE}"
                ),
                {
                    "cid": campaign_id,
                    "holding": list(CAMPAIGN_HOLDING_STATUSES),
                    "idle": idle_seconds,
                },
            )
        ).first()
        if unneeded is None:
            return None
    await _detach_campaign_agent(session, tenant_id=tenant_id, campaign_id=campaign_id, ref=ref)
    await _owe_holder_deletion(
        session, tenant_id=tenant_id, agent_id=holder.agent_id, ref=ref, campaign_id=campaign_id
    )
    log.info(
        "campaign_engine_agent_retired",
        extra={"campaign_id": str(campaign_id), "agent_id": str(holder.agent_id)},
    )
    return ref


async def retire_line_test_holder(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    line_id: UUID,
    idle_seconds: float | None = None,
) -> str | None:
    """A draft line gives back the engine agent its test call was rung through (D-1018), as
    `retire_campaign_agent` does for a campaign: the line forgets it in this transaction, its
    knowledge claims go with the vendor agent, and the deletion is owed through the outbox,
    which waits out a call still on it. A line put live meanwhile keeps it, and with
    `idle_seconds` (the hourly sweep) so does one whose holder a test call published since
    (`LINE_HOLDER_IDLE_WHERE`, asked under the row lock). Returns the retired ref, or None."""
    held = (
        LINE_HOLDER_IDLE_WHERE
        if idle_seconds is not None
        else "published_at IS NULL AND engine_agent_ref IS NOT NULL"
    )
    row = (
        await session.execute(
            text(
                f"SELECT agent_id, engine_agent_ref FROM inbound_lines WHERE id = :lid AND {held} "
                "FOR UPDATE"
            ),
            {"lid": line_id, "idle": idle_seconds},
        )
    ).first()
    if row is None:
        return None
    ref = str(row.engine_agent_ref)
    await _detach_line_holder(session, tenant_id=tenant_id, line_id=line_id)
    await _owe_holder_deletion(
        session, tenant_id=tenant_id, agent_id=UUID(str(row.agent_id)), ref=ref
    )
    log.info("line_test_holder_retired", extra={"line_id": str(line_id)})
    return ref


async def _holder_call_live(session: AsyncSession, ref: str) -> bool:
    return bool(
        (
            await session.execute(
                text(_HOLDER_CALL_LIVE_SQL),
                {"ref": ref, "horizon": live_test_call_horizon().total_seconds()},
            )
        ).scalar()
    )


async def _delete_holder_now(
    session: AsyncSession, engine: VoiceEngine, *, tenant_id: UUID, agent_id: UUID, ref: str
) -> bool:
    """What `workers/engine_workspaces.retire_moved_engine_agent` does, now rather than after
    commit, so the platform stops counting the engine agent before a new one is made in its
    place. False when a call is connected on it or the platform would not delete it; the
    caller then owes the deletion through the outbox, which waits the call out, and the slot
    frees when that runs.

    The vendor agent is deleted before its webhook and in-call actions are retired, not
    after: a delete refused for a call that connected since the check leaves that call its
    results webhook and its actions, which the call still needs."""
    from apps.api.reliability.engine_webhooks import retire_agent_webhook

    try:
        if await call_connected_on(engine=engine.name, engine_agent_ref=ref):
            log.info(
                "test_holder_give_back_waits_for_call",
                extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)},
            )
            return False
        await engine.delete_agent(ref)
        await retire_in_call_actions(agent_id=agent_id, ref=ref)
        await retire_agent_webhook(session, engine=engine.name, engine_agent_ref=ref)
    except Exception as exc:
        log.warning(
            "test_holder_give_back_deferred",
            extra={
                "tenant_id": str(tenant_id),
                "agent_id": str(agent_id),
                "error": exc.code if isinstance(exc, ProblemError) else type(exc).__name__,
            },
        )
        return False
    await session.execute(
        text(
            "UPDATE engine_agent_routes SET active = false, updated_at = now() "
            "WHERE engine = :engine AND engine_agent_ref = :ref"
        ),
        {"engine": engine.name, "ref": ref},
    )
    return True


#: Rows of this account holding a test holder in one workspace, matched on the handle's
#: scope suffix (`<raw>@<org_…>`) so rows in other workspaces are never locked. Locked by
#: `give_back_idle_test_holders` with SKIP LOCKED: a row someone holds is in use, and
#: waiting on it from there could wait on its own caller.
_IDLE_LINE_HOLDERS_IN_SQL: Final = (
    "SELECT id, agent_id, engine_agent_ref FROM inbound_lines "
    f"WHERE {LINE_HOLDER_IDLE_WHERE} AND right(engine_agent_ref, :n) = :suffix ORDER BY id"
)
_IDLE_CAMPAIGN_HOLDERS_IN_SQL: Final = (
    "SELECT id, agent_id, engine_agent_ref FROM campaigns "
    f"WHERE {CAMPAIGN_AGENT_UNNEEDED_WHERE} AND right(engine_agent_ref, :n) = :suffix "
    "ORDER BY id"
)
_IDLE_TEST_COPIES_IN_SQL: Final = (
    "SELECT agent_id, engine_agent_ref FROM agent_test_copies "
    "WHERE COALESCE(last_used_at, created_at) < now() - make_interval(secs => :idle) "
    "AND right(engine_agent_ref, :n) = :suffix ORDER BY agent_id"
)
_SKIP_LOCKED: Final = " FOR UPDATE SKIP LOCKED"


def _idle_holder_params(workspace: str) -> dict[str, Any]:
    suffix = f"{SCOPE_SEPARATOR}{workspace}"
    return {
        "idle": TEST_HOLDER_GRACE.total_seconds(),
        "holding": list(CAMPAIGN_HOLDING_STATUSES),
        "suffix": suffix,
        "n": len(suffix),
    }


async def idle_test_holders_in(session: AsyncSession, *, workspace: str) -> int:
    """How many setups in `workspace` `give_back_idle_test_holders` would free now, read
    without taking them: the launch check counts them as room, since Start frees them."""
    from apps.api.agents.paid_test_calls import copy_call_live

    params = _idle_holder_params(workspace)
    count = 0
    for sql in (_IDLE_LINE_HOLDERS_IN_SQL, _IDLE_CAMPAIGN_HOLDERS_IN_SQL):
        for _id, _agent_id, ref in (await session.execute(text(sql), params)).all():
            if scope_of(str(ref)) == workspace and not await _holder_call_live(session, str(ref)):
                count += 1
    for agent_id, ref in (await session.execute(text(_IDLE_TEST_COPIES_IN_SQL), params)).all():
        if scope_of(str(ref)) == workspace and not await copy_call_live(
            session, UUID(str(agent_id))
        ):
            count += 1
    return count


async def give_back_idle_test_holders(
    session: AsyncSession, *, tenant_id: UUID, workspace: str
) -> int:
    """Free the calling setups a Start or a line put live needs (D-1020): every test holder
    of a draft line or a campaign not started, and every agent test copy, held in this
    client's `workspace`, not published for `TEST_HOLDER_GRACE` and with no call on it. Each
    is detached and deleted at the platform at once, rather than the hour the sweep would
    leave it: a test holder costs nothing to make again on the next test call, and a Start
    refused for one is a campaign that does not dial.

    In the caller's transaction, under the tenant knowledge lock and the row its publish
    holds, so the recount that follows sees these gone and no other publish can count the
    same freed setup. A transaction of its own would hold a third pooled connection under a
    request's and the publish's (`scripts/check_session_nesting`). Rows another transaction
    holds are skipped; the caller's own row never matches, since a publish asks for room only
    when it holds no engine agent in this workspace.

    The platform deletes are not undone if the caller's publish then fails and rolls the
    detaches back: the rows name vendor agents that are gone, which every holder survives.
    A draft line's or a campaign's test publish makes its holder again
    (`_vendor_says_gone`), a test copy is replaced, and the next give-back or the hourly
    sweep detaches them again (a delete of an absent agent succeeds). Returns how many."""
    from apps.api.agents.paid_test_calls import copy_call_live
    from apps.api.kb.service import release_test_copy_claims

    engine = get_engine()
    params = _idle_holder_params(workspace)
    given = 0
    for line_id, agent_id, ref in (
        await session.execute(text(_IDLE_LINE_HOLDERS_IN_SQL + _SKIP_LOCKED), params)
    ).all():
        if scope_of(str(ref)) != workspace or await _holder_call_live(session, str(ref)):
            continue
        await _detach_line_holder(session, tenant_id=tenant_id, line_id=UUID(str(line_id)))
        if not await _delete_holder_now(
            session, engine, tenant_id=tenant_id, agent_id=UUID(str(agent_id)), ref=str(ref)
        ):
            await _owe_holder_deletion(
                session, tenant_id=tenant_id, agent_id=UUID(str(agent_id)), ref=str(ref)
            )
        given += 1
    for campaign_id, agent_id, ref in (
        await session.execute(text(_IDLE_CAMPAIGN_HOLDERS_IN_SQL + _SKIP_LOCKED), params)
    ).all():
        if scope_of(str(ref)) != workspace or await _holder_call_live(session, str(ref)):
            continue
        await _detach_campaign_agent(
            session, tenant_id=tenant_id, campaign_id=UUID(str(campaign_id)), ref=str(ref)
        )
        if not await _delete_holder_now(
            session, engine, tenant_id=tenant_id, agent_id=UUID(str(agent_id)), ref=str(ref)
        ):
            await _owe_holder_deletion(
                session,
                tenant_id=tenant_id,
                agent_id=UUID(str(agent_id)),
                ref=str(ref),
                campaign_id=UUID(str(campaign_id)),
            )
        given += 1
    copies = await session.execute(text(_IDLE_TEST_COPIES_IN_SQL + _SKIP_LOCKED), params)
    for agent_id, ref in copies.all():
        agent = UUID(str(agent_id))
        if scope_of(str(ref)) != workspace or await copy_call_live(session, agent):
            continue
        await session.execute(
            text("DELETE FROM agent_test_copies WHERE agent_id = :aid AND engine_agent_ref = :ref"),
            {"aid": agent, "ref": ref},
        )
        await release_test_copy_claims(session, tenant_id=tenant_id, agent_id=agent)
        if not await _delete_holder_now(
            session, engine, tenant_id=tenant_id, agent_id=agent, ref=str(ref)
        ):
            await _owe_holder_deletion(session, tenant_id=tenant_id, agent_id=agent, ref=str(ref))
        given += 1
    if given:
        log.info("idle_test_holders_given_back", extra={"tenant_id": str(tenant_id), "n": given})
    return given


async def retire_idle_client_test_copies(
    session: AsyncSession, *, tenant_id: UUID, idle_seconds: float
) -> int:
    """Give back every test copy of this account's agents held in its own workspace and
    unused for `idle_seconds` (D-1020), freeing the engine agent it holds there. The copy row
    goes in this transaction, under its row lock with the idle test re-asked, so a test call
    that used it meanwhile keeps it and the next one makes a new copy rather than ringing one
    owed a deletion; the deletion itself is owed through the outbox, which waits out a call
    still on it. Returns how many were given back."""
    from apps.api.kb.service import release_test_copy_claims

    rows = (
        await session.execute(
            text(
                "SELECT agent_id, engine_agent_ref FROM agent_test_copies "
                "WHERE COALESCE(last_used_at, created_at) < now() - make_interval(secs => :idle) "
                "ORDER BY agent_id"
            ),
            {"idle": idle_seconds},
        )
    ).all()
    retired = 0
    for agent_id, ref in rows:
        if scope_of(str(ref)) is None:
            continue
        # `refresh_test_copy` republishes the copy under the agent row lock
        # (`publish_agent`) and stamps `last_used_at` only after the platform round trip, so
        # a copy whose agent row is held is being readied for a test call: skipped, never
        # waited on, as `give_back_idle_test_holders` skips a row someone holds.
        in_use = (
            await session.execute(
                text("SELECT 1 FROM agents WHERE id = :aid FOR UPDATE SKIP LOCKED"),
                {"aid": agent_id},
            )
        ).first() is None
        if in_use:
            continue
        gone = await session.execute(
            text(
                "DELETE FROM agent_test_copies WHERE agent_id = :aid AND engine_agent_ref = :ref "
                "AND COALESCE(last_used_at, created_at) < now() - make_interval(secs => :idle)"
            ),
            {"aid": agent_id, "ref": ref, "idle": idle_seconds},
        )
        if not rowcount_of(gone):
            continue
        await release_test_copy_claims(session, tenant_id=tenant_id, agent_id=UUID(str(agent_id)))
        await _owe_holder_deletion(
            session, tenant_id=tenant_id, agent_id=UUID(str(agent_id)), ref=str(ref)
        )
        retired += 1
    if retired:
        log.info("client_test_copies_retired", extra={"tenant_id": str(tenant_id), "n": retired})
    return retired


#: The numbers an agent can place calls from: every number of its client (founder, 4 Nov
#: 2026: a client's number serves all its agents), the agent's own first, and, when the
#: engine presents only numbers it holds (`:carrier` set), held there and set up for
#: outgoing calls. `agent_id` on a number is who ANSWERS it; another agent calls out on it
#: by having it lent for the call (`_lend_client_number`). A caller id the dialling account
#: does not hold is one it cannot present, and a number bought for inbound only is not one
#: to place calls from; `:carrier` is NULL on an engine with no such rule
#: (`outbound_number_provider`). Read under the tenant's RLS, so only its own numbers.
#:
#: `dlt_status` is not asked (D-793): no client registers on DLT since D-692, every number
#: is inserted `pending` and nothing outbound requires `registered`, so filtering on it hid
#: every client number from the dial.
_AGENT_CALLER_ID_SQL = (
    "SELECT id, e164, agent_id IS NOT DISTINCT FROM :aid, engine_number_ref "
    "FROM phone_numbers "
    "WHERE released_at IS NULL "
    "AND (CAST(:carrier AS text) IS NULL "
    "     OR (provider = :carrier AND direction IN ('outbound', 'both'))) "
    "ORDER BY agent_id IS NOT DISTINCT FROM :aid DESC, created_at, id"
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


@dataclass(frozen=True, slots=True)
class CallerLine:
    """A number a dial can ring from, and whether it is the dialling agent's own."""

    number_id: UUID
    e164: str
    #: The agent answers it (or it was lent to it by its record): no lend is needed.
    own: bool
    engine_number_ref: str | None


async def caller_lines(
    session: AsyncSession,
    *,
    agent_id: UUID,
    dial_ref: str | None = None,
    workspace: str | None = None,
) -> list[CallerLine]:
    """Every number this agent can place calls from, its own first, then oldest first.

    On an engine that rings only from numbers it holds, a number in another workspace than
    the agent's is left out: the platform cannot lend it across workspaces
    (`engine_number_other_workspace`), so offering it only turns every dial into a refusal
    (a Calevate-held number recorded for a client before it is moved into the client's own
    workspace is exactly that). `dial_ref` is the engine agent the call rings through when
    it is not the agent's own (an inbound line's test holder), whose workspace decides;
    `workspace` names that workspace outright, for a holder not made yet (D-1020)."""
    carrier = outbound_number_provider()
    rows = (
        await session.execute(text(_AGENT_CALLER_ID_SQL), {"aid": agent_id, "carrier": carrier})
    ).all()
    agent_scope: str | None = workspace
    if carrier is not None and workspace is None:
        agent_ref = (
            dial_ref
            or (
                await session.execute(
                    text("SELECT engine_agent_ref FROM agents WHERE id = :aid"), {"aid": agent_id}
                )
            ).scalar()
        )
        agent_scope = scope_of(str(agent_ref)) if agent_ref else None
    return [
        CallerLine(
            number_id=UUID(str(row[0])),
            e164=str(row[1]),
            own=bool(row[2]),
            engine_number_ref=str(row[3]) if row[3] else None,
        )
        for row in rows
        if carrier is None or not row[3] or scope_of(str(row[3])) == agent_scope
    ]


async def agent_outbound_numbers(
    session: AsyncSession, *, agent_id: UUID
) -> list[tuple[UUID, str]]:
    """`(id, e164)` of every number this agent can place calls from, its own first."""
    return [(line.number_id, line.e164) for line in await caller_lines(session, agent_id=agent_id)]


async def resolve_caller_id(
    session: AsyncSession, *, agent_id: UUID, number_id: UUID | None = None
) -> str | None:
    """The number this dial rings from, or None to let the engine use the agent's own line.

    The candidates are every outbound number of the agent's client (`caller_lines`, D-793):

    * `number_id` (a campaign's chosen number) is presented when it is one of them. When it
      no longer is — released or changed since the tick's `dispatch_blockers` — the dial
      is refused with `CAMPAIGN_NUMBER_UNAVAILABLE_CODE` rather than sent from another
      number, because the campaign gate promises the calls come from the number it names;
    * otherwise the agent's own number when it has exactly one;
    * otherwise, with no number of its own, the client's oldest (lent for the call);
    * otherwise (several of its own and nothing chose) None: ThinnestAI then rings from the
      agent's own line (`place-call.md:708-715,971-977`), which beats the old
      `agent_caller_id_ambiguous` refusal — that guarded a 140/160 DLT class choice nobody
      makes since D-692, and refusing would stop every dial of a multi-number agent.

    Ids and counts in the log line, never a number (hard rule 6).
    """
    line = await choose_caller_line(session, agent_id=agent_id, number_id=number_id)
    return line.e164 if line is not None else None


async def choose_caller_line(
    session: AsyncSession, *, agent_id: UUID, number_id: UUID | None = None
) -> CallerLine | None:
    """`resolve_caller_id`'s choice with what the dial needs to know about it. An agent with
    no number of its own rings from its client's oldest one, lent to it for the call."""
    lines = await caller_lines(session, agent_id=agent_id)
    if number_id is not None:
        chosen = next((line for line in lines if line.number_id == number_id), None)
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
    own = [line for line in lines if line.own]
    if own:
        return own[0] if len(own) == 1 else None
    return lines[0] if lines else None


async def presented_caller_ids(
    session: AsyncSession,
    *,
    agent_id: UUID,
    number_id: UUID | None = None,
    campaign_ref: str | None = None,
    through_line: LineDial | None = None,
) -> list[str]:
    """The numbers a dial of this agent can present, for the calling-number declaration
    (D-941): the one `dispatch_call` would choose (`choose_caller_line`, `_campaign_caller`
    for a dial through a campaign's engine agent, `_holder_caller` for one through an inbound
    line's), including a client number lent to an agent with none of its own; or, when it
    names none and the engine rings from the agent's own line, every number the agent holds.
    The agent's own numbers alone are the wrong set both ways: they refuse an agent that
    borrows a declared number, and pass a dial that presents an undeclared one. Empty when no
    number can be named, which the declaration refuses."""
    try:
        line = (
            await _campaign_caller(
                session, agent_id=agent_id, number_id=number_id, ref=campaign_ref
            )
            if campaign_ref is not None
            else await _holder_caller(
                session,
                agent_id=agent_id,
                ref=through_line.ref,
                routed_number_ids=through_line.routed_number_ids,
            )
            if through_line is not None
            else await choose_caller_line(session, agent_id=agent_id, number_id=number_id)
        )
    except ProblemError:
        return []
    if line is not None:
        return [line.e164]
    return await agent_calling_numbers(session, agent_id=agent_id)


async def _refuse_undeclared_caller(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, line: CallerLine | None
) -> None:
    """The declaration asked of the number this dial actually presents, at the one place it
    is known. `check_dispatch` asks it before the dial of the number its caller named (a
    campaign's), so a number lent since the gate, or one chosen here when the caller named
    none, is caught here. Raised before the intent row, so nothing was seized."""
    if not enforcement_active():
        return
    presented = (
        [line.e164] if line is not None else await agent_calling_numbers(session, agent_id=agent_id)
    )
    undeclared = await a2p_declaration_blocker(session, tenant_id=tenant_id, caller_ids=presented)
    if undeclared is not None:
        rule, reason = undeclared
        log.info("dial_refused_undeclared_number", extra={"agent_id": str(agent_id), "rule": rule})
        raise ProblemError.business_rule(rule, reason)


async def _holder_caller(
    session: AsyncSession,
    *,
    agent_id: UUID,
    ref: str,
    routed_number_ids: frozenset[UUID],
    line_number_ids: frozenset[UUID] = frozenset(),
) -> CallerLine | None:
    """The number a call through an inbound line's engine agent rings from, a test call or a
    call-back alike: one the engine already routes to that holder needs no lend; otherwise
    one of the line's own numbers (a draft line's, D-1020), else the client's first number in
    the holder's workspace, lent to it for the call, as for an agent with no number."""
    lines = await caller_lines(session, agent_id=agent_id, dial_ref=ref)
    routed = [line for line in lines if line.number_id in routed_number_ids]
    if routed:
        return replace(routed[0], own=True)
    the_lines = [line for line in lines if line.number_id in line_number_ids]
    first = the_lines[0] if the_lines else lines[0] if lines else None
    return replace(first, own=False) if first is not None else None


async def _copy_caller(session: AsyncSession, *, agent_id: UUID, ref: str) -> CallerLine | None:
    """The number a test call through the agent's client-workspace test copy rings from
    (D-1020): the account's first number in the copy's workspace (`caller_lines`' order, the
    agent's own first), always lent, since the copy answers no number."""
    lines = await caller_lines(session, agent_id=agent_id, dial_ref=ref)
    return replace(lines[0], own=False) if lines else None


async def _campaign_caller(
    session: AsyncSession, *, agent_id: UUID, number_id: UUID | None, ref: str
) -> CallerLine | None:
    """The number a campaign's call rings from (D-1003): the campaign's chosen one, else its
    voice's own, else the client's oldest in the engine agent's workspace, and always as
    borrowed (`own=False`), since the campaign's engine agent answers no number and holds none.
    A chosen number that is no longer one it can call from is refused, as for an agent."""
    lines = await caller_lines(session, agent_id=agent_id, dial_ref=ref)
    if number_id is not None:
        chosen = next((line for line in lines if line.number_id == number_id), None)
        if chosen is None:
            log.warning(
                CAMPAIGN_NUMBER_UNAVAILABLE_CODE,
                extra={"agent_id": str(agent_id), "number_id": str(number_id)},
            )
            raise ProblemError.business_rule(
                CAMPAIGN_NUMBER_UNAVAILABLE_CODE,
                "This campaign's calling number is no longer one it can place calls from.",
                remediation="Pick another of your numbers for the campaign.",
            )
        return replace(chosen, own=False)
    own = [line for line in lines if line.own]
    first = own[0] if own else lines[0] if lines else None
    return replace(first, own=False) if first is not None else None


def _dial_origin(dial_ref: str, caller: CallerLine | None, *, trial: bool) -> DialOrigin:
    """Where a dial through `dial_ref` from `caller` is placed, as the hold-offs scope it."""
    return DialOrigin(
        workspace=scope_of(dial_ref),
        number_key=(
            str(caller.number_id) if caller is not None else TRIAL_LINE_KEY if trial else None
        ),
    )


async def campaign_dial_backoff_s(
    session: AsyncSession, *, agent_id: UUID, number_id: UUID | None, via: CampaignDial | None
) -> float:
    """Seconds left on the voice platform's hold-off that a campaign's next dial would be
    refused under, for the origin `dispatch_call` derives (its workspace or its number, not
    only the account); 0.0 when none holds it or the engine has no ceiling of its own.

    `via` is the campaign's own engine agent, or None for a campaign dialling through its
    agent's. A number the dial would refuse anyway (`CAMPAIGN_NUMBER_UNAVAILABLE_CODE`) reads
    as no hold here: the dial refuses it under that rule, which says what to fix."""
    if engine_concurrency_cap() is None:
        return 0.0
    try:
        if via is not None:
            ref: str | None = via.ref
            caller = await _campaign_caller(
                session, agent_id=agent_id, number_id=number_id, ref=via.ref
            )
        else:
            ref = (
                await session.execute(
                    text("SELECT engine_agent_ref FROM agents WHERE id = :aid"), {"aid": agent_id}
                )
            ).scalar_one_or_none()
            caller = await choose_caller_line(session, agent_id=agent_id, number_id=number_id)
    except ProblemError:
        return 0.0
    if not ref:
        return 0.0
    return await dial_backoff_remaining_s(_dial_origin(ref, caller, trial=False))


async def _assert_dialling_tenant_owns_the_session(
    session: AsyncSession, *, tenant_id: UUID
) -> None:
    """Refuse a dial whose reads and writes would belong to two different tenants.

    `dispatch_call` is the one function in this tree that takes BOTH a tenant-scoped
    session and a `tenant_id`, and it uses them for different halves of the same call:
    the agent row and the caller ID are read under the SESSION's
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
class LineTestDial:
    """A test call rung through an inbound line's own engine agent (Phase 3b), not the
    agent's: the line's test holder (`publish_line(test=True)`). Built only by
    `inbound/publish.line_test_dial`, and only with a `TrialDial` or an `OwnerTestDial`."""

    ref: str
    line_id: UUID
    #: The line's numbers the engine already routes to `ref` (a live line's): a dial from one
    #: needs no lend. Any other number of the client is lent to `ref` for the call.
    routed_number_ids: frozenset[UUID] = frozenset()
    #: A draft line's test holder, made in our developer workspace (D-1018): the call rings
    #: from the shared test line, never from the client's numbers.
    developer: bool = False
    #: A draft line's own numbers, none routed to it yet: its test from the client's
    #: workspace (D-1020) rings from one of them, lent to the holder for the call.
    line_number_ids: frozenset[UUID] = frozenset()


@dataclass(frozen=True, slots=True)
class CopyTestDial:
    """A paying account's test call of an agent through its test copy in the CLIENT's
    workspace (D-1020), rung from the client's own number lent to the copy for the call.
    Built only by `agents/trial_calls.place_trial_call`, always with an `OwnerTestDial`."""

    ref: str


@dataclass(frozen=True, slots=True)
class LineDial:
    """A call placed through a LIVE inbound line's engine agent (D-1019): a call-back, a call
    again or a lead call in the line's voice when no campaign holds the lead. The line's
    engine agent answers its numbers and may also place calls (D2), so the call rings from
    one of those numbers unlent, or from another client number lent to it for the call. The
    call row carries the line (`calls.inbound_line_id`), so a call-back of this call finds
    the same line. Built only by `agents/dial_through.resolve_dial_holder`."""

    ref: str
    line_id: UUID
    #: The line's numbers the engine already routes to `ref`: a dial from one needs no lend.
    routed_number_ids: frozenset[UUID] = frozenset()


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
    from apps.api.agents.paid_test_calls import PLACED_TODAY_SQL, paid_daily_cap_reason

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
            PAID_TEST_DAILY_CAP_RULE,
            paid_daily_cap_reason(test.daily_cap),
            remediation="You can place more tomorrow.",
        )


def trial_call_first_words(agent: AgentRow, *, call_is_recorded: bool) -> str | None:
    """What an agent that only answers calls says first when it rings its owner on a test
    call (founder, 23 Oct 2026): who it is, from which business, why it rings and whether now
    suits, then the notices its switches turn on, in the order its greeting carries them
    (D-861). When its AI notice introduces it (D-865), the line after the introduction says
    only why it rings and whether now suits. None for an agent that calls out (`dial_first_words`
    decides its first words) or a language with no such line (its greeting is spoken)."""
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
    line = said_as_taught(
        line, body=str(agent.get("prompt") or ""), business=str(agent.get("business_name") or "")
    )
    notices = compose_opening_line(posture, call_is_recorded=call_is_recorded)
    return join_first_words(notices, line, ai_notice=ai_notice, language=language)


def lead_first_words(agent: AgentRow, *, call_is_recorded: bool) -> str | None:
    """What an agent that calls leads says first to a lead whose name is known (D-945): its
    opening with the language's name check as the one question, the notices where its
    greeting carries them. None while the language has no name check, so the greeting is
    spoken as before."""
    if agent["direction"] == "inbound":
        return None
    posture = posture_of(agent)
    language = str(agent["language_primary"])
    ai_notice = spoken_ai_notice(posture)
    body = str(agent.get("prompt") or "")
    business = str(agent.get("business_name") or "")
    line = (
        placed_call_line(body=body, language=language, business=business, ai_notice=ai_notice)
        if agent["direction"] == "both"
        else said_as_taught(opening_line_of(body), body=body, business=business)
    )
    named = named_lead_opening(
        line,
        language=language,
        introduced=introduces_itself(ai_notice=ai_notice, language=language),
    )
    if named is None:
        return None
    notices = compose_opening_line(posture, call_is_recorded=call_is_recorded)
    return join_first_words(
        notices,
        named,
        ai_notice=ai_notice,
        language=language,
        # The agent's name only, as on any placed call (`placed_call_first_words`).
        names=introduction_names(name=str(agent["name"]), business="", body=body),
        said=said_notices(body, business=business, placed=agent["direction"] == "both"),
    )


def campaign_first_words(agent: AgentRow, opening_line: str, *, call_is_recorded: bool) -> str:
    """A campaign's own opening line with the agent's notices: `join_first_words` says each
    switched-on notice's stored sentence beside an opening that does not already say it.
    The opening is said with the names the owner taught the voice (D-947). A sentence before
    its question is dropped as a second introduction only when it says the agent's name, as
    on any placed call (`placed_call_first_words`): "calling from <business> about ..." is
    the reason for the call, which the introduction does not say."""
    posture = posture_of(agent)
    body = str(agent.get("prompt") or "")
    return join_first_words(
        compose_opening_line(posture, call_is_recorded=call_is_recorded),
        said_as_taught(
            opening_line.strip(), body=body, business=str(agent.get("business_name") or "")
        ),
        ai_notice=spoken_ai_notice(posture),
        language=str(agent["language_primary"]),
        names=introduction_names(name=str(agent["name"]), business="", body=body),
    )


async def refuse_campaign_opening_over_limit(
    session: AsyncSession, *, tenant_id: UUID, campaign_id: UUID, opening_line: str
) -> None:
    """Refuse a campaign opening whose first words, composed exactly as the dial composes them
    (`campaign_first_words` over `campaign_agent_row`), would not fit the engine's per-call
    ceiling. Over it, the adapter speaks the agent's own greeting instead
    (`ThinnestEngine.start_outbound_call`), so half a test would hear an opening it does not
    record; refused at save time instead."""
    engine = get_engine()
    limit = hosted_agent_limits(engine).call_opening_chars
    if limit is None:
        return
    speaker = await campaign_agent_row(session, tenant_id=tenant_id, campaign_id=campaign_id)
    length = len(
        campaign_first_words(
            speaker, opening_line, call_is_recorded=engine.capabilities.records_audio
        )
    )
    if length <= limit:
        return
    raise ProblemError(
        kind="business_rule",
        code=OPENING_TOO_LONG,
        title="This opening line is too long",
        detail=(
            f"With the notices said with it, what the agent says first would be "
            f"{length:,} characters, and at most {limit:,} can be spoken there. Nothing was "
            "saved."
        ),
        remediation=f"Shorten it by at least {length - limit:,} characters.",
    )


def dial_first_words(
    agent: AgentRow,
    *,
    test_call: bool,
    call_is_recorded: bool,
    lead_name: str | None = None,
    through_line: bool = False,
) -> str | None:
    """The first words of a call this agent places, or None for its greeting.

    A call to a lead whose name is known opens with the name check where the language has one
    (`lead_first_words`, D-945). A "both" agent opens EVERY call it places, test calls
    included, with its outbound opening (D-920): its greeting thanks the person for calling,
    which on the founder's call of 28 Oct 2026 it said to the person it had rung. An
    answering agent rings out with the test-call line on a test call only; an outbound
    agent's greeting is its opening.

    `through_line` is a call placed through an inbound line's engine agent (D-1019). An
    answering agent placing it opens as a "both" agent does, because its greeting thanks the
    person for calling; it has no placed-call opening of its own, so the language's line
    naming the business is said, with the notices joined as on every placed call."""
    answering_through_line = through_line and agent["direction"] == "inbound"
    if answering_through_line:
        agent = cast(AgentRow, {**agent, "direction": "both"})
    if lead_name and lead_name.strip() and not test_call:
        named = lead_first_words(agent, call_is_recorded=call_is_recorded)
        if named is not None:
            return named
    if agent["direction"] == "both":
        posture = posture_of(agent)
        body = str(agent.get("prompt") or "")
        if not outbound_opening_of(body) and not answering_through_line:
            # The last resort (D-963): the language's line naming only the business. A "both"
            # agent is built with its own placed-call opening, so this is a gap to close.
            log.warning("placed_call_opening_ready_made", extra={"agent_id": str(agent.get("id"))})
        return placed_call_first_words(
            body=body,
            notices=compose_opening_line(posture, call_is_recorded=call_is_recorded),
            ai_notice=spoken_ai_notice(posture),
            language=str(agent["language_primary"]),
            business=str(agent.get("business_name") or ""),
            agent_name=str(agent["name"]),
        )
    if test_call:
        return trial_call_first_words(agent, call_is_recorded=call_is_recorded)
    return None


_ARM_SCRIPT_SQL: Final = (
    "SELECT v.label, v.disclosure_line, pv.body FROM prompt_experiment_variants v "
    "JOIN prompt_versions pv ON pv.id = v.prompt_version_id WHERE v.id = :vid"
)


async def held_greeting(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent: AgentRow,
    campaign_id: UUID | None = None,
    line_id: UUID | None = None,
    arm: assignment.VariantArm | None = None,
) -> str | None:
    """The greeting the dialled engine agent holds once its republish lands, composed from our
    rows now (`compose_first_utterance` of the config that publish writes): the campaign's,
    the line's, the experiment arm's or the agent's own. A dial whose first words are that
    greeting carries this instead of letting the engine speak what it holds, which after a
    notice switch moves is the old posture until the tenant's live apply reaches it.

    None leaves the engine's own greeting: an arm whose script is gone, an empty greeting, or
    a config our rows cannot compose (no script yet), which a publish would refuse too and
    which must not refuse a dial the engine can still place."""
    engine = get_engine()
    try:
        if campaign_id is not None:
            cfg = await campaign_config(
                session, tenant_id=tenant_id, campaign_id=campaign_id, agent=agent
            )
        elif line_id is not None:
            cfg = await line_config(session, tenant_id=tenant_id, line_id=line_id, agent=agent)
        elif arm is not None:
            row = (await session.execute(text(_ARM_SCRIPT_SQL), {"vid": arm.variant_id})).first()
            if row is None:
                return None
            cfg = _variant_config(
                tenant_id,
                agent,
                arm.variant_id,
                str(row.label),
                str(row.body),
                str(row.disclosure_line),
                engine=engine,
            )
        else:
            cfg = _to_config(tenant_id, agent, engine=engine)
    except ProblemError as refused:
        log.info(
            "dial_greeting_not_composed",
            extra={"agent_id": str(agent["id"]), "reason": refused.code},
        )
        return None
    return compose_first_utterance(cfg) or None


async def holder_config(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent: AgentRow,
    kind: HolderKind,
    holder_id: UUID | None = None,
    business_only: bool = False,
) -> AgentConfig | None:
    """The config one engine holder's publish composes, before workspace placement: what
    `publish_line`, `publish_campaign_agent`, `publish_variant` and `publish_agent` (the
    agent's own engine agent and its test copy) build, by the same builders. None for an arm
    whose script is gone. Raises what those builders raise (a holder with no script)."""
    engine = get_engine()
    if kind == "line" and holder_id is not None:
        return await line_config(session, tenant_id=tenant_id, line_id=holder_id, agent=agent)
    if kind == "campaign" and holder_id is not None:
        return await campaign_config(
            session, tenant_id=tenant_id, campaign_id=holder_id, agent=agent
        )
    handoff, _duty = await handoff_module.spec_for(session, dict(agent))
    if kind == "arm" and holder_id is not None:
        row = (await session.execute(text(_ARM_SCRIPT_SQL), {"vid": holder_id})).first()
        if row is None:
            return None
        return _variant_config(
            tenant_id,
            agent,
            holder_id,
            str(row.label),
            str(row.body),
            str(row.disclosure_line),
            engine=engine,
            handoff=handoff,
        )
    from apps.api.actions import service as actions_service
    from apps.api.agents.business_only import business_row

    held = (
        await business_row(session, tenant_id=tenant_id, agent=agent)
        if kind == "test_copy" and business_only
        else agent
    )
    config = _to_config(tenant_id, held, engine=engine, handoff=handoff)
    tools = await actions_service.declare(
        session, agent_id=UUID(str(agent["id"])), direction=held["direction"]
    )
    return config.model_copy(
        update={"action_tools": tools, **({"holder": "test_copy"} if kind == "test_copy" else {})}
    )


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
    contact_details: dict[str, str] | None = None,
    opening_line: str | None = None,
    line_test: LineTestDial | None = None,
    campaign: CampaignDial | None = None,
    line: LineDial | None = None,
    copy_test: CopyTestDial | None = None,
) -> str:
    """Place ONE outbound call. The caller has already passed the compliance gate.

    `copy_test` rings through the agent's test copy in the client's workspace (D-1020), from
    the client's first number there, lent to the copy for the call: a paying account's test
    call of an agent from its own number. With `owner_test` only.

    `line` rings through a live inbound line's engine agent (D-1019): a direct call the
    resolver (`agents/dial_through`) sent through the line. The call row carries the line,
    it rings from a number the line answers or one lent to its engine agent, and it takes
    part in no agent experiment. At most one of `campaign`, `line_test` and `line`.

    `campaign` rings through that campaign's own engine agent (D-1003): its script and
    settings in the agent's voice, its first words from its own opening, and no agent
    experiment. It holds no number of its own, so the number it calls from is ALWAYS lent to
    it for the call (`phone-numbers.md:748-753`, 2026-10-29 mirror: a number is lent to one
    agent at a time and a call waiting to ring from a number lent away is not placed), and
    held per engine agent while the call lasts (`_hold_client_number`).

    `line_test` rings through an inbound line's test holder rather than the agent's own
    engine agent (Phase 3b): the agent need not be published itself, the call row carries
    the line, and it opens as an answering agent's test call does.

    `opening_line` is a campaign's own opening for this call (its A/B test, D-992). It goes
    through `campaign_first_words`, which puts the agent's switched-on notices beside any
    opening that does not already say them, so no opening can drop a notice (hard rule 5).

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

    `contact_details` is the person's row of the client's list (`campaign_contacts.custom`,
    D-905), which the engine hands the agent as call variables; without one, a dial for a
    known lead carries the lead's stored details (`campaigns/contact_details.lead_details`).
    """
    if rings_at_any_hour and trial is None and owner_test is None:
        # Only a test call can be exempt from the window; a campaign, callback or lead dial
        # that asked for it would be a night call to the public.
        raise ValueError("rings_at_any_hour is for a test call only")
    if line_test is not None and trial is None and owner_test is None:
        raise ValueError("line_test is for a test call only")
    if copy_test is not None and (owner_test is None or trial is not None):
        raise ValueError("copy_test is a paying account's own-number test call only")
    if sum(holder is not None for holder in (campaign, line_test, line, copy_test)) > 1:
        raise ValueError("a call rings through one holder: campaign, line_test, line or copy")
    await _assert_dialling_tenant_owns_the_session(session, tenant_id=tenant_id)

    agent = await _load_agent(session, tenant_id, agent_id)
    # Who speaks this call: the campaign's own row when it rings a campaign, else the agent.
    speaker = (
        await campaign_agent_row(
            session, tenant_id=tenant_id, campaign_id=campaign.campaign_id, agent=agent
        )
        if campaign is not None
        else agent
    )
    ref = (
        campaign.ref
        if campaign is not None
        else line_test.ref
        if line_test is not None
        else line.ref
        if line is not None
        else copy_test.ref
        if copy_test is not None
        else agent["engine_agent_ref"] or (trial.agent_ref if trial is not None else None)
    )
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
    holder_line = line_test or line
    caller = (
        None
        if trial is not None
        else await _campaign_caller(session, agent_id=agent_id, number_id=number_id, ref=ref)
        if campaign is not None
        else await _holder_caller(
            session,
            agent_id=agent_id,
            ref=holder_line.ref,
            routed_number_ids=holder_line.routed_number_ids,
            line_number_ids=line_test.line_number_ids if line_test is not None else frozenset(),
        )
        if holder_line is not None
        else await _copy_caller(session, agent_id=agent_id, ref=copy_test.ref)
        if copy_test is not None
        else await choose_caller_line(session, agent_id=agent_id, number_id=number_id)
    )
    if copy_test is not None and caller is None:
        # Checked before the copy was readied (`trial_calls`); a number released in between.
        raise ProblemError.business_rule(
            CLIENT_NUMBER_UNAVAILABLE_RULE,
            "There is no number of yours this test call can ring from right now.",
            remediation="Try again in a few minutes.",
        )
    if trial is None and owner_test is None:
        # A test call is asked by the gate itself (`a2p_dial_blocker(trial_call=True)`).
        await _refuse_undeclared_caller(
            session, tenant_id=tenant_id, agent_id=agent_id, line=caller
        )
    from_e164 = trial.from_e164 if trial is not None else caller.e164 if caller else None
    # Another agent's number on an engine that rings only from numbers lent to the caller:
    # held for this call and lent to it just before the dial (`_lend_client_number`).
    borrowed = (
        caller
        if caller is not None
        and not caller.own
        and caller.engine_number_ref
        and outbound_number_provider() is not None
        else None
    )

    # The stable unit: the lead when there is one, the destination otherwise. See
    # `agents/assignment.py` for why it is not the call id. An agent's arms are variants of
    # its own engine agent, so a call through any holder, or of an agent that holds none of
    # its own (D-1019), takes part in no experiment.
    arm = (
        None
        if trial is not None
        or owner_test is not None
        or campaign is not None
        or holder_line is not None
        or not agent["engine_agent_ref"]
        else await assignment.assign(
            session, agent_id=agent_id, unit_key=str(lead_id) if lead_id else phone_e164
        )
    )
    # An arm that has never been published has no engine agent to dial. Falling back to
    # the agent's own ref rather than failing: the client's call is the thing that
    # matters, and a call that ran the control is a call, whereas a refused dial is an
    # outage caused by an experiment. It is not recorded as assigned — see below.
    dial_ref = (
        ref
        if campaign is not None
        else trial.agent_ref
        if trial is not None and trial.agent_ref
        else arm.arm.engine_agent_ref
        if arm and arm.arm.engine_agent_ref
        else ref
    )

    # THE ENGINE ACCOUNT'S TWO LIMITS (ThinnestAI): the vendor's hold-off after a 429, then
    # its call ceiling under the line lock. Both are refused before the intent row exists,
    # so nothing is left `queued` for a dial that was never placed. The hold-off is scoped
    # to what the 429 named, so one client's exhausted number holds no other dial.
    # What the dialled engine agent says first when this dial brings no first words of its
    # own, composed from our rows before anything is written: a notice switch moved since
    # that engine agent was last published must not open a placed call on the old notices
    # (D-1021). A test copy and a test holder are published for the call they make.
    held_first_words = (
        await held_greeting(
            session,
            tenant_id=tenant_id,
            agent=agent,
            campaign_id=campaign.campaign_id if campaign is not None else None,
            line_id=line.line_id if line is not None else None,
            arm=arm.arm if arm is not None and arm.arm.engine_agent_ref else None,
        )
        if trial is None
        and copy_test is None
        and line_test is None
        and not (opening_line and opening_line.strip())
        else None
    )

    engine_capped = engine_concurrency_cap() is not None
    origin = _dial_origin(dial_ref, caller, trial=trial is not None)
    if engine_capped and (held := await dial_backoff_refusal(origin)) is not None:
        raise held

    call_id = uuid7()
    intent_engine_call_id = unconfirmed_engine_call_id(call_id)
    async with tenant_session(tenant_id) as intent:
        if trial is not None:
            await _hold_trial_line(intent)
            studio_left = await refuse_trial_studio_over_cap(
                intent, tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=dial_ref
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
        if borrowed is not None:
            await _hold_client_number(intent, number=borrowed, engine_agent_ref=dial_ref)
        await intent.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, from_e164, "
                "to_e164, trial_call, paid_test_call, inbound_line_id, engine_agent_ref, status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'outbound', :from_e, "
                ":to_e, :trial, :owner_test, :line, :ref, 'queued', now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ref": dial_ref,
                "line": holder_line.line_id if holder_line is not None else None,
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
    if borrowed is not None:
        await _lend_client_number(tenant_id, call_id=call_id, number=borrowed, agent_ref=dial_ref)
    from apps.api.actions.pre_dial import CallerPrefill, pre_dial_lookup
    from apps.api.campaigns.contact_details import lead_details

    # A dial for a known lead that brings no list row of its own (a new lead's first call,
    # a call-back outside a campaign, the "call this lead" button) carries the lead's stored
    # details instead, through the same call variables and details line (D-940). A campaign
    # row, when there is one, is what the client chose to say on that campaign's calls, so
    # it is not mixed with the lead's.
    details = dict(contact_details or {})
    if not details and lead_id is not None:
        details = await lead_details(session, lead_id=lead_id)

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
                contact_details=details,
                context_note=context_note,
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
                    speaker,
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
                opening=(
                    # A line answers calls, so its test call opens as an answering agent's.
                    trial_call_first_words(
                        cast(AgentRow, {**agent, "direction": "inbound"}),
                        call_is_recorded=engine.capabilities.records_audio,
                    )
                    if line_test is not None
                    else campaign_first_words(
                        speaker, opening_line, call_is_recorded=engine.capabilities.records_audio
                    )
                    if opening_line and opening_line.strip()
                    else dial_first_words(
                        speaker,
                        test_call=trial is not None or owner_test is not None,
                        call_is_recorded=engine.capabilities.records_audio,
                        lead_name=lead_name or prefill.name,
                        through_line=line is not None,
                    )
                    or held_first_words
                ),
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
        if engine_capped and isinstance(exc, EngineRateLimitedError | EngineNumberDailyLimitError):
            await start_dial_backoff(exc.retry_after_s, scope=exc.scope, origin=origin)
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
    if await _confirm_dial(tenant_id, call_id=call_id, handle=handle):
        await _recall_if_stopped_while_dialling(tenant_id, call_id=call_id, phone_e164=phone_e164)
    if lead_id is not None:
        await _link_dial_to_lead(session, call_id=call_id, lead_id=lead_id)
    return handle


#: The person-level refusals a suppression written while a dial was in flight can raise:
#: a do-not-call entry and a withdrawn or declined consent. The others (not India, erased,
#: no consent record, expired consent) cannot appear between the gate and the dial.
_RECALLED_PERSON_RULES: Final = {"dnc": None, "no_consent": RECALL_CAUSE_CONSENT}


async def _recall_if_stopped_while_dialling(
    tenant_id: UUID, *, call_id: UUID, phone_e164: str
) -> None:
    """Hand a dial accepted after the big red switch or a suppression to that recall.

    Both recalls (`workers/dial_recall`, `workers/dnc_recall`) scan only dials that carry
    the vendor's handle, so one thrown between the gate and `_confirm_dial` (the pre-dial
    lookup and the `POST /calls` round trip) scanned past this dial while it was still a
    `local:` placeholder, and nothing scanned again (D-428's open window). Asking again here,
    AFTER the handle is committed, closes it whichever way the race falls: a halt or entry
    committed before this read is seen and recalled now; one committed after it enqueues its
    own recall, whose scan runs after this dial's handle is stamped and finds it. A second
    recall of a dial the first already stopped is a no-op (`recall_requested_at`).

    Never raises: the vendor has accepted the call, and a raise reads as "not placed".
    """
    from apps.api.compliance.service import person_level_refusal

    try:
        async with tenant_session(tenant_id) as recheck:
            # The durable row on this connection, not the 15-second hot-path cache: the
            # halt that matters here is one thrown seconds ago.
            if (await read_halt_state(recheck)).outbound_halted:
                await queue_dial_recall()
            refusal = await person_level_refusal(
                recheck, tenant_id=tenant_id, phone_e164=phone_e164
            )
            if refusal is not None and refusal.rule in _RECALLED_PERSON_RULES:
                await enqueue_dnc_recall(
                    recheck,
                    tenant_id=tenant_id,
                    phones=[phone_e164],
                    cause=_RECALLED_PERSON_RULES[refusal.rule],
                )
    except Exception as exc:
        _alarm_unconfirmed_bookkeeping(call_id, step="stop_recheck", exc=exc)


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


#: Another engine agent's live dial from this number. Keyed on the engine agent the dial rang
#: through (`calls.engine_agent_ref`, D-1003): two campaigns in one voice are two callers on
#: the platform. A dial from before the column is read as its agent's own engine agent.
_NUMBER_LENT_ELSEWHERE_SQL: Final = (
    "SELECT count(*) FROM calls c JOIN agents a ON a.id = c.agent_id "
    "WHERE c.from_e164 = :e164 "
    "AND COALESCE(c.engine_agent_ref, a.engine_agent_ref) IS DISTINCT FROM :ref "
    "AND c.direction = 'outbound' AND c.status = ANY(:statuses) "
    "AND c.created_at > now() - make_interval(secs => :horizon)"
)


async def _hold_client_number(
    session: AsyncSession, *, number: CallerLine, engine_agent_ref: str
) -> None:
    """Refuse the dial while another engine agent is calling out on this number.

    A number is lent to one agent at a time (`update-phone-number.md:144-145`; a waiting call
    told to ring from a number lent away is not placed, `phone-numbers.md:748-753`, 2026-10-29
    mirror), so a borrowed number is held for the whole call, as the trial line is: the lock
    serialises the count with the intent row, and from commit that row's status is the hold.
    Calls through the same engine agent share it freely. Refused as `lines_busy`, which every
    caller already treats as not placed and tries again."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"client-number-lend:{number.number_id}"},
    )
    others = (
        await session.execute(
            text(_NUMBER_LENT_ELSEWHERE_SQL),
            {
                "e164": number.e164,
                "ref": engine_agent_ref,
                "statuses": _ENGINE_LINE_STATUSES,
                "horizon": ENGINE_LINE_HORIZON.total_seconds(),
            },
        )
    ).scalar_one()
    if others:
        log.info("dial_refused_number_lent_elsewhere", extra={"number_id": str(number.number_id)})
        raise lines_busy()


async def _lend_client_number(
    tenant_id: UUID, *, call_id: UUID, number: CallerLine, agent_ref: str
) -> None:
    """Lend the client's number to the agent about to dial, or close the dial unplaced."""
    from apps.api.campaigns.engine_numbers import lend_client_number

    assert number.engine_number_ref is not None
    if await lend_client_number(number.engine_number_ref, agent_ref):
        return
    await _close_unplaced_dial(tenant_id, call_id=call_id, code=CLIENT_NUMBER_UNAVAILABLE_RULE)
    raise ProblemError.business_rule(
        CLIENT_NUMBER_UNAVAILABLE_RULE,
        "The calling number could not be made ready for this agent just now.",
        remediation="Try again in a few minutes.",
    )


async def _confirm_dial(tenant_id: UUID, *, call_id: UUID, handle: str) -> bool:
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
    is ringing, and a raise would be read as "not placed" (`dispatch_call`). Returns False
    only then: the database did not answer, so nothing else is asked of it for this dial.
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
        return False
    if stamped == 0:
        log.warning("dial_handle_not_stamped", extra={"call_id": str(call_id)})
    return True


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
    # Every line in use is the account's capacity, not this call's fault: marked so the
    # attention list does not report it as a failed call and the call page says why. Every
    # other close is marked too, because the daily test-call caps count only calls with no
    # reason: a dial that rang nobody must not spend one.
    reason: NotPlacedReason = "lines_full" if code == LINES_BUSY_CODE else "refused"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET status = 'failed', not_placed_reason = :reason, "
                "updated_at = now() WHERE id = :id AND status = 'queued'"
            ),
            {"id": call_id, "reason": reason},
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

    A live number is unique across tenants (`uq_phone_numbers_e164_live`; a released row
    does not hold it), and the collision is caught
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
    session: AsyncSession,
    *,
    agent_id: UUID,
    answers_inbound: bool,
    routing: InboundRouting,
    through_lines_only: bool = False,
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
    # An agent with no engine agent of its own (D-1019) answers only on its live lines, so
    # the fix is a number on one of them rather than on the agent.
    where = "on a live inbound line of this agent" if through_lines_only else "attached to it"
    alert(
        "CORE_LOGIC",
        "agent_published_answering_no_number",
        detail=(
            f"this agent answers incoming calls and is now live, but no number is {where} "
            f"— while this client holds {orphaned} recorded number(s) attached to no "
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

NUMBER_ON_INBOUND_LINE_CODE: Final = "number_on_inbound_line"

_NUMBER_LINE_SQL: Final = (
    "SELECT l.id, l.name FROM phone_numbers n JOIN inbound_lines l "
    "ON l.id = n.inbound_line_id AND l.archived_at IS NULL "
    "WHERE n.id = :nid AND n.released_at IS NULL"
)


async def number_inbound_line(session: AsyncSession, number_id: UUID) -> tuple[UUID, str] | None:
    """The open Inbound line a number answers with, as (id, name), or None."""
    row = (await session.execute(text(_NUMBER_LINE_SQL), {"nid": number_id})).first()
    return None if row is None else (row[0], str(row[1]))


def number_on_inbound_line(line_name: str) -> ProblemError:
    """A number on an Inbound line answers with that line's own engine agent, so it is moved
    only from Inbound (D-1008). Pointing it at an agent here would bind it to that agent's
    own engine agent while Inbound still lists it on the line, and `phone_numbers.agent_id`
    would stop matching the line's agent."""
    return ProblemError.business_rule(
        NUMBER_ON_INBOUND_LINE_CODE,
        f"This number answers with your Inbound line “{line_name}”.",
        remediation="To change who answers it, change it in Inbound, on that line.",
    )


#: What decides whether attaching to this agent makes the phone ring NOW. `deleted_at IS
#: NULL` is in the predicate rather than checked afterwards so an erased agent is a 404
#: and not a 409 about an archive.
_AGENT_FOR_ATTACH_SQL = (
    "SELECT direction, status, engine_agent_ref FROM agents WHERE id = :aid AND deleted_at IS NULL"
)


async def attach_number_to_agent(
    session: AsyncSession,
    *,
    number_id: UUID,
    agent_id: UUID | None,
    onto_line: UUID | None = None,
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
    not a connection. An agent that only makes calls is accepted: the number becomes the
    line it calls out from, and nobody answers it.

    A number on an open Inbound line, draft or live, is refused with
    `number_on_inbound_line` naming the line, detach included (D-1008): the line decides
    who answers it, and a draft line's numbers already answer with the line's voice
    (`route_line_numbers`), so a change here would leave Inbound listing the number under
    an agent that no longer answers it. `onto_line` is the escape for Inbound's own move of
    a number onto that line (`inbound/routes.assign_number`), which rewrites the line's
    numbers right after.

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
    if onto_line is None:
        line = await number_inbound_line(session, number_id)
        if line is not None:
            raise number_on_inbound_line(line[1])

    answers = False
    ref = ""
    if agent_id is not None:
        agent = (await session.execute(text(_AGENT_FOR_ATTACH_SQL), {"aid": agent_id})).first()
        if agent is None:
            raise ProblemError.not_found("Agent")
        direction, status, engine_agent_ref = agent
        # Any agent can have a number, and the number does what the agent does: an agent
        # that only makes calls calls out from it (the engine's `callingAgent`, set by
        # `sync_number_attachment` from the agent's direction) and nobody answers it. The
        # number's own direction follows, kept `both` for an answering agent so the client's
        # other agents can still call out from it (shared outbound, founder 4 Nov 2026).
        inbound = _is_agent_direction(direction) and agent_answers_inbound(direction)
        await session.execute(
            text("UPDATE phone_numbers SET direction = :dir, updated_at = now() WHERE id = :nid"),
            {"dir": "both" if inbound else "outbound", "nid": number_id},
        )
        # LIVE AND PUBLISHED, or the engine is told to release rather than to bind. An
        # agent that has never been published has no ref to bind to, and a paused or
        # deleted one was deliberately taken off its numbers; `activate` republishes and
        # routes every attached number, so the attachment starts working the moment it
        # comes back. This is `provision_number`'s D-440 reasoning, on the later step.
        answers = inbound and bool(engine_agent_ref) and str(status) == "live"
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
    "CAMPAIGN_AGENT_UNNEEDED_WHERE",
    "CAMPAIGN_HOLDING_STATUSES",
    "CAMPAIGN_NUMBER_UNAVAILABLE_CODE",
    "CARRIER_SPELLINGS",
    "CLIENT_NUMBER_UNAVAILABLE_RULE",
    "CREDIT_STOP_MESSAGE",
    "DIAL_NOT_PLACED_CODES",
    "HEALER_FORWARD_LINE",
    "INBOUND_SILENCE_CREDITS",
    "INBOUND_SILENCE_HEALER",
    "INBOUND_SILENCE_PRECEDENCE",
    "INBOUND_SILENCE_REASONS",
    "INBOUND_SILENCE_TRUTHFUL_ANSWER",
    "KNOWLEDGE_PUBLISH_IN_PROGRESS",
    "LINE_HOLDER_IDLE_WHERE",
    "NUMBER_INBOUND_ONLY_REASON",
    "NUMBER_INBOUND_ONLY_RULE",
    "NUMBER_NOT_ON_CARRIER_REASON",
    "NUMBER_NOT_ON_CARRIER_RULE",
    "NUMBER_ON_INBOUND_LINE_CODE",
    "UNCONFIRMED_ENGINE_CALL_PREFIX",
    "ArmToPublish",
    "DialUnconfirmedError",
    "ForwardsLine",
    "HealerHold",
    "InboundCutover",
    "InboundRouting",
    "agent_outbound_numbers",
    "allowance_refusal",
    "apply_healer_silence",
    "attach_number_to_agent",
    "campaign_dial_backoff_s",
    "carrier_of_provider",
    "credit_stop_greeting",
    "credit_stop_prompt",
    "dial_was_not_placed",
    "dispatch_call",
    "effective_call_cap",
    "give_back_idle_test_holders",
    "healer_forward_greeting",
    "healer_forward_prompt",
    "in_call_model",
    "lift_healer_silence",
    "line_config",
    "number_inbound_line",
    "number_on_inbound_line",
    "outbound_number_provider",
    "provision_number",
    "publish_agent",
    "publish_line",
    "publish_variant",
    "publish_variants",
    "reconcile_inbound_answering",
    "reconcile_inbound_truthful_answer",
    "refuse_campaign_opening_over_limit",
    "republish_lines",
    "republish_running_variants",
    "resolve_caller_id",
    "route_inbound_numbers",
    "route_line_numbers",
    "set_number_dlt_status",
    "set_number_engine_ref",
    "unconfirmed_engine_call_id",
]
