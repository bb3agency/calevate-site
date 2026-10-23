"""A route that accepts a file bigger than 2 MiB has an outer wall at its own limit.

The global body cap (`core/middleware.MAX_BODY_BYTES`) refused a 3 MB knowledge PDF, PAN
scan or voice note before the route that promises to take it was reached.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.compliance.kyc_documents import KYC_MAX_DOCUMENT_BYTES
from apps.api.core.middleware import MAX_BODY_BYTES, ROUTE_BODY_LIMITS, body_limit_for
from apps.api.core.ratelimit import profile_for
from apps.api.kb.pdf_render import MAX_UPLOAD_BYTES
from apps.api.main import app
from apps.api.teach.teaching import MAX_VOICE_BYTES
from httpx import ASGITransport, AsyncClient
from tests.api_security_test import _make_tenant

pytestmark = [pytest.mark.rls]

#: (route, the limit the route itself enforces on the file).
BOUNDED_UPLOADS = [
    ("/v1/kb/uploads", MAX_UPLOAD_BYTES),
    ("/v1/compliance/kyc/documents", KYC_MAX_DOCUMENT_BYTES),
    ("/v1/kb/teach/upload", MAX_VOICE_BYTES),
    ("/v1/first-run/recordings", MAX_VOICE_BYTES),
]


@pytest.mark.parametrize(("path", "file_limit"), BOUNDED_UPLOADS)
def test_the_outer_wall_sits_just_above_the_routes_own_limit(path: str, file_limit: int) -> None:
    wall = ROUTE_BODY_LIMITS[("POST", path)]
    assert file_limit <= wall <= file_limit + 128 * 1024, (path, file_limit, wall)


def test_a_dispute_contest_may_carry_every_evidence_file_it_accepts() -> None:
    from apps.api.billing.payment_admin_routes import _EVIDENCE_MAX_BYTES, EVIDENCE_MAX_FILES

    files = EVIDENCE_MAX_FILES * _EVIDENCE_MAX_BYTES
    wall = body_limit_for("POST", "/v1/admin/payments/disputes/disp_abc123/contest")
    assert files <= wall <= files + 128 * 1024
    # The pattern is one path segment wide: nothing nested or neighbouring matches it.
    assert body_limit_for("POST", "/v1/admin/payments/disputes/a/b/contest") == MAX_BODY_BYTES
    assert body_limit_for("GET", "/v1/admin/payments/disputes/disp_abc123/contest") == (
        MAX_BODY_BYTES
    )


@pytest.mark.parametrize("path", [p for p, limit in BOUNDED_UPLOADS if limit > 4 * 1024 * 1024])
def test_a_large_upload_is_rated_as_an_upload(path: str) -> None:
    assert profile_for(path, "POST").name == "upload"


async def test_a_three_megabyte_document_reaches_the_knowledge_route() -> None:
    _, slug, token = await _make_tenant("owner")
    body = b"%PDF-1.4\n" + b"0" * (3 * 1024 * 1024)
    assert len(body) > MAX_BODY_BYTES
    peer = f"2001:db8:{uuid.uuid4().hex[:4]}::1"
    async with AsyncClient(
        transport=ASGITransport(app=app, client=(peer, 1)), base_url="http://api"
    ) as http:
        response = await http.post(
            "/v1/kb/uploads",
            files={"file": ("menu.pdf", body, "application/pdf")},
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert response.status_code != 413, response.text


async def test_a_body_over_the_routes_wall_is_still_refused() -> None:
    _, slug, token = await _make_tenant("owner")
    wall = ROUTE_BODY_LIMITS[("POST", "/v1/compliance/kyc/documents")]
    peer = f"2001:db8:{uuid.uuid4().hex[:4]}::1"
    async with AsyncClient(
        transport=ASGITransport(app=app, client=(peer, 1)), base_url="http://api"
    ) as http:
        response = await http.post(
            "/v1/compliance/kyc/documents",
            files={"file": ("pan.jpg", b"\xff\xd8\xff" + b"0" * wall, "image/jpeg")},
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
    assert response.status_code == 413, response.text
