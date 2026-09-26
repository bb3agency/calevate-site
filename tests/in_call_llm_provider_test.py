"""The in-call LLM leg can name where it runs, and it cannot name anywhere but our resource.

D-400 moved the canonical in-call LLM off Sarvam 105B (free per token, sovereign by
vendor) onto a PAID account; D-410 re-aimed that account at Azure OpenAI, and D-449 moved
the region out of India to `eastus2` (withdrawing the residency claim rather than
improving it).
Either way it is a residency change wearing a pricing decision: D-36's guarantee was an
argument about a VENDOR, and the replacement — D-127's, extended to the in-call leg — is
an argument about an ENDPOINT. An endpoint is a string, and this file is one of the two
things standing between that string and a DPDP-relevant transfer.

⚠ **WHAT THIS FILE CAN NO LONGER PROVE, SAID FIRST BECAUSE IT IS A REAL WEAKENING.**
Vertex put `asia-south1` in the host AND in the `locations/` path segment, so the tests
below used to read the region off the URL twice and refuse the nine characters that
changed it. Azure's shipped endpoint shape names no region at all — `<resource>.openai
.azure.com` — because the region is a property of the RESOURCE, fixed by whoever created
it in the portal. So what is asserted here is one link of a three-link chain:
`AZURE_LOCATION` says which region the resource must be in, `Settings.azure_openai_resource`
points at a resource an operator asserts is there, and a HUMAN confirms it once in the
Azure portal (OPERATIONS §2). No test in this repository can close the last link, and one
claiming to would be worse than the gap. `calevate_shared.engine.AZURE_LOCATION` carries
the same warning in the other place a reader looks.

WHAT IS STILL PROVED, WHICH IS NOT NOTHING: no endpoint reaches an engine except one
`azure_openai_base_url()` could have emitted; that builder refuses anything but a single
DNS label, so the HOST is Azure's rather than a look-alike whose tail merely reads like
it; the leg's model identifier and its endpoint cannot be configured apart; and every arm
of the one switch that decides whether an agent's LLM is ours has a test that fails when
it is deleted.

THE OTHER THING IS `scripts/check_model_residency.py`, AND THE SPLIT IS THE POINT. That
guard reads the AST and proves things about the model URLs *written in this tree*. It
says in its own docstring what it cannot see: a URL assembled at runtime, read from a
store, or handed to a vendor. `ModelConfig`'s validator covers exactly that blind spot —
the VALUE rather than the literal — and this file is what proves the validator is
connected to anything. A tripwire with no test that steps on it is a tripwire nobody has
evidence is wired up (`model_residency_guard_test` makes the same argument about its
subject).

WHAT THIS FILE DELIBERATELY DOES NOT ASSERT: **that an Azure-backed agent placed a real
phone call.** No real call has been placed on this product (BLOCKER-1). What IS asserted is
that the configuration is EXPRESSIBLE and that no other endpoint can be expressed at all.
How an engine renders the leg onto its own wire is that adapter's test.
"""

from __future__ import annotations

import pytest
from apps.api.agents.voices import CARTESIA_TTS_MODEL
from calevate_shared.engine import (
    AZURE_LOCATION,
    AZURE_OPENAI_DEFAULT_MODEL,
    AZURE_OPENAI_MODELS,
    ModelConfig,
    azure_openai_base_url,
    openai_base_url,
)
from pydantic import ValidationError

RESOURCE = "calevate-voice"
#: The DEPLOYMENT ID, which is what travels in the vendor's one model slot. Deliberately
#: unlike any model name in `AZURE_OPENAI_MODELS`, so a test that confuses the two fails
#: instead of coincidentally passing — the whole point of the distinction is that on every
#: other OpenAI-compatible provider these two strings are one string.
DEPLOYMENT = "calevate-voice-inbound"
ENDPOINT = azure_openai_base_url(RESOURCE)

#: The Azure model that is NOT the platform default — the one `_configure` leaves without a
#: deployment, so it stands for "permitted, but this platform cannot address it".
ALTERNATE_AZURE_MODEL = next(iter(AZURE_OPENAI_MODELS - {AZURE_OPENAI_DEFAULT_MODEL}))


def _azure_models() -> ModelConfig:
    return ModelConfig(
        stt_provider="sarvam",
        stt_model="saaras:v3",
        llm_model=DEPLOYMENT,
        llm_provider="azure_openai",
        llm_base_url=ENDPOINT,
        tts_provider="cartesia",
        tts_model=CARTESIA_TTS_MODEL,
        tts_voice="anushka",
    )


# --- the endpoint --------------------------------------------------------------------


def test_the_base_url_is_the_v1_surface_and_carries_no_api_version() -> None:
    """The v1 surface is the whole reason this leg is simpler than the Vertex leg it
    replaced: it needs no dated `api-version` and it accepts a key in the authorization
    header, which is what an OpenAI-shaped client sends. The classic surface
    (`/openai/deployments/{id}/chat/completions?api-version=YYYY-MM-DD`) is a second
    thing to keep current forever and an auth header no such client emits."""
    assert f"https://{RESOURCE}.openai.azure.com/openai/v1" == ENDPOINT
    assert "api-version" not in ENDPOINT
    assert "/deployments/" not in ENDPOINT


def test_the_endpoint_names_no_region_and_that_is_recorded_rather_than_hidden() -> None:
    """THE WEAKENING, ASSERTED AS A FACT SO IT CANNOT BE FORGOTTEN.

    Under Vertex this file's first test read `asia-south1` out of the URL twice. Azure
    hides the region inside the resource, so there is nothing to read — and a test that
    quietly stopped looking would leave a reader believing the old proof still holds. So
    the absence is asserted: if a future endpoint shape ever DOES carry the region, this
    fails, and the person who made that possible is exactly the person who should hear
    about it (the regional hostname `<region>.api.cognitive.microsoft.com` is the
    rejected-for-now alternative that would do it — see `AZURE_LOCATION`).
    """
    assert AZURE_LOCATION not in ENDPOINT
    assert AZURE_LOCATION == "eastus2", (
        "one spelling of the region, and since D-449 it is NOT an Indian one — the India "
        "residency claim was withdrawn, not narrowed"
    )


@pytest.mark.parametrize(
    "resource",
    [
        # The attack this guard exists for: Azure puts the caller's value at the FRONT of
        # the authority, so an interpolated `evil.example/x` is a URL whose HOST is the
        # attacker's and whose tail merely reads like Azure.
        "evil.example/x",
        "res.openai.azure.com",
        "res:8443",
        "a",  # one character: not a legal two-plus DNS label
        "-leading",
        "trailing-",
        "",
    ],
)
def test_a_resource_that_is_not_one_dns_label_is_refused_rather_than_interpolated(
    resource: str,
) -> None:
    """A builder that quietly emitted `https://evil.example/x.openai.azure.com/openai/v1`
    would be handing a third party an attacker's host wearing our suffix — and the value
    it is handing over is where a client's caller's words go."""
    with pytest.raises(ValueError):
        azure_openai_base_url(resource)


# --- what the config will and will not accept -----------------------------------------


@pytest.mark.parametrize(
    "base_url",
    [
        # THE CLASSIC AZURE SURFACE, on our own resource. Right host, wrong door: it wants
        # a dated `api-version` and an `api-key:` header, and it is the shape somebody
        # copies out of an Azure quickstart.
        "https://calevate-voice.openai.azure.com/openai/deployments/d/chat/completions",
        # THE REGIONAL HOSTNAME. It would restore the AST proof of residency and is
        # rejected FOR NOW because the v1 surface is documented only on the custom
        # subdomain — so this is a refusal with a reason, not an oversight (`AZURE_LOCATION`).
        "https://southindia.api.cognitive.microsoft.com/openai/v1",
        # A LOOK-ALIKE whose tail reads like Azure and whose host is not.
        "https://evil.example/x.openai.azure.com/openai/v1",
        # OpenAI direct: DISQUALIFIED (their India residency covers storage at rest only;
        # inference still runs in the US, and for a phone call the transcript IS the
        # inference input).
        "https://api.openai.com/v1",
        # The AI Studio Developer API — a global host with no region in it and no field in
        # which to ask for one.
        "https://generativelanguage.googleapis.com/v1beta",
        # THE LEG THIS ONE REPLACED. Vertex Mumbai was correct under D-400 and is not
        # expressible any more, which is what "replaced outright rather than joined" means:
        # a residency posture with two answers is two postures.
        "https://asia-south1-aiplatform.googleapis.com/v1/projects/p/locations/asia-south1/endpoints/openapi",
        # Plain HTTP to the right host: the transcript would cross the network in clear.
        "http://calevate-voice.openai.azure.com/openai/v1",
    ],
)
def test_no_endpoint_but_our_own_can_be_configured(base_url: str) -> None:
    with pytest.raises(ValidationError):
        ModelConfig(llm_provider="azure_openai", llm_base_url=base_url)


def test_an_azure_leg_without_an_endpoint_is_refused() -> None:
    """Naming the provider and omitting the URL would route to the engine's default
    client with a deployment id for a model — a confusing 4xx from a vendor rather than a
    sentence about what is wrong."""
    with pytest.raises(ValidationError):
        ModelConfig(llm_provider="azure_openai", llm_model=DEPLOYMENT)


def test_an_endpoint_without_a_provider_is_refused() -> None:
    """The shape a future caller reaches for when it wants "just point the LLM
    somewhere" — and the one that would send our endpoint to the wrong client."""
    with pytest.raises(ValidationError):
        ModelConfig(llm_base_url=ENDPOINT)


def test_the_pre_d400_config_is_still_valid_and_unchanged() -> None:
    """Every agent row in this repository resolves to this: no provider, no base URL,
    the engine's own default. A residency validator that broke it would be a validator
    that broke every live agent."""
    models = ModelConfig(llm_model="sarvam-105b")
    assert models.llm_provider is None
    assert models.llm_base_url is None


# --- the money the decision costs lives in `tests/llm_cost_model_test.py` --------------
#
# THREE COST TESTS USED TO SIT HERE and were removed rather than kept, which is worth a
# note because "delete a passing test" is normally the wrong move. They were written in
# parallel with `tests/llm_cost_model_test.py` during the D-410 migration and were
# genuine duplicates of three tests there — the USD→INR derivation, the unpriced-model
# refusal, and the rising per-minute curve — not weaker versions of them.
#
# One way per problem, and the tiebreak is SUBJECT rather than seniority: this file's
# subject is the provider contract and the one resolver switch (which endpoint, which
# spelling, which arms fall back). What a token costs in rupees is a different subject
# with its own file, and that file also covers what this one never did — that no cost
# function may grow a `model=` default, and that a metered row cannot disagree with its
# own model. Two files asserting one property is how they drift into disagreeing, and
# the one that goes stale is always the one whose subject it was not.


# --- the one switch, and every arm of it ----------------------------------------------
#
# `in_call_llm` is the single decision point for the whole leg, and it has THREE necessary
# conditions — resource, key, deployment. Each is exercised ALONE-MISSING, because a
# condition whose failing arm nobody has run is a condition nobody knows the shape of; and
# each names a different way the leg breaks at a different, worse moment.
#
# THE ARMS ARE ASSERTED ON THE PASSTHROUGH, not on "no exception". A half-configured
# deployment must fall back to the ENGINE'S OWN DEFAULT — the same body every agent row in
# this repository has always produced — and never to a half-built Azure endpoint, which is
# the one outcome that looks configured and cannot authenticate.

_AZURE_FIELDS = ("azure_openai_resource", "azure_openai_api_key", "azure_openai_deployment")

API_KEY = "azure-static-key-under-test"


def _configure(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> None:
    """Set the three credential fields, with `None` for the one under test."""
    from apps.api.core.settings import get_settings

    values: dict[str, str | None] = {
        "azure_openai_resource": RESOURCE,
        "azure_openai_api_key": API_KEY,
        "azure_openai_deployment": DEPLOYMENT,
    }
    values.update(overrides)
    settings = get_settings()
    for field in _AZURE_FIELDS:
        monkeypatch.setattr(settings, field, values[field], raising=False)


@pytest.mark.parametrize(
    ("missing", "why"),
    [
        (
            "azure_openai_resource",
            "the resource is the first label of the hostname, so without it there is no "
            "endpoint to name at all",
        ),
        (
            "azure_openai_api_key",
            "THE CONDITION A REVIEWER WOULD DROP: the resource and the deployment alone "
            "BUILD a URL, so a leg configured from those two looks complete and points "
            "every agent at an endpoint nothing can authenticate against — a 401 from "
            "Azure mid-sentence on a client's live phone call, not a publish-time error",
        ),
        (
            "azure_openai_deployment",
            "Azure serves a model under a deployment the operator named and the v1 "
            "surface addresses THAT; a resource with no deployment addresses a host and "
            "no model",
        ),
    ],
)
def test_a_half_configured_deployment_stays_on_the_engines_own_default(
    monkeypatch: pytest.MonkeyPatch, missing: str, why: str
) -> None:
    """`None` IS THE ARGUMENT NOW, AND THE CHANGE IS THE POINT RATHER THAN A FIXTURE TWEAK.

    This used to pass `"sarvam-105b"` and get it straight back, because the passthrough arm
    forwarded ANY string to the engine unexamined. That is no longer legal and must not be:
    `leg_for_model` refuses an identifier the catalogue does not know rather than guessing a
    leg for it, and an unpriced string reaching a vendor is exactly the spend the catalogue
    exists to prevent. `None` is what this state actually looks like in production — nobody
    chose, so the engine uses its own default — and the refusal for a stranger is asserted
    directly below.
    """
    from apps.api.agents import service

    _configure(monkeypatch, **{missing: None})
    assert service.in_call_llm(None) == {"llm_model": None}, why


def test_an_identifier_the_catalogue_does_not_know_is_refused_on_every_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The passthrough arm is NOT a hole for an unknown model, on any configuration.

    A string with no `LlmModelSpec` has no leg, no price and no traps, so there is nothing
    to decide an endpoint from and nothing to meter a minute against. It raises rather than
    defaulting to the incumbent leg — defaulting is how a Gemini identifier ends up in an
    Azure deployment field as a 404 mid-call.
    """
    from apps.api.agents import service

    for configuration in ({}, {"azure_openai_resource": None, "azure_openai_api_key": None}):
        _configure(monkeypatch, **configuration)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="not a model this repository knows"):
            service.in_call_llm("sarvam-105b")


def test_a_deployment_with_no_azure_credential_at_all_stays_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local, CI and any staging without an Azure resource are exactly this, and they
    must keep publishing. It is also the OFF position of the switch: D-410 deleted the
    founder's constant along with the Vertex leg, so what turns this leg off is having no
    credential rather than a boolean somebody has to remember to flip."""
    from apps.api.agents import service
    from apps.api.core.errors import ProblemError

    _configure(
        monkeypatch,
        azure_openai_resource=None,
        azure_openai_api_key=None,
        azure_openai_deployment=None,
    )
    assert service.in_call_llm(None) == {"llm_model": None}
    # ⚠ AN EXPLICIT AZURE CHOICE IS NOW REFUSED HERE, AND THIS ASSERTION USED TO BE ITS
    # OPPOSITE. The passthrough forwarded a CHOSEN model too, on the ground that with no
    # deployment indirection the identifier IS what the engine is sent — which published an
    # agent under a model the client had been quoted and billed for while the engine served
    # it from its own bundled tier (`agents/llm_models.py`'s module docstring carries the
    # vendor page). The passthrough now fires only when NOBODY chose; a choice this platform
    # cannot address is the loud refusal, and `validate_llm_model` refuses the selection one
    # step earlier so this arm is only reachable when config moved under a live choice.
    with pytest.raises(ProblemError) as refused:
        service.in_call_llm(AZURE_OPENAI_DEFAULT_MODEL)
    assert refused.value.code == "llm_model_not_deployed"


def test_a_fully_configured_deployment_moves_the_endpoint_and_the_model_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What lands in `llm_model` is the DEPLOYMENT, never `Settings.azure_openai_model` —
    the trap Azure sets, asserted here at the source as well as on the wire.

    `None` is the argument because it is the state every agent is in until somebody
    chooses: no per-agent and no per-account model, so the leg resolves to the platform's
    own model and therefore to `azure_openai_deployment`, which is the pairing
    `config.py` requires to move together.
    """
    from apps.api.agents import service
    from apps.api.core.settings import get_settings

    _configure(monkeypatch)
    monkeypatch.setattr(
        get_settings(), "azure_openai_model", AZURE_OPENAI_DEFAULT_MODEL, raising=False
    )
    # AND THE PLATFORM'S OWN DEFAULT IS ITS OWN SETTING: `azure_openai_model` says
    # which model the deployment was made from, `platform_llm_model` says what an account
    # that has chosen nothing runs. This case is about the Azure leg, so it puts the platform
    # rung on the Azure model; the shipped default is a Google one.
    monkeypatch.setattr(
        get_settings(), "platform_llm_model", AZURE_OPENAI_DEFAULT_MODEL, raising=False
    )

    leg = service.in_call_llm(None)
    assert leg == {
        "llm_model": DEPLOYMENT,
        "llm_provider": "azure_openai",
        "llm_base_url": ENDPOINT,
        # EMPTY IS A READING: neither allow-listed Azure model is GPT-5-class, so neither
        # carries a request-field trap. The tuple is present rather than absent so the
        # adapter never has to distinguish "no traps" from "nobody resolved them".
        "llm_traps": (),
    }
    assert leg["llm_model"] != AZURE_OPENAI_DEFAULT_MODEL
    # And it must be a config `ModelConfig` will actually accept — the residency
    # validator runs on exactly this dict the moment `_to_config` builds one from it.
    assert ModelConfig(**leg).llm_base_url == ENDPOINT


def test_a_model_this_platform_has_no_deployment_for_is_refused_not_substituted(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THE SUBSTITUTION THAT USED TO HAPPEN HERE, now a refusal (D-454).

    This test used to pass `"sarvam-105b"` and assert the deployment came back anyway —
    the column was IGNORED on an Azure leg, which was correct while nothing could write
    it. `agents.llm_model` and `organizations.default_llm_model` are written by real
    endpoints now and the two allow-listed models differ 2.7x in price, so "ignore what
    was chosen and address the default deployment" became: quote one model, run another,
    bill for the first. There is no safe substitute, so there is none — the leg refuses,
    names the model, and the agent does not publish.

    The stand-in is now a REAL catalogue model with no deployment configured for it, rather
    than a made-up identifier: `leg_for_model` refuses a stranger outright (asserted
    separately), so a stranger could no longer reach this arm at all. The API cannot store an
    undeployed selection either (`ck_agents_llm_model_allowed`, `validate_llm_model`), which
    is why this arm is reached by calling the decision point directly: the state it guards is
    an operator removing a deployment under an account that already chose.
    """
    import logging

    from apps.api.agents import service
    from apps.api.core.errors import ProblemError
    from apps.api.core.logging import JsonFormatter

    _configure(monkeypatch)
    undeployed = ALTERNATE_AZURE_MODEL
    formatter = JsonFormatter()
    with caplog.at_level(logging.ERROR), pytest.raises(ProblemError) as raised:
        service.in_call_llm(undeployed)
    assert raised.value.code == "llm_model_not_deployed"
    assert undeployed in raised.value.detail
    # THE AUDIENCE SPLIT (regression guard). Publish is a client action, so the message a
    # client reaches names only what THEY can do and NOT the operator ground — a client
    # cannot create a deployment, install a key or attest a price. The ground is not lost:
    # it goes to the operator's log line, which is the path an operator does reach.
    assert "deployment" not in raised.value.detail.lower()
    assert "your Calevate team" in (raised.value.remediation or "")
    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert "agent_llm_model_not_offerable" in rendered, "the operator ground is logged"
    assert "deployment" in rendered, "the ground the client message dropped is in the log"


def test_in_call_llm_routes_an_openai_model_to_the_openai_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `elif leg.builder is not None` arm — the OpenAI leg's own endpoint.

    OFFERABILITY IS MONKEYPATCHED, NOT REBUILT, and that is deliberate: whether a model is
    offerable (selectable + credential installed + price attested) is `unofferable_reason`'s
    job and is covered end to end in `tests/model_pricing_test.py`. What is under test here
    is the ROUTING decision one layer down — given an offerable model, which base URL does
    `in_call_llm` choose — and isolating it keeps this a fast unit test rather than a second
    copy of the offerability setup.

    An OpenAI model addresses itself by its own published name (no Azure deployment
    indirection), so `bind_model` returns the identifier unchanged and the endpoint is the
    region-pinned `openai_base_url()`. No Azure credential is configured, which is also the
    point: the OpenAI leg reaches its endpoint without one.
    """
    from apps.api.agents import service

    monkeypatch.setattr(service, "unofferable_reason", lambda _model: None)
    leg = service.in_call_llm("gpt-5.4-mini")

    assert leg["llm_provider"] == "openai"
    assert leg["llm_base_url"] == openai_base_url()
    # Addressed by its own name — never a deployment id, which only Azure has.
    assert leg["llm_model"] == "gpt-5.4-mini"


def test_in_call_llm_routes_an_azure_model_to_its_resource_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `if leg.provider == "azure_openai"` arm — the resource endpoint and the
    deployment id, together, on a fully configured Azure leg.

    Same isolation as the OpenAI case: offerability is stubbed so the test is about routing.
    With all three Azure credentials present the wire carries the DEPLOYMENT id (never the
    model name — that is Azure's one trap) and the base URL is built from the resource.
    """
    from apps.api.agents import service

    _configure(monkeypatch)
    monkeypatch.setattr(service, "unofferable_reason", lambda _model: None)
    leg = service.in_call_llm(AZURE_OPENAI_DEFAULT_MODEL)

    assert leg["llm_provider"] == "azure_openai"
    assert leg["llm_base_url"] == azure_openai_base_url(RESOURCE)
    # The deployment the platform default was configured with, not the model name.
    assert leg["llm_model"] == DEPLOYMENT


def test_in_call_llm_gives_a_google_model_no_base_url_the_engine_builds_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The third arm — neither `azure_openai` nor a leg with a builder.

    The Google leg has `builder=None` on purpose: the engine constructs its Gemini client
    from a single API key and reads no base URL of ours (there is no endpoint knob to set),
    so `in_call_llm` must leave `llm_base_url` UNSET rather than inventing one. This is the
    `756->761` path — the `if`/`elif` both fall through — and it is a real shipped route now
    that gemini-2.5-flash is selectable, not a defensive dead end.
    """
    from apps.api.agents import service

    monkeypatch.setattr(service, "unofferable_reason", lambda _model: None)
    leg = service.in_call_llm("gemini-2.5-flash")

    assert leg["llm_provider"] == "google"
    assert "llm_base_url" not in leg
    assert leg["llm_model"] == "gemini-2.5-flash"
