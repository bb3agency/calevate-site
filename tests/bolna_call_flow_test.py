"""What the adapter puts on the wire about WHO places a call, and WHEN.

Three of Bolna's call-flow features would each place, delay or repeat a dial on their
own scheduler — outside `compliance.service.check_dispatch`, which is the only thing in
this system that asks the platform halt, the tenant's cap, the calling hour and the DNC
list. Hard rule 5 says DNC additions take effect before the next dispatch tick; a dial
the vendor holds and fires later has no tick.

    | vendor feature          | where it is set                      | our posture |
    | ----------------------- | ------------------------------------ | ----------- |
    | `retry_config`          | `POST /call`, `POST /batches`        | never sent  |
    | `bypass_call_guardrails`| `POST /call`                         | never sent  |
    | `auto_reschedule`       | agent `task_config` + dashboard      | sent False  |
    | `dtmf_enabled`          | agent `task_config` + dashboard      | sent False  |
    | `calling_guardrails`    | agent `agent_config` + dashboard     | not sent    |

The first two are absences and the tests below pin them AS absences, because an absence
is the one property a reviewer cannot see in a diff and a future contributor can undo
with a single keyword. The two `False`s are stated rather than inherited for
`multilingual_config`'s reason — an omitted key is a field left as it was — sharpened by
the fact that both also have a Call Tab toggle a console user can flip without a deploy.

`calling_guardrails` is the deliberate exception and is argued in
`docs/evidence/bolna-call-flows.md` rather than here: their window would hold an
out-of-window dial and fire it at the next allowed hour, which is the ungated dial the
other four rows exist to prevent, and our own gate is upstream of it and stricter.

**NOT A DUPLICATE OF `bolna_contract_test`'s
`test_the_dial_body_carries_only_fields_the_vendor_declares`, and the difference is the
whole reason both exist.** That one asks a SCHEMA question — is
every key we send declared by `POST /call`, so nothing is silently ignored or 422'd — and
answers it with a subset check against the vendor's full field list, `retry_config` and
`bypass_call_guardrails` INCLUDED. This one asks a COMPLIANCE question about the same
body: are we handing the vendor a scheduler that dials outside our gate. A body carrying
`retry_config` passes that test and fails this one, which is exactly the arrangement
wanted — the vendor's schema is not the authority on what Indian telecom law lets us send.

Evidence for every claim is a page under `bolna-findings/mirror/pages/`, cited at the
assertion that encodes it (VERIFIED-VENDOR-DOCS).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
from apps.api.engine.bolna import BASE_URL, BolnaEngine
from calevate_shared.engine import AgentConfig, CallContext, ModelConfig


def _engine(handler: Any) -> BolnaEngine:
    return BolnaEngine(
        api_key="k",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


def _config() -> AgentConfig:
    return AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id="0199a0b0-0000-7000-8000-000000000002",
        name="Sunrise Clinic outbound",
        direction="outbound",
        system_prompt="You are calling on behalf of Sunrise Clinic.",
        opening_line="Idi AI assistant.",
        models=ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v3",
            llm_model="sarvam-105b",
            tts_provider="sarvam",
            tts_voice="bulbul:v3",
        ),
    )


async def _dial_body() -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/call"
        seen.update(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={"execution_id": "exec_1", "status": "queued"})

    await _engine(handler).start_outbound_call("agent_1", "+919876543210", CallContext())
    return seen


async def _agent_task_config() -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/agent"
        seen.update(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={"agent_id": "agent_1"})

    await _engine(handler).create_agent(_config())
    task: dict[str, Any] = seen["agent_config"]["tasks"][0]["task_config"]
    return task


# --- the dial body: two keys that must never appear ---------------------------


async def test_a_dial_never_hands_the_vendor_a_second_retry_ladder() -> None:
    """`retry_config` on `POST /call` makes BOLNA re-dial a no-answer, busy or failed
    call on its own schedule — `{"enabled": true, "max_retries": 3,
    "retry_intervals_minutes": [30, 60, 120]}` is their documented example
    (`bolna-findings/mirror/pages/guides/outbound/auto-retry.md`).

    `workers/campaign_dispatch._record_failure` already IS that ladder, and its defaults
    are almost the same numbers — `max_attempts` 3, `backoff_minutes` [30, 120]. Stacked,
    the two do not add up to a longer ladder, they double every rung of it: one person
    called twice per attempt, which is a TRAI complaint and twice the wallet.

    Ours has to be the one that survives, and not because it was first. Each rung of ours
    returns the contact to `pending` with `next_attempt_at`, so the NEXT dispatch tick
    re-runs `check_dispatch` — the halt, the cap, the hour and the DNC list — before the
    second ring. Theirs re-dials from their scheduler, so a number that joined the DNC
    list between attempt 1 and attempt 2 is called anyway. Hard rule 5 forbids exactly
    that, so `retry_config` is not a knob to tune, it is a key that must not be present.
    """
    assert "retry_config" not in await _dial_body(), (
        "the vendor's retry ladder re-dials without our compliance gate; ours is the "
        "one that must run"
    )


async def test_a_dial_never_carries_the_documented_compliance_bypass() -> None:
    """`bypass_call_guardrails: true` on `POST /call` *"skips time validation for a
    specific call"* and it *"goes through immediately regardless of the configured
    window"* (`bolna-findings/mirror/pages/guides/outbound/calling-guardrails.md`).

    The vendor recommends it for development — their own accordion is titled "Bypass for
    Testing in Development" — and that recommendation is the thing CLAUDE.md hard rule 5
    names in so many words: never add a bypass "for testing", use staging fixtures. It is
    pinned here because it is a single word in a dict that would leave no other trace, on
    the one code path where the consequence is a real phone ringing in somebody's house
    at 2am.

    Its absence is worth having even though the flag only relaxes a window we do not set:
    the day `calling_guardrails` is turned on — in the dashboard, by somebody who is not
    reading this file — this key is the difference between a guardrail and a decoration.
    """
    assert "bypass_call_guardrails" not in await _dial_body(), (
        "hard rule 5: no bypass, not even for testing"
    )


async def test_the_dial_body_is_exactly_what_we_meant_to_send() -> None:
    """The two assertions above name two keys; this one closes the set.

    A `POST /call` body is small enough to state completely, and stating it completely is
    what makes the next scheduling feature the vendor ships — `scheduled_at`, a second
    bypass, whatever replaces `retry_config` — fail here rather than arrive silently on
    the dial path. Add a key deliberately and this test is one line; add one by copying a
    curl example out of their docs and it stops you.
    """
    assert set(await _dial_body()) == {"agent_id", "recipient_phone_number", "user_data"}


# --- the agent body: two conversation flags stated at their safe value ---------


async def test_every_publish_refuses_the_in_call_callback_scheduler() -> None:
    """`ConversationConfig.auto_reschedule` — *"Automatically reschedule the call when
    the user asks to be called back at a later time"*, `default: false`
    (`bolna-findings/mirror/pages/api-reference/agent/v2/create.md`).

    A callback booked inside the call is placed by THEIR scheduler and never reaches
    `check_dispatch`, so the DNC list, the halt, the cap and the agent gate are asked once
    and never again. And the window such a request is validated against is, with no
    `calling_guardrails` set, *"the LLM reads time restrictions from the system prompt"*
    (`guides/outbound/calling-guardrails.md`, priority 2 of 3) — a tenant-authored string.
    A script saying the business is available round the clock would book a 23:00 callback
    against Calevate's telemarketer registration.

    PRESENT AND FALSE, not absent: an omitted key leaves the vendor's stored value alone,
    and this one has a Call Tab switch ("Auto Reschedule") that a console user can turn on
    for a live agent without our deploying.
    """
    assert (await _agent_task_config())["auto_reschedule"] is False


async def test_every_publish_refuses_keypad_input() -> None:
    """`ConversationConfig.dtmf_enabled`, `default: false`.

    Keypad digits are not a side channel: they are delivered to the agent as the
    conversation message `dtmf_number: <digits>`
    (`bolna-findings/mirror/pages/guides/inbound/dtmf.md`), so they land in the transcript
    this platform stores, redacts and exports — and the vendor's own worked use cases are
    PIN and OTP verification, an account number, and "a password or card number".

    The redactor does not save us, which is why this is pinned rather than tolerated: a
    keypad-entered 4-digit PIN arrives as `dtmf_number: 1234`, too short for
    `redaction._PHONE_SPAN_RE`'s numbering-plan validator, too short for `_CARD_RE`, and
    invisible to `_OTP_RE`, which needs the literal word otp/code/pin/password within 20
    characters of the digits and gets `dtmf_number`.

    Nothing in this product asks a caller to press a key. When an IVR product does want
    it, this line is where the decision gets made — with a redaction rule beside it.
    """
    assert (await _agent_task_config())["dtmf_enabled"] is False


async def test_the_call_can_always_end_by_itself() -> None:
    """The money half of the same block, pinned because a call that never terminates
    bills until somebody notices.

    Two independent stops, both from `ConversationConfig`: `call_terminate` (*"The call
    automatically disconnects reaching this limit"*) and `hangup_after_silence`. Ours are
    STATED rather than inherited, and on the first of the two that matters — the vendor's
    own default is 90 seconds, which would truncate a receptionist mid-appointment, while
    `agents.service.effective_call_cap` resolves a NULL column to 600 and the DB
    constraint bounds the column to 60-3600. So there is no configuration of an agent in
    this product that produces an unbounded call, and no publish that leaves the ceiling
    to a vendor release note.
    """
    task = await _agent_task_config()

    assert task["call_terminate"] == 600, "the platform default, not the vendor's 90"
    assert task["hangup_after_silence"] == 10
