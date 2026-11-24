"""Pip writes the company training in the background and saves it live (D-1034, founder 23 Nov
2026: "company training is to be done automatically when the agent is created itself ...
written very very accurately and correctly and appropriately to the business and as per their
details").

Queued by `agents/company_training.schedule_write`: the client's first agent, a knowledge
source going live or coming down, the business profile, the owner's overview, or Rewrite now.
A queued write waits out its debounce (`due_at`) by deferring itself, so a burst of changes is
one write. One answer on the dashboard AI ladder (`script_assist.ask_json`), written from what
is known about the business (`lead_fields_draft.business_context`, already redacted), the
owner's overview (redacted here, D-127 G-1), every source the agents use (`knowledge_words`,
read the way onboarding reads documents: `first_run.documents_block`), and the live training
with the owner's own edits in it.

THE OWNER'S EDITS ARE CONSTRAINTS, NOT A MERGE. The live text differing from what Pip last
saved is the owner's (`edits_since`). A line-level three-way merge (diff3) cannot rewrite
prose around an edit, and an edit dropped by a free rewrite is lost silently; so the writer is
given each edit as a numbered constraint to carry, and the review must show where each one
landed. This is the "user edits as constraints" shape (an LLM merge of a user's edit with a
fresh baseline, preserving the user's framing while absorbing new facts:
docs.hyperspell.com, "LLM-based three-way merge of a user edit with the current LLM output",
read 23 Nov 2026). An owner's fact stays theirs through later rewrites (`owner_edits.said`),
and a sentence they took out is never put back (`owner_edits.removed`).

GROUNDED OR NOT SAVED. The draft is read by a second pass, the campaign script writer's
review (D-1004): each claim must carry a word-for-word quote that the CODE finds in the
sources (`campaign_script_ask.quoted_in`), so the judge's leniency is overruled by text
(platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations,
"Verify with citations", read 23 Nov 2026); a model rarely finds its own errors in the answer
it just gave, hence a separate pass (arxiv.org/abs/2310.01798). Each owner's edit must be
quoted where it landed, its figures must survive (`figures_in`), and newer knowledge may replace
one only by a quote the code finds in the sources. A failing draft is repaired once and
reviewed again; still failing, it is not saved, the previous training stays, and an operator
is alerted (`company_training_not_saved`). A draft that does not fit the engine's box beside
the longest script is shortened once and reviewed again.

Every write back is a compare-and-set: the claim on the pending write's id, the save on the
training's version (`company_training.save_written`), so a write the owner stopped is never
saved and a rewrite started before an owner's save never overwrites it. Metered as a script
draft.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import company_training
from apps.api.agents.assist_leg import account_assist_leg
from apps.api.agents.live_apply import lock_tenant_target
from apps.api.billing.ai_quota import new_assist_ref, read_ai_quota
from apps.api.compliance.audit import write_audit
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_JOB_TIMEOUT_S, enqueue, job_id_for
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.first_run.documents import document_words
from apps.api.first_run.models import KNOWLEDGE_DOCUMENT_CHARS
from apps.api.teach.facts import FACTS_SOURCE_NAME
from apps.workers.campaign_script_ask import quoted_in
from apps.workers.extraction import ASSIST_LADDER_LEGS
from apps.workers.first_run import documents_block
from apps.workers.lead_fields_draft import business_context
from apps.workers.redaction import MASK, redact
from apps.workers.script_assist import JsonAnswer, ask_json
from apps.workers.script_proposal import PROPOSAL_MAX_TOKENS, PROPOSAL_REQUEST_TIMEOUT_S
from apps.workers.training_sections import FIELDS_ASK, SCHEMA, corpus_of
from apps.workers.training_sections import written as built_training

log = get_logger(__name__)

#: The ARQ name, `company_training.TRAINING_DRAFT_JOB` on the enqueue side; a literal here so
#: `scripts/check_job_wiring` can read this file's own deferred enqueue (`_defer`).
JOB_NAME: Final = "draft_company_training"

TRAINING_ASK: Final = (
    "Write the training this business gives every phone agent it puts on calls, the way a "
    "company trains every new employee before giving them work. Each agent also gets its "
    "own script for each piece of work; this training is what they all share, so it is about "
    "the business and how its agents behave on every call. When a source is written for one "
    "piece of work, take from it only what is true on every call. Use ONLY what the owner's "
    "words and the sources below say: never add a price, place, offer, time, product, "
    "process, promise or reassurance they do not state. Keep names, figures and the owner's "
    "own phrases exactly as they wrote them. No markdown, no emoji. "
) + FIELDS_ASK
EDIT_TAIL: Final = (
    " A training exists already, under CURRENT TRAINING: keep its wording wherever the "
    "material below does not change it, and bring it in line with the material where it does."
)
OWNER_EDITS_TAIL: Final = (
    " THE OWNER'S OWN EDITS are what the owner wrote into the training themselves. Carry "
    "every one of them: each fact and what it means must be in the training, in clearer words "
    "if you can, never dropped or contradicted. Only where a source states a newer, different "
    "fact on the same point does the source win. Never put back anything listed under THE "
    "OWNER TOOK THESE OUT."
)
REPAIR_TAIL: Final = (
    " You wrote the training under THE TRAINING YOU WROTE, and a check found the problems "
    "under FIX THESE. Return every list again with each one fixed and nothing else changed."
)
SHORTEN_TAIL: Final = (
    " The training under THE TRAINING YOU WROTE is too long to fit beside the agents' "
    "scripts. Return every list again so their text comes to at most {limit:,} characters: "
    "fewer and shorter items, each thing once, never a fact the owner's edits give."
)

_WRITE_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {"name": "company_training", "strict": True, "schema": SCHEMA},
}


#: The newest sources Pip reads; `documents_block` shares one word budget among them, so more
#: would only shorten each.
KNOWLEDGE_SOURCES_READ: Final = 20

#: Every source the agents use, newest first: an upload (file or link) or a typed note. The
#: taught facts are left out: they reach every agent already, as known facts. Sources a
#: campaign or a line picked (`only`) are read once approved, before the publish job makes
#: them live: a note added from a campaign page and Generate pressed straight after would
#: otherwise be written without, as would a note whose newest version is still publishing.
#: One version per source: the newest that qualifies, the live one first. A picked list can
#: name an older approved version beside the live one, and reading both doubled one guide
#: and halved every other source's share of the budget.
_KNOWLEDGE_SQL: Final = text(
    "SELECT id, name, upload_id FROM ("
    "SELECT DISTINCT ON (s.kind, s.name) s.id, s.name, u.id AS upload_id, s.updated_at "
    "FROM kb_sources s LEFT JOIN kb_uploads u ON u.source_id = s.id "
    "WHERE (s.is_active OR (CAST(:only AS uuid[]) IS NOT NULL AND s.status = 'approved')) "
    "AND s.name <> :facts "
    "AND (CAST(:only AS uuid[]) IS NULL OR s.id = ANY(CAST(:only AS uuid[]))) "
    "ORDER BY s.kind, s.name, s.is_active DESC, s.version DESC, s.id DESC"
    ") newest ORDER BY updated_at DESC, id DESC LIMIT :n"
)
_NOTE_WORDS_SQL: Final = text("SELECT content FROM kb_documents WHERE source_id = :s ORDER BY idx")


async def knowledge_words(
    session: AsyncSession, only: Sequence[UUID] | None = None
) -> list[tuple[str, str]]:
    """(name, words) of each source the agents use, or of the ones `only` names (the sources
    an inbound line was written from), unredacted: `documents_block` redacts."""
    rows = (
        await session.execute(
            _KNOWLEDGE_SQL,
            {
                "facts": FACTS_SOURCE_NAME,
                "n": KNOWLEDGE_SOURCES_READ,
                "only": None if only is None else [str(i) for i in only],
            },
        )
    ).all()
    found: list[tuple[str, str]] = []
    for source_id, name, upload_id in rows:
        if upload_id is not None:
            words = await document_words(session, upload_id)
        else:
            chunks = (await session.execute(_NOTE_WORDS_SQL, {"s": source_id})).scalars()
            words = "\n\n".join(str(c) for c in chunks)
        if words.strip():
            found.append((str(name), words))
    return found


# --- the owner's edits -------------------------------------------------------------------

#: The most owner's facts, and sentences they took out, carried from write to write.
OWNER_EDITS_KEPT: Final = 60
_SENTENCE_END: Final = re.compile(r"(?<=[.!?।])\s+")


def sentences(training: str) -> list[str]:
    """The training's sentences, each heading or line its own when it has no full stop."""
    found: list[str] = []
    for line in training.splitlines():
        found += [part.strip() for part in _SENTENCE_END.split(line) if part.strip()]
    return found


def edits_since(pip_text: str | None, live: str) -> tuple[list[str], list[str]]:
    """The owner's edits since Pip last saved: (sentences the owner wrote or changed,
    sentences of Pip's they took out). With nothing from Pip yet, every live sentence is the
    owner's. A sentence counts as kept when it is a passage of the other text up to case,
    punctuation and spacing (`quoted_in`), so retyping one with other spacing is no edit."""
    if not (pip_text or "").strip():
        return sentences(live), []
    assert pip_text is not None
    added = [s for s in sentences(live) if not quoted_in(s, pip_text)]
    removed = [s for s in sentences(pip_text) if not quoted_in(s, live)]
    return added, removed


@dataclass(frozen=True, slots=True)
class OwnerFact:
    #: The owner's words.
    text: str
    #: The training's words that carried it at the last write, '' before one.
    where: str = ""


@dataclass(frozen=True, slots=True)
class OwnerEdits:
    said: list[OwnerFact] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def stored(self) -> dict[str, Any]:
        return {
            "said": [{"text": f.text, "where": f.where} for f in self.said],
            "removed": list(self.removed),
        }


def _stored_edits(raw: Any) -> OwnerEdits:
    raw = raw if isinstance(raw, dict) else {}
    said = [
        OwnerFact(str(row.get("text") or ""), str(row.get("where") or ""))
        for row in raw.get("said") or ()
        if isinstance(row, dict) and str(row.get("text") or "").strip()
    ]
    removed = [str(r) for r in raw.get("removed") or () if str(r).strip()]
    return OwnerEdits(said, removed)


def carried_edits(stored: Any, pip_text: str | None, live: str) -> OwnerEdits:
    """Every owner's edit the next write must carry: the ones carried before, less those the
    owner has since taken out themselves, plus the edits since Pip last saved."""
    before = _stored_edits(stored)
    added, removed = edits_since(pip_text, live)
    said = [
        fact
        for fact in before.said
        if not any(quoted_in(fact.where or fact.text, gone) for gone in removed)
    ]
    known = {fact.text for fact in said}
    said += [OwnerFact(sentence) for sentence in added if sentence not in known]
    # A sentence the owner took out and then wrote back in is theirs again.
    out = [s for s in dict.fromkeys([*before.removed, *removed]) if not quoted_in(s, live)]
    return OwnerEdits(said[-OWNER_EDITS_KEPT:], out[-OWNER_EDITS_KEPT:])


def private_edits(edits: OwnerEdits) -> tuple[OwnerEdits, list[OwnerFact]]:
    """(the edits the writer is given, the owner's sentences holding a phone number, email or
    other detail `redact` masks). No model may read those (D-127 G-1), and a writer given the
    mask would drop the detail, so they are kept out of what it reads and put back word for
    word after it (`with_verbatim`)."""
    private = [fact for fact in edits.said if redact(fact.text).changed]
    shared = [fact for fact in edits.said if fact not in private]
    return OwnerEdits(shared, edits.removed), private


def with_verbatim(training: str, verbatim: Sequence[OwnerFact]) -> str:
    """`training` with each private owner's sentence it does not already hold on its own line
    at the end, as the owner wrote it."""
    missing = [fact.text for fact in verbatim if not quoted_in(fact.text, training)]
    return "\n".join([training, *missing]) if missing else training


# --- what Pip is asked -------------------------------------------------------------------


def _numbered(edits: OwnerEdits) -> str:
    return "\n".join(f"[{i}] {redact(f.text).text}" for i, f in enumerate(edits.said, 1))


def request_text(
    *,
    business: str,
    overview: str,
    documents: str,
    current: str | None,
    edits: OwnerEdits | None = None,
) -> str:
    """What the training is written from, in the order the ask names it."""
    parts = [f"WHAT IS KNOWN ABOUT THE BUSINESS:\n{business}"]
    if overview.strip():
        parts.append(f"THE OWNER'S OVERVIEW, IN THEIR WORDS:\n{redact(overview.strip()).text}")
    if current:
        parts.append(f"CURRENT TRAINING:\n{redact(current).text}")
    if edits is not None and edits.said:
        parts.append(f"THE OWNER'S OWN EDITS:\n{_numbered(edits)}")
    if edits is not None and edits.removed:
        gone = "\n".join(f"- {redact(s).text}" for s in edits.removed)
        parts.append(f"THE OWNER TOOK THESE OUT:\n{gone}")
    if documents:
        parts.append(documents)
    return "\n\n".join(parts)


def review_sources(*, business: str, overview: str, documents: str) -> str:
    """Everything a claim in the training may come from besides the owner's edits, as the
    review reads it; a quote is looked up in exactly this text."""
    parts = [f"WHAT IS KNOWN ABOUT THE BUSINESS:\n{business}"]
    if overview.strip():
        parts.append(f"THE OWNER'S OVERVIEW:\n{redact(overview.strip()).text}")
    if documents:
        parts.append(documents)
    return "\n\n".join(parts)


# --- the review --------------------------------------------------------------------------

REVIEW_INSTRUCTION: Final = (
    "You check a company training an assistant just wrote for a business's phone agents, "
    "before it goes live on every call. You are given the SOURCES (what is known about the "
    "business, the owner's words and documents), THE OWNER'S EDITS (numbered) and THE "
    "TRAINING. Judge only against the SOURCES and THE OWNER'S EDITS, never your own "
    "knowledge.\n"
    "1. claims: every statement of fact in the training: a price, amount, date, time, place, "
    "product, service, offer, discount, guarantee, promise, policy, process, contact detail, "
    "or anything the business does for its customers. `said` copies the training's words "
    "that state it. `claim` names it in a few plain English words. `evidence` copies, word "
    "for word, the shortest passage of the SOURCES or THE OWNER'S EDITS that states it, or "
    "is empty when none does. A heading, or how to speak (tone, politeness, pace), is not a "
    "claim unless it promises something.\n"
    "2. owner_edits: one row for each of THE OWNER'S EDITS, by its number. `kept_in` copies, "
    "word for word, the training's words that carry its facts and meaning, or is empty when "
    "the training drops or contradicts it. `replaced_by` copies, word for word, a passage of "
    "the SOURCES that states a newer, different fact on the same point, or is empty.\n"
    "3. problems: a line of the training that is a stock line that would fit any business, "
    "with `said` copying it and `detail` a few plain English words. Most trainings have "
    "none.\n"
    "Return ONLY JSON."
)
REVIEW_MAX_TOKENS: Final = 4_000
_CLAIMS_IN_REPAIR: Final = 12
_QUOTE_MAX: Final = 300

_CLAIM_ROW: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "said": {"type": "string"},
        "claim": {"type": "string"},
        "evidence": {"type": "string"},
    },
    "required": ["said", "claim", "evidence"],
    "additionalProperties": False,
}
_EDIT_ROW: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "edit": {"type": "integer"},
        "kept_in": {"type": "string"},
        "replaced_by": {"type": "string"},
    },
    "required": ["edit", "kept_in", "replaced_by"],
    "additionalProperties": False,
}
_PROBLEM_ROW: Final[dict[str, object]] = {
    "type": "object",
    "properties": {"said": {"type": "string"}, "detail": {"type": "string"}},
    "required": ["said", "detail"],
    "additionalProperties": False,
}
REVIEW_FORMAT: Final[dict[str, object]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "company_training_review",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "claims": {"type": "array", "items": _CLAIM_ROW},
                "owner_edits": {"type": "array", "items": _EDIT_ROW},
                "problems": {"type": "array", "items": _PROBLEM_ROW},
            },
            "required": ["claims", "owner_edits", "problems"],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True, slots=True)
class Findings:
    """What the review and the deterministic checks found in one draft."""

    #: (the training's words, the claim) for each claim no source states.
    unsourced: list[tuple[str, str]] = field(default_factory=list)
    #: The owner's edits (redacted, as the writer read them) the draft drops or contradicts.
    dropped: list[str] = field(default_factory=list)
    #: Sentences the owner took out that the draft puts back.
    reinstated: list[str] = field(default_factory=list)
    #: Stock lines.
    generic: list[str] = field(default_factory=list)
    #: The draft holds a masked detail (`[redacted]`, `[phone ••12]`).
    masked: bool = False
    #: Each owner's fact by its index, with the training's words that now carry it.
    kept: dict[int, str] = field(default_factory=dict)
    #: The owner's facts a newer source replaced, by index.
    superseded: dict[int, str] = field(default_factory=dict)

    @property
    def failing(self) -> bool:
        return bool(
            self.unsourced or self.dropped or self.reinstated or self.generic or self.masked
        )

    def problems(self) -> list[str]:
        """Each finding as one sentence for the repair ask."""
        found = [
            f'"{said}" says {claim}, which nothing the business gave states: say only what '
            "the sources say, or leave it out"
            for said, claim in self.unsourced[:_CLAIMS_IN_REPAIR]
        ]
        found += [
            f'The owner\'s edit "{edit}" is missing or contradicted: carry its facts and '
            "meaning, in clearer words if you can"
            for edit in self.dropped
        ]
        found += [f'"{s}" is something the owner took out: leave it out' for s in self.reinstated]
        found += [
            f'"{said}" is a stock line that would fit any business: say it with this '
            "business's own details, or leave it out"
            for said in self.generic
        ]
        if self.masked:
            found.append(
                "It holds a hidden detail written as [redacted] or [phone ...]: leave that "
                "detail out"
            )
        return found


def figures_in(words: str) -> set[str]:
    """Every run of digits in `words`, in any script, as ASCII; a masked detail's own digits
    (`[phone ••12]`) are not a figure."""
    unmasked = re.sub(r"\[phone [^\]]*\]", " ", words)
    runs, run = set(), ""
    for ch in unmasked:
        digit = unicodedata.decimal(ch, None)
        if digit is None:
            if run:
                runs.add(run)
            run = ""
        else:
            run += str(digit)
    if run:
        runs.add(run)
    return runs


def _quote(value: object) -> str:
    return " ".join(value.split())[:_QUOTE_MAX] if isinstance(value, str) else ""


def checked(
    raw: dict[str, Any], *, training: str, sources: str, edits: OwnerEdits
) -> Findings | None:
    """The review's JSON turned into findings the code decides, not the judge: a claim is
    unsourced unless its evidence is a passage of the sources or the owner's edits; an owner's
    edit is kept only where its `kept_in` is a passage of the training and every figure in it
    is in the training, and replaced only by a passage of the sources. None for an answer
    without the lists, which the ladder counts as no answer."""
    claims, rows, problems = raw.get("claims"), raw.get("owner_edits"), raw.get("problems")
    if not (isinstance(claims, list) and isinstance(rows, list) and isinstance(problems, list)):
        return None
    redacted = [redact(fact.text).text for fact in edits.said]
    grounds = "\n".join([sources, *redacted])
    unsourced = [
        (_quote(row.get("said")), _quote(row.get("claim")))
        for row in claims
        if isinstance(row, dict)
        and _quote(row.get("claim"))
        and not quoted_in(_quote(row.get("evidence")), grounds)
    ]
    by_index = {
        row["edit"]: row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("edit"), int)
    }
    figures = figures_in(training)
    kept: dict[int, str] = {}
    superseded: dict[int, str] = {}
    dropped: list[str] = []
    for index, edit in enumerate(redacted, 1):
        row = by_index.get(index, {})
        where, newer = _quote(row.get("kept_in")), _quote(row.get("replaced_by"))
        if newer and quoted_in(newer, sources) and not quoted_in(newer, edit):
            superseded[index] = newer
        elif where and quoted_in(where, training) and figures_in(edit) <= figures:
            kept[index] = where
        else:
            dropped.append(edit)
    return Findings(
        unsourced=unsourced,
        dropped=dropped,
        reinstated=[s for s in edits.removed if quoted_in(s, training)],
        generic=[
            said for row in problems if isinstance(row, dict) and (said := _quote(row.get("said")))
        ],
        masked=MASK in training or "[phone " in training,
        kept=kept,
        superseded=superseded,
    )


def review_request(*, sources: str, edits: OwnerEdits, training: str) -> str:
    parts = [f"SOURCES:\n{sources}"]
    if edits.said:
        parts.append(f"THE OWNER'S EDITS:\n{_numbered(edits)}")
    parts.append(f"THE TRAINING:\n{training}")
    return "\n\n".join(parts)


# --- the job ------------------------------------------------------------------------------

#: The least time worth starting another pass with, and what is kept back at the end.
_PASS_MIN_S: Final = 20.0
_JOB_MARGIN_S: Final = 30.0
#: Room left under the box after a shortening, so a draft that comes back a little long fits.
_SHORTEN_MARGIN: Final = 200

UNGROUNDED_NOTE: Final = (
    "Pip's new training did not pass its check against your business details, so the last "
    "one stays. Press Rewrite now to try again, or edit it yourself."
)
TOO_LONG_NOTE: Final = (
    "Pip's new training would not fit beside your longest script, so the last one stays. "
    "Shorten that script or the training."
)
#: Why a write was not saved, as the screen shows it, by `reason`.
FAILED_NOTES: Final[dict[str, str]] = {
    "ungrounded": UNGROUNDED_NOTE,
    "too_long": TOO_LONG_NOTE,
}


class _NotWrittenError(Exception):
    """A pass that ended the write without a save: `reason` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class _Run:
    """One write's inputs and what it has spent."""

    tenant_id: UUID
    started: float
    request: str
    sources: str
    edits: OwnerEdits
    ask: str
    tenant_leg: Any
    quota_exhausted: bool
    spent: list[JsonAnswer[Any]] = field(default_factory=list)
    #: Where an item's quote may come from (`training_sections.corpus_of`).
    corpus: str = ""
    #: The parts the first write found no source for (`training_sections.MISSING_PARTS`).
    missing: tuple[str, ...] = ()
    #: The owner's sentences no model may read (`private_edits`), put back word for word.
    verbatim: list[OwnerFact] = field(default_factory=list)

    def timeout(self) -> float:
        left = WORKER_JOB_TIMEOUT_S - _JOB_MARGIN_S - (time.monotonic() - self.started)
        per_request = min(PROPOSAL_REQUEST_TIMEOUT_S, left / ASSIST_LADDER_LEGS)
        if per_request < _PASS_MIN_S:
            raise _NotWrittenError("out_of_time")
        return per_request

    async def write(self, *, tail: str = "", draft: str | None = None, fix: str = "") -> str:
        request = self.request
        if draft is not None:
            request += f"\n\nTHE TRAINING YOU WROTE:\n{draft}"
        if fix:
            request += f"\n\nFIX THESE:\n{fix}"

        def parse(raw: dict[str, Any]) -> str | None:
            built = built_training(raw, self.corpus)
            if not built.text or len(built.text) > company_training.TRAINING_MAX:
                return None
            # Repairs and shortenings rewrite the same material: the first write's answer
            # is the one about what the material holds.
            if not tail:
                self.missing = built.missing
            if built.unsourced:
                log.info("company_training_unsourced_dropped", extra={"items": built.unsourced})
            return built.text

        answer: JsonAnswer[str] = await ask_json(
            request,
            self.ask + tail,
            parse=parse,
            azure_format=_WRITE_FORMAT,
            tenant_leg=self.tenant_leg,
            quota_exhausted=self.quota_exhausted,
            max_tokens=PROPOSAL_MAX_TOKENS,
            temperature=0.3,
            timeout_s=self.timeout(),
        )
        self.spent.append(answer)
        return answer.value

    async def review(self, training: str) -> Findings:
        def parse(raw: dict[str, Any]) -> Findings | None:
            return checked(raw, training=training, sources=self.sources, edits=self.edits)

        answer: JsonAnswer[Findings] = await ask_json(
            review_request(sources=self.sources, edits=self.edits, training=training),
            REVIEW_INSTRUCTION,
            parse=parse,
            azure_format=REVIEW_FORMAT,
            tenant_leg=self.tenant_leg,
            quota_exhausted=self.quota_exhausted,
            max_tokens=REVIEW_MAX_TOKENS,
            temperature=0.2,
            timeout_s=self.timeout(),
        )
        self.spent.append(answer)
        return answer.value

    async def grounded(self, training: str, *, repair: bool) -> tuple[str, Findings]:
        """`training` reviewed, repaired once when `repair` and it fails, reviewed again."""
        findings = await self.review(training)
        if findings.failing and repair:
            log.info("company_training_repairing", extra={"problems": len(findings.problems())})
            fix = "\n".join(f"- {p}" for p in findings.problems())
            training = await self.write(tail=REPAIR_TAIL, draft=training, fix=fix)
            findings = await self.review(training)
        if findings.failing:
            raise _NotWrittenError("ungrounded")
        return training, findings


@dataclass(frozen=True, slots=True)
class _Claim:
    version: int
    training: str
    pip_training: str | None
    owner_edits: Any
    overview: str
    reasons: list[str]


async def _claim(tenant_id: UUID, proposal_id: UUID) -> _Claim | datetime | None:
    """Take the queued write once (the outbox delivers at least once): its inputs, or the
    instant it is due when that is still ahead, or None when it is no longer pending."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT proposal, version, training, pip_training, owner_edits, overview "
                    "FROM company_trainings WHERE tenant_id = :t AND proposal->>'id' = :pid "
                    "AND proposal->>'status' = 'queued' FOR UPDATE"
                ),
                {"t": tenant_id, "pid": str(proposal_id)},
            )
        ).first()
        if row is None:
            return None
        now = datetime.now(UTC)
        due = datetime.fromisoformat(str(row.proposal["due_at"]))
        if due > now:
            return due
        await session.execute(
            text(
                "UPDATE company_trainings SET proposal = proposal || jsonb_build_object("
                "'status', 'drafting', 'claimed_at', CAST(:at AS text)) WHERE tenant_id = :t"
            ),
            {"t": tenant_id, "at": now.isoformat()},
        )
    return _Claim(
        version=int(row.version),
        training=str(row.training or ""),
        pip_training=row.pip_training,
        owner_edits=row.owner_edits,
        overview=str(row.overview or ""),
        reasons=[str(r) for r in row.proposal.get("reasons") or ()],
    )


async def _defer(tenant_id: UUID, proposal_id: UUID, due: datetime) -> None:
    """Run again once the debounce is over. Keyed by the due instant, so each push-back is its
    own delivery and a repeated one is deduped by arq."""
    await enqueue(
        JOB_NAME,
        {"tenant_id": str(tenant_id), "proposal_id": str(proposal_id)},
        job_id=job_id_for(JOB_NAME, str(proposal_id), due.isoformat()),
        _defer_until=due,
    )


async def _meter(
    session: AsyncSession,
    tenant_id: UUID,
    spent: Sequence[JsonAnswer[Any]],
    refusal: ProblemError | None = None,
) -> None:
    """Every pass is money spent, metered in the transaction that settles the write."""
    feature = crm_assist.ASSIST_FEATURE_SCRIPT_DRAFT
    for answer in spent:
        await crm_assist.meter_earlier(
            session, tenant_id=tenant_id, earlier=answer.earlier, feature=feature
        )
        await crm_assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=answer,
            model=answer.model,
            feature=feature,
        )
    if refusal is not None:
        await crm_assist.meter_refusal(
            session, tenant_id=tenant_id, refusal=refusal, feature=feature
        )


async def _settle(
    session: AsyncSession, tenant_id: UUID, proposal_id: UUID, *, failed: str | None
) -> bool:
    """End the pending write: cleared, or marked failed with why. A change that arrived while
    it was being written (`again`) queues the next write instead, so it is never lost. False
    when the write is no longer this one (the owner stopped it)."""
    await lock_tenant_target(session, tenant_id)
    row = (
        await session.execute(
            text(
                "SELECT proposal FROM company_trainings WHERE tenant_id = :t "
                "AND proposal->>'id' = :pid FOR UPDATE"
            ),
            {"t": tenant_id, "pid": str(proposal_id)},
        )
    ).first()
    if row is None:
        return False
    again = [r for r in row.proposal.get("again") or () if r in company_training.WRITE_REASONS]
    record: dict[str, Any] | None = None
    if failed is not None and not again:
        record = {
            **row.proposal,
            "status": "failed",
            "reason": failed,
            "note": FAILED_NOTES.get(failed, company_training.FAILED_NOTE),
        }
    await session.execute(
        text("UPDATE company_trainings SET proposal = CAST(:p AS jsonb) WHERE tenant_id = :t"),
        {"p": None if record is None else json.dumps(record), "t": tenant_id},
    )
    for reason in again:
        await company_training.schedule_write(session, tenant_id, reason=reason)
    return True


async def _fail(
    tenant_id: UUID,
    proposal_id: UUID,
    reason: str,
    spent: Sequence[JsonAnswer[Any]] = (),
    refusal: ProblemError | None = None,
) -> str:
    """Keep the previous training and say why on the screen. A draft that failed its own
    checks is an operator's to see: Pip could not write this client's training."""
    async with tenant_session(tenant_id) as session:
        await _meter(session, tenant_id, spent, refusal)
        await _settle(session, tenant_id, proposal_id, failed=reason)
    log.info("company_training_not_saved", extra={"reason": reason})
    if reason in FAILED_NOTES:
        alert(
            "CORE_LOGIC",
            "company_training_not_saved",
            detail=f"Pip's company training was not saved ({reason}); the previous one stays",
            episode=reason,
            tenant_id=str(tenant_id),
            proposal_id=str(proposal_id),
        )
    return reason


def _last_write(
    claim: _Claim,
    findings: Findings,
    edits: OwnerEdits,
    verbatim: Sequence[OwnerFact],
    *,
    shortened: bool,
    disclosure: Any,
    missing: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "at": datetime.now(UTC).isoformat(),
        "reasons": claim.reasons,
        "owner_edits_kept": len(findings.kept) + len(verbatim),
        "superseded": [edits.said[i - 1].text for i in sorted(findings.superseded)],
        "shortened": shortened,
        "disclosure": disclosure,
        "missing": list(missing),
    }


def _edits_after(
    edits: OwnerEdits, findings: Findings, verbatim: Sequence[OwnerFact]
) -> OwnerEdits:
    """The owner's facts the next rewrite carries: each with where it now landed, less the
    ones newer knowledge replaced, and the private ones as they stand."""
    said = [
        OwnerFact(fact.text, findings.kept.get(index, fact.where))
        for index, fact in enumerate(edits.said, 1)
        if index not in findings.superseded
    ]
    said += [OwnerFact(fact.text, fact.text) for fact in verbatim]
    return OwnerEdits(said, edits.removed)


async def _inputs(tenant_id: UUID, claim: _Claim) -> tuple[str, str, Any, bool] | None:
    """(business, documents, the account's leg, quota spent), or None with nothing to write
    the training from."""
    business, _vertical = await business_context(tenant_id, include_type=False)
    async with tenant_session(tenant_id) as session:
        words = await knowledge_words(session)
        tenant_leg = await account_assist_leg(session)
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    documents = documents_block(words, budget=KNOWLEDGE_DOCUMENT_CHARS)
    # The name alone is no material; the business type on file is left out above, because
    # an account given one by default would have Pip write about a business it is not.
    if not (claim.overview.strip() or documents or len(business.splitlines()) > 1):
        return None
    return business, documents, tenant_leg, quota.at_ceiling or quota.platform_paused


async def draft_company_training(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    del ctx
    tenant_id = UUID(str(payload["tenant_id"]))
    proposal_id = UUID(str(payload["proposal_id"]))
    claim = await _claim(tenant_id, proposal_id)
    if claim is None:
        return "not_pending"
    if isinstance(claim, datetime):
        await _defer(tenant_id, proposal_id, claim)
        return "deferred"
    started = time.monotonic()
    spent: list[JsonAnswer[Any]] = []
    try:
        inputs = await _inputs(tenant_id, claim)
        if inputs is None:
            async with tenant_session(tenant_id) as session:
                await _settle(session, tenant_id, proposal_id, failed=None)
            log.info("company_training_no_material")
            return "no_material"
        business, documents, tenant_leg, quota_exhausted = inputs
        edits, verbatim = private_edits(
            carried_edits(claim.owner_edits, claim.pip_training, claim.training)
        )
        current = claim.training
        for fact in verbatim:
            current = current.replace(fact.text, "")
        ask = TRAINING_ASK + (EDIT_TAIL if current.strip() else "")
        run = _Run(
            tenant_id=tenant_id,
            started=started,
            request=request_text(
                business=business,
                overview=claim.overview,
                documents=documents,
                current=current.strip() or None,
                edits=edits,
            ),
            sources=review_sources(business=business, overview=claim.overview, documents=documents),
            corpus=corpus_of(
                review_sources(business=business, overview=claim.overview, documents=documents),
                [fact.text for fact in edits.said],
            ),
            edits=edits,
            ask=ask + (OWNER_EDITS_TAIL if edits.said or edits.removed else ""),
            tenant_leg=tenant_leg,
            quota_exhausted=quota_exhausted,
            spent=spent,
            verbatim=verbatim,
        )
        return await _written(run, claim, proposal_id)
    except _NotWrittenError as stopped:
        return await _fail(tenant_id, proposal_id, stopped.reason, spent)
    except ProblemError as refused:
        log.info("company_training_refused", extra={"reason": refused.code})
        return await _fail(tenant_id, proposal_id, refused.code, spent, refused)
    except Exception:
        log.exception("company_training_crashed")
        await _fail(tenant_id, proposal_id, "crashed", spent)
        return "failed"


async def _written(run: _Run, claim: _Claim, proposal_id: UUID) -> str:
    """Write, check, fit and save one training."""
    tenant_id = run.tenant_id
    written, findings = await run.grounded(await run.write(), repair=True)
    training = with_verbatim(written, run.verbatim)
    shortened = False
    async with tenant_session(tenant_id) as session:
        over = await company_training.overflow_of(session, tenant_id, training)
    if over is not None:
        limit = max(len(written) - over.over - _SHORTEN_MARGIN, 0)
        log.info("company_training_shortening", extra={"over": over.over})
        written, findings = await run.grounded(
            await run.write(tail=SHORTEN_TAIL.format(limit=limit), draft=written),
            repair=False,
        )
        training = with_verbatim(written, run.verbatim)
        shortened = True
    disclosure = run.spent[0].capability.disclosure if run.spent else None
    too_long = False
    async with tenant_session(tenant_id) as session:
        await _meter(session, tenant_id, run.spent)
        await lock_tenant_target(session, tenant_id)
        pending = (
            await session.execute(
                text(
                    "SELECT 1 FROM company_trainings WHERE tenant_id = :t "
                    "AND proposal->>'id' = :pid FOR UPDATE"
                ),
                {"t": tenant_id, "pid": str(proposal_id)},
            )
        ).first()
        if pending is None:
            # Stopped by the owner while it was written: paid for, never saved.
            log.info("company_training_stopped")
            return "not_pending"
        try:
            async with session.begin_nested():
                version = await company_training.save_written(
                    session,
                    tenant_id,
                    training=training,
                    base_version=claim.version,
                    owner_edits=_edits_after(run.edits, findings, run.verbatim).stored(),
                    last_write=_last_write(
                        claim,
                        findings,
                        run.edits,
                        run.verbatim,
                        shortened=shortened,
                        disclosure=disclosure,
                        missing=run.missing,
                    ),
                )
        except ProblemError as refused:
            # A script grew between the measure above and this save: the next write fits it.
            if refused.code != "company_training_too_long":
                raise
            version, too_long = None, True
        if version is None and not too_long:
            # The owner saved while Pip wrote: their text stands, and the change Pip was
            # writing for is written again over it.
            await _settle(session, tenant_id, proposal_id, failed=None)
            for reason in claim.reasons:
                if reason in company_training.WRITE_REASONS:
                    await company_training.schedule_write(session, tenant_id, reason=reason)
        elif version is not None:
            await _settle(session, tenant_id, proposal_id, failed=None)
            await write_audit(
                session,
                action="company_training.written",
                actor_type="system",
                tenant_id=tenant_id,
                object_type="company_training",
                object_id=str(tenant_id),
                summary={
                    "version": version,
                    "reasons": claim.reasons,
                    "owner_edits_kept": len(findings.kept),
                    "superseded": len(findings.superseded),
                    "shortened": shortened,
                },
            )
    if too_long:
        return await _fail(tenant_id, proposal_id, "too_long")
    if version is None:
        log.info("company_training_owner_saved_first")
        return "superseded"
    log.info(
        "company_training_written",
        extra={"version": version, "kept": len(findings.kept), "shortened": shortened},
    )
    return "saved"


__all__ = [
    "FAILED_NOTES",
    "JOB_NAME",
    "KNOWLEDGE_SOURCES_READ",
    "REVIEW_INSTRUCTION",
    "TRAINING_ASK",
    "Findings",
    "OwnerEdits",
    "OwnerFact",
    "carried_edits",
    "checked",
    "draft_company_training",
    "edits_since",
    "knowledge_words",
    "request_text",
    "review_sources",
    "sentences",
]
