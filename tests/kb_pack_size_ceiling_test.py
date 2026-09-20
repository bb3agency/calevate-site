"""A pack too big to fetch is refused at PUBLISH, where somebody is standing.

WHAT THIS IS ABOUT, AND IT IS NOT DISK SPACE. The voice worker fetches the WHOLE pack while
the phone rings, under a fixed wall clock (`voice_worker/storage.PACK_FETCH_BUDGET_S`, 2.0 s).
A pack that does not arrive inside it is not a slow pack: `load_session_knowledge` answers
`fetch_failed`, and from then on every question on every call to that agent comes back
`temporarily_unavailable` — the agent answers the phone and cannot say one thing about the
client's business. Nothing on our side of the wire records that; the only trace is a log line
in a container a vendor operates, so a client could run that way for weeks.

Nothing bounded a pack's size, and nothing needs to bound it at the CALL, where the only
available answer is silence. It is bounded at the build, where the answer is an alarm naming
the size, the ceiling and what to prune.

No database: `publish_pack`'s size gate runs on the built pack's bytes, so a fake builder is
the whole fixture. What a pack CONTAINS when it is built from real published chunks is
`tests/kb_pack_test.py`'s subject.

Run: uv run pytest -q tests/kb_pack_size_ceiling_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from apps.api.kb import pack as kb_pack
from calevate_shared.knowledge_pack import KnowledgePack, PackEntry

TENANT = uuid.UUID("11111111-1111-7111-8111-111111111111")
AGENT = uuid.UUID("22222222-2222-7222-8222-222222222222")

#: The largest pack anybody in this tree has WEIGHED: 300 entries at 3072 dimensions, against
#: the bytes `publish_pack` uploads (`tests/in_call_lookup_latency_test.py`, 14 Sep 2026).
#: The ceiling has to sit above a corpus that size or it refuses a client the platform was
#: designed to serve.
WEIGHED_300_ENTRY_PACK_BYTES = 5_003_292


def _pack(*texts: str) -> KnowledgePack:
    entries = tuple(
        PackEntry(
            chunk_id=uuid.uuid5(AGENT, body),
            document_id=uuid.uuid5(TENANT, body),
            document_version=1,
            text=body,
        )
        for body in texts
    )
    entries = tuple(sorted(entries, key=lambda entry: str(entry.chunk_id)))
    return KnowledgePack(
        tenant_id=TENANT,
        agent_id=AGENT,
        content_sha256=KnowledgePack.digest(
            TENANT, AGENT, entries, embedding_model=None, embedding_dimensions=None
        ),
        built_at=datetime.now(UTC),
        entries=entries,
    )


class _Store:
    """The object store, as the two calls `publish_pack` makes of it."""

    def __init__(self, *, holds: bool = False) -> None:
        self.holds = holds
        self.written: list[str] = []

    async def read_kb_object(self, key: str) -> bytes | None:
        return b"{}" if self.holds else None

    async def store_knowledge_pack(self, *, key: str, data: bytes) -> None:
        self.written.append(key)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    """`publish_pack` defers its import of `apps.workers.storage` (boto3 is heavy and this
    module is reachable from a request path), so the patch goes on that module."""
    from apps.workers import storage

    fake = _Store()
    monkeypatch.setattr(storage, "read_kb_object", fake.read_kb_object)
    monkeypatch.setattr(storage, "store_knowledge_pack", fake.store_knowledge_pack)
    return fake


def _builds(monkeypatch: pytest.MonkeyPatch, pack: KnowledgePack) -> None:
    async def _build(session: Any, *, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> KnowledgePack:
        return pack

    monkeypatch.setattr(kb_pack, "build_pack", _build)


async def test_a_pack_over_the_ceiling_is_refused_and_nothing_is_stored(
    monkeypatch: pytest.MonkeyPatch, store: _Store
) -> None:
    """The refusal carries both numbers, because an operator's next question is "by how
    much?" and the answer decides whether one document or the whole corpus has to go."""
    _builds(monkeypatch, _pack("The clinic opens at 9 am.", "We are shut on Sunday."))
    monkeypatch.setattr(kb_pack, "MAX_PACK_BYTES", 64)

    with pytest.raises(kb_pack.PackTooLargeError) as refusal:
        await kb_pack.publish_pack(None, tenant_id=TENANT, agent_id=AGENT)

    assert refusal.value.ceiling == 64
    assert refusal.value.size > 64
    assert store.written == [], (
        "an oversize pack must not reach the bucket: a stored pack is one a session can be "
        "pointed at, and the point of the ceiling is that this one cannot be fetched in time"
    )


async def test_the_refusal_does_not_depend_on_what_the_bucket_already_holds(
    monkeypatch: pytest.MonkeyPatch, store: _Store
) -> None:
    """The size gate runs BEFORE the write-once existence check.

    Otherwise the same corpus refuses or publishes according to whether an earlier deploy —
    with a different ceiling, or none — happened to leave those bytes at that key, and the
    ceiling would be a property of the bucket's history rather than of the corpus.
    """
    store.holds = True
    _builds(monkeypatch, _pack("The clinic opens at 9 am."))
    monkeypatch.setattr(kb_pack, "MAX_PACK_BYTES", 64)

    with pytest.raises(kb_pack.PackTooLargeError):
        await kb_pack.publish_pack(None, tenant_id=TENANT, agent_id=AGENT)


async def test_a_pack_under_the_ceiling_publishes_unchanged(
    monkeypatch: pytest.MonkeyPatch, store: _Store
) -> None:
    """The gate is a ceiling and not a new shape: an ordinary corpus is stored exactly as
    it was, under the key its own digest names."""
    pack = _pack("The clinic opens at 9 am.")
    _builds(monkeypatch, pack)

    published = await kb_pack.publish_pack(None, tenant_id=TENANT, agent_id=AGENT)

    assert published == pack.content_sha256
    assert store.written == [f"knowledge-packs/{TENANT}/{AGENT}/{pack.content_sha256}.json"]


async def test_the_refusal_reaches_an_operator_with_its_own_alarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its OWN code, and the pointer does not move.

    `knowledge_pack_publish_failed` sends an operator to check a bucket that is healthy;
    this one names the corpus. Keeping the previous pointer is the best outcome available —
    the agent answers from the last pack that FITS, which is stale and coherent, rather than
    from one that cannot be fetched in time, which is `temporarily_unavailable` to every
    question on every call.
    """
    fired: list[tuple[str, str, dict[str, Any]]] = []
    monkeypatch.setattr(kb_pack, "alert", lambda stage, code, **kw: fired.append((stage, code, kw)))

    async def _refuse(session: Any, *, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
        raise kb_pack.PackTooLargeError(size=9_000_000, ceiling=kb_pack.MAX_PACK_BYTES)

    monkeypatch.setattr(kb_pack, "publish_pack", _refuse)

    class _Session:
        async def execute(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
            raise AssertionError("the pointer must not move when the pack was not stored")

    recorded = await kb_pack.refresh_published_pack(_Session(), tenant_id=TENANT, agent_id=AGENT)

    assert recorded is None
    assert [(stage, code) for stage, code, _ in fired] == [
        ("CORE_LOGIC", "knowledge_pack_too_large")
    ]
    detail = fired[0][2]["detail"]
    assert "9000000" in detail and str(kb_pack.MAX_PACK_BYTES) in detail
    # Hard rule 6: ids and numbers, never a client's words.
    assert fired[0][2]["tenant_id"] == str(TENANT)


def test_the_ceiling_clears_the_largest_pack_anybody_has_weighed() -> None:
    """A ceiling below a corpus the platform is designed to carry would refuse a real client
    rather than a runaway one. 300 vectored entries is the measured case."""
    assert kb_pack.MAX_PACK_BYTES > WEIGHED_300_ENTRY_PACK_BYTES
