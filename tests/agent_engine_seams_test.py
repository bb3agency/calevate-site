"""The failure arms of the per-agent engine seams in `agents/service.py` (D-678).

Publishing registers three engine-side objects after the routing row — the results webhook,
the business-facts document and the in-call actions — and each failure must fail the
publish. What differs is the vendor agent: one THIS publish created is reclaimed, because
nothing of ours will ever point at it; one a re-publish was updating is the agent the
client's calls run on, and deleting it would take the agent off the air.

Unpublishing removes the in-call actions and the carrier's routing object, and a failure
there alarms without undoing the pause or archive.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

ENGINE = SimpleNamespace(name="fake")
REF = "vendor-agent-1"


def _unreachable() -> ProblemError:
    return ProblemError(kind="dependency", code="engine_unreachable", title="x", detail="x")


async def _webhook(agent_id: UUID, created: bool) -> None:
    await agents_service._ensure_results_webhook(
        ENGINE,  # type: ignore[arg-type]
        ref=REF,
        agent_id=agent_id,
        created=created,
        session=None,  # type: ignore[arg-type]
        rate_key="base",  # type: ignore[arg-type]
    )


async def _facts(agent_id: UUID, created: bool) -> None:
    await agents_service._publish_business_facts(
        ENGINE,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        agent_id=agent_id,
        ref=REF,
        created=created,
        script="[IDENTITY]\nReceptionist.\n",
    )


async def _actions(agent_id: UUID, created: bool) -> None:
    await agents_service._ensure_in_call_actions(
        ENGINE,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        agent_id=agent_id,
        ref=REF,
        created=created,
    )


SEAMS: list[tuple[str, Callable[[UUID, bool], Awaitable[None]], str]] = [
    ("ensure_agent_webhook", _webhook, "results_webhook_not_registered"),
    ("sync_business_facts", _facts, "business_facts_not_published"),
    ("ensure_agent_actions", _actions, "in_call_actions_not_registered"),
]


@pytest.fixture
def reclaimed(monkeypatch: pytest.MonkeyPatch) -> list[tuple[UUID, str, str]]:
    seen: list[tuple[UUID, str, str]] = []

    async def _reclaim(engine: Any, agent_id: UUID, ref: str, reason: str) -> None:
        seen.append((agent_id, ref, reason))

    monkeypatch.setattr(agents_service, "_reclaim_orphan", _reclaim)
    return seen


def _failing(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    async def _fail(*_: Any, **__: Any) -> None:
        raise _unreachable()

    monkeypatch.setattr(agents_service, name, _fail)


@pytest.mark.parametrize(("patched", "seam", "reason"), SEAMS)
async def test_a_failed_seam_on_a_first_publish_reclaims_the_vendor_agent(
    monkeypatch: pytest.MonkeyPatch,
    reclaimed: list[tuple[UUID, str, str]],
    patched: str,
    seam: Callable[[UUID, bool], Awaitable[None]],
    reason: str,
) -> None:
    _failing(monkeypatch, patched)
    agent_id = uuid7()
    with pytest.raises(ProblemError) as raised:
        await seam(agent_id, True)
    assert raised.value.code == "engine_unreachable"
    assert reclaimed == [(agent_id, REF, reason)]


@pytest.mark.parametrize(("patched", "seam", "reason"), SEAMS)
async def test_a_failed_seam_on_a_republish_keeps_the_live_vendor_agent(
    monkeypatch: pytest.MonkeyPatch,
    reclaimed: list[tuple[UUID, str, str]],
    patched: str,
    seam: Callable[[UUID, bool], Awaitable[None]],
    reason: str,
) -> None:
    _failing(monkeypatch, patched)
    with pytest.raises(ProblemError) as raised:
        await seam(uuid7(), False)
    assert raised.value.code == "engine_unreachable"
    assert reclaimed == [], "the agent the client's calls run on was deleted"


# --- unpublishing --------------------------------------------------------------------


@pytest.fixture
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    fired: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        agents_service,
        "alert",
        lambda stage, code, **kwargs: fired.append((stage, code, str(kwargs.get("detail")))),
    )
    return fired


async def test_actions_that_cannot_be_removed_alarm_and_do_not_fail_the_pause(
    monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str, str]]
) -> None:
    monkeypatch.setattr(agents_service, "get_engine", lambda: SimpleNamespace(name="thinnest"))
    _failing(monkeypatch, "retire_agent_actions")
    assert await agents_service.retire_in_call_actions(agent_id=uuid7(), ref=REF) == 0
    assert [(stage, code) for stage, code, _ in alerts] == [
        ("CORE_LOGIC", "engine_actions_not_retired")
    ]
    assert "engine_unreachable" in alerts[0][2]


class _BindingEngine:
    """An adapter whose carrier keeps a per-agent routing object (`RetiresAgentBindings`)."""

    name = "pipecat"

    def __init__(self, outcome: bool | ProblemError) -> None:
        self.outcome = outcome
        self.retired: list[str] = []

    async def retire_agent_bindings(self, ref: str) -> bool:
        self.retired.append(ref)
        if isinstance(self.outcome, ProblemError):
            raise self.outcome
        return self.outcome


async def test_an_archived_agents_carrier_binding_is_removed(
    monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str, str]]
) -> None:
    engine = _BindingEngine(True)
    monkeypatch.setattr(agents_service, "get_engine", lambda: engine)
    assert await agents_service.retire_agent_carrier_bindings(agent_id=uuid7(), ref=REF) is True
    assert engine.retired == [REF]
    assert alerts == []


async def test_a_carrier_binding_that_cannot_be_removed_alarms_and_keeps_the_archive(
    monkeypatch: pytest.MonkeyPatch, alerts: list[tuple[str, str, str]]
) -> None:
    engine = _BindingEngine(_unreachable())
    monkeypatch.setattr(agents_service, "get_engine", lambda: engine)
    assert await agents_service.retire_agent_carrier_bindings(agent_id=uuid7(), ref=REF) is False
    assert engine.retired == [REF]
    assert [(stage, code) for stage, code, _ in alerts] == [
        ("CORE_LOGIC", "carrier_binding_not_retired")
    ]
    assert "engine_unreachable" in alerts[0][2]
