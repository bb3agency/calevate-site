"""How a LEAD becomes retrievable chunks: which fields, how they are labelled, what is left out.

This is the `lead` scope's half of the caller-chunk store — the pure function that turns one
lead's captured extraction payload into the rows an ingestion sweep embeds. It holds no SQL,
opens no session and knows nothing about the table, for the reason `kb/service.chunk_text`
and `retrieval/call_projection.py` are pure functions too: what gets embedded is where
retrieval quality AND data minimisation are decided, and a decision that can only be
exercised through a database is a decision nobody tests.

--------------------------------------------------------------------------------
AN EMBEDDING OF A CALLER'S WORDS IS A COPY OF THEIR WORDS
--------------------------------------------------------------------------------
`leads.data` is not a client's own prose like a knowledge base — it is what a caller told
an agent, structured. A vector is not anonymous for being floats (embedding inversion
recovers substantial fragments of the input text), and the sparse key is literally the
caller's lexemes. So every field admitted below is a field this product is choosing to
COPY, and the default here is exclusion: a field earns its place by being something a
person would search for in words, not by being present.

WHAT A LEAD CONTRIBUTES, and the four exclusions, each of which is a decision:

* **INCLUDED: `text` fields that do not ask for a phone number, and `enum` fields.** These
  are the answers a person searches in prose — "3BHK", "Gachibowli", "site visit on the
  weekend", "budget flexible". `is_phone_field` (the schema's own key/label/reason hint,
  the same predicate `coerce_value` uses to decide a field holds a number) is what keeps an
  "alternate contact" text field out; it is an identifier, and identifiers are what the
  Leads screen already looks up exactly.
* **EXCLUDED: `leads.phone_e164` and `leads.name`.** The caller's identifiers. They are
  what the existing screen search already matches (`crm/service._lead_scope`: `name ILIKE`
  + phone suffix), exactly and cheaply, so embedding them buys nothing retrieval could not
  already do — and a name index built out of vectors is a name index that erasure has to
  chase. Hard rule 6's reasoning applied to a store rather than to a log line.
* **EXCLUDED: `number`, `date` and `bool` fields.** Two reasons, and the first is the
  stronger. (1) They are already answerable EXACTLY: numbers and dates are filters, and a
  bool is a chip. An embedding of "42" or "true" is a point in space that means nothing and
  is close to every other number in the corpus, so it degrades the neighbours it crowds out
  of the top-k. (2) Minimisation: a date of birth, a household size and an income are the
  fields most likely to be sensitive and least likely to be typed into a search box.
  ⚠ A number's UNITS live in its label ("Budget in lakhs"), so a person searching "budget
  around 80 lakhs" is served by the label of a text field that captured it in words, and by
  the field filters otherwise — never by pretending a scalar embeds.
* **EXCLUDED: `lead_events`.** VERIFIED, not assumed: `LEAD_EVENT_TYPES` admits a `note`
  type but nothing in this repository writes free text into one — `crm/service._project_event`
  renders a `note` as the bare word "Note" unless it is a `kind: "blocked"` row, whose
  payload carries a rule CODE (`ingest/service.py:535`). There is no user-authored note
  body to index today. When one is added it belongs in this projection, and this paragraph
  is what the person adding it should find.

**NO SECOND REDACTION PASS HERE, DELIBERATELY.** `coerce_value` already refuses a
phone-shaped value in a field that does not ask for one ("a phone number in the name field
is PII nobody redacts") and canonicalises it in one that does, so the write path is where
that rule lives. Running `workers/redaction.redact` again over the value would make the
stored retrieval key differ from what the client's own Leads table shows them — one lead,
two texts — while adding nothing the write path did not already refuse. The rendering
surfaces still redact on the way OUT (`copilot/tools._clean`), which is where a mask
belongs: at the edge, not in the index.

--------------------------------------------------------------------------------
THE LABEL IS EMBEDDED WITH THE VALUE, AND THAT IS A DEPARTURE FROM `embedding_input`
--------------------------------------------------------------------------------
`kb_embeddings.embedding_input` refuses to write "English:" in front of a gloss because
that label names our own PIPELINE — a token competing with the ones that carry meaning.
A lead field's label is the opposite kind, and `call_projection`'s speaker labels make the
same distinction: "Gachibowli" alone is a token, "Locality: Gachibowli" is a fact, and the
question this scope exists to answer ("leads who asked about a 3BHK in Gachibowli") is
asked in the vocabulary of the client's own field labels. The label is also the only thing
that distinguishes two fields holding the same word.

--------------------------------------------------------------------------------
THE SCHEMA IS PER TENANT, PER AGENT AND PER VERSION — SO THE FIELD LIST IS AN INPUT
--------------------------------------------------------------------------------
`leads.data` is keyed by whatever extraction schema was live when it was captured
(`leads.schema_version`), and the client edits that schema. So this function takes the
resolved field list and projects only what it can name. A `data` key with no field in the
list is DROPPED and COUNTED (`LeadProjection.unknown_keys`) rather than guessed at, which
is `crm/columns.resolve`'s rule for a stale column reference and it is the safe direction
here for a second reason: an unnamed key could be a phone field from a schema the client
has since edited, and a guessed label cannot apply the phone exclusion above.

--------------------------------------------------------------------------------
AN ERASED LEAD PROJECTS TO NOTHING
--------------------------------------------------------------------------------
A DPDP erasure does not delete a lead. It sets `data = '{}'::jsonb`, NULLs the name and
anonymizes the phone in place (`workers/retention.execute_deletion_request`,
`_erase_tenant_leads`, `_LEAD_SQL`), so no `CASCADE` ever fires and the erased state of a
lead is an EMPTY payload. Every entry point here therefore yields nothing for an empty
payload and skips a blank value — that is the *belt*, which stops a re-projection racing an
erasure from putting the sentence back. The braces are that both erasure paths and the
`lead` retention clock DELETE these rows outright (`crm/lead_chunks.py`).

HARD RULE 6: nothing here logs. It is a pure function over caller-supplied values, and the
only safe amount of that in a log line is none — the callers log ids and counts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from calevate_shared.extraction import MAX_TEXT_LEN, ExtractionField, is_phone_field

from apps.api.kb.service import MAX_CHUNK_CHARS, MIN_CHUNK_CHARS

#: `caller_chunks.subject_kind` for this scope. Spelled once, here, because it is also the
#: `retention_policies.data_category` this scope's rows expire on (`lead`) and the two must
#: not become two vocabularies — the argument `RetrievalTier` makes about `kb_retrieval_logs`.
LEAD_SUBJECT_KIND: Final = "lead"

#: The field types this projection embeds. A closed set rather than a "not in (...)" test,
#: so a new member of `FieldType` is EXCLUDED until somebody decides it should not be —
#: which is the direction a store of caller personal data should fail in.
PROJECTED_TYPES: Final[frozenset[str]] = frozenset({"text", "enum"})


@dataclass(frozen=True, slots=True)
class LeadChunk:
    """One projected chunk of one lead: what to embed, and which fields it covers."""

    #: Position within THIS lead, 0-based and dense. The second half of the store's natural
    #: key (`caller_chunks UNIQUE (subject_kind, subject_id, idx)` — migration
    #: `c6b1f0d47e83`), so re-projecting an edited lead overwrites its own slots instead of
    #: accumulating a second set that would each take a place in the top-k.
    idx: int
    #: The text that gets embedded AND from which the sparse key is built, already labelled.
    text: str
    #: Which schema keys this chunk covers, in projection order. A FACT on the row rather
    #: than a re-parse of the prose: it is what lets a hit be explained ("matched on
    #: Requirement, Location") without the store holding a second copy of the value.
    keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LeadProjection:
    """One lead's whole projection, plus what it could not name."""

    chunks: tuple[LeadChunk, ...]
    #: `data` keys with no field in the resolved schema. Counted for the caller's log line
    #: (a rising number means leads are being captured against a schema this projection
    #: cannot read), never rendered into a chunk.
    unknown_keys: tuple[str, ...]


def _value_text(raw: Any) -> str | None:
    """One field's value as the words that go in a chunk, or None to skip it.

    `str(raw).strip()` and no coercion: `validate_extraction` already coerced this value
    when the extraction was written, and re-coercing here would be a second interpretation
    of one payload — the drift CLAUDE.md calls a defect even when both copies agree. A
    non-string that reached a text field (an older schema version, a manual edit) is
    rendered as it stands rather than dropped, because dropping is silent.
    """
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    # The cap is the EXTRACTION's own (`MAX_TEXT_LEN` = 500, enforced by `coerce_value`),
    # so this is a backstop for a row written before that guard rather than a second
    # policy. It truncates rather than drops: a long value is still the caller's answer,
    # and half of it retrieves better than none of it.
    return value[:MAX_TEXT_LEN]


def project_field(field: ExtractionField, raw: Any) -> str | None:
    """One `label: value` line, or None when this field contributes nothing.

    The single place the inclusion rules are applied, so the projection and anything that
    later asks "would this field be embedded?" cannot disagree.

    A bool is refused BY VALUE as well as by type, because `str(True)` is `"True"` — a word
    that embeds like a word — and a payload written under an older schema can carry one
    under a key the current schema calls text.
    """
    if field.type not in PROJECTED_TYPES or is_phone_field(field) or isinstance(raw, bool):
        return None
    value = _value_text(raw)
    return None if value is None else f"{field.label}: {value}"


def project_lead(
    fields: Sequence[ExtractionField], data: Mapping[str, Any] | None
) -> LeadProjection:
    """ONE lead's projection: its embeddable fields, one line each, in SCHEMA order.

    Schema order, not `data` order: the field list is the order the client chose on their
    own Leads table, so two leads captured under one schema project identically and a
    dict's insertion order never moves a boundary.

    **MOST LEADS ARE ONE CHUNK, AND THE PACKING IS FOR THE ONES THAT ARE NOT.** A lead is a
    short structured record about one enquiry, so the whole of it usually fits one vector —
    which is what a query like "a 3BHK in Gachibowli" wants, since it is the CONJUNCTION of
    two fields rather than a moment inside a conversation. The cap only bites on a schema
    with dozens of long text fields, where one vector would average them into nothing;
    `call_projection`'s argument, reached from the other end.

    Returning a value and writing nothing is what makes every decision above testable
    without a database, and what lets the ingestion sweep own the transaction, the
    idempotency key and the budget — one mechanism for those, not one per scope.
    """
    payload = data or {}
    chunks: list[LeadChunk] = []
    window: list[tuple[str, str]] = []
    size = 0
    for field in fields:
        line = project_field(field, payload.get(field.key))
        if line is None:
            continue
        # `+ 1` for the newline this line costs once it is not first in the window —
        # charged only when there IS a joiner, `call_projection.project_turns`' fix for the
        # zero-length chunk a flat charge used to write.
        cost = len(line) + (1 if window else 0)
        if window and size + cost > MAX_CHUNK_CHARS:
            chunks.append(_emit(window, len(chunks)))
            window, size, cost = [], 0, len(line)
        window.append((field.key, line))
        size += cost
    if window:
        chunks.append(_emit(window, len(chunks)))
    _merge_stub_tail(chunks)
    known = {field.key for field in fields}
    return LeadProjection(
        chunks=tuple(chunks),
        unknown_keys=tuple(key for key in payload if key not in known),
    )


def _emit(window: Sequence[tuple[str, str]], idx: int) -> LeadChunk:
    return LeadChunk(
        idx=idx,
        text="\n".join(line for _, line in window),
        keys=tuple(key for key, _ in window),
    )


def _merge_stub_tail(chunks: list[LeadChunk]) -> None:
    """Fold a stub last chunk into its predecessor, in place.

    `chunk_text`'s rule for `chunk_text`'s reason: a one-line final chunk is a vector of a
    single short answer ("Timeline: this month") that sits close to the same line on every
    other lead in the account, so it retrieves noisily while taking a top-k slot. This is
    the one place a chunk may exceed the cap, by at most `MIN_CHUNK_CHARS` plus a newline.
    """
    if len(chunks) < 2 or len(chunks[-1].text) >= MIN_CHUNK_CHARS:
        return
    tail = chunks.pop()
    head = chunks.pop()
    chunks.append(
        LeadChunk(idx=head.idx, text=f"{head.text}\n{tail.text}", keys=head.keys + tail.keys)
    )


__all__ = [
    "LEAD_SUBJECT_KIND",
    "PROJECTED_TYPES",
    "LeadChunk",
    "LeadProjection",
    "project_field",
    "project_lead",
]
