"""The Azure OpenAI client and the ONE availability policy (D-410, inheriting D-127 G-6).

WHY EVERY ASSERTION HERE IS ABOUT WHAT WE *ASKED*, NOT ABOUT WHAT WE STORED. There is no
Azure resource and `*.openai.azure.com` is unreachable from this environment, so nothing
in this file can talk to Microsoft. A test that only checked the rows we wrote afterwards
would pass identically against a client pointed at the classic dated-`api-version`
surface, at OpenAI direct, or at nothing at all — which is precisely the defect class
D-127 exists for. So the double RECORDS the request: host, path, query, headers and body.

**WHAT THIS FILE CAN AND CANNOT PROVE, SAID FIRST, BECAUSE D-410 MADE IT WEAKER.** The
Vertex client it replaced put `asia-south1` in the hostname AND the `locations/` path
segment, so a test could read residency straight off the URL. `<resource>.openai.azure.com`
names no region at all: **where the request is processed is a property of the Azure
RESOURCE, asserted by config and verified by a human in the portal.** That is a real
weakening and this file states it as one (`test_the_endpoint_cannot_prove_its_own_region`)
rather than dressing up a weaker check as the old proof. What is still provable, and is
proved here, is everything else the endpoint decision rests on:

  1. the host is the **custom-subdomain v1 surface**, built from the ONE builder;
  2. there is **no `api-version` query parameter** — the v1 surface needs none, and the
     dated one is a second thing to keep current;
  3. authentication is `Authorization: Bearer <static key>` and **never** an `api-key:`
     header, a query parameter, or an OAuth2 handshake;
  4. the body addresses the **DEPLOYMENT**, while everything we meter and baseline names
     the MODEL — the two are different strings and only one goes on the wire.

THE SECOND HALF IS THE POLICY (G-6), and it is tested as a pure function of its inputs
because that is how it was written: `assist_capability()` takes the two facts nobody can
read from configuration (quota, and whether the provider just failed) as arguments, so
every one of its states is reachable without a database, a clock or a network.

Hard rule 6 throughout: no assertion here prints a transcript, and no assertion prints
the key.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.workers import extraction as extraction_module
from apps.workers.extraction import (
    AZURE_PROVIDER,
    AZURE_SCHEMA_NAME,
    NO_CREDENTIAL_REASON,
    PROVIDER_UNAVAILABLE_REASON,
    QUOTA_EXHAUSTED_REASON,
    SARVAM_PROVIDER,
    AssistCapability,
    AzureOpenAIExtractor,
    OfflineExtractor,
    SarvamExtractor,
    assist_capability,
    assist_unavailable,
    azure_credentials,
    azure_extractor,
    build_azure_response_schema,
    get_extractor,
    run_assist,
)
from calevate_shared.engine import (
    AZURE_LOCATION,
    AZURE_OPENAI_DEFAULT_MODEL,
    AZURE_OPENAI_MODELS,
    azure_openai_base_url,
)
from calevate_shared.extraction import ExtractionField, ExtractionSchemaSpec

RESOURCE = "calevate-test"
API_KEY = "azure-static-key-value-under-test"
DEPLOYMENT = "calevate-assist-v1"

SPEC = ExtractionSchemaSpec(
    version=3,
    fields=[
        ExtractionField(key="caller_name", label="Caller name", type="text"),
        ExtractionField(
            key="intent",
            label="Intent",
            type="enum",
            enum_values=["book", "cancel", "enquiry"],
            reason="What the caller rang about",
        ),
        ExtractionField(key="party_size", label="Party size", type="number"),
        ExtractionField(key="site_visit_interest", label="Site visit interest", type="bool"),
        ExtractionField(key="visit_on", label="Visit on", type="date"),
    ],
)

# Already through `redact()`: a phone number is `[REDACTED]`, which is what `run_assist`
# requires and what `transcript_turns.text_redacted` holds.
REDACTED_TRANSCRIPT = "caller: naa peru Ravi, 3BHK kavali\nagent: sari andi"

#: What an Azure error body says, in this file. Real ones echo the request.
VENDOR_BODY_MARKER = "vendor-error-body-must-never-be-logged"


class FakeAzure:
    """Azure, as far as httpx is concerned. RECORDS what we actually sent.

    Deliberately not a model: it answers with the response SHAPE the OpenAI-compatible
    surface answers with and keeps the request objects, because the request is the
    artefact under test. Anything more would be testing the fake.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        #: Refuse `response_format: json_schema` with a 400, the way a resource whose
        #: model predates Structured Outputs would. `json_object` still answers, which is
        #: what makes the degrade observable rather than merely survivable.
        self.refuse_json_schema = False
        self.answer: dict[str, Any] = {
            "caller_name": "Ravi",
            "intent": "enquiry",
            "party_size": None,
            "site_visit_interest": None,
            "visit_on": None,
            "summary": "Caller asked about a 3BHK.",
            "sentiment": "neutral",
            "outcome_tag": "resolved",
            "out_of_scope": False,
            "callback_requested": False,
        }
        #: Set for a content-filter refusal — `choices: []`, an ordinary 200.
        self.blocked = False
        #: Azure's own token count. `None` returns a body WITHOUT the block, which is how
        #: "we do not know what this cost" is spelled — distinct from zero.
        #:
        #: `completion_tokens_details` is a BREAKDOWN of `completion_tokens`, never an
        #: addition to it. It is here so the regression has something to double-count.
        self.usage: dict[str, Any] | None = {
            "prompt_tokens": 1_200,
            "completion_tokens": 800,
            "total_tokens": 2_000,
            "completion_tokens_details": {"reasoning_tokens": 500},
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        asked = dict(json.loads(request.content)).get("response_format", {})
        if self.refuse_json_schema and asked.get("type") == "json_schema":
            return httpx.Response(400, json={"error": {"message": VENDOR_BODY_MARKER}})
        if self.status != 200:
            # A distinctive marker, because real error bodies QUOTE the request — and the
            # request on this path is a call transcript. The only way to prove none of it
            # reaches a log line is to make the body findable.
            return httpx.Response(self.status, json={"error": {"message": VENDOR_BODY_MARKER}})
        choices: list[dict[str, Any]] = (
            []
            if self.blocked
            else [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(self.answer)},
                }
            ]
        )
        body: dict[str, Any] = {"choices": choices}
        if self.usage is not None:
            body["usage"] = self.usage
        return httpx.Response(200, json=body)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def extractor(self, model: str = AZURE_OPENAI_DEFAULT_MODEL) -> AzureOpenAIExtractor:
        return AzureOpenAIExtractor(RESOURCE, API_KEY, DEPLOYMENT, model, client=self.client())

    @property
    def sent(self) -> httpx.Request:
        assert len(self.requests) == 1, self.requests
        return self.requests[0]

    @property
    def body(self) -> dict[str, Any]:
        return dict(json.loads(self.sent.content))

    def body_of(self, index: int) -> dict[str, Any]:
        return dict(json.loads(self.requests[index].content))


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A deployment that holds an Azure credential and no Sarvam key."""
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", RESOURCE, raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", API_KEY, raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", DEPLOYMENT, raising=False)
    monkeypatch.setattr(settings, "azure_openai_model", AZURE_OPENAI_DEFAULT_MODEL, raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    return settings


@pytest.fixture
def unconfigured(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A deployment that holds no Azure credential at all — today's ordinary state."""
    settings = get_settings()
    for field in (
        "azure_openai_resource",
        "azure_openai_api_key",
        "azure_openai_deployment",
        "azure_openai_model",
        "sarvam_api_key",
    ):
        monkeypatch.setattr(settings, field, None, raising=False)
    return settings


def _patch_client(monkeypatch: pytest.MonkeyPatch, azure: FakeAzure) -> None:
    """Point `azure_extractor()`'s constructor at the recording transport.

    Patched on the MODULE rather than injected, because the thing under test is that
    `run_assist` builds its adapter through the one constructor — a test that handed an
    adapter in would not notice if it stopped doing so.
    """

    # `timeout_s` is accepted and forwarded rather than swallowed: `azure_extractor()`
    # passes it now (the assist path asks for a tighter budget than the post-call one), and
    # a stand-in that dropped the keyword would keep these tests green while the real
    # constructor's signature had moved out from under them. It changes no request here —
    # the injected client owns its own timeout, per the adapter's ownership rule.
    def _stand_in(
        resource: str,
        api_key: str,
        deployment: str,
        model: str,
        timeout_s: float = extraction_module.EXTRACTION_TIMEOUT_S,
    ) -> AzureOpenAIExtractor:
        return AzureOpenAIExtractor(
            resource, api_key, deployment, model, client=azure.client(), timeout_s=timeout_s
        )

    monkeypatch.setattr(extraction_module, "AzureOpenAIExtractor", _stand_in)


# --- 1. the request. host, path, query, auth, body --------------------------------


async def test_the_request_goes_to_the_v1_surface_with_a_bearer_and_no_api_version() -> None:
    """THE test. Every fact about the request that makes this client the shipped design
    rather than one of the three it was chosen over, in one place.

    Each one alone is the whole posture: an `api-version` query parameter, an `api-key:`
    header, a credential in the query string or the deployment and the model swapped each
    turns this into a different client, and none of them is visible in the rows we write
    afterwards.
    """
    azure = FakeAzure()

    await azure.extractor().run(SPEC, REDACTED_TRANSCRIPT)

    sent = azure.sent
    assert sent.method == "POST"
    assert str(sent.url).startswith(azure_openai_base_url(RESOURCE)), sent.url
    assert sent.url.path == "/openai/v1/chat/completions", sent.url.path

    # THE V1 SURFACE TAKES NO `api-version`, and that is the reason it was chosen over the
    # classic one: a dated version string is a second thing to keep current, and the day
    # it lapses is the day every assist 400s.
    assert "api-version" not in sent.url.params, f"the dated surface: {sent.url.params}"
    # A query string is where a credential ends up in an access log. Asserted BEFORE the
    # header so a client that reverted to `?key=` fails with a sentence about the key
    # rather than a KeyError about a missing header.
    assert not sent.url.params, f"a credential in the query string: {sent.url.params}"

    assert sent.headers.get("Authorization") == f"Bearer {API_KEY}", (
        "the v1 surface takes the static key in the authorization header, which is what "
        f"lets an OpenAI-shaped client work at all; this request carried {sorted(sent.headers)}"
    )
    assert "api-key" not in {name.lower() for name in sent.headers}, (
        "the classic `api-key:` header is not what an OpenAI-compatible client sends"
    )

    body = azure.body
    # THE DEPLOYMENT GOES ON THE WIRE, THE MODEL DOES NOT. Swapping these is the mistake
    # the two-string design makes easy, and the symptom is a 404 that reads like an
    # availability problem.
    assert body["model"] == DEPLOYMENT
    assert body["model"] != AZURE_OPENAI_DEFAULT_MODEL
    assert body["temperature"] == 0

    # STRUCTURED OUTPUTS, NOT JSON MODE. `json_object` promises only that the bytes parse;
    # `json_schema` + `strict` promises the document matches the agent's extraction
    # schema, which IS the client's CRM columns. Dropping to the weaker form is a
    # product-visible regression and is exactly the edit this assertion exists to catch.
    schema_request = body["response_format"]
    assert schema_request["type"] == "json_schema", (
        "the assist asked for plain JSON mode — a client's CRM columns are back to being "
        "a parser's best effort"
    )
    assert schema_request["json_schema"]["strict"] is True, (
        "`strict: false` makes the schema a HINT; the model may deviate from it"
    )
    assert schema_request["json_schema"]["name"] == AZURE_SCHEMA_NAME
    assert schema_request["json_schema"]["schema"] == build_azure_response_schema(SPEC)


def test_the_endpoint_cannot_prove_its_own_region_and_this_file_says_so() -> None:
    """THE RECORDED WEAKENING (D-410), pinned so nobody later mistakes it for a proof.

    Vertex put `asia-south1` in the host and the path, so residency was readable from the
    URL. Azure's custom-subdomain form names no region: the resource's region is asserted
    by config and confirmed by a human in the portal. This test exists to stop a future
    reader adding `assert AZURE_LOCATION in url` — which would pass only by accident of
    how somebody named a resource, and would report a guarantee this design does not
    make. What IS still enforced is that one spelling of the region exists and that no
    endpoint is built outside the single builder.
    """
    url = azure_openai_base_url(RESOURCE)
    assert AZURE_LOCATION not in url, (
        "the shipped hostname now carries the region — if that is deliberate, D-410's "
        "rejected regional-hostname alternative has been taken and this file, "
        "check_model_residency and the OPERATIONS gate all have to change together"
    )
    assert url == f"https://{RESOURCE}.openai.azure.com/openai/v1"


def test_no_azure_endpoint_is_spelled_in_this_modules_code() -> None:
    """`check_model_residency` proves this across the tree; this proves it for the file a
    reader is most likely to add a second f-string to, and fails on the same commit rather
    than at the next guardrail run. One builder is what makes the host unable to disagree
    with itself.

    PROSE IS EXEMPT AND CODE IS NOT: the class docstring quotes the hostname on purpose,
    to say what the endpoint is and why it cannot prove its own region. Docstring nodes
    are excluded through `check_wiring`'s own helper rather than a second parser, because
    two ideas of "is this string prose" is the drift both files exist to catch.
    """
    import ast
    from pathlib import Path

    from scripts.check_wiring import _docstring_nodes

    tree = ast.parse(Path(str(extraction_module.__file__)).read_text(encoding="utf-8"))
    prose = _docstring_nodes(tree)
    spelled = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in prose
        and "openai.azure.com" in node.value
    ]
    assert spelled == [], (
        f"an Azure hostname is spelled in module code at line(s) {spelled}, outside "
        "`azure_openai_base_url` — the one builder the residency guard reads"
    )


async def test_a_content_filter_refusal_is_an_ordinary_response_and_not_a_crash() -> None:
    """Azure's content filter answers 200 with no usable choice — documented behaviour,
    not an exception. Indexing it blindly is the IndexError that once failed a whole
    post-call job, losing the call to keep the fields."""
    azure = FakeAzure()
    azure.blocked = True

    assert await azure.extractor().run(SPEC, REDACTED_TRANSCRIPT) == {}


async def test_a_null_content_is_not_a_string_called_none() -> None:
    """`content` is nullable on this wire format. `str(None)` is `"None"`, which the
    fence-stripper would happily scan and return `{}` from — the right answer for the
    wrong reason, and one refactor away from being wrong."""
    azure = FakeAzure()
    azure.answer = {}
    handler_body = {"choices": [{"message": {"role": "assistant", "content": None}}]}
    azure.handler = lambda request: httpx.Response(200, json=handler_body)  # type: ignore[method-assign]

    assert await azure.extractor().run(SPEC, REDACTED_TRANSCRIPT) == {}


# --- 2. G-7: the first post-call extraction never reaches the assist provider ------


def test_get_extractor_cannot_return_the_assist_provider_even_with_a_credential(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE G-2 REGRESSION. `pipeline.py` hands `get_extractor()` the RAW transcript.

    Before D-127 this function returned the assist client whenever that provider's key was
    present and a Sarvam key was not — so one absent environment variable sent raw caller
    PII to a second processor. The precedence is not merely Sarvam-FIRST any more; the
    assist provider is not in the ladder at all, and D-410 changing WHICH company holds
    that key changed nothing about the argument.
    """
    assert azure_credentials() is not None, "the fixture did not configure Azure"
    assert isinstance(get_extractor(), OfflineExtractor)

    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)
    assert isinstance(get_extractor(), SarvamExtractor)


def test_the_capability_constant_is_the_greppable_form_of_g7() -> None:
    """`check_docs_drift` §5 judges prose that quotes this name by value. It is only worth
    minting if it says what the code does, so this is the tie between the two.

    THE NAME IS A FOSSIL ON PURPOSE: Gemini is gone from this product, and renaming the
    constant would unbind every doc sentence the drift check matches on it in the same
    commit that changed what they are about. What it stands for is "the first post-call
    extraction does not run on the assist provider, whoever that is".
    """
    assert extraction_module.GEMINI_EXTRACTION_DEFAULT is False
    assert extraction_module.ASSIST_QUOTA_ENFORCED is True


async def test_run_assist_refuses_text_that_has_not_been_redacted(configured: Any) -> None:
    """G-2, enforced structurally rather than promised in a parameter name.

    A parameter called `redacted_transcript` is exactly the guarantee `pipeline.py:750`
    broke by accident, with `turn.text` and `redacted.text` one line apart.
    """
    with pytest.raises(ProblemError) as caught:
        await run_assist(SPEC, "caller: naa number 9876543210, malli call cheyandi")

    assert caught.value.code == "assist_input_not_redacted"
    assert "text_redacted" in (caught.value.remediation or "")


# --- 3. G-6: one place decides, and a fallback is always disclosed ----------------


def test_a_configured_deployment_answers_with_azure_and_discloses_nothing(
    configured: Any,
) -> None:
    """Nothing was substituted, so there is nothing to disclose. A capability that carried
    a disclosure on the happy path would train every surface to ignore the field."""
    capability = assist_capability()
    assert capability.available is True
    assert capability.provider == AZURE_PROVIDER
    assert capability.reason is None
    assert capability.fallback_reason is None
    assert capability.disclosure is None


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"quota_exhausted": True}, QUOTA_EXHAUSTED_REASON),
        ({"provider_unavailable": True}, PROVIDER_UNAVAILABLE_REASON),
    ],
)
def test_every_fallback_names_its_own_reason_and_says_so_in_words(
    configured: Any, monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, bool], expected: str
) -> None:
    """The reasons are not decoration: a client at their ceiling and a client hitting a
    vendor outage need different sentences, and a surface that saw only `available=False`
    would show them the same one."""
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    capability = assist_capability(**kwargs)

    assert capability.available is True
    assert capability.provider == SARVAM_PROVIDER
    assert capability.fallback_reason == expected
    assert capability.disclosure is not None
    assert "Sarvam" in capability.disclosure


def test_an_off_list_model_is_refused_where_values_enter_and_not_here() -> None:
    """WHY THIS LEG HAS NO `model_not_allowed` REASON CODE, asserted rather than asserted
    about in a comment.

    D-127 carried a fourth reason here (`ai_studio_key_disqualified`) for a deployment
    configured WRONGLY rather than not at all, and the obvious Azure analogue is "the
    model is not one we ship". It would be an arm no user can reach: `azure_openai_model`
    is a closed `Literal` and `platform_config.validate_value` — the ONE door a console
    write goes through — checks a candidate against that field definition before storing
    it. The allow-list is enforced strictly earlier and strictly more completely than a
    runtime branch could, and a second statement of the rule is a second place for the
    two to differ.

    A future contributor who deletes the `Literal` and reaches for a runtime check gets
    this failure first.
    """
    import pydantic
    from apps.api.core.platform_config import validate_value

    with pytest.raises(pydantic.ValidationError):
        validate_value("azure_openai_model", "gpt-9-omni-turbo")

    assert validate_value("azure_openai_model", "gpt-4.1-mini") == "gpt-4.1-mini", (
        "the live switch D-410 shipped stopped being settable"
    )


def test_the_configured_model_is_what_the_client_reports_and_the_default_ships(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`gpt-4o-mini` is the default because it is the cheaper of the two — at `eastus2`
    both are available on the mandated SKU, so D-449 left the choice to price (D-410 chose
    it on an availability claim that was backwards). `gpt-4.1-mini` is the live switch, and
    switching it must reach the client without a deploy or it is not a switch."""
    assert AZURE_OPENAI_DEFAULT_MODEL in AZURE_OPENAI_MODELS

    built = azure_extractor()
    assert built is not None
    assert built.model_name == AZURE_OPENAI_DEFAULT_MODEL

    monkeypatch.setattr(get_settings(), "azure_openai_model", "gpt-4.1-mini", raising=False)
    switched = azure_extractor()
    assert switched is not None
    assert switched.model_name == "gpt-4.1-mini"


def test_a_half_configured_deployment_is_named_rather_than_reported_as_empty(
    configured: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An operator midway through a change must not be told "nothing is configured" —
    that sends them to install what they already installed. The log names the FIELDS that
    are missing and never a value: one of the three IS the credential."""
    monkeypatch.setattr(get_settings(), "azure_openai_deployment", None, raising=False)

    with caplog.at_level(logging.DEBUG):
        assert azure_credentials() is None

    record = next(r for r in caplog.records if r.getMessage() == "azure_credential_incomplete")
    assert record.levelno == logging.ERROR
    assert record.__dict__["missing"] == ["azure_openai_deployment"]
    blob = "\n".join(f"{r.__dict__}" for r in caplog.records)
    assert API_KEY not in blob, f"the key reached a log line: {blob}"


def test_nothing_configured_at_all_says_nothing_rather_than_crying_wolf(
    unconfigured: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """No Azure resource exists yet, so this is the ORDINARY state of every deployment
    today. An error line per assist attempt for the expected state is how an operator
    learns to ignore the channel."""
    with caplog.at_level(logging.DEBUG):
        assert azure_credentials() is None

    assert [r for r in caplog.records if r.getMessage() == "azure_credential_incomplete"] == []


def test_with_nothing_configured_it_refuses_with_something_a_user_can_do(
    unconfigured: Any,
) -> None:
    """Refusal, not a silent empty state (§52). `OfflineExtractor` is deliberately NOT in
    the ladder: substituting a deterministic literal-text reader for "re-summarise this
    call" would be substituting a different KIND of thing while claiming to substitute a
    model."""
    capability = assist_capability()
    assert capability.available is False
    assert capability.reason == NO_CREDENTIAL_REASON
    assert capability.provider is None

    problem = assist_unavailable(capability)
    assert problem.code == "assist_no_credential"
    # THE OPERATOR'S SENTENCE IS STILL THE OPERATOR'S SENTENCE. This assertion used to be
    # made against the DEFAULT audience, which is how the env-var text reached a client.
    operator = assist_unavailable(capability, audience="operator")
    assert "AZURE_OPENAI_RESOURCE" in (operator.remediation or "")

    quota = assist_unavailable(AssistCapability(available=False, reason=QUOTA_EXHAUSTED_REASON))
    assert "Add credit" in (quota.remediation or "")
    assert quota.remediation != problem.remediation, (
        "two different reasons produced one sentence — the reason codes buy nothing"
    )


async def test_an_azure_failure_falls_back_to_sarvam_and_the_answer_says_so(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole of G-6 in one path: Azure fails, Sarvam answers, and the RESULT carries
    the sentence. A silent fallback quietly changes output quality with nobody told."""
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    sarvam_calls: list[str] = []

    async def _sarvam_run(
        self: SarvamExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        sarvam_calls.append(transcript)
        return {"summary": "from sarvam", "sentiment": "neutral", "outcome_tag": "resolved"}

    async def _azure_run(
        self: AzureOpenAIExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        raise httpx.ConnectError("azure is unreachable")

    monkeypatch.setattr(SarvamExtractor, "run", _sarvam_run)
    monkeypatch.setattr(AzureOpenAIExtractor, "run", _azure_run)

    result = await run_assist(SPEC, REDACTED_TRANSCRIPT)

    assert sarvam_calls == [REDACTED_TRANSCRIPT]
    assert result.capability.provider == SARVAM_PROVIDER
    assert result.capability.fallback_reason == PROVIDER_UNAVAILABLE_REASON
    assert result.capability.disclosure is not None
    assert result.output.summary == "from sarvam"


async def test_an_azure_failure_with_no_sarvam_key_refuses_rather_than_returning_nothing(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The half a naive implementation gets wrong. `extract_call` swallows a provider
    failure into `errors["_model"]` so a post-call pipeline never loses a call over one —
    which is right there and wrong here, where a user is waiting and would be handed a
    blank answer that looks like a successful one."""

    async def _azure_run(
        self: AzureOpenAIExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        raise httpx.ConnectError("azure is unreachable")

    monkeypatch.setattr(AzureOpenAIExtractor, "run", _azure_run)

    with pytest.raises(ProblemError) as caught:
        await run_assist(SPEC, REDACTED_TRANSCRIPT)

    assert caught.value.code == f"assist_{PROVIDER_UNAVAILABLE_REASON}"
    assert "did not answer" in (caught.value.remediation or "")


async def test_the_happy_path_runs_on_azure_and_returns_validated_fields(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end through the real client, so the URL under test is the one a user's
    assist would actually reach — and the schema-validated fields come back."""
    azure = FakeAzure()
    _patch_client(monkeypatch, azure)

    result = await run_assist(SPEC, REDACTED_TRANSCRIPT)

    assert result.capability.provider == AZURE_PROVIDER
    assert result.capability.disclosure is None
    assert result.output.data["caller_name"] == "Ravi"
    assert result.output.data["intent"] == "enquiry"
    assert result.output.valid is True
    assert azure.sent.url.host == f"{RESOURCE}.openai.azure.com"


# --- 4. the schema, and the promise it carries -----------------------------------


def test_the_schema_describes_the_agents_own_fields() -> None:
    """A model-side schema is a stronger guarantee than a parser, and it is only that if
    it is built from the SPEC rather than from a template."""
    schema = build_azure_response_schema(SPEC)
    properties = schema["properties"]

    # NULLABILITY IS A TYPE UNION, not Vertex's `nullable` keyword — strict mode rejects
    # that dialect, and this is the JSON Schema spelling of the same fact.
    assert properties["caller_name"] == {"type": ["string", "null"]}
    assert properties["party_size"]["type"] == ["number", "null"]
    assert properties["site_visit_interest"]["type"] == ["boolean", "null"]
    # A date is a STRING, deliberately: `format: "date"` would make the model invent a
    # calendar date for "repu udayam" to satisfy the type — and strict mode rejects
    # `format` anyway, so the product argument and the vendor constraint agree.
    assert properties["visit_on"]["type"] == ["string", "null"]
    assert "format" not in properties["visit_on"]

    # An enum's members are constrained at the MODEL rather than rejected at the
    # validator. `None` rides in the list because a nullable enum whose enum omits null
    # is a schema no value can satisfy.
    assert properties["intent"]["enum"] == ["book", "cancel", "enquiry", None]
    assert properties["intent"]["description"] == "What the caller rang about"


def test_the_schema_satisfies_strict_modes_own_rules() -> None:
    """Strict mode REJECTS THE REQUEST if the schema breaks its rules, so a builder that
    got these wrong would 400 every assist for every tenant. That is a good failure — it
    lands at request time, loudly, and never silently on a caller's data — but it is
    still a failure, so the rules are asserted here rather than discovered in production.
    """
    for spec in (SPEC, ExtractionSchemaSpec(version=1, fields=[])):
        schema = build_azure_response_schema(spec)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        # EVERY property required — the rule that reads like a conflict with "absent
        # means null" and is not: optionality lives in the type union instead.
        assert set(schema["required"]) == set(schema["properties"])
        assert len(schema["required"]) == len(schema["properties"]), schema["required"]


def test_required_and_nullable_together_still_never_ask_the_model_to_invent() -> None:
    """THE PROPERTY THAT MATTERS, and the one strict mode looks like it takes away.

    Forcing a client's `callback_number` to carry a value pushes the model to fabricate
    one, and a phone number one digit wrong is the worst output this system can produce.
    Strict mode requires the KEY, never a value — so every tenant field can still be
    `null`, and only the five keys `ExtractionOutput` always carries may not be.
    """
    schema = build_azure_response_schema(SPEC)
    for field in SPEC.fields:
        assert "null" in schema["properties"][field.key]["type"], field.key

    for fixed in ("summary", "sentiment", "outcome_tag", "out_of_scope", "callback_requested"):
        assert "null" not in schema["properties"][fixed]["type"], fixed


def test_a_present_null_is_the_same_answer_as_an_absent_key() -> None:
    """WHY REQUIRING EVERY KEY CHANGED NOTHING ABOUT HOW A SCHEMA IS EXPRESSED.

    Strict mode moves the wire spelling of "the caller never said" from an absent key to
    a present `null`. That is only free if the two are indistinguishable downstream, so
    this is the tie: `coerce_value` short-circuits on `raw is None` and
    `validate_extraction` skips a None, which makes them one case and not two.
    """
    from calevate_shared.extraction import validate_extraction

    absent = validate_extraction(SPEC, {"intent": "book"})
    explicit = validate_extraction(
        SPEC,
        {
            "intent": "book",
            "caller_name": None,
            "party_size": None,
            "site_visit_interest": None,
            "visit_on": None,
        },
    )

    assert absent.data == explicit.data == {"intent": "book"}
    assert absent.errors == explicit.errors == {}


def test_a_client_field_named_like_a_fixed_one_appears_once_and_stays_last() -> None:
    """`ExtractionField.key` permits every one of the five fixed keys, and "Summary of
    complaint" is an ordinary column for a client to author with `summary` as its key.

    Under Vertex this needed a separate `propertyOrdering` list, which named the colliding
    key TWICE — a malformed OpenAPI object — so one client's choice of field name turned
    every assist for that tenant into a 400 that `extract_call` could only report as the
    word `HTTPStatusError`. Order is property order here, so a dict cannot express the
    defect; what still has to be asserted is that the tenant's key is filtered out BEFORE
    the fixed five are appended rather than overwritten where it sits, which is what keeps
    the summary last.
    """
    colliding = ExtractionSchemaSpec(
        version=1,
        fields=[
            ExtractionField(key="summary", label="Summary of complaint", type="text"),
            ExtractionField(key="callback_requested", label="Callback requested", type="bool"),
            ExtractionField(key="ward", label="Ward", type="text"),
        ],
    )

    schema = build_azure_response_schema(colliding)
    order = list(schema["properties"])

    assert len(order) == len(set(order)), order
    # The fixed definition wins, and it is not nullable — those five are what
    # `ExtractionOutput` always carries.
    assert schema["properties"]["summary"] == {"type": "string"}
    assert schema["properties"]["callback_requested"] == {"type": "boolean"}
    # The tenant's own field still leads, because generation is left-to-right and the
    # model must read for facts before it writes the summary that would anchor them.
    assert order.index("ward") < order.index("summary")


def test_every_extraction_field_type_has_an_azure_spelling() -> None:
    """A sixth member of `FieldType` would otherwise be a `KeyError` inside
    `_azure_property` — caught by `extract_call`'s ladder, reported as the word
    `KeyError`, and silently costing that tenant every assist. `validate_extraction`
    makes the same closure argument on its own match; this is the Azure half of it."""
    from typing import get_args

    from calevate_shared.extraction import FieldType

    assert set(get_args(FieldType)) == set(extraction_module._AZURE_TYPES), (
        "a field type exists with no Azure spelling, or a spelling with no field type"
    )


def test_the_schema_name_is_one_azure_will_accept() -> None:
    """Azure constrains the label to `^[a-zA-Z0-9_-]+$`. A name it refuses 400s every
    assist, and the failure would read as if the SCHEMA were wrong."""
    import re

    assert re.fullmatch(r"[a-zA-Z0-9_-]+", AZURE_SCHEMA_NAME), AZURE_SCHEMA_NAME
    assert len(AZURE_SCHEMA_NAME) <= 64


async def test_a_resource_that_refuses_strict_mode_degrades_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THE UNOBSERVED HALF. Structured Outputs is documented on both models we ship, and
    nobody has watched OUR resource accept it — so a refusal must cost the guarantee and
    NOT the answer. The user gets their assist on the weaker promise and an operator gets
    a named line saying which promise was in force.
    """
    azure = FakeAzure()
    azure.refuse_json_schema = True

    with caplog.at_level(logging.DEBUG):
        parsed = await azure.extractor().run(SPEC, REDACTED_TRANSCRIPT)

    assert parsed["caller_name"] == "Ravi", "the assist failed instead of degrading"
    assert len(azure.requests) == 2, "the weaker form was never tried"
    assert azure.body_of(0)["response_format"]["type"] == "json_schema"
    assert azure.body_of(1)["response_format"] == {"type": "json_object"}, (
        "the retry asked for something other than plain JSON mode"
    )

    record = next(
        (r for r in caplog.records if r.getMessage() == "azure_json_schema_unsupported"), None
    )
    assert record is not None, (
        "the guarantee silently dropped to best-effort JSON with nobody told — the one "
        f"outcome this degrade exists to rule out; got {[r.getMessage() for r in caplog.records]}"
    )
    assert record.levelno == logging.WARNING
    assert record.__dict__["deployment"] == DEPLOYMENT
    blob = "\n".join(f"{r.__dict__}" for r in caplog.records)
    assert VENDOR_BODY_MARKER not in blob
    assert API_KEY not in blob


async def test_a_400_that_is_not_about_the_schema_reports_the_original_refusal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The degrade triggers on ANY 400, deliberately: what this resource says when it
    refuses `json_schema` is the very payload nobody has observed, so a discriminator
    keyed on the error body would be a guess about the thing in doubt.

    The cost of that choice is one cheap extra round trip when a 400 means something else
    — and the requirement is that it stays a cost and never a wrong diagnosis. A 400 the
    weaker form earns too is reported as the refusal it is, and nothing claims the schema
    was unsupported.
    """
    azure = FakeAzure()
    azure.status = 400

    with caplog.at_level(logging.DEBUG), pytest.raises(httpx.HTTPStatusError):
        await azure.extractor().run(SPEC, REDACTED_TRANSCRIPT)

    assert len(azure.requests) == 2
    assert [r.getMessage() for r in caplog.records if r.getMessage().startswith("azure_")] == [
        "azure_request_refused"
    ], "a non-schema 400 was reported as a Structured Outputs problem"


async def test_the_recovery_still_catches_a_fenced_answer_on_the_degraded_path() -> None:
    """`_first_json_object` is belt beside braces, not dead weight. Under strict mode it
    is a no-op; on the degraded path it is the only thing between a model that wrapped
    its answer in prose and an empty extraction — which is why "the schema guarantees
    JSON now, delete the parser" is the wrong edit."""
    azure = FakeAzure()
    fenced = "Here you go:\n```json\n" + json.dumps(azure.answer) + "\n```\nHope that helps."
    azure.handler = lambda request: httpx.Response(  # type: ignore[method-assign]
        200, json={"choices": [{"message": {"content": fenced}}]}
    )

    parsed = await azure.extractor().run(SPEC, REDACTED_TRANSCRIPT)

    assert parsed["caller_name"] == "Ravi"
    assert parsed["intent"] == "enquiry"


# --- 5. a refusal is a diagnosis, not the word HTTPStatusError --------------------


async def test_a_404_names_the_deployment_because_that_is_what_a_404_means_here(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THE CONFIGURATION GATE, at the only moment anyone is looking at it.

    On this surface a 404 is not "no such model" — it is "no deployment by that ID on this
    resource", which is the one mistake the model/deployment split makes easy to walk
    into. Before this the whole diagnosis reached the log as the single word
    `HTTPStatusError`, indistinguishable from a 401, a 429 or a 503.
    """
    azure = FakeAzure()
    azure.status = 404

    with caplog.at_level(logging.DEBUG), pytest.raises(httpx.HTTPStatusError):
        await azure.extractor().run(SPEC, REDACTED_TRANSCRIPT)

    record = next(
        (r for r in caplog.records if r.getMessage() == "azure_deployment_not_found"), None
    )
    assert record is not None, (
        "a 404 left no named line — the one vendor answer this build cannot get any "
        f"other way arrived as {[r.getMessage() for r in caplog.records]}"
    )
    assert record.levelno == logging.ERROR
    assert record.__dict__["region"] == AZURE_LOCATION
    assert record.__dict__["model"] == AZURE_OPENAI_DEFAULT_MODEL
    assert record.__dict__["deployment"] == DEPLOYMENT
    assert "AZURE_OPENAI_MODEL" in record.__dict__["remedy"], (
        "the remedy does not name the wrong fix, which is the tempting one"
    )
    # Hard rule 6: error bodies quote the request, and the request is a transcript.
    blob = "\n".join(f"{r.__dict__}" for r in caplog.records)
    assert VENDOR_BODY_MARKER not in blob
    assert API_KEY not in blob


async def test_any_other_refusal_logs_the_status_rather_than_the_exception_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """401 is the key, 403 is the resource's network rules, 429 is quota, 503 is Azure.
    One word for all four is not a diagnosis, and the status is the whole of it."""
    for status in (401, 403, 429, 503):
        caplog.clear()
        azure = FakeAzure()
        azure.status = status

        with caplog.at_level(logging.DEBUG), pytest.raises(httpx.HTTPStatusError):
            await azure.extractor().run(SPEC, REDACTED_TRANSCRIPT)

        record = next(r for r in caplog.records if r.getMessage() == "azure_request_refused")
        assert record.__dict__["status"] == status
        assert record.__dict__["model"] == AZURE_OPENAI_DEFAULT_MODEL
        blob = "\n".join(f"{r.__dict__}" for r in caplog.records)
        assert VENDOR_BODY_MARKER not in blob, f"the vendor's error body reached the log: {blob}"
        assert API_KEY not in blob, "the key reached the log"


# --- 6. what the assist cost, in Azure's own count -------------------------------


async def test_the_assist_carries_azures_token_count_without_double_counting_details(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`record_ai_assist_usage` (D-137) needs `tokens_in`/`tokens_out` and the client is
    the only thing that can see them.

    THE ONE LINE THAT CHANGED SHAPE AT D-410. Vertex reported `thoughtsTokenCount`
    SEPARATELY from `candidatesTokenCount`, so the two had to be SUMMED or a reasoning
    model was under-metered. On this wire format `completion_tokens_details` is a
    BREAKDOWN of `completion_tokens`, so porting that line across would bill a tenant
    twice for the same tokens. The fake sends a `reasoning_tokens` block precisely so this
    assertion fails if anybody adds it.
    """
    azure = FakeAzure()
    _patch_client(monkeypatch, azure)

    result = await run_assist(SPEC, REDACTED_TRANSCRIPT)

    assert result.usage == extraction_module.TokenUsage(prompt_tokens=1_200, output_tokens=800)


async def test_a_body_with_no_usage_block_meters_nothing_rather_than_zero(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "We do not know what this cost" and "it was free" must not meter the same. Zero
    would give one tenant a silent free assist and move the platform brake by nothing."""
    azure = FakeAzure()
    azure.usage = None
    _patch_client(monkeypatch, azure)

    result = await run_assist(SPEC, REDACTED_TRANSCRIPT)

    assert result.capability.provider == AZURE_PROVIDER
    assert result.usage is None


async def test_a_disclosed_sarvam_fallback_reports_no_usage(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The units are `ai_assist_ktok_*` and they price the ASSIST leg, the one that spends
    Calevate's rupees. D-36 prices the Sarvam leg at zero, so metering a fallback would
    charge a tenant for the substitution they were told about."""
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    async def _sarvam_run(
        self: SarvamExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        return {"summary": "from sarvam", "sentiment": "neutral", "outcome_tag": "resolved"}

    async def _azure_run(
        self: AzureOpenAIExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        raise httpx.ConnectError("azure is unreachable")

    monkeypatch.setattr(SarvamExtractor, "run", _sarvam_run)
    monkeypatch.setattr(AzureOpenAIExtractor, "run", _azure_run)

    result = await run_assist(SPEC, REDACTED_TRANSCRIPT)

    assert result.capability.provider == SARVAM_PROVIDER
    assert result.usage is None


# --- 7. the ceiling reaches the runner -------------------------------------------


async def test_the_quota_verdict_reaches_the_runner_and_discloses_the_substitution(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-137 built the ceiling (`require_ai_assist`) and D-134 built the runner, and
    nothing joined them: `run_assist` called `assist_capability()` with no arguments, so a
    caller holding the verdict had no way to state it and the ceiling could not reach the
    one function that runs an assist. A gate with no door.

    The verdict is an ARGUMENT and not a read, because answering it needs a session and a
    tenant and this module has neither — the same split `assist_capability` already made.
    """
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    reached: list[str] = []

    async def _sarvam_run(
        self: SarvamExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        reached.append("sarvam")
        return {"summary": "from sarvam", "sentiment": "neutral", "outcome_tag": "resolved"}

    async def _azure_run(
        self: AzureOpenAIExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:  # pragma: no cover - reaching this IS the failure
        reached.append("azure")
        return {}

    monkeypatch.setattr(SarvamExtractor, "run", _sarvam_run)
    monkeypatch.setattr(AzureOpenAIExtractor, "run", _azure_run)

    result = await run_assist(SPEC, REDACTED_TRANSCRIPT, quota_exhausted=True)

    assert reached == ["sarvam"], "a tenant at its ceiling still spent Calevate's key"
    assert result.capability.fallback_reason == QUOTA_EXHAUSTED_REASON
    assert "used up" in (result.capability.disclosure or "")
    assert result.usage is None


async def test_a_tenant_at_its_ceiling_with_no_sarvam_key_is_refused_not_served(
    configured: Any,
) -> None:
    """The other end of the same ladder, and the one G-5's modal hangs off."""
    with pytest.raises(ProblemError) as caught:
        await run_assist(SPEC, REDACTED_TRANSCRIPT, quota_exhausted=True)

    assert caught.value.code == f"assist_{QUOTA_EXHAUSTED_REASON}"


# --- 8. nothing on this path is console-editable except the non-secrets -----------


def test_the_key_is_read_in_one_place_and_is_never_console_editable() -> None:
    """The half a reviewer waves through, proved by enumeration rather than by reading.

    `platform_config.managed_fields()` DERIVES the console's editable set from
    `Settings.model_fields`, so "is this credential safe from the console" is not a
    question about the constant — it is a question about whether a `Settings` field could
    stand in for it. Two things settle it, and both are mechanical:

      1. **Nothing on this path reads a setting except the five named below**, read out of
         the AST, so a new `settings.azure_something` fails this test on the commit that
         adds it rather than on the day someone edits it in a web form.
      2. **The key is read in exactly ONE function.** A second reader is what turns a
         credential from a thing held once into a thing that can end up in a URL.

    The resource, deployment and model ARE console-editable, deliberately: none is a
    secret, and the model is D-410's `gpt-4.1-mini` switch, which has to move without a
    deploy or it is not a switch.
    """
    import ast
    from pathlib import Path

    from apps.api.core.platform_config import managed_fields
    from calevate_shared.config import Settings

    source = Path(str(extraction_module.__file__)).read_text(encoding="utf-8")
    tree = ast.parse(source)

    read: set[str] = set()
    for node in ast.walk(tree):
        # `settings.<attr>` / `cfg.<attr>` / `get_settings().<attr>` — every shape this
        # repo spells a config read in.
        if not isinstance(node, ast.Attribute):
            continue
        base = node.value
        named = isinstance(base, ast.Name) and base.id in {"settings", "cfg"}
        called = isinstance(base, ast.Call) and getattr(base.func, "id", "") == "get_settings"
        if (named or called) and node.attr in Settings.model_fields:
            read.add(node.attr)

    assert read == {
        "sarvam_api_key",
        "azure_openai_resource",
        "azure_openai_api_key",
        "azure_openai_deployment",
        "azure_openai_model",
    }, read

    key_readers = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "azure_openai_api_key"
    ]
    assert len(key_readers) == 1, f"the key is read in {len(key_readers)} places: {key_readers}"

    managed = set(managed_fields())
    assert "azure_openai_api_key" not in managed, (
        "the Azure key became console-editable as a plaintext row"
    )
    assert "sarvam_api_key" not in managed
    assert read & managed <= {
        "azure_openai_resource",
        "azure_openai_deployment",
        "azure_openai_model",
    }, read & managed


def test_no_settings_field_can_stand_in_for_the_region() -> None:
    """`check_model_residency` check 3 catches a field whose NAME says region; this
    catches one whose name says nothing and whose value is the region anyway.

    THE REGION IS THE ONLY VALUE THIS ARGUMENT APPLIES TO, and the exclusion is worth
    stating because the obvious wider version of this test is wrong. A `Settings` field
    that happens to equal `AZURE_LOCATION` is a second, console-editable place the region
    can be spoken from — the exact shape D-410's residency section says the code can no
    longer prove from the endpoint. `AZURE_OPENAI_DEFAULT_MODEL` is the opposite case:
    `azure_openai_model` DEFAULTS to it deliberately, so a collision there is the design.
    What matters for the model is that the default is the constant BY REFERENCE and not a
    retyped copy, which the second assertion pins.
    """
    from calevate_shared.config import Settings

    defaults = {name: field.default for name, field in Settings.model_fields.items()}
    collisions = [name for name, default in defaults.items() if default == AZURE_LOCATION]
    assert collisions == [], f"Settings.{collisions} can stand in for AZURE_LOCATION"

    assert defaults["azure_openai_model"] is AZURE_OPENAI_DEFAULT_MODEL, (
        "the model default is a retyped string rather than the constant — two spellings "
        "of one default is how they drift apart"
    )


def test_every_frozen_constant_on_this_path_is_annotated_final() -> None:
    """`Final` is what mypy strict — a CI gate here — refuses to let anything rebind, so
    it is the annotation that turns a convention into an enforced one. Asserted from the
    AST because the runtime cannot see an annotation that was deleted."""
    import ast
    from pathlib import Path

    from calevate_shared import engine as engine_module

    expected = {
        engine_module: {
            "AZURE_LOCATION",
            "AZURE_OPENAI_DEFAULT_MODEL",
            "AZURE_OPENAI_MODELS",
        },
        extraction_module: {
            "GEMINI_EXTRACTION_DEFAULT",
            "ASSIST_QUOTA_ENFORCED",
            "NO_CREDENTIAL_REASON",
            "AZURE_PROVIDER",
        },
    }
    for module, names in expected.items():
        tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
        final_names = {
            node.target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and "Final" in ast.unparse(node.annotation)
        }
        assert names <= final_names, f"{module.__name__}: {names - final_names} lost `Final`"
