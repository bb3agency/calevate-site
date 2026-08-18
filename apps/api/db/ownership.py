"""Refuse a caller-supplied reference to a row this tenant cannot see (D-193).

RLS is hard rule 1's isolation and it is doing its job on every READ in this tree. It
does not cover a WRITE that merely NAMES another tenant's row, and the gap is in
PostgreSQL by design:

    **Referential-integrity checks run with row security bypassed.**

That is deliberate on their side — integrity must not be defeasible by visibility, or a
tenant could delete a row somebody invisible to them still points at. The consequence
here is precise: a policy's `WITH CHECK` enforces the `tenant_id` OF THE ROW BEING
WRITTEN, so tenant B cannot forge a row into tenant A; but the foreign key in that row
is validated against the whole table, so B's own row may point at A's agent, A's
registered calling number, A's DLT template or A's call, and the INSERT succeeds. The
same is true of UNIQUE indexes, which are likewise evaluated over every row rather than
the visible ones.

WHAT THAT BUYS AN ATTACKER, and why "RLS blocks it downstream" is not an answer. Every
consumer checked when this was written does fail closed — `check_dispatch` scopes the
agent by `tenant_id` explicitly, and the launch gate's joins run under the caller's own
session, so a foreign number reads back NULL and the campaign is blocked as
`number_missing`. Three things survive that:

  * **The reference is stored.** It is one un-scoped `JOIN` away from disclosure, and
    that join is a normal thing for a future reader to write —
    `campaigns/service.py:1197` already carries a hand-written
    `AND p.tenant_id = c.tenant_id` on one such join, which is the same hazard noticed
    at the read side and patched one query at a time.
  * **Some of those rows are APPEND-ONLY.** `consent_ledger` is in
    `db/registry.APPEND_ONLY_TABLES` (hard rule 4), so a consent record citing another
    tenant's call as the conversation the customer agreed in cannot be corrected, only
    compensated. It is a legal record under DPDP and it is wrong permanently.
  * **It breaks the interface.** A campaign created against a foreign agent is visible
    in the client's own list and answers 200 on its detail route, while its
    launch-check 404s "Campaign not found" — because `_campaign_facts` INNER JOINs
    `agents`. That is a row the client owns, can see, and can never explain.

WHY ONE MODULE RATHER THAN A GUARD PER WRITE PATH. This check already existed twice —
`kb.service._assert_agent_is_ours` (whose docstring stated the mechanism above
correctly) and `ingest.service._agent_is_ours` — and two more write paths were shipped
without it. Two copies is how the third one comes to be missing; both callers move here
in the same change, so there is one place to add a reference kind and one place a
reviewer has to look. The kb-specific consequence (its `(agent_id, name, version)`
unique index turns an unauthorised row into a cross-tenant denial of service AND an
existence oracle) stays as a comment at that call site, because it is a fact about that
index rather than about this rule.

IT MUST STAY A READ ON THE CALLER'S OWN SESSION. `agents`, `calls`, `phone_numbers` and
`dlt_templates` are all FORCE-RLS'd, so "visible to this statement" is exactly "this
tenant's" — the database answers, and no handler has to remember a `tenant_id`.
Comparing a caller-supplied tenant id against something else the caller supplied would
prove nothing. It is also why the refusal is 404 and never 403: from inside a tenant,
"that id is not yours" and "there is no such id" are the same fact, and distinguishing
them would publish the existence of a neighbour's rows (the doctrine
`tests/adversarial_pass_test.py` pins for every `{id}` route).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError

#: The kinds of row a client may name in a request body. Adding one is a line here and a
#: line in each mapping below — deliberately not a table-name parameter, which would put
#: a caller-chosen identifier into SQL and is the thing `scripts/check_raw_sql.py` exists
#: to refuse.
OwnedRef = Literal["agent", "call", "dlt_template", "phone_number"]

#: Literal SQL per kind. No `deleted_at` predicate on `agents`: both guards this replaces
#: asked plain visibility, the callers that care about liveness ask their own richer
#: question afterwards (`check_dispatch`, the launch gate), and narrowing it here would
#: change the answer those callers already depend on.
_VISIBLE_SQL: dict[OwnedRef, str] = {
    "agent": "SELECT 1 FROM agents WHERE id = :rid",
    "call": "SELECT 1 FROM calls WHERE id = :rid",
    "dlt_template": "SELECT 1 FROM dlt_templates WHERE id = :rid",
    "phone_number": "SELECT 1 FROM phone_numbers WHERE id = :rid",
}

#: What the 404 calls the thing, in the words a client uses for it.
_LABEL: dict[OwnedRef, str] = {
    "agent": "Agent",
    "call": "Call",
    "dlt_template": "DLT template",
    "phone_number": "Phone number",
}


async def assert_visible(session: AsyncSession, ref: OwnedRef, row_id: UUID | None) -> None:
    """Refuse `row_id` unless this tenant-scoped session can see it.

    `None` is a no-op: every reference this guards is a NULLABLE column, and "no number
    attached yet" is a legitimate draft state that the launch gate — not this function —
    is responsible for refusing at the point it matters.

    Call it BEFORE any lock or any write, so naming a neighbour's row cannot make us
    hold a lock on their behalf (the ordering `kb.service.submit_source` already argues).
    """
    if row_id is None:
        return
    visible = (await session.execute(text(_VISIBLE_SQL[ref]), {"rid": row_id})).scalar()
    if visible is None:
        raise ProblemError.not_found(_LABEL[ref])


__all__ = ["OwnedRef", "assert_visible"]
