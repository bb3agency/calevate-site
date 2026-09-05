"""WHO MAY CURATE KNOWLEDGE — the role table, plus one owner-controlled conditional grant.

THE FOUNDER'S SENTENCE, AND THE HALF THIS FILE IMPLEMENTS. "Give the staff perms allowing
option to owner and every admin should have that permission." The admin half needed no
code: every admin already approves a client's knowledge as THEMSELVES through
`POST /v1/admin/tenants/{tenant_id}/kb/{source_id}/approve` (`agents:write`,
`realm="admin"`, audited `kb.approved` with the actor's realm and id), which is a surface
D-22 never blocked because nobody is impersonating on it. This file is the staff half: a
staff member MAY curate knowledge, but only in an account whose OWN OWNER switched it on.

═══ WHY THIS IS A CONDITIONAL GRANT AND NOT A WIDER ROLE ═══

The obvious change — adding `kb:write` to `ROLE_PERMISSIONS["staff"]` — is one line and is
wrong twice. It is not per-tenant, so it would hand the capability to every staff member
of every account on the platform the instant it merged, which is the silent widening the
founder's "allowing option to owner" explicitly refuses. And `kb:write` is not one
capability: `insights/routes.py` declares it on knowledge-gap dismissal and teaching too,
so the role edit would have moved three surfaces while a reader was reviewing one.

So `ROLE_PERMISSIONS` IS UNTOUCHED. `role_has("staff", "kb:write")` is False today, was
False yesterday, and stays False — which means every OTHER `requires("kb:write")` and
every `_may(actor, "kb:write")` in this tree answers for a staff member exactly as it did
before this change existed. What is added is a dependency that asks ONE additional
question, on the three routes that spend it, after the role table has already said no.

═══ THE LADDER, AND WHY IT IS ADDITIVE BY CONSTRUCTION ═══

`requires_kb_curation()` runs `core/auth.requires("kb:write")`'s ladder first and
unchanged — role table, then D-22's mutating clause. A caller the role table already
admits (an `owner`, an `operator`, a `superadmin`) reaches the identical answer down the
identical path, including the identical refusal when impersonating. The extra clause runs
ONLY on the branch that was already a 403, so there is no input for which this dependency
is stricter than `requires("kb:write")` and no owner whose behaviour it can move.

THE EXTRA CLAUSE IS THREE CONJUNCTS AND EACH IS LOAD-BEARING:

1. `principal.realm == "client"` and `not principal.impersonating` — this grant is a
   client account's decision about its own members. An admin's authority comes from the
   admin realm's role table and its own audited surfaces, never from a row a client can
   write; a client-writable column that could widen an ADMIN principal would be privilege
   escalation with a form field. The impersonation half is D-22 restated rather than
   inherited. It is unreachable as written (an impersonating principal is admin-realm, so
   the first half already rejects it), and it stays because the cost is one `and` and the
   failure it guards is an operator putting words into a client's agent under the client's
   own name. A defence that is currently redundant is the cheapest kind to keep.
2. the role is one of `_ELIGIBLE_ROLES` — `staff`, named as a set rather than tested as
   `!= "owner"`, so a THIRD client role added tomorrow is excluded by default.
3. the account's own switch is ON, read through the request's tenant-scoped session, so
   RLS answers "whose switch is this" (hard rule 1). There is no `tenant_id` predicate in
   the statement and there must not be one: `organizations`' policy matches on `id`, and a
   WHERE clause a caller can forget is not isolation. A neighbouring tenant's `true` is
   invisible here by construction, which is what `tests/kb_staff_curation_test.py` drives.

═══ WHAT A READER CAN SEE FROM ONE GREP ═══

`grep -rn requires_kb_curation apps/` names every surface this column can unlock, and the
answer is three routes: submitting knowledge for review, dismissing a knowledge gap and
teaching one. The column reaches nothing else — not the copilot (staff cannot open it at
all; `POST /v1/copilot/ask` declares `org:manage`), not approval, not publish, not billing,
not members. That is the "a reader must be able to see exactly which capability it
unlocks" property, and it is a property of the code shape rather than of this docstring:
a fourth surface can only join by importing this name.

AND THE GATE IS UNCHANGED ON EVERY PATH. This dependency decides WHO may submit; it does
not decide what happens next. A staff-submitted source lands `pending_approval` through
`kb.service.submit_source` — the same one door `kb/proposals.py` documents — and still
waits for the admin-realm approval and publish routes. Nothing here shortens the
preview-and-approve gate, and nothing here can: it returns a `Principal` or raises.
"""

from __future__ import annotations

from typing import Annotated, Final, cast

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import PermissionDependency, current_any
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import MUTATING_PERMISSIONS, role_has

# The one capability this module can unlock, and the one `kb/proposals.py` already names
# as the lane's permission. Imported from there rather than retyped so the two cannot
# drift into two answers about which permission curation is.
from apps.api.kb.proposals import CURATE_PERMISSION

#: The client-realm roles the owner's switch can lift. `staff` and nothing else — an
#: `owner` never reaches the conditional clause (the role table admits them one rung
#: earlier). Deny-by-default, the discipline `ROLE_PERMISSIONS`' hand-kept operator set
#: keeps for the same reason.
_ELIGIBLE_ROLES: Final[frozenset[str]] = frozenset({"staff"})

#: RLS scopes this to the requesting account (`organizations`' policy matches on `id`), so
#: there is deliberately no tenant predicate — see the module docstring, conjunct 3.
#: `deleted_at IS NULL` because a closed account grants nobody anything.
_SWITCH_SQL: Final = "SELECT staff_may_curate_knowledge FROM organizations WHERE deleted_at IS NULL"

#: What the staff member is told, and what it tells them to ask for. A 403 reading only
#: "you do not have permission" leaves them filing a support ticket about a switch their
#: own owner can flip in one click (quality bar: errors are part of the interface).
_REFUSAL: Final = (
    "Only the account owner can change what the agent knows. An owner can let staff do "
    "it from the account's Knowledge settings."
)


async def may_curate_knowledge(
    session: AsyncSession, *, realm: str, role: str | None, impersonating: bool
) -> bool:
    """Whether a caller with these three properties may curate knowledge in THIS account.

    The full ladder as a predicate a non-route caller can ask — the shape
    `copilot/write_tools._may` uses, for the same reason: one answer to "may this person
    do this", asked by more than one kind of caller.

    **THREE LOOSE FIELDS RATHER THAN A `Principal`, AND THAT IS NOT A STYLE CHOICE.** The
    copilot's caller holds a `ToolActor`, not a `Principal`, so a `Principal` parameter
    would have made it BUILD one — and `tests/impersonation_audit_test.py::
    test_the_flag_that_means_impersonation_is_set_in_exactly_one_place` exists to keep
    the impersonation flag constructible in `core/auth.py` alone, because every other site
    that can set that flag is a way into a tenant that writes no audit row. The guard caught
    exactly that here. Taking the fields means nothing outside `core/auth.py` assembles an
    identity in order to ask a question about one.

    NOT a re-derivation of the role table or of D-22: `role_has` and `MUTATING_PERMISSIONS`
    are imported, so a permission that stops being mutating stops being refused here in the
    same edit rather than in a later one somebody forgets.
    """
    if role_has(role or "", CURATE_PERMISSION):
        # The pre-existing answer, byte for byte, INCLUDING D-22's clause. An owner and an
        # admin never reach the conditional grant below.
        return not (impersonating and CURATE_PERMISSION in MUTATING_PERMISSIONS)
    if realm != "client" or impersonating:
        return False
    if (role or "") not in _ELIGIBLE_ROLES:
        return False
    return bool((await session.execute(text(_SWITCH_SQL))).scalar())


async def read_switch(session: AsyncSession) -> bool:
    """The account's own switch, for the screen that renders it. RLS does the scoping."""
    row = (await session.execute(text(_SWITCH_SQL))).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    return bool(row[0])


async def write_switch(session: AsyncSession, *, enabled: bool) -> bool:
    """Set the account's switch. Answers whether anything actually moved.

    THE ROW IS LOCKED FIRST — the instrument and the argument `llm_routes._write_default`
    gives: deciding "did this change?" is a read the write depends on, and a read-then-
    write without a lock is the shape BACKEND-PATTERNS §5 refuses. Two owners toggling at
    the same instant would otherwise each read the old value and each report a change, and
    the audit log would carry two `changed: true` rows for one transition.

    NO ROW TO LOCK IS A 404, not a silent success: under RLS an account that is not this
    session's is indistinguishable from one that does not exist, and answering 200 for a
    write that stored nothing is how a console reports a setting it never made.

    THE UPDATE CARRIES NO TENANT PREDICATE FOR THE REASON THE SELECT CARRIES NONE. RLS
    applies to UPDATE as it does to SELECT, and `organizations`' policy matches on `id`,
    so this statement can only reach the row the `FOR UPDATE` above just locked. A
    `WHERE id = :tid` would read as the safety and would in fact be the second copy of a
    predicate the database already applies — the WHERE clause hard rule 1 exists to stop
    people relying on.
    """
    current = (await session.execute(text(f"{_SWITCH_SQL} FOR UPDATE"))).first()
    if current is None:
        raise ProblemError.not_found("Organization")
    if bool(current[0]) is enabled:
        # Re-asserting the value already on file is a success that touches nothing: a PUT
        # states the whole resource, so a repeat is idempotent by construction.
        return False
    await session.execute(
        text(
            "UPDATE organizations SET staff_may_curate_knowledge = :on, updated_at = now() "
            "WHERE deleted_at IS NULL"
        ),
        {"on": enabled},
    )
    return True


def requires_kb_curation() -> PermissionDependency:
    """`requires("kb:write")` plus the owner's switch — the dependency the three curation
    routes spend.

    IT CARRIES `calevate_permission = "kb:write"` AND `calevate_realm = "any"`, which is
    not decoration: `core/rbac.route_enforcement` reads exactly those attributes to prove
    at boot that a route's declared permission is the one it actually verifies. A
    hand-rolled dependency without them would make every route using it fail
    `assert_policy_registry_complete` — correctly, since the registry could then read the
    label and never the lock. The value is `kb:write` because that IS what this enforces:
    the role-table rung is unchanged, and the OpenAPI schema, the generated TS client and
    the boot registry should all keep saying so.

    THE SESSION ARRIVES BY `Depends(db)`, WHICH IS THE ROUTE'S OWN SESSION. FastAPI caches
    a dependency per request, so this reads the switch inside the same tenant-scoped
    transaction the handler then writes in — not a second connection whose GUC could be
    set from a different tenant, and not a read that could be true at the gate and false
    at the write.
    """

    async def _dep(request: Request, session: Annotated[AsyncSession, Depends(db)]) -> Principal:
        principal = await current_any(request)
        if await may_curate_knowledge(
            session,
            realm=principal.realm,
            role=principal.role,
            impersonating=principal.impersonating,
        ):
            return principal
        if principal.impersonating:
            # D-22's own words, kept verbatim from `requires()` so an operator reads the
            # same sentence here as on every other mutating surface.
            raise ProblemError.forbidden(
                "Impersonation is read-only. Perform this action from the admin console."
            )
        raise ProblemError.forbidden(_REFUSAL)

    dep = cast("PermissionDependency", _dep)
    dep.calevate_permission = CURATE_PERMISSION
    dep.calevate_realm = "any"
    return dep


__all__ = [
    "CURATE_PERMISSION",
    "may_curate_knowledge",
    "read_switch",
    "requires_kb_curation",
    "write_switch",
]
