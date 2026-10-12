"""A filled vendor path cannot be steered to another endpoint by the id inside it.

Every adapter interpolates ids into its path template, and httpx removes dot segments when it
builds the URL (RFC 3986 §5.2.4), so an id of `../agents/x` in `DELETE /contacts/{id}` would
be sent as `DELETE /agents/x`. `vendor_http.assert_safe_vendor_path` runs inside the shared
ladder, before anything is sent.
"""

from __future__ import annotations

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.engine.thinnest_customer_data import ThinnestCustomerData
from apps.api.engine.vendor_http import assert_safe_vendor_path

WORKSPACE = "org_3fKq9TzQ1mN8vB2xR7cLpA"


@pytest.mark.parametrize(
    "path",
    [
        "/agents/agt_123",
        "/agents/agt_123@org_3fKq9TzQ1mN8vB2xR7cLpA/tools",
        "/do-not-call/919876543210",
        "/Account/MA123/numbers/+918012345678/application",
        "/voice-clones/a%2Fb",
        "/agents/v1.2/knowledge/doc.pdf",
        "https://files.example.com/rec/abc.wav?X-Amz-Signature=x&y=../z",
    ],
)
def test_real_ids_pass(path: str) -> None:
    assert_safe_vendor_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "/contacts/../agents/x",
        "/contacts/..",
        "/contacts/%2e%2e/agents/x",
        "/contacts/.%2E/agents/x",
        "/contacts/./x",
        "/contacts/x?scope=all",
        "/contacts/x#frag",
        "/contacts/x\\..\\agents",
        "/contacts/x y",
        "/contacts/x\r\nHost: evil",
    ],
)
def test_ids_that_would_reach_another_endpoint_are_refused(path: str) -> None:
    """FAILS IF: an id carrying a dot segment, a query or fragment marker, a backslash or a
    control character reaches the vendor."""
    with pytest.raises(ProblemError) as refused:
        assert_safe_vendor_path(path)
    assert refused.value.code == "engine_path_refused"


async def test_a_contact_id_with_a_dot_segment_is_never_sent() -> None:
    """The erasure deletes the contact the vendor named. An id that climbs out of
    `/contacts/` must not become a DELETE on some other object of the client's workspace."""
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(f"{request.method} {request.url.path}")
        return httpx.Response(204)

    client = ThinnestCustomerData(
        api_key="ta_live_test",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://app.thinnest.ai/api/v1"
        ),
    )
    with pytest.raises(ProblemError) as refused:
        await client.delete_contact(WORKSPACE, "../agents/agt_1")
    assert refused.value.code == "engine_path_refused"
    assert sent == []

    assert await client.delete_contact(WORKSPACE, "cust_1") == 0
    assert sent == ["DELETE /api/v1/contacts/cust_1"]
