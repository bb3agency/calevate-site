"""Was the AI disclosure actually SPOKEN on this call? — the evidence half of hard rule 5.

`calls.disclosure_played` has existed since the first migration (`05bba2f3c19c`). It is
rendered on the client's call detail screen (`DisclosureNotice`) and on the weekly QA
compliance-review queue (`quality/sampling.py`), where a reviewer working OPERATIONS §5's
*"disclosure spoken"* scenario reads it as the evidence.

**Nothing in this repository ever wrote it** (P3.3). Every one of those surfaces rendered
a permanently null column, which the screens correctly showed as "unknown" — so the
product asked a reviewer to certify a property it had never measured, on every call, and
the only real control was a one-off manual check before launch. IT Act / Sanjay Pandey
exposure (SEC-COMP §1) rested on that check.

WHY A SEPARATE MODULE RATHER THAN A FUNCTION IN THE WORKER. Two callers, and the second
one is the reason the first must not own it: the pipeline writes the column, and the
red-team eval harness scores the same property over fixture transcripts. `optout.py` is
split for exactly this reason and this follows it rather than inventing a second shape.

--------------------------------------------------------------------------------
WHAT THIS MEASURES, AND WHAT IT DOES NOT
--------------------------------------------------------------------------------

It answers *"did the agent say the disclosure line on this call?"* — no more. Three
properties nearby that it deliberately does NOT claim:

* **NOT "said it first".** That is the greeting field's job and it is verified at PUBLISH
  time, against the engine, by `agents/verification.judge` reading
  `AgentSnapshot.greeting` — the engine's `agent_welcome_message` / `introduction`, which
  is the deterministic first utterance. A transcript cannot distinguish "the greeting
  played" from "the model happened to say it in turn 4", and pretending otherwise here
  would put a second, weaker answer beside the strong one (P3.3's own defect class).
* **NOT a legal certification.** It is a string match over an engine's transcript. What it
  produces is EVIDENCE a human reviewer reads, which is precisely what the QA queue was
  built to hold.
* **NOT a gate.** Nothing blocks on it. A call is already over by the time this runs.

FAILING DIRECTION, CHOSEN DELIBERATELY. The match is strict containment after
normalisation, so it errs towards `False` — it will report "not spoken" for a disclosure
the engine rendered with different words. That is the safe direction for a compliance
signal: a false negative sends a reviewer to listen to a recording that turns out fine,
and a false positive certifies a call nobody checked. `_EVIDENCE` in `optout.py` argues
the same trade the other way round for the same reason — there, recall protects a
caller's request; here, precision protects a client's licence.

WHY NOT FUZZY MATCHING. A similarity threshold would be a number nobody could defend to a
regulator ("how similar is compliant?") and would move every verdict on every tuning. The
disclosure line is a SHORT fixed string the tenant themselves authored, sent to the engine
verbatim as the greeting; if it does not come back the honest answer is that we did not
observe it.

HARD RULE 6. Nothing here logs or returns transcript text. The answer is one tri-state.
"""

from __future__ import annotations

from collections.abc import Sequence

from apps.api.compliance.optout import SpokenTurn, normalize_utterance

__all__ = ["disclosure_spoken"]


def disclosure_spoken(turns: Sequence[SpokenTurn], *, disclosure_line: str) -> bool | None:
    """`True` spoken · `False` not observed · `None` nothing to judge.

    THE TRI-STATE IS THE `AgentSnapshot.*_readable` DOCTRINE, arriving at the same answer
    from the other end of the system: "we looked and it was not there" and "there was
    nothing to look at" are different facts, and only the first is a finding. A call with
    no transcript (the engine returned none, or the caller hung up before a word) yields
    `None`, and the column keeps the NULL the screens already render as "unknown" —
    rather than a `False` that reads, to a reviewer and to a client, as a breach.

    AGENT TURNS ONLY. The disclosure is ours to speak; a caller reading it back, or an
    STT pass attributing our own audio to the caller channel, must not be able to satisfy
    it. That is the same rule `detect_opt_out` applies in mirror image — it reads CALLER
    turns only, so a prompt regression cannot suppress a client's list by having the
    agent say the words.

    ANY AGENT TURN, not the first. Engines legitimately emit a short filler or
    connection-noise turn ahead of the welcome message, and requiring index 0 would
    report a compliance breach on a call where the line was played exactly as configured.
    "First" is verified at publish against the engine's greeting field, where it can be
    verified properly (module docstring).
    """
    needle = normalize_utterance(disclosure_line)
    if not needle:
        # A tenant cannot reach this — `agents.disclosure_line` is NOT NULL and the
        # compliance gate refuses an empty one — but a fixture or a future importer can,
        # and "the empty string is in every transcript" would certify every call ever.
        return None
    spoken = [
        normalized
        for turn in turns
        if turn.speaker != "caller" and (normalized := normalize_utterance(turn.text))
    ]
    if not spoken:
        return None
    return any(needle in line for line in spoken)
