"""D-839: what the Our own model card reads — a client whose first set-up failed, where an
unofferable default is fixed, the clients the picker offers, and the cache share."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import own_model
from apps.api.agents.llm_models import (
    ACCESS_RESTRICTED_REASON,
    NO_ATTESTED_PRICE_REASON,
    NO_CREDENTIAL_REASON,
    NO_DEPLOYMENT_REASON,
)
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.catalogue import OwnVoiceKeyState
from apps.api.ops import own_model_cache
from apps.api.ops.hosted_voice_routes import default_fix
from apps.api.tenancy.engine_workspace import own_model_workspaces
from sqlalchemy import text
from tests.conftest import make_tenant_with_pip
from tests.own_model_test import _OwnModelEngine
from tests.thinnest_publish_limits_test import _agent_with_script
from tests.workspace_support import give_own_workspace


async def test_a_first_set_up_that_failed_is_kept_and_listed_as_not_on_our_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the failure record is rolled back with the refused publish (so the client
    never shows), or a client never on our key is listed as on it."""
    tenant_id, _slug, _token = await make_tenant_with_pip()
    workspace = await give_own_workspace(tenant_id)

    async def _fail(*_a: Any, **_k: Any) -> OwnVoiceKeyState:
        raise ProblemError(kind="dependency", code="engine_unreachable", title="t", detail="d")

    monkeypatch.setattr(own_model, "_switch_on", _fail)
    engine = _OwnModelEngine(
        OwnVoiceKeyState(enabled=False, scope=None, complete=False, using="none")
    )
    with pytest.raises(ProblemError):
        await own_model.ensure_own_model_workspace(
            engine,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            workspace=workspace,
        )
    enabled = frozenset(w.tenant_id for w in await own_model_workspaces())
    assert tenant_id not in enabled
    failures = await own_model.own_model_failures()
    pending = await own_model.pending_own_model_workspaces(enabled, failures)
    assert {p.tenant_id: p.error_code for p in pending}.get(tenant_id) == "engine_unreachable"

    # A later success forgets it, so the card stops listing the client.
    await own_model.forget_own_model_failure(tenant_id)
    assert tenant_id not in await own_model.own_model_failures()


@pytest.mark.parametrize(
    ("reason", "fix"),
    [
        (None, None),
        (NO_CREDENTIAL_REASON, "key"),
        (NO_ATTESTED_PRICE_REASON, "price"),
        (NO_DEPLOYMENT_REASON, "deployment"),
        (ACCESS_RESTRICTED_REASON, "default"),
        ("this platform does not run it", "default"),
    ],
)
def test_an_unofferable_default_names_where_it_is_fixed(
    reason: str | None, fix: str | None
) -> None:
    """FAILS IF: the card's "Price the model" step sends an operator to the prices for a
    model that no price can make answer."""
    assert default_fix(reason) == fix


async def _own_model_call(tenant_id: UUID, agent_id: UUID, meta: dict[str, Any]) -> UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'outbound', '+919876500002', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex}"},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                "'llm_ktok_in', 1, NULL, now(), CAST(:m AS jsonb), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id, "m": json.dumps(meta)},
        )
    return call_id


async def test_each_own_model_calls_cache_share_and_the_fleets() -> None:
    """FAILS IF: a call's cached share is misread, a call without counts is counted as zero
    cached, or the fleet figure leaves out a tenant's calls."""
    tenant_id, agent_id = await _agent_with_script("[BUSINESS]\nOrganics\n\n[GOAL]\nBook.")
    model = "gemini-3.1-flash-lite"
    cached = await _own_model_call(
        tenant_id,
        agent_id,
        {"own_model": model, "llm_input_tokens": 10_000, "llm_cached_input_tokens": 6_200},
    )
    uncounted = await _own_model_call(tenant_id, agent_id, {"own_model": model})
    async with tenant_session(tenant_id) as session:
        shares = await own_model_cache.call_cache_shares(session, [cached, uncounted])
    assert set(shares) == {cached}
    assert shares[cached].share == Decimal("0.6200")

    fleet = await own_model_cache.compute_fleet_cache_share()
    assert fleet.totals.cached_input_tokens >= 6_200
    assert fleet.totals.calls >= 1
    stored = await own_model_cache.refresh_fleet_cache_share()
    read = await own_model_cache.current_fleet_cache_share()
    assert read is not None and read.totals == stored.totals
