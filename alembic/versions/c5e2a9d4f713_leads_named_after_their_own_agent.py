"""A lead a call renamed to the agent's own name gets its real name back, or none

Revision ID: c5e2a9d4f713
Revises: a8d3f1c6e2b9
Create Date: 2026-11-01

Before e4e9aa853 a caller who asked "Anjali?" had "Anjali" filed as their name, and
`_upsert_lead`'s latest-call-wins merge renamed the lead to the agent. The pipeline no longer
does either (`apps/workers/caller_name.py`), but the leads it already renamed still carry the
agent's name, so every caller line on their calls reads as the agent.

A lead is repaired when its name is the agent's or the business's (a whole-word run of any of
the tenant's agent names, or the business name whole, after `caller_name.fold`) AND one of its
own calls captured exactly that name. The second condition is the evidence that a call wrote
it: a client who named a lead "Priya" themselves keeps it even when an agent is called Priya.

The name restored is, first, the newest dialled campaign row's for the lead's number and agent
(the client's own list, which is what the agent greeted the person with), then the newest name
a call of the lead captured that is not a self name; with neither, the name is cleared. The
lead's captured `name` / `caller_name` keys holding a self name are removed from `leads.data`,
as `without_self_names` removes them from a new extraction. `updated_at` is left alone: the
Leads table sorts on it and this is no activity of the client's.

`call_extractions` is left as written: it is the record of what the model returned for that
call, and the call page already reads its name through the lead.

`_FOLD` is `caller_name.fold` in SQL, so the statement is fixed and renders under `--sql`.
Two differences, both towards matching LESS: letters outside Latin, Devanagari and Telugu
fold to spaces here (a name wholly in another script folds to "" and is never matched), and
`lower()` follows the database's ctype, so an uppercase non-ASCII letter with no decomposition
(Ø) may stay uppercase under a C locale. `tests/lead_self_name_repair_test.py` holds the SQL
fold equal to the Python one over the names this repair is for.

DOWNGRADE is empty: the value replaced is the defect, and putting it back would rename the
leads to the agent again.
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "c5e2a9d4f713"
down_revision: str | None = "a8d3f1c6e2b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")


def _fold(expr: str) -> str:
    """`caller_name.fold(expr)` in SQL: diacritics stripped after decomposition, lowercased,
    and every run of characters that are not part of a word made one space."""
    return (
        "btrim(regexp_replace(lower(normalize(regexp_replace(normalize("
        f"{expr}, NFKD), '[\\u0300-\\u036f]', '', 'g'), NFC)), "
        "'[^0-9a-z\\u00c0-\\u024f\\u0300-\\u036f\\u0900-\\u0963\\u0966-\\u097f"
        "\\u0c00-\\u0c7f]+', ' ', 'g'))"
    )


def _captured(alias: str) -> str:
    """The caller's name one extraction captured: `name`, else the older `caller_name`."""
    return (
        f"NULLIF(btrim(COALESCE(NULLIF(btrim({alias}.data->>'name'), ''), "
        f"{alias}.data->>'caller_name')), '')"
    )


def _is_self(expr: str, tenant: str) -> str:
    """Whether `expr` is one of the tenant's agent names (whole-word run) or its business
    name (whole). False, never NULL, for an empty or missing name."""
    folded = _fold(expr)
    return (
        f"COALESCE({folded} <> '' AND ("
        f"{folded} = (SELECT {_fold('o.name')} FROM organizations o WHERE o.id = {tenant}) "
        f"OR EXISTS (SELECT 1 FROM agents a WHERE a.tenant_id = {tenant} "
        f"AND strpos(' ' || {_fold('a.name')} || ' ', ' ' || {folded} || ' ') > 0)), false)"
    )


def _repair_statement() -> str:
    captured = _captured("e")
    return (
        "WITH renamed AS ("
        "SELECT l.id, l.tenant_id, l.agent_id, l.phone_e164 FROM leads l "
        f"WHERE l.name IS NOT NULL AND {_is_self('l.name', 'l.tenant_id')} "
        "AND EXISTS (SELECT 1 FROM calls c JOIN call_extractions e ON e.call_id = c.id "
        f"WHERE c.lead_id = l.id AND {_fold(captured)} = {_fold('l.name')})"
        "), restored AS ("
        "SELECT r.id, COALESCE("
        "(SELECT btrim(cc.name) FROM campaign_contacts cc "
        "JOIN campaigns cp ON cp.id = cc.campaign_id "
        "WHERE cc.tenant_id = r.tenant_id AND cc.phone_e164 = r.phone_e164 "
        "AND cp.agent_id = r.agent_id AND btrim(cc.name) <> '' "
        f"AND NOT {_is_self('cc.name', 'r.tenant_id')} "
        "ORDER BY cc.updated_at DESC, cc.id DESC LIMIT 1), "
        f"(SELECT {captured} FROM calls c JOIN call_extractions e ON e.call_id = c.id "
        f"WHERE c.lead_id = r.id AND {captured} IS NOT NULL "
        f"AND NOT {_is_self(captured, 'r.tenant_id')} "
        "ORDER BY COALESCE(c.started_at, c.created_at) DESC, e.created_at DESC LIMIT 1)"
        ") AS name FROM renamed r) "
        "UPDATE leads l SET name = s.name, "
        "data = l.data - ARRAY(SELECT k FROM unnest(ARRAY['name', 'caller_name']) k "
        f"WHERE {_is_self('l.data->>k', 'l.tenant_id')}) "
        "FROM restored s WHERE l.id = s.id"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # The bracket (d3b71c9a5e08): every table the statement reads or writes is FORCE-RLS'd,
    # and the migration role is subject to `tenant_isolation`, so without it the statement
    # matches no rows wherever the owner is not a superuser.
    op.execute("ALTER TABLE leads NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE calls NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE call_extractions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE campaign_contacts NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE campaigns NO FORCE ROW LEVEL SECURITY")
    repaired = execute_data_statement(
        sa.text(_repair_statement()),
        note="Restored or cleared each lead a call had renamed to its own agent.",
    )
    op.execute("ALTER TABLE campaigns FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE campaign_contacts FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE call_extractions FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE calls FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE leads FORCE ROW LEVEL SECURITY")
    if repaired is not None:
        log.info("leads named after their own agent: %s repaired", repaired)


def downgrade() -> None:
    pass
