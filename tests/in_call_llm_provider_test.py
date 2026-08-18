"""The in-call LLM leg can name where it runs, and it cannot name anywhere outside India.

D-400 moved the canonical in-call LLM from Sarvam 105B (free per token, sovereign by
vendor) to Gemini on a PAID Vertex AI account. That is a residency change wearing a
pricing decision: D-36's guarantee was an argument about a VENDOR, and the replacement —
D-127's, now extended to the in-call leg — is an argument about an ENDPOINT. An endpoint
is a string, the difference between `asia-south1` and `us-central1` is nine characters,
and this file is one of the two things standing between those nine characters and a
DPDP-relevant transfer.

THE OTHER THING IS `scripts/check_model_residency.py`, AND THE SPLIT IS THE POINT. That
guard reads the AST and proves every Google model URL *written in this tree* names
Mumbai. It says in its own docstring what it cannot see: a URL assembled at runtime, read
from a store, or handed to a vendor. `ModelConfig`'s validator covers exactly that blind
spot — the VALUE rather than the literal — and this file is what proves the validator is
connected to anything. A tripwire with no test that steps on it is a tripwire nobody has
evidence is wired up (`model_residency_guard_test` makes the same argument about its
subject).

WHAT THIS FILE DELIBERATELY DOES NOT ASSERT, AND THE LINE HAS MOVED (D-404). It used to
be "that the leg is LIVE", because `VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE` was False and
nothing could put a bearer where the engine would find one. That constant is now True and
the rotation is built (`apps/workers/vertex_credential.py`,
`tests/vertex_credential_test.py`), so what is left unasserted is smaller and sharper:
**that a Gemini in-call agent placed a real phone call.** Asserting that would be
asserting a vendor behaviour nobody has observed — `api.bolna.ai` is refused by this
environment's egress proxy, and OPERATIONS §2 gate 16c is where the observation goes.
What IS asserted here is that the configuration is EXPRESSIBLE, that it renders to the
vendor body their published schema and their own server accept, and that no other
endpoint can be expressed at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.api.engine.bolna import BolnaEngine, _agent_models, _llm_routing
from calevate_shared.engine import (
    GEMINI_DEFAULT_LLM,
    GEMINI_LIST_PRICE_USD_PER_MTOK,
    VERTEX_LOCATION,
    ModelConfig,
    vertex_openai_base_url,
)
from pydantic import ValidationError

PROJECT = "calevate-voice"


def _vertex_models() -> ModelConfig:
    return ModelConfig(
        stt_provider="sarvam",
        stt_model="saaras:v3",
        llm_model=GEMINI_DEFAULT_LLM,
        llm_provider="vertex_openai",
        llm_base_url=vertex_openai_base_url(PROJECT),
        tts_provider="sarvam",
        tts_voice="anushka",
    )


# --- the endpoint --------------------------------------------------------------------


def test_the_base_url_carries_mumbai_in_both_places_it_appears() -> None:
    """Host AND path. They are separate strings in the URL and can disagree — a host
    pinned to Mumbai with `locations/global` in the path is the global endpoint wearing
    a regional host, which is the substitution D-127 exists to refuse."""
    url = vertex_openai_base_url(PROJECT)
    assert url.startswith(f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/")
    assert f"/locations/{VERTEX_LOCATION}/" in url
    assert "global" not in url


def test_the_base_url_is_the_openai_surface_and_not_the_generatecontent_one() -> None:
    """`endpoints/openapi` is the OpenAI Chat Completions door, which is the only one a
    voice engine speaking OpenAI can use. `:generateContent` is our own client's door
    (`workers/extraction.py`) and sending it here would 404 at dial time."""
    url = vertex_openai_base_url(PROJECT)
    assert url.endswith("/endpoints/openapi")
    assert ":generateContent" not in url


# --- what the config will and will not accept -----------------------------------------


@pytest.mark.parametrize(
    "base_url",
    [
        # The global endpoint: Google states the caller cannot control or know which
        # region processes the request on it.
        "https://aiplatform.googleapis.com/v1/projects/p/locations/global/endpoints/openapi",
        # A regional HOST with a global PATH — the half a reviewer waves through.
        "https://asia-south1-aiplatform.googleapis.com/v1/projects/p/locations/global/endpoints/openapi",
        # The right shape, the wrong nine characters.
        "https://us-central1-aiplatform.googleapis.com/v1/projects/p/locations/us-central1/endpoints/openapi",
        # The AI Studio Developer API, which D-127 disqualified outright and which is
        # what Bolna's own first-party `provider: "google"` reaches.
        "https://generativelanguage.googleapis.com/v1beta",
        # Something that is not Google at all, reached by a config bug or a paste.
        "https://api.openai.com/v1",
    ],
)
def test_no_endpoint_outside_mumbai_can_be_configured(base_url: str) -> None:
    with pytest.raises(ValidationError):
        ModelConfig(llm_provider="vertex_openai", llm_base_url=base_url)


def test_a_vertex_leg_without_an_endpoint_is_refused() -> None:
    """Naming the provider and omitting the URL would route to the engine's default
    client with a Gemini model identifier — a confusing 4xx from a vendor rather than a
    sentence about what is wrong."""
    with pytest.raises(ValidationError):
        ModelConfig(llm_provider="vertex_openai", llm_model=GEMINI_DEFAULT_LLM)


def test_an_endpoint_without_a_provider_is_refused() -> None:
    """The shape a future caller reaches for when it wants "just point the LLM
    somewhere" — and the one that would send our endpoint to the wrong client."""
    with pytest.raises(ValidationError):
        ModelConfig(llm_base_url=vertex_openai_base_url(PROJECT))


def test_the_pre_d400_config_is_still_valid_and_unchanged() -> None:
    """Every agent row in this repository resolves to this: no provider, no base URL,
    the engine's own default. A residency validator that broke it would be a validator
    that broke every live agent."""
    models = ModelConfig(llm_model="sarvam-105b")
    assert models.llm_provider is None
    assert models.llm_base_url is None


# --- what the adapter sends ----------------------------------------------------------


def test_an_unset_provider_renders_exactly_what_the_adapter_sent_before() -> None:
    """The word "before" means D-355's body, not D-283's, and the gap is a live wire change.
    D-400 was written against a tree that sent no `provider` at all; D-355 landed
    `"provider": "openai"` in between, on the argument that spelling both fields the same
    way is the only combination that cannot route somewhere we did not name. An omitted
    `provider` merely DEFAULTS to `openai` on their side (`Llm.provider`), so returning
    `{"family": "openai"}` here would swap an explicit choice for a vendor default — a
    silent revert of D-355 for every agent in the tree, which is precisely what this
    function's docstring forbids."""
    assert _llm_routing(ModelConfig(llm_model="sarvam-105b")) == {
        "provider": "openai",
        "family": "openai",
    }


def test_a_vertex_leg_renders_the_provider_the_engine_actually_routes_on() -> None:
    """READ AT SOURCE (`bolna/providers.py::SUPPORTED_LLM_PROVIDERS`): `provider` picks
    the client class and `"custom"` picks the OpenAI one, which is then constructed with
    our `base_url`. `family` is declared on their model and read by nothing, which is
    why the assertion that matters is on `provider`."""
    body = _llm_routing(_vertex_models())
    assert body["provider"] == "custom"
    assert body["base_url"] == vertex_openai_base_url(PROJECT)


def test_the_agent_body_carries_the_endpoint_into_the_llm_block() -> None:
    """The seam end to end: our config, their agent object, the URL where they will
    find it. `_agent_body` is the one place both `create_agent` and `update_agent` pass
    through, so this covers both.

    THE KEYS LIVE UNDER `llm_config`, NOT AT THE `llm_agent` ROOT, and the assertion is
    written that deep on purpose. `POST /v2/agent` binds `tools_config` to
    `ToolsConfigV2`, whose `llm_agent` is `LlmAgentV2` — model settings NESTED under
    `llm_config` (D-355). A `base_url` spread at the flat v1 level is a key the v2
    endpoint does not read, so it would send Indian callers' words to the engine's
    default OpenAI host while every test on the flat shape stayed green: the residency
    guarantee would be silently absent rather than loudly broken."""
    from calevate_shared.engine import AgentConfig

    cfg = AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="Reception",
        direction="inbound",
        system_prompt="Book appointments.",
        opening_line="",
        models=_vertex_models(),
    )
    body = BolnaEngine(api_key="k", fx_rate=Decimal("83.50"))._agent_body(cfg)
    llm_agent = body["agent_config"]["tasks"][0]["tools_config"]["llm_agent"]
    assert llm_agent["agent_type"] == "simple_llm_agent"
    llm = llm_agent["llm_config"]
    assert llm["model"] == GEMINI_DEFAULT_LLM
    assert llm["provider"] == "custom"
    assert llm["base_url"] == vertex_openai_base_url(PROJECT)
    # The flat v1 spelling must NOT also be present: two spellings of one endpoint is
    # how a corrected URL gets applied in one place and ignored in the other.
    assert "base_url" not in llm_agent


def test_a_bolna_google_provider_is_never_sent() -> None:
    """Bolna ships a first-party Gemini provider needing one static `GOOGLE` key, and it
    is `genai.Client(api_key=…)` against `generativelanguage.googleapis.com` — the AI
    Studio Developer API, disqualified by D-127 on residency AND on free-tier terms under
    which Google states human reviewers may read submitted prompts and responses. It is
    the EASY way to put Gemini on this leg, which is exactly why it needs a test rather
    than a comment."""
    for models in (_vertex_models(), ModelConfig(llm_model="sarvam-105b")):
        assert _llm_routing(models).get("provider") != "google"


# --- what the adapter reads back ------------------------------------------------------


def test_a_mumbai_endpoint_read_back_is_recognised_as_a_vertex_leg() -> None:
    models, readable = _agent_models(
        {
            "tasks": [
                {
                    "tools_config": {
                        "llm_agent": {
                            "model": GEMINI_DEFAULT_LLM,
                            "provider": "custom",
                            "base_url": vertex_openai_base_url(PROJECT),
                        }
                    }
                }
            ]
        }
    )
    assert readable
    assert models is not None
    assert models.llm_provider == "vertex_openai"
    assert models.llm_base_url == vertex_openai_base_url(PROJECT)


def test_the_v2_nesting_this_adapter_actually_writes_reads_back_too() -> None:
    """THE ROUND TRIP, and the case the read arrived unable to handle. `_agent_body`
    writes `base_url` inside `llm_config` (D-355); the D-400 read looked only at the flat
    v1 key, so every agent this adapter creates would have read back as "no Vertex
    endpoint configured" — a confident wrong answer on the field that carries residency,
    which is exactly the failure mode `_agent_models`'s docstring exists to prevent. The
    flat case above stays because an account may still hold v1-era agents."""
    models, readable = _agent_models(
        {
            "tasks": [
                {
                    "tools_config": {
                        "llm_agent": {
                            "agent_type": "simple_llm_agent",
                            "llm_config": {
                                "model": GEMINI_DEFAULT_LLM,
                                "provider": "custom",
                                "base_url": vertex_openai_base_url(PROJECT),
                            },
                        }
                    }
                }
            ]
        }
    )
    assert readable
    assert models is not None
    assert models.llm_model == GEMINI_DEFAULT_LLM
    assert models.llm_provider == "vertex_openai"
    assert models.llm_base_url == vertex_openai_base_url(PROJECT)


def test_an_endpoint_we_do_not_recognise_reads_back_as_no_provider_and_never_raises() -> None:
    """A read-back that RAISED would turn "the vendor stored something odd" into a failed
    publish, which is the one shape D-260 says a snapshot must never take. It must also
    not be normalised into a Vertex leg — the whole point is that this URL is not one."""
    models, readable = _agent_models(
        {
            "tasks": [
                {
                    "tools_config": {
                        "llm_agent": {
                            "model": GEMINI_DEFAULT_LLM,
                            "provider": "custom",
                            "base_url": "https://us-central1-aiplatform.googleapis.com/v1",
                        }
                    }
                }
            ]
        }
    )
    assert readable
    assert models is not None
    assert models.llm_provider is None
    assert models.llm_base_url is None


# --- the money the decision costs -----------------------------------------------------


def test_the_published_price_is_stated_once_and_the_rupee_table_derives_from_it() -> None:
    """D-400's second defect class: two INR literals with the exchange rate already
    folded in cannot both be corrected when the vendor's dollar price moves, and there
    are now two readers of that price. This asserts the derivation rather than the
    numbers, so the test survives a price change and the numbers do not."""
    from apps.api.billing.rates import LIST_PRICE_USD_INR, LLM_INR_PER_KTOK

    for leg, usd_per_mtok in GEMINI_LIST_PRICE_USD_PER_MTOK.items():
        assert LLM_INR_PER_KTOK[leg] == (usd_per_mtok * LIST_PRICE_USD_INR / 1000).quantize(
            LLM_INR_PER_KTOK[leg]
        )


def test_the_llm_leg_costs_more_per_minute_on_a_longer_call() -> None:
    """TRD §6.1: the full conversation is resent every turn, so input tokens grow through
    the call and a single "₹x/min" is a blended average a long call skews above. The
    figure D-36 retired (₹0.00, free per token) had no such shape; the one replacing it
    does, and a cost model that quoted minute one while reasoning about minute ten would
    understate the leg by more than half."""
    from apps.api.billing.rates import llm_cost_inr_per_minute

    assert llm_cost_inr_per_minute(1) < llm_cost_inr_per_minute(5) < llm_cost_inr_per_minute(10)
    with pytest.raises(ValueError):
        llm_cost_inr_per_minute(0)


# --- the one switch, and every arm of it ----------------------------------------------
#
# `in_call_llm` is the single decision point for the whole leg, and since D-404 it has
# THREE necessary conditions rather than two. Each is exercised alone, because a condition
# whose failing arm nobody has run is a condition nobody knows the shape of — and each
# names a different way the leg breaks at a different, worse moment.

SERVICE_ACCOUNT_JSON = '{"client_email": "a@b.iam.gserviceaccount.com", "private_key": "x"}'


def test_a_deployment_with_no_gcp_project_stays_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No project means no id to interpolate into the URL, so there is no endpoint to
    name. Local, CI and any staging without a Google account are exactly this, and they
    must keep publishing."""
    from apps.api.agents import service
    from apps.api.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "gcp_service_account_json", SERVICE_ACCOUNT_JSON)
    assert service.in_call_llm("sarvam-105b") == {"llm_model": "sarvam-105b"}


def test_a_deployment_that_cannot_mint_a_bearer_stays_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**THE D-404 CONDITION, AND THE ONE A REVIEWER WOULD DROP.** Every deployment
    running D-127's dashboard AI already has `gcp_project_id` set. If the project alone
    were enough, switching the dashboard assistant on would silently move every agent's
    in-call LLM to a Vertex endpoint this deployment holds no service account for — and
    that does not fail at publish time, where somebody would see it. It fails as a 401
    from Vertex, mid-sentence, on a client's live phone call.

    Deleting the `can_mint` clause from `in_call_llm` passes every other test in this
    file."""
    from apps.api.agents import service
    from apps.api.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "gcp_project_id", PROJECT)
    monkeypatch.setattr(get_settings(), "gcp_service_account_json", None)
    assert service.in_call_llm("sarvam-105b") == {"llm_model": "sarvam-105b"}


def test_the_founders_switch_is_still_a_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE` is True today, and it must still be able to
    turn the leg OFF for a fully configured deployment — that is what makes it a switch
    rather than a comment. The same constant is read by the refresher, which stops writing
    credentials when it is False, so the two halves cannot disagree about whether the leg
    is on."""
    from apps.api.agents import service
    from apps.api.core.settings import get_settings

    monkeypatch.setattr(service, "VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE", False)
    monkeypatch.setattr(get_settings(), "gcp_project_id", PROJECT)
    monkeypatch.setattr(get_settings(), "gcp_service_account_json", SERVICE_ACCOUNT_JSON)
    assert service.in_call_llm("sarvam-105b") == {"llm_model": "sarvam-105b"}


def test_a_fully_configured_deployment_moves_the_endpoint_and_the_model_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The half a reviewer would wave through: `agents.llm_model` holds what an operator
    configured, and sending `sarvam-105b` to Vertex is a 404 at dial time on a live phone
    line. The endpoint and the identifier are ONE decision."""
    from apps.api.agents import service
    from apps.api.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "gcp_project_id", PROJECT)
    monkeypatch.setattr(get_settings(), "gcp_service_account_json", SERVICE_ACCOUNT_JSON)

    leg = service.in_call_llm("sarvam-105b")
    assert leg == {
        "llm_model": GEMINI_DEFAULT_LLM,
        "llm_provider": "vertex_openai",
        "llm_base_url": vertex_openai_base_url(PROJECT),
    }
    # And it must be a config `ModelConfig` will actually accept — the residency
    # validator runs on exactly this dict the moment `_to_config` builds one from it.
    assert ModelConfig(**leg).llm_base_url == vertex_openai_base_url(PROJECT)
