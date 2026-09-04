"""One refusal for every write to a DELETED (archived) agent, at the one place writes are
authorised.

**WHY THIS IS A MODULE AND NOT A LINE IN EACH ENDPOINT.** There are already a dozen ways to
write to an agent — its name and direction, its script (save/apply/undo/AI assist), its
voice, its model, the two disclosure toggles, caller memory, the call cap, its extraction
schema, its enabled actions, its knowledge, its human-handoff configuration — and the list
grows every week. Four of them checked the archived state (`lifecycle.update_agent`,
`activate`, `deactivate`, `service.publish_agent`); the rest happily edited a retired
object, and the console offered a green "Open the script builder" button on the screen of an
agent whose header said Deleted. A per-button fix leaves every writer that has not been
written yet to remember on its own, which is precisely the class of defect hard rule 12
exists for.

**WHERE THE CHOKE POINT IS.** `core/auth.requires()` is the ONLY way a non-public route is
authorised — not by convention but by boot assertion: `rbac.assert_policy_registry_complete`
refuses to start a process in which any non-public route declares a permission it does not
enforce through that dependency. So a guard inside `requires()` is inherited by every agent
endpoint that exists today and by every one added tomorrow, in both realms, without the
endpoint's author doing anything and without one lane editing another lane's file.

**WHAT IT KEYS ON**, and each clause is doing work:

* the permission is in `rbac.MUTATING_PERMISSIONS` — so `POST .../script/preview`, which
  is a compile-and-return under `agents:read`, still works on a retired agent. Reading a
  deleted agent is the whole point of archiving instead of erasing.
* the HTTP method writes — a GET carrying a mutating permission is not a write.
* the path names an `{agent_id}` — the subject has to be an agent.
* the route is not one of `ARCHIVED_WRITE_EXEMPT_PATHS` — the two moves whose subject is
  legitimately a retired agent (see below).

**IT IS AN ADMISSION CHECK, NOT A REPLACEMENT FOR THE MOVERS' OWN.** It reads the status in
its own short transaction before the route opens its own, so it cannot be the authority on a
race with a concurrent archive. `lifecycle`'s movers keep their refusals under `FOR UPDATE`
on the agent row, which is where a race is actually decided; this makes the refusal
UNIVERSAL and the message ACTIONABLE, on paths that have no lock and no opinion of their own.

**THE CLIENT WORD IS DELETE (D-527).** The code, the column, the status and the audit action
still say `archive`; the sentence a person reads says deleted, because that is the button
they pressed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session

#: The methods that write. A GET or HEAD carrying a mutating permission (there are none
#: today) is still a read and is never refused here.
WRITE_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: The route templates whose SUBJECT is legitimately a retired agent, by FastAPI path.
#:
#: * `restore` is the whole answer this guard's own message gives ("restore it first"), so
#:   guarding it would make the refusal a dead end.
#: * `archive` is the DELETE itself, and re-deleting a deleted agent is an idempotent
#:   success (`lifecycle.archive_agent` returns `changed=False`, RFC 9110 §9.2.2). Turning
#:   that into a 409 would make a double-clicked Delete button an error.
#:
#: Everything else — activate, deactivate, publish, script, voice, model, disclosure,
#: caller memory, call cap, extraction schema, actions, knowledge, handoff — is refused.
#: `tests/agent_write_guard_test.py` asserts each of these paths really exists in the
#: mounted app, so a rename cannot silently turn an exemption into a hole.
ARCHIVED_WRITE_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/v1/agents/{agent_id}/archive",
        "/v1/agents/{agent_id}/restore",
    }
)


def archived_refusal(verb: str) -> ProblemError:
    """One wording for every place a deleted agent is refused.

    Deliberately not a count of the places: the number has already changed twice, and a
    count in prose is the defect class D-103/D-105 exist for.
    """
    return ProblemError.conflict(
        "agent_archived",
        f"This agent is deleted, so it cannot be {verb}.",
        remediation="Restore it first, then try again.",
    )


async def assert_agent_writable(
    session: AsyncSession, agent_id: UUID, *, verb: str = "changed"
) -> None:
    """Refuse if this agent has been deleted. Silent on every other status, and on a row
    this tenant cannot see — "not yours" is `db/ownership.assert_visible`'s question and
    answering it here would turn a 404 into a 409 that leaks a neighbour's id.
    """
    status = (
        await session.execute(
            text("SELECT status FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).scalar()
    if status is not None and str(status) == "archived":
        raise archived_refusal(verb)


async def guard_agent_write(request: Request, *, tenant_id: UUID | None) -> None:
    """The hook `core/auth.requires()` calls on every authorised mutating request.

    Cheap on the overwhelming majority of them: three in-memory tests before anything
    touches the database, and the query runs only for a write whose path names an agent.
    """
    if request.method not in WRITE_METHODS:
        return
    raw = request.path_params.get("agent_id")
    if raw is None:
        return
    route_path = getattr(request.scope.get("route"), "path", "")
    if route_path in ARCHIVED_WRITE_EXEMPT_PATHS:
        return
    # The admin realm names the tenant in the path and has no tenant of its own; the client
    # realm carries it on the principal. Neither can reach `agents` without an RLS scope, so
    # a request with no tenant at all has nothing to guard and nothing to write either.
    path_tenant = request.path_params.get("tenant_id")
    scope = _as_uuid(path_tenant) or tenant_id
    if scope is None:
        return
    agent_id = _as_uuid(raw)
    if agent_id is None:
        # A malformed id never reaches an agent; FastAPI's own 422 is the right answer and
        # a guess at the caller's intent here would only mask it.
        return
    async with tenant_session(scope) as session:
        await assert_agent_writable(session, agent_id)


def _as_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


__all__ = [
    "ARCHIVED_WRITE_EXEMPT_PATHS",
    "WRITE_METHODS",
    "archived_refusal",
    "assert_agent_writable",
    "guard_agent_write",
]
