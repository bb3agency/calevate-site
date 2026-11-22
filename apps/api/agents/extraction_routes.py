"""An agent's own lead-details list (`extraction_schemas`): read-only since D-1029, and the
extraction rules every "What it notes" list is held to.

D-1028 (founder, 22 Nov 2026): what a call notes belongs to its job. A campaign or an inbound
line keeps its own list (`campaigns/notes.py`); a new one starts from the business's starting
set (`lead_fields.starting_business_fields`), never from this list. D-1029 removed the client
and operator PUTs: nothing a person edits writes it any more. What stays here:

* `_validate_fields`, the rules a list must meet to be saved (unique keys, choices for a
  choice detail, no reserved key, the size ceilings below), which `campaigns/notes.save_notes`
  applies to every job's list;
* the GET, a read of an agent's list for API clients that still ask;
* `write_schema`, the versioned write the platform's own seeding still uses for a new agent
  (`starters`) and for a reworded template field (`refresh_field_reason`).

`extraction_schemas` and `agents.extraction_schema_id` are dropped in a later release (hard
rule 8). The versioned shape: a write INSERTs a new version row and repoints the agent, so
leads extracted under an older version render by it; a changed list also queues
`rebuild_collect` (D-889), which recompiles the agent's own script in a worker.
"""

from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from calevate_shared.extraction import ExtractionField, ExtractionSchemaSpec
from calevate_shared.lead_fields import OUTPUT_KEYS, business_only, core_fields
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.field_suggestions import queue_collect_rebuild
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.crm.columns import FIXED_KEYS
from apps.api.db.base import uuid7
from apps.api.tenancy.core_labels import core_labels

router = APIRouter(tags=["agents"])

Session = Annotated[AsyncSession, Depends(db)]


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
#: `calevate_shared/verticals.json` is 7 variables with reasons under 200 characters.
#: They are ceilings on a mistake, not a product limit anyone will meet.
MAX_EXTRACTION_FIELDS = 50
MAX_LABEL_LEN = 80
MAX_REASON_LEN = 500
MAX_ENUM_VALUES = 50
MAX_ENUM_VALUE_LEN = 80


class ExtractionSchemaOut(BaseModel):
    """The stored list after the write, and the version it became.

    `changed` is here for the same reason `llm-defaults` carries it: a PUT is idempotent, so
    re-sending the list already on file is a request somebody made and a change nobody made,
    and the screen (and an auditor) needs to tell "saved, new version" from "nothing moved".
    """

    model_config = ConfigDict(extra="forbid")

    #: This agent's own (business) fields, in order. The fixed core is NOT among them.
    fields: list[ExtractionField]
    #: The details every agent captures whatever the business (`calevate_shared.
    #: lead_fields`). Read-only: a field sent under one of these keys is ignored.
    core_fields: list[ExtractionField]
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

    The fixed core is not the client's to send: a field under a core key is dropped before
    any rule runs, so a list read back with the core still saves.
    """
    fields = business_only(fields)
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
            detail="Some of these variables need a fix before they can be saved.",
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

    reserved = sorted({f.key for f in fields} & (FIXED_KEYS | OUTPUT_KEYS))
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
    session: AsyncSession,
    *,
    agent_id: UUID,
    fields: list[ExtractionField],
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

    # Only business fields are stored; the core is composed in on read.
    fields = business_only(fields)
    current_version, current_fields = await _read_current(session, current_schema_id)
    desired = [f.model_dump() for f in fields]
    if desired == current_fields:
        # Re-asserting the list already on file touches nothing and spends no version.
        return ExtractionSchemaOut(
            fields=fields,
            core_fields=core_fields(await core_labels(session)),
            version=current_version,
            changed=False,
        )

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
    await queue_collect_rebuild(session, tenant_id=tenant_id, agent_id=agent_id)
    return ExtractionSchemaOut(
        fields=fields,
        core_fields=core_fields(await core_labels(session)),
        version=next_version,
        changed=True,
    )


_DESCRIPTION = (
    "The agent's own list of details, kept read-only until it is dropped (D-1028, D-1029): no "
    "call reads it and no new campaign or line copies it. What a call notes is its campaign's "
    "or line's list (`/v1/campaigns/{id}/notes`, `/v1/inbound-lines/{id}/notes`), and a new "
    "one starts from the business's starting set (`/v1/lead-fields`)."
)


@router.get(
    "/v1/agents/{agent_id}/extraction-schema",
    response_model=ExtractionSchemaOut,
    openapi_extra=permission_meta("org:read"),
    summary="The agent's own list of lead details, read-only",
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
        fields=business_only(current),
        core_fields=core_fields(await core_labels(session)),
        version=version,
        changed=False,
    )


#: The rules and the write under public names: every job's list is held to `validate_fields`
#: (`campaigns/notes.save_notes`), and the platform's own seeding of an agent's list writes
#: through `write_schema` (`starters`, `lead_fields.refresh_field_reason`).
validate_fields = _validate_fields
write_schema = _write_schema
