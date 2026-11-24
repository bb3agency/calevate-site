"""What an id handed to a Pip tool actually names in this account (founder, 24 Nov 2026).

A model that puts a campaign's id in `agent_id` gets a not-found from the service under the
tool. Reported as it stands ("Agent not found"), that is a dead end for a request that was
never impossible: the model is told a fact it cannot argue with and gives up, and the person
reads a raw title and advice that does not fit. So before a not-found is reported, each id
argument of the call is looked up here across the account's own objects. When none of them
names the kind of object that was not found, the model is told what each one does name and
tries again in the same run; when one does, the not-found is a fact about the world (the
object went away for some other reason) and is reported as before.

The kinds below are the ones Pip tools take ids for (`*_id` / `*_ids` in the tool schemas
and the not-found titles their services raise). An argument's NAME is not trusted to say
which kind it takes: `line_id` is a phone line in `account_actions` and an Inbound line
elsewhere, so the comparison is between what the service said was missing and what each id
really is.

Every lookup runs in the caller's tenant session, and every table here is FORCE-RLS'd
(`db/registry.TENANT_TABLES`; `id_kinds_test` pins it), so another account's id names
nothing here exactly as it names nothing to the tool. Lead, call and phone-number rows are
never named, only counted as a kind: their labels are personal data (hard rule 6).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
    #: Whether the row names the agent that speaks for it (a campaign's, a line's).
    has_agent: bool = False


KINDS: Final[tuple[Kind, ...]] = (
    Kind("agent", "agent", "agents"),
    Kind("campaign", "campaign", "campaigns", has_agent=True),
    Kind("inbound_line", "Inbound line", "inbound_lines", has_agent=True),
    Kind("lead", "lead", "leads"),
    Kind("call", "call", "calls"),
    Kind("knowledge_source", "knowledge source", "kb_sources", ("source",)),
    Kind("phone_number", "phone number", "phone_numbers", ("number", "calevate number")),
    Kind("follow_up", "follow-up", "follow_ups"),
    Kind("callback", "call-back", "scheduled_callbacks", ("callback",)),
    Kind("routine", "routine", "copilot_routines"),
    Kind("lead_source", "lead source", "inbound_webhooks"),
)

_BY_KEY: Final = {kind.key: kind for kind in KINDS}

#: One statement for every kind; ids are uuid7 across all tables, so at most one row
#: answers. Written out rather than generated from `KINDS` so `check_raw_sql` can read every
#: character of it. A label is selected only where it is a business's own name (an agent,
#: campaign, line, source, follow-up): a lead's, a call's or a number's would be personal
#: data. Soft-deleted and released rows count as gone; archived ones are reported as such,
#: because an archived object refuses changes.
_IDENTIFY_SQL: Final = (
    "SELECT 'agent' AS kind, CAST(o.name AS text) AS label, o.archived_at IS NOT NULL "
    "AS archived, NULL::uuid AS agent_id, NULL::text AS agent_name FROM agents o "
    "WHERE o.id = :oid AND o.deleted_at IS NULL "
    "UNION ALL SELECT 'campaign', CAST(o.name AS text), o.archived_at IS NOT NULL, "
    "o.agent_id, CAST(a.name AS text) FROM campaigns o "
    "LEFT JOIN agents a ON a.id = o.agent_id AND a.deleted_at IS NULL WHERE o.id = :oid "
    "UNION ALL SELECT 'inbound_line', CAST(o.name AS text), o.archived_at IS NOT NULL, "
    "o.agent_id, CAST(a.name AS text) FROM inbound_lines o "
    "LEFT JOIN agents a ON a.id = o.agent_id AND a.deleted_at IS NULL WHERE o.id = :oid "
    "UNION ALL SELECT 'lead', NULL, false, NULL, NULL FROM leads "
    "WHERE id = :oid AND deleted_at IS NULL "
    "UNION ALL SELECT 'call', NULL, false, NULL, NULL FROM calls WHERE id = :oid "
    "UNION ALL SELECT 'knowledge_source', CAST(name AS text), false, NULL, NULL "
    "FROM kb_sources WHERE id = :oid "
    "UNION ALL SELECT 'phone_number', NULL, false, NULL, NULL FROM phone_numbers "
    "WHERE id = :oid AND released_at IS NULL "
    "UNION ALL SELECT 'follow_up', CAST(name AS text), false, NULL, NULL FROM follow_ups "
    "WHERE id = :oid "
    "UNION ALL SELECT 'callback', NULL, false, NULL, NULL FROM scheduled_callbacks "
    "WHERE id = :oid "
    "UNION ALL SELECT 'routine', NULL, false, NULL, NULL FROM copilot_routines "
    "WHERE id = :oid "
    "UNION ALL SELECT 'lead_source', NULL, false, NULL, NULL FROM inbound_webhooks "
    "WHERE id = :oid"
)


@dataclass(frozen=True, slots=True)
class Found:
    kind: Kind
    label: str | None
    archived: bool
    agent_id: UUID | None
    agent_name: str | None


async def identify(session: AsyncSession, value: UUID) -> Found | None:
    """What `value` names in the session's account, or None."""
    row = (await session.execute(text(_IDENTIFY_SQL), {"oid": value})).first()
    if row is None:
        return None
    return Found(
        kind=_BY_KEY[str(row.kind)],
        label=None if row.label is None else strip_invisible(str(row.label)),
        archived=bool(row.archived),
        agent_id=row.agent_id,
        agent_name=None if row.agent_name is None else strip_invisible(str(row.agent_name)),
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


def _is(found: Found, noun: str) -> bool:
    return noun in (found.kind.noun.lower(), *found.kind.aliases)


def describe(found: Found) -> str:
    kind = found.kind
    said = f"the {'archived ' if found.archived else ''}{kind.noun}"
    if found.label:
        said += f" “{found.label}”"
    if kind.has_agent and found.agent_id is not None:
        agent = f" “{found.agent_name}”" if found.agent_name else ""
        said += f", whose agent{agent} has agent id {found.agent_id}"
    return said


async def correction_in(
    session: AsyncSession, tool: str, arguments: Mapping[str, Any], problem: ProblemError
) -> str | None:
    """The tool result that lets the model fix a not-found it caused, or None when the
    not-found is a fact it cannot change (or not a not-found at all)."""
    noun = missing_noun(problem)
    # Only a kind this module can look up is judged: a not-found for anything else (a
    # forwarded number, a saved view) cannot be told apart from a real absence here.
    if noun is None or not any(noun in (k.noun.lower(), *k.aliases) for k in KINDS):
        return None
    passed = id_arguments(arguments)
    if not passed:
        return None
    seen = [(name, value, await identify(session, value)) for name, value in passed]
    if any(f is not None and _is(f, noun) for _n, _v, f in seen):
        # The id of the missing kind is real, so something else went missing.
        return None
    what = f"no {noun} matched"
    lines = [
        f"`{name}` ({value}) is {describe(f)}"
        if f is not None
        else f"`{name}` ({value}) names nothing in this account"
        for name, value, f in seen
    ]
    return (
        f"NOT DONE, and nothing was changed: {what}. Here is what each id you passed names "
        f"in this account: {'; '.join(lines)}. An id works only in the argument for its own "
        f"kind of object: put each one where `{tool}` takes that kind, or use the related "
        "id given here, and call it again now. An id that names nothing is not in this "
        "account: look the object up again instead of reusing it, and if it is not there, "
        "tell the person it no longer exists. Do not tell the person about this mix-up."
    )


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


# --- what the person reads ---------------------------------------------------------------

#: A step whose id the model is told how to fix; seen only when no retry succeeds, so it
#: is also the closing reason.
WRONG_ITEM_PLAIN: Final = "I could not tell which one you meant. Ask again and name it"
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
    "correction",
    "correction_in",
    "describe",
    "id_arguments",
    "identify",
    "missing_noun",
    "person_safe",
    "problem_plain",
]
