"""The erasure CERTIFICATE — the artifact, as distinct from the row it is built from.

`apps/workers/retention.execute_deletion_request` writes a proof into
`deletion_requests.proof`: hashes, counts, and a line per table saying what was done to
it. That row is a record of FACTS. This module turns those facts into the document that
leaves the building — the thing a client files, forwards to a regulator, and someone
reads years later with no access to this codebase and nobody left to ask.

Why the two are not the same thing, and why this module exists at all:

**A proof that overstates what was erased is worse than one that admits a limitation**,
because the person relying on it cannot tell. The stored proof says `calls: "phone
numbers, recording pointer and summary cleared"`. Every word of that is true and it is
still misleading, because the POINTER is not the audio. That sentence used to describe
the whole of what happened to a recording; it no longer does — `_erase_recordings`
destroys the bytes of every recording past the retention floor and schedules the rest —
but the certificate still has three states to keep apart, and they are not
interchangeable: audio destroyed, audio scheduled with a date, and (for proofs written
before any of this) audio whose fate the proof does not state. A reader of the stored
`actions` line alone would collapse all three.

`ERASURE_LIMITATIONS` has always said so — but it rode the API *envelope*, beside the
proof rather than inside it. The envelope is not what gets filed. So the certificate
carries the register itself: what was cleared (`erased`, in counts and plain sentences),
what was NOT (`not_erased`, each with the rule that stopped it), and the notice text
verbatim (`limitations`), so the document is complete on its own.

Three design decisions worth stating before someone simplifies them away:

1. **The stored proof is READ BY NAME, never splatted.** `ErasureProofOut` is
   `extra="forbid"`; `ErasureProofOut(**stored)` would turn "a later worker recorded one
   more fact" into a 500 on the one endpoint whose subject is a person who asked to be
   erased. The proof is durable and this renderer is not, so the renderer takes what it
   understands and ignores the rest.

2. **Absent is not zero.** A proof that never recorded a count says so
   ("this certificate does not state how many") instead of certifying `0`. Zero is a
   claim; we can only make claims the row supports.

3. **Nothing here is derived from the subject.** `subject_hash` is passed through from
   the stored proof, unchanged, so it still equals `export.subject_ref(phone)` — the
   equality an auditor uses to line one person's access request up against their erasure
   (hard rule 6). This module never sees a phone number and must never be given one.

**Hard rule 4 and re-rendering.** This is a pure function of the stored row plus the
register in `deletion.py`: certifying the same proof twice returns the same document.
Nothing here UPDATEs the stored proof — not to back-fill the limitations into rows
written before this module existed, not for anything. If the register is later widened,
a certificate rendered afterwards is a NEW statement rather than a correction of the old
one, and `limitations_version` is what lets a reader holding two copies tell which is
which.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import astuple
from typing import Any

from apps.api.compliance.deletion import (
    DESTROYED_COUNT_KEY,
    ERASURE_EXCEPTIONS,
    ERASURE_LIMITATIONS,
    FLOOR_COUNT_KEY,
    FLOOR_OUTCOME,
    HOLD_UNTIL_KEY,
    KB_MATCH_KEY,
    KB_OUTCOME,
    RECORDING_FLOOR_DAYS,
    ErasureLimitation,
)

# A count that is absent from the stored proof, said plainly rather than as a zero.
# The erasure job records the floor collision into `scope` now, so this sentence is what
# certificates built from proofs written BEFORE it did carry — and they keep carrying it,
# because hard rule 4 forbids back-filling a durable row to make an old document say
# something it never said.
_FLOOR_UNKNOWN = (
    "This certificate does not state how many of those recordings were inside the "
    f"{RECORDING_FLOOR_DAYS}-day window when the erasure ran."
)
_FLOOR_NONE = (
    "None of those recordings were inside the "
    f"{RECORDING_FLOOR_DAYS}-day window when the erasure ran."
)
# A proof that counted the collision but recorded no destruction date was written before
# the deferral WAS a schedule — when clearing the pointer destroyed the only handle on the
# audio, so nothing could ever delete it. Certificates for those erasures keep saying the
# weaker, true thing.
_HOLD_UNSCHEDULED = (
    "This certificate does not state a destruction date for them; confirm their removal "
    "with the client in writing."
)
# The three states of the knowledge-base search, and none of them is either of the others.
# A proof written before D-179 carries no count: the erasure that produced it did not look
# at all, and saying "none mentioned this number" on its behalf would be inventing a
# search. A recorded 0 IS the claim that the search ran and found nothing.
_KB_UNSEARCHED = (
    "This erasure ran before the knowledge base was searched at all, so this certificate "
    "does not say whether any uploaded knowledge document mentions this number."
)
_KB_NO_MATCH = (
    "The knowledge base was searched for this number and no uploaded knowledge document "
    "mentions it."
)


def notice_version(limitations: Sequence[str], exceptions: Sequence[ErasureLimitation]) -> str:
    """A version derived FROM the notice text, so it cannot drift from what it names.

    A hand-maintained version number is a promise to remember; this one is a fact about
    the bytes. Two certificates for the same erasure carrying different versions were
    rendered against different registers — which, under hard rule 4, means the later one
    is a new statement rather than an edit of the first.
    """
    material = json.dumps(
        {"limitations": list(limitations), "exceptions": [astuple(e) for e in exceptions]},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(material.encode()).hexdigest()[:16]


def certificate(stored: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Render the document a client hands on, from the proof the worker stored.

    `None` in, `None` out: a pending request has no certificate, and inventing an empty
    one would answer "has my data been erased?" with a document saying nothing was found.
    """
    if stored is None:
        return None

    scope = _mapping(stored.get("scope"))
    calls = _hashes(scope.get("calls"))
    leads = _hashes(scope.get("leads"))
    turns = _count(scope.get("transcript_turns_erased"))
    extractions = _count(scope.get("call_extractions_erased"))
    floor = _optional_count(scope.get(FLOOR_COUNT_KEY))
    destroyed = _optional_count(scope.get(DESTROYED_COUNT_KEY))
    hold_until = _optional_text(scope.get(HOLD_UNTIL_KEY))
    kb_matched = _optional_count(scope.get(KB_MATCH_KEY))

    return {
        # Passed through, never recomputed: this module is not given the number, and the
        # hash is the only thing that lines this certificate up with the subject-access
        # export for the same person (hard rule 6).
        "subject_hash": str(stored.get("subject_hash") or ""),
        "executed_at": str(stored.get("executed_at") or ""),
        "scope": {
            "calls": calls,
            "leads": leads,
            "transcript_turns_erased": turns,
            "call_extractions_erased": extractions,
            FLOOR_COUNT_KEY: floor,
            DESTROYED_COUNT_KEY: destroyed,
            HOLD_UNTIL_KEY: hold_until,
            KB_MATCH_KEY: kb_matched,
        },
        "actions": _actions(stored.get("actions")),
        "engine_deletion": str(stored.get("engine_deletion") or ""),
        "erased": _erased(
            calls=len(calls),
            leads=len(leads),
            turns=turns,
            fields=extractions,
            recordings=destroyed,
        ),
        "not_erased": _not_erased(floor, hold_until, kb_matched),
        "limitations": list(ERASURE_LIMITATIONS),
        "limitations_version": notice_version(ERASURE_LIMITATIONS, ERASURE_EXCEPTIONS),
    }


# --- what was cleared ---------------------------------------------------------


def _erased(
    *, calls: int, leads: int, turns: int, fields: int, recordings: int | None
) -> list[str]:
    """The scope counts as sentences, for a reader who does not know our table names.

    "No call record held this number" is a real and common answer — a client cannot know
    in advance whether they hold anything — so the empty case gets a statement rather
    than an empty list a reader would have to interpret.
    """
    statements: list[str] = []
    if calls:
        statements.append(
            f"{_plural(calls, 'call record')} — both phone numbers, the call summary and "
            "the link to the recording were cleared."
        )
    else:
        statements.append("No call record held this number.")
    # Only when the proof RECORDED it. A certificate built from a proof written before
    # the audio was reachable must not claim a destruction, and must not claim zero
    # either — the recording exception below is where its silence is explained.
    if recordings:
        statements.append(
            f"{_plural(recordings, 'call recording')} — the audio was destroyed in "
            "object storage and cannot be recovered."
        )
    if turns:
        statements.append(
            f"{_plural(turns, 'transcript turn')} — the spoken text was replaced with a "
            "marker, in the raw copy and the redacted one."
        )
    if fields:
        statements.append(
            f"{_plural(fields, 'set')} of extracted caller details — the captured fields "
            "were emptied."
        )
    if leads:
        statements.append(
            f"{_plural(leads, 'CRM lead')} — the number was replaced with a placeholder, "
            "and the name and captured fields were cleared."
        )
    else:
        statements.append("No CRM lead held this number.")
    return statements


# --- what was not ------------------------------------------------------------


def _not_erased(
    floor: int | None, hold_until: str | None, kb_matched: int | None
) -> list[dict[str, Any]]:
    """The register, with each count attached to the one entry it speaks for.

    Matched on OUTCOME rather than on a list index, so reordering the register cannot
    silently attach a number to the wrong statement — the same rule `FLOOR_OUTCOME`
    established, now that there are two entries carrying a count.
    """
    counts: dict[str, int | None] = {FLOOR_OUTCOME: floor, KB_OUTCOME: kb_matched}
    sentences = {
        FLOOR_OUTCOME: _floor_sentence(floor, hold_until),
        KB_OUTCOME: _kb_sentence(kb_matched),
    }
    entries: list[dict[str, Any]] = []
    for exception in ERASURE_EXCEPTIONS:
        sentence = sentences.get(exception.outcome)
        entries.append(
            {
                "what": exception.what,
                "outcome": exception.outcome,
                "why": f"{exception.why} {sentence}" if sentence else exception.why,
                "authority": exception.authority,
                "count": counts.get(exception.outcome),
            }
        )
    return entries


def _kb_sentence(matched: int | None) -> str:
    """What the knowledge-base search found, or that it did not happen.

    The plural form is spelled out rather than run through `_plural`: this sentence tells
    a client there is manual work outstanding, and it is the one place in the certificate
    where the reader is being handed a task rather than a record.
    """
    if matched is None:
        return _KB_UNSEARCHED
    if matched == 0:
        return _KB_NO_MATCH
    return (
        f"{_plural(matched, 'uploaded knowledge document')} mention this number. They "
        "were not changed by this request: removing the person from them is a manual "
        "step, in Calevate and on the voice platform's copy of the same source."
    )


def _floor_sentence(floor: int | None, hold_until: str | None) -> str:
    """How many recordings the floor caught, and — the part that makes it actionable —
    the date they go.

    Three states, three sentences, and none of them is the other two: a proof that never
    recorded the count says so; a recorded zero is the claim "none"; and a recorded count
    with no date is a proof from the era when a deferral had no schedule, which is a
    weaker statement than one that names the day and must not borrow its wording.
    """
    if floor is None:
        return _FLOOR_UNKNOWN
    if floor == 0:
        return _FLOOR_NONE
    caught = (
        f"{floor} of those recordings were inside the {RECORDING_FLOOR_DAYS}-day window "
        "when the erasure ran and could not lawfully be destroyed then."
    )
    if hold_until is None:
        return f"{caught} {_HOLD_UNSCHEDULED}"
    return f"{caught} The last of them is destroyed on {hold_until}."


# --- reading a durable row written by code that is not this code ---------------


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _hashes(value: Any) -> list[str]:
    """Row hashes, as strings. Never ids — that is the stored proof's own discipline and
    this renderer does not get to relax it."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _optional_count(value: Any) -> int | None:
    """`None` when the stored proof never recorded it — see decision 2 in the docstring."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_text(value: Any) -> str | None:
    """Same discipline for a stored instant: absent, or null because nothing was
    deferred, both render as "no date" rather than as an empty string a screen would
    print."""
    return value if isinstance(value, str) and value else None


def _actions(value: Any) -> dict[str, str]:
    return {str(key): str(item) for key, item in _mapping(value).items()}


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


__all__ = ["certificate", "notice_version"]
