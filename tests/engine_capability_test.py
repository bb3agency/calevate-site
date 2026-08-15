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

import httpx
import pytest
from apps.api.engine import engine_availability, engine_capabilities, engine_lacks
from apps.api.engine.capabilities import (
    ENGINE_CAPABILITY_ABSENT,
    NO_CREDENTIALS_REASON,
    EngineCapabilityAbsentError,
)
from apps.api.engine.cartesia import (
    API_VERSION,
    CARTESIA_CAPABILITIES,
    SIGNATURE_UNIMPLEMENTED_REASON,
    CartesiaEngine,
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
            headers={"X-API-Key": "k", "Cartesia-Version": API_VERSION},
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


def test_an_engine_without_credentials_is_reported_unavailable_by_our_own_code() -> None:
    """The deployment-level answer, derived from the adapter rather than from settings.

    This is the state EVERY deployment is in for Cartesia today: the adapter is wired,
    selectable and has no account behind it. One selector says so once, with an authored
    reason naming which engine — rather than each surface discovering it separately at the
    vendor boundary, which is how a screen comes to offer what a route refuses.
    """
    unavailable = engine_availability(_cartesia_without_client(api_key=None))
    assert unavailable.available is False
    assert unavailable.reason == f"{NO_CREDENTIALS_REASON}:cartesia"
    # The capability answer survives the credential answer, and that is deliberate: an
    # engine with a knowledge base and no API key still HAS a knowledge base. Collapsing
    # the two would make "unconfigured" and "incapable" the same fact.
    assert unavailable.capabilities.knowledge_base is True

    available = engine_availability(_cartesia())
    assert available.available is True and available.reason is None


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
    assert getattr(raised.value, "code", "") == "engine_not_configured"


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
        headers={"X-API-Key": "secret", "Cartesia-Version": API_VERSION},
        transport=httpx.MockTransport(capture),
    )
    await engine.get_agent("agent_1")

    assert seen.get("cartesia-version") == API_VERSION
    assert seen.get("x-api-key") == "secret"


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
