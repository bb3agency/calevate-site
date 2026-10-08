"""A dial the voice platform refused for its shared do-not-call list, not ours (D-691).

ThinnestAI's list is per workspace and every client shares it (`thinnest-findings/mirror/
snapshots/2026-10-08/pages/api-reference/errors.md:113-114`), so a refusal for a number that
is not on THIS client's list is `engine_platform_dnc_block`, and our list is left alone.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.agents import service as agents_service
from apps.api.compliance.platform_dnc import (
    ENGINE_PERSON_REFUSALS,
    PLATFORM_DNC_BLOCK_CODE,
    RECIPIENT_OPTED_OUT,
    platform_dnc_refusal,
)
from apps.api.compliance.service import add_to_dnc
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.vendor_http import RECIPIENT_OPTED_OUT_CODE, recipient_opted_out_error
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant


def test_the_adapter_code_is_spelled_once() -> None:
    assert RECIPIENT_OPTED_OUT == RECIPIENT_OPTED_OUT_CODE
    assert {RECIPIENT_OPTED_OUT_CODE, PLATFORM_DNC_BLOCK_CODE} == ENGINE_PERSON_REFUSALS
    assert PLATFORM_DNC_BLOCK_CODE in agents_service.DIAL_NOT_PLACED_CODES


async def test_only_a_number_off_our_lists_becomes_the_platform_block() -> None:
    tenant_id, _ = await _seed_tenant(f"fakeagent_{uuid.uuid4().hex[:10]}")
    listed = f"+9198765{uuid.uuid4().int % 100000:05d}"
    unlisted = f"+9197765{uuid.uuid4().int % 100000:05d}"
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=listed, source="manual")
    refused = recipient_opted_out_error()

    async with tenant_session(tenant_id) as session:
        block = await platform_dnc_refusal(
            session, refused, tenant_id=tenant_id, phone_e164=unlisted
        )
        ours = await platform_dnc_refusal(session, refused, tenant_id=tenant_id, phone_e164=listed)
        other = await platform_dnc_refusal(
            session, ProblemError.not_found("Agent"), tenant_id=tenant_id, phone_e164=unlisted
        )
        stranger = await platform_dnc_refusal(
            session, RuntimeError("x"), tenant_id=tenant_id, phone_e164=unlisted
        )

    assert block is not None and block.code == PLATFORM_DNC_BLOCK_CODE
    assert block.title == "Blocked by the voice platform's do-not-call list"
    assert (ours, other, stranger) == (None, None, None)


async def test_a_dial_the_platform_refuses_is_closed_with_the_platform_code_and_not_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through the one outbound entry point: nothing rang, the intent row is closed with
    the distinct code, and the client's own list gains nothing."""
    tenant_id, agent_id = await _seed_tenant(f"fakeagent_{uuid.uuid4().hex[:10]}")
    phone = f"+9196765{uuid.uuid4().int % 100000:05d}"

    async def _refused(*_a: object, **_k: object) -> str:
        raise recipient_opted_out_error()

    monkeypatch.setattr(get_engine(), "start_outbound_call", _refused)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await agents_service.dispatch_call(
                session, tenant_id=tenant_id, agent_id=agent_id, lead_id=None, phone_e164=phone
            )
    assert raised.value.code == PLATFORM_DNC_BLOCK_CODE

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM calls WHERE tenant_id = :tid AND to_e164 = :p"),
                {"tid": tenant_id, "p": phone},
            )
        ).scalar_one()
        listed = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE tenant_id = :tid"), {"tid": tenant_id}
            )
        ).scalar_one()
    assert status == "failed"
    assert listed == 0
