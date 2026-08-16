"""Key moments in a call: the timestamps a client can jump to instead of re-listening.

A recording is a linear artefact and a reason to open one is almost never linear — "when
did they agree the slot", "where did they give the number", "did they ask to be removed".
Without anchors the only way to answer is to play the call again, which is the cost this
module removes. The markers are computed ONCE, in the post-call pipeline, and stored; a
listen costs nothing.

## Two provenances, and the distinction is load-bearing

`DERIVED` markers are computed here, from facts the pipeline already holds. They are
arithmetic on data, not a judgement, so a derived marker cannot point at the wrong second
— if the anchor cannot be PROVEN it is not emitted at all. `MODEL` markers come from the
extraction model and are richer and fallible. The screen labels them differently for that
reason: a wrong derived timestamp would be a bug, a wrong model one is a nuisance, and a
reader who cannot tell them apart has to distrust both.

## Why the derived half exists at all when a model could do it

Because it is free, exact, and already paid for. Every input is in hand at the moment the
extraction lands: `start_ms` per turn (persisted since the pipeline was written and, until
now, read by nothing), the extracted field values, and the opt-out detector's turn index.
Asking a model to re-derive what a string match can prove is how a feature acquires a
hallucination surface it never needed.

## PII: the default label carries none

A derived label names WHAT was captured and WHEN — "Appointment slot captured" — never the
value. The value is already on the same screen in its own panel, under the redaction rules
that govern it, and duplicating it into a marker would create a second copy with its own
redaction story to get wrong (hard rule 6). Model labels are the exception and are handled
by the caller: they are generated from the raw transcript, so they carry BOTH a raw and a
redacted form and the redacted one is what a client sees by default (hard rule 5).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Final, Literal, Protocol

#: What produced a marker. A closed set because it selects the icon, the wording and the
#: trust a reader should place in the timestamp — not a free-form note.
MomentSource = Literal["derived", "model"]

#: What KIND of thing happened. Closed for the same reason every other label in this repo
#: is (BACKEND-PATTERNS §8: the code IS the deduplication key), and deliberately SHORT.
#:
#: There is exactly ONE model kind, `highlight`, and that is a decision rather than an
#: omission. D-36 records that Sarvam's LLM quality on Telugu extraction is UNMEASURED;
#: asking an unmeasured model to sort moments into a taxonomy — "objection", "pricing",
#: "escalation" — and then rendering that taxonomy as fact would be publishing a
#: classification we have never scored. It writes a sentence; we present it as a
#: suggestion. When task #87 scores extraction against real transcripts, a taxonomy can
#: be earned.
MomentKind = Literal["field_captured", "opt_out", "highlight"]

#: Below this a value is too short to anchor honestly. "5" appears in half the turns of
#: any call that mentions a time, and a marker pointing at the wrong one is worse than no
#: marker — it sends someone to a place in the audio and is confidently wrong about it.
MIN_ANCHOR_CHARS: Final = 3

#: The most markers one call may carry. A cap, not a target: a forty-minute call with
#: sixty anchors is a second transcript, and the panel exists to be shorter than the
#: thing it indexes. Derived markers are kept first when the cap bites, because they are
#: the ones that cannot be wrong.
MAX_MOMENTS: Final = 12

_WHITESPACE = re.compile(r"\s+")

#: How close two markers must be to be describing the same moment. One conversational
#: turn is rarely under two seconds, so this is "the same turn" expressed in time rather
#: than in an index the model does not have.
_TIE_MS: Final = 2_000


class Turn(Protocol):
    """The three fields a marker needs, and no more.

    A Protocol so this module couples to no engine model and can be driven from a
    snapshot, a DB row, or a test's own object. READ-ONLY properties rather than plain
    attributes: a mutable Protocol attribute is INVARIANT, so declaring `speaker: str`
    would have rejected `TranscriptTurn`, whose `speaker` is a `Literal` — and `speaker`
    is not read here at all, so requiring it was asking callers to satisfy a constraint
    this module does not have.
    """

    @property
    def idx(self) -> int: ...

    @property
    def text(self) -> str: ...

    @property
    def start_ms(self) -> int | None: ...


def _normalize(value: str) -> str:
    """Casefolded, whitespace-collapsed. Enough to survive the transcript's own spacing
    without pretending to be a fuzzy matcher — see `anchor_of` for why exactness matters
    more here than recall."""
    return _WHITESPACE.sub(" ", value).strip().casefold()


def anchor_of(value: Any, turns: Sequence[Turn]) -> int | None:
    """The `start_ms` of the EARLIEST turn containing `value`, or None if unprovable.

    None rather than a guess, always. An extracted value is often a NORMALISED form of
    what was said — a model turns "tuesday at five" into "Tuesday 5pm" — so a plain
    containment test misses a large share of real values. That is the correct failure:
    a marker exists to say "it is at 1:42", and a marker that is sometimes at 1:42 and
    sometimes at 3:10 teaches people to stop trusting the whole panel. Fuzzy matching
    would raise the hit rate and remove exactly the property that makes these markers
    worth more than the model's.

    Turns with no `start_ms` are skipped: an engine that gives us no per-turn offsets is
    a supported engine (`TranscriptTurn.start_ms` is nullable), and it simply cannot
    carry derived markers.
    """
    if isinstance(value, bool) or value is None:
        # `True` is not a thing anyone said, and `"true"` would match the word.
        return None
    needle = _normalize(str(value))
    if len(needle) < MIN_ANCHOR_CHARS:
        return None
    for turn in sorted(turns, key=lambda t: t.idx):
        if turn.start_ms is None:
            continue
        if needle in _normalize(turn.text):
            return turn.start_ms
    return None


def _moment(*, at_ms: int, kind: MomentKind, label: str, source: MomentSource) -> dict[str, Any]:
    """One marker, in the shape the column stores and the API returns.

    `label_redacted` equals `label` for derived markers because a derived label carries no
    value — only the field's own name, which is the client's own schema wording. Keeping
    the key present rather than omitting it means every marker has the same shape whatever
    produced it, so the read path never has to ask which kind it is holding.
    """
    return {
        "at_ms": at_ms,
        "kind": kind,
        "label": label,
        "label_redacted": label,
        "source": source,
    }


def derive_moments(
    *,
    turns: Sequence[Turn],
    extraction: dict[str, Any],
    field_labels: dict[str, str],
    opt_out_turn_idx: int | None = None,
) -> list[dict[str, Any]]:
    """The markers that can be PROVEN from what the pipeline already has.

    `field_labels` maps an extraction key to the label the client chose for it, so a
    marker reads "Appointment slot captured" and not "appointment_slot captured" — the
    schema is the client's product copy (`ExtractionField.description` is explicitly
    that), and their words belong on their screen.

    Sorted by time, because the panel is a table of contents and a table of contents in
    dictionary order is a list.
    """
    out: list[dict[str, Any]] = []

    for key, value in extraction.items():
        at = anchor_of(value, turns)
        if at is None:
            continue
        out.append(
            _moment(
                at_ms=at,
                kind="field_captured",
                label=f"{field_labels.get(key, key.replace('_', ' ').capitalize())} captured",
                source="derived",
            )
        )

    if opt_out_turn_idx is not None:
        # The one marker that is a compliance fact rather than a convenience: a reviewer
        # checking why a number stopped being dialled needs to hear the sentence, and
        # `consent_ledger` stores the matched words but not a place in the audio.
        spoken = next((t for t in turns if t.idx == opt_out_turn_idx), None)
        if spoken is not None and spoken.start_ms is not None:
            out.append(
                _moment(
                    at_ms=spoken.start_ms,
                    kind="opt_out",
                    label="Caller asked not to be called again",
                    source="derived",
                )
            )

    return sorted(out, key=lambda m: m["at_ms"])


def merge_moments(
    derived: list[dict[str, Any]], model: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """One ordered list, derived winning every tie, capped at `MAX_MOMENTS`.

    **The cap is applied to the MODEL half only.** Dropping a derived marker to make room
    for a model one would trade a timestamp that is certainly right for one that is
    probably right, which is the wrong direction on a panel whose whole value is that you
    can trust where it sends you. A call with twelve provable anchors is a call that
    genuinely has twelve things in it.

    Model markers landing within `_TIE_MS` of a derived one are dropped rather than shown
    beside it: two entries a second apart describing the same moment read as two moments,
    and the derived one already says the true thing.
    """
    kept = list(derived)
    anchors = {m["at_ms"] for m in derived}
    room = max(0, MAX_MOMENTS - len(kept))
    for candidate in sorted(model, key=lambda m: m["at_ms"]):
        if room == 0:
            break
        if any(abs(candidate["at_ms"] - a) <= _TIE_MS for a in anchors):
            continue
        kept.append(candidate)
        anchors.add(candidate["at_ms"])
        room -= 1
    return sorted(kept, key=lambda m: m["at_ms"])


__all__ = [
    "MAX_MOMENTS",
    "MIN_ANCHOR_CHARS",
    "MomentKind",
    "MomentSource",
    "Turn",
    "anchor_of",
    "derive_moments",
    "merge_moments",
]
