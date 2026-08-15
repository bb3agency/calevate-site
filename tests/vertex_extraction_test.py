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
from calevate_shared.engine import GEMINI_DEFAULT_LLM, VERTEX_LOCATION
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
            return httpx.Response(self.generate_status, json={"error": {"message": "no"}})
        if self.blocked:
            return httpx.Response(200, json={"candidates": []})
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"role": "model", "parts": [{"text": json.dumps(self.answer)}]}}
                ]
            },
        )

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
    exactly why `google_oauth` keys its cache on (account, scope) rather than on account.
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
    assert extraction_module.ASSIST_QUOTA_ENFORCED is False


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
