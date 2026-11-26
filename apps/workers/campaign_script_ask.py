"""The small requests and settings the holder script writer shares (D-992, D-997, D-1004):
the reading of a main task's numbered list as the call's steps, the owner's tones, the
holder's own settings as text, the room the engine leaves for a script, and the word-for-word
quote check the grounded writers use.

The words of each step are written by `workers/step_writer` against the plan
`agents/script_plan` builds; the whole-script asks, rules and review that used to live here
went with the one-pass writer (DESIGN §3, 26 Nov 2026).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import Any, Final, Literal

from apps.api.agents.owner_plan import OwnerPlan

#: The main task's numbered list read as the call's steps (founder, 26 Nov 2026: a first draft
#: must be as exact as a rewrite to a step list). A main task written as plain numbered
#: sentences gives `owner_plan` no names or outcomes, so the writer had only the items as
#: guidance and code could check nothing; one small pass names each item and states its
#: outcome, and code then holds the draft to that plan like an owner's own
#: (`script_writer.plan_for`). One step per item, so the reading can only label the
#: owner's list, never reshape it; code refuses any answer that does not keep the count.
TASK_STEPS_INSTRUCTION: Final = (
    "You read the numbered list in a business owner's main task for a phone call as the "
    "call's steps. Return one step per numbered item, in the same order: never merge two "
    "items, split one, drop one or add one. Keep each item's meaning, in plain English. "
    "`name` is 1 to 4 plain words naming the step. `does` says in one or two short sentences "
    "what the agent does in it, from the item's own words, keeping every case the item "
    "handles inside the step (if they have not done it, explain why; help them on each kind "
    "of device it names). `outcome` is one sentence saying what is true once the step is "
    "done, checkable "
    "from what the person says, so the call can move on. `ways_out` only where the item "
    "itself sends the call elsewhere: `when` names the case in a few words and `to` is "
    'another step\'s name, "end", or "call_back"; a call back only for someone who still '
    "cannot do something after being guided step by step. Most items have no ways out. "
    "Return ONLY JSON."
)
TASK_STEPS_MAX_TOKENS: Final = 1_500

_TASK_WAY: Final[dict[str, object]] = {
    "type": "object",
    "properties": {"when": {"type": "string"}, "to": {"type": "string"}},
    "required": ["when", "to"],
    "additionalProperties": False,
}
_TASK_STEP: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "does": {"type": "string"},
        "outcome": {"type": "string"},
        "ways_out": {"type": "array", "items": _TASK_WAY},
    },
    "required": ["name", "does", "outcome", "ways_out"],
    "additionalProperties": False,
}
TASK_STEPS_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "task_steps",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"steps": {"type": "array", "items": _TASK_STEP}},
            "required": ["steps"],
            "additionalProperties": False,
        },
    },
}


def task_steps_request(main_task: str, items: Sequence[str]) -> str:
    listed = "\n".join(f"{n}. {item}" for n, item in enumerate(items, 1))
    return f"MAIN TASK:\n{main_task.strip()}\nITS {len(items)} NUMBERED ITEMS:\n{listed}"


def _one_line(value: object, limit: int) -> str:
    # A colon would start a label of its own in the plan text `owner_plan` reads.
    text = " ".join(str(value).split()).replace(":", " -") if isinstance(value, str) else ""
    return text[:limit].strip()


def task_steps_text(raw: dict[str, Any]) -> str | None:
    """The answer as the owner-plan text form ("1. Name: what to do. Outcome: ...", a way out
    "   - When: go to "Step"."), for `owner_plan` to read like an owner's own list; None
    when it holds no step."""
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        return None
    lines: list[str] = []
    for n, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            return None
        name = " ".join(_one_line(step.get("name"), 60).split()[:4])
        does = _one_line(step.get("does"), 400).rstrip(".")
        outcome = _one_line(step.get("outcome"), 300).rstrip(".")
        if not (name and does and outcome):
            return None
        lines.append(f"{n}. {name}: {does}. Outcome: {outcome}.")
        for way in step.get("ways_out") or []:
            if not isinstance(way, dict):
                continue
            when = _one_line(way.get("when"), 120).rstrip(".")
            to = _one_line(way.get("to"), 60).strip("\"' ")
            if not when or not to:
                continue
            said = (
                "offer a call back"
                if to == "call_back"
                else "end the call"
                if to == "end"
                else f'go to "{to}"'
            )
            lines.append(f"   - {when}: {said}.")
    return "\n".join(lines)


def task_steps_note(plan: OwnerPlan) -> str:
    """What the owner reads beside the steps: how Pip read their main task."""
    steps = "; ".join(
        f"{step.number}. {step.name}: {step.outcome.rstrip('.')}"
        for step in plan.steps
        if step.number is not None
    )
    return f"Pip read your main task as these steps: {steps}."


#: The part name the Script section's "Let Pip map the scenarios" sends (`CampaignFlow`).
FLOW_PART: Final = "flow"
Tone = Literal["warm", "respectful", "brief"]
#: The owner's tone (D-1004), as the writer reads it. Keys are the request's `tone`. None asks
#: for formal words: every call's register forbids them (`engine._REGISTER_BULLET`), and the
#: tone reaches the call as the script's `Tone:` line.
TONES: Final[dict[str, str]] = {
    "warm": "friendly and warm, like a helpful neighbour, still polite",
    "respectful": "respectful, with the polite address form the spoken-style guide gives, "
    "in everyday spoken words",
    "brief": "short and direct, every line as few words as it can be",
}

#: The owner's note for one draft, in characters. Real rewrite notes (who the agent is, what
#: it says first, which English words stay, what it never claims) run 600 to 900 (founder,
#: 21 Nov 2026), and Pip, passing on a request, writes them longer. An owner who lays out
#: every step with its outcome and ways out (`agents.owner_plan`) needs about 2,500, so
#: 4,000. The note is folded onto one line, so however long it is it stays inside
#: "THE OWNER ASKS:" and cannot start a heading of its own.
INSTRUCTION_MAX: Final = 4000


#: How the business has the people's numbers, by the campaign's declared consent source
#: (`campaigns.models.CONSENT_SOURCES`). `purchased_list` is refused at launch and has none.
_HOW_THEY_CAME: Final[dict[str, str]] = {
    "existing_customer": "they are the business's existing customers",
    "inbound_enquiry": "they contacted the business: called, messaged or filled its enquiry form",
    "web_form_optin": "they ticked a box on the business's web form to be contacted",
    "offline_form_optin": "they signed up on a paper form, at an event or at the business",
}


def situation_block(
    *,
    agent_name: str = "",
    holder_name: str = "",
    purpose: str = "",
    goal: str = "",
    consent_source: str | None = None,
    inbound: bool = False,
) -> str:
    """The campaign's or line's own settings, so every line is written for this call and the
    review can check a claim against them: its name, why these people are called, what a good
    call ends with, how the business has their numbers, and the agent's name. "" when none."""
    rows = [
        (("Phone line: " if inbound else "Campaign name: "), holder_name),
        ("Why these people are called: ", purpose),
        ("A good call ends with: ", goal),
        ("The agent's name: ", agent_name),
    ]
    lines = [f"{label}{value.strip()}" for label, value in rows if value.strip()]
    came = _HOW_THEY_CAME.get(consent_source or "")
    if came:
        lines.append(
            f"How the business has their numbers: {came}. The agent may say so when asked how "
            "it got their number; it never tells the person what they did."
        )
    if not lines:
        return ""
    return ("THE LINE:\n" if inbound else "THE CAMPAIGN:\n") + "\n".join(lines) + "\n"


#: Where the engine's box is measured from, and the share of what is left the ask names: the
#: writer overshoots a stated budget a little, and the save refuses a script that does not fit
#: (`script_builder.refuse_if_too_long`), so the ask names less than the room there is.
BUDGET_SHARE: Final = 0.85


def budget_of(limit: int | None, total: int, script_chars: int) -> int | None:
    """The characters the script may take: the box less everything around the script."""
    if limit is None:
        return None
    return max(int((limit - (total - script_chars)) * BUDGET_SHARE), 0)


TOO_LONG_RULE: Final = (
    "Too long for the agent to hold by {over:,} characters. Shorten {parts} before you keep it"
)


def _plain(text: str) -> str:
    """`text` with case, punctuation and spacing gone, in any script: letters, marks (Telugu
    vowel signs are marks) and digits kept, so a quote copied with other spacing still
    matches."""
    kept = (
        ch if unicodedata.category(ch)[0] in "LMN" else " "
        for ch in unicodedata.normalize("NFC", text.casefold())
    )
    return " ".join("".join(kept).split())


def quoted_in(evidence: str, sources: str) -> bool:
    """Whether `evidence` is a passage of `sources`, word for word up to case, punctuation and
    spacing. A paraphrase does not count: the point is that the code, not the judge, decides
    a claim is sourced."""
    said = _plain(evidence)
    return bool(said) and f" {said} " in f" {_plain(sources)} "


__all__ = [
    "BUDGET_SHARE",
    "FLOW_PART",
    "INSTRUCTION_MAX",
    "TASK_STEPS_FORMAT",
    "TASK_STEPS_INSTRUCTION",
    "TASK_STEPS_MAX_TOKENS",
    "TONES",
    "TOO_LONG_RULE",
    "Tone",
    "budget_of",
    "quoted_in",
    "situation_block",
    "task_steps_note",
    "task_steps_request",
    "task_steps_text",
]
