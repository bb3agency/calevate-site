"""The policy registry, the role table, and the step-up vocabulary — checked for the
failures that leave everything looking green.

`tests/api_security_test.py` proves the registry refuses a route with NO declaration and
that it refuses to run against an empty route table. `tests/authz_audit_test.py` proves
it catches a declaration with nothing enforcing it and a declaration that disagrees with
the lock. All four are about the RELATIONSHIP between a label and a lock. None of them
asks whether the label MEANS anything, and until this file the answer was that it did
not have to: `permission_meta("agents:reed")` beside `requires("agents:reed")` satisfied
every one of those checks, because two copies of one typo agree with each other.

Three properties are asserted here, and each closes a way the registry could pass
vacuously:

  1. A DECLARED PERMISSION IS A REAL ONE — in the `Permission` Literal, and held by at
     least one role. A permission no role holds is a lock with no key: `role_has`
     answers False for every role the database allows, so the route 403s the entire
     population while reading as guarded.
  2. THE ROLE TABLE MATCHES POSTGRES. `ROLE_PERMISSIONS` is one flat dict holding BOTH
     realms' roles, so the separation of `owner`/`staff` from `operator`/`superadmin` is
     a naming convention in Python and a CHECK constraint in the database. The
     constraint is the enforcement; this test is what keeps Python from drifting away
     from it and inventing a client role that holds `ops:manage`.
  3. STEP-UP CONFIRMATIONS ARE UNIQUE PER ACTION. `require_step_up` is string equality,
     so the whole guarantee "a confirmation captured for one action cannot be replayed
     against another" reduces to whether any two actions spell themselves the same way.
     Asserted over the vocabulary AND driven across two live routes.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

import pytest
from apps.api.admin.routes import spend_ceiling_confirmation
from apps.api.billing.credit_routes import (
    credit_adjustment_confirmation,
    topup_restatement_confirmation,
)
from apps.api.compliance.national_dnd_routes import (
    SUPPRESS_GLOBALLY_CONFIRMATION,
    preference_scrub_confirmation,
    release_globally_confirmation,
)
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.rbac import (
    GRANTED_PERMISSIONS,
    KNOWN_PERMISSIONS,
    MUTATING_PERMISSIONS,
    PUBLIC_PREFIXES,
    ROLE_PERMISSIONS,
    MissingPolicyError,
    assert_policy_registry_complete,
    iter_api_routes,
    permission_meta,
    role_has,
)
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops.config_routes import config_confirmation, revert_confirmation
from apps.api.ops.routes import (
    OUTBOX_REPLAY_CONFIRMATION,
    outbox_replay_confirmation,
    platform_confirmation,
    spend_cap_confirmation,
)
from apps.api.ops.secret_routes import REWRAP_CONFIRMATION, secret_confirmation
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

# Aliases at module level for the throwaway apps below: `Depends()` in a signature
# default is B008 inside a function body, and a CapWords local is N806. Same idiom as
# `tests/authz_audit_test.py`.
AgentReader = Annotated[Principal, Depends(requires("agents:read"))]
# A permission that exists in the type but that no role in ROLE_PERMISSIONS holds would
# be spelled here. There is none — which is the point of
# `test_every_permission_the_type_admits_is_held_by_somebody` — so the unheld case is
# built by taking a permission away from every role instead.
DirectoryReader = Annotated[Principal, Depends(requires("admin:tenants"))]

#: The two realms' role names, as the database's CHECK constraints spell them. Restated
#: here rather than imported so the test compares two independently-written statements
#: of the same fact; the constraint text itself is read from Postgres below.
CLIENT_ROLES = frozenset({"owner", "staff"})
ADMIN_ROLES = frozenset({"operator", "superadmin"})

#: Permission prefixes that describe acting on the PLATFORM or across tenants. A client
#: realm role holding one of these would be a tenant's own staff member with a lever on
#: everybody else's service.
ADMIN_ONLY_PREFIXES = ("admin:", "ops:", "platform:")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


# ------------------------------------------------------- 1. the declaration means something


def test_the_registry_refuses_a_permission_that_does_not_exist() -> None:
    """The vacuity this file exists for, exercised on the mistake that produces it.

    A typo copied into both halves of the decorator — `permission_meta("agents:reed")`
    and `requires("agents:reed")` — used to pass the boot assertion: declared equals
    enforced, an identity is resolved, nothing is missing. `role_has` then answered
    False for every role the database allows, so the route was a 403 for the entire
    population. Nobody notices, because a route nobody can call has no happy-path test
    to go red.

    mypy is the other half of this guard and catches the literal spelling. It does not
    run at boot, it does not see a permission assembled from a variable, and it does not
    look at the route table the process is about to serve.
    """
    misspelled = FastAPI()
    Typo = Annotated[Principal, Depends(requires("agents:reed"))]  # type: ignore[arg-type]  # noqa: N806

    @misspelled.get("/v1/typo", openapi_extra=permission_meta("agents:reed"))  # type: ignore[arg-type]
    async def _typo(_: Typo) -> dict[str, str]:
        return {"ok": "ok"}

    with pytest.raises(MissingPolicyError, match="not a Permission") as raised:
        assert_policy_registry_complete(misspelled)
    assert "agents:reed" in str(raised.value), "the failure must name the string to fix"


def test_the_registry_refuses_a_permission_no_role_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A correctly spelled permission that is a lock with no key.

    This is the direction the typo test cannot reach, because it is not a typo: someone
    adds `platform:secrets` to the `Permission` type and to a route, and forgets the
    role table — or removes the permission from the last role that held it while the
    route stays. Either way `role_has` refuses every caller and the console shows a
    control that can only ever 403.

    The refusal names the role table rather than the route, because that is where the
    fix goes: the route is right and nobody has been given the key.
    """
    stripped = FastAPI()

    @stripped.get("/v1/directory", openapi_extra=permission_meta("admin:tenants"))
    async def _directory(_: DirectoryReader) -> dict[str, str]:
        return {"ok": "ok"}

    # The control: with the role table as shipped, this route is fine.
    assert_policy_registry_complete(stripped)

    for role, permissions in ROLE_PERMISSIONS.items():
        monkeypatch.setitem(ROLE_PERMISSIONS, role, frozenset(permissions - {"admin:tenants"}))
    monkeypatch.setattr(
        "apps.api.core.rbac.GRANTED_PERMISSIONS",
        frozenset[str]().union(*ROLE_PERMISSIONS.values()),
    )

    with pytest.raises(MissingPolicyError, match="no role in ROLE_PERMISSIONS holds"):
        assert_policy_registry_complete(stripped)


def test_the_new_clauses_do_not_reject_the_shape_every_real_route_uses() -> None:
    """The control for both checks above, and the reason the live app is asserted
    separately below: a guard that refused the ordinary case would be discovered by the
    boot assertion, but only after every other test in this file had already gone red
    for the wrong reason."""
    proper = FastAPI()

    @proper.get("/v1/proper", openapi_extra=permission_meta("agents:read"))
    async def _proper(_: AgentReader) -> dict[str, str]:
        return {"ok": "ok"}

    assert_policy_registry_complete(proper)


def test_every_permission_the_live_route_table_declares_is_real_and_reachable() -> None:
    """The same two properties, asserted about the app that actually ships.

    `assert_policy_registry_complete(app)` runs at boot and would catch these, but it
    catches them as one opaque failure among several; a reviewer reading THIS file
    should be able to see the live table stated in the terms the checks use.
    """
    declared = {
        str((route.openapi_extra or {}).get("x-calevate-permission"))
        for route in iter_api_routes(app)
        if not any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES)
        and (route.openapi_extra or {}).get("x-calevate-permission")
    }
    assert declared, "no route declares a permission — route discovery is broken"
    assert declared <= KNOWN_PERMISSIONS, sorted(declared - KNOWN_PERMISSIONS)
    assert declared <= GRANTED_PERMISSIONS, sorted(declared - GRANTED_PERMISSIONS)


def test_every_permission_the_type_admits_is_held_by_somebody() -> None:
    """The other direction: a `Permission` in the Literal that no role holds.

    It is not yet a broken route — a permission can legitimately exist before the route
    that uses it — but it is a permission that will break the FIRST route to declare it,
    at boot, in whatever change happened to add that route rather than in the change
    that left the gap. Held to equality so both drifts are caught.
    """
    assert KNOWN_PERMISSIONS == GRANTED_PERMISSIONS, {
        "in the type, held by no role": sorted(KNOWN_PERMISSIONS - GRANTED_PERMISSIONS),
        "held by a role, not in the type": sorted(GRANTED_PERMISSIONS - KNOWN_PERMISSIONS),
    }


def test_every_mutating_permission_is_a_permission() -> None:
    """`MUTATING_PERMISSIONS` is what D-22's read-only rule is made of. An entry that is
    not a real permission would silently protect nothing — `requires()` compares the
    route's permission against this set, and a member nothing declares is never hit."""
    assert MUTATING_PERMISSIONS <= KNOWN_PERMISSIONS
    declared = {
        (route.openapi_extra or {}).get("x-calevate-permission") for route in iter_api_routes(app)
    }
    unused = MUTATING_PERMISSIONS - declared
    assert not unused, f"MUTATING_PERMISSIONS names permissions no route declares: {sorted(unused)}"


# ------------------------------------------------------------- 2. the role table vs Postgres


async def test_the_python_role_table_names_exactly_the_roles_postgres_allows() -> None:
    """DATABASE-ENFORCED, not application-enforced — and that is why this test reads
    the constraint instead of asserting a behaviour.

    `ROLE_PERMISSIONS` is ONE dict holding both realms' roles, so nothing in Python
    stops a client `owner` and an admin role sharing a name; if they ever did, a client
    owner would silently inherit that admin role's permission set on every
    `realm="any"` route. What actually prevents it is Postgres:
    `ck_memberships_role_enum` admits only `owner`/`staff` and
    `ck_admin_users_role_enum` only `operator`/`superadmin`, so a colliding role cannot
    be STORED and no principal can ever carry one.

    THIS TEST CANNOT BE MADE RED FROM APPLICATION CODE. Adding a colliding key to
    `ROLE_PERMISSIONS` breaks it here (which is the drift worth catching), but removing
    the guarantee itself means dropping a CHECK constraint in a migration — the
    sabotage for it is `ALTER TABLE ... DROP CONSTRAINT`, not an edit to a `.py` file.
    What is asserted is the correspondence: the two statements of one fact agree.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT conrelid::regclass::text, pg_get_constraintdef(oid) "
                    "FROM pg_constraint "
                    "WHERE conname IN ('ck_memberships_role_enum', 'ck_admin_users_role_enum')"
                )
            )
        ).all()
    definitions = {str(table): str(definition) for table, definition in rows}
    assert set(definitions) == {"memberships", "admin_users"}, (
        f"a role CHECK constraint is missing from this database: {sorted(definitions)}"
    )

    for role in CLIENT_ROLES:
        assert f"'{role}'" in definitions["memberships"], definitions["memberships"]
        assert f"'{role}'" not in definitions["admin_users"], (
            f"{role} is accepted on BOTH tables — one flat ROLE_PERMISSIONS dict makes "
            "that a permission merge, not a naming coincidence"
        )
    for role in ADMIN_ROLES:
        assert f"'{role}'" in definitions["admin_users"], definitions["admin_users"]
        assert f"'{role}'" not in definitions["memberships"], definitions["memberships"]

    assert set(ROLE_PERMISSIONS) == CLIENT_ROLES | ADMIN_ROLES, (
        "ROLE_PERMISSIONS and the database disagree about which roles exist: "
        f"{sorted(ROLE_PERMISSIONS)}"
    )


def test_no_client_realm_role_holds_a_platform_permission() -> None:
    """The consequence the constraint above protects, stated directly.

    A tenant's own `owner` is the most privileged principal inside one account and must
    stay inside it. `admin:*` acts across tenants, `ops:*` is the incident surface (the
    big red switch, the DLQ replay) and `platform:*` changes what every client's
    platform does at once — none of them is a thing a client's staff member holds,
    however senior they are in their own business.
    """
    for role in CLIENT_ROLES:
        crossings = sorted(
            permission
            for permission in ROLE_PERMISSIONS[role]
            if permission.startswith(ADMIN_ONLY_PREFIXES)
        )
        assert not crossings, f"client role {role!r} holds platform permissions: {crossings}"
        # And the reverse reading, so the assertion above cannot pass by the prefixes
        # being renamed: a client role must not hold what only superadmin should.
        assert not role_has(role, "ops:manage")
        assert not role_has(role, "platform:secrets")


def test_the_client_realm_roles_are_ordered_by_containment() -> None:
    """`staff` ⊂ `owner`, asserted rather than eyeballed.

    Two frozensets written out longhand drift by one line at a time: the failure mode is
    a permission added to `staff` and not to `owner`, which makes the account's owner
    less able than their own staff and is discovered by a client, not by us.
    """
    assert ROLE_PERMISSIONS["staff"] < ROLE_PERMISSIONS["owner"]
    assert ROLE_PERMISSIONS["operator"] < ROLE_PERMISSIONS["superadmin"]
    # The one client permission an owner has and nobody should be able to add to staff
    # without noticing: raw transcripts are hard rule 5's role check.
    assert role_has("owner", "calls:read_raw")
    assert not role_has("staff", "calls:read_raw")


# ------------------------------------------------------------- 3. the step-up vocabulary


def _confirmation_vocabulary() -> dict[str, str]:
    """Every step-up string this repo can produce, keyed by the action it confirms.

    Built by CALLING the builders rather than by quoting their output, so a reformat of
    any one of them is compared against the others as they are today. The parametrised
    ones are all fed the SAME argument on purpose: two builders that both render
    `f"<verb>:{id}"` would only collide when the ids match, which is exactly the case an
    operator hits — one incident, one tenant, two confirmations captured minutes apart.
    """
    subject = uuid.UUID("00000000-0000-0000-0000-000000000001")
    key = "SARVAM_API_KEY"
    return {
        "halt_outbound": platform_confirmation(outbound_halted=True, load_shed_mode=None),
        "release_outbound": platform_confirmation(outbound_halted=False, load_shed_mode=None),
        "set_load_shed": platform_confirmation(outbound_halted=None, load_shed_mode="reduced"),
        "halt_and_shed": platform_confirmation(outbound_halted=True, load_shed_mode="reduced"),
        "recompute_spend_cap": spend_cap_confirmation(subject),
        "raise_spend_ceiling": spend_ceiling_confirmation(subject),
        "adjust_credits": credit_adjustment_confirmation(subject),
        "restate_topup": topup_restatement_confirmation("UTR-1", Decimal("900.00")),
        "record_preference_scrub": preference_scrub_confirmation(subject),
        "set_config": config_confirmation(key),
        "revert_config": revert_confirmation(key),
        "set_secret": secret_confirmation(key),
        "replay_one_job": outbox_replay_confirmation("deliver_lead"),
        "replay_all_jobs": OUTBOX_REPLAY_CONFIRMATION,
        "rewrap_keks": REWRAP_CONFIRMATION,
        "suppress_number": SUPPRESS_GLOBALLY_CONFIRMATION,
        "release_number": release_globally_confirmation(subject),
        # Not a builder — the route computes it inline from the requested direction
        # (`ops/routes.py::set_tm_registration_route`), which is why it is written out.
        "record_tm_registration": "record_tm_registration",
        "withdraw_tm_registration": "withdraw_tm_registration",
    }


def test_no_two_step_up_actions_spell_themselves_the_same_way() -> None:
    """`require_step_up` is `confirm != action`. Everything the header buys — "the
    confirmation captured for one action cannot be replayed against another" — is
    therefore a property of the VOCABULARY and of nothing else.

    Collisions in a set of nineteen strings across six modules are not hypothetical:
    every one of these is `<verb>` or `<verb>:<subject>`, the verbs are chosen by
    whoever wrote the route, and two of them are one synonym apart
    (`release_outbound` / `release_number_platform_wide`).

    THE ONE UNPARAMETRISED DNC STRING IS NOT AN OVERSIGHT, and its sibling stopped
    being one. `suppress_number_platform_wide` names the act and not the number because
    its subject is a LIST of numbers in the body: binding it would put phone numbers in a
    request header, which hard rule 6 forbids and which access logs, referrers and
    browser history would then carry. `release_number_platform_wide` used to be bare for
    the same stated reason, and that reason did not apply to it — its subject is an
    `entry_id` that is already the last path segment — so it now carries that id like
    every other subject-bearing confirmation, and a header typed for one suppression can
    no longer lift a different one (D-141).
    """
    vocabulary = _confirmation_vocabulary()
    by_string: dict[str, list[str]] = {}
    for action, confirmation in vocabulary.items():
        by_string.setdefault(confirmation, []).append(action)
    collisions = {string: actions for string, actions in by_string.items() if len(actions) > 1}
    assert not collisions, f"one confirmation string authorises several actions: {collisions}"

    # A prefix collision is the near miss: `replay_dead_letters` is deliberately the
    # "every job" string AND the prefix of the per-job one, which is safe only because
    # the comparison is equality. Stated here so a future move to `startswith` — which
    # would look like a kindness to operators — fails a test instead of a client.
    assert vocabulary["replay_one_job"].startswith(vocabulary["replay_all_jobs"])
    assert vocabulary["replay_one_job"] != vocabulary["replay_all_jobs"]


async def test_a_confirmation_for_one_route_does_not_authorise_another() -> None:
    """The vocabulary test's behavioural half, across two DIFFERENT routes.

    `tests/platform_halt_test.py` already swaps confirmations WITHIN `POST /v1/ops/
    platform`. The cross-route case is the one an operator actually generates: they hold
    a valid, freshly-typed header for the action they just performed, and the next
    request in the runbook is a different endpoint.

    Refusals only — neither request below changes any state, so this runs beside every
    other suite on the shared database.
    """
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    auth = {"Authorization": f"Bearer dev:admin:{admin_id}"}

    async with _client() as http:
        # A header captured for the TM-registration route, replayed at the big red switch.
        halt_with_registration_header = await http.post(
            "/v1/ops/platform",
            headers={**auth, "X-Confirm-Action": "record_tm_registration"},
            json={"outbound_halted": True, "reason": "replayed from another route"},
        )
        # And the reverse: the halt confirmation replayed at TM registration, which is
        # the more dangerous direction — it turns every tenant's launch gate green.
        registration_with_halt_header = await http.post(
            "/v1/ops/platform/tm-registration",
            headers={**auth, "X-Confirm-Action": "halt_outbound"},
            # A COMPLETE, VALID body. `require_step_up` runs inside the handler, so
            # Pydantic validates first — a request that is refused for a missing field
            # would prove nothing about the confirmation, which is the trap this comment
            # exists to keep the next author out of.
            json={
                "status": "active",
                "tm_id": "TM-REPLAY-0000000001",
                "registered_at": "2026-01-01T00:00:00Z",
                "reason": "replayed from the halt confirmation",
            },
        )

    for name, response in (
        ("halt_with_registration_header", halt_with_registration_header),
        ("registration_with_halt_header", registration_with_halt_header),
    ):
        assert response.status_code == 403, f"{name}: {response.text}"
        body = response.json()
        assert body["type"].endswith("/step_up_required"), f"{name}: {body}"
        assert "X-Confirm-Action: " in body["remediation"], (
            f"{name}: an operator mid-incident must be told the exact header, not sent "
            "to read the source"
        )


async def test_a_missing_confirmation_is_a_refusal_and_not_a_silent_proceed() -> None:
    """The base case, on a route whose effect would be platform-wide.

    Worth its own test because the failure it guards against is invisible: a
    `require_step_up` call moved below the work, or an `if confirm and confirm != action`
    that reads as defensive and turns the whole control off for any caller who simply
    omits the header. The state is re-read afterwards and asserted unchanged.
    """
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    auth = {"Authorization": f"Bearer dev:admin:{admin_id}"}

    async with untenanted_session() as session:
        before = (
            await session.execute(text("SELECT outbound_halted FROM platform_state WHERE id = 1"))
        ).scalar()

    async with _client() as http:
        response = await http.post(
            "/v1/ops/platform",
            headers=auth,
            json={"outbound_halted": True, "reason": "no confirmation sent"},
        )

    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/step_up_required"), response.text

    async with untenanted_session() as session:
        after = (
            await session.execute(text("SELECT outbound_halted FROM platform_state WHERE id = 1"))
        ).scalar()
    assert after == before, "the refusal happened AFTER the switch moved"
