"""What the client and admin number screens are told, so they offer only what the server does.

* `GET /v1/campaigns/numbers` says `releasable` exactly when the client release route would
  accept the number, and says `answerable` for a voice-platform number from the agent our
  record has it answer, since nothing there writes `carrier_binding_id` (Pipecat unchanged).
* A replayed purchase reports `first_period = "replayed"`.
* The generic admin release refuses a voice-platform number; the workspace route owns it.
* An operator's business-details send is audited once it happened, or as a failure.
* Uploading KYC documents and accepting the pledge are named view-as acts, so `/v1/me`
  reports them and the page can disable them with the server's own reason.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import number_routes
from apps.api.campaigns import number_supply
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import VIEW_AS_WITHHELD_ACTS
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.engine_number_purchase_test import (
    _attested,
    _bundle,
    _client,
    _live_agent,
    _recorded,
    kyc_bundle,  # noqa: F401 - pytest fixture
)
from tests.engine_workspace_routes_test import _admin_headers, _client_headers
from tests.thinnest_fake_account import FakeAccount

pytestmark = [pytest.mark.rls]

NUMBERS = "/v1/campaigns/numbers"


def _http() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _answering(tenant_id: UUID, workspace: str | None, *, direction: str) -> UUID:
    agent_id, _ref = await _live_agent(tenant_id, workspace)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = :d WHERE id = :a"),
            {"d": direction, "a": agent_id},
        )
    return agent_id


async def _bind(tenant_id: UUID, number_id: UUID, agent_id: UUID | None) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE phone_numbers SET agent_id = :a WHERE id = :n"),
            {"a": agent_id, "n": number_id},
        )


async def _listed(tenant_id: UUID) -> dict[str, dict[str, Any]]:
    headers = await _client_headers(tenant_id)
    async with _http() as http:
        response = await http.get(NUMBERS, headers=headers)
    assert response.status_code == 200, response.text
    return {row["id"]: row for row in response.json()}


# --- releasable and answerable on the voice platform ----------------------------------------


async def test_only_a_number_in_the_clients_own_workspace_is_releasable(
    account: FakeAccount,
) -> None:
    tenant_id, workspace = await _client(account)
    own = await _recorded(tenant_id, f"{account.available[0]}@{workspace}")
    lent = await _recorded(tenant_id, account.available[1])
    elsewhere = await _recorded(tenant_id, f"{account.available[2]}@org_someone_else")

    rows = await _listed(tenant_id)

    assert rows[str(own)]["releasable"] is True
    assert rows[str(lent)]["releasable"] is False, "a platform-held number is an operator's"
    assert rows[str(elsewhere)]["releasable"] is False


async def test_a_voice_platform_number_answers_from_its_recorded_agent(
    account: FakeAccount,
) -> None:
    tenant_id, workspace = await _client(account)
    number = await _recorded(tenant_id, f"{account.available[0]}@{workspace}")

    assert (await _listed(tenant_id))[str(number)]["answerable"] is False, "no agent on it"

    inbound = await _answering(tenant_id, workspace, direction="inbound")
    await _bind(tenant_id, number, inbound)
    row = (await _listed(tenant_id))[str(number)]
    assert row["answerable"] is True, "no carrier binding is written on this engine"

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'outbound' WHERE id = :a"), {"a": inbound}
        )
    assert (await _listed(tenant_id))[str(number)]["answerable"] is False, "it answers nothing"


async def test_an_agent_in_another_workspace_does_not_answer_the_number(
    account: FakeAccount,
) -> None:
    tenant_id, workspace = await _client(account)
    number = await _recorded(tenant_id, f"{account.available[0]}@{workspace}")
    platform_agent = await _answering(tenant_id, None, direction="inbound")
    await _bind(tenant_id, number, platform_agent)

    assert (await _listed(tenant_id))[str(number)]["answerable"] is False


async def test_pipecat_still_needs_the_carrier_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Pipecat reading is untouched: an answering agent alone is not enough there."""
    from tests.campaign_route_wrappers_test import _headers, _tenant
    from tests.numbers_answerable_test import _number

    monkeypatch.setattr(get_settings(), "engine", "pipecat")
    tenant_id, agent_id, slug = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'inbound' WHERE id = :a"), {"a": agent_id}
        )
    unbound = await _number(tenant_id, agent_id=agent_id, engine_ref="vz-1", binding_id=None)
    bound = await _number(tenant_id, agent_id=agent_id, engine_ref="vz-2", binding_id="app-1")
    async with _http() as http:
        response = await http.get(NUMBERS, headers=await _headers(tenant_id, slug))
    rows = {row["id"]: row for row in response.json()}
    assert (rows[unbound]["answerable"], rows[bound]["answerable"]) == (False, True)
    assert not rows[bound]["releasable"]


# --- purchase replay -------------------------------------------------------------------------


async def test_a_replayed_purchase_says_so_in_first_period(account: FakeAccount) -> None:
    await _attested()
    tenant_id, _workspace = await _client(account)
    headers = await _client_headers(tenant_id)
    body = {"number": account.available[0], "request_key": f"key-{uuid.uuid4().hex}"}
    async with _http() as http:
        first = await http.post("/v1/numbers/own/purchase", json=body, headers=headers)
        again = await http.post("/v1/numbers/own/purchase", json=body, headers=headers)
    assert first.json()["first_period"] == "charged"
    assert (again.json()["replayed"], again.json()["first_period"]) == (True, "replayed")


# --- one release path for a voice-platform number ------------------------------------------


async def test_the_generic_release_refuses_a_voice_platform_number(account: FakeAccount) -> None:
    tenant_id, workspace = await _client(account)
    number_id = await _recorded(tenant_id, f"{account.available[0]}@{workspace}")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await number_supply.release_number(session, get_engine(), number_id=number_id)
    assert refused.value.code == "number_released_in_voice_workspace"

    async with _http() as http:
        listed = await http.get(
            f"/v1/admin/numbers/tenants/{tenant_id}", headers=await _admin_headers()
        )
    [row] = [r for r in listed.json() if r["id"] == str(number_id)]
    assert row["on_engine"] is True
    assert number_routes.TenantNumberCostOut.model_fields["on_engine"].default is False


# --- the operator's business-details send ---------------------------------------------------


async def _actions(tenant_id: UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE tenant_id = :t "
                    "AND action LIKE 'engine_workspace.business_details%' ORDER BY at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [str(r[0]) for r in rows]


async def test_a_failed_send_is_audited_as_a_failure_and_never_as_sent(
    account: FakeAccount,
) -> None:
    tenant_id, _workspace = await _client(account, approved=False)
    async with _http() as http:
        response = await http.post(
            f"/v1/admin/engine-workspaces/tenants/{tenant_id}/business-details",
            headers=await _admin_headers(),
        )
    assert response.status_code == 422, response.text
    assert "business_details_kyc_not_verified" in response.text
    assert await _actions(tenant_id) == ["engine_workspace.business_details_send_failed"]


async def test_a_send_is_audited_with_what_the_vendor_answered(
    account: FakeAccount,
    kyc_bundle: dict[UUID, Any],  # noqa: F811
) -> None:
    tenant_id, workspace = await _client(account, approved=False)
    account.ws(workspace).business = {"status": "none"}
    kyc_bundle[tenant_id] = _bundle(tenant_id)
    async with _http() as http:
        response = await http.post(
            f"/v1/admin/engine-workspaces/tenants/{tenant_id}/business-details",
            headers=await _admin_headers(),
        )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "submitted"
    assert await _actions(tenant_id) == ["engine_workspace.business_details_sent"]


# --- the business's own acts, named for view-as ---------------------------------------------


def _operator(tenant_id: UUID) -> Principal:
    return Principal(
        realm="admin",
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="owner",
        impersonating=True,
    )


class _Request:
    client = None
    headers: dict[str, str] = {}  # noqa: RUF012


async def test_view_as_is_refused_uploads_and_the_pledge_with_the_named_reason(
    account: FakeAccount,
) -> None:
    from apps.api.compliance import outbound_pledge
    from apps.api.compliance.kyc_routes import upload_document
    from apps.api.compliance.outbound_pledge_routes import (
        OutboundPledgeIn,
        accept_outbound_pledge,
    )

    tenant_id, _workspace = await _client(account)
    operator = _operator(tenant_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as upload:
            await upload_document(
                _Request(),  # type: ignore[arg-type]
                session,
                operator,
                None,  # type: ignore[arg-type]
                "business",
                "gst",
                None,  # type: ignore[arg-type]
            )
        with pytest.raises(ProblemError) as pledge:
            await accept_outbound_pledge(
                OutboundPledgeIn(
                    version=outbound_pledge.PLEDGE_VERSION,
                    text_sha256=outbound_pledge.PLEDGE_TEXT_SHA256,
                ),
                _Request(),  # type: ignore[arg-type]
                session,
                operator,
            )
    assert upload.value.detail == VIEW_AS_WITHHELD_ACTS["compliance.kyc_documents"]
    assert pledge.value.detail == VIEW_AS_WITHHELD_ACTS["compliance.outbound_pledge"]
