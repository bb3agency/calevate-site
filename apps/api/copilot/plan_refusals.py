"""A planner's `ProblemError` that the MODEL caused, turned into a refusal it can correct.

A planner only reads, and every id it reads came from the model. So a `not_found` raised
while planning means the model named the wrong thing — a campaign's id where an agent's
goes, a call's where a lead's goes, a campaign this action does not take — and a
`validation` problem means it sent a value the service will not accept. Both are mistakes
the model can fix in its next call. Relayed as a `ProblemError` they are not: the loop
tells the model the platform refused and not to call again (`service._problem_result`),
which is how "rewrite this campaign's script" ended in "Agent not found" for an owner
looking at that campaign (24 Nov 2026).

Every other kind stays a `ProblemError`: a conflict or a business rule raised at plan time
is a fact about the account (a gate, a state) that the model must relay, not retry around.
A `not_found` raised AFTER the plan — at Confirm, when the object was deleted in between —
is also left alone; only the planning call is wrapped.

Under RLS an id from another account finds nothing in any table here, so it reads exactly
as an id that names nothing — the neighbour's object stays indistinguishable from absence.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.copilot.actions import Plan, WriteRefusedError
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.errors import ProblemError

#: What a refused wrong id shows the person. The model is told which id was wrong and
#: retries; the person needs only to know that nothing changed.
WRONG_ID_PLAIN: Final = "That pointed at the wrong item, so nothing changed."

#: What an argument key names. A key absent here is still probed; it simply has no
#: expected kind to compare against.
_EXPECTED: Final[dict[str, frozenset[str]]] = {
    "agent_id": frozenset({"agent"}),
    "campaign_id": frozenset({"campaign"}),
    "lead_id": frozenset({"lead"}),
    "call_id": frozenset({"call"}),
    "callback_id": frozenset({"call-back"}),
    "hold_id": frozenset({"held lead"}),
    "follow_up_id": frozenset({"follow-up"}),
    "number_id": frozenset({"phone number"}),
    "source_id": frozenset({"knowledge source"}),
    # A job is a campaign or an Inbound line; a line on the numbers screen is a forwarded
    # line and on an agent's jobs an Inbound line.
    "job_id": frozenset({"campaign", "inbound line"}),
    "line_id": frozenset({"inbound line", "forwarded line"}),
}

#: The read that lists ids of each kind, named so the model knows where to look.
_LISTED_BY: Final[dict[str, str]] = {
    "agent": "`agents_list`",
    "campaign": "`campaigns_list`",
    "inbound line": "`agent_detail`",
    "lead": "`leads_search`",
    "call": "`calls_recent`",
    "call-back": "`callbacks_list`",
    "held lead": "`integrations_status`",
    "follow-up": "`follow_ups_list`",
    "knowledge source": "`knowledge_sources`",
    "phone number": "`numbers_list`",
    "forwarded line": "`numbers_list`",
}

#: One round trip: which of the account's things this id names. Lead rows carry no label
#: — a lead's name is personal data and this reason reaches a prompt and the activity log
#: (hard rule 6); a campaign's or an agent's name is the business's own.
_PROBE_SQL: Final = """
SELECT 'agent' AS kind, name AS label, NULL::uuid AS agent_id, NULL::uuid AS lead_id
  FROM agents WHERE id = :id
UNION ALL SELECT 'campaign', name, agent_id, NULL FROM campaigns WHERE id = :id
UNION ALL SELECT 'inbound line', name, agent_id, NULL FROM inbound_lines WHERE id = :id
UNION ALL SELECT 'lead', NULL, NULL, id FROM leads WHERE id = :id
UNION ALL SELECT 'call', NULL, agent_id, lead_id FROM calls WHERE id = :id
UNION ALL SELECT 'call-back', NULL, agent_id, lead_id FROM scheduled_callbacks WHERE id = :id
UNION ALL SELECT 'held lead', NULL, agent_id, lead_id FROM lead_call_holds WHERE id = :id
UNION ALL SELECT 'follow-up', name, NULL, NULL FROM follow_ups WHERE id = :id
UNION ALL SELECT 'knowledge source', name, NULL, NULL FROM kb_sources WHERE id = :id
UNION ALL SELECT 'phone number', NULL, agent_id, NULL FROM phone_numbers WHERE id = :id
UNION ALL SELECT 'forwarded line', NULL, NULL, NULL FROM forwarded_lines WHERE id = :id
LIMIT 1
"""

_LABEL_CHARS: Final = 60


@dataclass(frozen=True, slots=True)
class _Named:
    kind: str
    label: str | None
    agent_id: UUID | None
    lead_id: UUID | None

    def described(self) -> str:
        return f"the {self.kind} “{self.label}”" if self.label else _a(self.kind)


async def _probe(session: AsyncSession, value: UUID) -> _Named | None:
    row = (await session.execute(text(_PROBE_SQL), {"id": value})).first()
    if row is None:
        return None
    label = None if row.label is None else strip_invisible(str(row.label))[:_LABEL_CHARS]
    return _Named(kind=str(row.kind), label=label, agent_id=row.agent_id, lead_id=row.lead_id)


def _uuid_args(args: Mapping[str, Any]) -> list[tuple[str, UUID]]:
    found: list[tuple[str, UUID]] = []
    for key, value in args.items():
        if not isinstance(value, str):
            continue
        try:
            found.append((key, UUID(value)))
        except ValueError:
            continue
    return found


def _a(noun: str) -> str:
    return f"{'an' if noun[:1] in 'aeiou' else 'a'} {noun}"


def _mismatch(key: str, expected: frozenset[str], named: _Named) -> str:
    wanted = " or ".join(_a(kind) for kind in sorted(expected)) or "what this takes"
    sentence = f"`{key}` is {named.described()}, not {wanted}"
    # The unambiguous way back: a job has one agent, a call one lead.
    if "agent" in expected and named.agent_id is not None:
        sentence += f"; its agent is agent_id {named.agent_id}"
    if "lead" in expected and named.lead_id is not None:
        sentence += f"; its lead is lead_id {named.lead_id}"
    if named.kind == "campaign" and "agent" in expected:
        sentence += (
            "; if the person means the campaign itself, use the campaign's own action "
            "with `campaign_id`"
        )
    return sentence


async def _not_found_reason(
    session: AsyncSession | None, problem: ProblemError, args: Mapping[str, Any]
) -> str:
    if session is None:
        keys = ", ".join(f"`{key}`" for key, _ in _uuid_args(args)) or "an id"
        return (
            f"{problem.title}: {keys} does not name what this action takes. Take the id from "
            "the lookup that lists it and call again, or ask the operator which one they mean"
        )
    sentences: list[str] = []
    right_kind: list[str] = []
    for key, value in _uuid_args(args):
        expected = _EXPECTED.get(key)
        named = await _probe(session, value)
        if named is None:
            where = (
                f"; take {_a(sorted(expected)[0])} id from {_LISTED_BY[sorted(expected)[0]]}"
                if expected
                else ""
            )
            sentences.append(f"`{key}` names nothing in this account{where}")
        elif expected is not None and named.kind not in expected:
            sentences.append(_mismatch(key, expected, named))
        else:
            right_kind.append(f"`{key}` ({named.described()})")
    if not sentences and right_kind:
        # Every id names the right kind of thing, so the planner filtered it out: it is in
        # a state this action does not take (archived, cancelled, already settled).
        return (
            f"{problem.title} for this action, although "
            + ", ".join(right_kind)
            + " exists: it is in a state this action does not take. Read it (its detail "
            "tool or the SCREEN STATE) and tell the person its state and what they can do "
            "instead; do not say it does not exist"
        )
    if not sentences:
        sentences.append(f"{problem.title}")
    return (
        "; ".join(sentences)
        + ". Call again with the right id, or ask the person which one they mean. Do not "
        "tell the person it does not exist"
    )


def _validation_reason(problem: ProblemError) -> str:
    parts = [f"{problem.title}: {problem.detail}"]
    if problem.fields:
        parts.append(" ".join(str(entry.get("message", "")) for entry in problem.fields[:8]))
    if problem.remediation:
        parts.append(problem.remediation)
    parts.append("Change that argument and call again, or ask the person for a value that fits")
    return " ".join(part for part in parts if part)


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
    site to this function."""
    try:
        return await planner(session, actor, args)
    except ProblemError as problem:
        refusal = await correctable(session if probe else None, problem, args)
        if refusal is None:
            raise
        raise refusal from problem


async def unread_id(session: AsyncSession, key: str, value: UUID) -> str:
    """What a READ tool answers when its `key` names nothing it can read: what the id is,
    if anything, and where the right one comes from. Never "it does not exist" alone — the
    model relayed that as fact for an object on the person's screen."""
    expected = _EXPECTED.get(key, frozenset())
    named = await _probe(session, value)
    if named is None:
        listed = (
            f" Take {_a(sorted(expected)[0])} id from {_LISTED_BY[sorted(expected)[0]]}."
            if expected
            else ""
        )
        return f"`{key}` names nothing in this account.{listed} Ask the person if unsure."
    if named.kind in expected:
        return (
            f"`{key}` is {named.described()}, which this lookup cannot read (it may be "
            "archived or deleted). Tell the person its state; do not say it does not exist."
        )
    return _mismatch(key, expected, named) + ". Call again with the right id."


async def correctable(
    session: AsyncSession | None, problem: ProblemError, args: Mapping[str, Any]
) -> WriteRefusedError | None:
    """The refusal to raise instead of `problem`, or None when `problem` is a fact the
    model must relay. `session` is the planner's own (tenant-scoped) one; `None` skips the
    probe, for a platform-wide session in which RLS would not hide another account."""
    if problem.kind == "not_found":
        return WriteRefusedError(
            await _not_found_reason(session, problem, args), plain=WRONG_ID_PLAIN
        )
    if problem.kind == "validation":
        return WriteRefusedError(_validation_reason(problem), plain=problem.detail)
    return None


__all__ = ["WRONG_ID_PLAIN", "correctable", "unread_id"]
