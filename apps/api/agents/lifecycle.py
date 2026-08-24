"""The life of an agent: born a draft, activated, deactivated, archived, restored (D-440).

An agent is the object a business owner creates, trains and puts on their phone line, and
until this module existed it had no life of its own: `admin/service.create_organization`
minted exactly one per tenant, `publish_agent` moved it to `live`, and nothing in the tree
could move it back. `paused` was in the CHECK constraint and no code path wrote it.

WHAT THE FOUR STATES MEAN, and every one of them is enforced by a gate that already
existed rather than by a new one:

* `draft`    — being written. Never dialled, never answers: `check_dispatch` refuses
               `status <> 'live'` per contact, and the engine holds no agent for it at all.
* `live`     — the ACTIVE state. Published, verified against the engine, answering the
               numbers bound to it and dialable by a campaign.
* `paused`   — the INACTIVE state. Off the frontline and reversible: the row, the script,
               the numbers and the history all stay, and `activate` puts it back by
               republishing rather than by flipping a column.
* `archived` — retired. Never dialled, never assignable, and NOT deleted: `deleted_at` is
               the DPDP erasure column and writing it here would take the agent's own call
               history off every screen (migration e4b90d27c1f6 argues this at length).

WHY THE TRANSITIONS ARE A TABLE AND NOT A CHAIN OF `if`s. BACKEND-PATTERNS §5 asks for
"a central transition table + `INVALID_STATUS_TRANSITION` error", and `AGENT_TRANSITIONS`
below is the whole of the machine: which moves are legal is one dict, so a fifth state or
a new edge is one line in one place and no function carries a private opinion about it.

WHICH MOVER OWNS WHICH EDGE IS A SECOND QUESTION AND NEEDS A SECOND ANSWER — `AGENT_MOVERS`
— because two buttons end at `paused`. Deriving a mover's accepted sources from its TARGET
alone gave `restore` the `live -> paused` edge and `deactivate` the `archived -> paused`
one, which is a restore that silently switched a live agent off while its numbers went on
answering. The two tables are held together at import (`_assert_movers_partition_the_table`)
rather than by anybody remembering, so neither can grow an edge the other does not have.

WHY `activate` IS A PUBLISH AND NOT A COLUMN WRITE. "Active" is a claim about somebody
else's system — that the engine is holding this agent's script, its voice and the
truthful-answer directive — and D-64 made `publish_agent` prove that by reading the agent
back before any column says `live`. An activate that wrote `status = 'live'` directly would
be the exact defect that decision closed, one layer up. So this module never writes `live`;
it calls `publish_agent`, which earns it.

WHY `deactivate` AND `archive` REACH THE ENGINE. Taking an agent off the frontline has to
stop the phone ringing, and the phone is bound at the vendor: `phone_numbers.agent_id` is
our record of it and `bind_inbound_number` is what made it true (D-420). A paused agent
whose numbers still answer is a client's line still being picked up by an AI they switched
off — the same class of lie D-420 exists for, in the opposite direction. So both movers
release the agent's numbers, through the same function a publish uses.

WHAT THIS MODULE DELIBERATELY DOES NOT ADD: a per-agent concurrency knob. Multiple live
agents genuinely answer inbound in parallel — inbound is a per-number binding and the
vendor documents no inbound limit — but OUTBOUND parallelism is an ACCOUNT-level pool
(`workers/campaign_dispatch.PLATFORM_LINES_TOTAL` minus the inbound reserve, clamped per
tenant by the plan), and over-limit outbound is QUEUED by the vendor in a queue we can
neither see nor cancel. A number on an agent row would therefore be a promise nothing can
keep. The honest per-agent fact is how many numbers it answers, which is a count of
`phone_numbers`, and that is what the API returns.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.models import AGENT_DIRECTIONS, AgentDirection, AgentStatus
from apps.api.agents.service import publish_agent, route_inbound_numbers
from apps.api.compliance.disclosure import (
    ai_disclosure_for,
    bundled_disclosure_line,
    recording_notice_for,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.transition import transition_status
from apps.api.engine import get_engine
from apps.api.tenancy.lifecycle import assert_account_open

log = get_logger(__name__)

#: THE STATE MACHINE, as one table (BACKEND-PATTERNS §5). Read it as "from → the states it
#: may reach". Everything else in this module derives from it.
#:
#: `archived -> paused` and NOT `archived -> live` is the one edge worth arguing. Coming
#: back from the archive must not put an agent on the phone in the same request: the engine
#: may have been reconfigured, deleted or drifted while the agent sat retired, and the only
#: thing that can establish what it is holding is a publish with its read-back. So a
#: restore returns the agent to the INACTIVE state and the owner activates it deliberately,
#: which runs that proof.
AGENT_TRANSITIONS: dict[AgentStatus, frozenset[AgentStatus]] = {
    "draft": frozenset({"live", "archived"}),
    "live": frozenset({"paused", "archived"}),
    "paused": frozenset({"live", "archived"}),
    "archived": frozenset({"paused"}),
}

#: THE ONE STATE A CAMPAIGN MAY NOT NAME. Everything else is assignable, deliberately: a
#: client assembles a campaign draft — list, template, number, window — while the agent it
#: will use is still being written, and `campaigns/service.launch_blockers` refuses the
#: LAUNCH with `agent_not_live` until it is published. Archived is different in kind: there
#: is no state of the world in which that campaign becomes launchable, so binding it is a
#: dead end the client cannot diagnose, and the founder's rule is that an archived agent is
#: never assignable.
ASSIGNABLE_STATUSES: frozenset[AgentStatus] = frozenset(
    status for status in AGENT_TRANSITIONS if status != "archived"
)


#: WHICH MOVER OWNS WHICH IN-EDGE, and why `AGENT_TRANSITIONS` alone cannot say.
#:
#: The table answers "is this move legal". A mover has to answer a different question —
#: "is this move MINE" — and the two stop having the same answer the moment two buttons
#: end at one state. `deactivate` and `restore` BOTH finish at `paused`, one from `live`
#: and one from `archived`, so deriving a mover's accepted sources from its TARGET handed
#: each of them the other's edge. Both halves shipped and both were wrong:
#:
#: * **Restore on a LIVE agent returned 200 and wrote `paused`.** Restore releases no
#:   numbers — it has none to release — so our record said the agent was switched off
#:   while the voice platform went on answering every line bound to it. That is precisely
#:   the lie D-420 exists for, produced by the one button whose promise is that it is the
#:   safe, reversible half of the archive.
#: * **Deactivate on an ARCHIVED agent let it out of the archive**, under the wrong audit
#:   action (`agent.deactivated` for what was a restore) and without clearing
#:   `archived_at` — so it landed on `ck_agents_archived_at_matches_status` as an
#:   IntegrityError nobody authored rather than a refusal anybody can read. The constraint
#:   is what turned a silent un-archiving into a loud 500; it is not what should have
#:   stopped it.
#:
#: PARTITION, NOT A SECOND LIST. `_assert_movers_partition_the_table` below runs at import
#: and fails unless these edges are EXACTLY the edges of `AGENT_TRANSITIONS`: a mover
#: cannot claim an edge the table forbids, and an edge added to the table cannot be left
#: without a mover to make it. That is the property the target-keyed derivation was
#: protecting (D-104 — one rule, one spelling, no stale copy); what it could not do was
#: tell two movers apart, and this can do both.
AGENT_MOVERS: dict[str, tuple[frozenset[AgentStatus], AgentStatus]] = {
    "activate": (frozenset({"draft", "paused"}), "live"),
    "deactivate": (frozenset({"live"}), "paused"),
    "archive": (frozenset({"draft", "live", "paused"}), "archived"),
    "restore": (frozenset({"archived"}), "paused"),
}


def _sources_for(mover: str) -> tuple[AgentStatus, ...]:
    """The states `mover` accepts, sorted so the CAS predicate is stable across runs."""
    sources, _ = AGENT_MOVERS[mover]
    return tuple(sorted(sources))


def _owners(
    movers: Mapping[str, tuple[frozenset[AgentStatus], AgentStatus]],
) -> dict[tuple[AgentStatus, AgentStatus], list[str]]:
    """`{edge: the movers claiming it}` — a LIST, because the duplicates are the finding."""
    owners: dict[tuple[AgentStatus, AgentStatus], list[str]] = {}
    for mover, (sources, target) in sorted(movers.items()):
        for source in sources:
            owners.setdefault((source, target), []).append(mover)
    return owners


def _assert_movers_partition_the_table(
    transitions: Mapping[AgentStatus, frozenset[AgentStatus]] | None = None,
    movers: Mapping[str, tuple[frozenset[AgentStatus], AgentStatus]] | None = None,
) -> None:
    """Every legal edge is made by EXACTLY ONE mover — checked at import, not in prose.

    A PARTITION and not a set equality, and the difference is the whole defect: two movers
    claiming one edge leaves the edge covered, the vocabularies agreeing and both dicts
    looking right, while the button that should refuse the move makes it instead. Set
    equality was this function's first draft and it passed on the shipped bug.

    Both arguments are injectable for `check_redaction_exposure`'s reason: a registry
    nobody can take away in a test is one nobody can prove still sees anything.
    """
    table = AGENT_TRANSITIONS if transitions is None else transitions
    owned = AGENT_MOVERS if movers is None else movers
    legal = frozenset((source, target) for source, targets in table.items() for target in targets)
    owners = _owners(owned)
    unowned = sorted(legal - set(owners))
    illegal = sorted(set(owners) - legal)
    shared = sorted((edge, names) for edge, names in owners.items() if len(names) > 1)
    if unowned or illegal or shared:
        raise AssertionError(
            "AGENT_MOVERS and AGENT_TRANSITIONS disagree about the agent lifecycle. "
            f"Claimed by no mover: {unowned}. "
            f"Claimed but not legal: {illegal}. "
            f"Claimed by more than one mover: {shared}."
        )


_assert_movers_partition_the_table()


# Only rows this tenant can see AND that the erasure path has not taken. `transition_status`
# applies it to the CAS and to the discriminating SELECT, which is what makes "erased" and
# "never existed" one answer instead of a 409 naming a status the caller may not know.
_VISIBLE = "deleted_at IS NULL"


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    """What a transition did, so a route can audit the MOVE rather than the button press.

    `changed=False` is the idempotent answer — the agent already held the state asked for —
    and it is the reason this is a value rather than `None`: an audit row written for a
    second click would claim a decision nobody took, and `integrations/routes.py`'s
    `deactivate_endpoint` skips its ledger write on exactly this signal.
    """

    agent_id: UUID
    status: AgentStatus
    changed: bool
    #: How many of this agent's numbers the engine was told to stop answering. Zero on a
    #: draft (nothing was ever bound) and on an engine that cannot route numbers at all.
    numbers_released: int


async def create_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    name: str,
    direction: AgentDirection,
    language_primary: str,
    max_call_duration_s: int | None = None,
) -> UUID:
    """Mint a DRAFT agent with the compliance floor already satisfied, and return its id.

    **THE ONE INSERT INTO `agents` ON ANY PATH THAT PRODUCES AN AGENT A CLIENT USES.** It
    used to live inline in `admin/service._write_tenant_root`, which was fine while a tenant
    got exactly one agent and nobody else could make another; the moment a client can create
    their own, a second INSERT is a second place that decides what a new agent is born with
    — and four of those columns are hard rule 5. `_write_tenant_root` now calls this, so the
    receptionist a new client is born with and the fifth agent they create at 11pm are the
    same object.

    THIS SENTENCE USED TO SAY "THE ONE INSERT INTO `agents` IN THIS REPOSITORY" AND THAT WAS
    NOT TRUE WHEN IT WAS WRITTEN: `scripts/restore_drill.py::_seed` inserts two agent rows
    into a scratch database so a restored copy can be compared against its source. That one
    is legitimate and now says so where it can be checked rather than where it can be
    believed — `scripts/check_compliance_invariants.py::AGENT_STATE_WRITERS` registers every
    writer of an agent's existence or status with its reason, and fails the build on a third.
    A prose claim of uniqueness is worth exactly as much as the enumeration behind it.

    **CREATION IS NOT A ROUTE AROUND THE FLOOR.** Both sentences are written here, from the
    language templates, and never taken from the caller: `ai_disclosure_line` and
    `recording_notice_line` are NOT NULL with non-empty CHECKs, both toggles start TRUE,
    and the legacy bundle is composed from the pair by its own function. There is no
    argument to this function that can produce an agent without an AI disclosure on file,
    which is what the dial gate reads and what the truthful answer needs something to say.
    Wording a disclosure differently is a separate, reviewed surface — not a field on the
    create form, because the create form is the one place a client is not yet thinking
    about TRAI.

    **NO SCRIPT, AND THAT IS THE POINT OF `draft`.** `publish_agent` refuses an agent with
    no prompt version by name (`agent_has_no_script`), so a newly created agent cannot be
    activated until somebody writes what it says. The alternative — seeding a placeholder —
    is the defect `_assert_has_a_script` exists to have removed.

    The tenant must still be OPEN, for `publish_agent`'s reason one step earlier: an agent
    created against a churned or erased account is a row on a retention clock, and the
    account that cannot take a publish should not be manufacturing things to publish.
    """
    await assert_account_open(session, tenant_id=tenant_id)
    if direction not in AGENT_DIRECTIONS:
        # Unreachable through the API, whose schema is the same Literal — and asked anyway,
        # because this is also the function `admin/service` and any future importer call,
        # and `ck_agents_direction_enum` refusing it would surface as an IntegrityError
        # nobody authored.
        raise ProblemError(
            kind="validation",
            code="agent_direction_invalid",
            title="Unrecognised calling direction",
            detail=f"An agent's direction must be one of: {', '.join(AGENT_DIRECTIONS)}.",
        )

    business = (
        await session.execute(
            text("SELECT name FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar()
    # `assert_account_open` above has already 404'd an invisible or absent tenant, so this
    # read cannot be empty; `str()` is for the type, not for a case.
    ai_line = ai_disclosure_for(language=language_primary, business=str(business))
    recording_line = recording_notice_for(language=language_primary)
    agent_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO agents (id, tenant_id, name, direction, language_primary, "
            "disclosure_line, ai_disclosure_line, recording_notice_line, "
            "ai_disclosure_enabled, recording_notice_enabled, max_call_duration_s, "
            "status, engine, created_at, updated_at) VALUES (:id, :tid, :name, :dir, :lang, "
            ":bundle, :ai_line, :rec_line, true, true, :cap, 'draft', :engine, now(), now())"
        ),
        {
            "id": agent_id,
            "tid": tenant_id,
            "name": name,
            "dir": direction,
            "lang": language_primary,
            # Both toggles TRUE and the bundle written, spelled at the INSERT rather than
            # left to a `server_default` three files away: a new agent discloses, and that
            # is a statement worth reading here.
            "bundle": bundled_disclosure_line(
                ai_disclosure_line=ai_line, recording_notice_line=recording_line
            ),
            "ai_line": ai_line,
            "rec_line": recording_line,
            "cap": max_call_duration_s,
            "engine": get_settings().engine,
        },
    )
    log.info(
        "agent_created",
        extra={
            "agent_id": str(agent_id),
            "tenant_id": str(tenant_id),
            "direction": direction,
            "language_primary": language_primary,
        },
    )
    return agent_id


async def update_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    name: str | None = None,
    direction: AgentDirection | None = None,
    language_primary: str | None = None,
    llm_model: str | None = None,
    set_llm_model: bool = False,
) -> None:
    """Edit the fields that describe WHAT an agent is.

    Returns nothing: the caller re-reads the agent to answer with, and a boolean nobody
    consults is a value the next reader has to work out the meaning of.

    All of them ride on `AgentConfig` — name, direction, language and the chosen model
    reach the vendor's agent object — so a LIVE agent is republished in the same
    transaction. That is the ordering `set_call_cap` and `set_disclosure_posture` already
    use and the reason it is safe: the column write happens first, the engine push
    second, so a vendor failure rolls the row back with it and our record never claims a
    configuration the engine was not sent.

    DIRECTION IS THE ONE THAT RINGS A PHONE. Republishing runs `route_inbound_numbers`,
    which BINDS this agent's numbers when it answers inbound and RELEASES them when it does
    not — so switching a `both` agent to `outbound` here actually stops it picking up,
    rather than only stopping our screens saying it does.

    An ARCHIVED agent is refused. Its script, its numbers and its history stay readable —
    that is what archiving is — but editing what a retired agent *is* changes a record
    somebody may be reading as evidence of what it was.

    `None` on a field leaves it alone, for `DisclosureIn`'s reason: a screen with three
    inputs sends whichever one moved, and a PATCH that could only send all three would make
    renaming an agent a read-modify-write race against a direction change.

    ⚠ **`llm_model` BREAKS THAT RULE AND NEEDS TWO ARGUMENTS FOR IT** (D-454). Its column
    is nullable and its NULL is a meaning — "inherit the account default" — so `None`
    cannot also stand for "leave it alone" without making the two requests
    indistinguishable. `set_llm_model` is what separates them, and it is a separate
    parameter rather than a sentinel value because a sentinel would have to travel through
    `AgentUpdateIn` and into the OpenAPI document as a type no generated client can spell.
    """
    # COLUMN NAMES, not a name->value map, which is what this was: nothing has ever read
    # the values (the log line prints `sorted(supplied)` and the emptiness check reads the
    # keys), and holding them made "supplied" unable to express the one field whose
    # supplied value is legitimately NULL.
    supplied = [
        column
        for column, value in (
            ("name", name),
            ("direction", direction),
            ("language_primary", language_primary),
        )
        if value is not None
    ]
    if set_llm_model:
        # Named here rather than by the comprehension above, because "the caller asked for
        # NULL" is a supplied field and `value is not None` cannot see it.
        supplied.append("llm_model")
    if not supplied:
        # A body that names nothing is a client bug, and answering 200 for it would write
        # an audit row describing a decision nobody took (`DisclosureIn._at_least_one`).
        raise ProblemError(
            kind="validation",
            code="agent_update_empty",
            title="Nothing to change",
            detail=(
                "Change at least one thing — the name, the direction, the main "
                "language or the language model."
            ),
        )

    # SELECT FOR UPDATE before the write, not a bare CAS, because two things have to be
    # decided from one read: whether the agent is archived (a refusal with its own name)
    # and whether it is live (a republish). A CAS could carry the first and not the second.
    row = (
        await session.execute(
            text(
                "SELECT status, engine_agent_ref FROM agents "
                "WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"
            ),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    if str(row[0]) == "archived":
        raise _archived_refusal("edited")

    # ONE STATEMENT WITH `coalesce`, NOT AN ASSEMBLED ASSIGNMENT LIST. Building
    # `SET name = :name, ...` from the fields that were supplied is the obvious shape and
    # it puts a computed fragment into `text()`, which `scripts/check_raw_sql.py` refuses on
    # principle — 493 statements in this tree run as a NOBYPASSRLS role and an injection
    # here is a `SET LOCAL` away from every account, so the rule is that the whole string is
    # typed in our source. `coalesce(:col, col)` says exactly what the signature says —
    # NULL leaves the column alone — with every column named literally.
    #
    # No rowcount check: the row is held FOR UPDATE above, so a concurrent delete cannot
    # commit before this statement runs and zero rows is not a state this can reach.
    await session.execute(
        text(
            "UPDATE agents SET name = coalesce(:name, name), "
            "direction = coalesce(:direction, direction), "
            "language_primary = coalesce(:language_primary, language_primary), "
            # NOT `coalesce`, and this is the one column where it would be wrong: a NULL
            # here is the caller ASKING for NULL, so `coalesce(:llm_model, llm_model)`
            # would silently turn "clear my choice" into "change nothing". The CASE reads
            # the second parameter — the same distinction `set_llm_model` carries all the
            # way from the request body — with both columns still named literally, which
            # is what `scripts/check_raw_sql.py` requires of every statement here.
            "llm_model = CASE WHEN :set_llm_model THEN CAST(:llm_model AS text) "
            "ELSE llm_model END, "
            "updated_at = now() WHERE id = :aid AND deleted_at IS NULL"
        ),
        {
            "name": name,
            "direction": direction,
            "language_primary": language_primary,
            "llm_model": llm_model,
            "set_llm_model": set_llm_model,
            "aid": agent_id,
        },
    )
    if str(row[0]) == "live" and bool(row[1]):
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    log.info(
        "agent_updated",
        extra={
            "agent_id": str(agent_id),
            "tenant_id": str(tenant_id),
            # Field NAMES, not values: an agent's name is a client's business copy and
            # there is nothing an operator does with it in a log line (hard rule 6's
            # neighbourhood).
            "fields": sorted(supplied),
            "republished": str(row[0]) == "live" and bool(row[1]),
        },
    )


async def activate_agent(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> LifecycleResult:
    """Put the agent on the frontline: `draft`/`paused` → `live`, BY PUBLISHING.

    This function writes no status. `publish_agent` does, and only after it has created or
    updated the agent at the engine and read it back to prove the engine is holding the
    script, the opening line and the truthful-answer directive (D-64). An activate that set
    `status = 'live'` itself would be a claim about the vendor derived from a fact about us,
    which is precisely what that decision removed.

    So every refusal a publish can raise is a refusal this can raise, by design and with
    better wording than a lifecycle-only check could invent: no script (`agent_has_no_script`),
    a closed account, an engine that does not host agents, a read-back that proved the
    change did not land.

    ALREADY LIVE IS SUCCESS AND PUBLISHES NOTHING (RFC 9110 §9.2.2). The caller's intent —
    be on the frontline — already holds. Re-pushing the configuration is a different intent
    with its own endpoint, and doing it here would make a double-clicked button hit the
    vendor twice.
    """
    status = await _locked_status(session, agent_id)
    if status == "archived":
        raise _archived_refusal("activated")
    if status == "live":
        return LifecycleResult(agent_id=agent_id, status="live", changed=False, numbers_released=0)
    # `draft` and `paused` are what is left, and `AGENT_TRANSITIONS` says both may go live.
    # There is deliberately no third branch asserting that: it could not execute today, and
    # a defensive arm nothing can reach is a suppression in the report rather than a guard.
    # What keeps this honest when a FIFTH state is added is
    # `agent_lifecycle_test.test_activate_accepts_exactly_the_states_the_table_admits`,
    # which fails the moment the table and these two branches stop agreeing.
    await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    return LifecycleResult(agent_id=agent_id, status="live", changed=True, numbers_released=0)


async def deactivate_agent(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> LifecycleResult:
    """Take the agent off the frontline: `live` → `paused`, and stop the phone ringing.

    Reversible by design — the row, the script, the numbers and the history all stay, and
    `activate` republishes rather than flipping a column back.

    THE ENGINE RELEASE IS THE HALF THAT MATTERS. `check_dispatch` already refuses to DIAL a
    non-live agent on the very next tick, so outbound stops by itself; inbound does not,
    because an incoming call is answered by whatever the vendor has bound to the number and
    nothing in our database is consulted. Without the release, "paused" would mean "stops
    calling out, still picks up" — which is not what any owner pressing this means.

    `tenant_id` is taken and deliberately unused: the session is already RLS-scoped to it,
    so naming it in a predicate would prove nothing (`db/ownership.py`). It stays in the
    signature because every mover in this module takes it and because the ROUTE needs it
    for the audit row — a signature that varied per transition would make the caller
    remember which of four functions wants which arguments.
    """
    del tenant_id
    # ARCHIVED IS ITS OWN REFUSAL, and it is read under the lock rather than left to the
    # CAS. The CAS is what makes the rule true — `from_statuses` is `('live',)`, so an
    # archived row is never updated — but the answer it produces on its own is "cannot
    # move from archived to paused", which is both the wrong action to offer and the
    # wording every OTHER archived refusal in this module deliberately does not use.
    if await _locked_status(session, agent_id) == "archived":
        raise _archived_refusal("deactivated")
    moved = await transition_status(
        session,
        table="agents",
        entity="Agent",
        row_id=agent_id,
        to_status="paused",
        from_statuses=_sources_for("deactivate"),
        visible_where=_VISIBLE,
    )
    released = await _release_inbound_numbers(session, agent_id=agent_id) if moved else 0
    return LifecycleResult(
        agent_id=agent_id, status="paused", changed=moved, numbers_released=released
    )


async def archive_agent(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> LifecycleResult:
    """Retire the agent: `draft`/`live`/`paused` → `archived`. Never a delete.

    WHAT SURVIVES, and it is the whole reason this is not `deleted_at`: the agent row, its
    prompt versions, its extraction schema, every `calls` row that references it
    (`calls.agent_id` is ON DELETE RESTRICT for exactly this) and its audit trail. What
    stops is dialling — `check_dispatch` refuses `status <> 'live'` — and answering, which
    is the number release below.

    ARCHIVING FROM `live` IS ALLOWED and does the deactivation's work in the same move. The
    alternative, forcing deactivate-then-archive, buys nothing: both paths must release the
    numbers, and a two-click retirement is a retirement somebody abandons halfway.

    `archived_at` is stamped by the transition itself, in the same UPDATE as the status,
    because `ck_agents_archived_at_matches_status` makes the pair inseparable — there is no
    moment at which one is written and the other is not.

    IT REFUSES WHILE A CAMPAIGN IS STILL DIALLING THROUGH THIS AGENT, and `deactivate`
    deliberately does not. The dispatcher's per-contact gate refuses a non-live agent, but
    it refuses it CONTACT BY CONTACT: the campaign stays `running`, claims its next batch
    every tick, is refused, refunds and reschedules — for ever, showing the client a
    campaign that says "running" and calls nobody, with nothing on the screen to say why
    (`campaigns/service.launch_blockers` is the reason that state has a name, and it only
    runs at launch). Retiring an agent is not urgent enough to be worth manufacturing that;
    pausing it IS, because deactivate is the emergency brake and an incident is the worst
    possible time to be told to go and tidy up a campaign first.
    """
    del tenant_id
    # THE LOCK COMES FIRST, AND WITHOUT IT THE CHECK BELOW IS DECORATIVE. Counting
    # campaigns is a read, and a read under READ COMMITTED proves nothing about the
    # instant after it: a campaign launch that had already read this agent as `live`
    # commits its `status = 'running'` a moment later and the count never saw it. Measured,
    # not theorised — two interleaved transactions produced
    # `OUTCOME agent='archived' campaign='running'`, which is precisely the zombie this
    # function's docstring says it refuses to manufacture.
    #
    # `FOR UPDATE` here conflicts with the `FOR SHARE` that
    # `agents/lifecycle.hold_agent_for_campaign_start` takes on the two paths that write
    # `campaigns.status = 'running'`, so the two orders both end consistently: a launch in
    # flight makes this block until it commits, and the count then runs on a NEW snapshot
    # (per-statement, READ COMMITTED) and sees the running campaign it must refuse; an
    # archive in flight makes the launch block and read `archived`, which its own gate
    # names. EITHER HALF ALONE IS A NO-OP — a lock nobody conflicts with is a lock.
    #
    # Archive is the mover that did not take this, while `activate`, `deactivate` and
    # `restore` all did; taking it here also makes `agents` the FIRST row every one of
    # these paths locks, which is what keeps the ordering deadlock-free against
    # `update_agent` (agents → engine) and `launch_campaign` (agents → campaigns).
    await _locked_status(session, agent_id)
    await _assert_no_campaign_is_dialling(session, agent_id=agent_id)
    moved = await transition_status(
        session,
        table="agents",
        entity="Agent",
        row_id=agent_id,
        to_status="archived",
        from_statuses=_sources_for("archive"),
        extra_set="archived_at = now()",
        visible_where=_VISIBLE,
    )
    released = await _release_inbound_numbers(session, agent_id=agent_id) if moved else 0
    return LifecycleResult(
        agent_id=agent_id, status="archived", changed=moved, numbers_released=released
    )


async def restore_agent(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID
) -> LifecycleResult:
    """Bring an agent back out of the archive: `archived` → `paused`.

    INACTIVE, NOT ACTIVE, and the edge is argued at `AGENT_TRANSITIONS`: an agent that sat
    retired has no proof left that the engine still holds its configuration, and the only
    thing that can establish one is a publish with its read-back. The owner activates it
    next, deliberately.

    A RESTORE OF AN AGENT THAT IS NOT ARCHIVED IS REFUSED BY NAME, and this is the one
    refusal in the module that could not be left to the transition primitive. `restore` and
    `deactivate` share a target, so the primitive's own wording for a live agent is "cannot
    move from live to paused" — a sentence that describes the move deactivate makes every
    day, offered to somebody who pressed Restore. Worse, that move is one this function
    does not do the work for: it releases no numbers, so applying it would leave our record
    saying `paused` while the voice platform went on answering the agent's lines. So the
    state is read under the row lock and anything but `archived` (or `paused`, which is the
    intent already holding) is a conflict that says what to press instead.
    """
    del tenant_id
    status = await _locked_status(session, agent_id)
    if status not in ("archived", "paused"):
        raise ProblemError.conflict(
            "agent_not_archived",
            f"This agent is {status}, not archived, so there is nothing to restore.",
            remediation=(
                "Restore only brings an agent back out of the archive. To take a live "
                "agent off the frontline, use Deactivate."
            ),
        )
    moved = await transition_status(
        session,
        table="agents",
        entity="Agent",
        row_id=agent_id,
        to_status="paused",
        from_statuses=_sources_for("restore"),
        # Cleared in the SAME statement that moves the status: the CHECK forbids a
        # non-archived row carrying an archival timestamp, so this is not tidiness.
        extra_set="archived_at = NULL",
        visible_where=_VISIBLE,
    )
    return LifecycleResult(agent_id=agent_id, status="paused", changed=moved, numbers_released=0)


async def assert_assignable(session: AsyncSession, agent_id: UUID) -> None:
    """Refuse an ARCHIVED agent as the subject of a campaign (the founder's rule).

    Called AFTER `db.ownership.assert_visible`, which is the tenancy question and answers
    404 for a neighbour's id; this is the lifecycle question and answers 409 for one of the
    caller's own. Splitting them keeps "not yours" and "retired" from collapsing into one
    message that is wrong for both.

    Everything except `archived` passes — see `ASSIGNABLE_STATUSES` for why a draft agent is
    deliberately still assignable and where its launch is refused instead.
    """
    status = (
        await session.execute(
            text("SELECT status FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).scalar()
    if status is None:
        raise ProblemError.not_found("Agent")
    if str(status) not in ASSIGNABLE_STATUSES:
        raise _archived_refusal("used by a campaign")


async def hold_agent_for_campaign_start(session: AsyncSession, agent_id: UUID) -> None:
    """Hold this agent's row in SHARE mode until the caller's transaction ends.

    THE OTHER HALF OF `archive_agent`'S CAMPAIGN CHECK, and neither half works alone.
    `_assert_no_campaign_is_dialling` counts running and scheduled campaigns before it
    retires an agent; a campaign start reads the agent's status before it writes
    `running`. Both are reads, so under READ COMMITTED they interleave cleanly and the
    pair commits a state neither would have allowed: an `archived` agent with a `running`
    campaign, which the dispatcher then refuses contact by contact for ever while the
    client's screen says "running". Measured on two real transactions, not reasoned about.

    A LOCK AND NOT A RULE, deliberately. The rule is `assert_assignable` (the founder's
    "an archived agent is never assignable") and `launch_blockers`' `agent_archived`, and
    both already say the right sentence to the right person — a second refusal here would
    be a second wording of one rule, and `launch_blockers` is deliberately exhaustive
    rather than fail-fast, so raising from a lock would collapse its list into one 409.
    This function's whole job is to make those existing answers TRUE at the moment they
    are given.

    `FOR SHARE` and not `FOR UPDATE`: two campaigns starting against one agent do not
    conflict with each other and must not serialise, while `archive_agent`'s `FOR UPDATE`
    conflicts with both. `NOWAIT` is deliberately not used — the correct behaviour of a
    launch that meets an archive in flight is to WAIT and then be refused by name, not to
    fail with a lock error the client cannot act on.

    No row is a no-op, not a 404: whether this agent exists is the caller's own question
    and every caller already asks it (`assert_assignable`, `launch_blockers`'
    `agent_missing`). Answering it twice, in two vocabularies, is the drift this avoids.

    THE COST, stated because it is real: the agent row stays share-locked for the rest of
    the launch transaction, which includes the DNC scrub over `campaign_contacts`. An
    archive, deactivate or publish of that agent waits for it. That is the correct
    behaviour — retiring an agent halfway through its own campaign launch is the thing
    being prevented — and it is bounded by a transaction that already had to finish.
    """
    await session.execute(
        text("SELECT 1 FROM agents WHERE id = :aid AND deleted_at IS NULL FOR SHARE"),
        {"aid": agent_id},
    )


async def _assert_no_campaign_is_dialling(session: AsyncSession, *, agent_id: UUID) -> None:
    """Refuse to retire an agent a live campaign is still working through.

    `running` and `scheduled` only. A `draft` campaign has dialled nobody and a
    `completed`/`cancelled` one is finished, so neither can produce the zombie above; a
    `scheduled` campaign is counted because it fires through the same launch path at its
    start time and would then become a running one nobody can explain.

    A `PAUSED` CAMPAIGN IS THE ONE THAT NEEDED A SECOND GUARD, NOT A WIDER ONE HERE. It has
    stopped, so archiving over it is right — but Resume is a bare CAS with no gate, so
    "pause the campaign, archive the agent, press Resume" reached the same zombie through a
    different door. Counting paused campaigns here would have closed it by making an agent
    with one abandoned campaign unretirable for ever, which is the worse trade;
    `campaigns/service.assert_agent_still_assignable` closes it at the resume instead, with
    the client's two real remedies named (D-440).
    """
    blocking = (
        await session.execute(
            text(
                "SELECT count(*) FROM campaigns "
                "WHERE agent_id = :aid AND status IN ('running', 'scheduled')"
            ),
            {"aid": agent_id},
        )
    ).scalar()
    if blocking:
        raise ProblemError.conflict(
            "agent_has_active_campaigns",
            f"This agent is still being used by {blocking} running or scheduled "
            "campaign(s), so it cannot be archived.",
            remediation=(
                "Pause or cancel those campaigns first — or switch the agent off with "
                "Deactivate, which stops it immediately and keeps it restorable."
            ),
        )


async def _locked_status(session: AsyncSession, agent_id: UUID) -> str:
    """This agent's status under a row lock, or a 404 — the read every mover starts from.

    `FOR UPDATE` for `_load_agent`'s reason: activate reads a status and then publishes,
    which is a read-then-write over `engine_agent_ref`, and two of them interleaving
    manufacture an orphan agent at the vendor that we are billed for and cannot address.
    """
    row = (
        await session.execute(
            text("SELECT status FROM agents WHERE id = :aid AND deleted_at IS NULL FOR UPDATE"),
            {"aid": agent_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Agent")
    return str(row[0])


async def _release_inbound_numbers(session: AsyncSession, *, agent_id: UUID) -> int:
    """Tell the engine this agent answers nothing, and report how many numbers moved.

    Through `route_inbound_numbers` rather than a loop of its own: that function already
    owns the capability check, the per-number alarm and the hard-rule-6 logging, and a
    second implementation of "stop answering" is the copy that would miss one of the three.
    `answers=False` is the release arm it was built with — an agent republished as
    `outbound` uses the same path for the same reason.

    A failure here alarms and does NOT undo the transition, which is `route_inbound_numbers`'
    own contract: the client asked for this agent to be off, our record says it is off, and
    a named alarm per number tells an operator exactly which line is still answering. What
    is not acceptable is neither, which is what happened before this call existed.
    """
    ref = (
        await session.execute(
            text("SELECT engine_agent_ref FROM agents WHERE id = :aid"), {"aid": agent_id}
        )
    ).scalar()
    if not ref:
        # Never published: the engine holds nothing for this agent and no number can be
        # bound to it, so there is nothing to release and no vendor call worth making.
        return 0
    routing = await route_inbound_numbers(
        session, get_engine(), agent_id=agent_id, ref=str(ref), answers=False
    )
    return routing.released


def _archived_refusal(verb: str) -> ProblemError:
    """One wording for every place an archived agent is refused.

    Deliberately not a count: the number has already changed once (D-440's deactivate arm),
    and a count in prose is the defect class D-103/D-105 exist for.
    """
    return ProblemError.conflict(
        "agent_archived",
        f"This agent is archived, so it cannot be {verb}.",
        remediation="Restore the agent first, then try again.",
    )


__all__ = [
    "AGENT_TRANSITIONS",
    "ASSIGNABLE_STATUSES",
    "LifecycleResult",
    "activate_agent",
    "archive_agent",
    "assert_assignable",
    "create_agent",
    "deactivate_agent",
    "hold_agent_for_campaign_start",
    "restore_agent",
    "update_agent",
]
