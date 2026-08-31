"""The three things that must be true of a memory row AFTER it is written.

1. **Retention.** A row past the tenant's `copilot_memory` policy is swept, on the same
   nightly mechanism as every other category — and a tenant with memories and no published
   agent is REACHED by it, which is the D-368 hole this table would otherwise have
   re-opened.
2. **Erasure.** Tenant offboarding destroys every memory row, and the certificate says so.
   This is the arm that makes the store lawful to have at all: `redact()` keeps identifiers
   out, but it cannot recognise a proper noun, so "the account's memories are destroyed
   with the account" is doing real work rather than tidying up.
3. **Distillation.** The worker is idempotent, bounded, produces semantic rows, and never
   runs in a live turn.

The provider is stubbed. This suite asserts the JOB's contract — what it reads, what it
writes, what it refuses, what it spends — not what a model says; a test that needed a live
Azure key would assert nothing on any machine that has none.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import tenant_erasure
from apps.api.copilot import memory
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import chat, copilot_memory, retention
from sqlalchemy import text


async def _tenant_with_user() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Lifecycle Clinic",
        slug=f"mlc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    return tenant_id, user_id


async def _write(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    content: str,
    *,
    kind: str = memory.KIND_EPISODIC,
    age_days: float = 0.0,
    age_minutes: float = 0.0,
    route: str | None = "/agents",
) -> uuid.UUID:
    memory_id = uuid.uuid4()
    when = datetime.now(UTC) - timedelta(days=age_days, minutes=age_minutes)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO copilot_memories "
                "(id, tenant_id, user_id, kind, content, screen_route, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :kind, :content, :route, :at, :at)"
            ),
            {
                "id": memory_id,
                "tid": tenant_id,
                "uid": user_id,
                "kind": kind,
                "content": content,
                "route": None if kind == memory.KIND_SEMANTIC else route,
                "at": when,
            },
        )
    return memory_id


async def _count(tenant_id: uuid.UUID, *, kind: str | None = None) -> int:
    sql = "SELECT count(*) FROM copilot_memories"
    params: dict[str, Any] = {}
    if kind is not None:
        sql += " WHERE kind = :kind"
        params["kind"] = kind
    async with tenant_session(tenant_id) as session:
        return int((await session.execute(text(sql), params)).scalar_one())


# --- 1. retention -------------------------------------------------------------------


async def test_a_memory_past_its_policy_is_swept_and_a_fresh_one_is_not() -> None:
    tenant_id, user_id = await _tenant_with_user()
    async with tenant_session(tenant_id) as session:
        ttl = (
            await session.execute(
                text(
                    "SELECT ttl_days FROM retention_policies WHERE data_category = 'copilot_memory'"
                )
            )
        ).scalar_one()
    assert int(ttl) == 180, "every tenant gets the seeded policy at creation"

    expired = await _write(tenant_id, user_id, "Asked: an old question", age_days=int(ttl) + 5)
    # A DISTILLED FACT PAST THE SAME CLOCK. It is derived from episodes that are
    # themselves expiring, so keeping it would be the retelling outliving the thing it
    # retold — the D-126 shape on a new table.
    old_fact = await _write(
        tenant_id,
        user_id,
        "The clinic is closed on Sunday.",
        kind=memory.KIND_SEMANTIC,
        age_days=int(ttl) + 5,
    )
    kept = await _write(tenant_id, user_id, "Asked: a question from today")

    counts = await retention.sweep_tenant(tenant_id)
    assert counts["copilot_memories"] == 2

    async with tenant_session(tenant_id) as session:
        surviving = {
            uuid.UUID(str(row))
            for row in (await session.execute(text("SELECT id FROM copilot_memories")))
            .scalars()
            .all()
        }
    assert surviving == {kept}
    assert expired not in surviving
    assert old_fact not in surviving


async def test_the_nightly_sweep_reaches_a_tenant_that_only_has_memories() -> None:
    """The D-368 hole, closed for this table. A tenant whose agent was never published has
    no `engine_agent_routes` row, so without the worklist trigger its memories would never
    expire — a legal obligation switched off by an unrelated fact about their onboarding."""
    tenant_id, user_id = await _tenant_with_user()
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM engine_agent_routes WHERE tenant_id = :tid"), {"tid": tenant_id}
        )
    await _write(tenant_id, user_id, "Asked: something, before publishing anything")

    due = await retention._due_tenants()
    assert tenant_id in due


# --- 2. erasure ---------------------------------------------------------------------


async def test_tenant_erasure_destroys_every_memory_and_says_so() -> None:
    """Through the REAL deletion path — the worker, not a hand-written DELETE."""
    tenant_id, user_id = await _tenant_with_user()
    await _write(tenant_id, user_id, "Asked: what did the enquiry from Lakshmi say")
    await _write(tenant_id, user_id, "The clinic is closed on Sunday.", kind=memory.KIND_SEMANTIC)
    assert await _count(tenant_id) == 2

    request_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned', updated_at = now() WHERE id = :t"),
            {"t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO tenant_erasure_requests (id, tenant_id, reason, requested_at, "
                "created_at) VALUES (:id, :t, 'engagement ended', now(), now())"
            ),
            {"id": request_id, "t": tenant_id},
        )
    result = await retention.execute_tenant_erasure(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    assert result != "not_found"

    assert await _count(tenant_id) == 0, "a memory row surviving an erasure is a DPDP defect"

    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM tenant_erasure_requests WHERE id = :r"), {"r": request_id}
            )
        ).scalar()
    assert dict(proof)["scope"]["copilot_memories_erased"] == 2  # type: ignore[index]
    # The certificate a client reads must NAME what was destroyed, not imply it from a
    # number nobody renders.
    rendered = tenant_erasure.certificate(dict(proof))
    assert "assistant memor" in str(rendered).lower()


# --- 3. distillation ----------------------------------------------------------------


class _StubProvider:
    """Every `chat.complete` the tick makes, with the prompt it sent.

    COUNTED BY MARKER, NOT IN TOTAL, and that is not fussiness: this suite runs against a
    shared Postgres beside its siblings, `distil_copilot_memories` sweeps EVERY tenant on
    the worklist, and a bare `len(self.calls) == 1` would be an assertion about whichever
    other tests happened to leave undistilled rows behind. Each case marks its own
    episodes and asks only about calls whose prompt carries that marker.
    """

    def __init__(self, facts: list[str], *, usage: chat.TokenUsage | None = None) -> None:
        self.facts = facts
        self.calls: list[str] = []
        self.usage = usage or chat.TokenUsage(prompt_tokens=400, output_tokens=40)
        self.max_tokens: list[int | None] = []

    async def complete(self, leg: Any, messages: Any, **kwargs: Any) -> chat.ChatOutcome:
        self.calls.append("\n".join(str(message.get("content", "")) for message in messages))
        self.max_tokens.append(kwargs.get("max_tokens"))
        import json

        return chat.ChatOutcome(
            content=json.dumps({"facts": self.facts}),
            finish_reason="stop",
            usage=self.usage,
        )

    def calls_for(self, marker: str) -> int:
        return sum(1 for prompt in self.calls if marker in prompt)


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Azure 'configured', and `chat.complete` replaced. Returns a factory so a test can
    choose what the model says."""

    def install(facts: list[str], *, usage: chat.TokenUsage | None = None) -> _StubProvider:
        provider = _StubProvider(facts, usage=usage)
        monkeypatch.setattr(
            copilot_memory, "azure_credentials", lambda: ("res", "key", "gpt-4o-mini-dep")
        )
        monkeypatch.setattr(copilot_memory.chat, "complete", provider.complete)
        return provider

    return install


async def _quiet_conversation(
    tenant_id: uuid.UUID, user_id: uuid.UUID, turns: int = 3, *, marker: str = ""
) -> str:
    """`turns` episodes on one screen, all older than the idle window — i.e. a finished
    conversation as the job defines one. Returns the marker the prompt will carry."""
    marker = marker or f"mk{uuid.uuid4().hex[:10]}"
    for index in range(turns):
        await _write(
            tenant_id,
            user_id,
            f"Asked: turn {index} about opening hours {marker}",
            age_minutes=copilot_memory.IDLE_WINDOW_MINUTES + 10 + index,
        )
    return marker


async def test_the_job_writes_semantic_rows_and_marks_the_episodes(stub_provider: Any) -> None:
    tenant_id, user_id = await _tenant_with_user()
    marker = await _quiet_conversation(tenant_id, user_id)
    provider = stub_provider(["The clinic opens at nine.", "The owner writes in Telugu."])

    await copilot_memory.distil_copilot_memories({})

    assert provider.calls_for(marker) == 1
    assert set(provider.max_tokens) == {copilot_memory.DISTILL_MAX_TOKENS}, "the valve is set"
    assert await _count(tenant_id, kind=memory.KIND_SEMANTIC) == 2
    async with tenant_session(tenant_id) as session:
        undistilled = (
            await session.execute(
                text(
                    "SELECT count(*) FROM copilot_memories "
                    "WHERE kind = 'episodic' AND distilled_at IS NULL"
                )
            )
        ).scalar_one()
    assert int(undistilled) == 0, "the stamp IS the idempotency; it must land with the facts"


async def test_a_second_tick_neither_pays_again_nor_duplicates(stub_provider: Any) -> None:
    """Idempotency, asserted on the two things it protects: the bill and the row count."""
    tenant_id, user_id = await _tenant_with_user()
    marker = await _quiet_conversation(tenant_id, user_id)
    provider = stub_provider(["The clinic opens at nine."])

    await copilot_memory.distil_copilot_memories({})
    await copilot_memory.distil_copilot_memories({})

    assert provider.calls_for(marker) == 1, "a re-run must not re-read the same conversation"
    assert await _count(tenant_id, kind=memory.KIND_SEMANTIC) == 1


async def test_a_fact_learned_twice_is_stored_once(stub_provider: Any) -> None:
    """The second-order duplicate: the same fact out of two different conversations. The
    `NOT EXISTS` makes the semantic set converge instead of growing every hour."""
    tenant_id, user_id = await _tenant_with_user()
    await _quiet_conversation(tenant_id, user_id)
    stub_provider(["The clinic opens at nine."])
    await copilot_memory.distil_copilot_memories({})

    await _quiet_conversation(tenant_id, user_id)
    stub_provider(["The clinic opens at nine."])
    await copilot_memory.distil_copilot_memories({})

    assert await _count(tenant_id, kind=memory.KIND_SEMANTIC) == 1


async def test_a_live_conversation_is_left_alone(stub_provider: Any) -> None:
    """ "After a conversation ends" is the idle window, and a person still typing has not
    ended one. Distilling here would be paying for a conversation that is still going."""
    tenant_id, user_id = await _tenant_with_user()
    marker = f"mk{uuid.uuid4().hex[:10]}"
    for index in range(3):
        await _write(tenant_id, user_id, f"Asked: turn {index} {marker}", age_minutes=1)
    provider = stub_provider(["something"])

    await copilot_memory.distil_copilot_memories({})
    assert provider.calls_for(marker) == 0
    assert await _count(tenant_id, kind=memory.KIND_SEMANTIC) == 0


async def test_a_single_exchange_does_not_buy_a_model_call(stub_provider: Any) -> None:
    tenant_id, user_id = await _tenant_with_user()
    marker = await _quiet_conversation(tenant_id, user_id, turns=1)
    provider = stub_provider(["something"])
    await copilot_memory.distil_copilot_memories({})
    assert provider.calls_for(marker) == 0


async def test_the_output_is_bounded_in_count_length_and_content(stub_provider: Any) -> None:
    """Every bound is enforced HERE and not trusted to the prompt — a model that ignores
    all three instructions is an ordinary Tuesday (`copilot/service.validate_fill`'s
    argument, citing OWASP LLM01 #4)."""
    tenant_id, user_id = await _tenant_with_user()
    await _quiet_conversation(tenant_id, user_id)
    stub_provider(
        [f"Fact number {index} " + ("z" * 900) for index in range(20)]
        + ["Ring the owner on +91 98765 43210."]
    )

    await copilot_memory.distil_copilot_memories({})

    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    text("SELECT content FROM copilot_memories WHERE kind = 'semantic'")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) <= copilot_memory.MAX_FACTS_PER_GROUP
    assert all(len(str(row)) <= copilot_memory.MAX_FACT_CHARS for row in rows)
    assert all("98765" not in str(row) for row in rows)


async def test_a_tenant_with_no_language_credential_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tolerant boot: a deployment with no credential runs every other queue and says so
    at `/healthz/ready`, rather than crash-looping or alerting hourly."""
    monkeypatch.setattr(copilot_memory, "azure_credentials", lambda: None)
    assert await copilot_memory.distil_copilot_memories({}) == "no_provider"


async def test_the_tick_is_bounded_across_tenants(stub_provider: Any) -> None:
    """`MAX_GROUPS_PER_TENANT` is what stops one busy account owning the whole budget."""
    tenant_id, user_id = await _tenant_with_user()
    marker = f"mk{uuid.uuid4().hex[:10]}"
    for index in range(copilot_memory.MAX_GROUPS_PER_TENANT + 3):
        for turn in range(copilot_memory.MIN_EPISODES):
            await _write(
                tenant_id,
                user_id,
                f"Asked: screen {index} turn {turn} {marker}",
                route=f"/screen-{index}",
                age_minutes=copilot_memory.IDLE_WINDOW_MINUTES + 5,
            )
    provider = stub_provider(["A fact."])

    await copilot_memory.distil_copilot_memories({})
    assert provider.calls_for(marker) == copilot_memory.MAX_GROUPS_PER_TENANT


async def test_the_job_meters_what_it_spent(stub_provider: Any) -> None:
    """Hard rule 7. A model call that spent our credential is recorded, even though no
    client asked for it — and under its OWN feature name, so an operator can separate
    background spend from what a client triggered."""
    tenant_id, user_id = await _tenant_with_user()
    await _quiet_conversation(tenant_id, user_id)
    stub_provider(["The clinic opens at nine."])

    await copilot_memory.distil_copilot_memories({})

    async with tenant_session(tenant_id) as session:
        features = (
            (
                await session.execute(
                    text(
                        "SELECT meta ->> 'feature' FROM usage_events "
                        "WHERE unit_type LIKE 'ai_assist_ktok%'"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert "copilot_memory_distillation" in [str(f) for f in features]
