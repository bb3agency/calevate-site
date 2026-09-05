"""D-165's opaque sessions, driven with real rows and a negative control per property.

`apps/api/authn/sessions.py` replaces the one thing Clerk does that this repo cannot do
without — turning a cookie into a principal — so every claim it makes needs a test that
FAILS if the claim stops holding, not a test that passes because a happy path works:

  * a live session verifies, and a tampered token does not;
  * a token minted for one realm is not a token for the other (the single most dangerous
    property in this migration — TRD §11, `tests/realm_boundary_test.py` is its
    Clerk-era twin);
  * both timeouts bite, server-side, independently, and the refusal names WHICH;
  * revocation bites on the next request, which is why the sessions are opaque at all;
  * rotation replaces the credential without extending the lifetime;
  * a rotated-away token presented again is treated as theft, not as a stale tab — and
    the family revocation that follows SURVIVES, which is a property about transactions
    rather than about sessions and is the one this suite nearly failed to check.

**EVERY VERIFICATION HERE RUNS IN ITS OWN TRANSACTION, exactly as a request does**, because
`verify_session` owns one (see its docstring). Tests therefore CLOSE the block that issued
a session before presenting it — writing them the other way would have them verifying
against a row their own open transaction had not committed, which is both a broken test
and a misleading model of production.

SHARED DATABASE DISCIPLINE. Every row hangs off a `subject_id` this module minted with
`uuid4`, so nothing it writes can collide with another suite's rows, and the `subjects`
fixture deletes exactly those. No assertion counts rows globally.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from apps.api.authn.sessions import (
    IDLE_WRITE_FLOOR,
    REALM_TIMEOUTS,
    REFUSALS,
    IssuedSession,
    VerifiedSession,
    issue_session,
    revoke_session,
    revoke_subject_sessions,
    rotate_session,
    token_fingerprint,
    verify_session,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import credential_session
from sqlalchemy import text


@pytest_asyncio.fixture
async def subjects() -> AsyncIterator[list[uuid.UUID]]:
    """Subject ids this test owns, and their cleanup.

    A list the test appends to rather than a single id, because several tests need two
    subjects (or one subject in two realms) and the teardown has to cover both.
    """
    owned: list[uuid.UUID] = []
    yield owned
    if owned:
        async with credential_session() as session:
            await session.execute(
                text("DELETE FROM auth_sessions WHERE subject_id = ANY(:ids)"), {"ids": owned}
            )
            await session.execute(
                text("DELETE FROM auth_credentials WHERE subject_id = ANY(:ids)"), {"ids": owned}
            )


def _subject(owned: list[uuid.UUID]) -> uuid.UUID:
    subject_id = uuid.uuid4()
    owned.append(subject_id)
    return subject_id


async def _issue(
    *,
    realm: str,
    subject_id: uuid.UUID,
    mfa_verified_at: datetime | None = None,
    now: datetime | None = None,
) -> IssuedSession:
    """Issue and COMMIT, so the next call can see the row. See the module docstring."""
    async with credential_session() as session:
        return await issue_session(
            session,
            realm=realm,
            subject_id=subject_id,
            mfa_verified_at=mfa_verified_at,
            now=now,
        )


async def _live(*, token: str, realm: str, now: datetime | None = None) -> VerifiedSession:
    """The happy path in one call, so a test asserting success reads as one line."""
    return (await verify_session(token=token, realm=realm, now=now)).require_live()


async def _refusal(*, token: str, realm: str, now: datetime | None = None) -> str:
    """The refusal CODE, asserted directly rather than only through the exception.

    `require_live()` collapses every failure into one sentence on purpose — telling a
    caller "that token was real but expired" is an oracle. The code is for us, and
    asserting it is what stops a test from passing because a DIFFERENT branch refused.
    """
    outcome = await verify_session(token=token, realm=realm, now=now)
    assert not outcome.live
    assert outcome.refusal is not None
    with pytest.raises(ProblemError) as raised:
        outcome.require_live()
    assert raised.value.status == 401
    return outcome.refusal


async def _row(session_id: uuid.UUID, column: str) -> object:
    async with credential_session() as session:
        return (
            await session.execute(
                text(f"SELECT {column} FROM auth_sessions WHERE id = :i"), {"i": session_id}
            )
        ).scalar_one()


# ------------------------------------------------------------------ the basic claim


async def test_a_freshly_issued_session_verifies(subjects: list[uuid.UUID]) -> None:
    subject_id = _subject(subjects)
    issued = await _issue(realm="client", subject_id=subject_id)
    verified = await _live(token=issued.token, realm="client")

    assert verified.session_id == issued.session_id
    assert verified.subject_id == subject_id
    assert verified.realm == "client"
    assert verified.mfa_verified_at is None


async def test_a_tampered_token_is_refused(subjects: list[uuid.UUID]) -> None:
    """NEGATIVE CONTROL. One character changed in a token that is otherwise real.

    The token is opaque, so there is nothing to forge — but nothing is what a caller
    holding a near-miss must get, and the same refusal an unknown token gets.
    """
    issued = await _issue(realm="client", subject_id=_subject(subjects))
    tampered = ("A" if issued.token[0] != "A" else "B") + issued.token[1:]
    assert await _refusal(token=tampered, realm="client") == "unknown"


# ------------------------------------------------------------------ the realm boundary


def test_the_realm_is_inside_the_fingerprint() -> None:
    """The structural half of the realm boundary, asserted on the arithmetic.

    One token, two realms, two different stored values. This is what makes cross-realm
    confusion impossible rather than merely filtered: there is no row the admin lookup
    could compare a client token's admin-domain fingerprint against.
    """
    token = "a-token-that-does-not-care-which-realm-it-is-in"
    assert token_fingerprint(token, "admin") != token_fingerprint(token, "client")
    assert token_fingerprint(token, "client") == token_fingerprint(token, "client")


async def test_a_client_token_is_not_a_weak_admin_token(subjects: list[uuid.UUID]) -> None:
    """NEGATIVE CONTROL for the realm boundary, with the control that makes it mean
    something: the same token succeeds on its own realm in the same test.

    Without that half, a refusal here would be satisfied by a token that was simply
    broken — the shape of assertion `tests/realm_boundary_test.py` exists to avoid. The
    refusal is `unknown` rather than a realm-specific code, which is itself the point:
    the admin lookup does not find a client session and decline it, it finds nothing.
    """
    issued = await _issue(realm="client", subject_id=_subject(subjects))

    assert await _refusal(token=issued.token, realm="admin") == "unknown"
    assert (await _live(token=issued.token, realm="client")).realm == "client"


async def test_an_admin_token_is_not_a_client_token(subjects: list[uuid.UUID]) -> None:
    """The other direction, and it is not symmetric by accident — an operator session
    reaching a client surface is D-22's whole subject."""
    issued = await _issue(realm="admin", subject_id=_subject(subjects))
    assert await _refusal(token=issued.token, realm="client") == "unknown"


async def test_one_subject_id_in_two_realms_is_two_unrelated_sessions(
    subjects: list[uuid.UUID],
) -> None:
    """The nastiest confusion this schema could permit, driven.

    `subject_id` has no foreign key (it points at `users` or `admin_users` depending on
    realm), so the SAME uuid can legitimately exist in both. Revoking one realm's
    sessions must not touch the other's, or a client signing out would sign an operator
    out — or, far worse, the reverse would read as "already handled".
    """
    subject_id = _subject(subjects)
    as_client = await _issue(realm="client", subject_id=subject_id)
    as_admin = await _issue(realm="admin", subject_id=subject_id)

    async with credential_session() as session:
        assert await revoke_subject_sessions(session, realm="client", subject_id=subject_id) == 1

    assert await _refusal(token=as_client.token, realm="client") == "revoked"
    assert (await _live(token=as_admin.token, realm="admin")).realm == "admin"


async def test_the_two_realms_get_different_lifetimes(subjects: list[uuid.UUID]) -> None:
    """The admin realm holds cross-client data and the big red switch, so it expires
    sooner. A single shared pair of numbers would be the easy regression."""
    assert REALM_TIMEOUTS["admin"].idle < REALM_TIMEOUTS["client"].idle
    assert REALM_TIMEOUTS["admin"].absolute < REALM_TIMEOUTS["client"].absolute

    started = datetime.now(UTC)
    subject_id = _subject(subjects)
    admin = await _issue(realm="admin", subject_id=subject_id, now=started)
    client = await _issue(realm="client", subject_id=subject_id, now=started)
    assert admin.absolute_expires_at < client.absolute_expires_at


# ------------------------------------------------------------------ the timeouts


async def test_an_idled_out_session_is_refused(subjects: list[uuid.UUID]) -> None:
    """NEGATIVE CONTROL for the idle bound. `now` is injected rather than slept for."""
    started = datetime.now(UTC)
    issued = await _issue(realm="client", subject_id=_subject(subjects), now=started)
    later = started + REALM_TIMEOUTS["client"].idle + timedelta(seconds=1)
    assert await _refusal(token=issued.token, realm="client", now=later) == "idle_expired"


async def test_a_session_past_its_absolute_bound_is_refused_however_active(
    subjects: list[uuid.UUID],
) -> None:
    """NEGATIVE CONTROL for the absolute bound, and the two bounds are independent.

    The session is used every few hours so the idle window never lapses; the absolute
    bound must still end it, and the refusal must be the ABSOLUTE one — asserting only
    "refused" would pass a version where the idle bound happened to bite first, which is
    the version that does not cap a stolen cookie at all.
    """
    started = datetime.now(UTC)
    absolute = REALM_TIMEOUTS["client"].absolute
    issued = await _issue(realm="client", subject_id=_subject(subjects), now=started)

    kept_alive = started
    while kept_alive + timedelta(hours=6) < started + absolute:
        kept_alive += timedelta(hours=6)
        await _live(token=issued.token, realm="client", now=kept_alive)

    refusal = await _refusal(token=issued.token, realm="client", now=started + absolute)
    assert refusal == "absolute_expired"


async def test_the_idle_window_slides_but_not_on_every_request(
    subjects: list[uuid.UUID],
) -> None:
    """The write floor: a dashboard polling six endpoints must not mean six row writes.

    Both halves are asserted, because only checking that it slides would pass a version
    that writes every time, and only checking the floor would pass one that never slides.
    """
    started = datetime.now(UTC)
    issued = await _issue(realm="client", subject_id=_subject(subjects), now=started)

    await _live(token=issued.token, realm="client", now=started + timedelta(seconds=5))
    assert await _row(issued.session_id, "last_seen_at") == started

    moved_on = started + IDLE_WRITE_FLOOR + timedelta(seconds=1)
    await _live(token=issued.token, realm="client", now=moved_on)
    assert await _row(issued.session_id, "last_seen_at") == moved_on
    assert await _row(issued.session_id, "idle_expires_at") == (
        moved_on + REALM_TIMEOUTS["client"].idle
    )


# ------------------------------------------------------------------ revocation


async def test_a_revoked_session_is_refused_on_the_next_request(
    subjects: list[uuid.UUID],
) -> None:
    """NEGATIVE CONTROL for the property the whole opaque-session design exists to buy.

    No denylist, no token lifetime to wait out: the row says no and the next request is
    refused.
    """
    issued = await _issue(realm="client", subject_id=_subject(subjects))
    assert (await _live(token=issued.token, realm="client")).subject_id

    async with credential_session() as session:
        assert await revoke_session(session, session_id=issued.session_id, reason="signed_out")

    assert await _refusal(token=issued.token, realm="client") == "revoked"


async def test_a_second_revocation_does_not_overwrite_the_first_reason(
    subjects: list[uuid.UUID],
) -> None:
    """`signed_out` landing on top of `reuse_detected` would erase the only record that a
    token leaked, which is the one thing an investigator would come looking for."""
    issued = await _issue(realm="client", subject_id=_subject(subjects))
    async with credential_session() as session:
        assert await revoke_session(session, session_id=issued.session_id, reason="reuse_detected")
        assert not await revoke_session(session, session_id=issued.session_id, reason="signed_out")
    assert await _row(issued.session_id, "revoked_reason") == "reuse_detected"


async def test_revoking_a_subject_ends_every_session_it_has_and_nobody_elses(
    subjects: list[uuid.UUID],
) -> None:
    """ "Sign me out everywhere" — what a password change and a deactivation both owe."""
    mine, theirs = _subject(subjects), _subject(subjects)
    phone = await _issue(realm="client", subject_id=mine)
    laptop = await _issue(realm="client", subject_id=mine)
    colleague = await _issue(realm="client", subject_id=theirs)

    async with credential_session() as session:
        assert await revoke_subject_sessions(session, realm="client", subject_id=mine) == 2

    for token in (phone.token, laptop.token):
        assert await _refusal(token=token, realm="client") == "revoked"
    assert (await _live(token=colleague.token, realm="client")).subject_id


# ------------------------------------------------------------------ rotation and reuse


async def test_rotation_replaces_the_credential_and_keeps_the_lifetime(
    subjects: list[uuid.UUID],
) -> None:
    """OWASP's session-fixation defence: regenerate the identifier on privilege change.

    The absolute bound is carried forward, never recomputed — otherwise a session that
    rotates often would live forever, and an attacker with a foothold could keep one
    alive indefinitely.
    """
    first = await _issue(realm="client", subject_id=_subject(subjects))
    verified = await _live(token=first.token, realm="client")

    async with credential_session() as session:
        second = await rotate_session(session, verified=verified)

    assert second.token != first.token
    assert second.family_id == first.family_id
    assert second.absolute_expires_at == first.absolute_expires_at
    assert (await _live(token=second.token, realm="client")).session_id == second.session_id


async def test_rotation_carries_the_second_factor_forward_unless_told_otherwise(
    subjects: list[uuid.UUID],
) -> None:
    """A rotation must not silently DOWNGRADE a session that completed MFA — the admin
    realm's whole gate reads this value (`core/auth.py`'s Clerk-era `fva` check)."""
    at = datetime.now(UTC)
    issued = await _issue(realm="admin", subject_id=_subject(subjects), mfa_verified_at=at)
    verified = await _live(token=issued.token, realm="admin")
    assert verified.mfa_verified_at == at

    async with credential_session() as session:
        rotated = await rotate_session(session, verified=verified)
    assert (await _live(token=rotated.token, realm="admin")).mfa_verified_at == at


async def test_replaying_a_rotated_token_revokes_the_whole_family(
    subjects: list[uuid.UUID],
) -> None:
    """NEGATIVE CONTROL for reuse detection (RFC 9700 §4.14.2, applied to sessions).

    Two parties holding one token means it leaked. Refusing only the replay would leave
    the thief's copy — or the victim's — working, so the family goes. **Both tokens are
    dead afterwards** — that is the assertion distinguishing this from a plain 401 — and
    they are checked in transactions of their own, so a revocation that did not COMMIT
    would be invisible here and the test would go red. That is the whole reason
    `verify_session` owns its transaction rather than borrowing the caller's; written the
    other way round, this file would have passed over the defect.
    """
    subject_id = _subject(subjects)
    first = await _issue(realm="client", subject_id=subject_id)
    verified = await _live(token=first.token, realm="client")
    async with credential_session() as session:
        second = await rotate_session(session, verified=verified)

    assert await _refusal(token=first.token, realm="client") == "reuse_detected"
    assert await _refusal(token=second.token, realm="client") == "revoked"

    async with credential_session() as session:
        reasons = (
            (
                await session.execute(
                    text("SELECT DISTINCT revoked_reason FROM auth_sessions WHERE family_id = :f"),
                    {"f": first.family_id},
                )
            )
            .scalars()
            .all()
        )
        live = (
            await session.execute(
                text(
                    "SELECT count(*) FROM auth_sessions WHERE family_id = :f AND revoked_at IS NULL"
                ),
                {"f": first.family_id},
            )
        ).scalar_one()
    assert reasons == ["reuse_detected"]
    assert live == 0


async def test_a_session_cannot_be_rotated_twice(subjects: list[uuid.UUID]) -> None:
    """The compare-and-swap on `superseded_at`. Two live members in one family is exactly
    the state the reuse detector reads as theft, so it must be unreachable.

    `rotate_session` RAISES here rather than returning an outcome, and that asymmetry is
    deliberate: a lost CAS wrote nothing, so there is no side effect for the rollback to
    eat — which is precisely the argument that does not hold for `verify_session`.
    """
    issued = await _issue(realm="client", subject_id=_subject(subjects))
    verified = await _live(token=issued.token, realm="client")

    async with credential_session() as session:
        await rotate_session(session, verified=verified)

    with pytest.raises(ProblemError):
        async with credential_session() as session:
            await rotate_session(session, verified=verified)


async def test_every_refusal_code_is_reachable_and_named(subjects: list[uuid.UUID]) -> None:
    """`REFUSALS` is the vocabulary a log line, a metric and this suite all key off, so it
    has to be EXACTLY what the code can produce — in both directions.

    A member nothing reaches is a label nobody will ever see (and usually a branch that
    was refactored away); a code outside the tuple is one no dashboard has a row for. The
    tests above each assert one code in isolation, which cannot notice either drift.
    """
    started = datetime.now(UTC)
    timeouts = REALM_TIMEOUTS["client"]
    subject_id = _subject(subjects)

    idled = await _issue(realm="client", subject_id=subject_id, now=started)
    aged = await _issue(realm="client", subject_id=subject_id, now=started)
    dropped = await _issue(realm="client", subject_id=subject_id)
    rotated_away = await _issue(realm="client", subject_id=subject_id)

    async with credential_session() as session:
        await revoke_session(session, session_id=dropped.session_id, reason="signed_out")
    async with credential_session() as session:
        await rotate_session(
            session, verified=await _live(token=rotated_away.token, realm="client")
        )

    seen = {
        await _refusal(token="a-token-that-was-never-issued", realm="client"),
        await _refusal(
            token=idled.token,
            realm="client",
            now=started + timeouts.idle + timedelta(seconds=1),
        ),
        await _refusal(token=aged.token, realm="client", now=started + timeouts.absolute),
        await _refusal(token=dropped.token, realm="client"),
        await _refusal(token=rotated_away.token, realm="client"),
    }
    assert seen == set(REFUSALS)


# ------------------------------------------------------------------ programming errors


async def test_an_unknown_realm_is_refused_loudly() -> None:
    """`realm` never comes off the wire — it is chosen by whichever dependency is asking —
    so a bad value is a bug, and a bug must not become a row the CHECK constraint rejects
    three statements later. Refused BEFORE a session is opened, so a typo costs no
    connection."""
    async with credential_session() as session:
        with pytest.raises(ValueError, match="not an authentication realm"):
            await issue_session(session, realm="ops", subject_id=uuid.uuid4())
    with pytest.raises(ValueError, match="not an authentication realm"):
        await verify_session(token="anything", realm="ops")
    with pytest.raises(ValueError, match="not an authentication realm"):
        token_fingerprint("anything", "ops")


# ----------------------------------------------------- who is allowed to rotate at all


#: Every call site of `rotate_session` in `apps/api`, and what makes it acceptable to the
#: no-grace-window decision the module docstring argues.
#:
#: THE CENSUS IS THE POINT, not the three entries. `sessions.py` refuses the 10-second
#: reuse grace its reference implementation carries, and the whole argument for that
#: refusal is that nothing here rotates on a schedule: every rotation is one person doing
#: one thing, so two requests never race the same token from this side. That premise used
#: to be stated as "sign-in, MFA completion, role change" — a list in which two of the
#: three do not rotate and the one caller a client can drive at will (`session/refresh`)
#: was missing. A prose list cannot hold a security premise up; this can.
#:
#: The failure this catches is precise: a SERVER-side rotation caller — a periodic re-mint,
#: a middleware, a background sweep — would make racing bursts ordinary, and every one of
#: them would revoke a live family as theft. Adding one is legitimate; adding one without
#: revisiting the grace-window decision is not, and an entry here is what forces the
#: reading.
_ROTATION_CALLERS: dict[str, str] = {
    "complete_second_factor": (
        "a second factor was proved — OWASP's session-fixation defence asks for a new "
        "identifier at exactly this moment. One person, one code, one request."
    ),
    "complete_step_up": (
        "a factor was re-proved for a dangerous act (D-178). Same shape: one person "
        "answering one emailed code."
    ),
    "refresh": (
        "the console's idle-extension button (POST /v1/auth/{realm}/session/refresh). The "
        "ONLY caller reachable at a client's discretion, and therefore the one the "
        "no-grace-window decision rests on: `apps/web/src/lib/authn/realm.ts` holds the "
        "'never a burst' premise up with a single-flight and a rotation barrier."
    ),
}


def test_the_only_rotation_callers_are_the_three_recorded_here() -> None:
    """Walk `apps/api` for `rotate_session(` and require the enclosing functions to match.

    A source walk rather than a monkeypatch: the property is about which code EXISTS, not
    about which code ran in one test. `sessions.py` itself is excluded — it defines the
    function — and so are comments and docstrings, which name it constantly.
    """
    import ast
    from pathlib import Path

    api = Path(__file__).resolve().parent.parent / "apps" / "api"
    callers: dict[str, str] = {}
    for path in sorted(api.rglob("*.py")):
        if path.name == "sessions.py" and path.parent.name == "authn":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "rotate_session"
                ):
                    callers[node.name] = str(path.relative_to(api.parent.parent))
    assert set(callers) == set(_ROTATION_CALLERS), (
        f"`rotate_session` is called from {sorted(callers)}; this census records "
        f"{sorted(_ROTATION_CALLERS)}. Rotation supersedes a token and the NEXT "
        "presentation of it revokes the whole family as theft — `authn/sessions.py` "
        "refuses a concurrency grace window on the premise that nothing here rotates on a "
        "schedule. Add the caller here with the sentence that keeps that premise true, or "
        "reopen the grace-window decision."
    )
