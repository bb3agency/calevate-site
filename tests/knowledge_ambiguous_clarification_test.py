"""`ambiguous` must produce a QUESTION the caller can answer, never an apology.

**THE FAILURE THIS FILE EXISTS TO CATCH.** Two documents answer one question equally well —
the Kukatpally branch and the Gachibowli branch — and the agent says "I do not have that
information" instead of "did you mean Kukatpally or Gachibowli?". It is the most expensive
of the four retrieval outcomes to get wrong, because the business HAS published the answer
and the caller is turned away from it.

It is a live risk rather than a hypothetical one: every agent's prompt carries
`VOICE_STYLE_GUIDANCE`'s "if you do not know, offer to have someone call back rather than
inventing an answer", and an `ambiguous` result reads to a model like not knowing.

**WHAT IS ASSERTED, AND WHY IT IS NOT A CANNED STRING.** An agent cannot ask "did you mean
X or Y" unless the payload told it X and Y, so the load-bearing property is that the two
competing passages arrive with words that TELL THEM APART — derived here from the payload
itself, never from a fixture's own knowledge of what the answer should be. The clarifier
below reads only what the model reads.

**THE HONESTY BOUNDARY IS ASSERTED IN THE SAME PLACE.** Asking must not become inventing:
the options offered come from the two passages' own published text, a `not_found` is still
admitted rather than converted into a choice, and the bound is two because a third option
in one breath is a list a caller cannot hold in their head.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from calevate_shared.knowledge_pack import KnowledgePack, PackEntry
from voice_worker import pipeline
from voice_worker.knowledge import AMBIGUOUS_CANDIDATES, LexicalIndex, SessionKnowledge

TENANT = UUID("0199c1de-0001-7000-8000-00000000a001")
AGENT = UUID("0199c1de-0001-7000-8000-00000000a002")

KUKATPALLY_DOC = UUID("0199c1de-0001-7000-8000-00000000b001")
GACHIBOWLI_DOC = UUID("0199c1de-0001-7000-8000-00000000b002")
MADHAPUR_DOC = UUID("0199c1de-0001-7000-8000-00000000b003")
SECUNDERABAD_DOC = UUID("0199c1de-0001-7000-8000-00000000b004")
PARKING_DOC = UUID("0199c1de-0001-7000-8000-00000000b005")

#: Two branches, one sentence each, identical but for the name. A caller asking about
#: "branch timings" has named a category, which is exactly what `AMBIGUITY_MARGIN` is for.
BRANCH_QUESTION = "what are the branch timings"


def _entry(document_id: UUID, text: str) -> PackEntry:
    return PackEntry(chunk_id=uuid4(), document_id=document_id, document_version=1, text=text)


def _session(entries: tuple[PackEntry, ...]) -> SessionKnowledge:
    digest = KnowledgePack.digest(TENANT, AGENT, entries)
    pack = KnowledgePack(
        tenant_id=TENANT,
        agent_id=AGENT,
        content_sha256=digest,
        built_at=datetime(2026, 9, 20, 6, 0, tzinfo=UTC),
        entries=entries,
    )
    return SessionKnowledge(
        tenant_id=TENANT,
        agent_id=AGENT,
        pack=pack,
        index=LexicalIndex(pack.entries),
        requested_digest=digest,
    )


def two_branch_session() -> SessionKnowledge:
    return _session(
        (
            _entry(KUKATPALLY_DOC, "The Kukatpally branch is open from nine to eight."),
            _entry(GACHIBOWLI_DOC, "The Gachibowli branch is open from nine to eight."),
            _entry(PARKING_DOC, "Two wheeler parking is in the basement."),
        )
    )


def four_branch_session() -> SessionKnowledge:
    return _session(
        (
            _entry(KUKATPALLY_DOC, "The Kukatpally branch is open from nine to eight."),
            _entry(GACHIBOWLI_DOC, "The Gachibowli branch is open from nine to eight."),
            _entry(MADHAPUR_DOC, "The Madhapur branch is open from nine to eight."),
            _entry(SECUNDERABAD_DOC, "The Secunderabad branch is open from nine to eight."),
        )
    )


async def lookup(session: SessionKnowledge | None, question: str) -> dict[str, Any]:
    """One tool call, as the model receives it."""
    return await pipeline.knowledge_tool_payload(session, question, pack_configured=True)


# ======================================================================================
# The crux: can the agent NAME the alternatives it is being told to offer?
# ======================================================================================


def distinguishing_words(payload: dict[str, Any]) -> list[set[str]]:
    """Per passage, the words it holds that no OTHER passage in this payload holds.

    This is the whole question the audit asked, expressed as data: an agent handed two
    passages can only tell the caller them apart if the passages differ in words it is
    allowed to say. Derived from the payload and nothing else, so a fixture cannot supply
    the answer the code failed to.
    """
    bags = [{word.strip(".,?").lower() for word in p["text"].split()} for p in payload["passages"]]
    return [
        bag - set().union(*(other for i, other in enumerate(bags) if i != index))
        for index, bag in enumerate(bags)
    ]


def next_thing_said(payload: dict[str, Any]) -> str:
    """What a literal reader of THIS payload says next — a question, or an apology.

    It reads the guidance and the passages, never the outcome word's reputation. If the
    guidance does not tell it to ask, or the passages do not let it name the options, it
    falls back to what a model reliably does with a result it cannot use: apologise.
    """
    guidance = payload["guidance"].lower()
    options = [sorted(words)[0] for words in distinguishing_words(payload) if words]
    if "do not say you do not know" in guidance and len(options) == AMBIGUOUS_CANDIDATES:
        return f"Did you mean {options[0]} or {options[1]}?"
    return "Sorry, I do not have that information."


async def test_an_ambiguous_lookup_hands_the_model_both_competing_documents() -> None:
    payload = await lookup(two_branch_session(), BRANCH_QUESTION)

    assert payload["outcome"] == "ambiguous"
    assert len(payload["passages"]) == AMBIGUOUS_CANDIDATES
    assert {p["source_id"] for p in payload["passages"]} == {
        str(KUKATPALLY_DOC),
        str(GACHIBOWLI_DOC),
    }
    # Each candidate carries a word the other does not, which is the minimum an agent needs
    # to ask "did you mean X or Y" without inventing either name.
    assert all(words for words in distinguishing_words(payload))


async def test_an_ambiguous_lookup_produces_a_question_and_not_an_apology() -> None:
    """The regression this file is named for."""
    payload = await lookup(two_branch_session(), BRANCH_QUESTION)
    spoken = next_thing_said(payload)

    assert spoken.endswith("?"), "the agent apologised for a question the business answered"
    assert spoken.count("?") == 1, "one clarifying question, not an interrogation"
    assert "kukatpally" in spoken.lower()
    assert "gachibowli" in spoken.lower()


async def test_a_not_found_lookup_is_still_admitted_and_cannot_become_a_choice() -> None:
    """The negative control, and the honesty boundary in one.

    The same literal reader, handed a genuine absence, has nothing to offer and says so.
    A clarification loop that turned `not_found` into a guess between two nearby documents
    would pass the test above and be a worse product than the apology it replaced.
    """
    payload = await lookup(two_branch_session(), "do you repair tractor tyres")

    assert payload["outcome"] == "not_found"
    assert payload["passages"] == []
    assert next_thing_said(payload) == "Sorry, I do not have that information."
    assert "do not have that information" in payload["guidance"]


async def test_an_agent_with_no_pack_is_not_offered_options_either() -> None:
    payload = await pipeline.knowledge_tool_payload(None, BRANCH_QUESTION, pack_configured=False)

    assert payload["outcome"] == pipeline.KNOWLEDGE_OUTCOME_NO_PACK
    assert payload["passages"] == []
    assert next_thing_said(payload) == "Sorry, I do not have that information."


# ======================================================================================
# The bound, and the speakability of what the model is told.
# ======================================================================================


async def test_four_competing_branches_are_still_offered_two() -> None:
    """A spoken either/or is a question; four options read aloud is a list the caller has
    to remember while it is still being read."""
    payload = await lookup(four_branch_session(), BRANCH_QUESTION)

    assert payload["outcome"] == "ambiguous"
    assert len(payload["passages"]) == AMBIGUOUS_CANDIDATES
    assert next_thing_said(payload).count(" or ") == 1


def test_the_ambiguous_guidance_tells_the_agent_to_ask_from_the_passages() -> None:
    """The four properties the guidance has to carry, asserted as properties.

    Worded rather than quoted whole: the sentences may be rewritten, but a rewrite that
    drops any of these four restores the defect.
    """
    guidance = pipeline._KNOWLEDGE_GUIDANCE["ambiguous"].lower()

    assert "ask" in guidance, "nothing tells the agent to ask"
    assert "do not say you do not know" in guidance, "the apology is not ruled out"
    assert "passages" in guidance, "the options are not bound to what was retrieved"
    assert "not in them" in guidance, "nothing forbids offering an option that was invented"


def test_the_tool_description_says_both_documents_are_given() -> None:
    """The description is read when the tool is advertised, before any result exists, and
    is the only place the model learns `ambiguous` comes WITH its alternatives."""
    description = pipeline.KNOWLEDGE_TOOL_DESCRIPTION

    assert "ambiguous" in description
    assert "BOTH are given" in description
    assert "saying you do not know" in description


def test_nothing_the_model_is_told_about_retrieval_is_written_for_a_screen() -> None:
    """Guidance is read in the same breath as the result and is echoed under pressure, so
    it obeys the same spoken-output constraints as the prompt (`AGENTS.md:180`)."""
    for text in (pipeline.KNOWLEDGE_TOOL_DESCRIPTION, *pipeline._KNOWLEDGE_GUIDANCE.values()):
        # `_` is absent from this set on purpose: `not_found` and `no_knowledge_base` are
        # outcome WORDS the model has to be told, not formatting.
        assert not set(text) & set("*#`|"), f"markdown characters in: {text[:60]}"
        assert not any(line.lstrip().startswith(("- ", "1.")) for line in text.splitlines())
