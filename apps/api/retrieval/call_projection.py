"""How a CALL becomes retrievable chunks: the windowing, the speaker labels, the marker.

This is the `transcript` scope's half of the caller-chunk store — the pure function that
turns one call's redacted turns and its summary into the rows an ingestion sweep embeds. It
holds no SQL, opens no session and knows nothing about the table, for the reason
`kb/service.chunk_text` is a pure function too: chunking is where retrieval quality is
decided, and a decision that can only be exercised through a database is a decision nobody
tests.

--------------------------------------------------------------------------------
IT READS `text_redacted`, NEVER `text`
--------------------------------------------------------------------------------
`transcript_turns.text` is the raw ASR output and is gated behind a role check plus an
`audit_log` write (hard rule 5, `crm/models.TranscriptTurn`). Every derived surface in this
repository reads `text_redacted` — the post-call pipeline's gap detector does
(`insights/service.record_call_gaps`), the CRM detail does — and so does this. `Turn.text`
is therefore not a field on the input model at all: the raw column has no name here to be
read by accident, which is a stronger guarantee than a comment saying not to.

--------------------------------------------------------------------------------
WHY A WINDOW OF TURNS, AND NOT A TURN AND NOT A CALL
--------------------------------------------------------------------------------
**A per-TURN vector is mostly noise.** A conversation's turn distribution is dominated by
backchannel — "haan", "yes", "okay", "one moment" — and an embedding of "yes" is a point in
space that is weakly close to everything and diagnostic of nothing. Worse, it takes a slot
in a top-k that a real exchange wanted: `retrieval/pgvector.py` fuses two arms at depth 20,
so a hundred one-word vectors per call do not merely fail to help, they crowd out the rows
that would have answered.

**A per-CALL vector is too coarse to answer the question this scope exists for.** "Which
callers asked about weekend appointments" is a question about a MOMENT inside a call that
was mostly about something else. One vector over a twenty-minute conversation is an average
of every topic in it, and averaging is precisely how a specific question stops being
retrievable — the single-vector-per-document failure the chunking literature exists about.

So: **a window of consecutive turns, capped at `MAX_CHUNK_CHARS`** — the same cap
`kb/service.chunk_text` packs prose to, IMPORTED rather than re-typed. Two chunkers with two
copies of one number is the drift CLAUDE.md calls a defect even when both copies agree, and
the number is a property of the thing both feed: one `text-embedding-3-small` vector at
`EMBEDDING_DIMS`, holding one idea. The cap is what makes a window "a topic", and the
boundary rule below is what makes it "an exchange".

--------------------------------------------------------------------------------
THE BOUNDARY RULE: A CHUNK ENDS ON AN ANSWER
--------------------------------------------------------------------------------
Greedy packing alone puts a boundary wherever the cap happens to fall, and the cap does not
know what a conversation is. The failure that costs retrieval quality is specific and
one-directional: a window that ENDS on a caller's question leaves that question separated
from the agent's answer, so the chunk that matches "do you open on Saturdays?" contains no
Saturday hours, and the chunk that contains the hours never matched the question.

So when a window closes, any TRAILING RUN OF CALLER TURNS is pushed into the next window
(`_settle`). Every chunk therefore ends on an agent turn or on the end of the call, and every
caller question is stored with whatever the agent said next. The rule is one-sided on
purpose: nothing is done about a window that STARTS mid-answer, because a partial answer
still contains the words the question is about, whereas a question with no answer contains
none of them.

--------------------------------------------------------------------------------
SPEAKER: LABELLED IN THE TEXT, AND NOT SPLIT INTO TWO VECTORS
--------------------------------------------------------------------------------
Three options were live. **Dropping the speaker** loses the only thing that distinguishes
"the caller asked about weekend appointments" from "the agent mentioned weekend
appointments" — the first is a demand signal a client would act on, the second is our own
script talking back. That distinction is the entire product value of this scope, so an
undifferentiated blob is not a cheaper version of it, it is a different and useless feature.
**A vector per speaker** doubles the rows, halves each one's context (a question without its
answer is exactly what the boundary rule above works to avoid), and gives the fusion two
arms of the same corpus to double-count.

So the speaker is **a two-token English prefix on each turn**, from `_SPEAKER_LABELS`.

**AND THIS IS A DELIBERATE DEPARTURE FROM `kb_embeddings.embedding_input`, WHICH ARGUES THE
OPPOSITE FOR ITS OWN CASE.** That function refuses to write "English:" in front of a gloss
because the label names the text's PROVENANCE, which is a fact about our pipeline and not
about the client's business — a token competing with the ones that carry meaning. A speaker
label is the other kind: who said a sentence is part of what the sentence MEANS in a
dialogue, and it is the axis the queries this scope serves are asked along. The two
decisions agree on the rule (a label earns its tokens only if it is signal) and differ
because the labels differ.

The roles are also kept as a fact on the chunk (`CallChunk.speakers`), so a store can filter
or a reader can explain a hit without re-parsing the prose it embedded.

--------------------------------------------------------------------------------
THE MARKER, AND WHY IT IS AN INPUT RATHER THAN A CONSTANT
--------------------------------------------------------------------------------
An erasure does not delete a call — it overwrites `transcript_turns.text_redacted` with
`retention.REDACTED_MARK` and sets `calls.summary = NULL`, keeping the row as billing
evidence. So the erased state of a call is a turn whose text IS the marker, and projecting
it would write "[erased]" into a vector store, or — far worse, on a re-projection that
raced an erasure — leave a stale vector of the real sentence sitting beside it. Every entry
point here therefore SKIPS a marker turn and a blank one, and a call whose every turn is
marked projects to nothing at all.

That is the *belt*. The braces are that erasure and retention delete these rows outright
(`workers/retention.py`); this function is what stops a later re-projection from putting
them back, which a `CASCADE` cannot do because nothing is ever deleted for it to follow.

`mark` is a parameter rather than an import so this module does not depend on the worker
package for a string, exactly as `insights/service.scrub_quotes_for_calls` takes it.

HARD RULE 6: nothing here logs. It is a pure function over caller utterances, and the only
safe amount of that in a log line is none — the callers do the logging, with ids and counts.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid5

from apps.api.kb.service import MAX_CHUNK_CHARS, MIN_CHUNK_CHARS, chunk_text
from apps.api.retrieval.models import SUBJECT_CALL_SUMMARY, SUBJECT_CALL_TURN

#: What each speaker is called in the embedded text. The values are the `speaker` column's
#: closed vocabulary (`crm/models.SPEAKERS`) and the labels are English because the
#: embedding model is; a Telugu label would be two tokens of Telugu attached to every chunk
#: of every call, which is a constant offset in the wrong space.
#:
#: A speaker the enum does not know is labelled by its own name rather than dropped — an
#: unknown role is a schema change somebody made upstream, and silently un-attributing the
#: text would hide it while degrading exactly the axis this module exists to preserve.
#: `crm/models.SPEAKERS` is the closed vocabulary and this is the one role the boundary
#: rule names, so it is spelled once. Imported from the model would drag the whole CRM
#: table module into a pure function; the enum is two values and is pinned by
#: `call_projection_test.py` against `crm.models.SPEAKERS`, which is the check that keeps
#: them in step without the import.
_CALLER: Final = "caller"
_AGENT: Final = "agent"

_SPEAKER_LABELS: Final[dict[str, str]] = {_CALLER: "Caller", _AGENT: "Agent"}

#: `caller_chunks.subject_kind` for the two things a call contributes, IMPORTED from the
#: store's own vocabulary (`retrieval/models.py`) rather than spelled again here. Aliased
#: only so this module reads in its own terms; the values have one author, because two
#: spellings of one discriminator is how a typo becomes a scope nothing sweeps.
#:
#: They are two kinds and not one because they are not the same evidence. A turn window is
#: what was actually SAID, verbatim after redaction. A summary is a MODEL's retelling of
#: it, and a reader who cannot tell them apart will quote a paraphrase to a client as if a
#: caller had said it. Two values also let a client search one and not the other.
#:
#: The summary is projected at all because it is the only chunk carrying the shape of a
#: WHOLE call ("caller wanted a refund and was transferred"), which no window of turns
#: contains — and `retention.DERIVED_COPIES` already classifies `calls.summary` as
#: transcript-class personal data on the transcript clock, so it costs no new policy.
#: `models.SUBJECT_RETENTION` is what files both on that clock; this module does not choose
#: a retention category, which is deliberate — a scope that could choose its own could file
#: a caller's sentence on the 1095-day CRM clock by naming itself a lead.
SUBJECT_KIND_TURNS: Final = SUBJECT_CALL_TURN
SUBJECT_KIND_SUMMARY: Final = SUBJECT_CALL_SUMMARY
SUBJECT_KINDS: Final[tuple[str, ...]] = (SUBJECT_KIND_TURNS, SUBJECT_KIND_SUMMARY)

#: The uuid5 namespace every transcript-scope `subject_id` is minted under.
#:
#: A CONSTANT NAMESPACE AND A VERSIONED NAME STRING, so the id is a pure function of
#: (call, window position) and a re-projection of an unchanged call writes the same ids —
#: which is what makes `ON CONFLICT (subject_kind, subject_id, idx)` idempotent instead of
#: accumulating a second set of rows that would each take a slot in the top-k.
#:
#: **NOT the turn's own id, and that is decision (B) rather than a preference.**
#: `retention._TRANSCRIPT_DELETE_SQL` genuinely DELETEs `transcript_turns` rows when a
#: tenant's `transcript` policy action is `delete`, so a `subject_id` pointing at one would
#: dangle on a schedule. `call_id` survives — a call is kept as billing evidence under an
#: FK RESTRICT from `usage_events` — and the window's first turn INDEX is a small integer on
#: the call, not a row that can be removed from under it.
#:
#: `uuid5` rather than this repo's usual `uuid7` because this is not a primary key and is
#: not sortable-by-time: it is a content-addressed idempotency key, and the whole value of
#: it is that the same input yields the same id on every tick for ever.
SUBJECT_NAMESPACE: Final = UUID("6f1a1e2c-5c62-5a2f-9d3e-0b5a7c4d81f0")


@dataclass(frozen=True, slots=True)
class Turn:
    """One transcript turn, reduced to the three fields a projection may see.

    **THERE IS NO `text` FIELD, AND THAT IS THE POINT** (hard rule 5). The raw column is
    role-gated and audited; the projection reads `text_redacted` like every other derived
    surface. A model with no name for the raw column cannot read it by a typo.
    """

    idx: int
    speaker: str
    text_redacted: str | None


@dataclass(frozen=True, slots=True)
class CallChunk:
    """One projected chunk of one call: what to embed, and what it came from."""

    #: `caller_chunks.subject_kind` — one of `SUBJECT_KINDS`.
    subject_kind: str
    #: Position within THIS call, 0-based and dense, summary last. The stable half of the
    #: store's natural key (`call_id`, `idx`), so a re-projection of an unchanged call
    #: overwrites its own rows instead of accumulating a second set that would each take a
    #: slot in the top-k — `kb_chunks`' `UNIQUE (document_id)` argument, on a call.
    idx: int
    #: The text that gets embedded AND from which the sparse key is built. Already labelled
    #: and already redacted.
    text: str
    #: The turn range this chunk covers, so a hit can be shown in place. `None` on a
    #: summary chunk, which covers the call rather than any span of it.
    first_turn_idx: int | None
    last_turn_idx: int | None
    #: Which roles speak in this chunk, in first-appearance order. A FACT rather than a
    #: filter this module applies: a caller-only chunk is legitimate (the call ended before
    #: the agent replied) and dropping it would lose the last thing that caller said.
    speakers: tuple[str, ...]


def label_turn(speaker: str, text: str) -> str:
    """One turn as it appears inside a chunk: `Caller: ...`."""
    return f"{_SPEAKER_LABELS.get(speaker, speaker)}: {text}"


def _usable(turns: Iterable[Turn], *, mark: str) -> list[Turn]:
    """The turns a projection may embed: redacted text, present, and not the erasure mark.

    A turn whose `text_redacted` is NULL is skipped rather than falling back to `text` —
    the fallback is the hard-rule-5 violation this module is shaped to make unavailable,
    and a null redaction means the redactor has not run, which is a pipeline state and not
    a licence.
    """
    usable: list[Turn] = []
    for turn in turns:
        body = (turn.text_redacted or "").strip()
        if not body or body == mark:
            continue
        usable.append(Turn(idx=turn.idx, speaker=turn.speaker, text_redacted=body))
    return usable


def _fragments(turn: Turn) -> list[Turn]:
    """One turn as one record — or several, when its own text is longer than the cap.

    `kb/service.chunk_text` does the splitting rather than a second splitter written here:
    it packs to the same cap, breaks on sentence ends (including the Devanagari danda), and
    is TESTED LOSSLESS, which is the property that matters most on this corpus. A dropped
    tail is a caller sentence that is silently unsearchable, and nothing downstream can
    detect it — the exact defect that function's docstring records having shipped once.

    Every fragment keeps the turn's own `idx` and speaker, because they ARE that turn: the
    packing and the boundary rule below then treat a split long turn exactly as they treat
    an unsplit one, with no second code path to keep in step.
    """
    body = turn.text_redacted or ""
    if len(body) <= MAX_CHUNK_CHARS:
        return [turn]
    return [
        Turn(idx=turn.idx, speaker=turn.speaker, text_redacted=piece) for piece in chunk_text(body)
    ]


def _settle(window: list[Turn]) -> tuple[list[Turn], list[Turn]]:
    """Split a full window into (what to emit, what to carry into the next one).

    THE BOUNDARY RULE, and the whole of it: a trailing run of CALLER turns is carried
    forward so the chunk ends on an answer. A window that is ALL caller turns is emitted
    unchanged — carrying it forward whole would rebuild the identical window on the next
    pass and never terminate, and a chunk that ends on a question beats a loop.
    """
    cut = len(window)
    while cut > 0 and window[cut - 1].speaker == _CALLER:
        cut -= 1
    if cut == 0:
        return window, []
    return window[:cut], window[cut:]


def _emit(window: Sequence[Turn], idx: int) -> CallChunk:
    """One window as a chunk: the labelled text, the span it covers, the roles in it."""
    speakers: list[str] = []
    for turn in window:
        if turn.speaker not in speakers:
            speakers.append(turn.speaker)
    return CallChunk(
        subject_kind=SUBJECT_KIND_TURNS,
        idx=idx,
        text="\n".join(label_turn(t.speaker, t.text_redacted or "") for t in window),
        first_turn_idx=window[0].idx,
        last_turn_idx=window[-1].idx,
        speakers=tuple(speakers),
    )


def _merge_stub_tail(chunks: list[CallChunk]) -> None:
    """Fold a stub last chunk into its predecessor, in place.

    `chunk_text`'s rule, for `chunk_text`'s reason and one of this corpus's own: a two-word
    final chunk retrieves noisily, and on a call it is almost always "Agent: Thank you,
    goodbye." — a vector that is close to the end of every call ever recorded. This is the
    one place a chunk may exceed the cap, by at most `MIN_CHUNK_CHARS` plus a newline.
    """
    if len(chunks) < 2 or len(chunks[-1].text) >= MIN_CHUNK_CHARS:
        return
    tail = chunks.pop()
    head = chunks.pop()
    chunks.append(
        CallChunk(
            subject_kind=SUBJECT_KIND_TURNS,
            idx=head.idx,
            text=f"{head.text}\n{tail.text}",
            first_turn_idx=head.first_turn_idx,
            last_turn_idx=tail.last_turn_idx,
            speakers=head.speakers + tuple(s for s in tail.speakers if s not in head.speakers),
        )
    )


def project_turns(turns: Sequence[Turn], *, mark: str) -> list[CallChunk]:
    """The windows of one call's turns. See the module docstring for every decision here.

    Greedy packing to `MAX_CHUNK_CHARS`, with `_settle`'s trailing-question carry, and a
    stub tail folded into its predecessor.
    """
    pieces = [fragment for turn in _usable(turns, mark=mark) for fragment in _fragments(turn)]
    chunks: list[CallChunk] = []
    at = 0
    while at < len(pieces):
        window: list[Turn] = []
        size = 0
        while at < len(pieces):
            # `+ 1` for the newline this fragment costs once it is not the first in the
            # window. Charged only when there IS a joiner, `chunk_text`'s fix for the
            # zero-length chunk a flat charge used to write.
            cost = len(label_turn(pieces[at].speaker, pieces[at].text_redacted or "")) + (
                1 if window else 0
            )
            if window and size + cost > MAX_CHUNK_CHARS:
                break
            window.append(pieces[at])
            size += cost
            at += 1
        # SETTLED ONLY WHEN THERE IS A NEXT WINDOW TO CARRY INTO. The final window is
        # emitted whole: a question the call ended on is still the caller asking it, and
        # there is no answer anywhere to reunite it with.
        emitted, carried = _settle(window) if at < len(pieces) else (window, [])
        chunks.append(_emit(emitted, len(chunks)))
        at -= len(carried)
    _merge_stub_tail(chunks)
    return chunks


def project_summary(summary: str | None, *, idx: int, mark: str) -> CallChunk | None:
    """`calls.summary` as its own chunk, or None when there is nothing to project.

    NULL IS THE ERASED STATE HERE, not the marker: `_SUMMARY_SQL` and both erasure paths
    set `summary = NULL` rather than marking it, because summary is free prose with no
    shape worth keeping. The marker is checked anyway — one function that recognises every
    way a call can be empty is cheaper to keep true than two that each know half.
    """
    body = (summary or "").strip()
    if not body or body == mark:
        return None
    return CallChunk(
        subject_kind=SUBJECT_KIND_SUMMARY,
        idx=idx,
        # Labelled, for the same reason a turn is: without it the model embedding this
        # cannot tell our retelling from the caller's own words, and neither can a reader
        # who is shown the hit.
        text=f"Summary: {body}",
        first_turn_idx=None,
        last_turn_idx=None,
        speakers=(),
    )


def project_call(turns: Sequence[Turn], *, summary: str | None, mark: str) -> list[CallChunk]:
    """ONE call's whole projection: its turn windows, then its summary. Ordered, dense idx.

    Returning a LIST and not writing anything is what makes the chunking decisions above
    testable without a database, and what lets the ingestion sweep own the transaction, the
    idempotency key and the budget — one mechanism for those, not one per scope.
    """
    chunks = project_turns(turns, mark=mark)
    summary_chunk = project_summary(summary, idx=len(chunks), mark=mark)
    if summary_chunk is not None:
        chunks.append(summary_chunk)
    return chunks


def subject_id_for(call_id: UUID, chunk: CallChunk) -> UUID:
    """The store's idempotency key for one projected chunk. Deterministic, for ever.

    The name is versioned (`v1`) because a change to the WINDOWING changes which chunk a
    given `(call, first turn)` pair denotes. Bumping it would orphan every existing row
    rather than silently overwrite rows whose vectors were bought for different text — so
    the version is here to be bumped deliberately, with the re-projection that implies.

    A summary has no window, so it is minted from the call alone: one summary per call, and
    a re-summarised call overwrites its own row.
    """
    if chunk.subject_kind == SUBJECT_KIND_SUMMARY:
        return uuid5(SUBJECT_NAMESPACE, f"v1/{chunk.subject_kind}/{call_id}")
    return uuid5(SUBJECT_NAMESPACE, f"v1/{chunk.subject_kind}/{call_id}/{chunk.first_turn_idx}")


__all__ = [
    "SUBJECT_KINDS",
    "SUBJECT_KIND_SUMMARY",
    "SUBJECT_KIND_TURNS",
    "SUBJECT_NAMESPACE",
    "CallChunk",
    "Turn",
    "label_turn",
    "project_call",
    "project_summary",
    "project_turns",
    "subject_id_for",
]
