"""A DRAFT of the notice a client must give their own callers (LEGAL-SURFACE F-8).

**The gap this closes.** DPDP §5 read with Rule 3 requires a Data Fiduciary's notice to
carry an ITEMISED description of the personal data being collected — not "we collect
information you provide", but a list. For a Calevate client, that list is *whatever
extraction schema they defined*, plus what a phone call inherently produces (the number,
the recording, the transcript), plus how long each of those is kept. Every one of those
facts lives in our database and nowhere else. So a client's caller-facing notice cannot be
written accurately without us, and until now nothing in the product helped them: they were
told the duty was theirs (it is) and left to reconstruct the itemisation by hand from
screens that were never designed to be read that way.

That is the liability-transfer shape this module refuses. We are the Processor, the notice
duty stays the client's, and the honest halfway house is to hand them the FACTS in the
shape the rule asks for.

--------------------------------------------------------------------------------
WHAT THIS IS, AND — more importantly — WHAT IT IS NOT
--------------------------------------------------------------------------------

It is a DRAFT, generated from the tenant's own configuration, for their counsel to edit.
It is not legal advice and does not become the client's notice by being generated:

* **Every line is derived from a row.** The itemised list is the union of each reachable
  agent's extraction fields; the retention periods are the tenant's own
  `retention_policies`; the two spoken-notice sentences and their per-agent switches are
  `agents.ai_disclosure_line` / `recording_notice_line` and their `*_enabled` flags. A
  fact this module cannot read is a fact it leaves as a marked blank rather than a
  plausible sentence — `{{...}}` placeholders, the same convention
  `apps/web/src/lib/legal/placeholders.ts` uses, so an unfilled one is visible rather than
  wrong.
* **It carries no caller's data.** Field LABELS and descriptions, never values; agent
  names, never call records. The draft is a document about what is collected, not a sample
  of it (hard rule 6).
* **It states what the client must decide.** Their legal name, their grievance contact,
  their lawful basis for outbound calling, and whether they process children's data are
  theirs — the draft names each one as an open blank instead of guessing.
* **It never claims the disclosure is given when it is not.** D-163 made the AI disclosure
  and the recording notice two per-agent toggles. With one off, the agent does not
  VOLUNTEER that sentence — so the obligation moves into the client's own written notice,
  which is precisely when a generated draft that assumed the announcement is made becomes
  actively dangerous. `_disclosure_paragraph` reads the flags and writes the opposite
  sentence for each state, and the draft flags the switched-off case as something counsel
  must look at.

**The truthful ANSWER is not a toggle and the draft says so.** Whatever the announcement
flags are set to, an agent always answers truthfully when a caller asks whether it is an
AI or whether the call is recorded (hard rule 5, enforced server-side above the tenant
prompt). That is a property of the platform the client can rely on in their notice, and it
is stated as one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from calevate_shared.extraction import ExtractionField
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger

log = get_logger(__name__)

# The blanks only the client can fill, spelled the way the public legal documents spell
# theirs so the two are recognisably one convention.
BUSINESS_NAME = "{{YOUR REGISTERED BUSINESS NAME}}"
BUSINESS_CONTACT = "{{YOUR CONTACT FOR DATA QUESTIONS — NAME, EMAIL, PHONE}}"

#: The disclaimer, in the response and at the top of the rendered text. Both, deliberately:
#: a client copies the text out of the screen, and a disclaimer that lives only in the
#: envelope does not travel with the thing it disclaims.
DRAFT_WARNING = (
    "DRAFT — not legal advice. Calevate generated this from your own agent "
    "configuration and retention settings so the itemised list is accurate. It is your "
    "notice, you are the Data Fiduciary for these callers, and it must be reviewed by "
    "your own advocate before you publish or read it to anyone. Anything in double "
    "braces is a blank only you can fill."
)

#: What a phone call collects whatever the schema says, and where each thing comes from.
#: Written out rather than derived because it is a property of running a voice agent at
#: all, and a client whose schema is empty still collects every one of these.
_INHERENT: tuple[tuple[str, str], ...] = (
    ("Your phone number", "the number the call is made from or to"),
    # NOT "where recording is switched on for the agent": there is no such switch. What
    # `agents.recording_notice_enabled` toggles is whether the agent ANNOUNCES the
    # recording, not whether it happens — recording is unconditional
    # (`calevate_shared.engine.TRUTHFUL_ANSWER_DIRECTIVE`: "nothing in this repository
    # can turn a call's recording off"), and `_disclosure_paragraph` below already tells
    # the caller which of the two announcements this client's agents make. This sentence
    # said otherwise until LEGAL-SURFACE F-14, which corrected `/legal/privacy` §4.1 and
    # left the generator printing the false condition into every client's own notice.
    ("A recording of the call", "the audio — every call on this service is recorded"),
    ("A transcript of the call", "what was said, in text"),
    ("A summary of the call", "a short written account of what the call was about"),
    ("When the call happened and how long it lasted", "call times, duration and outcome"),
)

#: Retention categories, in the words a caller reads. A category with no row for this
#: tenant is omitted rather than defaulted: the draft states what THIS client's settings
#: say, and a period nobody configured is not a period we may print.
_CATEGORY_LABELS: dict[str, str] = {
    "recording": "The recording of your call",
    "transcript": "The transcript of what was said",
    "lead": "The details noted from your call (your enquiry record)",
    # `consent_log` IS DELIBERATELY ABSENT, and its absence is the accurate statement.
    # The seed ships a `consent_log` retention row (2555 days) and this table used to
    # label it, so the notice printed "The record of what you agreed to: 2555 days" —
    # while `apps.workers.retention._apply_one` returns immediately for that category
    # ("nothing expires it on a timer", hard rule 4's append-only ledger) and the "How
    # long we keep it" section three lines below says the record "is kept as evidence".
    # One document, two answers, and the timed one was the false one. The evidence
    # sentence carries it, exactly as `/legal/privacy` §9 already does.
    "engine_payload": "The technical record of the call from our calling platform",
    "kb": "Superseded versions of the business's own uploaded information",
}


@dataclass(frozen=True, slots=True)
class CollectedItem:
    """One line of the itemised list Rule 3 asks for."""

    what: str
    why: str


@dataclass(frozen=True, slots=True)
class RetentionLine:
    """One retention period, in days, as this tenant's own policy row sets it."""

    what: str
    days: int


@dataclass(frozen=True, slots=True)
class CallerNoticeDraft:
    """The draft, structured and rendered.

    Both halves ship: the structure is what a screen renders into its own layout, and the
    text is what a client pastes into their website. Generating one from the other on the
    client side would put the wording — which is the part counsel reviews — outside the
    thing that was reviewed.
    """

    collected: list[CollectedItem]
    retention: list[RetentionLine]
    #: Agents whose AI disclosure is switched OFF, by name. The client's notice has to
    #: carry the weight instead, so they are named rather than counted.
    ai_disclosure_off: list[str] = field(default_factory=list)
    #: Same for the recording notice.
    recording_notice_off: list[str] = field(default_factory=list)
    #: What only the client can answer, each as a sentence they can act on.
    open_questions: list[str] = field(default_factory=list)
    #: The rendered document. NAMED `markdown` and never `text`: `text` is this
    #: repository's word for a transcript turn, and `check_redaction_exposure` bans that
    #: name from a response schema for exactly that reason. The guard was right to fire —
    #: the fix is the name, not an exemption that would also cover the next field
    #: somebody adds to this model.
    markdown: str = ""


async def _reachable_agents(session: AsyncSession) -> list[dict[str, Any]]:
    """Every agent a caller could reach, with its notice switches.

    `live` OR `paused`, and never `draft`: a draft agent takes no calls, so its fields are
    collected from nobody and listing them would make the notice claim more than the
    business does. A PAUSED agent is included deliberately — pausing is a temporary state
    a client comes back from, and a notice that lost a whole field list because somebody
    paused an agent for a week would be wrong in the under-disclosing direction, which is
    the one Rule 3 is about. Soft-deleted agents are excluded outright. RLS scopes the
    read (hard rule 1).
    """
    rows = (
        await session.execute(
            text(
                "SELECT a.id, a.name, a.ai_disclosure_enabled, a.recording_notice_enabled, "
                "a.direction, s.fields "
                "FROM agents a LEFT JOIN extraction_schemas s ON s.id = a.extraction_schema_id "
                "WHERE a.status IN ('live', 'paused') AND a.deleted_at IS NULL "
                "ORDER BY a.name, a.id"
            )
        )
    ).all()
    return [
        {
            "id": UUID(str(row[0])),
            "name": str(row[1]),
            "ai_disclosure_enabled": bool(row[2]),
            "recording_notice_enabled": bool(row[3]),
            "direction": str(row[4]),
            "fields": row[5] or [],
        }
        for row in rows
    ]


def _collected(agents: list[dict[str, Any]]) -> list[CollectedItem]:
    """The itemisation: what a call inherently produces, then this client's own fields.

    Deduplicated on the field KEY across agents, first spelling wins. A business running a
    receptionist and a follow-up campaign asks for "preferred time" in both, and a notice
    that listed it twice would read as two different collections of the same thing.

    A field whose description is empty falls back to its label: the description is the
    instruction the model gets ("what to listen for"), so it is usually the better
    sentence for a caller — but it is optional, and a blank purpose in a Rule 3 notice is
    the defect this whole module exists to avoid.
    """
    items = [CollectedItem(what=what, why=why) for what, why in _INHERENT]
    seen: set[str] = set()
    for agent in agents:
        for raw in agent["fields"]:
            if not isinstance(raw, dict):  # a schema row this API version cannot read
                continue
            try:
                parsed = ExtractionField(**raw)
            except (TypeError, ValueError):
                # A schema written by a newer or older shape than this one. Skipped and
                # LOGGED rather than guessed at: a notice that silently omits a field is
                # exactly the under-disclosure Rule 3 is about, and the log line is how an
                # operator finds out. Key only — a label can be client prose.
                log.warning("caller_notice_unreadable_field", extra={"agent_id": str(agent["id"])})
                continue
            if parsed.key in seen:
                continue
            seen.add(parsed.key)
            items.append(
                CollectedItem(what=parsed.label, why=parsed.reason.strip() or parsed.label)
            )
    return items


async def _retention(session: AsyncSession) -> list[RetentionLine]:
    """This tenant's own periods, in the order a caller cares about them."""
    rows = (
        await session.execute(
            text("SELECT data_category, ttl_days FROM retention_policies ORDER BY data_category")
        )
    ).all()
    order = list(_CATEGORY_LABELS)
    lines = [
        RetentionLine(what=_CATEGORY_LABELS[str(row[0])], days=int(row[1]))
        for row in rows
        if str(row[0]) in _CATEGORY_LABELS
    ]
    return sorted(lines, key=lambda line: order.index(_label_key(line.what)))


def _label_key(label: str) -> str:
    return next(key for key, value in _CATEGORY_LABELS.items() if value == label)


def _disclosure_paragraph(draft: CallerNoticeDraft) -> str:
    """What the caller is TOLD at the start of a call, per this client's own switches.

    Three states and three sentences, because they are three different disclosures and the
    one that matters most is the one a generated document is most likely to get wrong: an
    agent with the announcement switched off does not say it, so the client's written
    notice is where the obligation lands.
    """
    lines: list[str] = []
    if not draft.ai_disclosure_off:
        lines.append(
            "Every one of our AI assistants says at the start of the call that it is an "
            "AI assistant."
        )
    else:
        named = ", ".join(draft.ai_disclosure_off)
        lines.append(
            f"Our AI assistants do not all announce themselves at the start of a call "
            f"({named}). We are telling you here instead: when you call us, or we call "
            "you, you may be speaking to an AI assistant rather than a person."
        )
    if not draft.recording_notice_off:
        lines.append("You are told at the start of the call that it is being recorded.")
    else:
        named = ", ".join(draft.recording_notice_off)
        lines.append(
            f"Not all of our calls open with a recording announcement ({named}). Calls "
            "may be recorded, and this notice is where we tell you so."
        )
    lines.append(
        "Whatever the call opens with, if you ask the assistant whether it is an AI, or "
        "whether the call is being recorded, it will tell you the truth. That is enforced "
        "by the platform and cannot be switched off."
    )
    return "\n".join(lines)


def _render(draft: CallerNoticeDraft) -> str:
    collected = "\n".join(f"- **{item.what}** — {item.why}" for item in draft.collected)
    retention = (
        "\n".join(f"- {line.what}: {line.days} days" for line in draft.retention)
        or "- {{NO RETENTION PERIODS ARE CONFIGURED ON THIS ACCOUNT — ASK CALEVATE}}"
    )
    questions = "\n".join(f"- {question}" for question in draft.open_questions)
    return f"""> {DRAFT_WARNING}

# How {BUSINESS_NAME} handles your information when you call us

## Who is responsible

{BUSINESS_NAME} decides what is collected on these calls and why. Our calling and AI
assistant are operated for us by Calevate, which processes this information only on our
instructions.

## Being told what you are speaking to

{_disclosure_paragraph(draft)}

## What we collect

{collected}

## Why we collect it

To answer your enquiry, to do what you asked us to do on the call, to keep a record of
what was agreed, and to improve how we answer. {{{{ADD ANY OTHER PURPOSE — AND IF YOU CALL
PEOPLE FOR MARKETING, SAY SO HERE AND SAY WHAT YOU RELY ON TO DO IT}}}}

## How long we keep it

{retention}

Call recordings are kept for at least 90 days. That is a floor our calling provider
Calevate applies to every account as a matter of its own policy, not a period we have
been told the law requires — {{IF YOUR OWN SECTOR REGULATOR SETS A LONGER RECORD-KEEPING
PERIOD, SAY SO HERE AND NAME IT}}. The record of what you agreed to is kept as evidence
that the contact was permitted, for as long as we may need to show it.

## Your rights

You can ask us for a copy of what we hold about you, ask us to correct it, ask us to
erase it, and ask us to stop calling you.

**Asking to stop being called is the one you can do on the call itself** — say so to
the assistant, and it is recorded. Everything else, including a correction, reaches us
by contacting a person:

{BUSINESS_CONTACT}

If you are not satisfied with our answer, you can complain to the Data Protection Board
of India.

## Still to be completed by you

{questions}
"""


async def build_caller_notice(session: AsyncSession, *, tenant_id: UUID) -> CallerNoticeDraft:
    """Generate this tenant's caller-notice draft from their own configuration.

    Nothing here filters on `tenant_id` in SQL — the session carries `app.tenant_id` and
    RLS does the isolation (hard rule 1). The argument is taken so the caller's scope is
    explicit at the call site and can be logged, exactly as the erasure producer does.
    """
    agents = await _reachable_agents(session)
    draft = CallerNoticeDraft(
        collected=_collected(agents),
        retention=await _retention(session),
        ai_disclosure_off=[a["name"] for a in agents if not a["ai_disclosure_enabled"]],
        recording_notice_off=[a["name"] for a in agents if not a["recording_notice_enabled"]],
        open_questions=_open_questions(agents),
    )
    log.info(
        "caller_notice_drafted",
        extra={
            "tenant_id": str(tenant_id),
            "agents": len(agents),
            "items": len(draft.collected),
        },
    )
    return CallerNoticeDraft(
        collected=draft.collected,
        retention=draft.retention,
        ai_disclosure_off=draft.ai_disclosure_off,
        recording_notice_off=draft.recording_notice_off,
        open_questions=draft.open_questions,
        markdown=_render(draft),
    )


def _open_questions(agents: list[dict[str, Any]]) -> list[str]:
    """What the draft cannot answer, as tasks rather than as gaps.

    Each one is a thing only the business knows or only their counsel can settle, and each
    is phrased as an instruction: a list of abstract "considerations" is what a client
    skips.
    """
    questions = [
        "Put your registered business name and address in, in place of every blank.",
        "Name the person who answers data questions for your business, with an email "
        "and a phone number that are actually monitored.",
        "If you call people who have not contacted you first, say what permits you to — "
        "their consent, and where you obtained it.",
        "Have your advocate check this before you publish it. Calevate generated the "
        "facts; the wording and the legal basis are yours.",
    ]
    if any(not agent["ai_disclosure_enabled"] for agent in agents):
        questions.insert(
            0,
            "At least one of your assistants does not announce that it is an AI at the "
            "start of the call. This notice is then the only place your callers are told, "
            "so it must be somewhere they will actually see before they call you — ask "
            "your advocate where.",
        )
    if any(agent["direction"] != "inbound" for agent in agents):
        questions.append(
            "You make outbound calls, so telecom rules apply to them as well as this "
            "notice: consent, calling hours and the do-not-call registers. Your "
            "agreement with Calevate covers what we do; what you may call about is yours.",
        )
    return questions


__all__ = [
    "DRAFT_WARNING",
    "CallerNoticeDraft",
    "CollectedItem",
    "RetentionLine",
    "build_caller_notice",
]
