"""The dial's tenant binding, and the absence of a platform carrier account (Model B).

Two different claims, kept in one file because an audit reads them as one:

1. **A dial cannot mix two tenants.** `agents.service.dispatch_call` is the platform's
   single outbound entry point and the only function in this tree that takes BOTH a
   tenant-scoped session and a `tenant_id`. It reads the agent, the DLT-registered header
   and the caller memory under the SESSION's `app.tenant_id`, and writes the `calls`
   intent row under `tenant_session(tenant_id)`. RLS cannot see a mismatch — each half is
   individually legal — so the binding is asserted explicitly and pinned here.
2. **There is no platform carrier ACCOUNT for a dial to be placed on.** Model B (D-474)
   makes the client the subscriber of record. The only carrier secrets this platform has
   a name for are `Settings.plivo_auth_id` / `plivo_auth_token`, which live in the
   `calevate-pipecat-worker` secret set and are read by Pipecat's own serializer to HANG
   UP (`DELETE /v1/Account/{auth_id}/Call/{call_id}/`). Nothing on the API, worker or
   voice-runtime side reads them, and that is what keeps a client's traffic off a
   Calevate carrier account. The last test fails the day some module starts.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents import service as agents_service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from sqlalchemy import text
from tests.conftest import accept_agreements

#: The two field names that would let an `apps/` module dial on OUR carrier account.
_PLATFORM_CARRIER_FIELDS = frozenset({"plivo_auth_id", "plivo_auth_token"})

#: The deployables that must never read them. `apps/voice-worker` is absent deliberately:
#: it is the one container that DOES hold the pair, for the hangup.
_MODEL_B_DEPLOYABLES = ("apps/api", "apps/workers", "apps/voice-runtime")


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inside TRAI's calling window, so nothing here is refused for the hour."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


class _SessionScopedTo:
    """Answers `session_tenant` and nothing else.

    A real session would need a database; what is under test is the ORDER — that the
    binding is checked before any agent, number or call row is touched — and a stub that
    can answer exactly one statement proves it by failing on the second.
    """

    def __init__(self, tenant_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id
        self.statements = 0

    async def execute(self, statement: Any, params: Any = None) -> Any:
        self.statements += 1
        if self.statements > 1:
            raise AssertionError(
                "dispatch_call read past the tenant binding check on a mismatched session"
            )
        return _Scalar(str(self.tenant_id))


class _Scalar:
    def __init__(self, value: str) -> None:
        self._value = value

    def scalar(self) -> str:
        return self._value


async def test_a_dial_refuses_a_session_scoped_to_another_tenant() -> None:
    """THE CROSS-TENANT DIAL, REFUSED AT THE CHOKEPOINT.

    Tenant A's session with tenant B named as the payer is the shape that would dial A's
    published agent, present A's DLT-registered header, and book the minutes, the wallet
    debit and the complaint trail to B. It is refused before the agent is read, so no
    lock is taken and no row is written on anyone's behalf.
    """
    session = _SessionScopedTo(uuid.uuid4())

    with pytest.raises(RuntimeError, match="different tenant"):
        await agents_service.dispatch_call(
            session,  # type: ignore[arg-type]
            tenant_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            lead_id=None,
            phone_e164="+919876543210",
        )

    assert session.statements == 1, "the binding must be the FIRST thing this dial asks"


async def test_an_untenanted_session_can_never_dial() -> None:
    """The fail-closed half: no GUC is not tenant zero, it is no tenant.

    `session_tenant` raises on an unset `app.tenant_id`, so a dial attempted from a
    worker or webhook path that forgot to open a tenant session stops here rather than
    running every read against a connection that sees nothing and calling that an answer.
    """

    class _Unscoped(_SessionScopedTo):
        async def execute(self, statement: Any, params: Any = None) -> Any:
            self.statements += 1
            return _Scalar("")

    session = _Unscoped(uuid.uuid4())
    with pytest.raises(RuntimeError, match="tenant-scoped session"):
        await agents_service.dispatch_call(
            session,  # type: ignore[arg-type]
            tenant_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            lead_id=None,
            phone_e164="+919876543210",
        )


def test_no_shared_deployable_reads_the_platform_carrier_credential() -> None:
    """MODEL A, PINNED OUT — by attribute access, not by grep.

    `Settings` carries the carrier pair so the credential has a row in the platform's own
    register (a name, an `env_var`, and the sentence saying it belongs in the Pipecat
    Cloud secret set). A READ of it from the API, the workers or voice-runtime would be a
    process on our side holding a carrier account's keys, which is the step from Model B
    to Model A and a legal decision rather than a code change
    (`campaigns/provisioning.PROVISIONING_IMPLEMENTED`).

    Matched on `ast.Attribute` so the many prose mentions — `core/settings.py`'s env-only
    reasons, `engine/pipecat.py`'s note on why there is no per-tenant store — do not read
    as uses. A string constant would find those and teach the next person to delete the
    explanations instead of the access.
    """
    repo_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for deployable in _MODEL_B_DEPLOYABLES:
        for path in sorted((repo_root / deployable).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in _PLATFORM_CARRIER_FIELDS:
                    offenders.append(f"{path.relative_to(repo_root)}:{node.lineno} .{node.attr}")

    assert not offenders, (
        "these modules read the platform's own carrier credential, which is Model A: "
        + ", ".join(offenders)
    )


# --- the database half ---------------------------------------------------------------


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Binding Properties",
        slug=f"binding-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    # Before publish, not after: `publish_agent` calls `assert_agreements_accepted` and
    # refuses an account that has not accepted them.
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Binding Properties.\n",
            notes=None,
            created_by=None,
        )
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, "
                "dlt_status, created_at, updated_at) VALUES (:id, :tid, :aid, :e, '160', "
                "'registered', now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                # Globally UNIQUE across tenants, so it is minted per call rather than
                # spelled as a constant this file would collide with itself on.
                "e": f"+91160{uuid.uuid4().int % 1000000:06d}",
            },
        )
        await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    return tenant_id, agent_id


@pytest.mark.rls
async def test_a_cross_tenant_dial_leaves_zero_call_rows_for_either_tenant() -> None:
    """Hard rule 1's zero-rows clause, asserted over the thing a dial actually produces.

    Refusing is not enough on its own: `dispatch_call` commits its intent row on a second
    connection before the engine is asked, so a guard that fired late would leave a
    `queued` call — a charge we may have incurred — attributed to the wrong client. Both
    tenants' `calls` tables must be empty afterwards, and tenant B's registered header
    must be unused.
    """
    tenant_a, agent_a = await _tenant()
    tenant_b, _agent_b = await _tenant()

    async with tenant_session(tenant_a) as session:
        with pytest.raises(RuntimeError, match="different tenant"):
            await agents_service.dispatch_call(
                session,
                tenant_id=tenant_b,
                agent_id=agent_a,
                lead_id=None,
                phone_e164="+919876543210",
            )

    for tenant_id in (tenant_a, tenant_b):
        async with tenant_session(tenant_id) as session:
            calls = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()
        assert calls == 0, f"a refused cross-tenant dial left a call row on {tenant_id}"


@pytest.mark.rls
async def test_a_matched_dial_still_places_the_call() -> None:
    """The guard must cost the ordinary path nothing — otherwise it is an outage.

    Same tenant on the session and in the argument, which is what every caller in the
    tree passes, so the dial runs to a handle and the call row lands under that tenant.
    """
    tenant_id, agent_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        handle = await agents_service.dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=None,
            phone_e164="+919876543210",
        )
    assert handle

    async with tenant_session(tenant_id) as session:
        owner = (
            await session.execute(
                text("SELECT agent_id FROM calls WHERE engine_call_id = :h"), {"h": handle}
            )
        ).scalar()
    assert owner == agent_id
