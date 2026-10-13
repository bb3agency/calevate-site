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
it; and the leg's model identifier and its endpoint cannot be configured apart.

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
from calevate_shared.engine import (
    AZURE_LOCATION,
    ModelConfig,
    azure_openai_base_url,
)
from pydantic import ValidationError

RESOURCE = "calevate-voice"
#: The DEPLOYMENT ID, which is what travels in the vendor's one model slot. Deliberately
#: unlike any model name in `AZURE_OPENAI_MODELS`, so a test that confuses the two fails
#: instead of coincidentally passing — the whole point of the distinction is that on every
#: other OpenAI-compatible provider these two strings are one string.
DEPLOYMENT = "calevate-voice-inbound"
ENDPOINT = azure_openai_base_url(RESOURCE)


def _azure_models() -> ModelConfig:
    return ModelConfig(
        stt_provider="sarvam",
        stt_model="saaras:v3",
        llm_model=DEPLOYMENT,
        llm_provider="azure_openai",
        llm_base_url=ENDPOINT,
        tts_provider="cartesia",
        tts_model="sonic-3.5",
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
