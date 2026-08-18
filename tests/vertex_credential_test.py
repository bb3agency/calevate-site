"""The in-call LLM bearer's rotation (D-404) — every refusal, by name.

WHY THIS FILE IS MOSTLY REFUSALS. The happy path here is three HTTP calls and a log line;
it is the arms that DO NOT install a credential that carry the design, because each of
them is a way the leg dies quietly. A refresher that installs a 1-hour token, or a token
that is already expired, or one that reaches an engine which never wanted it, reports
success and then fails hours later on a live phone call — at which point the symptom is a
caller hearing silence and the cause is invisible. So every arm below asserts THREE
things: nothing was installed, something was PAGED, and the outcome string names which
arm it was.

WHAT IS DRIVEN AND WHAT IS FAKED. Real `httpx` transports carrying real Google-shaped
bodies, and the REAL engine adapter (`FakeEngine`), because the two things most likely to
be wrong are the protobuf `Duration`/`Timestamp` encodings — `lifetime` is `"43200s"` and
not `43200`, `expireTime` is RFC 3339 — and the capability gate on the engine side. A
mocked engine would have agreed with whatever the caller did.

HARD RULE 6'S NEIGHBOUR: `test_no_credential_reaches_a_log_record` drives a real
`logging` handler over the whole successful path. A bearer in a log line is the failure
this module's entire docstring is about, and it is the one a reviewer cannot see by
reading.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from apps.api.core.settings import get_settings
from apps.api.engine.fake import (
    DEFAULT_FAKE_CAPABILITIES,
    EXTERNAL_DEPLOYMENT_CAPABILITIES,
    FakeEngine,
)
from apps.workers import vertex_credential
from apps.workers.google_oauth import reset_token_cache
from apps.workers.vertex_credential import (
    MIN_GRANTED_LIFETIME_S,
    REFRESH_INTERVAL_HOURS,
    TOKEN_LIFETIME,
    TOKEN_LIFETIME_S,
    mint_in_call_bearer,
    refresh_in_call_llm_credential,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

PROJECT = "calevate-voice"
EMAIL = "calevate-vertex@calevate-voice.iam.gserviceaccount.com"
#: The value a passing rotation must put in the engine. Distinctive so a test that finds
#: it somewhere it should not be (a log line) can say so.
BEARER = "ya29.rotated-in-call-bearer-DO-NOT-LOG"

#: Bound at IMPORT, before any test replaces `httpx.AsyncClient`. `_wire` patches that
#: name so the job's own `async with httpx.AsyncClient(...)` reaches the fake transport —
#: and `FakeGoogle.client()` would then call the patch and recurse forever. Capturing the
#: real class here is what keeps the patch one level deep.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _service_account_json() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "client_email": EMAIL,
            "private_key": pem,
            "private_key_id": "key-1",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


class FakeGoogle:
    """Both Google endpoints this flow touches, recording what it was asked for.

    TWO endpoints and not one, because the whole point of the design is that the JWT-bearer
    token (capped at an hour) is spent on ONE call to the IAM Credentials API, which is the
    only thing that can issue a longer one. A fake with a single endpoint would have hidden
    the two-step entirely.
    """

    def __init__(self, *, granted_seconds: int = TOKEN_LIFETIME_S) -> None:
        self.granted_seconds = granted_seconds
        self.mint_requests: list[dict[str, Any]] = []
        self.token_status = 200
        self.mint_status = 200
        #: None ⇒ omit `expireTime` entirely, which the proto says never happens and which
        #: the code must therefore refuse rather than paper over.
        self.expire_override: str | object | None = object()

    async def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "ya29.assertion", "expires_in": 3599})
        assert request.url.host == "iamcredentials.googleapis.com", request.url
        body = json.loads(request.content.decode())
        self.mint_requests.append(
            {"url": str(request.url), "body": body, "auth": request.headers.get("authorization")}
        )
        if self.mint_status != 200:
            return httpx.Response(self.mint_status, json={"error": {"message": EMAIL}})
        expiry = datetime.now(UTC) + timedelta(seconds=self.granted_seconds)
        payload: dict[str, Any] = {"accessToken": BEARER}
        if isinstance(self.expire_override, object) and self.expire_override.__class__ is object:
            payload["expireTime"] = expiry.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif self.expire_override is not None:
            payload["expireTime"] = self.expire_override
        return httpx.Response(200, json=payload)

    def client(self) -> httpx.AsyncClient:
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(self.handler))


class Pages:
    """Every `alert()` this module raised, so a test can assert one was — or was not."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, stage: str, code: str, *, detail: str = "", **ids: str) -> None:
        self.calls.append((stage, code, detail))

    @property
    def codes(self) -> list[str]:
        return [code for _, code, _ in self.calls]

    @property
    def details(self) -> str:
        return " ".join(detail for _, _, detail in self.calls)


@pytest.fixture(autouse=True)
def _cold(monkeypatch: pytest.MonkeyPatch) -> Any:
    # The bearer cache is module-level in `google_oauth` and shared across this process:
    # a token minted by a NEIGHBOURING test file would make the assertion step here a
    # no-op and the two-call flow untestable.
    reset_token_cache()
    yield
    reset_token_cache()


@pytest.fixture
def pages(monkeypatch: pytest.MonkeyPatch) -> Pages:
    recorder = Pages()
    monkeypatch.setattr(vertex_credential, "alert", recorder)
    return recorder


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    """The REAL fake adapter, wired in where `get_engine` would answer.

    Not a stub with a `set_llm_credential` attribute: the capability gate that refuses a
    dictated LLM leg lives in the adapter, and a stub would have had no gate to fail.
    """
    adapter = FakeEngine(capabilities=DEFAULT_FAKE_CAPABILITIES)
    monkeypatch.setattr(vertex_credential, "get_engine", lambda _settings: adapter)
    return adapter


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> str:
    raw = _service_account_json()
    monkeypatch.setattr(get_settings(), "gcp_project_id", PROJECT)
    monkeypatch.setattr(get_settings(), "gcp_service_account_json", raw)
    return raw


def _wire(monkeypatch: pytest.MonkeyPatch, google: FakeGoogle) -> None:
    """Point the job's own client factory at the fake, leaving everything else real."""
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: google.client())


# --- the happy path, and what it actually sent ----------------------------------------


@pytest.mark.asyncio
async def test_a_rotation_installs_the_bearer_and_asks_google_for_twelve_hours(
    monkeypatch: pytest.MonkeyPatch, configured: str, engine: FakeEngine, pages: Pages
) -> None:
    """The seam end to end, and the two encodings most likely to be wrong.

    `lifetime` is a `google.protobuf.Duration`, whose JSON form is a STRING with an `s`
    suffix — sending the integer `43200` is a 400 that names the field and not the
    encoding, which is a hard error to read at 3am. And the request must be authenticated
    with the short JWT-bearer token, because a `generateAccessToken` call that carried no
    credential would 401 in a way no test that only checks the URL would notice.
    """
    google = FakeGoogle()
    _wire(monkeypatch, google)

    outcome = await refresh_in_call_llm_credential({})

    assert outcome.startswith("rotated")
    assert engine._llm_credential == BEARER
    assert pages.codes == []
    assert len(google.mint_requests) == 1
    sent = google.mint_requests[0]
    assert sent["body"]["lifetime"] == TOKEN_LIFETIME == "43200s"
    assert sent["body"]["scope"] == ["https://www.googleapis.com/auth/cloud-platform"]
    assert sent["auth"] == "Bearer ya29.assertion"
    # `projects/-` is Google's wildcard: the account is identified by its address, so a
    # key from another project keeps working.
    assert f"/v1/projects/-/serviceAccounts/{EMAIL}:generateAccessToken" in sent["url"]


@pytest.mark.asyncio
async def test_a_second_rotation_replaces_rather_than_accumulates(
    monkeypatch: pytest.MonkeyPatch, configured: str, engine: FakeEngine, pages: Pages
) -> None:
    """Rotation is the operation whose whole purpose is to replace something that still
    works. Two runs must leave ONE credential — the engine holding both is the failure
    `LlmCredentialPlacement` exists to detect."""
    google = FakeGoogle()
    _wire(monkeypatch, google)

    await refresh_in_call_llm_credential({})
    await refresh_in_call_llm_credential({})

    assert engine._llm_credential == BEARER
    assert pages.codes == []


# --- the refusals. Each: nothing installed, somebody paged, the arm named --------------


@pytest.mark.asyncio
async def test_no_service_account_pages_and_installs_nothing(
    monkeypatch: pytest.MonkeyPatch, engine: FakeEngine, pages: Pages
) -> None:
    """A project without a key cannot mint anything. It is a PAGE and not a silent skip,
    because `in_call_llm` publishes a Vertex endpoint only when a key is present — so a
    deployment reaching this arm has agents pointing at Vertex and no way to credential
    them."""
    monkeypatch.setattr(get_settings(), "gcp_project_id", PROJECT)
    monkeypatch.setattr(get_settings(), "gcp_service_account_json", None)
    google = FakeGoogle()
    _wire(monkeypatch, google)

    outcome = await refresh_in_call_llm_credential({})

    assert outcome == "mint_failed"
    assert engine._llm_credential is None
    assert pages.codes == ["vertex_llm_credential_refresh_failed"]


@pytest.mark.asyncio
async def test_no_project_is_a_stated_skip_rather_than_a_page(
    monkeypatch: pytest.MonkeyPatch, engine: FakeEngine, pages: Pages
) -> None:
    """A deployment with no GCP project is not on this leg at all — local, CI, any staging
    without a Google account. Nothing is broken, so nothing pages; but the outcome NAMES
    the unmet condition rather than reporting a bland success, because an operator running
    this by hand during an incident asked a question."""
    monkeypatch.setattr(get_settings(), "gcp_project_id", None)
    google = FakeGoogle()
    _wire(monkeypatch, google)

    assert await refresh_in_call_llm_credential({}) == "skipped_no_project"
    assert engine._llm_credential is None
    assert pages.codes == []


@pytest.mark.asyncio
async def test_an_engine_that_chooses_its_own_model_is_a_stated_skip(
    monkeypatch: pytest.MonkeyPatch, configured: str, pages: Pages
) -> None:
    """A deployment that switched ENGINE to one which dictates its LLM has a cron running
    against a credential store that does not exist. Stated, not paged: nothing is broken,
    the leg simply is not ours — and NOT silent, because a refresher reporting success
    forever against somebody else's model is exactly the shape this file exists to
    prevent."""
    adapter = FakeEngine(capabilities=EXTERNAL_DEPLOYMENT_CAPABILITIES)
    monkeypatch.setattr(vertex_credential, "get_engine", lambda _settings: adapter)
    google = FakeGoogle()
    _wire(monkeypatch, google)

    assert await refresh_in_call_llm_credential({}) == "skipped_llm_not_ours"
    assert adapter._llm_credential is None
    assert pages.codes == []


@pytest.mark.asyncio
async def test_a_short_lifetime_is_refused_by_name_and_nothing_is_installed(
    monkeypatch: pytest.MonkeyPatch, configured: str, engine: FakeEngine, pages: Pages
) -> None:
    """**THE ORG-POLICY ARM, and the reason `expireTime` is read rather than assumed.**

    Ask for 43200s without `constraints/iam.allowServiceAccountCredentialLifetimeExtension`
    and Google silently caps at 3600s. Installing that would be a success message followed
    by a five-hour hole between ticks — every in-call model turn 401ing, on live calls,
    with our own log saying the rotation worked. Refusing installs nothing, so the leg
    keeps running on the credential it already has while somebody sets the policy."""
    google = FakeGoogle(granted_seconds=3600)
    _wire(monkeypatch, google)

    outcome = await refresh_in_call_llm_credential({})

    assert outcome == "lifetime_too_short"
    assert engine._llm_credential is None
    assert pages.codes == ["vertex_llm_credential_refresh_failed"]
    # The remedy has to be IN the page: this is the one arm whose fix is a GCP org policy
    # nobody would guess from "refresh failed".
    assert "allowServiceAccountCredentialLifetimeExtension" in pages.details


@pytest.mark.asyncio
async def test_a_token_already_expired_is_refused_rather_than_installed(
    monkeypatch: pytest.MonkeyPatch, configured: str, engine: FakeEngine, pages: Pages
) -> None:
    """Host clock skew, realistically. Installing it would be worse than refusing: the
    engine would hold a credential that fails on the very next call, and the NEXT tick
    would report a healthy rotation on top of it."""
    google = FakeGoogle(granted_seconds=-60)
    _wire(monkeypatch, google)

    outcome = await refresh_in_call_llm_credential({})

    assert outcome == "expired_on_arrival"
    assert engine._llm_credential is None
    assert pages.codes == ["vertex_llm_credential_refresh_failed"]
    assert "clock" in pages.details


@pytest.mark.asyncio
async def test_a_refused_mint_pages_and_installs_nothing(
    monkeypatch: pytest.MonkeyPatch, configured: str, engine: FakeEngine, pages: Pages
) -> None:
    """The 403 an operator will actually meet: the service account lacks
    `roles/iam.serviceAccountTokenCreator` ON ITSELF, which self-impersonation needs."""
    google = FakeGoogle()
    google.mint_status = 403
    _wire(monkeypatch, google)

    outcome = await refresh_in_call_llm_credential({})

    assert outcome == "mint_failed"
    assert engine._llm_credential is None
    assert pages.codes == ["vertex_llm_credential_refresh_failed"]


@pytest.mark.asyncio
async def test_a_response_without_a_readable_expiry_is_refused(
    monkeypatch: pytest.MonkeyPatch, configured: str, engine: FakeEngine, pages: Pages
) -> None:
    """`GenerateAccessTokenResponse.expire_time` is documented as ALWAYS set, so a response
    without a readable one is not a Google response we recognise. Defaulting to
    `now + TOKEN_LIFETIME_S` would invent the exact fact the check above reads — and would
    invent it in the optimistic direction."""
    google = FakeGoogle()
    google.expire_override = None
    _wire(monkeypatch, google)

    assert await refresh_in_call_llm_credential({}) == "mint_failed"
    assert engine._llm_credential is None
    assert pages.codes == ["vertex_llm_credential_refresh_failed"]


@pytest.mark.asyncio
async def test_a_naive_expiry_does_not_become_a_traceback(
    monkeypatch: pytest.MonkeyPatch, configured: str, engine: FakeEngine, pages: Pages
) -> None:
    """An expiry compared against an aware `now()` must itself be aware, or the comparison
    raises `TypeError` — turning a perfectly readable token into a crashed cron. The value
    is treated as UTC, which is what Google emits."""
    google = FakeGoogle()
    google.expire_override = (datetime.now(UTC) + timedelta(seconds=TOKEN_LIFETIME_S)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    _wire(monkeypatch, google)

    assert (await refresh_in_call_llm_credential({})).startswith("rotated")
    assert engine._llm_credential == BEARER
    assert pages.codes == []


@pytest.mark.asyncio
async def test_an_engine_that_refuses_the_write_pages_and_says_so(
    monkeypatch: pytest.MonkeyPatch, configured: str, engine: FakeEngine, pages: Pages
) -> None:
    """The vendor refusing the write is the likeliest real failure, because
    `bolna_llm_credential_name` is a MARKED ASSUMPTION. It must page rather than propagate:
    a cron that raises is retried and then dropped, and a dropped cron is precisely the
    outcome this alarm exists to make impossible."""

    async def boom(_secret: str) -> None:
        raise RuntimeError("vendor said no")

    monkeypatch.setattr(engine, "set_llm_credential", boom)
    google = FakeGoogle()
    _wire(monkeypatch, google)

    outcome = await refresh_in_call_llm_credential({})

    assert outcome == "install_failed"
    assert pages.codes == ["vertex_llm_credential_refresh_failed"]


@pytest.mark.asyncio
async def test_the_founders_switch_stops_the_refresher_too(
    monkeypatch: pytest.MonkeyPatch, configured: str, engine: FakeEngine, pages: Pages
) -> None:
    """`VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE` is read by BOTH `in_call_llm` and this job,
    so switching the leg off stops publishing Vertex endpoints AND stops writing bearers
    for an endpoint no agent points at any more. Two halves reading one constant is what
    makes them unable to disagree about whether the leg is on."""
    monkeypatch.setattr(vertex_credential, "VERTEX_IN_CALL_CREDENTIAL_DELIVERABLE", False)
    google = FakeGoogle()
    _wire(monkeypatch, google)

    assert await refresh_in_call_llm_credential({}) == "skipped_not_deliverable"
    assert engine._llm_credential is None
    assert pages.codes == []


# --- the credential never appears anywhere it must not ---------------------------------


@pytest.mark.asyncio
async def test_no_credential_reaches_a_log_record(
    monkeypatch: pytest.MonkeyPatch,
    configured: str,
    engine: FakeEngine,
    pages: Pages,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Hard rule 6's neighbour, and the failure a reviewer cannot see by reading: a bearer
    or a private key in a log line. Driven over the WHOLE successful path with a real
    handler attached, and it checks the formatted message AND every `extra` value, because
    structured fields are where a credential would realistically be put by accident."""
    google = FakeGoogle()
    _wire(monkeypatch, google)

    with caplog.at_level(logging.DEBUG):
        assert (await refresh_in_call_llm_credential({})).startswith("rotated")

    private_key = json.loads(configured)["private_key"]
    for record in caplog.records:
        blob = " ".join(
            [record.getMessage(), *(str(v) for v in record.__dict__.values() if v is not None)]
        )
        assert BEARER not in blob
        assert private_key not in blob
        assert "ya29.assertion" not in blob

    # And the fingerprint IS there, because correlating two rotations without the value is
    # the whole reason it exists.
    assert any("fingerprint" in record.__dict__ for record in caplog.records)


def test_the_fingerprint_is_not_the_credential() -> None:
    """A truncated one-way digest, not a prefix or a suffix of the token. A "first eight
    characters" scheme would be a credential leak wearing the word fingerprint."""
    printed = vertex_credential._token_fingerprint(BEARER)
    assert len(printed) == 12
    assert printed not in BEARER
    assert BEARER[:12] != printed
    assert vertex_credential._token_fingerprint("other") != printed


# --- the cadence is arithmetic, not a typed number -------------------------------------


def test_the_refresh_floor_leaves_room_for_a_missed_tick() -> None:
    """The number that makes this rotation survivable rather than merely correct. A token
    must outlive TWO refresh intervals, so a single failed tick is a page with hours of
    lead time rather than an outage — and the floor is DERIVED from the interval, so
    moving the cadence moves the check with it."""
    assert MIN_GRANTED_LIFETIME_S == REFRESH_INTERVAL_HOURS * 2 * 3600
    assert TOKEN_LIFETIME_S >= MIN_GRANTED_LIFETIME_S + REFRESH_INTERVAL_HOURS * 3600


def test_the_cron_fires_at_the_interval_the_constant_states() -> None:
    """The registration must be the cadence the argument was made about. Writing the hours
    by hand would be a second place the interval is stated, and the two would drift in the
    direction nobody notices — a wider gap than the token's lifetime."""
    from apps.workers.settings import CRON_JOBS

    registered = [
        job
        for job in CRON_JOBS
        if getattr(job, "name", "").endswith("refresh_in_call_llm_credential")
    ]
    assert len(registered) == 1
    hours = sorted(registered[0].hour or [])
    assert hours == sorted(range(1, 24, REFRESH_INTERVAL_HOURS))
    assert len(hours) == 24 // REFRESH_INTERVAL_HOURS
    # `cron()` defaults `max_tries` to 1 and `WorkerSettings.max_tries` does not reach a
    # cron that carries its own — a job that gives up on one transient 503 leaves the leg
    # four hours closer to dark.
    assert (registered[0].max_tries or 1) > 1


@pytest.mark.asyncio
async def test_mint_returns_the_expiry_google_gave_not_the_one_we_asked_for(
    monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    """The property the whole org-policy refusal rests on, asserted directly on the mint
    so it cannot be satisfied by the caller's arithmetic."""
    google = FakeGoogle(granted_seconds=3600)
    async with google.client() as http:
        minted = await mint_in_call_bearer(http)

    assert minted is not None
    assert minted.remaining < timedelta(seconds=TOKEN_LIFETIME_S)
    assert minted.remaining <= timedelta(seconds=3600)
