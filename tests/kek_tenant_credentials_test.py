"""A KEK rotation must move clients' saved integration credentials, not only ours.

`integration_credentials` is sealed under the same PLATFORM_KEK as `platform_secrets`, and
the rewrap used to move only the second. The console's `pending` then read 0 while a
client's credential was still wrapped under the outgoing key, and removing
`PLATFORM_KEK_RETIRED` on the strength of that 0 makes the credential unreadable for good.

Every test walks ONLY the tenants it created (`tenant_ids=`): the walk re-wraps under the
ring it is handed, and re-wrapping a sibling suite's rows under a test key would break them.
Needs a migrated database.
"""

from __future__ import annotations

import base64
import uuid
from uuid import UUID

import pytest
from apps.api.actions import credentials as creds
from apps.api.actions.credentials import credential_context
from apps.api.admin import service as admin_service
from apps.api.core.envelope import Envelope, KekRing, build_ring, seal, unseal
from apps.api.db.session import tenant_session
from apps.api.ops.secret_service import count_tenant_credential_keks, rewrap_tenant_credentials
from sqlalchemy import text

SECRET = "aisensy-test-value-7f3a"

Row = tuple[bytes, bytes, bytes, bytes, int]


def _kek(seed: bytes) -> str:
    return base64.b64encode(seed * 32).decode()


def _ring(active: bytes, retired: bytes | None = None) -> KekRing:
    return build_ring(kek=_kek(active), retired=_kek(retired) if retired else None, app_env="prod")


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="KEK Co",
        slug=f"kek-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def _credential_under(tenant: UUID, ring: KekRing) -> UUID:
    """A credential row whose DEK is wrapped under a NAMED ring, not the process's own."""
    async with tenant_session(tenant) as session:
        record = await creds.create_credential(
            session, tenant_id=tenant, kind="aisensy", label="Main key", secret="placeholder"
        )
        envelope = seal(SECRET, context=credential_context(tenant, record.id), ring=ring)
        await session.execute(
            text(
                "UPDATE integration_credentials SET ciphertext = :ct, nonce = :n, "
                "dek_wrapped = :dw, dek_nonce = :dn, kek_version = :kek WHERE id = :id"
            ),
            {
                "ct": envelope.ciphertext,
                "n": envelope.nonce,
                "dw": envelope.dek_wrapped,
                "dn": envelope.dek_nonce,
                "kek": envelope.kek_id,
                "id": record.id,
            },
        )
    return record.id


async def _row(tenant: UUID, credential_id: UUID) -> Row:
    async with tenant_session(tenant) as session:
        row = (
            await session.execute(
                text(
                    "SELECT ciphertext, nonce, dek_wrapped, dek_nonce, kek_version "
                    "FROM integration_credentials WHERE id = :id"
                ),
                {"id": credential_id},
            )
        ).first()
    assert row is not None
    return bytes(row[0]), bytes(row[1]), bytes(row[2]), bytes(row[3]), int(row[4])


async def _opens_under(tenant: UUID, credential_id: UUID, ring: KekRing) -> str:
    ciphertext, nonce, dek_wrapped, dek_nonce, kek_id = await _row(tenant, credential_id)
    envelope = Envelope(
        ciphertext=ciphertext,
        nonce=nonce,
        dek_wrapped=dek_wrapped,
        dek_nonce=dek_nonce,
        kek_id=kek_id,
    )
    return unseal(envelope, context=credential_context(tenant, credential_id), ring=ring)


@pytest.mark.asyncio
async def test_a_rotation_moves_a_client_credential_and_it_opens_under_the_new_key() -> None:
    tenant = await _tenant()
    credential_id = await _credential_under(tenant, _ring(b"\x61"))
    before = await _row(tenant, credential_id)

    rotating = _ring(b"\x62", retired=b"\x61")
    counted = await count_tenant_credential_keks(ring=rotating, tenant_ids=[tenant])
    assert counted.total == 1 and counted.pending == 1 and counted.complete

    result = await rewrap_tenant_credentials(ring=rotating, tenant_ids=[tenant])
    assert result.examined == 1 and result.rewrapped == 1
    assert result.unreadable == () and result.complete

    after = await _row(tenant, credential_id)
    assert after[0] == before[0] and after[1] == before[1], "the payload was re-encrypted"
    assert after[2] != before[2], "the DEK wrapping did not move"
    assert after[4] == rotating.active.kek_id

    # Opens under the NEW key with no retired key at all: what makes removing it safe.
    only_new = _ring(b"\x62")
    assert await _opens_under(tenant, credential_id, only_new) == SECRET
    settled = await count_tenant_credential_keks(ring=only_new, tenant_ids=[tenant])
    assert settled.pending == 0


@pytest.mark.asyncio
async def test_a_mislabelled_client_credential_is_still_rewrapped() -> None:
    """D-96: the rewrap never trusts `kek_version`. A row wrapped under the old key but
    labelled with the new one must still be moved, or the next rotation loses it."""
    tenant = await _tenant()
    credential_id = await _credential_under(tenant, _ring(b"\x63"))
    rotating = _ring(b"\x64", retired=b"\x63")
    async with tenant_session(tenant) as session:
        await session.execute(
            text("UPDATE integration_credentials SET kek_version = :kek WHERE id = :id"),
            {"kek": rotating.active.kek_id, "id": credential_id},
        )

    result = await rewrap_tenant_credentials(ring=rotating, tenant_ids=[tenant])
    assert result.rewrapped == 1
    assert await _opens_under(tenant, credential_id, _ring(b"\x64")) == SECRET


@pytest.mark.asyncio
async def test_a_client_credential_no_key_opens_is_named_and_left_untouched() -> None:
    tenant = await _tenant()
    credential_id = await _credential_under(tenant, _ring(b"\x65"))
    before = await _row(tenant, credential_id)

    result = await rewrap_tenant_credentials(ring=_ring(b"\x66"), tenant_ids=[tenant])

    assert result.rewrapped == 0
    assert result.unreadable == (f"{tenant}:{credential_id}",)
    assert await _row(tenant, credential_id) == before
    assert SECRET not in repr(result)


@pytest.mark.asyncio
async def test_an_exhausted_walk_says_so_instead_of_reporting_a_subset() -> None:
    tenant = await _tenant()
    ring = _ring(b"\x67")
    await _credential_under(tenant, ring)

    counted = await count_tenant_credential_keks(ring=ring, tenant_ids=[tenant], budget_s=-1.0)
    rewrapped = await rewrap_tenant_credentials(ring=ring, tenant_ids=[tenant], budget_s=-1.0)

    assert counted.complete is False
    assert rewrapped.complete is False and rewrapped.examined == 0
