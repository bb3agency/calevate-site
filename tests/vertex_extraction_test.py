"""The Vertex client and the ONE availability policy (D-127; PLAN Parts 13 and 15).

WHY EVERY ASSERTION HERE IS ABOUT WHAT WE *ASKED*, NOT ABOUT WHAT WE STORED.
`asia-south1-aiplatform.googleapis.com` is egress-blocked from this environment and there
is no GCP project, so nothing in this file can talk to Google. A test that only checked
the rows we wrote afterwards would pass identically against a client pointed at
`us-central1`, at the AI Studio host, or at nothing at all — which is precisely the defect
class D-127 exists for. So the double RECORDS the request: host, path, `Authorization`
header shape, and body. The four facts that make this client correct rather than merely
working are all in that recording and nowhere else:

  1. the HOST carries `asia-south1`;
  2. the `locations/` PATH SEGMENT carries it too — a regional host with `locations/global`
     is the global endpoint wearing a regional hostname;
  3. authentication is `Authorization: Bearer <minted>` and there is **no `key=` query
     parameter anywhere**, because Vertex does not accept one and the previous client sent
     exactly that;
  4. the request carries a `responseSchema`, so valid JSON is a model-side guarantee
     rather than a parser's recovery.

THE SECOND HALF IS THE POLICY (G-6), and it is tested as a pure function of its inputs
because that is how it was written: `assist_capability()` takes the two facts nobody can
read from configuration (quota, and whether the provider just failed) as arguments, so all
six of its states are reachable without a database, a clock or a network.

Hard rule 6 throughout: no assertion here prints a transcript, and the RSA key below is
generated per run and never leaves the process.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.workers import extraction as extraction_module
from apps.workers import google_oauth
from apps.workers.extraction import (
    AI_STUDIO_KEY_REASON,
    GEMINI_PROVIDER,
    NO_CREDENTIAL_REASON,
    PROVIDER_UNAVAILABLE_REASON,
    QUOTA_EXHAUSTED_REASON,
    SARVAM_PROVIDER,
    VERTEX_SCOPE,
    AssistCapability,
    OfflineExtractor,
    SarvamExtractor,
    VertexGeminiExtractor,
    assist_capability,
    assist_unavailable,
    build_vertex_response_schema,
    get_extractor,
    run_assist,
    vertex_credentials,
    vertex_extractor,
    vertex_generate_url,
)
from apps.workers.google_oauth import parse_service_account
from calevate_shared.engine import (
    GEMINI_DEFAULT_LLM,
    GEMINI_MODEL_CONFIRMED_IN_REGION,
    VERTEX_LOCATION,
)
from calevate_shared.extraction import ExtractionField, ExtractionSchemaSpec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

SERVICE_ACCOUNT_EMAIL = "calevate-vertex@calevate-test.iam.gserviceaccount.com"
PROJECT = "calevate-test-1"

SPEC = ExtractionSchemaSpec(
    version=3,
    fields=[
        ExtractionField(key="caller_name", label="Caller name", type="text"),
        ExtractionField(
            key="intent",
            label="Intent",
            type="enum",
            enum_values=["book", "cancel", "enquiry"],
            description="What the caller rang about",
        ),
        ExtractionField(key="party_size", label="Party size", type="number"),
        ExtractionField(key="site_visit_interest", label="Site visit interest", type="bool"),
        ExtractionField(key="visit_on", label="Visit on", type="date"),
    ],
)

# Already through `redact()`: a phone number is `[REDACTED]`, which is what `run_assist`
# requires and what `transcript_turns.text_redacted` holds.
REDACTED_TRANSCRIPT = "caller: naa peru Ravi, 3BHK kavali\nagent: sari andi"

#: What a Vertex error body says, in this file. Google's real ones echo the request.
VENDOR_BODY_MARKER = "vendor-error-body-must-never-be-logged"


def _key_pair() -> str:
    """A throwaway RSA key. 2048 bits because that is what Google issues, and because a
    test that signed with something Google would reject would prove nothing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


_PRIVATE_PEM = _key_pair()


def _credential_json(**over: Any) -> str:
    payload: dict[str, Any] = {
        "type": "service_account",
        "client_email": SERVICE_ACCOUNT_EMAIL,
        "private_key": _PRIVATE_PEM,
        "private_key_id": "kid-1",
        "token_uri": google_oauth.TOKEN_URL,
    }
    payload.update(over)
    return json.dumps(payload)


def _account() -> google_oauth.ServiceAccount:
    account = parse_service_account(_credential_json())
    assert account is not None
    return account


class FakeVertex:
    """Google, as far as httpx is concerned. RECORDS what we actually sent.

    Deliberately not a model: it answers with the response SHAPE Vertex answers with and
    keeps the request objects, because the request is the artefact under test. Anything
    more would be testing the fake.
    """

    def __init__(self) -> None:
        self.token_requests: list[dict[str, list[str]]] = []
        self.generate_requests: list[httpx.Request] = []
        self.token_status = 200
        self.generate_status = 200
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
        #: Set to return a safety block — `candidates: []`, which is an ordinary response.
        self.blocked = False
        #: Vertex's own token count. `None` returns a body WITHOUT the block, which is
        #: how "we do not know what this cost" is spelled — distinct from zero.
        self.usage: dict[str, Any] | None = {
            "promptTokenCount": 1_200,
            "candidatesTokenCount": 300,
            "thoughtsTokenCount": 500,
            "totalTokenCount": 2_000,
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            self.token_requests.append(parse_qs(request.content.decode()))
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(
                200, json={"access_token": "ya29.vertex-token", "expires_in": 3599}
            )
        self.generate_requests.append(request)
        if self.generate_status != 200:
            # A distinctive marker, because Google's real error bodies QUOTE the request
            # — and the request on this path is a call transcript. The only way to prove
            # none of it reaches a log line is to make the body findable.
            return httpx.Response(
                self.generate_status, json={"error": {"message": VENDOR_BODY_MARKER}}
            )
        if self.blocked:
            return httpx.Response(200, json={"candidates": []})
        body: dict[str, Any] = {
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": json.dumps(self.answer)}]}}
            ]
        }
        if self.usage is not None:
            body["usageMetadata"] = self.usage
        return httpx.Response(200, json=body)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    @property
    def sent(self) -> httpx.Request:
        assert len(self.generate_requests) == 1, self.generate_requests
        return self.generate_requests[0]

    @property
    def body(self) -> dict[str, Any]:
        return dict(json.loads(self.sent.content))


@pytest.fixture(autouse=True)
def _clean_token_cache() -> Any:
    """The bearer cache is process-level on purpose (one token an hour, not one an
    assist). That makes it shared state between tests, so every test starts cold —
    otherwise the second test here would silently skip the token exchange."""
    google_oauth.reset_token_cache()
    yield
    google_oauth.reset_token_cache()


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> Any:
    """A deployment that holds a Vertex credential and no Sarvam key."""
    settings = get_settings()
    monkeypatch.setattr(settings, "gcp_project_id", PROJECT, raising=False)
    monkeypatch.setattr(settings, "gcp_service_account_json", _credential_json(), raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", None, raising=False)
    return settings


# --- 1. the request. host, path, auth, body ---------------------------------------


async def test_the_request_goes_to_vertex_asia_south1_with_a_bearer_and_no_api_key() -> None:
    """THE test. Four independent facts about the request we send, in one place.

    Each one alone is the whole posture: a global host, a `locations/global` path, an
    `?key=` query parameter or a missing schema each turns this client back into the one
    D-127 disqualified, and none of them is visible in the rows we write afterwards.
    """
    google = FakeVertex()
    extractor = VertexGeminiExtractor(_account(), PROJECT, client=google.client())

    await extractor.run(SPEC, REDACTED_TRANSCRIPT)

    sent = google.sent
    assert sent.url.host == f"{VERTEX_LOCATION}-aiplatform.googleapis.com", sent.url
    assert sent.url.path == (
        f"/v1/projects/{PROJECT}/locations/{VERTEX_LOCATION}"
        f"/publishers/google/models/{GEMINI_DEFAULT_LLM}:generateContent"
    ), sent.url.path
    # The path carries the region SEPARATELY from the host, and both have to be right.
    assert f"locations/{VERTEX_LOCATION}" in sent.url.path
    assert "locations/global" not in sent.url.path

    # The previous client authenticated with `params={"key": ...}`. Vertex does not accept
    # one, and a query string is where a credential ends up in an access log — so this is
    # asserted BEFORE the header, or a client that reverted to a key would fail with a
    # KeyError about the missing header instead of a sentence about the key.
    assert not sent.url.params, f"a credential in the query string: {sent.url.params}"
    assert sent.headers.get("Authorization") == "Bearer ya29.vertex-token", (
        "Vertex takes an OAuth2 bearer and nothing else; this request carried "
        f"{sorted(sent.headers)}"
    )

    assert sent.method == "POST"
    config = google.body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config.get("responseSchema", {}).get("type") == "OBJECT", (
        "no model-side response schema — this path is back to fence-stripping a model's "
        "prose, which is a recovery and not a guarantee"
    )
    assert config["temperature"] == 0


async def test_the_bearer_is_an_rfc7523_assertion_scoped_to_cloud_platform() -> None:
    """The token half of the request, which the generate call's header cannot show.

    A bearer minted for the Sheets scope would be accepted by our own code and refused by
    Vertex with a 403 that names neither the scope nor the cache it came from — which is
    exactly why `google_oauth` keys its cache on (account, KEY, scope) rather than on the
    account. `tests/google_oauth_test.py` owns the cache's own properties.
    """
    google = FakeVertex()
    extractor = VertexGeminiExtractor(_account(), PROJECT, client=google.client())

    await extractor.run(SPEC, REDACTED_TRANSCRIPT)

    assert len(google.token_requests) == 1
    form = google.token_requests[0]
    assert form["grant_type"] == [google_oauth.JWT_BEARER_GRANT]
    import jwt

    claims = jwt.decode(
        form["assertion"][0],
        options={"verify_signature": False},
        audience=google_oauth.TOKEN_URL,
    )
    assert claims["scope"] == VERTEX_SCOPE
    assert claims["iss"] == SERVICE_ACCOUNT_EMAIL
    # `aud` is the TOKEN endpoint, not the model endpoint: a captured assertion cannot be
    # replayed against Vertex itself.
    assert claims["aud"] == google_oauth.TOKEN_URL


async def test_one_bearer_serves_many_assists_and_a_second_scope_gets_its_own() -> None:
    """Tokens expire in about an hour and a worker outlives that, so the cache is not
    optional — but a cache keyed on the ACCOUNT alone would hand the Vertex caller a
    Sheets-scoped token. Both halves, because the fix for the first created the second."""
    google = FakeVertex()
    client = google.client()
    extractor = VertexGeminiExtractor(_account(), PROJECT, client=client)

    await extractor.run(SPEC, REDACTED_TRANSCRIPT)
    google.generate_requests.clear()
    await extractor.run(SPEC, REDACTED_TRANSCRIPT)

    assert len(google.token_requests) == 1, "a second assist re-minted the bearer"

    await google_oauth.access_token(
        client, _account(), scope="https://www.googleapis.com/auth/spreadsheets"
    )
    assert len(google.token_requests) == 2, "a different scope reused the cached bearer"
    assert google.token_requests[1]["assertion"], google.token_requests


async def test_a_refused_token_exchange_costs_the_fields_and_never_the_call() -> None:
    """`google_oauth.access_token` returns None rather than raising so a credential
    cannot land in a traceback. That must still reach `extract_call`'s error ladder —
    silently returning `{}` would file an empty extraction as a SUCCESS."""
    google = FakeVertex()
    google.token_status = 401
    extractor = VertexGeminiExtractor(_account(), PROJECT, client=google.client())

    with pytest.raises(ValueError, match="vertex_token_unavailable"):
        await extractor.run(SPEC, REDACTED_TRANSCRIPT)
    assert google.generate_requests == [], "we called the model without a bearer"


# --- 2. the response schema -------------------------------------------------------


def test_the_response_schema_describes_the_agents_own_fields() -> None:
    """A model-side schema is a stronger guarantee than a parser, and it is only that if
    it is built from the SPEC rather than from a template."""
    schema = build_vertex_response_schema(SPEC)
    properties = schema["properties"]

    assert properties["caller_name"] == {"type": "STRING", "nullable": True}
    assert properties["party_size"]["type"] == "NUMBER"
    assert properties["site_visit_interest"]["type"] == "BOOLEAN"
    # An enum's members are constrained at the model rather than rejected at the
    # validator, which is where `test_an_out_of_enum_value_never_reaches_the_crm` has to
    # catch them for every other provider.
    assert properties["intent"]["enum"] == ["book", "cancel", "enquiry"]
    assert properties["intent"]["description"] == "What the caller rang about"
    # A date is a STRING, deliberately: `format: "date"` would make the model invent a
    # calendar date for "repu udayam" in order to satisfy the type.
    assert properties["visit_on"]["type"] == "STRING"

    # Only the five fixed keys are required. Forcing a client's field to be present is
    # asking the model to fabricate it, and a phone number one digit wrong is the worst
    # output this system can produce.
    assert set(schema["required"]) == {
        "summary",
        "sentiment",
        "outcome_tag",
        "out_of_scope",
        "callback_requested",
    }
    for key in SPEC.fields:
        assert properties[key.key]["nullable"] is True
    # Generation is left-to-right: facts before the summary that would anchor them.
    assert schema["propertyOrdering"][: len(SPEC.fields)] == [f.key for f in SPEC.fields]


async def test_a_safety_block_is_an_ordinary_response_and_not_a_crash() -> None:
    """`candidates: []` is documented behaviour, not an exception. Indexing it blindly is
    the IndexError that once failed a whole post-call job — losing the call to keep the
    fields."""
    google = FakeVertex()
    google.blocked = True
    extractor = VertexGeminiExtractor(_account(), PROJECT, client=google.client())

    assert await extractor.run(SPEC, REDACTED_TRANSCRIPT) == {}


# --- 3. G-7: the first post-call extraction never reaches Gemini -------------------


def test_get_extractor_cannot_return_gemini_even_with_a_credential(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE G-2 REGRESSION. `pipeline.py` hands `get_extractor()` the RAW transcript.

    Before D-127 this function returned a Gemini client whenever a Gemini key was present
    and a Sarvam key was not — so one absent environment variable sent raw caller PII to
    Google. The precedence is not merely Sarvam-FIRST any more; Gemini is not in the
    ladder at all.
    """
    assert vertex_credentials() is not None, "the fixture did not configure Vertex"
    assert isinstance(get_extractor(), OfflineExtractor)

    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)
    assert isinstance(get_extractor(), SarvamExtractor)


def test_the_capability_constant_is_the_greppable_form_of_g7() -> None:
    """`check_docs_drift` §5 judges prose that quotes this name by value. It is only worth
    minting if it says what the code does, so this is the tie between the two."""
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


# --- 4. G-6: one place decides, and a fallback is always disclosed -----------------


def test_a_configured_deployment_answers_with_gemini_and_discloses_nothing(
    configured: Any,
) -> None:
    """Nothing was substituted, so there is nothing to disclose. A capability that carried
    a disclosure on the happy path would train every surface to ignore the field."""
    capability = assist_capability()
    assert capability.available is True
    assert capability.provider == GEMINI_PROVIDER
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
    """The three reasons are not decoration: a client at their ceiling and a client
    hitting a Google outage need different sentences, and a surface that saw only
    `available=False` would show them the same one."""
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    capability = assist_capability(**kwargs)

    assert capability.available is True
    assert capability.provider == SARVAM_PROVIDER
    assert capability.fallback_reason == expected
    assert capability.disclosure is not None
    assert "Sarvam" in capability.disclosure


def test_an_unconfigured_deployment_falls_back_and_an_ai_studio_key_says_which(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`gemini_api_key` is not a field that silently does nothing. It is the difference
    between "install a credential" and "the credential you installed opens the wrong
    door", and an operator who gets the first sentence goes and checks their typing."""
    settings = get_settings()
    monkeypatch.setattr(settings, "gcp_project_id", None, raising=False)
    monkeypatch.setattr(settings, "gcp_service_account_json", None, raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", None, raising=False)

    assert assist_capability().fallback_reason == NO_CREDENTIAL_REASON

    monkeypatch.setattr(settings, "gemini_api_key", "AIza-test", raising=False)
    capability = assist_capability()
    assert capability.fallback_reason == AI_STUDIO_KEY_REASON
    assert capability.provider == SARVAM_PROVIDER


def test_a_malformed_key_is_unconfigured_rather_than_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key that is present and unreadable is an operator error. It must not raise inside
    a worker whose next log line would print it, and it must not be reported as "no
    credential" WITHOUT a log an operator can act on."""
    settings = get_settings()
    monkeypatch.setattr(settings, "gcp_project_id", PROJECT, raising=False)
    monkeypatch.setattr(settings, "gcp_service_account_json", "{not json", raising=False)

    assert vertex_credentials() is None
    assert vertex_extractor() is None


def test_with_nothing_configured_it_refuses_with_something_a_user_can_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refusal, not a silent empty state (§52). `OfflineExtractor` is deliberately NOT in
    the ladder: substituting a deterministic literal-text reader for "re-summarise this
    call" would be substituting a different KIND of thing while claiming to substitute a
    model."""
    settings = get_settings()
    monkeypatch.setattr(settings, "gcp_project_id", None, raising=False)
    monkeypatch.setattr(settings, "gcp_service_account_json", None, raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", None, raising=False)

    capability = assist_capability()
    assert capability.available is False
    assert capability.reason == NO_CREDENTIAL_REASON
    assert capability.provider is None

    problem = assist_unavailable(capability)
    assert problem.code == "assist_no_credential"
    assert "GCP_PROJECT_ID" in (problem.remediation or "")

    quota = assist_unavailable(AssistCapability(available=False, reason=QUOTA_EXHAUSTED_REASON))
    assert "Add credit" in (quota.remediation or "")
    assert quota.remediation != problem.remediation, (
        "two different reasons produced one sentence — the reason codes buy nothing"
    )


async def test_a_gemini_failure_falls_back_to_sarvam_and_the_answer_says_so(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole of G-6 in one path: Vertex fails, Sarvam answers, and the RESULT carries
    the sentence. A silent fallback quietly changes output quality with nobody told."""
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    sarvam_calls: list[str] = []

    async def _sarvam_run(
        self: SarvamExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        sarvam_calls.append(transcript)
        return {"summary": "from sarvam", "sentiment": "neutral", "outcome_tag": "resolved"}

    async def _vertex_run(
        self: VertexGeminiExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        raise httpx.ConnectError("vertex is unreachable")

    monkeypatch.setattr(SarvamExtractor, "run", _sarvam_run)
    monkeypatch.setattr(VertexGeminiExtractor, "run", _vertex_run)

    result = await run_assist(SPEC, REDACTED_TRANSCRIPT)

    assert sarvam_calls == [REDACTED_TRANSCRIPT]
    assert result.capability.provider == SARVAM_PROVIDER
    assert result.capability.fallback_reason == PROVIDER_UNAVAILABLE_REASON
    assert result.capability.disclosure is not None
    assert result.output.summary == "from sarvam"


async def test_a_gemini_failure_with_no_sarvam_key_refuses_rather_than_returning_nothing(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The half a naive implementation gets wrong. `extract_call` swallows a provider
    failure into `errors["_model"]` so a post-call pipeline never loses a call over one —
    which is right there and wrong here, where a user is waiting and would be handed a
    blank answer that looks like a successful one."""

    async def _vertex_run(
        self: VertexGeminiExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        raise httpx.ConnectError("vertex is unreachable")

    monkeypatch.setattr(VertexGeminiExtractor, "run", _vertex_run)

    with pytest.raises(ProblemError) as caught:
        await run_assist(SPEC, REDACTED_TRANSCRIPT)

    assert caught.value.code == f"assist_{PROVIDER_UNAVAILABLE_REASON}"
    assert "did not answer" in (caught.value.remediation or "")


async def test_the_happy_path_runs_on_vertex_and_returns_validated_fields(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end through the real client, so the URL under test is the one a user's
    assist would actually reach — and the schema-validated fields come back."""
    google = FakeVertex()
    monkeypatch.setattr(
        extraction_module,
        "VertexGeminiExtractor",
        lambda account, project: VertexGeminiExtractor(account, project, client=google.client()),
    )

    result = await run_assist(SPEC, REDACTED_TRANSCRIPT)

    assert result.capability.provider == GEMINI_PROVIDER
    assert result.capability.disclosure is None
    assert result.output.data["caller_name"] == "Ravi"
    assert result.output.data["intent"] == "enquiry"
    assert result.output.valid is True
    assert google.sent.url.host.startswith(VERTEX_LOCATION)


# --- 5. the URL builder, judged directly ------------------------------------------


def test_the_url_builder_pins_both_halves_from_one_constant() -> None:
    """`scripts/check_model_residency.py` proves this from the AST; this proves it from
    the VALUE, because the two can be right about different things — the guard reads what
    the source says and this reads what a caller gets."""
    url = vertex_generate_url("calevate-prod", "gemini-x")
    assert url == (
        f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/v1/projects/calevate-prod"
        f"/locations/{VERTEX_LOCATION}/publishers/google/models/gemini-x:generateContent"
    )
    assert "generativelanguage.googleapis.com" not in url
    assert url.count(VERTEX_LOCATION) == 2, "the region appears in the host AND the path"


# --- 6. the response schema, and the shapes a client can author -------------------


def test_a_client_field_named_like_a_fixed_one_does_not_duplicate_the_ordering() -> None:
    """`ExtractionField.key` permits every one of the five fixed keys, and "Summary of
    complaint" is an ordinary column for a client to author with `summary` as its key.

    `properties` always resolved the collision correctly — `.update()` lets the fixed
    definition win, and the fixed five are what `ExtractionOutput` promises. The ORDER
    list did not: it named the colliding key twice, and a `propertyOrdering` naming one
    property two times is a malformed OpenAPI object. So one client's choice of field
    name turned every assist for that tenant into a 400 that `extract_call` could only
    report as the word `HTTPStatusError`.
    """
    colliding = ExtractionSchemaSpec(
        version=1,
        fields=[
            ExtractionField(key="summary", label="Summary of complaint", type="text"),
            ExtractionField(key="callback_requested", label="Callback requested", type="bool"),
            ExtractionField(key="ward", label="Ward", type="text"),
        ],
    )

    schema = build_vertex_response_schema(colliding)
    ordering = schema["propertyOrdering"]

    assert len(ordering) == len(set(ordering)), ordering
    assert set(ordering) == set(schema["properties"]), (
        "propertyOrdering and properties disagree about which keys exist"
    )
    # The fixed definition wins, and it is not nullable — those five are `required`.
    assert schema["properties"]["summary"] == {"type": "STRING"}
    assert "nullable" not in schema["properties"]["callback_requested"]
    # The tenant's own field still leads, because generation is left-to-right and the
    # model must read for facts before it writes the summary that would anchor them.
    assert ordering.index("ward") < ordering.index("summary")


def test_every_extraction_field_type_has_a_vertex_spelling() -> None:
    """A sixth member of `FieldType` would otherwise be a `KeyError` inside
    `_vertex_property` — caught by `extract_call`'s ladder, reported as the word
    `KeyError`, and silently costing that tenant every assist. `validate_extraction`
    makes the same closure argument on its own match; this is the Vertex half of it."""
    from typing import get_args

    from calevate_shared.extraction import FieldType

    assert set(get_args(FieldType)) == set(extraction_module._VERTEX_TYPES), (
        "a field type exists with no Vertex spelling, or a spelling with no field type"
    )


# --- 7. a 404 is the answer to the one thing nobody could verify ------------------


async def test_a_404_names_the_region_the_model_and_the_flag_that_was_never_confirmed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """THE GATE, at the only moment anyone is looking at it.

    `check_model_residency` can prove the URL is regional. Nothing in this repository can
    prove `asia-south1` SERVES `GEMINI_DEFAULT_LLM` — `GEMINI_MODEL_CONFIRMED_IN_REGION`
    is the greppable form of that, and a 404 from a host that unambiguously belongs to
    our project is the answer arriving. Before this the whole diagnosis reached the log
    as the single word `HTTPStatusError`, indistinguishable from a 401, a 429 or a 503.
    """
    google = FakeVertex()
    google.generate_status = 404
    extractor = VertexGeminiExtractor(_account(), PROJECT, client=google.client())

    with caplog.at_level(logging.DEBUG), pytest.raises(httpx.HTTPStatusError):
        await extractor.run(SPEC, REDACTED_TRANSCRIPT)

    record = next(
        (r for r in caplog.records if r.getMessage() == "vertex_model_not_served_in_region"), None
    )
    assert record is not None, (
        "a 404 from Vertex left no named line — the one vendor answer this build cannot "
        f"get any other way arrived as {[r.getMessage() for r in caplog.records]}"
    )
    assert record.levelno == logging.ERROR
    assert record.__dict__["region"] == VERTEX_LOCATION
    assert record.__dict__["model"] == GEMINI_DEFAULT_LLM
    assert record.__dict__["confirmed_in_region"] is GEMINI_MODEL_CONFIRMED_IN_REGION
    assert "locations/global" in record.__dict__["remedy"], (
        "the remedy does not name the wrong fix, which is the tempting one"
    )
    # Hard rule 6: Google's error bodies quote the request, and the request is a
    # transcript. Nothing from the body may reach any record.
    assert VENDOR_BODY_MARKER not in "\n".join(f"{r.__dict__}" for r in caplog.records)


async def test_any_other_refusal_logs_the_status_rather_than_the_exception_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """401 is the key, 403 is the IAM grant, 429 is quota, 503 is Google. One word for all
    four is not a diagnosis, and the status is the whole of it."""
    for status in (401, 403, 429, 503):
        caplog.clear()
        google = FakeVertex()
        google.generate_status = status
        extractor = VertexGeminiExtractor(_account(), PROJECT, client=google.client())

        with caplog.at_level(logging.DEBUG), pytest.raises(httpx.HTTPStatusError):
            await extractor.run(SPEC, REDACTED_TRANSCRIPT)

        record = next(r for r in caplog.records if r.getMessage() == "vertex_request_refused")
        assert record.__dict__["status"] == status
        assert record.__dict__["model"] == GEMINI_DEFAULT_LLM
        blob = "\n".join(f"{r.__dict__}" for r in caplog.records)
        assert VENDOR_BODY_MARKER not in blob, f"the vendor's error body reached the log: {blob}"


# --- 8. what the assist cost, in Vertex's own count -------------------------------


async def test_the_assist_carries_vertexs_token_count_with_thinking_folded_into_output(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`record_ai_assist_usage` (D-137) needs `tokens_in`/`tokens_out` and there was
    nowhere to get them: the client read `candidates` and threw the rest of the body away,
    so the meter D-137 built could not be filled by the runner D-134 built.

    THOUGHTS COUNT AS OUTPUT. Every Gemini generation this repo has shipped bills thinking
    tokens at the output rate — 2.5 Flash as much as the 3.x tier it replaced — and
    reports them separately from `candidatesTokenCount`, so counting only the latter
    under-meters exactly the calls that cost the most — a structured-output request to a
    reasoning model spends most of its budget there.
    """
    google = FakeVertex()
    monkeypatch.setattr(
        extraction_module,
        "VertexGeminiExtractor",
        lambda account, project: VertexGeminiExtractor(account, project, client=google.client()),
    )

    result = await run_assist(SPEC, REDACTED_TRANSCRIPT)

    assert result.usage == extraction_module.TokenUsage(prompt_tokens=1_200, output_tokens=800)
    # The schema is INPUT and is counted in that 1,200 — which is the reason the number
    # comes from Vertex rather than from anything this repo could add up.
    assert "responseSchema" in google.body["generationConfig"]


async def test_a_body_with_no_usage_block_meters_nothing_rather_than_zero(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "We do not know what this cost" and "it was free" must not meter the same. Zero
    would give one tenant a silent free assist and move the platform brake by nothing."""
    google = FakeVertex()
    google.usage = None
    monkeypatch.setattr(
        extraction_module,
        "VertexGeminiExtractor",
        lambda account, project: VertexGeminiExtractor(account, project, client=google.client()),
    )

    result = await run_assist(SPEC, REDACTED_TRANSCRIPT)

    assert result.capability.provider == GEMINI_PROVIDER
    assert result.usage is None


async def test_a_disclosed_sarvam_fallback_reports_no_usage(
    configured: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The units are `ai_assist_ktok_*` and they price GEMINI, the leg that spends
    Calevate's rupees. D-36 prices the Sarvam leg at zero, so metering a fallback would
    charge a tenant for the substitution they were told about."""
    monkeypatch.setattr(get_settings(), "sarvam_api_key", "sk-test", raising=False)

    async def _sarvam_run(
        self: SarvamExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        return {"summary": "from sarvam", "sentiment": "neutral", "outcome_tag": "resolved"}

    async def _vertex_run(
        self: VertexGeminiExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:
        raise httpx.ConnectError("vertex is unreachable")

    monkeypatch.setattr(SarvamExtractor, "run", _sarvam_run)
    monkeypatch.setattr(VertexGeminiExtractor, "run", _vertex_run)

    result = await run_assist(SPEC, REDACTED_TRANSCRIPT)

    assert result.capability.provider == SARVAM_PROVIDER
    assert result.usage is None


# --- 9. the ceiling reaches the runner --------------------------------------------


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

    async def _vertex_run(
        self: VertexGeminiExtractor, spec: ExtractionSchemaSpec, transcript: str
    ) -> dict[str, Any]:  # pragma: no cover - reaching this IS the failure
        reached.append("gemini")
        return {}

    monkeypatch.setattr(SarvamExtractor, "run", _sarvam_run)
    monkeypatch.setattr(VertexGeminiExtractor, "run", _vertex_run)

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


# --- 10. nothing about this path is console-editable except the project ------------


def test_only_the_project_id_is_console_editable_on_the_whole_vertex_path() -> None:
    """The half a reviewer waves through, proved by enumeration rather than by reading.

    `platform_config.managed_fields()` DERIVES the console's editable set from
    `Settings.model_fields`, so "is this constant safe from the console" is not a question
    about the constant — it is a question about whether a `Settings` field could stand in
    for it. Two things settle it, and both are mechanical:

      1. **Nothing on this path reads a setting except the four named below.** The set is
         read out of the AST, so a new `settings.vertex_something` fails this test on the
         commit that adds it rather than on the day someone edits it in a web form.
      2. **No `Settings` field, managed or not, DEFAULTS to any of the frozen values.**
         `check_model_residency` check 3 catches a field whose NAME says region; this
         catches one whose name says nothing and whose value is the region anyway.

    `gcp_project_id` IS console-editable, deliberately: it is not a secret, it appears in
    every URL, and it is the value an operator gets wrong first.
    """
    import ast
    from pathlib import Path

    from apps.api.core.platform_config import managed_fields
    from calevate_shared.config import Settings

    read: set[str] = set()
    for module in (extraction_module, google_oauth):
        source = Path(str(module.__file__)).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            # `settings.<attr>` / `cfg.<attr>` / `get_settings().<attr>` — every shape
            # this repo spells a config read in.
            if not isinstance(node, ast.Attribute):
                continue
            base = node.value
            named = isinstance(base, ast.Name) and base.id in {"settings", "cfg"}
            called = isinstance(base, ast.Call) and getattr(base.func, "id", "") == "get_settings"
            if (named or called) and node.attr in Settings.model_fields:
                read.add(node.attr)

    assert read == {
        "sarvam_api_key",
        "gemini_api_key",
        "gcp_project_id",
        "gcp_service_account_json",
    }, read

    managed = set(managed_fields())
    assert read & managed == {"gcp_project_id"}, (
        "a credential on this path became console-editable as a plaintext row"
    )

    # Values, not names — `check_model_residency` check 3 already catches a field whose
    # NAME says region. `GEMINI_MODEL_CONFIRMED_IN_REGION` is deliberately absent: it is
    # a boolean, every boolean setting defaults to False, and a value check on one would
    # pass or fail for reasons that have nothing to do with it. Point 1 above is what
    # covers it — nothing on this path reads a fifth setting, so no console field can
    # stand in for a flag the code never looks up.
    frozen: dict[str, object] = {
        "VERTEX_LOCATION": VERTEX_LOCATION,
        "GEMINI_DEFAULT_LLM": GEMINI_DEFAULT_LLM,
        "VERTEX_SCOPE": VERTEX_SCOPE,
        "TOKEN_URL": google_oauth.TOKEN_URL,
        "JWT_BEARER_GRANT": google_oauth.JWT_BEARER_GRANT,
        "TOKEN_TTL_S": google_oauth.TOKEN_TTL_S,
        "TOKEN_REFRESH_SKEW_S": google_oauth.TOKEN_REFRESH_SKEW_S,
    }
    defaults = {name: field.default for name, field in Settings.model_fields.items()}
    for constant, value in frozen.items():
        collisions = [name for name, default in defaults.items() if default == value]
        assert collisions == [], f"Settings.{collisions} can stand in for {constant}"


def test_every_frozen_constant_on_this_path_is_annotated_final() -> None:
    """`Final` is what mypy strict — a CI gate here — refuses to let anything rebind, so
    it is the annotation that turns a convention into an enforced one. Asserted from the
    AST because the runtime cannot see an annotation that was deleted."""
    import ast
    from pathlib import Path

    from calevate_shared import engine as engine_module

    expected = {
        engine_module: {
            "VERTEX_LOCATION",
            "GEMINI_DEFAULT_LLM",
            # The retirement date is on this path for the same reason the model is: the
            # founder's `asia-south1` decision made BRD R-04 live for this leg, and a
            # deadline something can rebind is a deadline that moves under whoever is
            # inconvenienced by it.
            "GEMINI_DEFAULT_LLM_RETIRES",
            "GEMINI_MODEL_CONFIRMED_IN_REGION",
        },
        extraction_module: {"VERTEX_SCOPE", "GEMINI_EXTRACTION_DEFAULT", "ASSIST_QUOTA_ENFORCED"},
        google_oauth: {"TOKEN_URL", "JWT_BEARER_GRANT", "TOKEN_TTL_S", "TOKEN_REFRESH_SKEW_S"},
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


def test_the_ai_studio_key_is_read_in_exactly_one_place_and_only_for_the_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`gemini_api_key`'s comment says it is read once, to turn "no credential" into "the
    WRONG KIND of credential". That comment used to ALSO claim step one of hard rule 8's
    two-step was done — "nothing in the tree does [read it]" — three lines above saying it
    is read in exactly one place, which cannot both be true.

    The field is kept permanently and this is what makes the surviving half checkable: one
    reader, in the selector, and no URL, header or query parameter anywhere can carry the
    value. A second reader is what would turn this from an error message into a
    credential, and D-127 disqualifies the endpoint it opens.
    """
    import ast
    from pathlib import Path

    readers: list[str] = []
    for path in sorted((Path(__file__).resolve().parents[1] / "apps").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr == "gemini_api_key":
                readers.append(f"{path.name}:{node.lineno}")

    assert len(readers) == 1, readers
    assert readers[0].startswith("extraction.py"), readers

    # And the one read only ever chooses a reason code.
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "AIza-an-ai-studio-key", raising=False)
    monkeypatch.setattr(settings, "gcp_project_id", None, raising=False)
    monkeypatch.setattr(settings, "gcp_service_account_json", None, raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)

    capability = assist_capability()

    assert capability.available is False
    assert capability.reason == AI_STUDIO_KEY_REASON
    problem = assist_unavailable(capability)
    assert "AI Studio" in (problem.remediation or "")
    assert "AIza-an-ai-studio-key" not in f"{problem.detail} {problem.remediation}"
