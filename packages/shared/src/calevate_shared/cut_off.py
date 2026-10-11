"""Which agent turns the caller probably did not hear in full, because they spoke over them.

A caller can talk over a ThinnestAI agent and it stops (thinnest-findings snapshots/
2026-10-08/pages/channels/voice.md:533-537), but the transcript still holds the agent's whole
generated reply (REPORTED: the founder's reading of production calls, 11 Oct 2026; the docs
do not say either way), and a turn's time is when it was written down, not where it falls
in the audio (api-reference/calls/get-call-transcript.md:7). Until the vendor trims it,
we infer it: a reply that would take longer to say than the time before the caller's next
turn was probably cut off. Founder decision, 11 Oct 2026 (D-739).

A derived reading, not a stored flag: it is a pure function of turns we already store, so
the call page, key moments and the extraction prompt all compute the same answer and a
better rate needs no migration.

ESTIMATE, on purpose on the fast side so a turn is flagged only when it is clearly too long
for its gap. `AGENT_CHARS_PER_SECOND` is 20 characters a second of speech. Our own
transcripts measured 571 agent characters per call-minute over three production calls
(D-728, `billing/tts_speaking_rate`); the agent speaks for part of each minute only, and at
the 40-60% share TRD §10.1 assumes that is roughly 950-1,430 characters a minute of speech,
16-24 a second. 20 sits inside that range. Turn times are whole seconds
(get-call-transcript.md, `offset`), so `TOLERANCE_MS` absorbs one second of rounding. The
caller's turn is written when their words are, after they start speaking, so the gap
overstates how long the agent had and the reading errs towards "heard".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from itertools import pairwise
from typing import Final, Protocol

#: Characters of agent speech a second. ESTIMATE; see the module docstring.
AGENT_CHARS_PER_SECOND: Final = 20
#: Rounding in the vendor's whole-second turn times.
TOLERANCE_MS: Final = 1_000


class TimedTurn(Protocol):
    @property
    def idx(self) -> int: ...

    @property
    def speaker(self) -> str: ...

    @property
    def text(self) -> str: ...

    @property
    def start_ms(self) -> int | None: ...


def speaking_ms(chars: int) -> int:
    """How long `chars` characters take to say, at `AGENT_CHARS_PER_SECOND`."""
    return chars * 1000 // AGENT_CHARS_PER_SECOND


def likely_cut_off_rows(rows: Iterable[tuple[int, str, int, int | None]]) -> frozenset[int]:
    """The `idx` of every agent turn the caller probably spoke over, from
    `(idx, speaker, characters, start_ms)` rows. Only an agent turn followed directly by a
    caller turn, both timed, can be flagged: the last turn and an untimed one never are."""
    ordered = sorted(rows, key=lambda row: row[0])
    flagged: set[int] = set()
    for (idx, speaker, chars, start), (_n, following, _c, next_start) in pairwise(ordered):
        if speaker != "agent" or following != "caller" or start is None or next_start is None:
            continue
        gap = next_start - start
        if gap >= 0 and speaking_ms(chars) > gap + TOLERANCE_MS:
            flagged.add(idx)
    return frozenset(flagged)


def likely_cut_off(turns: Sequence[TimedTurn]) -> frozenset[int]:
    """`likely_cut_off_rows` over turn objects."""
    return likely_cut_off_rows((t.idx, t.speaker, len(t.text), t.start_ms) for t in turns)


#: How the extraction prompt marks such a turn, so details and the summary do not treat an
#: offer or a price in it as heard.
UNHEARD_LABEL: Final = "agent (the caller spoke over this; they may not have heard it)"


__all__ = [
    "AGENT_CHARS_PER_SECOND",
    "TOLERANCE_MS",
    "UNHEARD_LABEL",
    "TimedTurn",
    "likely_cut_off",
    "likely_cut_off_rows",
    "speaking_ms",
]
