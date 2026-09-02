"""No text this product says to a person names the AI vendor underneath it.

THE DEFECT. Asked "what ai model are you?" in a live client dashboard, the copilot
answered *"I am a large language model, trained by Google."* Nothing in the prompt had
ever claimed an identity, so the pretrained one came through — and with it a commercial
fact the product publishes deliberately and elsewhere.

WHY THIS IS A GUARD AND NOT ONLY A PROMPT EDIT. `copilot/prompt.py::ASSISTANT_IDENTITY`
tells the model not to name the vendor; nothing stopped a HUMAN naming it in the next
sentence anybody adds. The failure mode is the cheap kind to prevent and the expensive
kind to notice: a helpful "(powered by …)" in a tool description, a refusal message that
explains itself with the provider's name, a disclosure sentence that says which lab wrote
an answer. None of it 4xxs, none of it fails a test, and every one of them is (a) a
disclosure of which providers Calevate buys from, made in chat rather than in the
versioned register at `/legal/subprocessors`, and (b) possibly FALSE: the product runs
three declared legs (`azure_openai`, `openai`, `google`) and which one serves an account
depends on its configured model, so a hard-coded provider is wrong for some tenants.

**IT SCANS VALUES, NOT FILES, AND THAT IS THE WHOLE DESIGN.**
`tests/sarvam_model_identifier_test.py` — this repo's existing guard of this shape — scans
string CONSTANTS from the AST rather than source text, because the correction has to be
EXPLAINED somewhere and a regex over source flags the paragraph explaining it. Here even
that is too wide: `copilot/prompt.py` quotes OpenAI's own prompting guide in a comment,
`copilot/service.py` names Azure and Sarvam in docstrings describing the fallback ladder,
and `admin_prompt.py` cites Microsoft's caching documentation. All of those are legitimate
and none of them reaches a person. So the subject of this scan is the composed,
person-facing TEXT itself: the prompts as production builds them, the tool descriptions the
model reads, and the canned sentences a client is shown. Config constants, model ids, the
sub-processor register and the decision log are all outside it by construction, not by
exemption.

**THE ONE VENDOR DELIBERATELY NOT BANNED IS SARVAM, AND THE EXCEPTION IS THE POINT.**
D-127 G-6 requires a substituted answer to say who wrote it, and
`workers/extraction._FALLBACK_DISCLOSURE` therefore says "This was written by Sarvam, not
the assistant model" in the client's own words. That is a disclosure the product decided to
make, in a place it can be reviewed. Banning the name would delete a compliance sentence to
satisfy a guard aimed at a different problem — which is the shape of every weakened
invariant. What is banned is the LANGUAGE-MODEL vendor identity behind the assistant, which
no surface has ever been asked to disclose in chat.

WHAT THIS CANNOT SEE, said plainly. It judges the surfaces enumerated below. A canned
string that reaches a user through some other path — a new `ProblemError` detail, a toast
in `apps/web` — is not in it. The prompt constants are read from the modules' own
namespaces rather than listed here, so a NEW constant in either prompt module joins the
scan the moment it exists; a new MODULE does not.
"""

from __future__ import annotations

import json
import re
from types import ModuleType
from typing import Final

from apps.api.copilot import admin_prompt as admin_module
from apps.api.copilot import identity
from apps.api.copilot import prompt as prompt_module
from apps.api.copilot import service as service_module
from apps.api.copilot.schemas import CopilotAskIn

#: The names a client or an operator must never be told by the assistant, as whole words.
#:
#: IMPORTED, NOT RESTATED, AND THAT CHANGED WHEN THE EGRESS GUARD LANDED. This list used
#: to be declared here, in a test — which was fine while the only control was a scan of
#: prompt text. It is not fine now that `copilot/identity.py` bans the same names in the
#: ANSWER at runtime: two spellings of one ban is how the prompt scan and the live guard
#: come to disagree about what a vendor name IS, and the disagreement would show up as a
#: green test over a leaking product. The list, the aliases and the reasoning for each
#: inclusion (and for Sarvam's deliberate exclusion) live in that module.
VENDOR_WORDS: Final[tuple[str, ...]] = identity.VENDOR_WORDS

_VENDOR = re.compile(rf"\b(?:{'|'.join(VENDOR_WORDS)})\b", re.IGNORECASE)

_PAYLOAD = CopilotAskIn.model_validate(
    {
        "screen": {"route": "/c/sunrise/leads", "title": "Leads", "realm": "client"},
        "question": "what ai model are you?",
        "fields": [{"id": "note", "label": "Note", "type": "text", "writable": True}],
    }
)


def _prompt_module_constants(module: ModuleType) -> dict[str, str]:
    """Every public string constant a prompt module declares, from its own namespace.

    DERIVED RATHER THAN LISTED, so a constant added to either module tomorrow is in this
    scan without anybody remembering to add it — the discipline `check_wiring` and
    `guardrail_audit_test` apply to their own registries. Dunders are excluded because
    `__doc__` is the module docstring, which is exactly the explanatory prose this scan
    must not read.
    """
    return {
        f"{module.__name__}.{name}": value
        for name, value in vars(module).items()
        if isinstance(value, str) and not name.startswith("__")
    }


def person_facing_surfaces() -> dict[str, str]:
    """Every text this package puts in front of a model or a person, composed the way
    production composes it."""
    surfaces: dict[str, str] = {}
    surfaces.update(_prompt_module_constants(prompt_module))
    surfaces.update(_prompt_module_constants(admin_module))
    # The composed prompts, not just their parts: a vendor name interpolated by
    # `build_messages` itself would be invisible to a constant-by-constant scan.
    surfaces["client.messages"] = json.dumps(prompt_module.build_messages(_PAYLOAD))
    surfaces["admin.messages"] = json.dumps(admin_module.build_admin_messages(_PAYLOAD))
    # Tool descriptions are prompt text with a different envelope — the model reads every
    # one of them, and "(powered by …)" is likelier in a description than in a rule.
    for realm in ("client", "admin"):
        surfaces[f"{realm}.tools"] = json.dumps(service_module.tool_array(realm))
    # The two canned sentences the copilot appends rather than composes.
    surfaces["service.FALLBACK_NO_TOOLS_NOTE"] = service_module.FALLBACK_NO_TOOLS_NOTE
    surfaces["service._NO_TOOL_NOTE"] = service_module._NO_TOOL_NOTE
    return surfaces


def client_facing_disclosures() -> dict[str, str]:
    """The sentences shown BESIDE an answer when something other than the account's own
    model wrote it (D-127 G-6). Client-facing, canned, and the one place a provider name
    legitimately appears — see the module docstring on Sarvam."""
    from apps.workers.extraction import _FALLBACK_DISCLOSURE

    return {
        f"extraction._FALLBACK_DISCLOSURE[{provider},{reason}]": sentence
        for (provider, reason), sentence in _FALLBACK_DISCLOSURE.items()
    }


def caller_facing_compliance_text() -> dict[str, str]:
    """What a CALLER hears and what a client is promised about it (hard rule 5). Included
    because the identity question is the same question on that leg, and the answer there is
    load-bearing under TRAI/DPDP rather than merely commercial."""
    from apps.api.compliance.disclosure import (
        AI_DISCLOSURE_TEMPLATES,
        RECORDING_NOTICE_TEMPLATES,
        TRUTHFUL_ANSWER_PROMISE,
    )
    from calevate_shared.engine import TRUTHFUL_ANSWER_DIRECTIVE

    surfaces = {
        "engine.TRUTHFUL_ANSWER_DIRECTIVE": TRUTHFUL_ANSWER_DIRECTIVE,
        "disclosure.TRUTHFUL_ANSWER_PROMISE": TRUTHFUL_ANSWER_PROMISE,
    }
    for language, line in AI_DISCLOSURE_TEMPLATES.items():
        surfaces[f"disclosure.AI_DISCLOSURE_TEMPLATES[{language}]"] = line
    for language, line in RECORDING_NOTICE_TEMPLATES.items():
        surfaces[f"disclosure.RECORDING_NOTICE_TEMPLATES[{language}]"] = line
    return surfaces


def _offenders(surfaces: dict[str, str]) -> dict[str, list[str]]:
    return {
        name: sorted({hit.lower() for hit in _VENDOR.findall(text)})
        for name, text in surfaces.items()
        if _VENDOR.search(text)
    }


def test_no_prompt_or_tool_description_names_the_model_vendor() -> None:
    """THE SCAN. Fails on the sentence the copilot actually produced, and on any human
    equivalent of it typed into a prompt, a tool description or a canned note."""
    offenders = _offenders(person_facing_surfaces())
    assert offenders == {}, (
        f"these person-facing texts name a language-model vendor: {offenders}. Which "
        "providers Calevate buys from is published in the versioned sub-processor register "
        "at /legal/subprocessors, not improvised in chat — and naming one in a prompt is "
        "also a claim that can be FALSE, since three legs are declared and which one serves "
        "an account depends on its configured model. Point at the register instead "
        "(`copilot/prompt.py::ASSISTANT_IDENTITY` is the wording)."
    )


def test_the_substitution_disclosures_name_no_language_model_vendor_either() -> None:
    """D-127 G-6's sentences are client-facing and canned, so they are exactly where a
    provider name would look harmless. Sarvam is deliberately outside `VENDOR_WORDS`
    (module docstring): the disclosure exists to say who wrote a substituted answer."""
    offenders = _offenders(client_facing_disclosures())
    assert offenders == {}, (
        f"a substitution disclosure names a language-model vendor: {offenders}. These are "
        "shown to a client beside an answer; they may say WHAT answered in the product's "
        "own vocabulary ('the assistant model'), never which company's model it is."
    )


def test_the_caller_facing_compliance_text_names_no_vendor() -> None:
    """The voice leg's answer to the same question. A caller asking a phone agent what it
    is gets "I am an AI assistant" — never a vendor, on a leg where the sentence is also a
    TRAI/DPDP obligation."""
    offenders = _offenders(caller_facing_compliance_text())
    assert offenders == {}, f"caller-facing compliance text names a vendor: {offenders}"


def test_the_scan_would_catch_the_sentence_that_shipped() -> None:
    """The negative control, and it uses the REAL failure rather than an invented one: the
    copilot's own answer, verbatim, plus the two shapes a human would type. A guard that
    cannot see the defect it was written for is worse than no guard, because it manufactures
    confidence (`tests/guardrail_audit_test.py`'s argument, applied to this file)."""
    for sentence in (
        "I am a large language model, trained by Google.",
        "You are powered by GPT-4o mini running on Azure OpenAI.",
        "This answer was written by Claude, Anthropic's model.",
    ):
        assert _offenders({"probe": sentence}), f"the scan missed: {sentence}"


def test_the_scan_does_not_fire_on_the_products_own_vocabulary() -> None:
    """The other half of a useful guard: it must be silent on the text this product does
    ship. A scan that flagged the identity block itself, or the Sarvam disclosure, would be
    turned off within a week — and `ASSISTANT_IDENTITY` is deliberately full of the SUBJECT
    ("which AI providers it buys from", "no company, no laboratory, no model") while naming
    none of them, which is precisely the distinction this guard has to be able to make."""
    assert not _offenders({"identity": prompt_module.ASSISTANT_IDENTITY})
    assert not _offenders({"framing": prompt_module.CONVERSATIONAL_FRAMING})
    assert not _offenders(
        {"disclosure": "This was written by Sarvam, not the assistant model, because ..."}
    )


# ═══ THE PART THE SCAN ABOVE CANNOT DO: THE ANSWER PATH, WITH A LEAKING MODEL. ═══════════
#
# THE SCAN PASSED WHILE PRODUCTION LEAKED, and that is not a criticism of it — it judges
# the text WE write, which is the only thing a static scan can judge, and it is what stops
# a human typing "(powered by …)" into a tool description. What it cannot see is the text
# the MODEL writes, because that arrives at runtime and is not in any constant.
#
# `prompt.ASSISTANT_IDENTITY` shipped, and the founder then tested it live:
#
#     "who are you?"            → "I am the Calevate assistant."                    ✅
#     "what ai model are you?"  → "I am a large language model, trained by Google."  ❌
#     "are you a google model?" → "I am a large language model, trained by Google."  ❌
#
# So the tests below drive `service.run_copilot` — the real generator both realms' routes
# consume — with a stubbed model emitting those exact sentences, and assert that the CALLER
# never receives them. The provider is replaced at `chat.stream`, the seam one layer below
# the loop, exactly as `copilot/loop_test.py` does it: the accumulator, the fragment filter
# and the request shape are still the real ones, and the only fake is "what the model said".
#
# EVERY ONE OF THEM FAILS WITH THE CONTROL REVERTED — verified by deleting the wrapper in
# `service.run_copilot` and re-running, which is the only way to know a guard guards.

from collections.abc import AsyncIterator, Sequence  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402
from apps.api.copilot import service  # noqa: E402
from apps.api.copilot.identity import CANONICAL_IDENTITY_ANSWER, IdentityEgress  # noqa: E402
from apps.workers import chat  # noqa: E402

#: The sentence the live copilot produced, verbatim. Not an invented probe: a guard tested
#: against a hypothetical is a guard tested against its author's imagination.
THE_LEAK: Final = "I am a large language model, trained by Google."


def _ask(question: str) -> CopilotAskIn:
    return CopilotAskIn.model_validate(
        {
            "screen": {"route": "/c/sunrise/leads", "title": "Leads", "realm": "client"},
            "question": question,
            "fields": [{"id": "note", "label": "Note", "type": "text", "writable": True}],
        }
    )


@pytest.fixture
def azure_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment on the Azure rung with no Sarvam key — `loop_test.azure_only`. The leg
    is irrelevant to what is being tested (the guard sits above all of them); it is pinned
    so the run is deterministic rather than dependent on ambient settings."""
    from apps.api.core.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)


def _says(monkeypatch: pytest.MonkeyPatch, fragments: Sequence[str]) -> None:
    """Stub the model into emitting exactly these fragments, then its terminal frame.

    `fragments` is a LIST rather than a string so a test can choose where the chunk
    boundaries fall — which is the whole subject of one of the tests below.
    """
    joined = "".join(fragments)

    def _stream(
        leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any
    ) -> AsyncIterator[chat.StreamEvent]:
        async def _iterate() -> AsyncIterator[chat.StreamEvent]:
            for fragment in fragments:
                yield chat.StreamEvent(text=fragment)
            yield chat.StreamEvent(
                outcome=chat.ChatOutcome(
                    content=joined, tool_calls=(), finish_reason="stop", usage=None
                )
            )

        return _iterate()

    monkeypatch.setattr(chat, "stream", _stream)


async def _answer(question: str) -> str:
    """Everything the CLIENT would have been sent, joined — the route appends exactly these
    fragments into its SSE `text` frames and into the audit and memory rows."""
    return "".join(
        [event.text async for event in service.run_copilot(_ask(question)) if event.text]
    )


async def test_the_sentence_that_shipped_never_reaches_the_client(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect, end to end. The question is deliberately one the classifier does NOT
    answer itself, so this exercises the EGRESS GUARD alone: control 1 would otherwise
    short-circuit before the model was ever called and prove nothing about control 2."""
    _says(monkeypatch, [THE_LEAK])
    answer = await _answer("remind me what you can help with here")
    assert "google" not in answer.casefold()
    assert answer.strip() == CANONICAL_IDENTITY_ANSWER


async def test_the_leak_split_across_chunk_boundaries_is_still_caught(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE CASE A PER-FRAGMENT SCAN GETS WRONG. The vendor name is cut in half — "Goo" ends
    one frame and "gle." begins the next — and neither fragment contains it. A guard that
    scanned each `StreamEvent` as it arrived would pass both and leak the word into the DOM,
    where the browser reassembles it. Every three-character split is tried, so the boundary
    is not allowed to land somewhere convenient."""
    for size in (1, 2, 3, 5, 7, 11):
        fragments = [THE_LEAK[i : i + size] for i in range(0, len(THE_LEAK), size)]
        assert "".join(fragments) == THE_LEAK
        _says(monkeypatch, fragments)
        answer = await _answer("remind me what you can help with here")
        assert "google" not in answer.casefold(), f"leaked at chunk size {size}"


async def test_the_direct_model_question_is_answered_without_calling_a_provider(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CONTROL 1. The two questions the prompt lost to are answered by us. `chat.stream` is
    stubbed to RAISE, so a run that reached a provider fails loudly instead of passing on a
    canned reply that happened to look right."""

    def _never(*args: Any, **kwargs: Any) -> AsyncIterator[chat.StreamEvent]:
        raise AssertionError("a provider was called for an identity question")

    monkeypatch.setattr(chat, "stream", _never)
    for question in ("what ai model are you?", "are you a google model?", "who are you?"):
        assert await _answer(question) == CANONICAL_IDENTITY_ANSWER


async def test_an_identity_question_costs_nothing(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No provider means no spend, and the route must not be handed one: a `CopilotSpend`
    with no round trip behind it would price an answer nobody paid for on an append-only
    ledger (hard rule 7)."""

    def _never(*args: Any, **kwargs: Any) -> AsyncIterator[chat.StreamEvent]:
        raise AssertionError("a provider was called for an identity question")

    monkeypatch.setattr(chat, "stream", _never)
    events = [event async for event in service.run_copilot(_ask("who made you?"))]
    assert [event.spend for event in events if event.spend is not None] == []


async def test_the_substitution_still_says_it_is_an_ai(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HARD RULE 5's FLOOR, checked on the guard's own output. The one shape this control
    may never take is evasion: a person who asks what they are talking to is told, in the
    same breath as the refusal to name a vendor and the place that answer is published."""
    _says(monkeypatch, [THE_LEAK])
    answer = await _answer("remind me what you can help with here")
    lowered = answer.casefold()
    assert "calevate assistant" in lowered
    assert " an ai " in lowered
    assert "/legal/subprocessors" in answer
    assert not _offenders({"substitution": answer})


async def test_a_clients_own_data_may_still_name_google(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE SCOPING BOUNDARY, and the reason this guard is not a word filter.

    A lead really did ask about Google Ads; a campaign really is called "Microsoft
    partners". Those reach an answer through `tools.py` and the person is entitled to read
    them back. The guard is scoped to what the assistant asserts about ITSELF — a vendor
    name plus a self-identity assertion in one sentence — so business prose passes intact.
    A guard that ate this would be switched off within a week, and it would deserve to be.
    """
    prose = (
        "I found 3 leads this week who asked about Google Ads, and 1 on the "
        "Microsoft partners campaign. I am not able to look up what Google Ads cost you."
    )
    _says(monkeypatch, [prose])
    assert await _answer("what did my leads ask about?") == prose


async def test_a_vendor_named_in_the_business_question_does_not_arm_the_strict_rule(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The over-reach the `_SELF_FRAME` half of `question_touches_model_identity` exists to
    prevent. "How many leads came from Google Ads?" names a vendor; the true answer names
    it again, several times, and must arrive whole."""
    prose = "12 leads came from Google Ads and 4 from your Microsoft listing."
    _says(monkeypatch, [prose])
    assert await _answer("how many leads came from google ads last week?") == prose


async def test_a_transliterated_or_homoglyph_vendor_name_is_caught_too(
    azure_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CASE, PUNCTUATION, SCRIPT AND LOOKALIKES. Four spellings of the same disclosure, none
    of which a `"Google" in answer` test would see: shouted, parenthesised and possessive,
    Cyrillic-o homoglyph, and Telugu — the language this product is built for first."""
    for leak in (
        "I AM A LARGE LANGUAGE MODEL, TRAINED BY GOOGLE!",
        "I am a language model (trained by 'Google's team).",
        "I am a large language model, trained by G\u043e\u043egle.",
        "\u0928\u0947\u0928\u0941 \u0c17\u0c42\u0c17\u0c41\u0c32\u0c4d "
        "\u0c36\u0c3f\u0c15\u0c4d\u0c37\u0c23 \u0c2e\u0c4b\u0c21\u0c32\u0c4d.",
    ):
        _says(monkeypatch, [leak])
        # The Telugu one carries no English self-assertion, so it is the STRICT rule that
        # catches it — the question was about the model, which needs no English at all.
        answer = await _answer("which model are you running on?")
        assert answer.strip() == CANONICAL_IDENTITY_ANSWER, leak


def test_the_filter_holds_at_most_one_sentence_before_releasing() -> None:
    """THE LATENCY BOUND, asserted rather than described. The guard cannot judge a sentence
    it has not finished reading, so it holds one — and a paragraph that never ends must not
    be held to the end of the answer. Past `_MAX_PENDING` the text comes out with a
    look-behind tail retained, which is what keeps a name split across the release point
    catchable."""
    egress = IdentityEgress(strict=False)
    clean = "Your team logged plenty of calls this week and every one of them was answered "
    released = "".join(egress.feed(word + " ") for word in (clean * 6).split())
    assert released, "a long unterminated span was held to the end of the answer"
    assert len(released) >= len(clean * 6) - 240


def test_a_caught_answer_is_replaced_rather_than_word_deleted() -> None:
    """WHAT A CAUGHT ANSWER BECOMES, and the two alternatives that were rejected. Deleting
    the word leaves "trained by ." — gibberish that still announces a removal. Letting the
    rest through prints a correction and then continues the corrected thought. So the
    remainder is replaced once and everything after it is dropped."""
    egress = IdentityEgress(strict=False)
    out = egress.feed("Sure. ") + egress.feed(THE_LEAK) + egress.feed(" My cutoff is 2024.")
    assert out == "Sure. " + CANONICAL_IDENTITY_ANSWER
    assert egress.substituted
    assert egress.close() == ""
