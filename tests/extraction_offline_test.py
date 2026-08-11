"""The offline extractor must never invent a fact about the caller.

That is the one rule it claims in its own docstring, and it broke the rule three
different ways — each one filing a value into a client's CRM that nobody said. This
matters more than "it is only the offline extractor": it is what CI scores, what a
laptop run scores, and what every golden-transcript regression is measured against. An
extractor that fabricates makes the quality gate measure fabrication.

All three defects share one root: it read the whole transcript without asking WHO SPOKE
or whether the thing was affirmed or denied.
"""

from __future__ import annotations

import pytest
from apps.workers.extraction import OfflineExtractor
from calevate_shared.extraction import ExtractionField, ExtractionSchemaSpec


def _spec(*fields: ExtractionField) -> ExtractionSchemaSpec:
    return ExtractionSchemaSpec(fields=list(fields))


NAME = ExtractionField(key="name", label="Name", type="text", description="caller's name")
CALLBACK = ExtractionField(
    key="wants_callback", label="Callback wanted", type="bool", description="wants a callback"
)
INTENT = ExtractionField(
    key="intent",
    label="Intent",
    type="enum",
    description="why they called",
    enum_values=["book", "cancel", "reschedule", "other"],
)


async def test_the_agents_question_does_not_become_the_callers_name() -> None:
    """`Mee peru cheppandi` is the AGENT asking for a name. It was filing "Cheppandi"
    as the caller — a person who does not exist, in a row the client will act on."""
    transcript = "agent: Namaskaram. Mee peru cheppandi.\ncaller: Sare andi."

    result = await OfflineExtractor().run(_spec(NAME), transcript)

    assert "name" not in result or result["name"] is None, (
        f"invented a caller named {result.get('name')!r} out of the agent's question"
    )


async def test_a_name_the_caller_actually_gives_is_still_captured() -> None:
    """The other direction, so the fix is not "capture nothing"."""
    transcript = "agent: Mee peru cheppandi.\ncaller: Naa peru Ravi Kumar andi."

    result = await OfflineExtractor().run(_spec(NAME), transcript)

    assert result["name"] == "Ravi Kumar"


async def test_a_caller_declining_does_not_set_the_flag_true() -> None:
    """The bool probe matched the field's label anywhere in the transcript — so the
    AGENT asking "callback avasaram unda?" and the caller answering "Ledu" recorded
    `wants_callback = True`. The client then rings someone who said no, which is the
    exact harm the do-not-call machinery exists to prevent."""
    transcript = "agent: Meeku callback avasaram unda?\ncaller: Ledu, callback avasaram ledu andi."

    result = await OfflineExtractor().run(_spec(CALLBACK), transcript)

    assert result.get("wants_callback") is not True, "recorded a callback the caller refused"


async def test_a_caller_asking_for_a_callback_still_sets_the_flag() -> None:
    transcript = "agent: Ela help cheyala?\ncaller: Callback kavali andi."

    result = await OfflineExtractor().run(_spec(CALLBACK), transcript)

    assert result["wants_callback"] is True


async def test_asking_whether_something_was_cancelled_is_not_a_cancellation() -> None:
    """A caller ringing to ASK whether their booking was cancelled must not be filed as
    intent=cancel — the client sees a cancellation that never happened and acts on it.

    This was a strict xfail on the grounds that no word-level rule separates asking from
    doing. That was half right: the WORD cannot be told apart, because a caller who asks
    about a thing names it exactly as plainly as one who did it. The ASKING can be, and
    that is a different question with an answer.
    """
    transcript = (
        "agent: Namaskaram.\n"
        "caller: Naa booking cancel aipoyinda ani adagataniki call chesanu andi."
    )

    result = await OfflineExtractor().run(_spec(INTENT), transcript)

    assert result.get("intent") != "cancel"


async def test_a_caller_who_actually_cancels_is_still_recorded() -> None:
    """The direction that stops the fix from being "record nothing". An enquiry filter
    that swallows real statements trades a false cancellation for a missed one, and the
    client acts on neither."""
    transcript = "agent: Cheppandi.\ncaller: Naa booking cancel cheyandi andi."

    result = await OfflineExtractor().run(_spec(INTENT), transcript)

    assert result["intent"] == "cancel"


async def test_an_enquiry_in_one_turn_does_not_mute_a_statement_in_another() -> None:
    """Enquiry is a property of the TURN, not of the call. A caller who asks about one
    thing and then asks for another has said both, and only the first is a question."""
    transcript = (
        "agent: Namaskaram.\n"
        "caller: Fees enta ani adagataniki call chesanu.\n"
        "caller: Sare, appointment book cheyandi andi."
    )

    result = await OfflineExtractor().run(_spec(INTENT), transcript)

    assert result["intent"] == "book"


async def test_asking_about_a_callback_is_not_requesting_one() -> None:
    """The same rule on the bool path, where the cost is a phone call to someone who
    only asked a question."""
    transcript = "agent: Cheppandi.\ncaller: Callback vasthundaa ani adugutunnanu andi."

    result = await OfflineExtractor().run(_spec(CALLBACK), transcript)

    assert result.get("wants_callback") is not True


async def test_an_enum_value_hiding_inside_another_word_is_not_a_match() -> None:
    """Substring matching made `other` match inside "brother" — so a caller mentioning
    their brother was filed with intent=other."""
    transcript = "agent: Cheppandi.\ncaller: Naa brother ki appointment kavali."

    result = await OfflineExtractor().run(_spec(INTENT), transcript)

    assert result.get("intent") != "other", "matched 'other' inside 'brother'"


async def test_the_speaker_label_itself_is_never_evidence() -> None:
    """The sharpest version of the same bug: an enum value of `caller` matched the
    `caller:` prefix on every single line, so the field was set on every transcript
    regardless of content."""
    field = ExtractionField(
        key="reported_by",
        label="Reported by",
        type="enum",
        description="who reported it",
        enum_values=["caller", "agent", "third_party"],
    )
    transcript = "agent: Namaskaram.\ncaller: Naaku oka doubt undi."

    result = await OfflineExtractor().run(_spec(field), transcript)

    assert "reported_by" not in result, "the speaker prefix was read as the answer"


async def test_the_agent_saying_a_value_is_not_the_caller_saying_it() -> None:
    """The general property behind all three, stated once."""
    transcript = "agent: Meeru book cheyala leda cancel cheyala?\ncaller: Emi ledu, thanks."

    result = await OfflineExtractor().run(_spec(INTENT, NAME, CALLBACK), transcript)

    assert "intent" not in result, "took the agent's menu of options as the caller's answer"
    assert "name" not in result
    assert result.get("wants_callback") is not True


@pytest.mark.parametrize(
    "transcript",
    [
        "caller: Naa peru Ravi andi.",  # no speaker labels on the agent side
        "Naa peru Ravi andi.",  # no labels at all
    ],
)
async def test_a_transcript_without_agent_labels_still_extracts(transcript: str) -> None:
    """Attribution must not become a way to extract nothing. A transcript we cannot
    split is read whole — it is weaker evidence, but discarding it silently would be a
    regression dressed as caution."""
    result = await OfflineExtractor().run(_spec(NAME), transcript)

    assert result["name"] == "Ravi"


async def test_a_silent_call_produces_no_fields_at_all() -> None:
    """The null case the whole "never invent" rule exists for."""
    result = await OfflineExtractor().run(_spec(NAME, INTENT, CALLBACK), "agent: Hello? Hello?")

    assert "name" not in result
    assert "intent" not in result
    assert "wants_callback" not in result
    assert result["outcome_tag"] == "resolved"
