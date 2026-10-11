"""Running an agent's saved tests spends like a try-chat, so it is gated like one.

`POST /v1/agents/{id}/test-cases/run` queued up to 20 tests x 6 caller lines against the
live agent with no AI-allowance check and no view-as withholding, while its sibling
try-chat had both.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.teach import routes


def _owner(**kw: object) -> Principal:
    return Principal(
        realm="client", user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner", **kw
    )  # type: ignore[arg-type]


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    runs: list[uuid.UUID] = []

    async def _visible(session: object, agent_id: uuid.UUID) -> None:
        return None

    async def _request_run(session: object, *, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> list:
        runs.append(agent_id)
        return []

    monkeypatch.setattr(routes, "assert_agent_visible", _visible)
    monkeypatch.setattr(routes.test_cases, "request_run", _request_run)
    return runs


async def test_an_account_at_its_ai_ceiling_queues_no_run(
    monkeypatch: pytest.MonkeyPatch, queued: list[uuid.UUID]
) -> None:
    async def _refuse(session: object, *, tenant_id: uuid.UUID) -> None:
        raise ProblemError(kind="business_rule", code="ai_quota_exceeded", title="t", detail="d")

    monkeypatch.setattr(routes, "require_ai_assist", _refuse)
    with pytest.raises(ProblemError) as refused:
        await routes.run_test_cases(uuid.uuid4(), session=object(), principal=_owner())  # type: ignore[arg-type]
    assert refused.value.code == "ai_quota_exceeded"
    assert queued == []


async def test_a_view_as_session_may_not_spend_the_clients_allowance_on_a_run(
    queued: list[uuid.UUID],
) -> None:
    viewer = Principal(
        realm="admin",
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role="operator",
        impersonating=True,
        impersonation_grant_id=uuid.uuid4(),
    )
    with pytest.raises(ProblemError) as refused:
        await routes.run_test_cases(uuid.uuid4(), session=object(), principal=viewer)  # type: ignore[arg-type]
    assert refused.value.status == 403
    assert queued == []
