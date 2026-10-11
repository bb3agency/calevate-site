"""D-735: lead-source secrets are sealed at rest, and verifying a request still works.

The column holds `sealed:v1:...`, never the secret; the config the ingest path loads holds
the secret itself, so the constant-time compare and Meta's signature check are unchanged; a
plaintext row written before the migration still verifies; a rotation seals the new value
and keeps the old one verifying through its grace window; and a sealed value moved onto
another source's row does not open.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.ingest import service
from apps.api.ingest.sealed_secret import (
    SEALED_PREFIX,
    is_sealed,
    open_source_secret,
    seal_source_secret,
)
from sqlalchemy import text
from tests.api_security_test import _make_tenant


async def _columns(tenant_id: uuid.UUID, webhook_id: uuid.UUID) -> tuple[str, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT secret_ref, previous_secret_ref FROM inbound_webhooks WHERE id = :i"),
                {"i": webhook_id},
            )
        ).first()
    assert row is not None
    return str(row[0]), None if row[1] is None else str(row[1])


async def _source(tenant_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    async with tenant_session(tenant_id) as session:
        webhook_id, secret = await service.create_lead_source(
            session,
            tenant_id=tenant_id,
            source="website_form",
            agent_id=None,
            mapping={"phone": "phone_number"},
            supplied_secret=None,
        )
    assert secret
    return webhook_id, secret


async def _config(tenant_id: uuid.UUID, webhook_id: uuid.UUID) -> service.IngestConfig:
    async with tenant_session(tenant_id) as session:
        config = await service.load_config(session, webhook_id)
    assert config is not None
    return config


async def test_a_new_secret_is_sealed_in_the_column_and_still_verifies() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    webhook_id, secret = await _source(tenant_id)

    stored, _previous = await _columns(tenant_id, webhook_id)
    assert stored.startswith(SEALED_PREFIX)
    assert secret not in stored

    config = await _config(tenant_id, webhook_id)
    assert service.verify_ingest_secret(config, secret)
    assert not service.verify_ingest_secret(config, secret + "x")


async def test_a_rotation_seals_both_and_the_old_secret_verifies_through_its_grace() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    webhook_id, old = await _source(tenant_id)
    async with tenant_session(tenant_id) as session:
        rotation = await service.rotate_secret(
            session, webhook_id=webhook_id, grace_minutes=60, supplied_secret=None
        )
    assert rotation.secret

    current, previous = await _columns(tenant_id, webhook_id)
    assert is_sealed(current) and is_sealed(previous)
    config = await _config(tenant_id, webhook_id)
    assert service.verify_ingest_secret(config, rotation.secret)
    assert service.verify_ingest_secret(config, old)


async def test_a_plaintext_row_from_before_the_migration_still_verifies() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    webhook_id, _secret = await _source(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_webhooks SET secret_ref = 'legacy-plaintext' WHERE id = :i"),
            {"i": webhook_id},
        )
    config = await _config(tenant_id, webhook_id)
    assert service.verify_ingest_secret(config, "legacy-plaintext")


async def test_the_listing_fingerprints_the_secret_not_its_envelope() -> None:
    from apps.api.integrations.service import secret_fingerprint

    tenant_id, _slug, _token = await _make_tenant()
    webhook_id, secret = await _source(tenant_id)
    async with tenant_session(tenant_id) as session:
        listed = await service.list_lead_sources(session)
    (row,) = [item for item in listed if item.id == webhook_id]
    assert row.secret_fingerprint == secret_fingerprint(secret)


def test_a_sealed_value_moved_to_another_source_does_not_open() -> None:
    tenant_id, webhook_id = uuid.uuid4(), uuid.uuid4()
    sealed = seal_source_secret("s3cret", tenant_id=tenant_id, webhook_id=webhook_id)
    assert open_source_secret(sealed, tenant_id=tenant_id, webhook_id=webhook_id) == "s3cret"
    with pytest.raises(ProblemError):
        open_source_secret(sealed, tenant_id=tenant_id, webhook_id=uuid.uuid4())
    with pytest.raises(ProblemError):
        open_source_secret(sealed, tenant_id=uuid.uuid4(), webhook_id=webhook_id)
