"""A per-tenant crash in a background AI sweep is isolated AND alarmed.

Each of these sweeps catches one tenant's unexpected failure so the tenants behind it in
the list still run. Before, the catch only logged: a row that crashes its tenant on every
tick left that tenant's work undone indefinitely with nothing on `/admin/ops/alerts`. The
sibling sweeps (`retention`, `account_closure`, `forwarding`, `trials`) count such
failures and raise `<sweep>_incomplete`; these now do the same.

Every test drives the real job function over one fabricated tenant whose per-tenant step
raises, with the tick's preconditions stubbed, so nothing here needs a provider or a row.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from apps.workers import (
    caller_embeddings,
    caller_memory_distil,
    copilot_memory,
    kb_embeddings,
    kb_gloss,
)
from apps.workers.chat import ChatLeg

_LEG = ChatLeg(
    url="https://example.invalid/embeddings", api_key="k", wire_model="d", dialect="openai"
)
_TENANT = uuid.uuid4()


class _TenantCrashError(RuntimeError):
    """Not a provider error: the arm under test is the catch-all, not the transient one."""


def _crashing_tenant_session(_tenant_id: uuid.UUID) -> Any:
    raise _TenantCrashError("tenant step failed")


async def _one_tenant() -> list[uuid.UUID]:
    return [_TENANT]


async def _nothing_set_aside(_sweep: str) -> list[str]:
    return []


async def _true() -> bool:
    return True


def _capture_alerts(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[tuple[str, str]]:
    raised: list[tuple[str, str]] = []
    monkeypatch.setattr(module, "alert", lambda stage, code, **_kw: raised.append((stage, code)))
    return raised


async def test_knowledge_embedding_sweep_alarms_a_crashed_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised = _capture_alerts(monkeypatch, kb_embeddings)
    monkeypatch.setattr(kb_embeddings, "embedding_price_is_billable", lambda: True)
    monkeypatch.setattr(kb_embeddings, "embedding_leg", lambda: _LEG)
    monkeypatch.setattr(kb_embeddings, "_column_can_hold_our_vectors", _true)
    monkeypatch.setattr(kb_embeddings, "tenants_holding_knowledge", _one_tenant)
    monkeypatch.setattr(kb_embeddings, "set_aside_ids", _nothing_set_aside)
    monkeypatch.setattr(kb_embeddings, "tenant_session", _crashing_tenant_session)

    assert await kb_embeddings.embed_knowledge_chunks({}) == "embedded=0"
    assert raised == [("WORKER_TERMINAL", "kb_embed_sweep_incomplete")]


async def test_caller_embedding_sweep_alarms_a_crashed_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised = _capture_alerts(monkeypatch, caller_embeddings)

    @asynccontextmanager
    async def _session() -> AsyncIterator[object]:
        yield object()

    async def _spend(_session: object) -> Any:
        return SimpleNamespace(tripped=False)

    async def _crash(*_a: Any, **_kw: Any) -> None:
        raise _TenantCrashError("tenant step failed")

    monkeypatch.setattr(caller_embeddings, "registered_projections", lambda: ("scope",))
    monkeypatch.setattr(caller_embeddings, "embedding_price_is_billable", lambda: True)
    monkeypatch.setattr(caller_embeddings, "embedding_leg", lambda: _LEG)
    monkeypatch.setattr(caller_embeddings, "_column_can_hold_our_vectors", _true)
    monkeypatch.setattr(caller_embeddings, "tenants_with_caller_data", _one_tenant)
    monkeypatch.setattr(caller_embeddings, "untenanted_session", _session)
    monkeypatch.setattr(caller_embeddings, "read_platform_ai_spend", _spend)
    monkeypatch.setattr(caller_embeddings, "set_aside_ids", _nothing_set_aside)
    monkeypatch.setattr(caller_embeddings, "_sweep_tenant", _crash)

    assert await caller_embeddings.embed_caller_chunks({}) == "projected=0 embedded=0"
    assert raised == [("WORKER_TERMINAL", "caller_embed_sweep_incomplete")]


async def test_pip_memory_sweep_alarms_a_crashed_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    raised = _capture_alerts(monkeypatch, copilot_memory)

    class _Rows:
        def scalars(self) -> _Rows:
            return self

        def all(self) -> list[uuid.UUID]:
            return [_TENANT]

    class _Session:
        async def execute(self, *_a: Any, **_kw: Any) -> _Rows:
            return _Rows()

    @asynccontextmanager
    async def _session() -> AsyncIterator[_Session]:
        yield _Session()

    async def _brake(_session: object) -> bool:
        return False

    monkeypatch.setattr(copilot_memory, "background_leg", lambda *_a, **_kw: object())
    monkeypatch.setattr(copilot_memory, "untenanted_session", _session)
    monkeypatch.setattr(copilot_memory, "platform_brake_tripped", _brake)
    monkeypatch.setattr(copilot_memory, "set_aside_ids", _nothing_set_aside)
    monkeypatch.setattr(copilot_memory, "tenant_session", _crashing_tenant_session)

    assert await copilot_memory.distil_copilot_memories({}) == "groups=0 facts=0"
    assert raised == [("WORKER_TERMINAL", "copilot_distil_sweep_incomplete")]


async def test_caller_memory_sweep_alarms_a_crashed_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised = _capture_alerts(monkeypatch, caller_memory_distil)

    async def _crash(*_a: Any, **_kw: Any) -> None:
        raise _TenantCrashError("tenant step failed")

    monkeypatch.setattr(caller_memory_distil, "ENGINES_THAT_REMEMBER", frozenset())
    monkeypatch.setattr(caller_memory_distil, "background_leg", lambda *_a, **_kw: object())
    monkeypatch.setattr(caller_memory_distil, "tenants_with_caller_data", _one_tenant)
    monkeypatch.setattr(caller_memory_distil, "set_aside_ids", _nothing_set_aside)
    monkeypatch.setattr(caller_memory_distil, "_sweep_tenant", _crash)

    assert await caller_memory_distil.distil_caller_memories({}) == "calls=0 facts=0"
    assert raised == [("WORKER_TERMINAL", "caller_memory_distil_sweep_incomplete")]


async def test_knowledge_gloss_sweep_alarms_a_crashed_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raised = _capture_alerts(monkeypatch, kb_gloss)

    async def _no_rekey(_tenant_id: uuid.UUID) -> int:
        return 0

    monkeypatch.setattr(kb_gloss, "background_leg", lambda *_a, **_kw: object())
    monkeypatch.setattr(kb_gloss, "tenants_holding_knowledge", _one_tenant)
    monkeypatch.setattr(kb_gloss, "set_aside_ids", _nothing_set_aside)
    monkeypatch.setattr(kb_gloss, "tenant_session", _crashing_tenant_session)
    monkeypatch.setattr(kb_gloss, "_rekey_one_tenant", _no_rekey)

    assert await kb_gloss.write_knowledge_glosses({}) == "translated=0 not_needed=0 rekeyed=0"
    assert raised == [("WORKER_TERMINAL", "kb_gloss_sweep_incomplete")]
