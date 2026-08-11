"""Two invariants that were previously only *nearly* true.

**A tenant is born in ONE transaction, or not at all.** Self-serve signup used to
build the tenant root (`admin/service.py::create_organization`), commit it, and only
then write the plan tier and the owner membership in a second transaction — with a
compensating soft-delete if that second half failed. A compensation is strictly worse
than not needing one: it can itself fail, and when it succeeds it leaves a
soft-deleted shell carrying a slug that is immutable and now permanently spent. The
test below makes the SECOND half fail and asserts there is no organization row at
all — not a soft-deleted one, none.

The failure is injected the way production would produce it: an owner `user_id` that
is not in `users`, so the membership INSERT trips the FK. Nothing is monkeypatched, so
the test cannot pass because a stub was wired to the wrong place.

**The top-up idempotency lookup cannot run outside the per-tenant lock.** The lookup
("is this payment reference already on the ledger?") lived in two modules, each
relying on its caller to take `lock_tenant_credits` first. Check-then-write outside
that lock is the exact bug that put duplicate pairs in this ledger, so the
consolidated `billing.service.find_topup` takes the lock ITSELF. The test asserts the
mechanism, not the location: while the lookup's own SELECT is executing, an
independent connection must NOT be able to take that tenant's credit lock.

CONCURRENCY: every query here is scoped to a slug or a tenant this test just minted.
Nothing enumerates `organizations` — the shared test database holds tens of thousands
of them from other suites running at the same time.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import credit_routes, payments
from apps.api.billing.service import find_topup, record_entry
from apps.api.db.session import admin_session, get_sessionmaker, tenant_session
from apps.api.tenancy import signup as signup_service
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# --- helpers ------------------------------------------------------------------


def _slug(tag: str) -> str:
    return f"atomic-{tag}-{uuid.uuid4().hex[:8]}"


async def _mirrored_user() -> uuid.UUID:
    """A Clerk user already mirrored into `users` — FLOWS §2 step 1's end state."""
    user_id = uuid.uuid4()
    async with admin_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:i, :c, :e, now(), now())"
            ),
            {"i": user_id, "c": f"user_{uuid.uuid4().hex[:12]}", "e": f"{user_id}@example.com"},
        )
    return user_id


async def _org_by_slug(slug: str) -> Any:
    """Look the org up BY SLUG, including soft-deleted rows.

    `admin_session` is the only session that can see an organization it is not scoped
    to, which is exactly what proving absence needs: a `tenant_session` sees nothing
    either way and would make this assertion pass for the wrong reason.
    """
    async with admin_session() as session:
        return (
            await session.execute(
                text("SELECT id, deleted_at, plan_tier FROM organizations WHERE slug = :s"),
                {"s": slug},
            )
        ).first()


async def _lock_is_free(tenant_id: uuid.UUID) -> bool:
    """Can an INDEPENDENT connection take this tenant's credit lock right now?

    `pg_try_advisory_xact_lock` never blocks, and this runs on its own connection, so
    it samples the lock without perturbing the transaction under test.
    """
    maker = get_sessionmaker()
    async with maker() as probe, probe.begin():
        got = (
            await probe.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"credit:{tenant_id}"},
            )
        ).scalar()
        return bool(got)


class _LockProbingSession:
    """A session proxy that samples the advisory lock at the moment the ledger lookup
    executes — the only instant at which "the lock is held" is the property that
    matters. Everything else is forwarded untouched to the real session."""

    def __init__(self, inner: Any, tenant_id: uuid.UUID) -> None:
        self._inner = inner
        self._tenant_id = tenant_id
        self.lock_free_at_lookup: bool | None = None

    async def execute(self, statement: Any, params: Any = None) -> Any:
        sql = str(statement)
        if "FROM credit_ledger" in sql and "reason = 'topup'" in sql:
            self.lock_free_at_lookup = await _lock_is_free(self._tenant_id)
        return await self._inner.execute(statement, params)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._inner, item)


# --- signup atomicity ---------------------------------------------------------


async def test_a_failed_owner_write_leaves_no_organization_at_all() -> None:
    """The whole point. The membership write fails (its user does not exist), and the
    org, its agent, its schema and its retention policies must all be gone with it —
    not soft-deleted, gone. A soft-deleted shell still owns the slug forever."""
    slug = _slug("ghost")
    ghost_user = uuid.uuid4()  # never mirrored into `users`

    with pytest.raises(IntegrityError):
        await signup_service.create_self_serve_tenant(
            user_id=ghost_user,
            name="Ghost Dental",
            slug=slug,
            vertical_template="clinic",
            language="te-IN",
            billing_email=None,
            plan_tier="self_serve",
        )

    row = await _org_by_slug(slug)
    assert row is None, (
        "a half-built tenant survived the failure — the row is "
        f"{'soft-deleted' if row is not None and row[1] is not None else 'live'}, and the "
        "slug it holds is immutable and now spent"
    )


async def test_a_failure_after_the_membership_also_rolls_the_tenant_back() -> None:
    """The audit row is written by the caller's hook INSIDE the birth transaction, so
    a failure there is not a late, unprotected step either. Same assertion, injected
    one statement further along."""
    slug = _slug("hook")
    user_id = await _mirrored_user()

    async def explode(_session: Any, _tenant_id: uuid.UUID) -> None:
        raise RuntimeError("the audit row could not be written")

    with pytest.raises(RuntimeError):
        await admin_service.create_organization(
            name="Hook Clinic",
            slug=slug,
            vertical_template="clinic",
            billing_email=None,
            language="te-IN",
            created_by=user_id,
            plan_tier="self_serve",
            owner_user_id=user_id,
            on_created=explode,
        )

    assert await _org_by_slug(slug) is None


async def test_the_slug_survives_the_failure_and_can_be_used_again() -> None:
    """The practical consequence of rolling back rather than compensating: the slug a
    failed attempt asked for is still available to the retry. Under the soft-delete it
    was held by a row nobody could reach and nobody could remove."""
    slug = _slug("retry")
    with pytest.raises(IntegrityError):
        await signup_service.create_self_serve_tenant(
            user_id=uuid.uuid4(),
            name="Retry Clinic",
            slug=slug,
            vertical_template="clinic",
            language="te-IN",
            billing_email=None,
            plan_tier="self_serve",
        )

    user_id = await _mirrored_user()
    created = await signup_service.create_self_serve_tenant(
        user_id=user_id,
        name="Retry Clinic",
        slug=slug,
        vertical_template="clinic",
        language="te-IN",
        billing_email=None,
        plan_tier="self_serve",
    )
    assert created["slug"] == slug
    assert created["plan_tier"] == "self_serve"


async def test_the_tier_and_the_owner_land_with_the_tenant() -> None:
    """One transaction still has to produce everything the two used to: the tier that
    tells the two motions apart, the owner membership, and the tenant root that could
    take a call."""
    user_id = await _mirrored_user()
    created = await signup_service.create_self_serve_tenant(
        user_id=user_id,
        name="Sunrise Dental",
        slug=_slug("whole"),
        vertical_template="clinic",
        language="te-IN",
        billing_email=None,
        plan_tier="trial",
    )
    tenant_id = created["id"]

    async with tenant_session(tenant_id) as session:
        tier = (
            await session.execute(
                text("SELECT plan_tier FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).scalar()
        role = (
            await session.execute(
                text("SELECT role FROM memberships WHERE tenant_id = :t AND user_id = :u"),
                {"t": tenant_id, "u": user_id},
            )
        ).scalar()
        disclosure = (
            await session.execute(
                text("SELECT disclosure_line FROM agents WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'organization.self_serve_created'"
                ),
                {"t": tenant_id},
            )
        ).scalar()

    assert tier == "trial"
    assert role == "owner"
    assert disclosure, "hard rule 5: the disclosure line is never null"
    assert int(audited or 0) == 1, "the audit row commits with the tenant, not after it"


async def test_a_managed_tenant_still_defaults_to_the_managed_tier() -> None:
    """The wizard passes neither new parameter, so the admin motion must be exactly
    what it was: managed tier, no membership (the operator invites the owner later)."""
    slug = _slug("wizard")
    created = await admin_service.create_organization(
        name="Wizard Clinic",
        slug=slug,
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    async with tenant_session(created["id"]) as session:
        members = (
            await session.execute(
                text("SELECT count(*) FROM memberships WHERE tenant_id = :t"),
                {"t": created["id"]},
            )
        ).scalar()
    row = await _org_by_slug(slug)
    assert row is not None and row[2] == "managed"
    assert int(members or 0) == 0


# --- the consolidated top-up lookup -------------------------------------------


async def _credit_tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Ledger Clinic",
        slug=_slug("ledger"),
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
        plan_tier="self_serve",
    )
    tenant_id: uuid.UUID = created["id"]
    return tenant_id


async def test_the_lookup_holds_the_lock_while_it_reads() -> None:
    """The property the consolidation exists to protect.

    A caller cannot reach this read without the lock, because the read takes the lock
    itself — so "check-then-write outside the lock" is not an ordering a future caller
    can choose. Sampled from an independent connection at the instant the SELECT runs.
    """
    tenant_id = await _credit_tenant()

    async with tenant_session(tenant_id) as session:
        assert await _lock_is_free(tenant_id) is True, "nothing holds the lock yet"
        probing = _LockProbingSession(session, tenant_id)
        found = await find_topup(probing, tenant_id=tenant_id, ref="UTR-LOCKED-1")

    assert found is None
    assert probing.lock_free_at_lookup is False, (
        "the ledger was read while the tenant's credit lock was free — a concurrent "
        "writer could have read the same 'not credited yet' and appended a second time"
    )


async def test_the_lock_the_lookup_takes_is_the_writers_lock() -> None:
    """Not just *a* lock: the same key `record_entry` and `charge_for_call` serialize
    on. A private lock would serialize the lookup against nothing that matters."""
    tenant_id = await _credit_tenant()

    async with tenant_session(tenant_id) as session:
        await find_topup(session, tenant_id=tenant_id, ref="UTR-LOCKED-2")
        assert await _lock_is_free(tenant_id) is False
        # And the writer can still proceed inside the SAME transaction: the advisory
        # lock is re-entrant per session, so taking it in the lookup does not deadlock
        # the record that follows it.
        balance = await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("500.00"),
            reason="topup",
            ref="UTR-LOCKED-2",
        )
    assert balance.amount_inr == Decimal("500.00")

    # Released at transaction end, like every `pg_advisory_xact_lock`.
    assert await _lock_is_free(tenant_id) is True


async def test_both_top_up_paths_use_the_one_lookup() -> None:
    """One query, one `reason = 'topup'` scoping rule, one lock discipline. Both
    callers must resolve to the function in `billing/service.py` — a second copy is
    how the two paths drift apart on the next fix."""
    assert payments.find_topup is find_topup
    assert credit_routes._find_topup is find_topup


async def test_the_lookup_ignores_a_usage_row_carrying_the_same_ref() -> None:
    """The scoping rule the consolidated function has to keep: a payment reference and
    a call id live in the same column, and crediting a wallet because a call happened
    to share the string would be a real, silent error."""
    tenant_id = await _credit_tenant()
    shared_ref = str(uuid.uuid4())

    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-10.00"),
            reason="usage",
            ref=shared_ref,
            allow_negative=True,
        )
        assert await find_topup(session, tenant_id=tenant_id, ref=shared_ref) is None

        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("300.00"), reason="topup", ref=shared_ref
        )
        found = await find_topup(session, tenant_id=tenant_id, ref=shared_ref)

    assert found is not None
    assert found.amount_inr == Decimal("300.0000")
    # The tuple shape is part of the contract — `payment_routes` indexes it positionally.
    assert found[1] == found.amount_inr
    assert found[0] == found.entry_id
