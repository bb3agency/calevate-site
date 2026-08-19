"""The capability seam, and the honesty of the Cartesia adapter's unverified surface.

Three questions, one file, and none of them is answered by the conformance suite:

1. **Does the seam refuse the way the other three seams refuse?** `payment_capability`,
   `lead_retrieval_capability` and `get_sheets_transport` all settled one shape — one
   selector, authored reason codes, never vendor prose — and a fourth seam that drifted
   from it would be the "two ways to do one thing" this repo treats as a defect even when
   both work.

2. **Is the Cartesia adapter's dangerous surface actually inert?** It is written from an
   API nobody here can read. The properties that make that acceptable are testable and
   are tested here: it refuses every webhook rather than guessing a signature, it reports
   no cost rather than guessing a currency, it will not dial without a caller id, and it
   pins the API version on every request.

3. **Do the adapters agree with the table the RECEIVER reads?** The voice-runtime cannot
   import an adapter (hard rule 3), so it authenticates from `WEBHOOK_AUTH_BY_ENGINE`.
   The conformance suite checks that per adapter; this checks the table has no entry
   pointing at an engine that does not exist, which is the other direction.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine import (
    engine_capabilities,
    engine_lacks,
    require_capability,
)
from apps.api.engine.bolna import BolnaEngine
from apps.api.engine.capabilities import (
    ENGINE_CAPABILITY_ABSENT,
    ENGINE_COMPLIANCE_FLOOR_ABSENT,
    NO_CREDENTIALS_REASON,
    EngineCapabilityAbsentError,
)
from apps.api.engine.cartesia import (
    API_VERSION,
    AUTH_HEADER,
    AUTH_SCHEME,
    CARTESIA_CAPABILITIES,
    SIGNATURE_UNIMPLEMENTED_REASON,
    CartesiaEngine,
    parse_transcript,
)
from apps.api.engine.fake import (
    DEFAULT_FAKE_CAPABILITIES,
    DICTATED_SPEECH_CAPABILITIES,
    EXTERNAL_DEPLOYMENT_CAPABILITIES,
    FakeEngine,
)
from calevate_shared.engine import (
    TRUTHFUL_ANSWER_DIRECTIVE,
    TRUTHFUL_ANSWER_MARKER,
    WEBHOOK_AUTH_BY_ENGINE,
    AgentConfig,
    CallContext,
    ModelConfig,
)


def _agent_config() -> AgentConfig:
    """A minimal publishable agent — every adapter's write methods take one of these."""
    return AgentConfig(
        tenant_id="0199a0b0-0000-7000-8000-000000000001",
        agent_id="0199a0b0-0000-7000-8000-000000000002",
        name="Sunrise Clinic receptionist",
        direction="inbound",
        system_prompt="You are the receptionist for Sunrise Clinic.",
        opening_line="Idi AI assistant.",
    )


def _cartesia(*, api_key: str | None = "k", from_number_id: str | None = "num_1") -> CartesiaEngine:
    """A Cartesia adapter whose transport never leaves the process."""
    return CartesiaEngine(
        api_key=api_key,
        from_number_id=from_number_id,
        client=httpx.AsyncClient(
            base_url="https://api.cartesia.ai",
            headers={AUTH_HEADER: f"{AUTH_SCHEME} k", "Cartesia-Version": API_VERSION},
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"id": "a_1"})),
        ),
    )


# --- 1. the seam behaves like the other three ---------------------------------


def test_an_absent_capability_refuses_with_an_authored_code_and_names_itself() -> None:
    """The refusal an operator can act on, by name.

    Two properties together, because either alone is useless: the machine code is STABLE
    (one problem type for the whole family, so the console switches on one value) and the
    capability rides on the exception as a field (so a test, a metric and a log line all
    read the same token rather than parsing English).

    And no vendor name reaches the client. Which engine we rent is our deployment detail;
    a client cannot act on it, and naming it in a problem body leaks an internal.
    """
    error = engine_lacks("tts", engine="cartesia")

    assert isinstance(error, EngineCapabilityAbsentError)
    assert error.code == ENGINE_CAPABILITY_ABSENT
    assert error.capability == "tts"
    problem = error.as_problem()
    assert problem["type"].rsplit("/", 1)[-1] == ENGINE_CAPABILITY_ABSENT
    assert problem["remediation"], "a refusal with no remediation is a dead end"
    assert "cartesia" not in str(problem).lower(), "the vendor name must not reach a client"


async def test_an_engine_without_credentials_refuses_through_the_one_shared_builder(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The deployment-level answer, derived from the adapter rather than from settings.

    This is the state EVERY deployment is in for Cartesia today: the adapter is wired,
    selectable and has no account behind it.

    WHAT THIS TEST USED TO ASSERT, AND WHY IT MOVED (P2.6). It called
    `engine_availability()` — a second deployment-level "can we reach the engine" answer
    that **nothing in production ever called**, beside the one that is wired
    (`missing_engine_credential_keys`, which readiness uses because it NAMES the
    environment key an operator must set). Two answers to one question is a defect even
    when both are correct, so the uncalled one is gone and this asserts the two facts that
    are actually reachable: readiness names the key, and the vendor boundary refuses
    through the ONE shared builder rather than a third hand-rolled ProblemError.
    """
    from apps.api.core.errors import ProblemError

    unconfigured = _cartesia_without_client(api_key=None)
    assert unconfigured.holds_credentials() is False
    assert unconfigured.credential_env_keys, "readiness needs a key to name, not a verdict"

    raised: ProblemError | None = None
    with caplog.at_level("WARNING"):
        try:
            # `get_execution`, NOT `get_agent`: since D-281 the prompt read-back refuses on
            # `agent_hosting` before it ever looks for a credential, which is the right
            # ORDER (a platform that will never answer the question is a stronger fact than
            # a missing key) and makes it useless as a credential probe. Reading a call is a
            # verified Cartesia operation, so it reaches the vendor boundary and refuses
            # there — which is the thing this clause is about.
            await unconfigured.get_execution("anything")
        except ProblemError as exc:
            raised = exc
    assert raised is not None, "an adapter with no credential must refuse at the boundary"
    problem = raised.as_problem()
    assert problem["type"].rsplit("/", 1)[-1] == "engine_not_configured"
    assert "cartesia" not in str(problem).lower(), (
        "the vendor name reached a client — it belongs in the operator log, which is "
        "exactly what `engine_not_configured` takes its `reason` for"
    )
    # And it DID reach the operator log, naming which engine. The refusal a client sees
    # is deliberately identical across engines; the line an operator acts on is not.
    reasons = [getattr(r, "reason", None) for r in caplog.records]
    assert f"{NO_CREDENTIALS_REASON}:cartesia" in reasons, reasons

    # The capability answer survives the credential answer, and that is deliberate: an
    # engine with a knowledge base and no API key still HAS a knowledge base. Collapsing
    # the two would make "unconfigured" and "incapable" the same fact.
    assert unconfigured.capabilities.knowledge_base is True


def _cartesia_without_client(*, api_key: str | None) -> CartesiaEngine:
    return CartesiaEngine(api_key=api_key, from_number_id=None)


def test_the_capability_selector_answers_about_the_adapter_it_is_given() -> None:
    """One selector, and it never re-reads settings behind the caller's back.

    The two callers that already hold an adapter (the publish path, the KB publish path)
    pass it, so the capability they check belongs to the adapter they are about to call.
    A selector that fetched its own would eventually check a different instance.
    """
    assert engine_capabilities(_cartesia()) == CARTESIA_CAPABILITIES
    assert engine_capabilities(FakeEngine()).tts == "ours"
    assert (
        engine_capabilities(FakeEngine(capabilities=DICTATED_SPEECH_CAPABILITIES)).tts == "engine"
    )


# --- 2. the Cartesia adapter's unverified surface is inert ---------------------


def test_cartesia_refuses_every_webhook_rather_than_guessing_a_signature() -> None:
    """FAIL CLOSED, and stay closed. This is the single most dangerous line in the module.

    Line signs its webhooks; the scheme is not sourced. A signature check is three
    independent guesses — header, canonical string, digest — and the wrong direction to be
    wrong in is `ok=True`: that is a public unauthenticated write endpoint reporting
    `method="hmac"`, i.e. wearing the word "verified".

    So every delivery is refused, including one carrying a plausible-looking signature
    header, and the reason is OUR code rather than a vendor's message.
    """
    engine = _cartesia()
    for headers in ({}, {"X-Cartesia-Signature": "deadbeef"}, {"Authorization": "Bearer x"}):
        verdict = engine.verify_webhook(headers, b'{"status":"completed"}', "13.203.39.153")
        assert verdict.ok is False, "a webhook was accepted on an unimplemented scheme"
        assert verdict.method == "hmac", "the declared method must still be reported"
        assert verdict.reason == SIGNATURE_UNIMPLEMENTED_REASON


def test_cartesia_reports_no_cost_rather_than_a_guessed_currency() -> None:
    """No cost is a visible hole; a stamped guess is an unauditable invoice.

    Hard rule 7 and `CostBreakdown` require the adapter to convert at capture and STAMP
    the rate so a ledger row can be re-derived. Nothing sourced says what currency Line
    quotes, so a `total_inr` from this adapter would be a number that looks auditable and
    is not — which is the exact defect `CostBreakdown.currency_stated` was introduced to
    expose. `charge_for_call` records nothing for this engine, deliberately.
    """
    snapshot = _cartesia()._snapshot(
        {"agent_call_id": "c1", "status": "completed", "total_cost": 12.5, "currency": "USD"}
    )
    assert snapshot.cost is None, "a cost was reported for a vendor whose currency is unsourced"


async def test_cartesia_will_not_dial_without_a_caller_id() -> None:
    """`from_number_id` is required by the outbound shape and we have no value for it.

    Which number a tenant dials FROM is a DLT 140/160 decision in our own schema, not a
    detail to let the vendor pick. Dialling from whatever the account happens to hold
    first is how a promotional campaign goes out on a service-series number.
    """
    with pytest.raises(Exception) as raised:
        await _cartesia(from_number_id=None).start_outbound_call(
            "agent_1",
            "+919876543210",
            # A floor-CARRYING context, because since D-282 an empty one is refused one
            # line earlier: this adapter's agents are deployed elsewhere, so a dial with no
            # truthful-answer rule on it never reaches the caller-id question. Passing the
            # composed prompt is what makes this clause still measure the ORDER it names.
            CallContext(system_prompt=f"Script.\n\n{TRUTHFUL_ANSWER_DIRECTIVE}"),
        )
    # ITS OWN CODE. This asserted `engine_not_configured`, which is the CREDENTIAL
    # refusal — one machine code for two causes (P2.6). An operator reading a
    # problem+json `type` could not tell "we hold no API key" from "we hold an API key
    # and no outbound number": different fixes, different people, and the remediation
    # text was already saying so in prose while the machine field said otherwise.
    # THE FLOOR OUTRANKS THE CALLER ID, and that ordering is now what this clause pins.
    # Both refusals are named and both are correct; the one that must come first is the
    # compliance failure rather than the configuration one, because an operator who fixes a
    # caller id and dials again must not discover the floor problem on a live line. The
    # caller-id branch itself is unreachable on this adapter until gate 19(b) says which
    # outbound field carries a prompt, and `_agent_body`'s removal is why: see
    # `test_cartesia_refuses_every_dial_because_the_floor_cannot_ride_the_call`.
    assert getattr(raised.value, "code", "") == ENGINE_COMPLIANCE_FLOOR_ABSENT


async def test_cartesia_pins_the_api_version_on_every_request() -> None:
    """An unpinned date-versioned API is a silent breaking change on someone else's
    release schedule, and the failure mode is a field quietly vanishing from a response we
    parse rather than an error anybody sees.

    Asserted on a request the adapter builds ITSELF (no injected client), because the
    header is set in `_http` and an injected client would prove only that the test set it.
    """
    seen: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, json={"documents": []})

    engine = CartesiaEngine(api_key="secret", from_number_id="n1")
    engine._client = httpx.AsyncClient(  # the client `_http` would build, with our transport
        base_url="https://api.cartesia.ai",
        headers={
            AUTH_HEADER: f"{AUTH_SCHEME} secret",
            "Cartesia-Version": API_VERSION,
        },
        transport=httpx.MockTransport(capture),
    )
    # `list_kb`, NOT `get_agent`: since D-281 the prompt read-back refuses on
    # `agent_hosting` before building a request, so it can no longer prove a header was
    # sent. Any operation this adapter still performs does — this one is a plain GET.
    await engine.list_kb("agent_1")

    assert seen.get("cartesia-version") == API_VERSION
    assert seen.get("authorization") == "Bearer secret"


def test_cartesia_pins_the_rest_api_version_and_not_the_line_websocket_one() -> None:
    """D-270. The pin was `2026-04-03`, which is not an API version at all.

    That string is `line/voice_agent_app.py:129`, and its only use (`:217`) is the body
    OUR deployed agent returns to Cartesia's harness from `POST /chats` — it versions the
    in-call WEBSOCKET protocol, travels agent→harness, and is a body field rather than a
    header. Pinning it as `Cartesia-Version` asked the REST control plane for a version of
    a different thing, and the failure mode is a response shape changing under a header
    the vendor cannot interpret.

    `2026-08-14` is what all three of Cartesia's own current clients send
    (`cartesia-python/src/cartesia/_client.py:244`, `cartesia-js/src/client.ts:801`,
    `cartesia-mcp/cartesia_mcp/api_version.py`). Asserted as a LITERAL rather than against
    an imported constant, because a test that compares a constant to itself would have
    passed just as happily with the wrong value in it.
    """
    assert API_VERSION == "2026-08-14"


def test_cartesia_authenticates_the_way_cartesias_own_clients_do() -> None:
    """D-270. The adapter sent `X-API-Key`, which is a published but superseded form.

    Both generated clients build `Authorization: Bearer <key>` for every operation
    including `client.agents.*` (`cartesia-python/src/cartesia/_client.py:232-236`,
    `cartesia-js/src/client.ts:353`). The `X-API-Key` sightings sit beside older
    `Cartesia-Version` values, which is what a superseded auth form looks like.

    Being wrong here 401s every request, which is the safe direction — but being wrong
    here also makes every OTHER finding in this slice untestable against a live account,
    which is why it is asserted rather than left to the pilot.
    """
    assert AUTH_HEADER == "Authorization"
    assert AUTH_SCHEME == "Bearer"


def test_cartesia_reads_the_call_object_cartesia_actually_returns() -> None:
    """D-270. Four field names were invented, and every one of them was silent.

    READ AT SOURCE, `cartesia-python/src/cartesia/types/agents/agent_call.py`: the id is
    `id`, the instants are `start_time`/`end_time`, and the numbers are NESTED under
    `telephony_params` as `from`/`to`. The adapter was reading `agent_call_id`,
    `started_at`/`created_at`, `ended_at`, and top-level `from_number`/`to_number` — so on
    a real payload it produced a snapshot with no id, no timestamps and no numbers, and
    reported it as a healthy completed call.

    The payload below carries ONLY the verified names, which is what makes this fail
    without the fix rather than pass on a fallback.
    """
    snapshot = _cartesia()._snapshot(
        {
            "id": "call_9",
            "agent_id": "agent_xyz",
            "status": "completed",
            "start_time": "2026-08-10T09:15:00Z",
            "end_time": "2026-08-10T09:16:35Z",
            "telephony_params": {"from": "+919876543210", "to": "+911140000000"},
        }
    )

    assert snapshot.engine_call_id == "call_9"
    assert snapshot.engine_agent_ref == "agent_xyz"
    assert snapshot.started_at is not None and snapshot.ended_at is not None
    assert snapshot.from_e164 == "+919876543210"
    assert snapshot.to_e164 == "+911140000000"
    # DERIVED, because `AgentCall` carries no duration field at all. Two instants we read
    # are the same information; a made-up number would not be.
    assert snapshot.duration_s == 95


def test_cartesia_treats_a_cancelled_call_as_over() -> None:
    """D-270, and it is the one mapping defect with a runtime cost.

    `cancelled` is a member of their status enum (`agent_call.py:34`) and was absent from
    `_TERMINAL_RAW`. It already degraded to `failed` through the unmapped default, so the
    STATUS looked right — but a non-terminal cancelled call is re-read on every
    reconciliation tick for ever and never reaches the post-call pipeline.
    """
    snapshot = _cartesia()._snapshot({"id": "c_1", "status": "cancelled"})

    assert snapshot.status == "failed"
    assert snapshot.terminal is True, "a cancelled call is over; nothing more will arrive"


def test_cartesia_transcript_reads_text_and_never_files_a_log_row_as_speech() -> None:
    """D-270. Two defects in one parser, both invisible in a passing suite.

    READ AT SOURCE (`agent_transcript.py:62-68, 85-89`): the utterance is `text`, and
    `"system` is used to indicate logs during the conversation such as `log_event` or
    `log_metric`". The parser preferred `content` (never populated by this vendor) and
    mapped every non-agent role to `caller` — so a `log_event` row would have been written
    into a client's transcript as something the caller said.

    A skipped log row is NOT counted as unparsed: `transcript_lines_unparsed` means
    "speech we could not read", and inflating it with rows that are not speech would make
    the one instrument that detects a broken parser fire on every healthy call.
    """
    turns, unparsed = parse_transcript(
        [
            {"role": "assistant", "text": "Namaskaram."},
            {"role": "user", "text": "Appointment kavali."},
            {"role": "system", "log_event": {"event": "kb_lookup", "metadata": {}}},
        ],
        call_id="c_1",
    )

    assert [(t.speaker, t.text) for t in turns] == [
        ("agent", "Namaskaram."),
        ("caller", "Appointment kavali."),
    ]
    assert unparsed == 0


async def test_cartesia_lists_calls_the_only_way_the_vendor_allows() -> None:
    """D-270. The listing was a request the vendor cannot serve.

    READ AT SOURCE (`resources/agents/calls.py:95-98`, `types/agents/call_list_params.py`):
    *"Lists calls sorted by start time in descending order for a specific agent.
    `agent_id` is required and if you want to include `transcript` in the response, add
    `expand=transcript`."* There is no time-filter parameter of any kind.

    So the previous call — a global `GET /agents/calls?start_time=…` — was missing the one
    required parameter and sending one that does not exist. This asserts the shape of what
    goes out, because the reconciliation poller is D-31's guarantee of record and a
    listing that 4xxs is a guarantee that silently recovers nothing.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/agents":
            return httpx.Response(200, json={"summaries": [{"id": "agent_a"}]})
        return httpx.Response(200, json={"data": []})

    engine = CartesiaEngine(
        api_key="k",
        from_number_id="n1",
        client=httpx.AsyncClient(
            base_url="https://api.cartesia.ai", transport=httpx.MockTransport(handler)
        ),
    )
    await engine.list_executions(since=datetime(2026, 8, 10, tzinfo=UTC))

    paths = [request.url.path for request in seen]
    assert paths == ["/agents", "/agents/calls"], (
        "the per-agent listing is only reachable by first asking which agents exist"
    )
    query = seen[-1].url.params
    assert query.get("agent_id") == "agent_a", "`agent_id` is required; without it this 4xxs"
    assert query.get("expand") == "transcript", "otherwise the vendor returns no transcript"
    assert "start_time" not in query, "no time filter exists on this endpoint; we invented one"
    assert int(query.get("limit") or 0) == 100


def test_cartesia_declares_no_indian_number_class() -> None:
    """The blocker, encoded rather than described.

    Line's number paths yield no DLT-registered 140/160-series Indian number, and whether
    it accepts BYOC SIP from an Indian carrier is UNVERIFIED (TRD §10.5) — the single
    question that decides whether this engine is usable for us at all. An empty
    `number_series` is the only answer that is not a guess, and it makes every series
    refuse by name instead of returning a number that would be recorded as dialable.
    """
    assert CARTESIA_CAPABILITIES.number_series == frozenset()
    for series in ("140", "160", "standard"):
        assert not CARTESIA_CAPABILITIES.provisions(series)  # type: ignore[arg-type]


def test_cartesia_claims_no_byok_leg_through_a_port_that_reaches_no_agent() -> None:
    """The founder's instinct was right about the VENDOR, and this port cannot use it.

    Line routes the LLM through LiteLLM (`model=` + `api_key=`), so D-36's free-per-token
    Sarvam leg really does run on Line — TRD §10.5's table says so about the VENDOR and
    stays correct. What changed under D-281 is the reading of `SpeechControl`, whose own
    docstring defines `ours` as "our provider and model strings REACH THE VENDOR": on this
    platform `LlmAgent(model=...)` is a constructor call inside the DEPLOYED PROGRAM,
    `AgentSummary` carries no `model`, and `AgentUpdateParams` is four fields none of which
    is one. There is no endpoint this adapter holds through which a `ModelConfig` value
    could arrive — the same argument `transfer=False` already makes about a transfer
    feature the vendor genuinely has.

    NOT a flag weakened to make something pass. It is the descriptor saying LESS, derived
    from the same VERIFIED-SDK absence that settled `agent_hosting` — and with the three
    agent-write methods refusing, `require_speech_leg` no longer runs on this adapter at
    all, so `llm="ours"` would have become a claim nothing could contradict.
    """
    assert CARTESIA_CAPABILITIES.agent_hosting == "external_deployment"
    for leg in ("stt", "llm", "tts"):
        assert CARTESIA_CAPABILITIES.is_ours(leg) is False, (
            f"`{leg}` is declared ours on an engine that holds no agent record of ours, so "
            "nothing in this repository could send a value for it or read one back"
        )


# --- 3. the receiver's table matches the adapters ------------------------------


def test_every_engine_in_the_webhook_auth_table_is_an_engine_we_ship() -> None:
    """The other direction from the conformance clause.

    That clause asks each ADAPTER whether the table agrees with it. This asks the TABLE
    whether it describes anything real: a stale entry — an engine renamed, an adapter
    deleted — would leave the receiver authenticating deliveries for a name nothing can
    produce, and no adapter-side test can see it because no adapter has that name.
    """
    shipped = {"bolna", "fake", "fake-restricted", "fake-deployed", "cartesia"}
    assert set(WEBHOOK_AUTH_BY_ENGINE) == shipped
    assert WEBHOOK_AUTH_BY_ENGINE["cartesia"] == "hmac"
    assert WEBHOOK_AUTH_BY_ENGINE["bolna"] == "source_ip"


# --- 4. agent hosting: the two homes hard rule 5 has (D-280..D-282) -------------


async def test_cartesia_refuses_the_three_agent_methods_that_describe_no_endpoint() -> None:
    """D-281. The port used to require a create endpoint Cartesia does not serve.

    `cartesia-python`'s `AgentsResource` has `retrieve`, `update`, `list`, `delete`,
    `list_phone_numbers` and `list_templates` and NO `create`; `AgentSummary` carries
    `git_repository`/`git_deploy_branch` and no prompt, greeting or model. D-270 could
    only relabel the three methods that assume otherwise, because `EngineCapabilities`
    had no way to say "this engine does not host an agent of ours". It has one now.

    ALL THREE, and by the SAME capability: a caller that asked before calling must get
    the answer the method gives, which is the whole of D-93. `create_agent` refusing
    while `update_agent` accepted would leave the second reachable by any caller
    supplying a ref it invented — and on this shape every ref is invented.
    """
    engine = _cartesia()
    cfg = _agent_config()
    for label, call in (
        ("create_agent", lambda: engine.create_agent(cfg)),
        ("update_agent", lambda: engine.update_agent("agent_1", cfg)),
        ("get_agent", lambda: engine.get_agent("agent_1")),
    ):
        with pytest.raises(EngineCapabilityAbsentError) as raised:
            await call()
        assert raised.value.capability == "agent_hosting", label
        problem = raised.value.as_problem()
        assert problem["remediation"], f"`{label}` refused with nothing a human can do"
        assert "cartesia" not in str(problem).lower(), (
            "the vendor name reached a client (hard rule 2) — which engine is running is "
            "our deployment detail and a client cannot act on it"
        )


async def test_cartesia_refuses_every_dial_because_the_floor_cannot_ride_the_call() -> None:
    """D-282. Hard rule 5 did not get weaker to accommodate an engine that cannot hold it.

    With no agent record, the truthful-answer directive can only reach a Cartesia call as
    per-call data. The outbound shape this adapter implements (`POST /agents/calls`,
    REPORTED-DOCS) names `from_number_id`, `agent_id`, `ringing_timeout_seconds` and
    `outbound_calls` — no prompt field — and the per-call prompt that IS read at source
    (`agent: {system_prompt, introduction}` on a `start` event) belongs to the WebSocket
    Calls API, which this adapter does not speak.

    So it refuses, and it refuses even when the CALLER supplies a perfectly good prompt:
    `require_call_compliance_floor` is asked what this adapter puts ON THE WIRE, not what
    it was handed. A context-shaped check would have let a floor-carrying context satisfy
    the guard while the request body dropped it — the silent drop the guard exists for.
    """
    engine = _cartesia()
    carried = CallContext(system_prompt=f"Script.\n\n{TRUTHFUL_ANSWER_DIRECTIVE}")
    for label, ctx in (("no prompt", CallContext()), ("a valid prompt", carried)):
        with pytest.raises(ProblemError) as raised:
            await engine.start_outbound_call("agent_1", "+919876543210", ctx)
        assert raised.value.code == ENGINE_COMPLIANCE_FLOOR_ABSENT, (
            f"dialling with {label} was refused for some other reason, or placed"
        )


async def test_an_externally_deployed_engine_carries_our_prompt_onto_the_call() -> None:
    """THE POSITIVE HALF OF THE ALTERNATIVE CONTRACT, observed rather than asserted.

    The conformance suite can only probe this negatively — `start_outbound_call` returns a
    handle and offers no read-back, so "it carried our prompt" and "it dropped our prompt"
    are the same observation from the port, which is exactly `transfer`'s problem. Here the
    fixture IS its own vendor, so the round trip can be watched end to end: the prompt goes
    in on the `CallContext` and comes back off the call the engine is running.

    Without this, `EXTERNAL_DEPLOYMENT_CAPABILITIES` would prove only that an engine of
    that shape refuses things, and the branch where one actually dials would be contract
    nothing executes.
    """
    engine = FakeEngine(capabilities=EXTERNAL_DEPLOYMENT_CAPABILITIES, name="fake-deployed")
    prompt = f"You are the receptionist.\n\n{TRUTHFUL_ANSWER_DIRECTIVE}"
    handle = await engine.start_outbound_call(
        "agent_deployed", "+919876543210", CallContext(system_prompt=prompt)
    )
    assert engine.call_prompt(handle) == prompt, (
        "the engine is not running the prompt it was dialled with, so the truthful-answer "
        "rule reached nothing — and no read-back anywhere on this shape could detect it"
    )
    assert TRUTHFUL_ANSWER_MARKER in (engine.call_prompt(handle) or ""), (
        "the prompt that reached the call does not carry the rule a client cannot switch off"
    )


async def test_a_dial_with_no_floor_is_refused_and_one_with_a_floor_is_placed() -> None:
    """Both directions on one engine, because only the pair is falsifiable.

    An adapter that refused everything would satisfy the negative half and be useless; one
    that accepted everything would satisfy the positive half and be dangerous. The clause
    that matters is that the SAME engine answers differently to the two contexts, which is
    the shape `test_a_claimed_verification_method_actually_rejects_somebody` uses for
    webhook methods and `require_speech_leg` uses for a dictated voice.
    """
    engine = FakeEngine(capabilities=EXTERNAL_DEPLOYMENT_CAPABILITIES, name="fake-deployed")
    with pytest.raises(ProblemError) as raised:
        await engine.start_outbound_call("agent_deployed", "+919876543210", CallContext())
    assert raised.value.code == ENGINE_COMPLIANCE_FLOOR_ABSENT

    # A prompt that is REAL but does not carry the rule — the case a hand-rolled adapter
    # produces, and the one a "is there a prompt at all" check would wave through.
    with pytest.raises(ProblemError):
        await engine.start_outbound_call(
            "agent_deployed", "+919876543210", CallContext(system_prompt="You are helpful.")
        )

    handle = await engine.start_outbound_call(
        "agent_deployed",
        "+919876543210",
        CallContext(system_prompt=f"Script.\n\n{TRUTHFUL_ANSWER_DIRECTIVE}"),
    )
    assert isinstance(handle, str) and handle


async def test_an_engine_that_hosts_agents_needs_no_per_call_prompt() -> None:
    """The other half of the split, so the guard cannot become "every dial needs a prompt".

    On a `control_plane` engine the directive is agent-record state that `publish_agent`
    wrote and `verification.judge` PROVED the engine is running. A second copy per call
    would be one string with two authorities, and the guard must not demand one — a dial
    that started failing on Bolna because an unrelated engine cannot hold a prompt is the
    regression this asserts against.
    """
    engine = FakeEngine()
    ref = await engine.create_agent(_agent_config())
    handle = await engine.start_outbound_call(ref, "+919876543210", CallContext())
    assert isinstance(handle, str) and handle
    assert engine.call_prompt(handle) is None, (
        "a control-plane engine was handed a per-call prompt, so one agent's script now "
        "has two authorities and they can disagree"
    )


def test_the_hosting_capability_answers_through_the_one_generic_ask() -> None:
    """`has("agent_hosting")` and `hosts_agents()` are one fact, for `is_ours`'s reason.

    A caller holding a capability NAME (a screen, a metric label, the refusal builder) and
    a caller holding the descriptor must not be able to get different answers — that
    divergence is what `EngineCapabilityName` is a closed Literal to prevent.
    """
    for caps in (DEFAULT_FAKE_CAPABILITIES, DICTATED_SPEECH_CAPABILITIES):
        assert caps.hosts_agents() is True
        assert caps.has("agent_hosting") is True
    for caps in (EXTERNAL_DEPLOYMENT_CAPABILITIES, CARTESIA_CAPABILITIES):
        assert caps.hosts_agents() is False
        assert caps.has("agent_hosting") is False


async def test_publishing_to_an_engine_that_hosts_no_agents_is_refused_not_recorded() -> None:
    """The publish path degrades honestly: it refuses, and the console is told first.

    A publish that "succeeded" against an engine with no create endpoint is the defect
    D-281 removes. `publish_agent` asks the capability before the account check's lock and
    before the vendor, so nothing is written and no `engine_agent_ref` can exist — which is
    also why `engine_drift_for` reports `not_published` truthfully on such an engine
    without needing a new state or a migration.
    """
    engine = FakeEngine(capabilities=EXTERNAL_DEPLOYMENT_CAPABILITIES, name="fake-deployed")
    with pytest.raises(EngineCapabilityAbsentError) as raised:
        require_capability("agent_hosting", engine=engine)
    assert raised.value.capability == "agent_hosting"
    assert raised.value.as_problem()["remediation"], (
        "an operator who cannot publish must be told what to do instead"
    )


async def test_bolna_sends_the_reply_ceiling_and_the_sampling_it_chose() -> None:
    """D-283. Unsent means the vendor's defaults apply, and one of them was a real knob.

    VERIFIED-OSS at `bolna-ai/bolna@cd2e192`, `bolna/models.py`: `Llm.max_tokens` defaults
    to **100** and `Llm.temperature` to **0.1**, and `task_manager.__setup_llm` reads both
    with bare subscripts off `llm_agent_config`. Our body omitted them, so the stored
    `agent_config.model_dump()` filled the defaults and every agent on the platform ran
    with a 100-token ceiling on each reply that nobody had chosen.

    ASSERTED AS LITERALS, not against a constant, for the reason
    `test_cartesia_pins_the_rest_api_version_and_not_the_line_websocket_one` gives: a test
    comparing a value to itself would have passed just as happily with the wrong number in
    it. What the numbers ARE is argued at the line in the adapter — briefly: a cap is a
    safety valve rather than a style control, 100 tokens is ~45 Telugu words at the
    fertility Indic scripts actually carry, and the LLM leg is free per token so headroom
    costs nothing; 0.1 is the vendor's default and is RIGHT for an agent that must not
    paraphrase a compliance sentence away, which is exactly why it is written down rather
    than inherited from somebody else's release note.
    """
    seen: dict[str, Any] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={"agent_id": "agent_1"})

    engine = BolnaEngine(
        api_key="k",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(
            base_url="https://api.bolna.ai", transport=httpx.MockTransport(capture)
        ),
    )
    await engine.create_agent(
        _agent_config().model_copy(
            update={
                "models": ModelConfig(
                    stt_provider="sarvam",
                    stt_model="saaras:v3",
                    llm_model="sarvam-105b",
                    tts_provider="sarvam",
                    tts_voice="bulbul:v3",
                )
            }
        )
    )

    llm = seen["agent_config"]["tasks"][0]["tools_config"]["llm_agent"]["llm_config"]
    assert llm["max_tokens"] == 400, (
        "the reply ceiling is not sent, so the vendor's 100-token default applies and "
        "every agent reply is truncated mid-sentence at roughly 45 Telugu words"
    )
    assert llm["temperature"] == 0.1, (
        "the sampling temperature is not sent, so it rides a vendor default that can "
        "change without our deploying — on a prompt carrying the truthful-answer rule"
    )
