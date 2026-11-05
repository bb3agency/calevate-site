"""`agent_settings`: one agent's set-up, a part at a time, for Pip's agent actions (D-893 L4).

One read with a `part` rather than five tools, so the cached prefix grows by one schema.
Each part reads what its screen reads, through the same services:

* `settings` — the Settings tab: how it sounds, how it handles a call, the longest call, the
  AI model and caller memory, each with the value in force.
* `script` — the Script tab: the whole script it shows (the autosaved working copy when there
  is one, else the saved version), whether callers hear it, and the versions.
* `handover` — the Hand-over list by name, and the business contacts that may be added.
  Never a phone number: they are staff mobiles (hard rule 6), and Pip names people.
* `actions` — the Actions tab: the master switch, each action, and the connections made.
* `lead_fields` — what it writes down, the suggestions waiting, and the account's draft.
* `tests` and `mistakes` — the Training tab's latest practice test run and the mistakes
  found on real calls, which Pip had no read for before.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final
from uuid import UUID

from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    HAND_OVER,
    STANDARD_VARIABLES,
    CallScript,
    ConversationStage,
    extract_variable_names,
    substitute_variables,
    upgrade_to_v2,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import credentials as action_credentials
from apps.api.actions import service as actions_service
from apps.api.actions.calendar import calendar_configured
from apps.api.agents import (
    call_handling,
    call_mistakes,
    field_suggestions,
    script_builder,
    test_conversations,
    trial_results,
    voice_tuning,
)
from apps.api.agents import handoff as handoff_service
from apps.api.agents import lead_fields as lead_fields_service
from apps.api.agents.business_fit import business_fit
from apps.api.agents.capability_manifest import books_visits
from apps.api.agents.llm_tiers import LLM_TIER_LABELS, tier_of_model
from apps.api.agents.models import CALL_CAP_DEFAULT_S
from apps.api.agents.script_edits import PART_LABELS
from apps.api.copilot.tools import ReadTool, ToolContext, _clean, ist_date
from apps.api.core.errors import ProblemError
from apps.api.db.ownership import assert_visible

#: Append only: the enum is part of the cacheable prefix.
PARTS: Final[tuple[str, ...]] = (
    "settings",
    "script",
    "handover",
    "actions",
    "lead_fields",
    "tests",
    "mistakes",
)
#: Who fixes a practice test that did not pass (`trial_results.Owner`), in the Training
#: tab's terms.
_TEST_FIXED_BY: Final[dict[str, str]] = {
    "script": "a script change (`agent_tests_fix`)",
    "knowledge": "something the agent should know (`agent_tests_fix`)",
    "setting": "a setting",
    "platform": "Calevate, not the owner",
    "test": "the test itself is wrong",
}
#: The Training tab's words for a practice test verdict.
_VERDICTS: Final[dict[str, str]] = {"needs_fix": "needs a fix", "failed": "failed"}
#: The Training tab's words for a call-mistake state (`lib/api/callMistakes.ts`
#: `clientStateLine`). Each kind is a rule Calevate fixes, never the owner.
_MISTAKE_STATES: Final[dict[str, str]] = {
    "back": "seen again after our fix; our team has been told",
    "fixing": "not fixed yet; our team has been told",
    "fixed": "fixed, not seen since",
}
#: Versions listed in the `script` part; History on the Script tab pages the rest.
_VERSIONS_SHOWN: Final = 10
#: Characters of a hand-written script quoted; the 20,000 a raw script may hold would crowd
#: out the rest of the question, and the Script tab shows all of it.
_RAW_SHOWN: Final = 8000
#: Above this many characters a printed script is offered in two answers: a twelve-step
#: Telugu script can pass the answer's output ceiling (`service.MAX_ANSWER_TOKENS`) and be
#: cut off mid-step.
_PRINT_IN_PARTS: Final = 5000


def _on(value: object) -> str:
    return "on" if value else "off"


async def _settings_part(session: AsyncSession, agent_id: UUID) -> list[str]:
    voice = await voice_tuning.read_voice_tuning(session, agent_id)
    handling = await call_handling.read_agent_call_handling(session, agent_id)
    row = (
        await session.execute(
            text(
                "SELECT max_call_duration_s, llm_model, caller_memory_enabled, "
                "caller_has_screen FROM agents WHERE id = :aid"
            ),
            {"aid": agent_id},
        )
    ).one()
    tuning = voice.tuning
    values = handling.resolved.values
    sources = handling.resolved.sources
    tier = tier_of_model(row[1]) if row[1] else None
    lines = [
        "Voice: "
        + ("Studio" if voice.studio else "Clear (only speed applies)")
        + f"; speed {tuning.speed or 'default'}, volume {tuning.volume or 'default'}, "
        f"emotion {tuning.emotion or 'default'}.",
        "Call handling (value, and whose it is): "
        + "; ".join(
            f"{field} {getattr(values, field)} ({sources[field]})"
            for field in call_handling.SETTING_FIELDS
        )
        + f"; opening_waits_for_caller {_on(handling.opening_waits_for_caller)}.",
        "Longest call: "
        + (
            f"{int(row[0]) // 60} min"
            if row[0] is not None
            else f"default ({CALL_CAP_DEFAULT_S // 60} min)"
        )
        + f". AI model: {LLM_TIER_LABELS[tier] if tier else 'the account default'}."
        + f" Caller memory: {_on(row[2])}. caller_has_screen: {_on(row[3])}.",
    ]
    return lines


def _target(target: str, stages: Sequence[ConversationStage]) -> str:
    """A branch target in the Script tab's words (`sectionParts.ts::targetLabel`)."""
    if target == END_OF_CALL:
        return "End the call"
    if target == HAND_OVER:
        return "Hand to a person"
    if target == CALL_BACK:
        return "Offer a call back"
    for number, stage in enumerate(stages, 1):
        if stage.id == target:
            return f"{number}. {stage.name.strip()}"
    return "a step that is not there"


def _then(index: int, stages: Sequence[ConversationStage]) -> str:
    """Where a step goes when no branch holds (`sectionParts.ts::thenLabel`)."""
    stage = stages[index]
    if stage.otherwise:
        return _target(stage.otherwise, stages)
    if index + 1 < len(stages):
        return _target(stages[index + 1].id, stages)
    return "Wraps up the call"


def _step_lines(stages: Sequence[ConversationStage]) -> list[str]:
    lines = [f"Steps ({len(stages)}), in order, numbered and named as on the Script tab:"]
    for index, stage in enumerate(stages):
        lines.append(f"{index + 1}. {stage.name.strip()}: {' '.join(stage.instruction.split())}")
        if stage.mode == "say":
            lines.append("   Says it in exactly these words.")
        if stage.sounds_like.strip():
            lines.append(f"   Example line: “{' '.join(stage.sounds_like.split())}”")
        if stage.collect:
            lines.append(f"   Finds out: {', '.join(stage.collect)}.")
        lines.extend(
            f"   Small step {n}: {step.action}"
            + (f" (waits until: {step.wait_for})" if step.wait_for else "")
            for n, step in enumerate(stage.procedure, 1)
        )
        lines.extend(
            f"   When {branch.when.strip().rstrip('.')}: {_target(branch.target, stages)}."
            for branch in stage.branches
        )
        lines.append(f"   Then: {_then(index, stages)}.")
    return lines


def _style_lines(script: CallScript) -> list[str]:
    style = script.style
    said = [
        f"tone: {style.tone}" if style.tone.strip() else "",
        f"calls callers: {style.address_form}" if style.address_form.strip() else "",
        "phrases: " + "; ".join(f"“{p}”" for p in style.sample_phrases)
        if style.sample_phrases
        else "",
        "says words as: " + "; ".join(f"{p.word} as {p.say_as}" for p in style.pronunciations)
        if style.pronunciations
        else "",
    ]
    said = [part for part in said if part]
    return [f"How it speaks: {'; '.join(said)}."] if said else []


def script_text(script: CallScript, *, direction: str) -> list[str]:
    """The whole script as an owner reads it on the Script tab, in the tab's own labels
    (`agents/script_edits.PART_LABELS`, `scriptDiff.ts`), for Pip to print when asked.

    Steps keep their stored order and names, so the owner can name one back ("delete step
    5", "rename Satisfaction level") and the change Pip suggests targets that step.
    """
    labels = {
        **dict(STANDARD_VARIABLES),
        **{variable.key: variable.label for variable in script.variables},
    }
    return [_named_variables(line, labels) for line in _script_lines(script, direction)]


def _named_variables(line: str, labels: Mapping[str, str]) -> str:
    """`{{lead_name}}` as the Script tab shows it, `{Caller's name}`: the key is a code
    name, the label is the owner's."""
    names: dict[str, str | None] = {
        key: "{" + labels.get(key, key.replace("_", " ")) + "}"
        for key in extract_variable_names(line)
    }
    return substitute_variables(line, names, keep_unresolved=True) if names else line


def _script_lines(script: CallScript, direction: str) -> list[str]:
    if script.is_raw:
        body = script.raw_override or ""
        lines = ["A hand-written script (not in steps). Its text:", body[:_RAW_SHOWN]]
        if len(body) > _RAW_SHOWN:
            lines.append(
                f"(the first {_RAW_SHOWN} of {len(body)} characters; the rest is on the Script tab)"
            )
        return lines
    script = upgrade_to_v2(script)

    def part(key: str, value: str) -> list[str]:
        value = " ".join(value.split())
        return [f"{PART_LABELS[key]}: {value}"] if value else []

    lines = [
        *part("business_line", script.business_line),
        *part("identity", script.identity),
        *part("goal", script.goal),
        *part("outbound_purpose", script.outbound_purpose),
        *part("opening_line", script.opening_line),
    ]
    if direction == "both" and script.outbound_opening_line.strip():
        lines.append(
            f"Opening line when it calls: {' '.join(script.outbound_opening_line.split())}"
        )
    lines += _step_lines(script.stages) if script.stages else ["Steps: none yet."]
    lines += part("ending", script.ending)
    lines += _style_lines(script)
    lines += [f"When callers push back: “{o.objection}” → {o.response}" for o in script.objections]
    if script.example_exchange:
        lines.append("An example call:")
        lines += [
            f"   {'Caller' if turn.speaker == 'caller' else 'Agent'}: {turn.text}"
            for turn in script.example_exchange
        ]
    lines.append(
        "How closely it follows the steps: "
        + (
            "Follow the steps closely."
            if script.adherence == "strict"
            else "Use the steps as a guide."
        )
    )
    return lines


async def _script_part(session: AsyncSession, agent_id: UUID) -> list[str]:
    draft = await script_builder.read_draft(session, agent_id)
    loaded = await script_builder.load_agent_script(session, agent_id)
    row = (
        await session.execute(
            text(
                "SELECT a.status, a.direction, a.system_prompt_id IS DISTINCT FROM "
                "a.live_prompt_id AND a.live_prompt_id IS NOT NULL, lv.version "
                "FROM agents a LEFT JOIN prompt_versions lv ON lv.id = a.live_prompt_id "
                "WHERE a.id = :aid"
            ),
            {"aid": agent_id},
        )
    ).one()
    status, direction, pending, live_version = row
    heard = (
        f"callers hear version {live_version}"
        if live_version is not None
        else "callers hear none of it yet: it has never been put live"
    )
    if status != "live" and live_version is not None:
        heard += f", and only once the agent is on again (it is {status})"
    if draft is not None:
        state = (
            f"The Script tab shows a working copy saved {ist_date(draft.saved_at)} that is NOT "
            f"live; {heard}. To make it live: `agent_script_put_live`."
        )
        shown = draft.script
    elif loaded.version is None:
        return ["This agent has no script written yet."]
    elif pending:
        state = (
            f"The Script tab shows version {loaded.version}, saved and waiting to go live; "
            f"{heard} (`agent_changes_apply` / `agent_script_discard`)."
        )
        shown = loaded.script
    else:
        state = f"The Script tab shows version {loaded.version}; {heard}."
        shown = loaded.script
    body = script_text(shown, direction=str(direction))
    lines = [state, "--- the script ---", *body, "--- end of the script ---"]
    if sum(len(line) for line in body) > _PRINT_IN_PARTS:
        lines.append(
            "This is long: asked to print it, print it up to the end of the steps, then "
            "offer the rest."
        )
    versions = await script_builder.list_versions(session, agent_id, limit=_VERSIONS_SHOWN)
    lines.append("Versions, newest first:")
    lines.extend(
        f"- {v.version}{' (callers hear this)' if v.is_live else ''}: "
        f"{v.summary or 'no note'}, {ist_date(v.created_at)}"
        for v in versions
    )
    return lines


async def _tests_part(session: AsyncSession, agent_id: UUID) -> list[str]:
    """The Training tab's latest practice test run (`test_conversations.latest_run`)."""
    run = await test_conversations.latest_run(session, agent_id)
    if run is None:
        return ["No practice tests have run for this agent yet (`agent_tests_run`)."]
    if run.status != "done":
        return [
            f"The latest practice test run, started {ist_date(run.created_at)}, is {run.status}."
        ]
    results = run.results
    passed = sum(1 for r in results if r.get("verdict") == "passed")
    lines = [
        f"Latest practice test run, {ist_date(run.completed_at or run.created_at)}: "
        f"{passed} of {len(results)} passed."
    ]
    for result in results:
        verdict = str(result.get("verdict"))
        if verdict not in _VERDICTS:
            continue
        owner = trial_results.result_owner(result)
        lines.append(
            f"- {result.get('title') or 'A test'}: {_VERDICTS[verdict]}"
            + (f", because {result['reason']}" if result.get("reason") else "")
            + (f". Fixed by {_TEST_FIXED_BY[owner]}" if owner in _TEST_FIXED_BY else "")
            + f". [key {result.get('key')}]"
        )
    return lines


async def _mistakes_part(session: AsyncSession, agent_id: UUID) -> list[str]:
    """The Training tab's call mistakes (`call_mistakes.agent_mistakes`), last 30 days."""
    mistakes = await call_mistakes.agent_mistakes(session, agent_id)
    if not mistakes:
        return [
            f"No mistakes found on this agent's calls in the last {call_mistakes.WINDOW_DAYS} days."
        ]
    lines = [f"Mistakes on real calls, last {call_mistakes.WINDOW_DAYS} days:"]
    lines.extend(
        f"- {m.label}: on {m.calls} call(s), last {ist_date(m.last_seen_at)}; "
        f"{_MISTAKE_STATES[m.state]}. What it should do: {m.instead}"
        for m in mistakes
    )
    return lines


async def _handover_part(session: AsyncSession, agent_id: UUID) -> list[str]:
    held = (
        await session.execute(
            text("SELECT handoff_enabled, handoff_trigger FROM agents WHERE id = :aid"),
            {"aid": agent_id},
        )
    ).one()
    roster = await handoff_service.roster(session, agent_id=agent_id)
    contacts = (
        await session.execute(text("SELECT id, label FROM business_contacts ORDER BY label"))
    ).all()
    lines = [
        f"Hand-over: {_on(held[0])}. When: "
        + (str(held[1]) if held[1] else handoff_service.HANDOFF_TRIGGER_DEFAULT),
        "On the list, in order: "
        + (
            "; ".join(
                f"{m.label} ({'on' if m.active else 'off for now'}) [contact_id {m.contact_id}]"
                for m in roster
            )
            or "nobody"
        ),
        "Business contacts who can be added: "
        + ("; ".join(f"{r[1]} [contact_id {r[0]}]" for r in contacts) or "none yet"),
        *await _team_alert_lines(session, agent_id),
    ]
    return lines


async def _team_alert_lines(session: AsyncSession, agent_id: UUID) -> list[str]:
    """Which calls this agent alerts about (D-904): the agent's rule and the keys and ids
    `agent_team_alert_set` and `team_alert_contact` take."""
    from apps.api.team_alerts import service as team_alerts

    view = await team_alerts.read_rule(session, agent_id=agent_id)
    rule = view.rule
    addresses = await team_alerts.list_contacts(session)
    return [
        "The alert list (the owner and every confirmed team address) hears from this agent "
        "about exactly these: outcomes "
        + (", ".join(rule.on_outcomes) or "none")
        + ("" if view.saved else " (not saved by the owner yet: every positive outcome)")
        + "; answers "
        + ("; ".join(f"{t.key}={'|'.join(t.values)}" for t in rule.on_fields) or "none")
        + f"; during the call {_on(rule.in_call)}"
        + ("." if view.in_call_live or not rule.in_call else ", once a team address is confirmed."),
        "Outcomes it can watch: "
        + (
            ", ".join(
                f"{o.label} ({o.key}{', makes the lead hot' if o.goal else ''})"
                for o in view.outcomes
            )
            or "none"
        ),
        "Answers it can watch: "
        + ("; ".join(f"{f.label} ({f.key}): {', '.join(f.values)}" for f in view.fields) or "none"),
        "Team addresses on the list: "
        + (
            "; ".join(
                f"{c.address} ({c.channel}"
                + ("" if c.verified else ", code not typed yet")
                + f") [team_contact_id {c.id}]"
                for c in addresses
            )
            or "none"
        ),
    ]


async def _actions_part(session: AsyncSession, agent_id: UUID) -> list[str]:
    enabled = await actions_service.actions_enabled(session, agent_id=agent_id)
    tools = await actions_service.list_tools(session, agent_id=agent_id)
    connections = await action_credentials.list_credentials(session)
    lines = [f"In-call actions are switched {_on(enabled)} for this agent."]
    lines.extend(
        f"- {t.name} ({t.kind}, {t.trigger}, {_on(t.enabled)}): {t.description[:200]} "
        f"[action_id {t.id}]"
        for t in tools
    )
    if not tools:
        lines.append("It has no actions yet.")
    lines.append(
        "Connections made (`connection_id`): "
        + ("; ".join(f"{c.label} ({c.kind}) [{c.id}]" for c in connections) or "none")
    )
    if await _calendar_would_help(session, agent_id, tools):
        # The readiness card's reminder (`agents/readiness.advice_for`), in Pip's words.
        lines.append(
            "No calendar is connected, and this agent places calls that book visits: you "
            "may suggest connecting one on its Actions tab so it offers times the business "
            "is really free."
        )
    return lines


async def _calendar_would_help(
    session: AsyncSession, agent_id: UUID, tools: list[actions_service.LoadedTool]
) -> bool:
    """D-945: only an agent that places calls and books visits, with no calendar on it."""
    if not calendar_configured() or any(
        t.kind == "calendar" and t.enabled and t.trigger == "during_call" for t in tools
    ):
        return False
    row = (
        await session.execute(
            text("SELECT direction, tenant_id FROM agents WHERE id = :a"), {"a": agent_id}
        )
    ).first()
    direction, tenant_id = (str(row[0]), row[1]) if row is not None else ("", None)
    script = upgrade_to_v2((await script_builder.load_agent_script(session, agent_id)).script)
    return books_visits(direction, script, await business_fit(session, tenant_id))


async def _lead_fields_part(
    session: AsyncSession, context: ToolContext, agent_id: UUID
) -> list[str]:
    fields = await field_suggestions.current_fields(session, agent_id)
    state = await field_suggestions.read_state(session, agent_id=agent_id)
    assert context.tenant_id is not None
    draft = await lead_fields_service.read_draft(session, tenant_id=context.tenant_id)
    lines = [
        "It writes down: "
        + (", ".join(f"{f.label} ({f.key})" for f in fields) or "no business details yet")
        + "."
    ]
    lines.extend(
        f"- suggestion {s.id}: {s.kind} {s.field_label} {', '.join(s.values)} — {s.reason}"
        for s in state.suggestions
    )
    if not state.suggestions:
        lines.append("No suggestions are waiting.")
    if draft is not None and draft.status == "done" and not draft.reviewed:
        lines.append(
            "A drafted set waits to be kept (`lead_fields_keep_draft`): "
            + ", ".join(f"{f.label} ({f.key})" for f in draft.fields)
        )
    return lines


async def _agent_settings(
    session: AsyncSession, context: ToolContext, args: Mapping[str, Any]
) -> str:
    try:
        agent_id = UUID(str(args.get("agent_id")))
    except ValueError:
        return (
            "`agent_id` was missing or is not an id. Take it from the SCREEN STATE or from "
            "an `agents_list` lookup, and call this again."
        )
    part = args.get("part")
    if part not in PARTS:
        return "`part` must be one of " + ", ".join(PARTS) + "."
    try:
        await assert_visible(session, "agent", agent_id)
    except ProblemError:
        return "No agent with that id in this account."
    if part == "settings":
        lines = await _settings_part(session, agent_id)
    elif part == "script":
        lines = await _script_part(session, agent_id)
    elif part == "handover":
        lines = await _handover_part(session, agent_id)
    elif part == "actions":
        lines = await _actions_part(session, agent_id)
    elif part == "tests":
        lines = await _tests_part(session, agent_id)
    elif part == "mistakes":
        lines = await _mistakes_part(session, agent_id)
    else:
        lines = await _lead_fields_part(session, context, agent_id)
    return _clean("\n".join(lines)) + f"\n[agent_id {agent_id}]"


AGENT_SETTINGS_READ: Final = ReadTool(
    name="agent_settings",
    description=(
        "One part of an agent's set-up: `settings` (voice, call handling, longest call, AI "
        "model, caller memory), `script` (the whole script, to show or print), `handover` "
        "(who it hands callers to, and contacts), `actions` (in-call actions and "
        "connections), `lead_fields` (what it writes down and suggestions), `tests` (latest "
        "practice "
        "tests) or `mistakes` (mistakes on real calls)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "The agent's id."},
            "part": {"type": "string", "enum": list(PARTS)},
        },
        "required": ["agent_id", "part"],
        "additionalProperties": False,
    },
    permission="agents:read",
    run=_agent_settings,
)

__all__ = ["AGENT_SETTINGS_READ", "PARTS", "script_text"]
