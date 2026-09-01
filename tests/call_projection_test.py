"""The chunking and speaker decisions of the transcript projection, pinned.

Pure functions and no database, which is the reason `retrieval/call_projection.py` is a
pure function: the decisions that set retrieval quality are exercised here, and the store,
the sweep and the erasure arms are tested where they live.

The erasure and retention proofs are NOT here — they are in
`tests/caller_chunk_erasure_test.py`, against real rows, because "a caller's sentence is
gone" is a claim about a table and not about a list.
"""

from __future__ import annotations

import re

from apps.api.crm.models import SPEAKERS
from apps.api.kb.service import MAX_CHUNK_CHARS, MIN_CHUNK_CHARS
from apps.api.retrieval.call_projection import (
    SUBJECT_KIND_SUMMARY,
    SUBJECT_KIND_TURNS,
    CallChunk,
    Turn,
    project_call,
    project_summary,
    project_turns,
)

MARK = "[erased]"

#: The sentence every erasure test in this repository hunts for. Spelled once.
WEEKEND_QUESTION = "Do you do appointments on the weekend?"


def _call(pairs: list[tuple[str, str]], *, start: int = 0) -> list[Turn]:
    return [
        Turn(idx=start + i, speaker=speaker, text_redacted=body)
        for i, (speaker, body) in enumerate(pairs)
    ]


def _long_call(exchanges: int = 20) -> list[Turn]:
    pairs: list[tuple[str, str]] = []
    for i in range(exchanges):
        pairs.append(("caller", f"Question number {i} about a topic that takes real words."))
        pairs.append(("agent", f"Answer number {i}, long enough that a window fills steadily."))
    return _call(pairs)


def _bodies(chunks: list[CallChunk]) -> str:
    """Every chunk's text with the speaker labels and all whitespace removed."""
    joined = "".join(chunk.text for chunk in chunks)
    for label in ("Caller:", "Agent:", "Summary:"):
        joined = joined.replace(label, "")
    return re.sub(r"\s+", "", joined)


# --- the chunking decision ------------------------------------------------------------


def test_a_backchannel_turn_never_becomes_its_own_vector() -> None:
    """The reason this is a window of turns and not a turn (module docstring)."""
    turns = _call(
        [
            ("agent", "Namaskaram, Sunrise Dental."),
            ("caller", "Haan."),
            ("agent", "How can I help you today?"),
            ("caller", "Yes."),
            ("caller", WEEKEND_QUESTION),
            ("agent", "We are open Saturday nine to two."),
        ]
    )
    chunks = project_turns(turns, mark=MARK)
    assert len(chunks) == 1
    # The one-word turns are IN the chunk — nothing is dropped — they simply do not each
    # get a vector of their own.
    assert "Caller: Haan." in chunks[0].text
    assert WEEKEND_QUESTION in chunks[0].text


def test_a_long_call_is_many_windows_not_one_vector() -> None:
    """The reason this is not a chunk per CALL: a specific question stays retrievable."""
    chunks = project_turns(_long_call(), mark=MARK)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= MAX_CHUNK_CHARS + MIN_CHUNK_CHARS + 1 for chunk in chunks)


def test_every_window_but_the_last_ends_on_an_answer() -> None:
    """THE BOUNDARY RULE. A chunk that ended on a question would be stored apart from the
    answer it is about, so the hours never match the hours question."""
    chunks = project_turns(_long_call(), mark=MARK)
    for chunk in chunks[:-1]:
        assert chunk.text.rsplit("\n", 1)[-1].startswith("Agent: ")


def test_a_final_question_is_still_projected() -> None:
    """`_settle` has nowhere to carry the last window, and a question the call ended on is
    still the caller asking it."""
    turns = _call([("agent", "Anything else?"), ("caller", WEEKEND_QUESTION)])
    chunks = project_turns(turns, mark=MARK)
    assert WEEKEND_QUESTION in "".join(chunk.text for chunk in chunks)


def test_an_all_caller_window_terminates() -> None:
    """A monologue has no agent turn to end on. `_settle` must emit rather than carry for
    ever — the one case where the boundary rule yields."""
    turns = _call(
        [("caller", f"Sentence {i} of a long monologue with no reply at all.") for i in range(40)]
    )
    chunks = project_turns(turns, mark=MARK)
    assert len(chunks) > 1
    assert all(chunk.speakers == ("caller",) for chunk in chunks)


def test_chunking_never_drops_a_character_of_the_conversation() -> None:
    """LOSSLESS, the property `kb/service.chunk_text` is tested on and the reason this
    module reuses it. A dropped tail is a caller sentence nothing can ever retrieve and
    nothing downstream can detect."""
    turns = _long_call(exchanges=30)
    turns.append(Turn(idx=999, speaker="caller", text_redacted="Ek minute. " * 400))
    chunks = project_turns(turns, mark=MARK)
    expected = re.sub(r"\s+", "", "".join(turn.text_redacted or "" for turn in turns))
    assert _bodies(chunks) == expected


def test_a_turn_longer_than_the_cap_is_split_and_keeps_its_speaker() -> None:
    turns = _call([("caller", "This is one very long sentence. " * 60)])
    chunks = project_turns(turns, mark=MARK)
    assert len(chunks) > 1
    for chunk in chunks:
        for line in chunk.text.split("\n"):
            if line.strip():
                assert line.startswith("Caller: ")
        assert chunk.first_turn_idx == 0 and chunk.last_turn_idx == 0


def test_chunk_indexes_are_dense_and_zero_based_with_the_summary_last() -> None:
    chunks = project_call(_long_call(), summary="Caller asked about hours.", mark=MARK)
    assert [chunk.idx for chunk in chunks] == list(range(len(chunks)))
    assert chunks[-1].subject_kind == SUBJECT_KIND_SUMMARY
    assert all(chunk.subject_kind == SUBJECT_KIND_TURNS for chunk in chunks[:-1])


# --- the speaker decision -------------------------------------------------------------


def test_the_speaker_vocabulary_is_the_column_s_own() -> None:
    """`_SPEAKER_LABELS` is spelled in the projection rather than imported from the CRM
    model; this is the check that keeps the two in step."""
    labelled = {
        line.split(":", 1)[0]
        for chunk in project_turns(
            _call([("agent", "Hello there."), ("caller", WEEKEND_QUESTION)]), mark=MARK
        )
        for line in chunk.text.split("\n")
    }
    assert labelled == {"Agent", "Caller"}
    assert set(SPEAKERS) == {"agent", "caller"}


def test_who_asked_survives_into_the_embedded_text() -> None:
    """The distinction the whole scope exists for: a caller ASKING about weekend
    appointments and an agent MENTIONING them are different facts about a business."""
    asked = project_turns(_call([("caller", WEEKEND_QUESTION)]), mark=MARK)[0]
    told = project_turns(_call([("agent", WEEKEND_QUESTION)]), mark=MARK)[0]
    assert asked.text != told.text
    assert asked.speakers == ("caller",)
    assert told.speakers == ("agent",)


def test_speakers_are_recorded_in_first_appearance_order() -> None:
    chunk = project_turns(
        _call([("agent", "Namaskaram."), ("caller", WEEKEND_QUESTION), ("agent", "Saturday.")]),
        mark=MARK,
    )[0]
    assert chunk.speakers == ("agent", "caller")


def test_an_unknown_speaker_is_labelled_rather_than_dropped() -> None:
    """A role the enum does not know is a schema change upstream. Un-attributing the text
    would hide it while degrading the one axis this module protects."""
    chunk = project_turns(_call([("supervisor", "Transferring you now.")]), mark=MARK)[0]
    assert chunk.text == "supervisor: Transferring you now."


# --- the marker -----------------------------------------------------------------------


def test_an_erased_turn_is_never_projected() -> None:
    turns = _call([("caller", WEEKEND_QUESTION), ("agent", MARK), ("caller", MARK)])
    chunks = project_turns(turns, mark=MARK)
    assert MARK not in "".join(chunk.text for chunk in chunks)


def test_a_fully_erased_call_projects_to_nothing() -> None:
    """The belt behind the erasure arms: a re-projection after an erasure must not put the
    rows back. A `CASCADE` cannot do this, because an erasure deletes no call."""
    turns = _call([("caller", MARK), ("agent", MARK)])
    assert project_call(turns, summary=None, mark=MARK) == []


def test_a_turn_with_no_redaction_is_skipped_rather_than_read_raw() -> None:
    """`text_redacted IS NULL` means the redactor has not run. There is no `text` field on
    `Turn` to fall back to, which is hard rule 5 enforced by the type."""
    turns = [
        Turn(idx=0, speaker="caller", text_redacted=None),
        Turn(idx=1, speaker="agent", text_redacted="   "),
        Turn(idx=2, speaker="caller", text_redacted=WEEKEND_QUESTION),
    ]
    chunks = project_turns(turns, mark=MARK)
    assert len(chunks) == 1
    assert chunks[0].text == f"Caller: {WEEKEND_QUESTION}"


# --- the summary ----------------------------------------------------------------------


def test_the_summary_is_its_own_labelled_chunk() -> None:
    chunk = project_summary("Caller wanted a refund.", idx=7, mark=MARK)
    assert chunk is not None
    assert chunk.subject_kind == SUBJECT_KIND_SUMMARY
    assert chunk.idx == 7
    assert chunk.text == "Summary: Caller wanted a refund."
    assert chunk.first_turn_idx is None and chunk.last_turn_idx is None


def test_a_null_or_marked_summary_projects_to_nothing() -> None:
    """NULL is the erased state for `calls.summary` — both erasure paths and the retention
    sweep clear it rather than marking it."""
    assert project_summary(None, idx=0, mark=MARK) is None
    assert project_summary("   ", idx=0, mark=MARK) is None
    assert project_summary(MARK, idx=0, mark=MARK) is None
