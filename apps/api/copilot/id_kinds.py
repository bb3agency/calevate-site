"""What an id handed to a Pip tool actually names in this account, and the one way a wrong
id is turned into something the model can fix (founder, 24 Nov 2026).

A model that puts a campaign's id in `agent_id` gets a not-found from the service under the
tool. Relayed as it stands ("Agent not found"), that is a dead end for a request that was
never impossible: the model is told a fact it cannot argue with and gives up, and the person
reads a raw title. So every id argument of the call is looked up here across the account's
own objects and the model is told what each one names, with the way back (a campaign's
agent, a call's lead), and tries again in the same run.

Three moments reach this module, and they differ only in what a not-found can mean:
- **planning** (`plan_correctably`): a planner only reads, and every id it reads came from
  the model, so ANY not-found or validation problem there is the model's to fix;
- **running** an action (`service._tool_problem`) and **reading** (`tools.run_read_tool`):
  a not-found may be a fact (the object went away), so it is corrected only when no id the
  model passed is of the missing kind (`correction_in`);
- a read tool that resolves its own id (`unread_id`).

An argument's NAME is a hint, not the truth: `line_id` is a forwarded line on the numbers
screen and an Inbound line on an agent's jobs, so `_EXPECTED` lists every kind a name takes.

Every lookup runs in the caller's tenant session, and every table here is FORCE-RLS'd
(`db/registry.TENANT_TABLES`; `id_kinds_test` pins it), so another account's id names
nothing here exactly as it names nothing to the tool. A platform-wide session is never
probed (`probe=False`). Lead, call and phone-number rows are never named, only counted as a
kind: their labels are personal data (hard rule 6).

The person-facing sentences for all of this live here too (`WRONG_ITEM_PLAIN`,
`problem_plain`, `person_safe`), so a step's line and the closing reason say one thing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.actions import Plan, WriteRefusedError
from apps.api.copilot.owner_words import machine_words
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session


@dataclass(frozen=True, slots=True)
class Kind:
    key: str
    #: How a person and a not-found title name it ("Inbound line not found").
    noun: str
    #: Read by `_IDENTIFY_SQL`; `id_kinds_test` holds the two to the same set of tables.
    table: str
    #: Other spellings of the noun that services raise not-founds under.
    aliases: tuple[str, ...] = ()
    #: The read that lists ids of this kind, named so the model knows where to look.
    listed_by: str | None = None


KINDS: Final[tuple[Kind, ...]] = (
    Kind("agent", "agent", "agents", listed_by="`agents_list`"),
    Kind("campaign", "campaign", "campaigns", listed_by="`campaigns_list`"),
    Kind("inbound_line", "Inbound line", "inbound_lines", listed_by="`agent_detail`"),
    Kind("lead", "lead", "leads", listed_by="`leads_search`"),
    Kind("call", "call", "calls", listed_by="`calls_recent`"),
    Kind(
        "knowledge_source",
        "knowledge source",
        "kb_sources",
        ("source",),
        listed_by="`knowledge_sources`",
    ),
    Kind(
        "phone_number",
        "phone number",
        "phone_numbers",
        ("number", "calevate number"),
        listed_by="`numbers_list`",
    ),
    Kind("forwarded_line", "forwarded line", "forwarded_lines", listed_by="`numbers_list`"),
    Kind("follow_up", "follow-up", "follow_ups", listed_by="`follow_ups_list`"),
    Kind(
        "callback",
        "call-back",
        "scheduled_callbacks",
        ("callback",),
        listed_by="`callbacks_list`",
    ),
    Kind("held_lead", "held lead", "lead_call_holds", listed_by="`integrations_status`"),
    Kind("routine", "routine", "copilot_routines", listed_by="`routines_list`"),
    Kind("lead_source", "lead source", "inbound_webhooks"),
)

_BY_KEY: Final = {kind.key: kind for kind in KINDS}

#: The kinds each argument name takes. A name absent here is still identified; it simply
#: has no expected kind to compare against.
_EXPECTED: Final[dict[str, frozenset[str]]] = {
    "agent_id": frozenset({"agent"}),
    "campaign_id": frozenset({"campaign"}),
    "lead_id": frozenset({"lead"}),
    "lead_ids": frozenset({"lead"}),
    "call_id": frozenset({"call"}),
    "callback_id": frozenset({"callback"}),
    "callback_ids": frozenset({"callback"}),
    "hold_id": frozenset({"held_lead"}),
    "follow_up_id": frozenset({"follow_up"}),
    "number_id": frozenset({"phone_number"}),
    "source_id": frozenset({"knowledge_source"}),
    "routine_id": frozenset({"routine"}),
    "lead_source_id": frozenset({"lead_source"}),
    "job_id": frozenset({"campaign", "inbound_line"}),
    "holder_id": frozenset({"campaign", "inbound_line"}),
    "line_id": frozenset({"inbound_line", "forwarded_line"}),
}

#: One statement for every kind; ids are uuid7 across all tables, so at most one row
#: answers. Written out rather than generated from `KINDS` so `check_raw_sql` can read every
#: character of it. A label is selected only where it is a business's own name (an agent,
#: campaign, line, source, follow-up): a lead's, a call's or a number's would be personal
#: data. Soft-deleted and released rows count as gone, and so does a deleted agent or lead
#: a row points back to; archived rows are reported as such, because an archived object
#: refuses changes.
_IDENTIFY_SQL: Final = (
    "SELECT 'agent' AS kind, CAST(o.name AS text) AS label, o.archived_at IS NOT NULL "
    "AS archived, NULL::uuid AS agent_id, NULL::uuid AS lead_id FROM agents o "
    "WHERE o.id = :oid AND o.deleted_at IS NULL "
    "UNION ALL SELECT 'campaign', CAST(o.name AS text), o.archived_at IS NOT NULL, a.id, "
    "NULL FROM campaigns o "
    "LEFT JOIN agents a ON a.id = o.agent_id AND a.deleted_at IS NULL WHERE o.id = :oid "
    "UNION ALL SELECT 'inbound_line', CAST(o.name AS text), o.archived_at IS NOT NULL, "
    "a.id, NULL FROM inbound_lines o "
    "LEFT JOIN agents a ON a.id = o.agent_id AND a.deleted_at IS NULL WHERE o.id = :oid "
    "UNION ALL SELECT 'lead', NULL, false, NULL, NULL FROM leads "
    "WHERE id = :oid AND deleted_at IS NULL "
    "UNION ALL SELECT 'call', NULL, false, a.id, l.id FROM calls o "
    "LEFT JOIN agents a ON a.id = o.agent_id AND a.deleted_at IS NULL "
    "LEFT JOIN leads l ON l.id = o.lead_id AND l.deleted_at IS NULL WHERE o.id = :oid "
    "UNION ALL SELECT 'knowledge_source', CAST(name AS text), false, NULL, NULL "
    "FROM kb_sources WHERE id = :oid "
    "UNION ALL SELECT 'phone_number', NULL, false, a.id, NULL FROM phone_numbers o "
    "LEFT JOIN agents a ON a.id = o.agent_id AND a.deleted_at IS NULL "
    "WHERE o.id = :oid AND o.released_at IS NULL "
    "UNION ALL SELECT 'forwarded_line', NULL, false, NULL, NULL FROM forwarded_lines "
    "WHERE id = :oid "
    "UNION ALL SELECT 'follow_up', CAST(name AS text), false, NULL, NULL FROM follow_ups "
    "WHERE id = :oid "
    "UNION ALL SELECT 'callback', NULL, false, a.id, l.id FROM scheduled_callbacks o "
    "LEFT JOIN agents a ON a.id = o.agent_id AND a.deleted_at IS NULL "
    "LEFT JOIN leads l ON l.id = o.lead_id AND l.deleted_at IS NULL WHERE o.id = :oid "
    "UNION ALL SELECT 'held_lead', NULL, false, a.id, l.id FROM lead_call_holds o "
    "LEFT JOIN agents a ON a.id = o.agent_id AND a.deleted_at IS NULL "
    "LEFT JOIN leads l ON l.id = o.lead_id AND l.deleted_at IS NULL WHERE o.id = :oid "
    "UNION ALL SELECT 'routine', NULL, false, NULL, NULL FROM copilot_routines "
    "WHERE id = :oid "
    "UNION ALL SELECT 'lead_source', NULL, false, NULL, NULL FROM inbound_webhooks "
    "WHERE id = :oid"
)

_LABEL_CHARS: Final = 60


@dataclass(frozen=True, slots=True)
class Found:
    kind: Kind
    label: str | None
    archived: bool
    #: The agent that speaks for it (a campaign's, a line's, a call's), when it has one.
    agent_id: UUID | None
    #: The lead it is about (a call's, a call-back's, a hold's).
    lead_id: UUID | None


async def identify(session: AsyncSession, value: UUID) -> Found | None:
    """What `value` names in the session's account, or None."""
    row = (await session.execute(text(_IDENTIFY_SQL), {"oid": value})).first()
    if row is None:
        return None
    return Found(
        kind=_BY_KEY[str(row.kind)],
        label=None if row.label is None else strip_invisible(str(row.label))[:_LABEL_CHARS],
        archived=bool(row.archived),
        agent_id=row.agent_id,
        lead_id=row.lead_id,
    )


def id_arguments(arguments: Mapping[str, Any]) -> list[tuple[str, UUID]]:
    """Every (argument, id) a call carries in a top-level `*_id` / `*_ids` argument. A value
    that is not a uuid is the tool's own parser's to refuse."""
    found: list[tuple[str, UUID]] = []
    for name, value in arguments.items():
        if not (name.endswith("_id") or name.endswith("_ids")):
            continue
        for item in value if isinstance(value, list) else [value]:
            if not isinstance(item, str):
                continue
            try:
                found.append((name, UUID(item)))
            except ValueError:
                continue
    return found


_NOT_FOUND_TITLE: Final = re.compile(r"^(?P<what>[A-Za-z][A-Za-z -]{0,40}) not found$")


def missing_noun(problem: ProblemError) -> str | None:
    """What a not-found says was missing ("agent"), when its title is the standard one."""
    if problem.kind != "not_found":
        return None
    matched = _NOT_FOUND_TITLE.match(problem.title.strip())
    return matched.group("what").lower() if matched else None


def _kind_named(noun: str) -> Kind | None:
    return next((k for k in KINDS if noun in (k.noun.lower(), *k.aliases)), None)


def _a(noun: str) -> str:
    return f"{'an' if noun[:1].lower() in 'aeiou' else 'a'} {noun}"


def describe(found: Found) -> str:
    """The object as the model reads it: "the archived campaign “Winter checkup”"."""
    said = f"the {'archived ' if found.archived else ''}{found.kind.noun}"
    return f"{said} “{found.label}”" if found.label else said


def _way_back(found: Found) -> str:
    """The ids that lead from `found` to what was probably meant: a job has one agent, a
    call one lead."""
    said = ""
    if found.agent_id is not None:
        said += f"; its agent is agent_id {found.agent_id}"
    if found.lead_id is not None:
        said += f"; its lead is lead_id {found.lead_id}"
    return said


def _where_listed(expected: frozenset[str]) -> str:
    for key in sorted(expected):
        if _BY_KEY[key].listed_by:
            return f"; take {_a(_BY_KEY[key].noun)} id from {_BY_KEY[key].listed_by}"
    return ""


def named_as(argument: str, found: Found | None, expected: frozenset[str] = frozenset()) -> str:
    """One sentence on what `argument` names: nothing, the expected kind, or another kind
    and the way back from it."""
    if found is None:
        return f"`{argument}` names nothing in this account{_where_listed(expected)}"
    said = f"`{argument}` is {describe(found)}"
    if found.kind.key in expected:
        return said
    if expected:
        said += ", not " + " or ".join(_a(_BY_KEY[key].noun) for key in sorted(expected))
    said += _way_back(found)
    if found.kind.key == "campaign" and "agent" in expected:
        said += (
            "; if the person means the campaign itself, use the campaign's own action "
            "with `campaign_id`"
        )
    return said


#: What the model is told after the sentences on each id, wherever the wrong id was caught.
_PUT_IT_RIGHT: Final = (
    ". An id works only in the argument for its own kind of object: put each one where "
    "this tool takes that kind, or use the related id given here, and call again now. An id "
    "that names nothing is not in this account: look it up again instead of reusing it, or "
    "ask the person which one they mean. Do not tell the person it does not exist"
)


async def correction_in(
    session: AsyncSession, tool: str, arguments: Mapping[str, Any], problem: ProblemError
) -> str | None:
    """What lets the model fix a not-found it caused while an action ran or a read was
    made, or None when the not-found is a fact it cannot change (or not a not-found)."""
    noun = missing_noun(problem)
    missing = None if noun is None else _kind_named(noun)
    # Only a kind this module can look up is judged: a not-found for anything else (a saved
    # view) cannot be told apart from a real absence here.
    if missing is None:
        return None
    passed = id_arguments(arguments)
    if not passed:
        return None
    seen = [(name, await identify(session, value)) for name, value in passed]
    if any(f is not None and f.kind == missing for _n, f in seen):
        # The id of the missing kind is real, so something else went missing.
        return None
    lines = [named_as(name, f, _EXPECTED.get(name, frozenset())) for name, f in seen]
    return f"no {noun} matched `{tool}`'s ids. " + "; ".join(lines) + _PUT_IT_RIGHT


async def correction(
    tenant_id: UUID | None, tool: str, raw_arguments: str, problem: ProblemError
) -> str | None:
    """`correction_in` under the account's own tenant session. None without an account (an
    operator with no client open has no account objects to name)."""
    if tenant_id is None or problem.kind != "not_found":
        return None
    try:
        arguments = json.loads(raw_arguments or "{}")
    except ValueError:
        return None
    if not isinstance(arguments, dict):
        return None
    async with tenant_session(tenant_id) as session:
        return await correction_in(session, tool, arguments, problem)


async def unread_id(session: AsyncSession, argument: str, value: UUID) -> str:
    """What a READ tool answers when its `argument` names nothing it can read: what the id
    is, if anything, and where the right one comes from. Never "it does not exist" alone:
    the model relayed that as fact for an object on the person's screen."""
    expected = _EXPECTED.get(argument, frozenset())
    found = await identify(session, value)
    if found is not None and found.kind.key in expected:
        return (
            f"`{argument}` is {describe(found)}, which this lookup cannot read (it may be "
            "archived or deleted). Tell the person its state; do not say it does not exist."
        )
    if found is None:
        # The same sentence for another account's id: no existence oracle across accounts.
        listed = _where_listed(expected).removeprefix("; take ")
        take = f" Take {listed}." if listed else ""
        return f"`{argument}` names nothing in this account.{take} Ask the person if unsure."
    return f"{named_as(argument, found, expected)}. Call again with the right id."


# --- planning -----------------------------------------------------------------------------


async def _plan_not_found_reason(
    session: AsyncSession | None, problem: ProblemError, args: Mapping[str, Any]
) -> str:
    passed = id_arguments(args)
    if session is None:
        keys = ", ".join(f"`{name}`" for name, _ in passed) or "an id"
        return (
            f"{problem.title}: {keys} does not name what this action takes. Take the id from "
            "the lookup that lists it and call again, or ask the operator which one they mean"
        )
    wrong: list[str] = []
    right: list[str] = []
    for name, value in passed:
        expected = _EXPECTED.get(name, frozenset())
        found = await identify(session, value)
        if found is not None and (not expected or found.kind.key in expected):
            right.append(f"`{name}` ({describe(found)})")
        else:
            wrong.append(named_as(name, found, expected))
    if not wrong and right:
        # Every id names the right kind of thing, so the planner filtered it out: it is in
        # a state this action does not take (archived, cancelled, already settled).
        return (
            f"{problem.title} for this action, although "
            + ", ".join(right)
            + " exists: it is in a state this action does not take. Read it (its detail "
            "tool or the SCREEN STATE) and tell the person its state and what they can do "
            "instead; do not say it does not exist"
        )
    return "; ".join(wrong or [problem.title]) + _PUT_IT_RIGHT


def _validation_reason(problem: ProblemError) -> str:
    parts = [f"{problem.title}: {problem.detail}"]
    if problem.fields:
        parts.append(" ".join(str(entry.get("message", "")) for entry in problem.fields[:8]))
    if problem.remediation:
        parts.append(problem.remediation)
    parts.append("Change that argument and call again, or ask the person for a value that fits")
    return " ".join(part for part in parts if part)


async def correctable(
    session: AsyncSession | None, problem: ProblemError, args: Mapping[str, Any]
) -> WriteRefusedError | None:
    """The refusal to raise instead of a planner's `problem`, or None when it is a fact the
    model must relay (a conflict or a business rule is about the account, not the call).
    `session` is the planner's own tenant-scoped one; `None` skips the lookup, for a
    platform-wide session in which RLS would not hide another account."""
    if problem.kind == "not_found":
        return WriteRefusedError(
            await _plan_not_found_reason(session, problem, args), plain=WRONG_ITEM_PLAIN
        )
    if problem.kind == "validation":
        return WriteRefusedError(_validation_reason(problem), plain=problem_plain(problem))
    return None


async def plan_correctably[A](
    planner: Callable[[AsyncSession, A, Mapping[str, Any]], Awaitable[Plan]],
    session: AsyncSession,
    actor: A,
    args: Mapping[str, Any],
    *,
    probe: bool = True,
) -> Plan:
    """THE way a model's call is planned: `planner`, with a model-caused `ProblemError`
    turned into the refusal it can correct (`correctable`). `probe=False` for a
    platform-wide session. `copilot/tool_refusals_test.py` holds every model-facing call
    site to this function. Only the planning call is wrapped: a not-found at Confirm means
    the object went away in between, which is the platform's answer to relay."""
    try:
        return await planner(session, actor, args)
    except ProblemError as problem:
        refusal = await correctable(session if probe else None, problem, args)
        if refusal is None:
            raise
        raise refusal from problem


# --- what the person reads ---------------------------------------------------------------

#: A step whose id the model is told how to fix; seen only when no retry succeeds, so it
#: is also the closing reason (`service.exhausted_text` does not say "nothing" twice).
WRONG_ITEM_PLAIN: Final = "That pointed at the wrong item, so nothing changed."
#: For a refusal whose own words cannot be shown.
UNSHOWABLE_PLAIN: Final = "This could not be done from here"

_UUID: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def problem_plain(problem: ProblemError) -> str:
    """A platform refusal as the person reads it, without a full stop (it is joined into a
    sentence). Never the raw title: "Agent not found" reads as a fault in the product, and
    a not-found's own detail ("We could not find that agent") is wrong when the agent is
    there and the model asked for it by the wrong id."""
    noun = missing_noun(problem)
    if problem.kind == "not_found":
        if noun is None:
            return "I could not find what that needs. Check it still exists, then ask again"
        return f"That {noun} could not be found. Check it still exists, then ask again"
    said = strip_invisible(" ".join(problem.detail.split())).rstrip(".")
    if not said or _UUID.search(said) or machine_words(said):
        return UNSHOWABLE_PLAIN
    return said


def person_safe(text_: str) -> bool:
    """Whether `text_` can reach a person: no ids, no machinery, no raw not-found title."""
    return not (
        _UUID.search(text_)
        or machine_words(text_)
        or re.search(r"\b[A-Z][a-z -]* not found\b", text_)
    )


__all__ = [
    "KINDS",
    "UNSHOWABLE_PLAIN",
    "WRONG_ITEM_PLAIN",
    "Found",
    "Kind",
    "correctable",
    "correction",
    "correction_in",
    "describe",
    "id_arguments",
    "identify",
    "missing_noun",
    "named_as",
    "person_safe",
    "plan_correctably",
    "problem_plain",
    "unread_id",
]
