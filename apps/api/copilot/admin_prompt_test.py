"""The admin realm's prefix: what it shares with the client's, and what it must not.

THIS FILE HAD BEEN CITED TWICE BEFORE IT EXISTED. `admin_prompt.py`'s own comment claimed
`copilot/admin_prompt_test.py` pinned the cacheable-prefix property and that
`tests/admin_copilot_test.py` pinned the two realms differing; neither file was ever
written. So the second-largest static prompt in this product — the one an operator acts on
during an incident, against other people's live accounts — was covered by nothing at all,
while reading as though it were covered by two things.

WHAT IT ASSERTS, and why each one is here rather than in `copilot/prompt_test.py`: every
property below is about the ADMIN prefix, and three of them are about the RELATIONSHIP
between the two prefixes, which no single-realm test can see. `prompt_test.py` keeps the
client half; this keeps the operator half and the seam.

ASSERTED ON THE PROMPT, NOT ON A MODEL'S ANSWER, for `prompt_test.py`'s reason: no Azure
credential exists in this environment and the endpoint is unreachable from it.
"""

from __future__ import annotations

import json

from apps.api.copilot import admin_prompt as admin_module
from apps.api.copilot import prompt as prompt_module
from apps.api.copilot.schemas import CopilotAskIn

PAYLOAD = CopilotAskIn.model_validate(
    {
        "screen": {
            "route": "/admin/clients/sunrise",
            "title": "Sunrise Dental",
            "realm": "admin",
        },
        "question": "what do I do when engine_error_spike fires?",
        "fields": [{"id": "note", "label": "Operator note", "type": "text", "writable": True}],
    }
)

OTHER = CopilotAskIn.model_validate(
    {
        "screen": {"route": "/admin/health", "title": "Triage", "realm": "admin"},
        "question": "is outbound halted?",
    }
)


# --- the cacheable prefix -------------------------------------------------------------


def test_the_admin_prefix_carries_nothing_request_specific() -> None:
    """Two caches, one per realm, each keyed on a leading run of byte-identical tokens.

    FAILS IF: an operator's name, the open tenant's slug or a clock reading is interpolated
    into `ADMIN_SYSTEM_PROMPT` — which would give the admin console a cache hit rate of
    zero on every request. Compared as BYTES across two unrelated requests rather than read
    off the constant, because an f-string in a helper would survive a reading."""
    first = admin_module.build_admin_messages(PAYLOAD)[0]
    second = admin_module.build_admin_messages(OTHER)[0]
    assert first == second
    assert first["role"] == "system"


def test_the_admin_prefix_clears_the_cache_floor() -> None:
    """1024 tokens is the documented floor (MicrosoftDocs/azure-ai-docs,
    `articles/foundry/openai/includes/how-to-prompt-caching-content.md` @ main, read 1 Sep
    2026 — quoted in `admin_prompt.py`). A prefix under it is never cached however
    identical it is, and the admin prefix is the smaller of the two."""
    prefix = json.dumps(admin_module.build_admin_messages(PAYLOAD)[0])
    assert len(prefix.encode("utf-8")) > 1024


def test_the_two_realms_do_not_share_one_prefix() -> None:
    """The other half of the caching argument, and the reason there are two prompts at all:
    a single prefix carrying both realms' rules would be paid for on every client request
    and would leave neither realm's rules fitting."""
    # Annotated `str` rather than compared directly: both sides are `Final` literals, so
    # mypy settles the comparison at type-check time and rejects it as non-overlapping —
    # which is a stronger proof than this test, but only until somebody makes one of them
    # a computed string. The runtime assertion is what survives that change.
    admin: str = admin_module.ADMIN_SYSTEM_PROMPT
    client: str = prompt_module.SYSTEM_PROMPT
    assert admin != client
    admin_closing: str = admin_module.ADMIN_CLOSING_RULES
    client_closing: str = prompt_module.CLOSING_RULES
    assert admin_closing != client_closing


# --- the blocks that are shared, and are shared by IMPORT ------------------------------


def test_the_identity_answer_is_byte_identical_in_both_realms() -> None:
    """THE OPERATOR ASSISTANT MUST NOT LEAK THE VENDOR EITHER.

    The live leak — "I am a large language model, trained by Google" — was answered by a
    model that both realms run through the same loop, so a fix applied to one prefix leaves
    the identical defect standing in the other. Two copies of an answer that must be
    identical is the drift shape D-103/D-105 exist for; identity is the worst place to pay
    for it, because the copy that drifts still reads plausibly.

    FAILS IF: somebody restates the identity here instead of importing it. Byte equality is
    the assertion, so a paraphrase fails even when it means the same thing."""
    assert prompt_module.ASSISTANT_IDENTITY in admin_module.ADMIN_SYSTEM_PROMPT
    assert prompt_module.ASSISTANT_IDENTITY in prompt_module.SYSTEM_PROMPT


def test_the_identity_block_is_the_first_thing_in_the_admin_prefix() -> None:
    """Same position, same reason: a persona buried mid-prompt is one the model resolves
    against whatever it read last."""
    prefix = admin_module.build_admin_messages(PAYLOAD)[0]["content"]
    header, _, rest = str(prefix).partition("\n")
    assert header.startswith("--- PLATFORM RULES")
    assert rest.startswith(prompt_module.ASSISTANT_IDENTITY)


def test_the_operator_realm_gets_the_conversational_framing_too() -> None:
    """The over-anchoring that turned "my name is umesh" into a refusal is structural, not
    client-specific: this prefix has its own "YOUR JOB IS FOUR THINGS AND NOTHING ELSE"
    list, which is the exact construction that caused it."""
    assert prompt_module.CONVERSATIONAL_FRAMING in admin_module.ADMIN_SYSTEM_PROMPT
    prompt_text = admin_module.ADMIN_SYSTEM_PROMPT
    assert prompt_text.index("YOUR JOB IS FOUR THINGS") < prompt_text.index(
        prompt_module.CONVERSATIONAL_FRAMING
    )


def test_the_admin_closing_rules_restate_identity_and_framing() -> None:
    """Last is where a model resolves a direct conflict — `prompt.CLOSING_RULES`' argument,
    which is why the client half carries the same two lines. Kept SHORT deliberately:
    repeating the whole prefix would push the conversation out of the model's attention,
    which is the failure the restatement exists to prevent."""
    closing = admin_module.ADMIN_CLOSING_RULES
    assert "you are an AI" in closing
    assert "/legal/subprocessors" in closing
    assert "self-introduction" in closing and "refuse nothing" in closing


# --- the order, which no test covered before ------------------------------------------


def test_the_screen_comes_last_and_the_admin_rules_are_restated_after_it() -> None:
    """`prompt.build_messages`' order exactly, which is what `build_admin_messages`'
    docstring promises and nothing checked: history between prefix and screen, the screen
    fenced, the restated rules after it, the operator's question last."""
    messages = admin_module.build_admin_messages(PAYLOAD)
    last = str(messages[-1]["content"])
    assert last.index(prompt_module.SCREEN_OPEN) < last.index(prompt_module.SCREEN_CLOSE)
    assert last.index(prompt_module.SCREEN_CLOSE) < last.index(admin_module.ADMIN_CLOSING_RULES)
    assert last.endswith("The operator asks: what do I do when engine_error_spike fires?")


def test_the_live_block_sits_between_the_screen_and_the_rules() -> None:
    """An operator viewing one account gets that account's live business state, in the
    client realm's position: after the screen, before the restated rules. Empty on most
    admin requests, and an empty block must not leave a blank stretch in the prompt."""
    with_live = str(admin_module.build_admin_messages(PAYLOAD, live="LIVE: 3 calls")[-1]["content"])
    assert (
        with_live.index(prompt_module.SCREEN_CLOSE)
        < with_live.index("LIVE: 3 calls")
        < with_live.index(admin_module.ADMIN_CLOSING_RULES)
    )
    without = str(admin_module.build_admin_messages(PAYLOAD)[-1]["content"])
    assert "\n\n\n" not in without
