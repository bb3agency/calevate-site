"""Tenant-birth and offboarding defects that are OPEN, recorded so they cannot be
quietly rediscovered.

The entries here were found by walking creation, provisioning and offboarding over HTTP,
are real, and could not be closed from inside the slice that found them — each names the
specific reason and the specific act that closes it. **None is waiting on a vendor**:
they are waiting on a file that slice did not own, and the file is named. (The
`organizations.deleted_at`-has-no-writer entry was one of them and is now closed by
D-122 — `compliance/tenant_erasure.py` and `workers/retention.execute_tenant_erasure`.
Its probe remains below, as a regression test.) (`tests/onboarding_known_gaps_test.py`
is the other half of this registry and holds the two that ARE vendor-blocked; the split is
by blocker, so a reader chasing a DID account and a reader chasing a code change do not
have to read each other's list.)

**THE ASSERTION IS AN EQUALITY**, in the shape `tests/reliability_known_gaps_test.py` and
`tests/engine_name_drift_test.py::KNOWN_OPEN_COPIES` established. Each key has a probe
that answers "is this still true?" and the test asserts the set of still-open gaps EQUALS
the recorded set. So an entry cannot outlive its defect — closing one turns this file red
and forces the entry's deletion in the same change — and a comment or a TODO, which can
outlive anything, is not an option.

The probes deliberately outlive their entries: a probe with no entry is a CLOSED gap whose
predicate must keep answering False, which makes it a regression test at the exact moment
it stops being a finding.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from apps.api.db.session import untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parent.parent


#: Gap key → why it is open, and WHAT CLOSES IT (`CLOSED BY:`). Delete an entry the moment
#: its probe stops finding the gap; the equality assertion makes that mandatory.
KNOWN_OPEN_TENANT_BIRTH_GAPS: dict[str, str] = {}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _nothing_writes_the_organization_soft_delete() -> bool:
    """Does any application module write `organizations.deleted_at`?

    A source scan of `apps/` because there is no endpoint to call — which is the gap. It
    matches the WRITE rather than the column name (every reader mentions the column), and
    it excludes this file's own registry text so the entry describing the defect cannot be
    what keeps the probe green.
    """
    writes = ("organizations set deleted_at", "update organizations set deleted_at")
    for path in sorted((REPO_ROOT / "apps").rglob("*.py")):
        lowered = path.read_text(encoding="utf-8").lower()
        if any(needle in lowered for needle in writes):
            return False
    return True


async def _an_unmirrored_identity_is_refused_as_unauthenticated() -> bool:
    """BEHAVIOURAL, over the route an invitee actually hits.

    A client-realm token for a Clerk id that verifies and has no `users` row — exactly the
    state between Clerk's signup and our Svix mirror. 401 is the gap; a 4xx-that-says-wait
    or a 503 is the fix.

    CLOSED by D-124, and kept as the regression test this file's docstring promises. With
    no Clerk secret configured — this environment — the just-in-time reconcile cannot run,
    so the answer is the transient `identity_mirror_pending` 503 rather than 401. If it
    ever returns to 401 the equality below turns red with no entry to match it.
    """
    unmirrored = f"user_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        # Belt and braces: prove the id really is absent, so a probe that passed because
        # of a colliding fixture would be impossible.
        present = (
            await session.execute(
                text("SELECT 1 FROM users WHERE clerk_user_id = :c"), {"c": unmirrored}
            )
        ).first()
    if present is not None:  # pragma: no cover - a 96-bit collision
        return False
    async with _client() as http:
        response = await http.post(
            "/v1/invitations/accept",
            headers={"Authorization": f"Bearer dev:client:{unmirrored}"},
            json={"token": "a" * 40},
        )
    return response.status_code == 401


#: key → the probe that answers "is this gap still real?". An entry must have a probe; a
#: probe may outlive its entry (see the module docstring).
PROBES: dict[str, Callable[[], Awaitable[bool]]] = {
    # The entry this probe recorded is GONE (D-122): `compliance/tenant_erasure.py`
    # files the request and `workers/retention.execute_tenant_erasure` writes the column.
    # The probe STAYS, as this file's docstring requires — a probe with no entry is a
    # CLOSED gap whose predicate must keep answering False, which makes it a regression
    # test at the exact moment it stops being a finding. Delete the writer and the
    # equality assertion reports an open gap nobody recorded.
    "organizations_soft_delete_has_readers_but_no_writer": (
        _nothing_writes_the_organization_soft_delete
    ),
    "an_unmirrored_clerk_identity_reads_as_a_permanent_auth_failure": (
        _an_unmirrored_identity_is_refused_as_unauthenticated
    ),
}


async def test_every_recorded_gap_is_still_open_and_no_other_is() -> None:
    """The equality. Closing one of these fails here until its entry is deleted; recording
    one that is not real fails here immediately."""
    still_open = {key for key, probe in PROBES.items() if await probe()}

    unprobed = set(KNOWN_OPEN_TENANT_BIRTH_GAPS) - set(PROBES)
    assert unprobed == set(), (
        f"these recorded gaps have no probe, so the equality below cannot close them: "
        f"{sorted(unprobed)}"
    )
    assert still_open == set(KNOWN_OPEN_TENANT_BIRTH_GAPS), (
        "the recorded tenant-birth gaps and the real ones disagree.\n"
        f"  fixed but still recorded: {sorted(set(KNOWN_OPEN_TENANT_BIRTH_GAPS) - still_open)}\n"
        f"  open but not recorded:    {sorted(still_open - set(KNOWN_OPEN_TENANT_BIRTH_GAPS))}"
    )


def test_every_gap_says_what_closes_it() -> None:
    """A recorded gap with no named remedy is a TODO wearing a test's clothes."""
    silent = [key for key, why in KNOWN_OPEN_TENANT_BIRTH_GAPS.items() if "CLOSED BY" not in why]
    assert silent == [], f"these entries do not say what would close them: {silent}"


def test_every_gap_names_the_file_that_must_change() -> None:
    """Neither of these waits on a vendor, so each has to name the module whose change
    closes it — an internal deferral with no address is a deferral nobody can pick up
    (CLAUDE.md's tempo rule)."""
    addressless = [
        key
        for key, why in KNOWN_OPEN_TENANT_BIRTH_GAPS.items()
        if ".py" not in why and "apps/api/" not in why
    ]
    assert addressless == [], f"these entries name no file to change: {addressless}"
