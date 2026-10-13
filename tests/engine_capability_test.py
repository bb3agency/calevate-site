"""The capability seam, the receiver's webhook table, and agent hosting.

Three questions, one file, and none of them is answered by the conformance suite:

1. **Does the seam refuse the way the other three seams refuse?** `payment_capability`,
   `lead_retrieval_capability` and `get_sheets_transport` all settled one shape — one
   selector, authored reason codes, never vendor prose — and a fourth seam that drifted
   from it would be the "two ways to do one thing" this repo treats as a defect even when
   both work.

2. **Do the adapters agree with the table the RECEIVER reads?** The voice-runtime cannot
   import an adapter (hard rule 3), so it authenticates from `WEBHOOK_AUTH_BY_ENGINE`.
   The conformance suite checks that per adapter; this checks the table has no entry
   pointing at an engine that does not exist, which is the other direction.

3. **Hard rule 5 has two homes.** An engine that hosts our agent record holds the
   truthful-answer directive there; one that does not must carry it on every dial.
"""

from __future__ import annotations

import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine import (
    engine_capabilities,
    engine_lacks,
    require_capability,
)
from apps.api.engine.capabilities import (
    ENGINE_CAPABILITY_ABSENT,
    ENGINE_COMPLIANCE_FLOOR_ABSENT,
    NO_CREDENTIALS_REASON,
    EngineCapabilityAbsentError,
)
from apps.api.engine.fake import (
    DEFAULT_FAKE_CAPABILITIES,
    DICTATED_SPEECH_CAPABILITIES,
    EXTERNAL_DEPLOYMENT_CAPABILITIES,
    FakeEngine,
)
from apps.api.engine.thinnest import ThinnestEngine
from calevate_shared.engine import (
    TRUTHFUL_ANSWER_DIRECTIVE,
    TRUTHFUL_ANSWER_MARKER,
    WEBHOOK_AUTH_BY_ENGINE,
    AgentConfig,
    CallContext,
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
    error = engine_lacks("tts", engine="thinnest")

    assert isinstance(error, EngineCapabilityAbsentError)
    assert error.code == ENGINE_CAPABILITY_ABSENT
    assert error.capability == "tts"
    problem = error.as_problem()
    assert problem["type"].rsplit("/", 1)[-1] == ENGINE_CAPABILITY_ABSENT
    assert problem["remediation"], "a refusal with no remediation is a dead end"
    assert "thinnest" not in str(problem).lower(), "the vendor name must not reach a client"


async def test_an_engine_without_credentials_refuses_through_the_one_shared_builder(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The deployment-level answer, derived from the adapter rather than from settings.

    This is the state of a deployment that selected the engine and installed no key.

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

    unconfigured = ThinnestEngine(api_key=None)
    assert unconfigured.holds_credentials() is False
    assert unconfigured.credential_env_keys, "readiness needs a key to name, not a verdict"

    raised: ProblemError | None = None
    with caplog.at_level("WARNING"):
        try:
            # Reading a call reaches the vendor boundary, which is where it must refuse.
            await unconfigured.get_execution("anything")
        except ProblemError as exc:
            raised = exc
    assert raised is not None, "an adapter with no credential must refuse at the boundary"
    problem = raised.as_problem()
    assert problem["type"].rsplit("/", 1)[-1] == "engine_not_configured"
    assert "thinnest" not in str(problem).lower(), (
        "the vendor name reached a client — it belongs in the operator log, which is "
        "exactly what `engine_not_configured` takes its `reason` for"
    )
    # And it DID reach the operator log, naming which engine. The refusal a client sees
    # is deliberately identical across engines; the line an operator acts on is not.
    reasons = [getattr(r, "reason", None) for r in caplog.records]
    assert f"{NO_CREDENTIALS_REASON}:thinnest" in reasons, reasons

    # The capability answer survives the credential answer, and that is deliberate: an
    # engine with a knowledge base and no API key still HAS a knowledge base. Collapsing
    # the two would make "unconfigured" and "incapable" the same fact.
    assert unconfigured.capabilities.knowledge_base is True


def test_the_capability_selector_answers_about_the_adapter_it_is_given() -> None:
    """One selector, and it never re-reads settings behind the caller's back.

    The two callers that already hold an adapter (the publish path, the KB publish path)
    pass it, so the capability they check belongs to the adapter they are about to call.
    A selector that fetched its own would eventually check a different instance.
    """
    assert engine_capabilities(ThinnestEngine(api_key=None)) == ThinnestEngine.capabilities
    assert engine_capabilities(FakeEngine()).tts == "ours"
    assert (
        engine_capabilities(FakeEngine(capabilities=DICTATED_SPEECH_CAPABILITIES)).tts == "engine"
    )


# --- 2. the receiver's table matches the adapters ------------------------------


def test_every_engine_in_the_webhook_auth_table_is_an_engine_we_ship() -> None:
    """The other direction from the conformance clause.

    That clause asks each ADAPTER whether the table agrees with it. This asks the TABLE
    whether it describes anything real: a stale entry — an engine renamed, an adapter
    deleted — would leave the receiver authenticating deliveries for a name nothing can
    produce, and no adapter-side test can see it because no adapter has that name.
    """
    shipped = {
        "fake",
        "fake-restricted",
        "fake-deployed",
        # D-678: the ThinnestAI control-plane adapter, which signs its deliveries.
        "thinnest",
    }
    assert set(WEBHOOK_AUTH_BY_ENGINE) == shipped
    assert WEBHOOK_AUTH_BY_ENGINE["thinnest"] == "hmac"


# --- 3. agent hosting: the two homes hard rule 5 has (D-280..D-282) -------------


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
    that started failing on a control-plane engine because an unrelated engine cannot hold
    a prompt is the regression this asserts against.
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
    for caps in (EXTERNAL_DEPLOYMENT_CAPABILITIES,):
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
