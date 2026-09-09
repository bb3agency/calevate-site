"""The platform configuration surface (PLATFORM-CONFIG §7).

    GET    /v1/ops/config          every key: value, source, who set it, when, its etag
    PUT    /v1/ops/config/{key}    validated against Settings, conditional on If-Match
    DELETE /v1/ops/config/{key}    revert to the code default, conditional on If-Match

**EVERY WRITE IS CONDITIONAL, AND THE HEADER IS REQUIRED.** `If-Match` carries the
`etag` from the read the operator decided against; a write whose token has moved is
refused with **412** and the current value, and a request with no token at all is
refused with **428** (RFC 6585). Optional would have made "a losing write is refused" a
property of the console rather than of the surface — the runbook curl and the second
operator would keep last-write-wins. `"0"` is the token of a key with no stored row, so
creating and reverting are conditional through the same header with no second mechanism.

**A WRITE THAT CHANGES NOTHING IS A NO-OP, AND SAYS SO.** `recorded: false` means the
value was already the stored one: no row moved, no audit row landed, the sentinel did
not move and no peer re-read the store. That is D-82's convention — "I stored this" and
"this was already the value" are different sentences.

All `platform:config`, admin realm, and — like every other route under `/v1/ops` — never
shed, because an operator must not be locked out of the configuration by the load-shed
mode they are trying to change.

**Its own router rather than more routes on `ops/routes.py`.** That file is the INCIDENT
switchboard: the big red switch, the DLQ replay, the audit chain. This is
change management. They share a URL prefix and a realm and nothing else — different
permission, different step-up vocabulary, different audience — and `ops/routes.py` is
already 800 lines of argument about levers. Mounted in `apps/api/main.py` beside it.

**WHY THE WRITES TAKE A STEP-UP CONFIRMATION.** These are not incident levers, so the
case has to be made rather than inherited. `engine` decides which vendor every call in
the platform is placed through. `self_serve_inr_per_min` is the price every self-serve
client is charged. `usd_inr_rate` is the FALLBACK the USD->INR conversion uses whenever the
automatic rate pull has nothing fresh (D-475), and the rate a call was actually costed
at is stamped into `usage_events.meta` — which is how a billed minute is re-derived a
year later (hard rule 7). A stolen admin session that
could change any of those with one POST would be able to reprice the platform or divert
every call, silently, from a tab left open on an unlocked laptop. The confirmation names
the KEY, so a header captured while raising a pool size cannot switch the engine.

**AND WHY THE REASON IS REQUIRED.** Same argument as `halt_reason` on the big red
switch, one surface along: whoever finds the calling window at 09:00 instead of 10:00
has to decide whether the change still holds, and "somebody changed it in July" is not
an answer. It goes into the row (`note`, the live answer) AND into `audit_log` (the
history), for the reason `ops/routes.py::set_platform` records: the audit log has no
summary column, so a reason that lives only in the log stream is a reason nobody finds.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.credit_packs import PACK_CATALOGUE, CreditPack, card_margins, card_refusals
from apps.api.billing.list_rates import (
    CARD_NOTICE_DAYS,
    PACK_RATE_KEY_PREFIX,
    SELF_SERVE_PER_MIN,
    cancel_card,
    card_at,
    card_is_scheduled,
    card_list_rate,
    card_with_rates,
    notice_refusal,
    pending_cards,
    record_card,
)
from apps.api.billing.plans import ist_billing_month
from apps.api.billing.rates import (
    CARTESIA_COST_FLOOR_INR_PER_MIN,
    CARTESIA_PLANS,
    CARTESIA_VOLUME_LADDER_CALL_MINUTES,
    MIN_GROSS_MARGIN,
    MONEY_Q,
    PREPAID_TIERS,
    ROUNDING,
    TTS_ASSUMED_CHARS_PER_CALL_MINUTE,
    VOICE_TIERS,
    CartesiaPlan,
    VoiceTier,
    cartesia_best_marginal_cost_inr_per_min,
    cartesia_cheapest_plan,
    cartesia_cost_floor_inr_per_min_at,
    cartesia_cost_inr_per_call_minute,
    cartesia_measured_cost_inr_per_call_minute,
    cartesia_plan_crossover_call_minutes,
    cartesia_plan_marginal_cost_inr_per_min,
    cartesia_rung_breakeven_call_minutes,
    cost_floor_inr_per_min,
    rate_margin,
    voice_tier_label,
)
from apps.api.billing.tts_volume import CartesiaVolume, fleet_cartesia_volume
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, global_db
from apps.api.core.errors import ProblemError
from apps.api.core.fx import UsdInrRate, usd_inr_rate_now
from apps.api.core.logging import get_logger
from apps.api.core.platform_config import (
    ConfigField,
    StoredRow,
    describe,
    etag_for,
    parse_etag,
    project,
    snapshot,
    typed_value,
)
from apps.api.core.rbac import permission_meta
from apps.api.core.settings import (
    ENV_ONLY_DISPLAY,
    effective_env,
    env_declares,
    env_var_for,
    get_settings,
)
from apps.api.core.stepup import StepUpGate
from apps.api.ops.config_service import (
    WriteResult,
    clear_value,
    propagate,
    read_rows,
    read_sentinel,
    set_value,
)
from apps.api.reliability.service import enqueue_outbox_once

log = get_logger(__name__)

router = APIRouter(prefix="/v1/ops/config", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
#: The TENANT-DIRECTORY session, for the one question on this module that is about
#: clients rather than about the platform: how many of them a rate card would have to be
#: announced to. `organizations` is the tenant root and FORCEs RLS, so `global_db` returns
#: ZERO rows from it — a count read there would silently be "nobody", which is the worst
#: possible answer to put next to a Record button. `admin_db` takes the admin principal as
#: a dependency and widens `USING` on `organizations` alone (`db/session.admin_session`).
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
# The permission, once, as an `Annotated` alias — the house pattern for a `*_routes.py`
# module (`billing/cap_routes.py`, `admin/holds_routes.py`). The boot assertion walks the
# whole dependency tree, so a permission reached through a shared alias counts exactly
# like one written on the handler (`core/rbac.route_enforcement`).
ConfigOperator = Annotated[Principal, Depends(requires("platform:config", realm="admin"))]

# A `Settings` field name. Bounded at the boundary because it is interpolated into a
# step-up string and an audit summary, and a path parameter is attacker-controlled on
# any surface. The pattern is Python's own identifier shape for a lower-case field —
# whatever the router does with it, it is [a-z0-9_] and short. NOT an allow-list of
# known keys: the service refuses an unknown one by name, and a second copy of the
# managed set here is the drift this slice exists to avoid.
ConfigKey = Annotated[str, Path(max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]

#: The value a setting may hold on the wire.
#:
#: JSON SCALARS ONLY, and that is a decision rather than a limitation. Every `Settings`
#: field today is a scalar — `str`, `int`, `float`, `bool`, `Decimal`, or a `Literal` —
#: so a union that also admitted objects would be a free-form `dict[str, Any]` in the
#: schema, which `check_redaction_exposure` correctly flags as "whatever the query
#: selected is serialized verbatim". Money arrives as a STRING (`"88.50"`), never as a
#: JSON float: hard rule 7 does not stop at the database. A future list- or dict-valued
#: setting widens this type deliberately, with that guardrail entry as the review.
ConfigValue = str | bool | int | float | None


#: What lands in the audit summary's `reason` for a revert.
#:
#: A revert takes no body — DELETE has none, and adding one would break the console's
#: button and the runbook's curl to buy a free-text field nobody reads back (the same
#: call `replay_outbox` makes). So the reason is CONSTANT and states the act itself,
#: which is honest: "why" for a revert is always the same sentence, and the interesting
#: half — which value it was and who removed it — is already in the row above it.
REVERT_REASON = "reverted to the code default from the ops console"


def config_confirmation(key: str) -> str:
    """The step-up string for setting ONE key.

    A named function rather than an inline f-string, for the reason
    `spend_cap_confirmation` and `outbox_replay_confirmation` are: these strings are an
    ops PROCEDURE that a runbook prints and a test pins, so changing the shape has to
    fail a test rather than quietly leave a documented curl being refused.

    Bound to the KEY, because that is the part of the action an operator could get wrong
    by replaying a header they already had: consent to raising `db_pool_size` is not
    consent to switching `engine`.
    """
    return f"set_config:{key}"


def revert_confirmation(key: str) -> str:
    """The step-up string for reverting ONE key to its code default.

    A DIFFERENT string from `config_confirmation`, deliberately. Reverting is not the
    small sibling of setting: on a deployment whose console is the source of truth, it
    is the act that puts a value nobody has looked at in months back into force. A
    header captured for either must not authorise the other.
    """
    return f"revert_config:{key}"


class ConfigFieldOut(BaseModel):
    """One managed key, as the console renders it.

    NO FIELD HERE CARRIES A DEFAULT, and that is load-bearing rather than tidy. A
    Pydantic field with a default is OPTIONAL in the generated TypeScript, so the
    console would have to write `field.editable ?? true` — and the fallback for
    "we do not know whether this is editable" would be "offer the form". Every fact the
    console must trust is required on the wire; `null` is used where the answer
    genuinely has no value, which is a different thing from absent.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    #: The variable that sets this key in the environment, so the read-only refusal can
    #: tell an operator exactly what to change instead.
    env_var: str
    #: The value IN FORCE in the process that served this request — read off its own
    #: `Settings`, not recomputed from the layers, so the screen shows what is running.
    value: ConfigValue
    #: `env` | `db` | `default`. The console renders `env` read-only WITH the reason:
    #: the environment always wins (§4), and a field that silently does nothing is worse
    #: than no field (§8).
    source: str
    #: What reverting would restore. Meaningless unless `has_default`.
    default: ConfigValue
    #: False for a required field, which has no code default and therefore cannot be
    #: reverted. Distinct from `default: null`, which most optional fields legitimately
    #: have.
    has_default: bool
    #: How to render an editor: string | integer | number | boolean | enum | decimal.
    #: Derived from the field's own annotation, so a type change moves the editor with
    #: it. `decimal` is money and must stay a string end to end.
    kind: str
    #: The permitted values for `kind == "enum"`; empty otherwise.
    options: list[str]
    editable: bool
    #: `live` | `on_restart` | `needs_republish` | `env_only` | `unclassified` — when a
    #: change actually takes effect. THE MOST LOAD-BEARING FIELD IN THIS MODEL: a key
    #: reported `live` that is really snapshotted at process start is a lie that costs an
    #: outage, so the console must render this verbatim and never assume a default.
    #: `needs_republish` means a restart does NOT fix it — something must be published
    #: again. `env_only` and `unclassified` always arrive with `editable: false`.
    applies: str
    #: What the operator still has to do after changing it, or null. Non-null for every
    #: `applies` except `live`.
    caveat: str | None
    #: The concurrency token for this key. Send it back as `If-Match` on a PUT or a
    #: DELETE; a write whose token has moved is refused with 412 rather than merged.
    #: `"0"` means "no row is stored", which is a state a write can be conditional on.
    etag: str
    updated_by: str | None
    updated_at: str | None
    note: str | None


class BootstrapKeyOut(BaseModel):
    """A §4 bootstrap key: real, required, and changeable ONLY on the VPS.

    THESE ARE NOT IN `fields` AND NEVER WILL BE, and that absence was the problem. An
    operator looking for `APP_ENV` on this screen found nothing at all, which reads
    identically to "this build does not have that setting" — so the one class of key that
    genuinely does need an SSH session and a restart was the one the console said nothing
    about. It says it here instead, with the reason, beside the keys it CAN change.

    NO VALUE, EVER. Two of the six are `PLATFORM_KEK` and `PLATFORM_KEK_RETIRED` — the
    keys that open the credential store — and one is `DATABASE_URL`, which carries a
    password. `configured` is presence and nothing more, which is the only fact an
    operator needs from a screen (hard rule 6 applies to a response body exactly as it
    applies to a log line).
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    env_var: str
    #: Why it can never move into the store.
    reason: str
    #: True when this deployment's environment declares it. Presence, never the value.
    configured: bool


class ConfigOut(BaseModel):
    """The whole managed surface, plus how much this answer can be trusted.

    `config_version` and `stale` ride along for the §52 reason: a console that showed
    values without saying whether the process could still reach the store would render a
    snapshot from an hour ago identically to a live one.
    """

    model_config = ConfigDict(extra="forbid")

    fields: list[ConfigFieldOut]
    #: The `platform_config_version` this process's snapshot was built from. 0 means it
    #: has never successfully read the store.
    config_version: int
    #: True when the last refresh FAILED. The values shown are the last good ones, so
    #: this is "possibly stale", never "wrong" — and never a reason to hide them.
    stale: bool
    #: True when this process has NEVER read the store: it is running on environment
    #: variables and code defaults, and a change made here may not be reflected in what
    #: it reports. A cold start with an unreachable database (§6).
    never_loaded: bool
    #: When the configuration last changed, from the DATABASE's own sentinel rather than
    #: from this process's snapshot. It is what makes `config_version` legible: a version
    #: bumped four seconds ago and one bumped four days ago mean different things to an
    #: operator whose change is not appearing. Null on a database that has never had one.
    config_changed_at: str | None
    #: The keys this console can NEVER change, with the reason and whether they are set.
    #: Rendered as its own read-only panel: everything in `fields` takes effect without a
    #: restart, and everything here needs an SSH session and one. No values.
    bootstrap: list[BootstrapKeyOut]


class ConfigSetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The new value, in its JSON form. Money as a string (`"88.50"`), never a float.
    value: ConfigValue
    #: REQUIRED, and required with content — the same bounds and the same argument as
    #: `PlatformStateIn.reason`: whoever finds this value in force has to be able to
    #: decide whether the condition still holds.
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _not_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("a reason is required — say what this changes, and why")
        return stripped


class ConfigWriteOut(BaseModel):
    """What changed, and the field as it now stands.

    The FIELD is returned rather than a bare acknowledgement so the console re-renders
    from the server's own view — including `source`, which is the one thing a write can
    change in a way the form would not predict (a value equal to the default still
    reports `db`, because a row exists and reverting it is now a distinct act).
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    #: The stored value before this request; null when there was no row.
    previous: ConfigValue
    field: ConfigFieldOut
    #: The config version after the write. Peers are on it within a poll interval.
    config_version: int
    #: False when the submitted value was ALREADY the stored value: nothing was written,
    #: no audit row exists for this request, the sentinel did not move and no process in
    #: the fleet re-read the store. D-82's convention — the console renders "already the
    #: value" rather than a change nobody made.
    recorded: bool
    #: The key's token AFTER this request, for the operator's next conditional write.
    #: Also returned in the `ETag` response header.
    etag: str


def _out(field: ConfigField) -> ConfigFieldOut:
    return ConfigFieldOut(
        key=field.key,
        env_var=field.env_var,
        value=field.value,
        source=field.source,
        default=field.default,
        has_default=field.has_default,
        kind=field.kind,
        options=list(field.options),
        editable=field.editable,
        applies=field.applies,
        caveat=field.caveat,
        etag=field.etag,
        updated_by=field.updated_by,
        updated_at=field.updated_at,
        note=field.note,
    )


def require_if_match(header: str | None, *, key: str) -> int:
    """The revision this caller believes it is writing over, or a refusal.

    REQUIRED, NOT OPTIONAL, and that is the decision worth stating. An optional
    precondition protects only the callers who remember to send one — which is the
    console, on the day it is written, and nothing else. The runbook curl, the second
    console, the operator with a shell: all of them keep last-write-wins, and the
    property "a losing write is refused" stops being a property of the SURFACE and
    becomes a property of one client. 428 (RFC 6585) is the status for exactly this: the
    server requires the request to be conditional, and it says which header.

    A caller with no value to send is not stuck: `If-Match: "0"` is the token of a key
    with no stored row, and it is what a GET reports for one.
    """
    if header is None:
        raise ProblemError(
            kind="conflict",
            status=428,
            code="config_if_match_required",
            title="This change has to say what it is replacing",
            detail=(
                "Writes to a platform setting are conditional, so two operators editing "
                "the same key cannot silently overwrite each other."
            ),
            remediation=(
                "Read GET /v1/ops/config, take this field's `etag`, and send it as "
                'If-Match. A key with no stored value has the etag "0".'
            ),
        )
    revision = parse_etag(header)
    if revision is None:
        raise ProblemError(
            kind="validation",
            code="config_if_match_invalid",
            title="That If-Match is not one of ours",
            detail=f"{header!r} is not an entity-tag this surface issues.",
            remediation=(
                "Send the `etag` from GET /v1/ops/config verbatim, quotes included — "
                'e.g. If-Match: "42". `*`, weak tags and lists are deliberately '
                "refused: each of them would let an unconditional write through."
            ),
            fields=[{"field": key, "rule": "if_match", "message": "expected a quoted integer"}],
        )
    return revision


async def _fields(session: AsyncSession) -> list[ConfigFieldOut]:
    return [_out(f) for f in describe(get_settings(), rows=await read_rows(session))]


async def _field(session: AsyncSession, key: str) -> ConfigFieldOut:
    """One key's post-write view, assembled from the same function the list uses.

    Deliberately not a second, cheaper query: the list and the single-key view must never
    be able to disagree about a source or an `editable`, and the cost here is one small
    SELECT on a connection that is already open.
    """
    for field in await _fields(session):
        if field.key == key:
            return field
    # Unreachable: the service refused every unmanaged key before the write. Raising
    # rather than returning a placeholder, because a config surface inventing a row is
    # worse than a 500 an operator can report.
    raise ProblemError(
        kind="internal",
        code="config_key_vanished",
        title="The setting could not be read back",
        detail=f"{key!r} was saved, but Calevate could not read it back afterwards.",
    )


@router.get(
    "",
    response_model=ConfigOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Every managed platform setting, with its value, source and provenance",
    description=(
        "Lists every `Settings` field that can be managed from the console: its current "
        "value in the serving process, where that value came from (`env` / `db` / "
        "`default`), who set it and when. A key set in the environment is reported "
        "`source: env` and `editable: false` — the environment always wins over the "
        "store, so offering to change it here would be a field that does nothing. "
        "Credentials are NOT in this list; they live encrypted in platform_secrets."
    ),
)
async def read_config(session: GlobalSession, _: ConfigOperator) -> ConfigOut:
    current = snapshot()
    # The sentinel is read from the DATABASE, not from this process's snapshot: the two
    # answer different questions, and the interesting case is exactly when they disagree
    # (this process is behind, and the operator needs to see that rather than a
    # self-consistent story).
    sentinel = await read_sentinel(session)
    environ = effective_env()
    return ConfigOut(
        fields=await _fields(session),
        config_version=current.version,
        stale=current.degraded,
        never_loaded=current.loaded_at is None,
        config_changed_at=sentinel.changed_at,
        bootstrap=[
            BootstrapKeyOut(
                key=key,
                env_var=env_var_for(key),
                reason=reason,
                configured=env_declares(key, environ),
            )
            for key, reason in sorted(ENV_ONLY_DISPLAY.items())
        ],
    )


@router.put(
    "/{key}",
    response_model=ConfigWriteOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Set one platform setting (step-up confirmed, audited)",
    description=(
        "Validates the value against the same `Settings` model the application loads at "
        "boot — including the field's own constraints — and refuses it here if the app "
        "would refuse it there. Requires `X-Confirm-Action: set_config:<key>`. The "
        "change reaches every other process within a few seconds without a restart; a "
        "field whose `applies` is `on_restart` is the exception and says so."
    ),
)
async def set_config(
    payload: ConfigSetIn,
    session: GlobalSession,
    request: Request,
    response: Response,
    tasks: BackgroundTasks,
    principal: ConfigOperator,
    key: ConfigKey,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
    if_match: Annotated[str | None, Header()] = None,
) -> ConfigWriteOut:
    """Bound to the key, audited in the same transaction, propagated after it commits."""
    step_up.require(x_confirm_action, config_confirmation(key))
    expected = require_if_match(if_match, key=key)
    if principal.user_id is None:
        # `updated_by` is NOT NULL and references `admin_users`: every value in this
        # table was put there by a person. An admin principal always has one; refusing
        # explicitly turns an impossible state into a sentence rather than an integrity
        # error rendered as a 500.
        raise ProblemError(
            kind="auth",
            code="config_actor_unknown",
            title="This session has no admin identity",
            detail="A configuration change has to be attributable to an operator.",
        )

    result = await set_value(
        session,
        key=key,
        value=payload.value,
        note=payload.reason,
        actor_id=principal.user_id,
        expected_revision=expected,
    )
    if result.recorded:
        # NO AUDIT ROW FOR A NO-OP. `audit_log` is hash-chained and is the answer to
        # "who changed this and when"; an entry for a request that changed nothing would
        # put a double-clicked Save into the permanent record as two changes.
        await _audit(
            session, request, principal, result, action="platform.config_set", reason=payload.reason
        )
        # THE PRICE ACQUIRES A DATE (D-492). Same transaction as the row above, for the
        # reason the audit entry is: a rate change nobody can place in time re-prices every
        # month rendered after it.
        await _record_card(session, result, actor_id=principal.user_id, reason=payload.reason)
    return _write_out(response, result, tasks)


@router.delete(
    "/{key}",
    response_model=ConfigWriteOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Revert one platform setting to its code default (step-up confirmed, audited)",
    description=(
        "Deletes the stored row so the value falls back to the environment, or to the "
        "code default when the environment does not set it. Requires "
        "`X-Confirm-Action: revert_config:<key>` — a DIFFERENT string from setting it, "
        "because reverting puts a value nobody has looked at recently back into force."
    ),
)
async def revert_config(
    session: GlobalSession,
    request: Request,
    response: Response,
    tasks: BackgroundTasks,
    principal: ConfigOperator,
    key: ConfigKey,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
    if_match: Annotated[str | None, Header()] = None,
) -> ConfigWriteOut:
    """Reverting a key that was never overridden is a 404, not a cheerful success.

    The row is what would be removed, and there is none. Answering 200 would put a
    `platform.config_reverted` entry in a tamper-evident ledger for a change nobody made
    — the same objection `platform_confirmation` raises against the empty transition.
    """
    step_up.require(x_confirm_action, revert_confirmation(key))
    expected = require_if_match(if_match, key=key)
    if principal.user_id is None:
        raise ProblemError(
            kind="auth",
            code="config_actor_unknown",
            title="This session has no admin identity",
            detail="A configuration change has to be attributable to an operator.",
        )

    result = await clear_value(
        session, key=key, actor_id=principal.user_id, expected_revision=expected
    )
    if result is None:
        raise ProblemError(
            kind="not_found",
            code="config_not_overridden",
            title="Nothing to revert",
            detail=f"{key!r} has no stored value, so it is already at its default.",
            remediation=(
                "The value in force comes from the environment or from the built-in "
                "default; the settings list shows which."
            ),
        )
    await _audit(
        session,
        request,
        principal,
        result,
        action="platform.config_reverted",
        # A revert leaves no row, so its reason lives ONLY in the audit summary. That is
        # the asymmetry with `set`: there is no `note` column left to read it from, and
        # `audit_log` is the whole history of why a value went back to its default.
        reason=REVERT_REASON,
    )
    # A REVERT MOVES THE PRICE TOO, and it is the one an operator forgets: the value goes
    # back to the environment or the code default, which is a rate change like any other.
    await _record_card(session, result, actor_id=principal.user_id, reason=REVERT_REASON)
    return _write_out(response, result, tasks)


async def _audit(
    session: AsyncSession,
    request: Request,
    principal: Principal,
    result: WriteResult,
    *,
    action: str,
    reason: str,
) -> None:
    """§9's row: actor, key, old → new, source and the operator's stated reason.

    Written on the caller's session — `global_db` commits at the end of the request — so
    the change and the record of who made it land together or neither does. That is
    money's rule (BACKEND-PATTERNS §4) applied to configuration, and it is the reason
    this is a helper both routes call rather than two literals that drift.

    The VALUES are in the summary because they are the change itself and this table
    holds no credentials by construction (`is_secret_key` refuses those at the
    boundary). The summary goes through `redact_mapping` on its way to the log stream
    like every other one, so a value that does look secret-shaped is masked there anyway.
    """
    await write_audit(
        session,
        action=action,
        actor=principal,
        object_type="platform_settings",
        object_id=result.key,
        ip=client_request_ip(request),
        summary={
            "config_key": result.key,
            "old": result.old,
            "new": result.new,
            # Where the value will now come FROM. `db` for a set, and for a revert
            # whichever layer takes over — which is the fact an operator needs, because
            # "reverted" does not mean "back to the code default" on a deployment that
            # also sets the variable in its environment.
            "source": "db" if result.new is not None else "env_or_default",
            "reason": reason,
            "config_version": result.version,
        },
    )


def _write_out(response: Response, result: WriteResult, tasks: BackgroundTasks) -> ConfigWriteOut:
    """The response, and the propagation, in the only order that is correct.

    THE ORDERING PROBLEM, stated because it is easy to get backwards. The row is written
    on a transaction that has NOT committed — `global_db` commits when the request ends —
    so refreshing the process snapshot here would read the state from before this write
    and report the old value back to the operator who just changed it. Two consequences:

    * the response is rendered from a PROJECTION (`platform_config.project`): this
      process's settings with this write applied. It is what the platform will be running
      one commit from now, and it is the honest thing to show the person who asked for it.
    * `propagate()` runs as a BACKGROUND TASK, which FastAPI executes after the response
      is sent and therefore after the dependency's transaction has committed. It rebuilds
      this process's snapshot for real and publishes the new version to Redis so peers
      pick it up on their next poll rather than waiting for the cached sentinel to expire.

    Neither is the guarantee. The guarantee is the trigger's bump plus every process's
    own poll (§6) — the background task only makes it faster, and its failure is logged
    and survivable.

    A NO-OP SCHEDULES NOTHING. If the value was already the stored one, no row moved and
    the sentinel did not move either; `propagate()` would force every process in the
    fleet to re-read Postgres for a change that did not happen, which is the cost a
    double-clicked Save must not have.
    """
    if result.recorded:
        tasks.add_task(propagate)
    etag = etag_for(result.revision)
    response.headers["ETag"] = etag
    return ConfigWriteOut(
        key=result.key,
        previous=result.old,
        field=_projected_field(result),
        config_version=result.version,
        recorded=result.recorded,
        etag=etag,
    )


def _projected_overrides(result: WriteResult) -> dict[str, Any]:
    """This process's stored overrides with `result` applied — the state one commit away.

    Extracted from `_projected_field`, which computed it inline, when a second caller
    needed it: `_record_card` has to know the value that will be IN FORCE after the
    write, and for a REVERT that is not `result.new` (which is `None`) but whatever the
    environment or the code default takes over with. Two spellings of "the projection"
    would be two answers to what the platform is about to be running.
    """
    overrides = dict(snapshot().overrides)
    if result.new is None:
        overrides.pop(result.key, None)
    else:
        overrides[result.key] = typed_value(result.key, result.new)
    return overrides


async def _record_card(
    session: AsyncSession, result: WriteResult, *, actor_id: UUID, reason: str
) -> None:
    """Date the CARD in force, in the same transaction as the setting that triggered it.

    **WHY A SECOND STORE FOR A PRICE (D-492).** `platform_settings` is keyed by `key`:
    changing `self_serve_inr_per_min` OVERWRITES the row, so the store that holds the price
    cannot say what the price WAS. Two money readers needed exactly that — a closed month's
    statement (`billing/service.calling_revenue_inr`) and a late-settling call's wallet debit
    (`workers/pipeline`) — and both were reading today's rate for a month that had already
    been charged at another one. `platform_list_rates` is the effective-dated home;
    `platform_settings` keeps its job, which is what the platform charges RIGHT NOW.

    **AND WHY IT WRITES TWELVE ROWS NOW, NOT ONE (D-547).** The self-serve price is no
    longer one number: it is six packs x two voices (`billing/credit_packs.PACK_CATALOGUE`),
    and Phase B freezes a purchase's rates onto its lot from the card in force at that
    instant. So the thing that has to acquire a valid time is the whole card, written under
    ONE `effective_from` (`list_rates.record_card` argues why one instant matters). The
    legacy `self_serve_inr_per_min` row is written alongside it, still holding the setting's
    projected value, because every reader of `self_serve_rate_at` is still live (plan §10).

    **THE MARGIN IS PREVIEWED, AND A BAD CARD IS REFUSED BEFORE ANYTHING IS WRITTEN.**
    Twelve verdicts are computed (`credit_packs.card_margins`) and logged — thin rows at
    `warning`, the rest at `info` — so the operator who pressed Save has the number beside
    the act, and `card_refusals` is the veto: a rate below its voice's cost floor, or a card
    that breaks invariant 6, raises a `ProblemError` and the transaction carries nothing.
    Today the card is a code constant, so a refusal here means CI's own pack guard was
    bypassed — which is the point of a second gate at the write path rather than only at the
    build: `admin/routes.py` applies exactly this posture to a committed bundle's rates.

    Written HERE rather than inside `set_value`/`clear_value` because those are the generic
    config writers and this is a fact about one key; and on the caller's session, so the
    price and the record of when it changed commit together or neither does.

    THE VALUE RECORDED FOR THE LEGACY KEY IS THE PROJECTION, NOT `result.new`. A revert
    leaves no row and its `new` is `None`, but the platform still starts charging something
    — whatever the environment or the code default takes over with — and that is the figure
    a month rendered afterwards has to resolve.

    A NO-OP RECORDS NOTHING, for the reason `_audit` skips one: a double-clicked Save must
    not put two price changes into an append-only history that cannot be corrected by an
    edit.
    """
    if result.key != SELF_SERVE_PER_MIN or not result.recorded:
        return
    # THE CARD IN FORCE, NOT THE COMMITTED CATALOGUE, AND THAT IS THE WHOLE FIX (D-550).
    # The card became operator-editable, so `PACK_CATALOGUE` is no longer "the rates we
    # sell" — it is the FALLBACK for a cell nobody has recorded. Re-stamping the catalogue
    # here would have made an unrelated setting change (`self_serve_inr_per_min` moving by a
    # paisa) silently revert every rate an operator had published, at the instant of the
    # save, with a green response. This re-dates what is already in force, so the write is a
    # no-op in rupees and remains what it always was: the record that the platform's own
    # price moved at this instant.
    in_force = card_with_rates(await card_at(session, at=datetime.now(UTC)))
    _refuse_bad_card(in_force)
    _log_margins(in_force)
    settings, _ = project(_projected_overrides(result))
    await record_card(
        session,
        card=in_force,
        self_serve_inr_per_min=settings.self_serve_inr_per_min,
        recorded_by=actor_id,
        note=reason,
    )


def _refuse_bad_card(card: tuple[CreditPack, ...]) -> None:
    """`card_refusals` as a 409 an operator can act on. THE ONE VETO, both write paths.

    Shared by the setting path above and by the card write route below rather than written
    twice, because the two refusing on different rules is exactly how a card that CI's own
    pack guard would fail reaches the table through the other door.
    """
    refusals = card_refusals(card)
    if refusals:
        raise ProblemError(
            kind="conflict",
            code="rate_card_below_floor",
            title="The rate card cannot be published",
            detail=(
                "Calevate refused to record this rate card because it would sell minutes "
                "below what they cost, or would let a bigger pack buy a dearer minute: "
                + "; ".join(refusals)
            ),
            remediation=(
                "Raise the rates named above, or lower the ones they are compared against, "
                "and record the card again. The per-minute cost floor for each voice is on "
                "the rate-card read."
            ),
        )


def _log_margins(card: tuple[CreditPack, ...]) -> None:
    """The twelve verdicts, beside the act that published them. Thin at `warning`.

    The operator who pressed Save has the number in the same log stream as the write, and
    it is the SAME function CI scores (`credit_packs.card_margins`) and the same one the
    read route renders — three surfaces, one arithmetic.
    """
    for pack_id, voice, verdict in card_margins(card):
        log.log(
            logging.WARNING if verdict.below_target else logging.INFO,
            "rate_card_margin_preview",
            extra={
                "pack_id": pack_id,
                "voice_tier": voice,
                # Rates and margins are money-shaped and go out as strings for hard rule 7's
                # reason: a float in a log line is a float somebody quotes back.
                "inr_per_min": str(verdict.rate),
                "cost_floor_inr_per_min": str(verdict.cost),
                "gross_margin": None if verdict.margin is None else str(verdict.margin),
                "below_target": verdict.below_target,
            },
        )


def _projected_field(result: WriteResult) -> ConfigFieldOut:
    """This key as it will stand once the caller's transaction commits.

    The provenance (`updated_by`, `updated_at`, `note`) is deliberately NOT re-read from
    the row here — it would be the caller's own uncommitted write, and the console
    re-fetches the list anyway. What matters in this response is the value and the
    SOURCE, because `source` is the one thing a write changes in a way the form cannot
    predict: a value equal to the code default still reports `db` afterwards, since a row
    now exists and reverting it has become a distinct act.
    """
    settings, projected = project(_projected_overrides(result))
    rows = {
        result.key: StoredRow(updated_by=None, updated_at=None, note=None, revision=result.revision)
    }
    for field in describe(settings, rows=rows, snap=projected):
        if field.key == result.key:
            return _out(field)
    raise ProblemError(
        kind="internal",
        code="config_key_vanished",
        title="The setting could not be read back",
        detail=f"{result.key!r} was saved, but Calevate could not read it back afterwards.",
    )


# --- the card, as a VIEWER (D-547) ------------------------------------------------
#
# Its own router and its own prefix: the card is not a `Settings` key and cannot be written
# through this file's three routes, which is exactly why the panel that shows it is a viewer.
# It lives in THIS module because the card's write path, its margin preview and its refusal
# check are all here (`_record_card`) — the numbers an operator reads must come from the
# same three functions that score them, or the screen and the gate would be two opinions.
rate_card_router = APIRouter(prefix="/v1/ops/rate-card", tags=["ops"])

#: The instant the CARD in force was dated. `NULL` on a deployment that has never recorded
#: one, which is the honest answer and not a zero date: `list_rates.card_at` falls back to
#: the committed catalogue per cell for exactly that state, so the rates below are real
#: while their effective instant is genuinely unknown.
#: `NOT EXISTS` against the cancellations for `list_rates._NOT_CANCELLED`'s reason, spelled
#: here rather than imported because this is a different question (the max instant, not a
#: per-key resolution) and a shared fragment that only fits one of them is a fragment that
#: will be edited for the other. A card an operator withdrew must not date the panel.
_CARD_EFFECTIVE_FROM = (
    "SELECT max(effective_from) FROM platform_list_rates "
    "WHERE rate_key LIKE :prefix AND effective_from <= now() "
    "AND NOT EXISTS (SELECT 1 FROM platform_list_rate_cancellations c "
    "WHERE c.effective_from = platform_list_rates.effective_from)"
)

#: HOW MANY CLIENTS A NEW CARD WOULD HAVE TO BE TOLD ABOUT — the number the console puts
#: beside the Record button, so an operator knows the size of what they are about to send
#: BEFORE they send it rather than from the mailbox afterwards.
#:
#: THE PREDICATE IS THE FAN-OUT'S, DELIBERATELY, and it is spelled from the same constant
#: rather than from a literal: `apps/workers/rate_card_notice._WALLET_TENANTS` selects
#: every organization with an address of record and then keeps the ones whose plan tier is
#: in `rates.PREPAID_TIERS` — the managed (invoiced) accounts are excluded because the
#: credit-pack card does not price them, so telling them their prices are changing would
#: be false. Two spellings of "who has a wallet" is how one of them drifts, so this asks
#: the same two questions in one statement and the tier list is the shared constant.
#:
#: It is an ESTIMATE OF THE BOOK AT READ TIME and the panel says so: the fan-out runs when
#: the card is recorded and reads the directory again, so a client who signs up in between
#: is notified and is not in this number.
_NOTICE_RECIPIENTS = (
    "SELECT count(*) FROM organizations "
    "WHERE billing_email IS NOT NULL AND billing_email <> '' "
    "AND plan_tier = ANY(:tiers)"
)

#: The ARQ function name registered in `apps/workers/settings.FUNCTIONS`. The outbox
#: dispatcher publishes `job` verbatim, so this string IS the contract with the worker
#: (`scripts/check_job_wiring.py` is what stops it becoming a silent no-op).
RATE_CARD_NOTICE_JOB = "fan_out_rate_card_notice"


def rate_card_confirmation(effective_from: datetime) -> str:
    """The step-up string for recording a card. BOUND TO THE DATE, for `config_confirmation`'s
    reason one surface along: a confirmation captured while scheduling a rise for December
    must not be replayable against one that starts tomorrow week."""
    return f"record_rate_card:{effective_from.isoformat()}"


def rate_card_cancel_confirmation(effective_from: datetime) -> str:
    """The step-up string for withdrawing one. A DIFFERENT string from recording it —
    `revert_confirmation`'s argument exactly: withdrawing a scheduled change puts the
    current card back into force for a period nobody has looked at recently."""
    return f"cancel_rate_card:{effective_from.isoformat()}"


class RateCardCellOut(BaseModel):
    """One rung on one voice: what we sell it at, what it costs us, and the verdict.

    EVERY FIGURE IS A DECIMAL STRING (hard rule 7) and every verdict is the SERVER's. The
    console derives no arithmetic — `gross_margin_pct` is computed here from
    `rates.gross_margin_ratio`, the one definition of the word, so the panel, the write-path
    preview and CI's own pack guard cannot report three margins for one cell.
    """

    model_config = ConfigDict(extra="forbid")

    pack_id: str
    amount_inr: str
    #: The wire spelling of the voice tier — the vendor's name, which this console names
    #: deliberately (an operator connects a rate to the key they installed).
    voice_tier: str
    #: What a CLIENT calls that voice, from `billing/rates.voice_tier_label`.
    tier_label: str
    inr_per_min: str
    #: What the minute costs us on this leg — the floor `card_refusals` refuses below.
    #: Published because it appeared on no surface at all before this route: the margin was
    #: computed, logged once inside the write path, and never shown to anyone.
    cost_floor_inr_per_min: str
    #: The gross margin as a PERCENTAGE string ("17.60"). `null` only where no margin is
    #: defined (a non-positive rate), which is a real state and not a zero.
    gross_margin_pct: str | None
    #: Under the target but above cost — a warning. The approved Sarvam column is
    #: deliberately in this band down to 8.4%, so a console that treated it as an error
    #: would refuse the founder's own card.
    below_target: bool
    #: Below cost. `card_refusals` refuses the write; nothing may be sold here.
    below_floor: bool
    #: **HOW MANY CARTESIA CALL-MINUTES A MONTH THE WHOLE PLATFORM MUST SPEAK BEFORE THIS
    #: RUNG STOPS LOSING MONEY AND STAYS THAT WAY** (`rates
    #: .cartesia_rung_breakeven_call_minutes`). `null` on every Sarvam cell, whose cost is a
    #: per-character list price and does not move with volume, and `null` on a Cartesia rate
    #: no volume can rescue — two different absences, both a stated absence and never a 0.
    breakeven_call_minutes: str | None
    #: What this minute costs us AT THE VOLUME THE PLATFORM ACTUALLY RAN THIS MONTH, and the
    #: margin and verdicts that follow from it. `cost_floor_inr_per_min` above is a
    #: STRUCTURAL bound — the worst marginal cost, which is what the write path refuses
    #: below — and on a subscription-billed voice it is not what a month cost. These four
    #: are the founder's second decision of 9 Sep 2026: judge the margin at actual volume.
    #:
    #: All four are `null`/`false` when no month volume could be measured (nobody has spoken
    #: a Studio minute yet), which the console renders as a stated absence. On a Sarvam cell
    #: they equal the structural figures beside them, because that voice's cost genuinely
    #: does not depend on volume — the same number twice is the honest answer, not a gap.
    cost_inr_per_min_at_volume: str | None
    gross_margin_pct_at_volume: str | None
    below_target_at_volume: bool
    below_floor_at_volume: bool


class CartesiaPlanOut(BaseModel):
    """One Cartesia subscription an operator could be on, as the console renders it.

    EVERY FIGURE IS THE SERVER'S DECIMAL STRING (hard rule 7) and every one of them is
    derived from the vendor's three inputs — fee, allotment, overage — rather than typed.
    `tts_concurrency` is NOT money and is published anyway, because the cheapest plan is not
    automatically the plan to buy: Pro carries 3 TTS contexts and the evidence file's §A2
    arithmetic says that is not enough for ten lines at peak. A console that ranked plans by
    price alone would be recommending a dead-air incident.
    """

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    fee_inr: str
    included_credits: str
    #: Call-minutes the allotment covers at the ASSUMED worst-case speaking rate — a model
    #: figure, which is why the assumption travels beside it on `CartesiaVolumeOut`.
    included_call_minutes: str
    #: What ONE MORE call-minute costs on this plan once the allotment is gone, all-in.
    marginal_cost_inr_per_min: str
    tts_concurrency: int


class CartesiaLadderPointOut(BaseModel):
    """The Cartesia cost curve at one monthly volume: which plan is cheapest, and what a
    minute costs there. The table that makes "COSTS US" an answerable question."""

    model_config = ConfigDict(extra="forbid")

    call_minutes: str
    plan_id: str
    cost_inr_per_min: str


class CartesiaVolumeOut(BaseModel):
    """**THE VOLUME EVERY CARTESIA COST FIGURE ON THIS SCREEN IS STRUCK AT.**

    THE DEFECT THIS EXISTS FOR (founder, 9 Sep 2026). The console printed ₹4.3639 under a
    column headed "COSTS US" for every Studio rung. That figure was the $49 Startup plan fee
    spread over the 2,315 call-minutes at which its allotment is exactly consumed — the
    cheapest a Cartesia minute can ever be, at a volume this platform has never run — and
    nothing on the screen said so. The arithmetic was right and the SCREEN was lying.

    Cartesia is a monthly subscription with an included allotment and an overage past it
    (`billing/rates.CartesiaPlan`), so a per-minute cost is a function of volume and a
    screen that shows one without its volume is showing a guess. This block carries the
    measurement, the assumption, the plan set and the curve, so no figure on the page is
    unqualified.
    """

    model_config = ConfigDict(extra="forbid")

    #: The IST billing month the measurement covers, `YYYY-MM`.
    month: str
    #: Cartesia call-minutes the WHOLE PLATFORM spoke this month, read from the fleet
    #: counter the post-call meter moves (`billing/tts_volume.py`). `"0"` is a measurement
    #: (nobody has run a Studio call this month), not an absence.
    measured_call_minutes: str
    #: Characters those calls synthesized — an INDEPENDENT count of the same calls, so the
    #: measured cost below needs no speaking-rate assumption at all.
    measured_characters: str
    #: What a Cartesia minute ACTUALLY cost us this month, all-in, and the plan that price
    #: assumes. `null` when the month has no minutes to divide by — printing the whole
    #: subscription fee against a per-minute heading would mean neither thing.
    cost_inr_per_min: str | None
    plan_id: str | None
    #: The chars-per-call-minute the MODEL assumes wherever no measurement exists (the top
    #: of TRD §10.1's unmeasured 360-540 band — pilot gate 12). Published because every
    #: ladder row below is struck at it.
    assumed_chars_per_call_minute: str
    #: **THE USD→INR RATE EVERY RUPEE ON THIS BLOCK WAS STRUCK AT, AND WHERE IT CAME FROM.**
    #: The founder's decision of 9 Sep 2026: Cartesia bills in dollars, so a cost we pay in
    #: dollars moves with the rupee, and this deployment already pulls and publishes the
    #: rate every five minutes. `fx_source` is `"frankfurter:FBIL"`-shaped for a published
    #: quote and `"configured:usd_inr_rate"` when the feed is silent or its rate has aged
    #: past `core/fx.MAX_QUOTE_AGE` — the fallback is NAMED rather than hidden, because a
    #: floor quietly struck at an operator's typed number is the same "best case presented
    #: as fact" defect this whole block exists to remove. `fx_as_of` is the SOURCE's own
    #: publication date and is `null` exactly when the configured rate was used: a typed
    #: number has no publication date and inventing today's would make a stale fallback
    #: look fresh.
    fx_usd_inr: str
    fx_source: str
    fx_as_of: str | None
    #: The structural refusal threshold and the best any volume can reach at the LIVE rate,
    #: so a reader can see the band the curve moves inside.
    floor_inr_per_min: str
    best_marginal_cost_inr_per_min: str
    #: **THE FROZEN BOUND THE WRITE PATH ACTUALLY REFUSES BELOW** (`rates
    #: .CARTESIA_COST_FLOOR_INR_PER_MIN`, struck at the evidence file's ₹88), published
    #: beside the live one because the two differ and an operator must know which number
    #: blocks a save. A refusal that moved with a currency feed would make a card
    #: recordable today and refused tomorrow on an FX tick alone — at ₹95.66 the live floor
    #: is above the founder's own ₹6.00 rung — so the veto is frozen and the live figure is
    #: a warning. When `floor_inr_per_min` exceeds this, some rung may be under water at
    #: today's rate and still recordable, which is exactly the state the console must show.
    refusal_floor_inr_per_min: str
    #: The volume at which the dearer plan stops costing more — DERIVED by search
    #: (`rates.cartesia_plan_crossover_call_minutes`), never typed.
    plan_crossover_call_minutes: str
    plans: list[CartesiaPlanOut]
    ladder: list[CartesiaLadderPointOut]


class PendingCardOut(BaseModel):
    """A card that has been recorded and has NOT taken effect yet.

    `cells` is what will be in force on the day rather than the rows this card happens to
    carry — `list_rates.PendingCard` resolves it AT that instant, so carry-forward and the
    per-cell catalogue fallback are already applied and the operator reads the card the
    platform will actually price with.
    """

    model_config = ConfigDict(extra="forbid")

    effective_from: str
    cells: list[RateCardCellOut]


class RateCardOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: When the card in force was dated, or `null` where none ever was.
    effective_from: str | None
    #: The target the thin cells are thin AGAINST, as a percentage string ("20").
    target_gross_margin_pct: str
    cells: list[RateCardCellOut]
    #: Cards already recorded whose date has not arrived. Empty is the ordinary state.
    pending: list[PendingCardOut]
    #: The notice period, in days — the console renders it beside the date picker so an
    #: operator learns the rule before the refusal rather than from it.
    notice_days: int
    #: The soonest date this deployment would accept RIGHT NOW, as an ISO instant. Computed
    #: server-side from the same function that refuses (`list_rates.notice_refusal`), so the
    #: picker's floor and the write's floor cannot be two answers.
    earliest_effective_from: str
    #: **THE VOLUME EVERY CARTESIA COST FIGURE ABOVE IS STRUCK AT**, measured and modelled.
    #: Required, never optional: a console that could render this card with the volume block
    #: missing is a console that can print a best case as a fact again, which is the whole
    #: defect (`CartesiaVolumeOut`).
    cartesia_volume: CartesiaVolumeOut
    #: How many clients would be emailed if a card were recorded now — the prepaid book,
    #: counted with the fan-out's own predicate (`_NOTICE_RECIPIENTS`). Published on the
    #: READ rather than only echoed on the write because the number an operator needs is
    #: the one they read BEFORE pressing Record; `RateCardWriteOut.clients_notified` says
    #: only that the promise was written, which is a different fact.
    notice_recipients: int


def _pct(ratio: Decimal | None) -> str | None:
    """A margin RATIO as a percentage string, quantized once, here.

    Two decimals because that is what a percentage means to the person reading it, and
    quantized at the boundary rather than in the arithmetic — `gross_margin_ratio` is
    deliberately unquantized so that comparisons against the target are exact.
    """
    if ratio is None:
        return None
    return str((ratio * 100).quantize(Decimal("0.01"), rounding=ROUNDING))


@rate_card_router.get(
    "",
    response_model=RateCardOut,
    openapi_extra=permission_meta("platform:config"),
    summary="The credit-pack card in force: every rung, both voices, with the server's margin",
    description=(
        "Twelve cells — six pack rungs on each of the two voice qualities — each with the "
        "rate a client is sold, the per-minute cost that rate carries, the gross margin "
        "the server strikes between them, and two verdicts: below the margin TARGET (a "
        "warning; the approved card is deliberately thin on the cheaper voice) and below "
        "COST (a refusal; the card cannot be recorded at all). It also carries every card "
        "already recorded whose date has not arrived (`pending`), the notice period in "
        "days, the soonest date this deployment would accept right now, and how many "
        "clients a new card would be announced to. Writing one is `POST` on this same "
        "path; a card is written whole and takes effect on its own date."
    ),
)
async def read_rate_card(session: AdminSession, _: ConfigOperator) -> RateCardOut:
    """THE DIRECTORY SESSION, not the global one, and the swap is the whole of why this
    signature changed: `notice_recipients` counts `organizations`, which FORCEs RLS with a
    policy that matches on `app.tenant_id`, so an untenanted session answers 0 for every
    deployment. The rate rows this route also reads (`platform_list_rates`) carry no RLS
    at all, so one session serves both questions.

    ⚠ **THIS DOCSTRING USED TO END "and it has to be one, because `db/session.py` runs
    `max_overflow=0` and no request path may hold two", AND BOTH HALVES ARE WRONG.** D-182
    moved the overflow to **1**, and `scripts/check_session_nesting.py` enforces a ceiling
    of `max_overflow + 1` = **2**. This route still uses exactly ONE, and the reason is
    worth recording: the Cartesia fleet volume this read publishes was first built as a
    per-tenant WALK (the shape `fleet_spend` uses, holding the directory open across a
    second session per client) and that turned one rate-card read into one session checkout
    per account — 8,480 of them on this repository's own development database. It is a
    counter now (`billing/tts_volume`), which is one indexed row on the session already
    open."""
    now = datetime.now(UTC)
    # WHAT THE PLATFORM ACTUALLY SPOKE THIS MONTH, before anything is rendered. It is a
    # per-tenant walk (`billing/tts_volume`) because `usage_events` is FORCE RLS'd and this
    # session's `app.admin` widens `organizations` alone — the same shape and the same cost
    # the fleet spend board already pays, with the same over-budget warning. It runs on the
    # READ and not on the write for the reason `notice_recipients` does: the figure an
    # operator needs is the one they read BEFORE pressing Record.
    # ONE RATE FOR THE WHOLE RESPONSE, resolved here. `usd_inr_rate_now` is the ONE
    # spelling of "the published rate while it is fresh, else the operator's typed one"
    # (`core/fx.py`); `billing/number_rental.py` calls it the same way. Resolving it per
    # figure would let a five-minute tick land between two rows of one table.
    fx = usd_inr_rate_now(get_settings().usd_inr_rate)
    volume = await fleet_cartesia_volume(session, month=ist_billing_month(now))
    measured_cost = cartesia_measured_cost_inr_per_call_minute(
        characters=volume.characters, call_minutes=volume.call_minutes, usd_inr=fx.rate
    )
    dated = (
        await session.execute(text(_CARD_EFFECTIVE_FROM), {"prefix": f"{PACK_RATE_KEY_PREFIX}:%"})
    ).scalar()
    # THE CARD IN FORCE, RESOLVED FROM THE STORE — not `PACK_CATALOGUE`, which this route
    # rendered while the card was a committed constant and nothing could change it. Since
    # D-550 an operator can, so reading the constant would show a screen that disagrees with
    # what a purchase made in the same second would freeze onto its lot.
    in_force = card_with_rates(await card_at(session, at=now))
    scheduled = await pending_cards(session, at=now)
    recipients = int(
        (await session.execute(text(_NOTICE_RECIPIENTS), {"tiers": list(PREPAID_TIERS)})).scalar()
        or 0
    )
    return RateCardOut(
        effective_from=dated.isoformat() if dated is not None else None,
        target_gross_margin_pct=_pct(MIN_GROSS_MARGIN) or "0",
        cells=_cells_out(in_force, measured_cost=measured_cost, fx=fx),
        pending=[
            PendingCardOut(
                effective_from=card.effective_from.isoformat(),
                cells=_cells_out(card_with_rates(card.cells), measured_cost=measured_cost, fx=fx),
            )
            for card in scheduled
        ],
        cartesia_volume=_cartesia_volume_out(volume, fx=fx),
        notice_days=CARD_NOTICE_DAYS,
        earliest_effective_from=(now + timedelta(days=CARD_NOTICE_DAYS)).isoformat(),
        notice_recipients=recipients,
    )


def _volume_cost(voice: VoiceTier, measured: Decimal | None) -> Decimal | None:
    """What one minute of `voice` cost at this month's MEASURED Cartesia volume.

    Sarvam's cost is a per-character list price in RUPEES and moves with neither volume nor
    the dollar, so its at-volume cost IS its structural floor — the same number twice, which
    is the honest answer and not a gap. Cartesia's is the measurement at the live rate, or
    `None` when there was none.
    """
    if voice == "sarvam":
        return cost_floor_inr_per_min(voice)
    return measured


def _cells_out(
    card: tuple[CreditPack, ...], *, measured_cost: Decimal | None, fx: UsdInrRate
) -> list[RateCardCellOut]:
    """One card as twelve rendered cells, verdicts included — TWICE OVER since 9 Sep 2026.

    THE PREVIEW'S OWN OUTPUT, in the preview's own order (card order, then voice order):
    `_log_margins` logs these verdicts and `_refuse_bad_card` vetoes on the same ones, so
    every screen shows what the gate scored. Shared by the card in force and by each pending
    card, because an operator comparing "now" against "from the 12th" must be reading two
    renderings of one function.

    **EVERY CELL NOW CARRIES TWO VERDICTS AND THE SECOND IS THE HONEST ONE.** The first is
    struck against the STRUCTURAL floor (`card_margins`, unchanged, and still the only thing
    the write path refuses on — see `_refuse_bad_card`). The second is struck against what
    the minute cost at the volume the platform actually ran, which on a subscription-billed
    voice is a different and usually worse number. Both are the SERVER's, computed from
    `rates.rate_margin` and `rates.gross_margin_ratio` so a browser never divides one
    rounded rupee figure by another.

    Why the refusal stays on the structural figure and the volume-real one is a warning:
    at today's volume several Studio rungs are under water, so refusing on it would refuse
    the card that is currently live and no card could be recorded at all. That is the
    founder's own resolution of the tension between his two decisions of 9 Sep 2026 (the
    rate card does not change; the margin is judged at actual volume), recorded at D-556.
    """
    amounts = {pack.pack_id: pack.amount_inr for pack in card}
    cells: list[RateCardCellOut] = []
    for pack_id, voice, verdict in card_margins(card):
        at_volume_cost = _volume_cost(voice, measured_cost)
        at_volume = (
            None if at_volume_cost is None else rate_margin(verdict.rate, cost=at_volume_cost)
        )
        cells.append(
            RateCardCellOut(
                pack_id=pack_id,
                amount_inr=str(amounts[pack_id]),
                voice_tier=voice,
                tier_label=voice_tier_label(voice),
                inr_per_min=str(verdict.rate),
                cost_floor_inr_per_min=str(verdict.cost),
                gross_margin_pct=_pct(verdict.margin),
                below_target=verdict.below_target,
                below_floor=verdict.below_cost,
                breakeven_call_minutes=(
                    None
                    if voice != "cartesia"
                    else _opt_str(
                        cartesia_rung_breakeven_call_minutes(verdict.rate, usd_inr=fx.rate)
                    )
                ),
                cost_inr_per_min_at_volume=_opt_str(at_volume_cost),
                gross_margin_pct_at_volume=(None if at_volume is None else _pct(at_volume.margin)),
                below_target_at_volume=at_volume is not None and at_volume.below_target,
                below_floor_at_volume=at_volume is not None and at_volume.below_cost,
            )
        )
    return cells


def _opt_str(value: Decimal | None) -> str | None:
    """A Decimal as its exact string, or `None` — so an absence cannot render as `"0"`."""
    return None if value is None else str(value)


def _cartesia_volume_out(volume: CartesiaVolume, *, fx: UsdInrRate) -> CartesiaVolumeOut:
    """The measured month and the modelled curve, both struck at ONE named USD→INR rate.

    `fx` is resolved ONCE by the route and threaded through every figure here, rather than
    each function reaching for the quote itself: a block in which the ladder, the floor and
    the measurement could each have caught a different tick of a five-minute feed is a block
    whose rows do not add up, and "the numbers on one screen came from one rate" is the
    property that makes it readable at all. It is the same gesture `core/fx.fx_scope` makes
    for a unit of work.
    """
    measured = cartesia_measured_cost_inr_per_call_minute(
        characters=volume.characters, call_minutes=volume.call_minutes, usd_inr=fx.rate
    )
    plan = (
        None
        if volume.call_minutes <= 0
        else cartesia_cheapest_plan(volume.call_minutes, usd_inr=fx.rate).plan_id
    )
    return CartesiaVolumeOut(
        month=volume.month,
        measured_call_minutes=str(volume.call_minutes),
        measured_characters=str(volume.characters),
        cost_inr_per_min=_opt_str(measured),
        plan_id=plan,
        assumed_chars_per_call_minute=str(TTS_ASSUMED_CHARS_PER_CALL_MINUTE[1]),
        fx_usd_inr=str(fx.rate),
        fx_source=fx.source,
        fx_as_of=fx.as_of.isoformat() if fx.as_of is not None else None,
        floor_inr_per_min=str(cartesia_cost_floor_inr_per_min_at(fx.rate)),
        best_marginal_cost_inr_per_min=str(cartesia_best_marginal_cost_inr_per_min(fx.rate)),
        refusal_floor_inr_per_min=str(CARTESIA_COST_FLOOR_INR_PER_MIN),
        plan_crossover_call_minutes=str(cartesia_plan_crossover_call_minutes(usd_inr=fx.rate)),
        plans=[_cartesia_plan_out(plan_row, fx=fx) for plan_row in CARTESIA_PLANS],
        ladder=[
            CartesiaLadderPointOut(
                call_minutes=str(minutes),
                plan_id=cartesia_cheapest_plan(minutes, usd_inr=fx.rate).plan_id,
                cost_inr_per_min=str(cartesia_cost_inr_per_call_minute(minutes, usd_inr=fx.rate)),
            )
            for minutes in CARTESIA_VOLUME_LADDER_CALL_MINUTES
        ],
    )


def _cartesia_plan_out(plan: CartesiaPlan, *, fx: UsdInrRate) -> CartesiaPlanOut:
    """One plan, every figure derived from the vendor's three inputs and the live rate."""
    return CartesiaPlanOut(
        plan_id=plan.plan_id,
        fee_inr=str(plan.fee_inr(fx.rate)),
        included_credits=str(plan.included_credits),
        included_call_minutes=str(
            plan.included_call_minutes.quantize(Decimal("1"), rounding=ROUNDING)
        ),
        marginal_cost_inr_per_min=str(
            cartesia_plan_marginal_cost_inr_per_min(plan, usd_inr=fx.rate)
        ),
        tts_concurrency=plan.tts_concurrency,
    )


# --- the card, as a WRITER (D-550) --------------------------------------------------
#
# WHY AN EDITABLE CARD IS SAFE TO BUILD AT ALL, stated here because it is the property the
# whole surface rests on: Terms §6.1 promises that a later card change does not reprice
# credit a client already holds, and `credit_lots` makes that true BY CONSTRUCTION — a
# purchase freezes its two ₹/min figures onto the lot it opens (`billing/service.
# rate_card_at`, read once at the instant the money arrives) and every minute is debited
# against the lot it is spent from. A card recorded here can therefore only ever price a
# purchase made AFTER it takes effect. Nothing on this route can reach money already paid.


class RateCardCellIn(BaseModel):
    """One posted cell: a pack rung, a voice, and the ₹/min to sell that minute at.

    **MONEY ARRIVES AS AN EXACT DECIMAL STRING** (hard rule 7, which does not stop at the
    database). A JSON number is an IEEE double before Pydantic ever sees it, so `4.85`
    reaches the process as 4.8499999999999996447 and a rate card would be published from a
    value nobody typed. `mode="before"` is what makes that refusable — by the time the
    field is coerced the damage is done and both spellings look identical.
    """

    model_config = ConfigDict(extra="forbid")

    pack_id: str = Field(min_length=1, max_length=64)
    voice_tier: str = Field(min_length=1, max_length=32)
    inr_per_min: Decimal

    @field_validator("inr_per_min", mode="before")
    @classmethod
    def _exact_decimal_string(cls, value: object) -> Decimal:
        if not isinstance(value, str):
            raise ValueError(
                'a rate is sent as an exact decimal string ("4.85"), never as a JSON '
                "number — a JSON number is a binary float and cannot hold a rupee amount"
            )
        try:
            amount = Decimal(value)
        except InvalidOperation:
            raise ValueError(f"{value!r} is not a decimal amount") from None
        if not amount.is_finite() or amount <= 0:
            raise ValueError("a per-minute rate is a positive amount")
        if amount != amount.quantize(MONEY_Q, rounding=ROUNDING):
            raise ValueError(
                f"a rate is stored to {MONEY_Q} and {value!r} is finer than that; the "
                "database would round it silently, so it is refused here instead"
            )
        return amount


class RateCardIn(BaseModel):
    """A whole card and the date it starts. Twelve cells, exactly — no partial edits.

    **THE CARD IS POSTED WHOLE BECAUSE IT IS JUDGED WHOLE.** `credit_packs.card_refusals`
    scores a rate against its voice's cost floor AND against the rung either side of it
    (invariant 6: a bigger pack never buys a dearer minute), so a one-cell PATCH could only
    ever be validated against eleven cells read back from somewhere else — which is a
    read-then-write on money, and the shape BACKEND-PATTERNS §4 refuses. The console sends
    what it is showing.
    """

    model_config = ConfigDict(extra="forbid")

    #: When the card starts. Timezone-aware, and at least `CARD_NOTICE_DAYS` ahead.
    effective_from: datetime
    #: The operator's ground, required for `ConfigSetIn.reason`'s reason: it lands in the
    #: rate row's `source_note` (the live answer) AND in `audit_log` (the history).
    reason: str = Field(min_length=3, max_length=500)
    cells: list[RateCardCellIn] = Field(min_length=1, max_length=64)

    @field_validator("effective_from")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError(
                "send the date with an offset (2026-10-15T00:00:00+05:30) — a bare "
                "instant would be read in the server's timezone, not the one you typed"
            )
        return value

    @field_validator("reason")
    @classmethod
    def _not_whitespace_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a reason is required")
        return value


class RateCardWriteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The instant the card was dated at, echoed back as the server stored it.
    effective_from: str
    #: The card as recorded, with the server's own margin on every cell.
    cells: list[RateCardCellOut]
    #: Whether the promise to tell every affected client was written in the same
    #: transaction. False means the notice was already on the books for this date — a
    #: re-record of the same date cannot happen (the instant is a primary key), so in
    #: practice this is true on every success and is here so a console never has to guess.
    clients_notified: bool


class RateCardCancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: datetime
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("effective_from")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("send the date with an offset, as the rate-card read prints it")
        return value

    @field_validator("reason")
    @classmethod
    def _not_whitespace_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a reason is required")
        return value


class RateCardCancelOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: str
    #: True when this call withdrew the card; false when it was already withdrawn.
    cancelled: bool


def _posted_card(cells: list[RateCardCellIn]) -> tuple[CreditPack, ...]:
    """Twelve posted cells as a priced pack ladder, or a 422 naming exactly what is wrong.

    FOUR WAYS A CARD CAN BE MALFORMED and each gets its own sentence, because "invalid
    card" is the error message an operator cannot act on: an unknown rung, an unknown
    voice, the same cell twice, and a cell that is simply missing. The last one is the one
    a console loses to a rendering bug and the one a silent default would hide — a missing
    cell would fall back to the catalogue rate through `card_with_rates` and publish a
    price nobody typed.
    """
    wanted = {(pack.pack_id, voice) for pack in PACK_CATALOGUE for voice in VOICE_TIERS}
    seen: dict[tuple[str, VoiceTier], Decimal] = {}
    problems: list[str] = []
    for cell in cells:
        key = (cell.pack_id, cell.voice_tier)
        if key not in wanted:
            problems.append(
                f"{cell.pack_id!r}/{cell.voice_tier!r} is not a cell on this card — the "
                f"rungs are {', '.join(sorted(pack.pack_id for pack in PACK_CATALOGUE))} "
                f"and the voices are {', '.join(VOICE_TIERS)}"
            )
            continue
        # The narrowing mypy cannot do from a `str` field: membership in `wanted` proves
        # the voice is a `VoiceTier`, and the tuple is rebuilt from the pack id and the
        # matching literal rather than cast, so no unreachable arm is introduced.
        voice = next(tier for tier in VOICE_TIERS if tier == cell.voice_tier)
        if (cell.pack_id, voice) in seen:
            problems.append(f"{cell.pack_id!r}/{voice} was sent twice with no way to choose")
            continue
        seen[(cell.pack_id, voice)] = cell.inr_per_min
    missing = sorted(f"{pack_id}/{voice}" for pack_id, voice in wanted - set(seen))
    if missing:
        problems.append(
            "the card is incomplete — every rung is priced on both voices or none is, and "
            f"these are missing: {', '.join(missing)}"
        )
    if problems:
        raise ProblemError(
            kind="validation",
            code="rate_card_malformed",
            title="This is not a whole rate card",
            detail="; ".join(problems),
            remediation=(
                "Send every pack rung once on each voice. A card is judged as a ladder, so "
                "it cannot be written one cell at a time."
            ),
        )
    return card_with_rates(
        {
            pack.pack_id: {voice: seen[(pack.pack_id, voice)] for voice in VOICE_TIERS}
            for pack in PACK_CATALOGUE
        }
    )


@rate_card_router.post(
    "",
    response_model=RateCardWriteOut,
    status_code=201,
    openapi_extra=permission_meta("platform:config"),
    summary="Record a future rate card (step-up confirmed, audited, clients notified)",
    description=(
        "Publishes a whole twelve-cell card — six pack rungs on each of the two voice "
        "qualities — to take effect on a date at least 30 days out. Requires "
        "`X-Confirm-Action: record_rate_card:<effective_from>`. Rates are exact decimal "
        "strings, never JSON numbers. The write is refused if the date is sooner than the "
        "notice period (a price CUT included), if any cell is below its voice's per-minute "
        "cost floor, if a bigger pack would buy a dearer minute, if a cell is missing or "
        "sent twice, or if a card is already scheduled at that instant. Nothing changes "
        "until the date: credit already bought keeps the rates it was bought at, because "
        "every purchase freezes its rates onto its own lot."
    ),
)
async def record_rate_card(
    payload: RateCardIn,
    session: GlobalSession,
    request: Request,
    principal: ConfigOperator,
    # Resolved BEFORE this handler body runs, so the session read cannot happen inside an
    # open transaction — `core/stepup.py` on `max_overflow=0`.
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> RateCardWriteOut:
    """The card, its refusals, its audit row and the promise to tell the clients — one
    transaction (BACKEND-PATTERNS §4). A rolled-back card cannot leave a notice behind, and
    a committed one cannot lose it.

    NO `If-Match`. The three config routes are conditional because they OVERWRITE one row
    and a losing write would be invisible; this appends a card at an instant that is its own
    primary key, so two operators saving at once produce two dated cards or one refusal,
    never a silent last-write-wins. `card_is_scheduled` is what turns the second one into a
    sentence instead of an integrity error rendered as a 500.
    """
    step_up.require(x_confirm_action, rate_card_confirmation(payload.effective_from))
    if principal.user_id is None:
        raise ProblemError(
            kind="auth",
            code="config_actor_unknown",
            title="This session has no admin identity",
            detail="A rate card has to be attributable to an operator.",
        )
    refusal = notice_refusal(payload.effective_from, now=datetime.now(UTC))
    if refusal is not None:
        raise ProblemError(
            kind="validation",
            code="rate_card_too_soon",
            title="This card starts too soon",
            detail=refusal,
            remediation=(
                "Pick a later date. The rate-card read publishes the earliest one this "
                "deployment will accept, as `earliest_effective_from`."
            ),
        )
    card = _posted_card(payload.cells)
    _refuse_bad_card(card)
    if await card_is_scheduled(session, effective_from=payload.effective_from):
        raise ProblemError(
            kind="conflict",
            code="rate_card_already_scheduled",
            title="A card already starts at that instant",
            detail=(
                f"A rate card is already recorded for {payload.effective_from.isoformat()}, "
                "and rate history is append-only — it cannot be overwritten."
            ),
            remediation=(
                "Withdraw the scheduled card first (it has not taken effect, so nothing has "
                "been priced at it), then record this one; or choose a different instant."
            ),
        )
    _log_margins(card)
    at = await record_card(
        session,
        card=card,
        effective_from=payload.effective_from,
        # THE LEGACY KEY FOLLOWS THE CARD, not the `self_serve_inr_per_min` setting. "The
        # list rate" has meant the entry rung's Sarvam rate since D-547 — it is what the
        # marketing site leads with — so a card that moves that cell moves it, and
        # `self_serve_rate_at` keeps answering a rate this card actually sold.
        self_serve_inr_per_min=card_list_rate(card),
        recorded_by=principal.user_id,
        note=payload.reason,
    )
    await write_audit(
        session,
        action="platform.rate_card_recorded",
        actor=principal,
        object_type="platform_list_rates",
        object_id=at.isoformat(),
        ip=client_request_ip(request),
        summary={
            "effective_from": at.isoformat(),
            "reason": payload.reason,
            # Money as strings, hard rule 7, in the order the guard scores them.
            "cells": {
                f"{pack.pack_id}:{voice}": str(pack.inr_per_min(voice))
                for pack in card
                for voice in VOICE_TIERS
            },
        },
    )
    notified = await enqueue_outbox_once(
        session,
        job=RATE_CARD_NOTICE_JOB,
        payload={"effective_from": at.isoformat()},
        # ONE FAN-OUT PER DATE, EVER. The outbox is at-least-once and this promise reaches
        # every client with a wallet; a duplicate here is a second "your rates are changing"
        # email to the whole book, which is the one duplicate this product cannot shrug off
        # the way `wallet_alerts` shrugs off a repeated low-balance warning.
        dedupe_key=f"rate-card-notice:{at.isoformat()}",
    )
    return RateCardWriteOut(
        effective_from=at.isoformat(),
        # NO VOLUME WALK ON THE WRITE, and the at-volume verdicts are therefore absent
        # rather than wrong. This is an echo of what was just recorded; the panel re-reads
        # the card immediately afterwards and that read carries the measurement. Paying for
        # a fleet walk inside a write that already holds a step-up confirmation would put a
        # per-tenant loop between an operator and their save for a number the next request
        # brings anyway.
        cells=_cells_out(
            card, measured_cost=None, fx=usd_inr_rate_now(get_settings().usd_inr_rate)
        ),
        clients_notified=notified is not None,
    )


@rate_card_router.post(
    "/cancellations",
    response_model=RateCardCancelOut,
    openapi_extra=permission_meta("platform:config"),
    summary="Withdraw a scheduled rate card before it takes effect (step-up confirmed)",
    description=(
        "Records that a card recorded earlier will never take effect. Requires "
        "`X-Confirm-Action: cancel_rate_card:<effective_from>`. It is a POST and not a "
        "DELETE because nothing is deleted: rate history is append-only, so the withdrawal "
        "is its own row and both facts — what was scheduled, and that it was withdrawn — "
        "stay readable. Only a card whose date is still in the future may be withdrawn; "
        "one already in force has priced purchases, and unwinding it would restate lots "
        "that are already frozen."
    ),
)
async def cancel_rate_card(
    payload: RateCardCancelIn,
    session: GlobalSession,
    request: Request,
    principal: ConfigOperator,
    step_up: StepUpGate,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> RateCardCancelOut:
    """The compensating entry hard rule 4 asks for, with its audit row in one transaction."""
    step_up.require(x_confirm_action, rate_card_cancel_confirmation(payload.effective_from))
    if principal.user_id is None:
        raise ProblemError(
            kind="auth",
            code="config_actor_unknown",
            title="This session has no admin identity",
            detail="Withdrawing a rate card has to be attributable to an operator.",
        )
    if not await card_is_scheduled(session, effective_from=payload.effective_from):
        raise ProblemError(
            kind="not_found",
            code="rate_card_not_scheduled",
            title="No card starts at that instant",
            detail=(
                f"Nothing was recorded for {payload.effective_from.isoformat()}, so there "
                "is nothing to withdraw."
            ),
            remediation=(
                "The rate-card read lists every scheduled card under `pending`, with the "
                "exact instant to send back."
            ),
        )
    if payload.effective_from <= datetime.now(UTC):
        raise ProblemError(
            kind="conflict",
            code="rate_card_already_in_force",
            title="That card has already taken effect",
            detail=(
                "A card can only be withdrawn before its date. This one has started, so "
                "purchases have been priced at it and their credit is frozen at those "
                "rates — withdrawing it now would restate money clients have already spent."
            ),
            remediation=(
                f"Record a NEW card with the rates you want, at least {CARD_NOTICE_DAYS} days out."
            ),
        )
    withdrawn = await cancel_card(
        session,
        effective_from=payload.effective_from,
        cancelled_by=principal.user_id,
        reason=payload.reason,
    )
    if withdrawn:
        # NO AUDIT ROW FOR A NO-OP, for `set_config`'s reason: a double-clicked Withdraw
        # must not enter a hash-chained ledger twice as two acts.
        await write_audit(
            session,
            action="platform.rate_card_cancelled",
            actor=principal,
            object_type="platform_list_rates",
            object_id=payload.effective_from.isoformat(),
            ip=client_request_ip(request),
            summary={
                "effective_from": payload.effective_from.isoformat(),
                "reason": payload.reason,
            },
        )
    return RateCardCancelOut(effective_from=payload.effective_from.isoformat(), cancelled=withdrawn)


__all__ = [
    "RATE_CARD_NOTICE_JOB",
    "config_confirmation",
    "rate_card_cancel_confirmation",
    "rate_card_confirmation",
    "rate_card_router",
    "require_if_match",
    "revert_confirmation",
    "router",
]
