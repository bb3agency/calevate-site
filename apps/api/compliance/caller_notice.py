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

**CROSS-CALL MEMORY IS DESCRIBED WHEN IT HAPPENS AND ONLY THEN (D-506, D-507).** The
draft names the agents that remember callers, itemises the note, prints the period from the
tenant's own `caller_memory` retention row, and says that those agents announce it at the
start of the call — which they do, on no switch of their own. Two ways it can be silent,
and both are the accurate document rather than an omission: the client has the switch off
(every client today), or the tenant is on a vertical where `caller_memory.
spdi_refuses_memory` refuses the write outright (D-507(b)), in which case the switch may
read `true` and nothing is ever written. A notice describing processing that cannot happen
is as false as one that hides processing that can.

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

from apps.api.compliance.caller_memory import spdi_refuses_memory
from apps.api.core.logging import get_logger
from apps.api.retrieval.models import RETENTION_CALLER_MEMORY

log = get_logger(__name__)

# The blanks only the client can fill, spelled the way the public legal documents spell
# theirs so the two are recognisably one convention.
BUSINESS_NAME = "{{YOUR REGISTERED BUSINESS NAME}}"
#: The IDENTIFICATION address, and it is a separate blank from `BUSINESS_CONTACT` on
#: purpose. `_open_questions` has always told the client to "put your registered business
#: name and address in, in place of every blank" — and there was no address blank to put
#: it in, so a client following the instruction to the letter published a notice that
#: identified them by name only. Consumer-protection display duties are about saying WHO
#: and WHERE the business is, which is not the same as offering a place to write to; it is
#: rendered under "Who is responsible" for that reason and never as a correspondence
#: route, matching `/legal/privacy` §14, `/legal/terms` §17 and `/legal/refunds` §7, which
#: all print the supplier's address as identification and say plainly that no postal
#: channel is operated.
BUSINESS_ADDRESS = "{{YOUR REGISTERED BUSINESS ADDRESS}}"
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

#: WHAT CROSS-CALL MEMORY ADDS TO THE ITEMISATION (D-506), included only for a tenant that
#: has it switched on somewhere. Written in the caller's words and not ours: "a short note
#: of what you asked about" is what a distilled fact IS, and a caller reading "caller
#: memory" would learn nothing. It is listed BESIDE the inherent items rather than inside
#: them because it is precisely NOT inherent — it is the one collection on this list that a
#: business chooses, which is why `_open_questions` also puts it in front of their counsel.
_MEMORY_ITEM: tuple[str, str] = (
    "A short note of what you asked about, kept after the call ends",
    "so that if you call us again, the assistant knows what you asked about last time",
)

#: How the `caller_memory` period is labelled, named as a constant because the builder
#: has to find that line again to decide whether it may be printed at all.
_MEMORY_CATEGORY_LABEL = "The short note of what you asked about"

#: Retention categories, in the words a caller reads. A category with no row for this
#: tenant is omitted rather than defaulted: the draft states what THIS client's settings
#: say, and a period nobody configured is not a period we may print.
_CATEGORY_LABELS: dict[str, str] = {
    "recording": "The recording of your call",
    "transcript": "The transcript of what was said",
    "lead": "The details noted from your call (your enquiry record)",
    #: D-507(c) made this a real category with its own 180-day/`delete` row, and the map
    #: is FILTERED — so a missing entry raised nothing and looked like nothing: the draft
    #: itemised the note as something collected and then printed no period for it, which
    #: is the one period a caller most needs. The wording is the caller's, matching the
    #: sentence the agent speaks (`disclosure.CALLER_MEMORY_NOTICE_TEMPLATES`) — never "a
    #: distilled fact" and never anything naming a vector.
    #:
    #: PRINTED ONLY FOR A TENANT THAT ACTUALLY KEEPS NOTES. `scripts/seed.py` writes this
    #: row for EVERY organisation, so an unconditional line would tell every client's
    #: callers how long notes about them are kept on an account that keeps none —
    #: `_CATEGORY_LABELS`' own `consent_log` lesson pointed the other way. The filter is
    #: in `build_caller_notice`, beside the switch that decides it.
    RETENTION_CALLER_MEMORY: _MEMORY_CATEGORY_LABEL,
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
    #: Agents that REMEMBER CALLERS ACROSS CALLS (D-506), by name. Named rather than
    #: counted for `ai_disclosure_off`'s reason: the client's notice has to carry it, and
    #: an operator reading "1 agent" cannot tell which conversation they are agreeing to.
    caller_memory_on: list[str] = field(default_factory=list)
    #: How long a caller note is kept, from this tenant's own `caller_memory` retention
    #: row. `None` when they keep no notes (the row is filtered out of `retention` above in
    #: the same breath) or when the account genuinely has no row for the category. The same
    #: number the "How long we keep it" line carries, read once — the memory section states
    #: it in place because that is where a caller is being told what the note IS, and a
    #: reader should not have to cross-reference a list to learn how long it lasts.
    memory_retention_days: int | None = None
    #: Agents that HAND A CALLER TO A PERSON mid-call (D-533), by name. Named rather than
    #: counted for `ai_disclosure_off`'s reason, and the fact needs stating for a reason
    #: none of the others have: it is the one part of the call where the caller stops
    #: talking to a machine and starts talking to a member of the client's own staff, on
    #: that person's own phone, and the voice platform records that second leg separately.
    #: A notice that itemised the AI half and said nothing about the human one would be
    #: describing the wrong call.
    handoff_agents: list[str] = field(default_factory=list)
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

    The join to `organizations` is an INNER one, matching
    `caller_memory.memory_enabled`'s exactly rather than choosing its own shape: the two
    reads answer the same question about the same tenant — may these agents remember their
    callers — and a LEFT JOIN here would read a hidden or missing org row as "no vertical,
    so not refused" while the write path read it as "no row, so nothing is written". That
    divergence is the one this module cannot afford, because its output is a document the
    client publishes.
    """
    rows = (
        await session.execute(
            text(
                "SELECT a.id, a.name, a.ai_disclosure_enabled, a.recording_notice_enabled, "
                "a.direction, a.caller_memory_enabled, a.handoff_enabled, "
                "s.fields, o.vertical_template "
                "FROM agents a JOIN organizations o ON o.id = a.tenant_id "
                "LEFT JOIN extraction_schemas s ON s.id = a.extraction_schema_id "
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
            # D-506. A caller who is REMEMBERED ACROSS CALLS is a materially different
            # privacy proposition from one who is not, so the itemisation Rule 3 asks for
            # has to say it. Defaults FALSE, so for every client today this is False and
            # the draft reads exactly as it did before.
            #
            # AND'ED WITH THE SPDI REFUSAL (D-507(b)), because this key means "does this
            # agent remember its callers" and not "what does the column say". On a refused
            # vertical `caller_memory.memory_enabled` returns False however the switch is
            # set, so nothing is ever written — and a draft that told those callers their
            # notes are kept would describe processing that cannot happen. Over-disclosure
            # is not the safe direction here: a caller reading it would decline something
            # nobody is doing, and the client would have published a false statement about
            # their own business. The predicate is imported rather than repeated so the two
            # answers cannot drift.
            "caller_memory_enabled": bool(row[5])
            and not spdi_refuses_memory(None if row[8] is None else str(row[8])),
            # D-533. The switch alone, deliberately NOT and'ed with "is anybody on the
            # roster right now": the notice describes what CAN happen on a call, and a
            # roster that is empty this afternoon is not a statement that this business
            # never puts callers through. Under-disclosing because of a temporary state is
            # the direction Rule 3 is about, and `caller_memory_enabled` above is and'ed
            # only because there the refusal is STRUCTURAL — on a refused vertical nothing
            # can ever be written, which is a different fact from "nothing is right now".
            "handoff_enabled": bool(row[6]),
            "fields": row[7] or [],
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
    if any(agent["caller_memory_enabled"] for agent in agents):
        items.append(CollectedItem(what=_MEMORY_ITEM[0], why=_MEMORY_ITEM[1]))
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

    A FOURTH SENTENCE SINCE D-507, AND IT IS NOT A FOURTH TOGGLE. An agent that remembers
    its callers says so at the start of the call —
    `calevate_shared.engine.compose_opening_line` appends
    `agents.caller_memory_notice_line` third, gated on `caller_memory_enabled` and on no
    switch of its own, so "remembers a caller without saying so" is not a state this
    product can be configured into. The draft therefore describes it as a consequence of
    the memory setting and never as a third announcement the client could turn off; a
    document that implied otherwise would send them looking for a control that does not
    exist, and a support answer would eventually invent one.
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
    if draft.caller_memory_on:
        named = ", ".join(draft.caller_memory_on)
        lines.append(
            f"The assistants that keep notes about you between calls also say so at the "
            f"start of the call ({named}). They always do: an assistant that keeps notes "
            'says so, and there is no separate setting for it — see "If you have called '
            'us before" below.'
        )
    lines.append(
        "Whatever the call opens with, if you ask the assistant whether it is an AI, or "
        "whether the call is being recorded, it will tell you the truth. That is enforced "
        "by the platform and cannot be switched off."
    )
    return "\n".join(lines)


def _handoff_paragraph(draft: CallerNoticeDraft) -> str:
    """What happens when the assistant puts a caller through to a person, or "".

    EMPTY WHEN NO AGENT HANDS OVER, which is every client until one configures a handover
    list — `_memory_paragraph`'s argument exactly: a notice describing a transfer that
    cannot happen over-discloses, and one silent about a transfer that can under-discloses.

    **IT SAYS THE SECOND RECORDING EXISTS, and that is the sentence worth the section.**
    The voice platform records the transferred leg as an object of its own
    (`HandoffLeg.recording_present`), which is a recording of this caller that Calevate
    does not hold and cannot erase on the client's behalf — so a caller asking for erasure
    is asking for something the client must route to us, and a notice that quietly counted
    it as "the call recording" would be describing one recording where there are two. The
    blank is marked rather than filled: how long the platform keeps it is
    OPERATIONS §2 gate 46b, and a plausible number here would be a guess published as a
    fact.
    """
    if not draft.handoff_agents:
        return ""
    named = ", ".join(draft.handoff_agents)
    return f"""## When we put you through to a person

Some of our assistants can hand your call to a member of our team while you are still on
the line ({named}) — if you ask to speak to a person, or if the assistant judges that
somebody should. When that happens we ring one of our own staff and connect you; you are
talking to a person from that point on, and they see why you called.

That second connection is a separate telephone call, made by our calling platform, and it
is recorded separately from the first part of your call. {{{{HOW LONG THAT SECOND
RECORDING IS KEPT IS SET BY OUR CALLING PROVIDER'S PLATFORM AND NOT BY US — ASK CALEVATE
FOR THE PERIOD AND STATE IT HERE}}}}

"""


def _memory_paragraph(draft: CallerNoticeDraft) -> str:
    """The cross-call memory sentence, or "" when this client does not remember callers.

    EMPTY BY DEFAULT AND FOR EVERY CLIENT TODAY, which is why it is a whole section rather
    than a clause bolted onto another one: a notice that mentions memory when there is none
    over-discloses, and one that stays silent when there IS memory under-discloses, which
    is the direction Rule 3 is about. The switch decides, so the document can only say what
    the configuration does.

    It names the agents, like `_disclosure_paragraph` does, because a business running a
    receptionist that remembers and a campaign that does not is telling their callers two
    different things and the draft must not flatten them into one.
    """
    if not draft.caller_memory_on:
        return ""
    named = ", ".join(draft.caller_memory_on)
    kept = (
        f"it is kept for {draft.memory_retention_days} days after the call it was taken on"
        if draft.memory_retention_days is not None
        else "{{ASK CALEVATE HOW LONG THESE NOTES ARE KEPT — YOUR ACCOUNT HAS NO "
        "RETENTION SETTING FOR THEM}}"
    )
    return (
        "## If you have called us before\n\n"
        f"Some of our assistants keep a short note of what you asked about, so that the "
        f"next time you call they already know ({named}). Those assistants tell you so at "
        "the start of the call. It is a note of the SUBJECT — "
        '"asked about prices", not a recording or a transcript of what you said — and '
        f"{kept} — a clock of its own, not the one that applies to the recording or the "
        "transcript. You can ask us to erase it with everything else, using the "
        'contact under "Your rights".\n\n'
        "{{YOUR ADVOCATE MUST CHECK THIS SECTION BEFORE YOU PUBLISH IT. Keeping notes "
        "about a caller between calls is a decision you have made, not something a phone "
        "call inherently does, and it is the part of this notice a caller is least likely "
        "to expect.}}\n"
    )


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

{BUSINESS_NAME}, of {BUSINESS_ADDRESS}, decides what is collected on these calls and why.
That address is here so you know who and where we are; it is not a channel for writing to
us about your information — use the contact under "Your rights" below for that. Our
calling and AI assistant are operated for us by Calevate, which processes this information
only on our instructions.

## Being told what you are speaking to

{_disclosure_paragraph(draft)}

## What we collect

{collected}

{_memory_paragraph(draft)}{_handoff_paragraph(draft)}
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
    remembering = [a["name"] for a in agents if a["caller_memory_enabled"]]
    retention = await _retention(session)
    # ONE READ, ONE NUMBER. The period appears twice in the finished document — as a line
    # in "How long we keep it" and inside the memory section that explains what the note
    # is — and both come from this row, so they cannot disagree. And it is DROPPED
    # entirely for a tenant that keeps no notes: the seed writes the row for every
    # organisation, so printing it unconditionally would state a period for a collection
    # that is not happening (see `_CATEGORY_LABELS`).
    memory_days = next(
        (line.days for line in retention if line.what == _MEMORY_CATEGORY_LABEL), None
    )
    if not remembering:
        retention = [line for line in retention if line.what != _MEMORY_CATEGORY_LABEL]
        memory_days = None
    draft = CallerNoticeDraft(
        collected=_collected(agents),
        retention=retention,
        ai_disclosure_off=[a["name"] for a in agents if not a["ai_disclosure_enabled"]],
        recording_notice_off=[a["name"] for a in agents if not a["recording_notice_enabled"]],
        caller_memory_on=remembering,
        memory_retention_days=memory_days,
        handoff_agents=[a["name"] for a in agents if a["handoff_enabled"]],
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
        caller_memory_on=draft.caller_memory_on,
        memory_retention_days=draft.memory_retention_days,
        handoff_agents=draft.handoff_agents,
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
        "Put your registered business name and your registered business address in, in "
        'place of every blank. The address identifies you under the "Who is '
        'responsible" heading; it is not offered to callers as a place to send things, '
        "so if you do want post, add that yourself and say so.",
        "Name the person who answers data questions for your business, with an email "
        "and a phone number that are actually monitored.",
        "If you call people who have not contacted you first, say what permits you to — "
        "their consent, and where you obtained it.",
        "Have your advocate check this before you publish it. Calevate generated the "
        "facts; the wording and the legal basis are yours.",
    ]
    if any(agent["caller_memory_enabled"] for agent in agents):
        # FIRST, ahead of the standing four, because it is the only one on this list that
        # is about a collection the caller does not expect at all. The other questions ask
        # a business to fill in facts about itself; this one asks whether they may lawfully
        # do a thing they have already switched on (D-506).
        questions.insert(
            0,
            "Your assistants keep notes about callers BETWEEN calls. Have your advocate "
            "confirm you may: it is a purpose your notice has to state before you collect "
            "for it, and it is not something a caller expects from a phone call. Ask them "
            "specifically whether telling people in writing is enough for someone who "
            "simply rings you and never sees this page, and whether any of the notes could "
            "amount to health or other sensitive information.",
        )
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
    "BUSINESS_ADDRESS",
    "BUSINESS_CONTACT",
    "BUSINESS_NAME",
    "DRAFT_WARNING",
    "CallerNoticeDraft",
    "CollectedItem",
    "RetentionLine",
    "build_caller_notice",
]
