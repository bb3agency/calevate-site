"""Editing the extraction VARIABLES an agent captures — the client's own field list.

WHAT CHANGED, AND THE DECISION BEHIND IT (D-460, superseding D-21's admin-only clause)
--------------------------------------------------------------------------------------
The per-agent extraction schema — the list of variables the AI fills in after a call, which
IS the Leads column list (`crm/columns.py`) — used to be written exactly once, at account
creation, from a hard-coded vertical template, with no edit path in either realm. D-21 kept
it admin-only on a managed-service argument. D-460 opens it: a client OWNER edits their own
agents' variables, and an operator edits any tenant's, because a business knows what it
needs to capture better than a template does, and each variable now carries an optional
`reason` the model reads.

WHY THIS ROUTER HAS NO PREFIX, and why there are two of them: the resource lives in two
spaces — the client realm's `/v1/agents/{agent_id}/extraction-schema` and the admin realm's
`/v1/admin/tenants/{tenant_id}/agents/{agent_id}/extraction-schema` — so one prefix could
describe only one. Same resolution as `llm_routes.py` and `prompt_routes.py`, which pair a
client router with an admin one for the identical reason. Both call one reader and one
writer; what differs is who is admitted and whose tenant is named (a `Depends` + a path
parameter), not a second implementation.

WHY A WHOLE-LIST PUT, NOT PER-FIELD POST/PATCH/DELETE. The field list is one ordered value
(order is the display order AND the prompt order), so add / edit / delete are all "here is
the new list". One write path is one place for the validation, the collision guard and the
versioning to live — per-field verbs would be four places for those to drift, and a
half-applied multi-field edit would be a schema nobody chose.

WHY A NEW VERSION RATHER THAN AN IN-PLACE UPDATE. `extraction_schemas` is versioned on
purpose (`models.py`): historical leads render by the version active when they were
extracted, and `leads.data` is keyed by `field.key`. So a save INSERTs a new version row and
repoints the agent at it; old versions stay for old leads. It is NOT append-only (edits are
allowed), but the versioning contract is what keeps a rename from rewriting history.

NO ENGINE REPUBLISH. Extraction is POST-CALL only (`apps/workers/extraction.py`), so the
schema never rides the voice-engine agent config. A save takes effect on the NEXT call's
extraction pass with nothing to push — which is why "live on save" (D-460) needs no
draft/publish gate the way a prompt change does.
"""

from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from calevate_shared.extraction import ExtractionField, ExtractionSchemaSpec
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.crm.columns import FIXED_KEYS
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session

router = APIRouter(tags=["agents"])

Session = Annotated[AsyncSession, Depends(db)]

# The owner's permission on the client side (the same gate the account model picker and the
# per-agent model edit use — this decides what every call on the agent captures, an owner's
# call); the operator's on the admin side.
Owner = Annotated[Principal, Depends(requires("org:manage"))]
Operator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]


#: THE CEILINGS THIS SURFACE HAD NONE OF, and the reason they are needed NOW rather than
#: when the list was hand-written. D-460 turned this from an operator-only surface into one
#: a client OWNER writes, which moves `fields` into the class `scripts/check_list_bounds`
#: calls caller-controlled — "rows a tenant can mint" — and off the "bounded by nature"
#: shelf its registry entry used to put it on. Nothing here was refusing a PUT of fifty
#: thousand variables, or one variable whose `reason` is a megabyte of prose.
#:
#: THE COST IS NOT THE ROW, IT IS EVERY CALL AFTERWARDS. Each variable and its `reason` are
#: folded verbatim into the extraction prompt and the JSON schema the model is given
#: (`workers/extraction.py`), so an oversized list is paid for on EVERY post-call
#: extraction that agent ever runs — in tokens, in latency, and eventually in an extraction
#: that fails outright because the prompt no longer fits. It also becomes a Leads table with
#: fifty thousand columns (`crm/columns.available`), a CSV header to match, and a
#: projection the retrieval store embeds field by field (`crm/lead_projection.py`).
#:
#: The numbers are generous against the real thing: the largest vertical template in
#: `scripts/seed.py::VERTICAL_TEMPLATES` is 7 variables with reasons under 200 characters.
#: They are ceilings on a mistake, not a product limit anyone will meet.
MAX_EXTRACTION_FIELDS = 50
MAX_LABEL_LEN = 80
MAX_REASON_LEN = 500
MAX_ENUM_VALUES = 50
MAX_ENUM_VALUE_LEN = 80


class ExtractionSchemaIn(BaseModel):
    """The whole new ordered field list. `extra="forbid"` on every field
    (`ExtractionField`), so an unknown key on a variable is a 422 rather than a silently
    dropped edit.

    `max_length` HERE and not on `ExtractionField`/`ExtractionSchemaSpec`, deliberately.
    Those two models also parse what is ALREADY STORED (`_read_current`, `crm.service.
    lead_columns`, `crm/lead_chunks._fields_for`), and a ceiling added to a read model is a
    ceiling that turns every row written before it existed into a 500 on the client's own
    Leads screen. A bound belongs on the write, where the person who can act on it is
    holding the form.
    """

    model_config = ConfigDict(extra="forbid")

    fields: list[ExtractionField] = Field(max_length=MAX_EXTRACTION_FIELDS)


class ExtractionSchemaOut(BaseModel):
    """The stored list after the write, and the version it became.

    `changed` is here for the same reason `llm-defaults` carries it: a PUT is idempotent, so
    re-sending the list already on file is a request somebody made and a change nobody made,
    and the screen (and an auditor) needs to tell "saved, new version" from "nothing moved".
    """

    model_config = ConfigDict(extra="forbid")

    fields: list[ExtractionField]
    version: int
    changed: bool


def _validate_fields(fields: list[ExtractionField]) -> None:
    """The two rules `ExtractionField`'s own validators cannot state, in words a client can
    act on rather than a generic 422.

    Unique keys and enum-needs-values are enforced by `ExtractionSchemaSpec`/`ExtractionField`
    already; this adds the collision guard the STORE needs: a variable whose key is one of the
    fixed Leads columns (`name`, `phone`, `status`, ...) would be SILENTLY DROPPED by
    `crm/columns.available` (a fixed column always wins), so the client would save a variable
    that never appears. Refuse it up front and name it, rather than let it vanish.
    """
    # Runs `ExtractionSchemaSpec._unique_keys` and each field's `_enum_needs_values`; a
    # ValueError becomes a 422 the form can show against the offending input.
    try:
        ExtractionSchemaSpec(version=1, fields=fields)
    except ValueError as exc:
        raise ProblemError(
            kind="validation",
            code="extraction_schema_invalid",
            title="That variable list can't be saved",
            # Not `str(exc)`: pydantic v2 embeds `input_value=…` (the submitted variable
            # definitions). A generic detail plus the field marker is what the form needs.
            detail="One or more variables are invalid.",
            fields=[{"name": "fields", "reason": "invalid variable list"}],
        ) from exc

    # The per-VARIABLE sizes, which `max_length` on the list above cannot state. Each one
    # names the offending variable by key, because "a label is too long" against a form of
    # fifty rows is not something anybody can act on.
    for field in fields:
        if len(field.label) > MAX_LABEL_LEN:
            raise ProblemError(
                kind="validation",
                code="extraction_field_label_too_long",
                title="A variable's name is too long",
                detail=(
                    f"'{field.key}' has a name of {len(field.label)} characters; the "
                    f"limit is {MAX_LABEL_LEN}. It is a column header on the Leads table."
                ),
                fields=[{"name": "fields", "reason": f"label too long: {field.key}"}],
            )
        if len(field.reason) > MAX_REASON_LEN:
            raise ProblemError(
                kind="validation",
                code="extraction_field_reason_too_long",
                title="A variable's reason is too long",
                detail=(
                    f"'{field.key}' has a reason of {len(field.reason)} characters; the "
                    f"limit is {MAX_REASON_LEN}. The AI reads this on every single call, "
                    "so a short, specific sentence works better than a long one."
                ),
                fields=[{"name": "fields", "reason": f"reason too long: {field.key}"}],
            )
        values = field.enum_values or []
        if len(values) > MAX_ENUM_VALUES or any(len(v) > MAX_ENUM_VALUE_LEN for v in values):
            raise ProblemError(
                kind="validation",
                code="extraction_field_choices_invalid",
                title="A variable has too many choices",
                detail=(
                    f"'{field.key}' may have at most {MAX_ENUM_VALUES} choices of "
                    f"{MAX_ENUM_VALUE_LEN} characters each."
                ),
                fields=[{"name": "fields", "reason": f"choices too large: {field.key}"}],
            )

    reserved = sorted({f.key for f in fields} & FIXED_KEYS)
    if reserved:
        names = ", ".join(reserved)
        raise ProblemError(
            kind="validation",
            code="extraction_field_reserved_key",
            title="A variable is using a reserved name",
            detail=(
                f"{names} is already a built-in column on every lead, so a variable with "
                "that name would never show. Rename the variable to something else."
            ),
            fields=[{"name": "fields", "reason": f"reserved key: {names}"}],
        )


#: The agent row, LOCKED, so the "did this actually change?" read and the write that depends
#: on it are one atomic step — the same instrument `llm_routes._write_default` and
#: `lifecycle.update_agent` use, and for the same reason: two owners saving at once would
#: each read the old list, each conclude they changed it, and each insert a version.
#: RLS scopes the row to this session's tenant (`agents` policy), so no `WHERE tenant_id`.
_AGENT_FOR_UPDATE = (
    "SELECT tenant_id, extraction_schema_id FROM agents "
    "WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"
)


async def _read_current(
    session: AsyncSession, schema_id: UUID | None
) -> tuple[int, list[dict[str, object]]]:
    """The version and fields currently on the agent, or `(0, [])` when it has no schema yet
    (an agent created without one — the passthrough case)."""
    if schema_id is None:
        return 0, []
    # `.one()`, not `.first()` with a None guard: `agents.extraction_schema_id` is a FK
    # (RESTRICT on delete) and nothing in this tree deletes an `extraction_schemas` row, so a
    # non-null id ALWAYS resolves. A defensive `if row is None` here would be a branch no
    # test could reach — the FK forbids the state — so it is not written; a genuinely
    # impossible miss surfaces loudly rather than as a silently empty schema.
    row = (
        await session.execute(
            text("SELECT version, fields FROM extraction_schemas WHERE id = :sid"),
            {"sid": schema_id},
        )
    ).one()
    return int(row[0]), list(row[1] or [])


async def _write_schema(
    session: AsyncSession, *, agent_id: UUID, fields: list[ExtractionField]
) -> ExtractionSchemaOut:
    """Insert a new schema version and point the agent at it — or do nothing if the list is
    unchanged. The caller has already validated `fields`.

    NO ROW TO LOCK IS A 404, not a silent success: under RLS an agent that is not this
    session's tenant's is indistinguishable from one that does not exist, and answering 200
    for a write that stored nothing is how a screen reports a save it never made.
    """
    agent = (await session.execute(text(_AGENT_FOR_UPDATE), {"aid": str(agent_id)})).first()
    if agent is None:
        raise ProblemError.not_found("Agent")
    tenant_id: UUID = agent[0]
    current_schema_id: UUID | None = agent[1]

    current_version, current_fields = await _read_current(session, current_schema_id)
    desired = [f.model_dump() for f in fields]
    if desired == current_fields:
        # Re-asserting the list already on file touches nothing — a PUT states the whole
        # resource, so a repeat is idempotent by construction and must not spend a version.
        return ExtractionSchemaOut(fields=fields, version=current_version, changed=False)

    # `MAX(version)+1` over the agent's own rows, not `current_version + 1`: it is the value
    # the UNIQUE(agent_id, version) constraint will accept even if a prior version row was
    # ever left behind, and the `FOR UPDATE` above serialises concurrent savers onto it.
    next_version = int(
        (
            await session.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM extraction_schemas "
                    "WHERE agent_id = :aid"
                ),
                {"aid": str(agent_id)},
            )
        ).scalar_one()
    )
    schema_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO extraction_schemas "
            "(id, tenant_id, agent_id, version, fields, created_at, updated_at) "
            "VALUES (:id, :tid, :aid, :ver, CAST(:fields AS jsonb), now(), now())"
        ),
        {
            "id": schema_id,
            "tid": tenant_id,
            "aid": str(agent_id),
            "ver": next_version,
            "fields": json.dumps(desired),
        },
    )
    await session.execute(
        text("UPDATE agents SET extraction_schema_id = :sid, updated_at = now() WHERE id = :aid"),
        {"sid": schema_id, "aid": str(agent_id)},
    )
    return ExtractionSchemaOut(fields=fields, version=next_version, changed=True)


def _audit_summary(result: ExtractionSchemaOut) -> dict[str, object]:
    """WHAT to record, and — as much — what NOT to. The variable KEYS, LABELS, reasons and
    types are tenant CONFIG (safe to log); a caller's extracted VALUES are PII and never
    touch this path (hard rule 6). So the summary is the shape of the schema, never a value:
    an auditor reconstructing "who changed what the agent captures" needs the field list and
    the version, and nothing a caller said.
    """
    return {
        "version": result.version,
        "changed": result.changed,
        "field_keys": [f.key for f in result.fields],
    }


_DESCRIPTION = (
    "The variables this agent captures from a call and writes into its leads — the Leads "
    "column list. Send the WHOLE ordered list; it replaces what was there. Each variable "
    "has a key (stored id), a label (shown), a type (text, number, bool, enum, date), "
    "whether it is required, enum values when the type is enum, and an OPTIONAL `reason` — "
    "why the variable is needed, which the AI reads to fill it more accurately. Leave the "
    "reason blank to have the AI work from the name alone.\n\n"
    "Saving creates a new schema version used on the NEXT call's extraction; calls already "
    "recorded keep the variables they were extracted with. A variable whose key is a "
    "built-in lead column, or a duplicate key, is refused. Renaming or removing a "
    "variable's key stops older leads from showing that column (their values are kept).\n\n"
    f"At most {MAX_EXTRACTION_FIELDS} variables, each with a name of "
    f"{MAX_LABEL_LEN} characters or fewer, a reason of {MAX_REASON_LEN} or fewer, and at "
    f"most {MAX_ENUM_VALUES} choices."
)


@router.get(
    "/v1/agents/{agent_id}/extraction-schema",
    response_model=ExtractionSchemaOut,
    openapi_extra=permission_meta("org:read"),
    summary="The variables this agent captures",
    description=_DESCRIPTION,
)
async def get_extraction_schema(
    agent_id: UUID,
    session: Session,
    _: Annotated[Principal, Depends(requires("org:read"))],
) -> ExtractionSchemaOut:
    """A read of the current list, for the editor to load. `changed` is always False on a
    read. RLS scopes the agent to the caller's tenant; a wrong id is 404, not a neighbour's
    schema."""
    agent = (
        await session.execute(
            text("SELECT extraction_schema_id FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": str(agent_id)},
        )
    ).first()
    if agent is None:
        raise ProblemError.not_found("Agent")
    version, current = await _read_current(session, agent[0])
    return ExtractionSchemaOut(
        fields=[ExtractionField.model_validate(f) for f in current],
        version=version,
        changed=False,
    )


@router.put(
    "/v1/agents/{agent_id}/extraction-schema",
    response_model=ExtractionSchemaOut,
    # `org:manage` — the OWNER's permission. Editing what every call captures is an owner's
    # decision, the same class as choosing the account's language model, not a staff read.
    openapi_extra=permission_meta("org:manage"),
    summary="Set the variables this agent captures",
    description=_DESCRIPTION,
)
async def set_extraction_schema(
    agent_id: UUID,
    payload: ExtractionSchemaIn,
    session: Session,
    request: Request,
    principal: Owner,
) -> ExtractionSchemaOut:
    assert principal.tenant_id is not None  # client realm; `requires()` resolves it
    _validate_fields(payload.fields)
    result = await _write_schema(session, agent_id=agent_id, fields=payload.fields)
    await write_audit(
        session,
        action="agent.extraction_schema_set",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="agent",
        object_id=str(agent_id),
        ip=client_request_ip(request),
        summary=_audit_summary(result),
    )
    return result


admin_router = APIRouter(prefix="/v1/admin", tags=["admin"])


@admin_router.put(
    "/tenants/{tenant_id}/agents/{agent_id}/extraction-schema",
    response_model=ExtractionSchemaOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Set the variables one client's agent captures",
    description=_DESCRIPTION,
)
async def admin_set_extraction_schema(
    tenant_id: UUID,
    agent_id: UUID,
    payload: ExtractionSchemaIn,
    request: Request,
    principal: Operator,
) -> ExtractionSchemaOut:
    """THE TENANT IS NAMED IN THE PATH AND ENTERED EXPLICITLY, never inferred from a session
    — the same resolution `agents/prompt_routes.py` and `llm_routes.py` record: an admin
    principal carries no tenant of its own, and impersonation is READ-ONLY (D-22), so a route
    that inferred the tenant would be un-callable for a mutation."""
    _validate_fields(payload.fields)
    async with tenant_session(tenant_id) as scoped:
        result = await _write_schema(scoped, agent_id=agent_id, fields=payload.fields)
        await write_audit(
            scoped,
            action="admin.agent_extraction_schema_set",
            actor=principal,
            tenant_id=tenant_id,
            object_type="agent",
            object_id=str(agent_id),
            ip=client_request_ip(request),
            summary=_audit_summary(result),
        )
        return result
