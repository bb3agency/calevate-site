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
client is charged. `usd_inr_rate` is stamped into `usage_events.meta` and is how a
billed minute is re-derived a year later (hard rule 7). A stolen admin session that
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

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import global_db
from apps.api.core.errors import ProblemError
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
    BOOTSTRAP_REASONS,
    effective_env,
    env_declares,
    env_var_for,
    get_settings,
)
from apps.api.core.stepup import require_step_up
from apps.api.ops.config_service import (
    WriteResult,
    clear_value,
    propagate,
    read_rows,
    read_sentinel,
    set_value,
)

router = APIRouter(prefix="/v1/ops/config", tags=["ops"])

GlobalSession = Annotated[AsyncSession, Depends(global_db)]
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
        detail=f"{key!r} was written but is not in the managed set.",
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
            for key, reason in sorted(BOOTSTRAP_REASONS.items())
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
    x_confirm_action: Annotated[str | None, Header()] = None,
    if_match: Annotated[str | None, Header()] = None,
) -> ConfigWriteOut:
    """Bound to the key, audited in the same transaction, propagated after it commits."""
    require_step_up(x_confirm_action, config_confirmation(key))
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
    x_confirm_action: Annotated[str | None, Header()] = None,
    if_match: Annotated[str | None, Header()] = None,
) -> ConfigWriteOut:
    """Reverting a key that was never overridden is a 404, not a cheerful success.

    The row is what would be removed, and there is none. Answering 200 would put a
    `platform.config_reverted` entry in a tamper-evident ledger for a change nobody made
    — the same objection `platform_confirmation` raises against the empty transition.
    """
    require_step_up(x_confirm_action, revert_confirmation(key))
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
                "The value in force comes from the environment or from the code "
                "default; GET /v1/ops/config reports which."
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
        ip=request.client.host if request.client else None,
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


def _projected_field(result: WriteResult) -> ConfigFieldOut:
    """This key as it will stand once the caller's transaction commits.

    The provenance (`updated_by`, `updated_at`, `note`) is deliberately NOT re-read from
    the row here — it would be the caller's own uncommitted write, and the console
    re-fetches the list anyway. What matters in this response is the value and the
    SOURCE, because `source` is the one thing a write changes in a way the form cannot
    predict: a value equal to the code default still reports `db` afterwards, since a row
    now exists and reverting it has become a distinct act.
    """
    overrides = dict(snapshot().overrides)
    if result.new is None:
        overrides.pop(result.key, None)
    else:
        overrides[result.key] = typed_value(result.key, result.new)
    settings, projected = project(overrides)
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
        detail=f"{result.key!r} was written but is not in the managed set.",
    )


__all__ = ["config_confirmation", "require_if_match", "revert_confirmation", "router"]
