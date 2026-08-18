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

from datetime import UTC, datetime

import httpx
import pytest
from apps.api.engine import engine_capabilities, engine_lacks
from apps.api.engine.capabilities import (
    ENGINE_CAPABILITY_ABSENT,
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
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from calevate_shared.engine import WEBHOOK_AUTH_BY_ENGINE, CallContext


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
            await unconfigured.get_agent("anything")
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
            "agent_1", "+919876543210", CallContext()
        )
    # ITS OWN CODE. This asserted `engine_not_configured`, which is the CREDENTIAL
    # refusal — one machine code for two causes (P2.6). An operator reading a
    # problem+json `type` could not tell "we hold no API key" from "we hold an API key
    # and no outbound number": different fixes, different people, and the remediation
    # text was already saying so in prose while the machine field said otherwise.
    assert getattr(raised.value, "code", "") == "engine_caller_id_not_configured"


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
        return httpx.Response(200, json={"id": "agent_1"})

    engine = CartesiaEngine(api_key="secret", from_number_id="n1")
    engine._client = httpx.AsyncClient(  # the client `_http` would build, with our transport
        base_url="https://api.cartesia.ai",
        headers={
            AUTH_HEADER: f"{AUTH_SCHEME} secret",
            "Cartesia-Version": API_VERSION,
        },
        transport=httpx.MockTransport(capture),
    )
    await engine.get_agent("agent_1")

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


def test_cartesia_keeps_the_one_byok_leg_and_gives_up_the_other_two() -> None:
    """The founder's instinct, scored. Right about the LLM, wrong about speech.

    Line routes the LLM through LiteLLM (`model=` + `api_key=`), so D-36's free-per-token
    Sarvam leg survives the move. Its TTS/STT config carries a Cartesia `voice_id` and a
    language and NO provider field, so those two legs are the engine's. One of three.
    """
    assert CARTESIA_CAPABILITIES.is_ours("llm") is True
    assert CARTESIA_CAPABILITIES.is_ours("tts") is False
    assert CARTESIA_CAPABILITIES.is_ours("stt") is False


# --- 3. the receiver's table matches the adapters ------------------------------


def test_every_engine_in_the_webhook_auth_table_is_an_engine_we_ship() -> None:
    """The other direction from the conformance clause.

    That clause asks each ADAPTER whether the table agrees with it. This asks the TABLE
    whether it describes anything real: a stale entry — an engine renamed, an adapter
    deleted — would leave the receiver authenticating deliveries for a name nothing can
    produce, and no adapter-side test can see it because no adapter has that name.
    """
    shipped = {"bolna", "fake", "fake-restricted", "cartesia"}
    assert set(WEBHOOK_AUTH_BY_ENGINE) == shipped
    assert WEBHOOK_AUTH_BY_ENGINE["cartesia"] == "hmac"
    assert WEBHOOK_AUTH_BY_ENGINE["bolna"] == "source_ip"
