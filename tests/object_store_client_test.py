"""The S3 client's identity: which region it signs for, whose session it is, how often.

Three properties, all of which were wrong or unpinned, and none of which any existing test
could see because they are all about the CLIENT rather than about a request. There is no
MinIO in this environment and none is needed: a presigned URL carries the entire sigv4
credential scope in its query string, so the region a client will sign with is readable
offline, exactly, without a store to talk to.

WHAT WAS ACTUALLY BROKEN.

1. **No region.** `_client()` passed `endpoint_url` and a `Config` and nothing else.
   botocore needs a region for the sigv4 credential scope, and for **s3 alone** it
   silently falls back to `us-east-1` when nothing supplies one — measured here rather
   than assumed, because the audit finding this closes claimed a `NoRegionError` at
   construction and that is not what happens (it IS what happens for other services; the
   s3 fallback is the special case). So it was never a crash. It was every request signed
   under a region nobody chose, against a store — Cloudflare R2, DEPLOYMENT §1 — that
   documents `auto`, and a `SignatureDoesNotMatch` from a mismatch would send an operator
   looking at the key and the bucket policy long before the region.

2. **The process-global session.** `boto3.client(...)` resolves through a module-level
   `DEFAULT_SESSION` shared with every other caller in the process, so the first one
   anywhere fixes the credentials the rest sign with — and caches that resolution against
   a changed environment. `infra/object-lifecycle/apply_lifecycle.py` already hit exactly
   this (D-106) and already fixed it with `boto3.Session().client(...)`; this module was
   the copy that did not get the fix.

3. **Rebuilt per call.** ~90ms per construction, because a fresh session loads botocore's
   s3 service model. `presigned_url` is called synchronously from an API request handler,
   so that was 90ms of event-loop CPU per recording playback, blocking every tenant.

Credentials are declared here with `monkeypatch.setenv` and never borrowed — the suite's
`_no_ambient_credentials` fixture strips them session-wide so local matches CI, and
signing needs a key to put in the scope.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pytest
from apps.workers import storage

#: `X-Amz-Credential` is `<access-key>/<YYYYMMDD>/<region>/<service>/aws4_request`
#: (AWS SigV4, "Authentication Methods — Query string"). The region is the third field and
#: is the ONLY place a client's region is observable without a store to answer.
_SCOPE = re.compile(r"^[^/]+/\d{8}/(?P<region>[^/]+)/(?P<service>[^/]+)/aws4_request$")


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAOBJECTSTORETEST")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-for-signing-only")


@pytest.fixture(autouse=True)
def _no_leaked_client() -> None:
    """Drop any client an earlier test in this session cached.

    The cache is keyed on a fingerprint of (endpoint, region, credentials), so a changed
    environment already produces a changed client and this is belt and braces — but a test
    file whose whole subject IS the cache should not be reading one somebody else warmed.
    """
    storage._cached_client = None


def _signed_region(key: str = "recordings/t/c.wav") -> str:
    url = storage.presigned_url(key)
    assert url is not None, "presign returned None — see the credentials fixture"
    credential = parse_qs(urlparse(url).query)["X-Amz-Credential"][0]
    match = _SCOPE.match(credential)
    assert match is not None, f"not a sigv4 credential scope: {credential}"
    assert match["service"] == "s3"
    return match["region"]


def test_the_signing_region_is_the_configured_one_and_not_botocores_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`auto` by default — what Cloudflare R2 documents for its S3 API — and `AWS_REGION`
    when a store wants its own datacenter slug instead.

    The default matters as much as the override: it is the value `apply_lifecycle.py`
    already signs the SAME bucket with, and two clients disagreeing about the region of
    one bucket is a signature failure with no obvious cause.
    """
    monkeypatch.delenv("AWS_REGION", raising=False)
    assert _signed_region() == "auto"

    monkeypatch.setenv("AWS_REGION", "blr1")
    storage._cached_client = None
    assert _signed_region() == "blr1"


def test_leaving_the_region_unset_would_sign_as_us_east_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The measurement the fix rests on, pinned so nobody has to re-derive it.

    This constructs a client the way `_client()` used to and reads the region back. If a
    future botocore starts raising instead of defaulting, this test says so — and the
    comment in `_client()` explaining why the old code did not crash becomes wrong on the
    same day, rather than silently.
    """
    import boto3
    from botocore.config import Config

    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    client = boto3.Session().client(
        "s3",
        endpoint_url="https://example.invalid",
        config=Config(signature_version="s3v4"),
    )
    assert client.meta.region_name == "us-east-1", (
        "botocore no longer defaults an s3 client's region. `_client()`'s comment says "
        "the missing region was a silently wrong signature rather than a crash — check "
        "whether that is still true before trusting it."
    )


def test_the_client_is_cached_across_calls() -> None:
    """Identity, not equality: a new client would be a new object and a new 90ms.

    `presigned_url` is called synchronously from an API route, so this is not a
    micro-optimisation — it is the difference between 0.17ms of local HMAC and 90ms of
    service-model loading on the event loop every tenant shares.
    """
    assert storage._client() is storage._client()


def test_changing_the_credentials_produces_a_different_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cache must not outlive the thing it was built from.

    This is the property that makes caching safe at all: D-106's failure was a client that
    kept signing with credentials the environment no longer held. Keyed on a fingerprint
    of the inputs, a rotation (or a test that declares its own key) gets a new client
    rather than a stale one, with no reset hook for anybody to forget to call.
    """
    first = storage._client()
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIADIFFERENTKEY")
    second = storage._client()
    assert first is not second


def test_the_client_does_not_come_from_the_process_global_session() -> None:
    """D-106, stated as a property rather than as a comment.

    `boto3.client(...)` populates `boto3.DEFAULT_SESSION` on first use and every later
    caller in the process — ours or a library's — shares it. Building our own session
    leaves that global untouched, which is what makes this module's credentials
    unpoisonable by a stranger and a stranger's unpoisonable by us.
    """
    import boto3

    boto3.DEFAULT_SESSION = None
    storage._client()
    assert boto3.DEFAULT_SESSION is None, (
        "storage._client() populated boto3's global DEFAULT_SESSION — it is back to "
        "boto3.client(...), and the first caller in the process now fixes the "
        "credentials every later one signs with (D-106)."
    )


def test_a_missing_credential_is_reported_by_name_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`presigned_url` returns None either way; the log line is the whole interface.

    A bare "presign_failed" sent an operator to the bucket, the key and the lifecycle
    policy. `NoCredentialsError` in the record sends them to the one line of `.env` that
    is actually missing — and `runtime_config_missing_keys` has already said so at
    `/healthz/ready` before any request reaches here.
    """
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    storage._cached_client = None

    with caplog.at_level("WARNING"):
        assert storage.presigned_url("recordings/t/c.wav") is None
    records = [record for record in caplog.records if record.message == "presign_failed"]
    assert records, "presign failed without a log line an operator can act on"
    assert getattr(records[0], "reason", None) == "NoCredentialsError"


def test_readiness_names_the_object_store_credentials_a_prod_deploy_lacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half: the operator meets this at `/healthz/ready`, not at the first call.

    Without it the first symptom of a credential-less host is a recording copy that
    retries three times and lands in the DLQ — and the recording is a TRAI 90-day
    obligation against a vendor link with no documented expiry, so by then it may simply
    be gone.
    """
    from apps.api.core.settings import runtime_config_missing_keys
    from calevate_shared.config import Settings

    def _prod(**overrides: object) -> Settings:
        base: dict[str, object] = {
            "app_env": "prod",
            "database_url": "postgresql+psycopg://calevate_app:x@db.internal:5432/calevate",
            "redis_url": "redis://redis.internal:6379/0",
            "object_store_endpoint": "https://example.invalid",
            "object_store_bucket": "calevate-prod",
        }
        base.update(overrides)
        return Settings(_env_file=None, **base)  # type: ignore[arg-type]

    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    reported = runtime_config_missing_keys(_prod())
    assert "AWS_ACCESS_KEY_ID" in reported, reported
    assert "AWS_SECRET_ACCESS_KEY" in reported, reported

    # And a local box is untouched: a developer with no object store is a coherent state,
    # and a probe that is red for every developer is a probe nobody reads.
    assert "AWS_ACCESS_KEY_ID" not in runtime_config_missing_keys(_prod(app_env="local"))
