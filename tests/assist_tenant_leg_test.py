"""The assist ladder's TENANT rung, and the two audiences its refusals are written for.

WHAT THIS FILE IS ABOUT, in the words of the defect it closes. A client on
`gemini-2.5-flash-lite` — chosen on their own settings screen, running their phone agents
at that moment — opened the in-app assistant and was told *"No AI provider is configured on
this deployment. Install an Azure OpenAI resource (AZURE_OPENAI_RESOURCE + …) or a Sarvam
API key (DEV-SETUP §4)."* Two defects: it was written for an operator, and it was FALSE
from where the client was sitting. `assist_capability()` was a hard-coded Azure → Sarvam →
refuse ladder that never consulted the tenant's model, so a PLATFORM fact was reported as a
fact about the client's ACCOUNT.

Every state below is driven WITHOUT A DATABASE, which is the property the ladder was
rewritten to preserve: the tenant's half arrives as a `TenantModelLeg` value, so the
selector stays a pure function of its arguments (D-477).

⚠ **NO ASSERTION HERE STATES WHAT ANY VENDOR'S TERMS SAY.** What is tested is the
MECHANISM — that an unattested provider is barred, that attesting changes the reported
ground, and that neither ever defaults to permitted. Whether Google's terms permit anything
is an operator attestation and an OPERATIONS §2 gate 41 question, not an assertion a test
in this container could honestly make.
"""

from __future__ import annotations

from typing import Any

import pytest
from apps.api.agents import llm_models
from apps.api.agents.llm_models import (
    CLIENT_DASHBOARD_UNAVAILABLE_REASON,
    DASHBOARD_ADDRESSABLE_PROVIDERS,
    DASHBOARD_NEEDS_DATA_USE_ATTESTATION,
    DASHBOARD_TERMS_UNREAD,
    NO_DASHBOARD_LEG_REASON,
    NO_DATA_USE_ATTESTATION_REASON,
    UNREAD_DASHBOARD_TERMS_REASON,
    dashboard_leg_providers,
    dashboard_leg_reason,
    install_dashboard_data_use_reader,
    tenant_dashboard_leg,
)
from apps.api.core.settings import get_settings
from apps.workers.extraction import (
    AZURE_PROVIDER,
    GOOGLE_PROVIDER,
    NO_CREDENTIAL_REASON,
    PROVIDER_UNAVAILABLE_REASON,
    QUOTA_EXHAUSTED_REASON,
    SARVAM_PROVIDER,
    TENANT_PROVIDER_UNSUPPORTED_REASON,
    AssistCapability,
    TenantModelLeg,
    assist_capability,
    assist_unavailable,
)
from calevate_shared.engine import LlmProvider

pytestmark = pytest.mark.anyio

RESOURCE = "calevate-test"


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A deployment with an Azure leg and no Sarvam key — the ladder's ordinary shape."""
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", RESOURCE, raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "gpt-4o-mini-dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    return settings


@pytest.fixture
def unconfigured(monkeypatch: pytest.MonkeyPatch) -> Any:
    """No Azure leg and no Sarvam key: the rung-4 refusal."""
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", None, raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", None, raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", None, raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    return settings


@pytest.fixture(autouse=True)
def _no_leaked_attestation() -> Any:
    """Nothing attested unless a case says so, and nothing leaks to the next case.

    The default matters as much as the reset: an empty reader is "NOBODY HAS ATTESTED",
    which is the honest cold-start state and the one the gate must report as an absent
    attestation rather than as a refusal somebody made.
    """
    install_dashboard_data_use_reader(None)
    yield
    install_dashboard_data_use_reader(None)


AZURE_LEG = TenantModelLeg(
    model="gpt-4o-mini", provider="azure_openai", serves_dashboard=True, blocked_reason=None
)
BLOCKED_LEG = TenantModelLeg(
    model="gemini-2.5-flash-lite",
    provider="google",
    serves_dashboard=False,
    blocked_reason=NO_DATA_USE_ATTESTATION_REASON,
)
#: A Gemini account whose leg an operator HAS attested, so it serves the dashboard (D-478).
#: Rung 1 runs it on the account's own model when the key is installed here.
GOOGLE_SERVING_LEG = TenantModelLeg(
    model="gemini-2.5-flash", provider="google", serves_dashboard=True, blocked_reason=None
)


# --- 1. dashboard eligibility is NOT in-call selectability ---------------------------


def test_every_declared_leg_is_classified_and_none_falls_through_to_permitted() -> None:
    """The classification is exhaustive BY CONSTRUCTION, asserted rather than believed.

    A fourth leg added to `LlmProvider` and to neither policy set would fall through to the
    addressability check — and if somebody also built its chat dialect, it would become
    dashboard-eligible with nobody having decided that. This is the test that turns that
    into a failure instead of a silent permission.
    """
    for provider in ("azure_openai", "openai", "google"):
        classified = (
            provider in DASHBOARD_TERMS_UNREAD
            or provider in DASHBOARD_NEEDS_DATA_USE_ATTESTATION
            or provider in DASHBOARD_ADDRESSABLE_PROVIDERS
        )
        assert classified, f"{provider} is in no dashboard policy set"


def test_a_model_selectable_for_the_phone_is_not_thereby_allowed_on_the_dashboard() -> None:
    """THE COMPLIANCE CORE. `gemini-2.5-flash-lite` is offerable for the IN-CALL leg — a
    client can and did pick it — and that says nothing about the dashboard leg, which is
    governed differently. A ladder that read `selectable` would have conflated them."""
    leg = tenant_dashboard_leg(model="gemini-2.5-flash-lite")

    assert leg.provider == "google"
    assert leg.serves_dashboard is False
    assert leg.blocked_reason == NO_DATA_USE_ATTESTATION_REASON


def test_the_unattested_default_is_barred_and_never_permitted() -> None:
    """It must never default to true. With no reader installed nothing is attested, and the
    only leg eligible is the one this repository can both address and has not gated."""
    assert dashboard_leg_providers() == frozenset({"azure_openai"})


def test_attesting_the_addressable_gemini_leg_makes_it_eligible(configured: Any) -> None:
    """**BOTH HALVES ARE THE POINT, AND D-478 FLIPPED THE SECOND.** Attesting Google's
    data-use position clears the COMPLIANCE ground — which is what makes the attestation a
    field something reads rather than a column nothing consults. Until D-478 that STILL left
    the leg ineligible, because no dashboard chat request could be built for it; now
    `google` is in `DASHBOARD_ADDRESSABLE_PROVIDERS` (the copilot builds the Gemini
    OpenAI-compat leg), so clearing the compliance ground clears the LAST ground and the leg
    becomes eligible. The attestation form is now a job that can actually finish."""
    assert dashboard_leg_reason("google") == NO_DATA_USE_ATTESTATION_REASON
    assert "google" not in dashboard_leg_providers()

    install_dashboard_data_use_reader(lambda: frozenset({"google"}))

    assert dashboard_leg_reason("google") is None
    assert "google" in dashboard_leg_providers()


def test_a_provider_attested_but_not_addressable_still_reports_the_unbuilt_leg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE DEFENSIVE GROUND, KEPT ALIVE PAST D-478. `NO_DASHBOARD_LEG_REASON` fires when a
    provider clears every COMPLIANCE ground but the repository can build no chat request for
    it — the state `google` was in before D-478 and the state a fourth, un-dialected provider
    would arrive in. It is unreachable for the three legs today (all three are either unread,
    or addressable once attested), so it is exercised by removing the addressable dialect out
    from under an attested `google`: reporting only the compliance clearance would then invite
    an operator to a job that cannot finish."""
    monkeypatch.setattr(llm_models, "DASHBOARD_ADDRESSABLE_PROVIDERS", frozenset({"azure_openai"}))
    install_dashboard_data_use_reader(lambda: frozenset({"google"}))

    assert dashboard_leg_reason("google") == NO_DASHBOARD_LEG_REASON
    assert "google" not in dashboard_leg_providers()


def test_openai_is_fail_closed_on_an_unread_position_rather_than_attestable() -> None:
    """An unread vendor position is not a permission, and an attestation cannot stand in for
    a reading — so attesting `openai` does not move it. Moving it is a reviewed commit that
    cites what somebody read."""
    install_dashboard_data_use_reader(lambda: frozenset({"openai", "google"}))

    assert dashboard_leg_reason("openai") == UNREAD_DASHBOARD_TERMS_REASON


def test_the_client_never_reads_the_operator_ground() -> None:
    """Not one of the three grounds is about the CLIENT's configuration — their model works
    and their agents run on it — so the client sentence says so and asks nothing of them."""
    for provider in ("google", "openai"):
        client = dashboard_leg_reason(provider, audience="client")
        assert client == CLIENT_DASHBOARD_UNAVAILABLE_REASON
        assert "ops console" not in (client or "")
        assert "chat.ChatDialect" not in (client or "")


def test_eligibility_is_one_fact_so_none_ness_is_audience_independent() -> None:
    """`unofferable_reason`'s rule, inherited: only the SENTENCE differs by audience. If the
    two audiences could disagree about None-ness, a screen could show "available" beside a
    reason why not."""
    for provider in ("azure_openai", "google", "openai"):
        operator = dashboard_leg_reason(provider, audience="operator")
        client = dashboard_leg_reason(provider, audience="client")
        assert (operator is None) is (client is None)


def test_an_unknown_identifier_is_refused_rather_than_reported_ineligible() -> None:
    """A model with no declared leg has no provider whose dashboard position could be asked
    about, so "not eligible" would imply the question made sense. Same refusal `bind_model`
    makes."""
    with pytest.raises(Exception):  # noqa: B017 - `leg_for_model`'s own refusal type
        tenant_dashboard_leg(model="not-a-model")


# --- 2. the ladder, rung by rung ------------------------------------------------------


def test_the_accounts_own_provider_serves_and_discloses_nothing(configured: Any) -> None:
    """RUNG 1. Nothing was substituted, so there is nothing to disclose — the same rule the
    old happy path had, now stated over the ACCOUNT's provider rather than over Azure."""
    capability = assist_capability(tenant_leg=AZURE_LEG)

    assert capability.available is True
    assert capability.provider == AZURE_PROVIDER
    assert capability.fallback_reason is None
    assert capability.disclosure is None


def test_the_account_runs_on_its_own_gemini_when_it_serves_and_the_key_is_installed(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RUNG 1, THE GEMINI ARM (D-478). The account runs Gemini, the leg is attested, and the
    key is installed — so the assistant runs on the account's OWN model, not the platform's
    Azure one, and nothing is disclosed. Checked BEFORE Azure precisely so a Gemini account
    with Azure also configured is not silently moved onto Azure."""
    monkeypatch.setattr(get_settings(), "gemini_api_key", "gk-test", raising=False)

    capability = assist_capability(tenant_leg=GOOGLE_SERVING_LEG)

    assert capability.available is True
    assert capability.provider == GOOGLE_PROVIDER
    assert capability.fallback_reason is None
    assert capability.disclosure is None


def test_a_serving_gemini_account_with_no_key_here_falls_to_the_platform(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The half-configured edge: the leg is attested but this deployment holds no Gemini key,
    so rung 1 cannot fire and Azure answers. `serves_dashboard` is True, so this is not
    flagged as a substitution — an operator misconfiguration (an attestation without the key
    it attests) that the realistic deployment does not hit, and OPERATIONS §2 gate 41's
    credentialled check owns."""
    monkeypatch.setattr(get_settings(), "gemini_api_key", None, raising=False)

    capability = assist_capability(tenant_leg=GOOGLE_SERVING_LEG)

    assert capability.available is True
    assert capability.provider == AZURE_PROVIDER


def test_a_blocked_tenant_provider_is_served_by_the_platform_and_told_about_it(
    configured: Any,
) -> None:
    """RUNG 2, AND THE WHOLE REPORTED DEFECT. The client keeps a working assistant; the
    answer says whose it is (D-127 G-7); and the reason is NOT `no_credential`, because the
    account has a provider and it is on the phone right now."""
    capability = assist_capability(tenant_leg=BLOCKED_LEG)

    assert capability.available is True
    assert capability.provider == AZURE_PROVIDER
    assert capability.fallback_reason == TENANT_PROVIDER_UNSUPPORTED_REASON
    assert capability.disclosure is not None
    assert "Calevate's own assistant model" in capability.disclosure
    # The substitution must not claim SARVAM wrote an answer Azure wrote.
    assert "Sarvam" not in capability.disclosure
    # The operator ground travels for the log line and stops there.
    assert capability.operator_detail == NO_DATA_USE_ATTESTATION_REASON


def test_with_no_platform_leg_a_blocked_tenant_falls_to_sarvam_and_is_told(
    monkeypatch: pytest.MonkeyPatch, unconfigured: Any
) -> None:
    """RUNG 3 with the tenant ground carried through. The earlier ground is what the
    disclosure names — not "the assistant model did not answer", which never happened."""
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    capability = assist_capability(tenant_leg=BLOCKED_LEG)

    assert capability.provider == SARVAM_PROVIDER
    assert capability.fallback_reason == TENANT_PROVIDER_UNSUPPORTED_REASON
    assert capability.disclosure is not None
    assert "Sarvam" in capability.disclosure


def test_the_refusal_with_no_leg_at_all_names_the_platform_gap_not_the_tenants_provider(
    unconfigured: Any,
) -> None:
    """RUNG 4, AND THE FALSEHOOD THAT REPLACED THE ONE IT FIXED.

    ⚠ **THIS TEST USED TO ASSERT THE OPPOSITE**, on the reasoning that "you have no AI" and
    "your AI cannot do this one thing" are different claims and the first was a lie told to a
    paying client. That reasoning is still right and is still pinned — one test down, on the
    rung where a substitute actually answers. It does not survive to a deployment holding NO
    assistant leg at all, and the argument is causal rather than editorial: with neither an
    Azure leg nor a Sarvam key, the tenant's provider is not a CAUSE of this refusal in any
    counterfactual sense. An account on the best-supported provider in the catalogue is
    refused identically. Naming their model therefore points them at a choice that would
    change nothing — "your model cannot do this" invites them to switch models, and switching
    models does not produce an assistant — while the operative fact, the one somebody can act
    on, is that this platform has configured no assistant. That is the same shape of error
    `NO_CREDENTIAL_REASON`'s own note exists to prevent, pointing the other way: a PLATFORM
    fact reported as a fact about the client's account.

    WHAT PROTECTS THE ORIGINAL FINDING NOW, so it is not traded away: the client's
    `no_credential` sentence says in its own words that their phone agents are unaffected and
    running normally — the reassurance that did not exist when that defect was found — and
    the tenant ground survives wherever it is causal, which is asserted directly below.
    """
    blocked = assist_capability(tenant_leg=BLOCKED_LEG)
    none_at_all = assist_capability(tenant_leg=None)

    assert blocked.reason == NO_CREDENTIAL_REASON
    assert none_at_all.reason == NO_CREDENTIAL_REASON

    problem = assist_unavailable(blocked)
    assert problem.code == f"assist_{NO_CREDENTIAL_REASON}"
    # It must not claim the client has no AI, which is the D-127 falsehood, and it must not
    # blame a model choice that is not the cause.
    assert "phone agents are not affected" in (problem.remediation or "")
    assert "you chose" not in (problem.remediation or "")
    # THE OPERATOR STILL SEES BOTH FACTS. The tenant leg's own ground rides along in
    # `operator_detail`, so nobody debugging loses the second half of the picture.
    assert blocked.operator_detail == NO_DATA_USE_ATTESTATION_REASON


def test_the_tenant_ground_survives_wherever_it_is_the_actual_cause(
    monkeypatch: pytest.MonkeyPatch, unconfigured: Any
) -> None:
    """The other side of the precedence rule, and the reason it is a rule rather than a
    deletion.

    With a Sarvam key installed, something DOES answer — and the reason it is Sarvam rather
    than the account's own model IS the account's provider. The counterfactual holds: an
    account on a supported provider would have been answered by their own model. So the
    specific sentence is the true one there, and the client is owed it under G-7.
    """
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    served = assist_capability(tenant_leg=BLOCKED_LEG)

    assert served.available is True
    assert served.fallback_reason == TENANT_PROVIDER_UNSUPPORTED_REASON
    assert "the AI model you chose" in (served.disclosure or "")
    # ONE LADDER, TWO GROUNDS, NEITHER HIDING THE OTHER: on the same deployment an account
    # whose provider WOULD have served this leg is told the platform's gap instead, because
    # for them that is the whole cause.
    assert assist_capability(tenant_leg=AZURE_LEG).fallback_reason == NO_CREDENTIAL_REASON


def test_omitting_the_tenant_leg_behaves_exactly_as_the_ladder_did_before(
    configured: Any,
) -> None:
    """The optional argument's contract. `None` is "no account in hand" — `scripts/eval.py`
    and the conformance fixtures — and on it rung 1 collapses into rung 2 with nothing to
    disclose, so no caller is silently changed by omitting it."""
    assert assist_capability() == assist_capability(tenant_leg=None)
    assert assist_capability().fallback_reason is None


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"quota_exhausted": True}, QUOTA_EXHAUSTED_REASON),
        ({"provider_unavailable": True}, PROVIDER_UNAVAILABLE_REASON),
    ],
)
def test_the_quota_and_outage_rungs_still_outrank_the_tenant_rung(
    monkeypatch: pytest.MonkeyPatch,
    configured: Any,
    kwargs: dict[str, bool],
    expected: str,
) -> None:
    """Order preserved. A client at their ceiling needs the wallet modal (G-5), not a
    sentence about which provider may serve the dashboard — that is true of them either
    way and is not what stopped this request."""
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    capability = assist_capability(tenant_leg=BLOCKED_LEG, **kwargs)

    assert capability.provider == SARVAM_PROVIDER
    assert capability.fallback_reason == expected


# --- 3. the refusal a client actually sees --------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        NO_CREDENTIAL_REASON,
        QUOTA_EXHAUSTED_REASON,
        PROVIDER_UNAVAILABLE_REASON,
        TENANT_PROVIDER_UNSUPPORTED_REASON,
    ],
)
def test_no_client_sentence_names_a_variable_a_setting_or_a_document(reason: str) -> None:
    """THE FIRST DEFECT, closed for EVERY reason rather than for the one that was reported.
    A client console has no environment, no `DEV-SETUP` and no deployment; naming any of
    them is instructing somebody to do something they have no power to do."""
    problem = assist_unavailable(AssistCapability(available=False, reason=reason))
    text = f"{problem.title} {problem.detail} {problem.remediation}"

    for forbidden in ("AZURE_", "SARVAM_API_KEY", "DEV-SETUP", "deployment", "credential"):
        assert forbidden not in text, f"{reason}'s client text names {forbidden!r}: {text}"


@pytest.mark.parametrize("reason", [NO_CREDENTIAL_REASON, TENANT_PROVIDER_UNSUPPORTED_REASON])
def test_where_the_honest_answer_is_ask_us_it_says_exactly_that(reason: str) -> None:
    """A remediation a person cannot act on is not a remediation. For the two grounds only
    Calevate can fix, the action is "ask your Calevate team" and the sentence says there is
    nothing on their side to change — which is both true and the thing they most need to
    know before they go looking."""
    problem = assist_unavailable(AssistCapability(available=False, reason=reason))

    assert "Calevate team" in (problem.remediation or "")
    assert "nothing to change on your side" in (problem.remediation or "")


def test_the_operator_half_still_exists_and_still_names_the_variables() -> None:
    """RELOCATED, NOT DELETED. A refusal that became friendly and untraceable would be a
    worse defect than the one being fixed."""
    problem = assist_unavailable(
        AssistCapability(available=False, reason=NO_CREDENTIAL_REASON), audience="operator"
    )

    assert "AZURE_OPENAI_RESOURCE" in (problem.remediation or "")
    assert "DEV-SETUP" in (problem.remediation or "")


def test_every_refusal_logs_the_operator_remediation_and_no_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THE OTHER HALF OF THE RELOCATION. Whichever audience is answered, the operator's
    sentence and the ground behind it reach a log line — so the assistant being off is
    discoverable by somebody who can act on it. Ids and authored codes only (hard rule 6):
    nothing here is a phone number, a transcript or an extraction payload."""
    with caplog.at_level("WARNING"):
        assist_unavailable(
            AssistCapability(
                available=False,
                reason=TENANT_PROVIDER_UNSUPPORTED_REASON,
                operator_detail=NO_DATA_USE_ATTESTATION_REASON,
            )
        )

    record = next(r for r in caplog.records if r.getMessage() == "assist_unavailable")
    assert record.__dict__["reason"] == TENANT_PROVIDER_UNSUPPORTED_REASON
    assert record.__dict__["operator_detail"] == NO_DATA_USE_ATTESTATION_REASON
    assert "AZURE_OPENAI_RESOURCE" in record.__dict__["operator_remediation"]


def test_every_reason_the_ladder_can_produce_has_both_audiences_written(
    configured: Any,
) -> None:
    """A reason with no sentence for one audience would be a `KeyError` on a refusal path —
    a 500 where an authored message belongs. Enumerated from the ladder's own vocabulary
    rather than from a list typed beside it."""
    for reason in (
        NO_CREDENTIAL_REASON,
        QUOTA_EXHAUSTED_REASON,
        PROVIDER_UNAVAILABLE_REASON,
        TENANT_PROVIDER_UNSUPPORTED_REASON,
    ):
        for audience in ("client", "operator"):
            problem = assist_unavailable(
                AssistCapability(available=False, reason=reason),
                audience=audience,  # type: ignore[arg-type]
            )
            assert problem.remediation


def test_every_substitution_the_ladder_can_produce_carries_a_sentence(
    monkeypatch: pytest.MonkeyPatch, configured: Any
) -> None:
    """G-7 has no exceptions, and a `fallback_reason` with no disclosure is a silent
    substitution wearing a flag. Driven through the LADDER rather than over the disclosure
    table, so a rung that starts producing a new pair fails here."""
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    produced = [
        assist_capability(tenant_leg=BLOCKED_LEG),
        assist_capability(tenant_leg=BLOCKED_LEG, provider_unavailable=True),
        assist_capability(tenant_leg=AZURE_LEG, quota_exhausted=True),
        assist_capability(tenant_leg=AZURE_LEG, provider_unavailable=True),
    ]
    for capability in produced:
        if capability.fallback_reason is not None:
            assert capability.disclosure, (
                f"{capability.provider}/{capability.fallback_reason} substitutes silently"
            )


def test_the_seam_is_the_one_the_ops_console_installs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`llm_models` holds no attestation and reads no database — the ops console reaches it
    through the installed reader, exactly as it does for prices and credentials. Asserted so
    that a second mechanism cannot appear beside it unnoticed."""
    seen: list[str] = []

    def _reader() -> frozenset[LlmProvider]:
        seen.append("read")
        return frozenset()

    install_dashboard_data_use_reader(_reader)
    llm_models.dashboard_data_use_attested()

    assert seen == ["read"]
