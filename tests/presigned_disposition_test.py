"""A presigned link must DOWNLOAD, never render.

Every object `storage.presigned_url` signs is bytes somebody else supplied — a client's
knowledge-base upload, a caller's recorded voice, an integration's delivery body — and an
object store replays whatever `Content-Type` the object was stored with. A presigned GET
is therefore a link, handed to a reader by our own console, that can render attacker-chosen
bytes in that reader's browser.

The September 2026 audit found the upload path storing the type the UPLOADER chose. That
is fixed where it is decided (`kb/uploads.stored_content_type`), and this is the second
lock on the same door: even a `text/html` object that slips past every type check cannot
execute if the browser was told to save it.

WHY A TEST AND NOT JUST THE ARGUMENT IN THE DOCSTRING. The parameter is one key in a dict
passed to boto3, which validates nothing about it and would accept its removal silently.
Nothing else in the tree would go red — no screen changes, no response shape changes, and
the link still works. So this asserts the SIGNED URL carries it, which is also the property
that matters: signed IN means a caller cannot strip it by editing the link.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from apps.workers import storage


@pytest.fixture
def _object_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """A presign is a local HMAC — no socket — so this needs credentials, not a server."""
    settings = storage.get_settings()
    monkeypatch.setattr(settings, "object_store_bucket", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "object_store_endpoint", "https://s3.example", raising=False)
    # THE CREDENTIAL IS THE ENVIRONMENT, not a `Settings` field — `_CREDENTIAL_ENV` at
    # `storage.py:126`, and `tests/conftest._no_ambient_credentials` strips these, so they
    # are set here rather than assumed. `AWS_SESSION_TOKEN` is cleared deliberately: a
    # leftover one on a developer's machine would put an `X-Amz-Security-Token` in the
    # query and change the signature this file compares.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s3cret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    # No cache reset: `_client` is keyed on a FINGERPRINT of endpoint, region and the
    # credential environment (`storage.py:145`), so changing any of them above rebuilds it.
    # That design is the reason this fixture works at all — an `lru_cache` would have
    # served a client built before the monkeypatch.


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_a_presigned_read_tells_the_browser_to_save_rather_than_render(
    _object_store: None,
) -> None:
    url = storage.presigned_url("recordings/t/abc.wav")
    assert url is not None
    query = _query(url)
    assert query.get("response-content-disposition") == ["attachment"], (
        "a presigned link renders somebody else's bytes on the object store's origin; "
        "without `attachment` a text/html object executes in the reader's browser"
    )


def test_the_disposition_is_inside_the_signature_and_not_merely_appended(
    _object_store: None,
) -> None:
    """Stripping it must BREAK the link rather than widen it.

    `X-Amz-SignedHeaders` covers headers; a response override is covered because it is a
    signed QUERY PARAMETER — so the canonical query string, and therefore the signature,
    changes when it is removed. Asserted by signing the same key twice, once through our
    function and once without the override, and requiring the signatures to differ: if the
    parameter were outside the signature both would sign identically and an attacker could
    delete it from a link we handed out.
    """
    ours = storage.presigned_url("kb-uploads/t/doc.pdf")
    assert ours is not None
    bare = storage._client().generate_presigned_url(
        "get_object",
        Params={"Bucket": "calevate-test", "Key": "kb-uploads/t/doc.pdf"},
        ExpiresIn=storage.PRESIGN_TTL_S,
    )
    assert _query(ours)["X-Amz-Signature"] != _query(bare)["X-Amz-Signature"]


def test_every_caller_inherits_it_because_it_is_signed_here(_object_store: None) -> None:
    """The three call sites — the CRM recording link, the knowledge-base original and the
    integration delivery body — all reach the object store through this one function, so
    the control cannot be forgotten at a call site. Driven by key shape rather than by
    importing three routers, which would drag their whole dependency trees in."""
    for key in (
        "recordings/tenant/call.wav",
        "kb-uploads/tenant/price-list.pdf",
        "delivery-bodies/tenant/body.json",
    ):
        url = storage.presigned_url(key)
        assert url is not None
        assert _query(url).get("response-content-disposition") == ["attachment"], key
