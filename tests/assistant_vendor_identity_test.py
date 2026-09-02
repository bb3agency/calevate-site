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
from apps.api.copilot import prompt as prompt_module
from apps.api.copilot import service as service_module
from apps.api.copilot.schemas import CopilotAskIn

#: The names a client or an operator must never be told by the assistant, as whole words.
#:
#: LANGUAGE-MODEL VENDORS AND THEIR MODEL FAMILIES, which is the class the leak belongs to.
#: Every provider this product has ever routed a language request through is here whether or
#: not it is a live leg today — the sentence to catch is "trained by X", and a retired vendor
#: reads exactly as authoritatively as a current one. `gpt` and `claude` are in because the
#: leak came out as a MODEL FAMILY rather than as a company name; `microsoft` because it is
#: how the Azure leg is named in the register.
#:
#: NOT `sarvam` — see the module docstring. NOT `bolna`: the voice engine is not the
#: assistant's identity and a tenant's own agent screens name it.
VENDOR_WORDS: Final[tuple[str, ...]] = (
    "anthropic",
    "azure",
    "claude",
    "deepseek",
    "gemini",
    "google",
    "gpt",
    "llama",
    "microsoft",
    "mistral",
    "openai",
    "vertex",
)

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
