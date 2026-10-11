"""Key moments in a call: the places in the recording a client jumps to instead of
re-listening.

A recording is linear and a reason to open one almost never is: "when did they agree the
slot", "where did they complain", "did they ask to be removed". The markers are computed
ONCE, in the post-call pipeline, and stored in `call_extractions.moments`.

## Two provenances

`derived` markers are computed here from facts the pipeline already holds: a captured
field's value found verbatim in a turn, and the opt-out detector's turn. They are arithmetic,
not a judgement, so a derived marker is never on the wrong TURN. `model` markers are
suggested by the extraction model in the same request that reads the call
(`calevate_shared.extraction.build_extraction_prompt(..., moments=...)`); they are fallible
and the screen calls them "Suggested" (D-36: the model's quality is unscored).

## Two kinds of time, and the second is the common one

A marker's `at_ms` is its turn's `start_ms`. On ENGINE=thinnest that is the vendor's turn
time, which is "when it was written down, not where it falls in the audio"
(thinnest-findings get-call-transcript.md:7), so the turn carries `start_approximate` and
the marker carries `precision: "approximate"`. The founder chose that over paying to
re-transcribe (11 Oct 2026): show "~0:21" and seek a couple of seconds early. A turn with no
time at all still cannot carry a marker.

## PII

A derived label names WHAT was captured, never the value (hard rule 6): the value is on the
same screen under its own redaction. A model `field_captured` label is built here from the
client's field label for the same reason. Other model labels are the model's words, written
from the raw transcript, so they carry a raw and a redacted form and the redacted one is the
default view (hard rule 5).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Sequence
from typing import Any, Final, Literal, Protocol

from calevate_shared.extraction import (
    MAX_CALL_MOMENTS,
    MOMENT_KINDS,
    MomentCandidate,
    MomentKind,
)

#: What produced a marker. Selects the wording and the trust a reader places in it.
MomentSource = Literal["derived", "model"]

#: Whether `at_ms` is a point in the audio or a rough position near it.
MomentPrecision = Literal["exact", "approximate"]

#: Below this a value is too short to anchor honestly: "5" appears in half the turns of any
#: call that mentions a time, and a marker on the wrong one is confidently wrong.
MIN_ANCHOR_CHARS: Final = 3

#: The most markers one call carries (`calevate_shared.extraction.MAX_CALL_MOMENTS`).
MAX_MOMENTS: Final = MAX_CALL_MOMENTS

_WHITESPACE = re.compile(r"\s+")


class Turn(Protocol):
    """The fields a marker needs. Read-only properties so `TranscriptTurn`, whose `speaker`
    is a `Literal`, satisfies it, and so a test can drive it with a plain object."""

    @property
    def idx(self) -> int: ...

    @property
    def text(self) -> str: ...

    @property
    def start_ms(self) -> int | None: ...

    @property
    def start_approximate(self) -> bool: ...


def _normalize(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip().casefold()


def _precision(turn: Turn) -> MomentPrecision:
    return "approximate" if turn.start_approximate else "exact"


def anchor_turn(value: Any, turns: Sequence[Turn]) -> Turn | None:
    """The EARLIEST timed turn containing `value` verbatim, or None.

    None rather than a guess: an extracted value is often a normalised form of what was said
    ("Tuesday 5pm" for "tuesday at five"), and a fuzzy match would put the marker on a
    plausible-looking wrong turn. The model's `field_captured` suggestion covers the values
    this misses, labelled as a suggestion.
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
            return turn
    return None


def anchor_of(value: Any, turns: Sequence[Turn]) -> int | None:
    """`anchor_turn`'s `start_ms`, or None."""
    turn = anchor_turn(value, turns)
    return turn.start_ms if turn is not None else None


def moment(
    *,
    turn: Turn,
    kind: MomentKind,
    label: str,
    source: MomentSource,
    importance: int,
    label_redacted: str | None = None,
    field: str | None = None,
) -> dict[str, Any]:
    """One marker, in the shape the column stores.

    `label_redacted` defaults to `label` because a derived or field label carries no value.
    Every marker has every key, so the read path never asks which kind it holds.
    """
    if turn.start_ms is None:
        raise ValueError("a moment needs a turn with a time")
    return {
        "at_ms": turn.start_ms,
        "turn_idx": turn.idx,
        "kind": kind,
        "category": MOMENT_KINDS[kind][0],
        "label": label,
        "label_redacted": label if label_redacted is None else label_redacted,
        "source": source,
        "precision": _precision(turn),
        "importance": importance,
        "field": field,
    }


def _field_label(key: str, field_labels: dict[str, str]) -> str:
    return f"{field_labels.get(key, key.replace('_', ' ').capitalize())} captured"


def derive_moments(
    *,
    turns: Sequence[Turn],
    extraction: dict[str, Any],
    field_labels: dict[str, str],
    opt_out_turn_idx: int | None = None,
    unheard: Collection[int] = (),
) -> list[dict[str, Any]]:
    """The markers provable from what the pipeline already has, in time order.

    `field_labels` maps an extraction key to the client's own label, so a marker reads
    "Appointment slot captured", not "appointment_slot captured". `unheard` holds the
    agent turns the caller probably spoke over (`calevate_shared.cut_off`): no marker is
    placed on one, because what the caller may not have heard is not a moment of the call.
    """
    out: list[dict[str, Any]] = []
    heard = [turn for turn in turns if turn.idx not in unheard]
    for key, value in extraction.items():
        turn = anchor_turn(value, heard)
        if turn is None:
            continue
        out.append(
            moment(
                turn=turn,
                kind="field_captured",
                label=_field_label(key, field_labels),
                source="derived",
                importance=2,
                field=key,
            )
        )

    if opt_out_turn_idx is not None:
        # A compliance fact rather than a convenience: `consent_ledger` stores the matched
        # words but no place in the audio, and a reviewer asked why a number stopped being
        # dialled needs to hear the sentence.
        spoken = next((t for t in turns if t.idx == opt_out_turn_idx), None)
        if spoken is not None and spoken.start_ms is not None:
            out.append(
                moment(
                    turn=spoken,
                    kind="opt_out",
                    label=MOMENT_KINDS["opt_out"][1],
                    source="derived",
                    importance=3,
                )
            )
    return sorted(out, key=lambda m: m["at_ms"])


def prompt_line_turns(turns: Sequence[Any]) -> list[Any]:
    """The turn behind each line the extraction prompt numbers, 1-based line n at [n - 1].

    Mirrors `pipeline._persist_transcript` (one `speaker: text` line per turn with words)
    and `calevate_shared.extraction.numbered_lines` (non-blank physical lines), so a turn
    whose text holds a newline owns every line it spans.
    """
    out: list[Any] = []
    for turn in turns:
        if not turn.text.strip():
            continue
        rendered = f"{turn.speaker}: {turn.text}"
        out.extend(turn for line in rendered.split("\n") if line.strip())
    return out


def model_moments(
    candidates: Sequence[MomentCandidate],
    *,
    line_turns: Sequence[Turn],
    field_labels: dict[str, str],
    redact: Callable[[str], str],
    unheard: Collection[int] = (),
) -> list[dict[str, Any]]:
    """The model's suggestions, placed on their turns. Unplaceable ones are dropped.

    A line out of range or a turn with no time cannot be shown on the recording. A
    `field_captured` label is OURS, from the client's field label; any other label is the
    model's raw wording plus its redacted form (`redact`), falling back to the kind's plain
    label when the model wrote none.
    """
    out: list[dict[str, Any]] = []
    for candidate in candidates:
        if not 1 <= candidate.line <= len(line_turns):
            continue
        turn = line_turns[candidate.line - 1]
        if turn.start_ms is None or turn.idx in unheard:
            continue
        if candidate.kind == "field_captured" and candidate.field:
            label = _field_label(candidate.field, field_labels)
            redacted = label
        else:
            label = candidate.label or MOMENT_KINDS[candidate.kind][1]
            redacted = redact(label)
        out.append(
            moment(
                turn=turn,
                kind=candidate.kind,
                label=label,
                label_redacted=redacted,
                source="model",
                importance=candidate.importance,
                field=candidate.field,
            )
        )
    return out


def _same_moment(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two markers describing one thing: the same captured field, or the same kind on the
    same turn. Shown twice they read as two moments."""
    if a["kind"] != b["kind"]:
        return False
    if a["kind"] == "field_captured":
        return a.get("field") is not None and a.get("field") == b.get("field")
    return a.get("turn_idx") == b.get("turn_idx")


def merge_moments(
    derived: list[dict[str, Any]], model: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """One list in time order, at most `MAX_MOMENTS`, the most important kept.

    A model marker that repeats a derived one is dropped: the derived one is on a proven
    turn. When the cap bites, markers are ranked by importance, then derived before model
    (a provable turn beats a suggested one), then earlier first.
    """
    kept = list(derived)
    for candidate in model:
        if any(_same_moment(candidate, existing) for existing in kept):
            continue
        kept.append(candidate)
    ranked = sorted(
        kept,
        key=lambda m: (
            -int(m.get("importance") or 2),
            0 if m["source"] == "derived" else 1,
            m["at_ms"],
        ),
    )
    return sorted(ranked[:MAX_MOMENTS], key=lambda m: (m["at_ms"], m.get("turn_idx") or 0))


__all__ = [
    "MAX_MOMENTS",
    "MIN_ANCHOR_CHARS",
    "MomentKind",
    "MomentPrecision",
    "MomentSource",
    "Turn",
    "anchor_of",
    "anchor_turn",
    "derive_moments",
    "merge_moments",
    "model_moments",
    "moment",
    "prompt_line_turns",
]
