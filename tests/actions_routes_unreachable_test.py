"""A provider that does not answer an owner's connection request.

The connection test, the code exchange and the Sheets picker let a raw `httpx` error out
of the handler: a 500 "something went wrong at our end" for a provider being slow. The
test now answers that it could not reach the provider (and never "reconnect", which would
send the owner to redo a connection that works); the other two refuse with a problem the
owner can act on.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from apps.api.actions import credentials as creds
from apps.api.actions import routes
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError


def _unreachable_client(**kwargs: Any) -> httpx.AsyncClient:
    def _refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no answer", request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(_refuse))


def _owner() -> Principal:
    return Principal(realm="client", user_id=uuid4(), tenant_id=uuid4(), role="owner")


@pytest.mark.parametrize(
    ("kind", "non_secret"),
    [("razorpay", {"key_id": "rzp_test_x"}), ("zoho_crm", {})],
)
async def test_a_connection_test_that_gets_no_answer_says_so(
    monkeypatch: pytest.MonkeyPatch, kind: str, non_secret: dict[str, object]
) -> None:
    async def _resolve(session: Any, **kwargs: Any) -> creds.ResolvedCredential:
        return creds.ResolvedCredential(kind=kind, secret="s", non_secret=non_secret, version=1)

    monkeypatch.setattr(creds, "resolve_credential", _resolve)
    monkeypatch.setattr(routes, "egress_client", _unreachable_client)
    monkeypatch.setattr(routes.oauth, "require_configured", lambda kind: None)

    out = await routes.test_credential(uuid4(), session=object(), principal=_owner())  # type: ignore[arg-type]

    assert out.ok is False
    assert out.message == routes.UNREACHABLE_TEST_MESSAGE
    assert "connect" not in out.message.lower()


async def test_the_sheets_picker_refuses_rather_than_500s_when_google_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _kind(session: Any, **kwargs: Any) -> str:
        return "google_sheets"

    async def _resolve(session: Any, **kwargs: Any) -> creds.ResolvedCredential:
        return creds.ResolvedCredential(
            kind="google_sheets", secret="refresh", non_secret={}, version=1
        )

    monkeypatch.setattr(creds, "credential_kind", _kind)
    monkeypatch.setattr(creds, "resolve_credential", _resolve)
    monkeypatch.setattr(routes.gsheets, "picker_configured", lambda: True)

    async def _silent(resolved: Any, **kwargs: Any) -> str:
        raise httpx.ReadTimeout("no answer")

    monkeypatch.setattr(routes, "access_token_for", _silent)

    with pytest.raises(ProblemError) as refused:
        await routes.sheets_picker(uuid4(), session=object(), principal=_owner())  # type: ignore[arg-type]
    assert refused.value.code == "integration_unreachable"


def test_the_unreachable_refusal_is_a_dependency_problem() -> None:
    problem = routes.vendor_unreachable("Zoho CRM")
    assert problem.kind == "dependency"
    assert problem.code == "integration_unreachable"
    assert "Zoho CRM" in problem.title
