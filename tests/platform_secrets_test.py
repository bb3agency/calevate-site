"""Credentials: sealed, versioned, never readable back (PLATFORM-CONFIG §5, §7, §10).

Ranked by what each failure costs, worst first:

1. **A plaintext credential must never reach disk or a response.** Everything else on
   this list is an inconvenience; this one is the reason §1 rejects the single-table
   design. Asserted at BOTH ends — the bytes in the column, and the JSON on the wire.
2. **The append-only boundary is real, and it is narrow.** A KEK rewrap may change the
   wrapping and nothing else. If the trigger let a ciphertext be edited, "which key was
   live when this call was billed" would be rewritable, which is the property the whole
   ledger family exists for.
3. **A wrong key is refused at the screen, not at the next call.** That is what `/test`
   is for, and its three non-success outcomes must stay distinguishable: a vendor that
   said no, a vendor we could not reach, and a vendor we cannot test at all.
4. **The environment still wins.** A stored credential that `.env` shadows is INERT, and
   the console has to say so or an operator rotates a key and the platform keeps using
   the old one.

Concurrency: `platform_secrets` is a shared table on a shared database. Every test here
uses its own key name where it can, and the ones that must use a real `Settings` field
clean up in a fixture.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from unittest import mock

import pytest
from apps.api.core import platform_config as pc
from apps.api.core.context import Principal
from apps.api.core.envelope import MASKED, build_ring, kek_ring
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops.secret_routes import (
    REWRAP_CONFIRMATION,
    SecretSetIn,
    secret_confirmation,
    set_secret_route,
)
from apps.api.ops.secret_service import (
    manageable_secret_keys,
    read_secrets,
    resolve_secrets,
    rewrap_all,
    secret_context,
    set_secret,
)
from calevate_shared.config import Settings
from fastapi import BackgroundTasks
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.requests import Request
from tests.admin_security_test import _make_admin

# A real `Settings` field, a credential by NAME, and absent from this repo's `.env` — so
# the resolution path is reachable without the environment shadowing it. The shadowing
# case is proved separately, against a key that IS in `.env`.
KEY = "meta_page_access_tokens"
#: The credential used to prove §4's precedence. The test DECLARES it in the environment
#: itself rather than relying on this repo's `.env` carrying it — which is what the
#: earlier version did, and it made the test pass on a developer's machine and fail in
#: CI, where there is no `.env` at all. A test whose subject is "the environment wins"
#: must own the environment it is asserting about; borrowing an ambient one asserts
#: whatever that machine happens to have.
SHADOWED_KEY = "cohere_api_key"
SECRET = "co-live-9f3a71b2c8d4e6f5"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _auth(token: str, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    return headers


async def _admin_id() -> uuid.UUID:
    async with untenanted_session() as session:
        row = (await session.execute(text("SELECT id FROM admin_users LIMIT 1"))).first()
        if row is not None:
            return uuid.UUID(str(row[0]))
        admin = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:i, :c, 'Secrets Test', 'superadmin', now(), now())"
            ),
            {"i": admin, "c": f"admin_{uuid.uuid4().hex[:12]}"},
        )
        return admin


async def _purge(*keys: str) -> None:
    """Remove this suite's rows, as the table OWNER.

    The app role cannot do it and that is the point: `untenanted_session` connects as
    `calevate_app`, which is neither the owner nor able to disable a trigger, so a DELETE
    through the ordinary path is refused twice over. The harness therefore reaches for
    `ALEMBIC_DATABASE_URL` — the same escape hatch `tests/rls_sweep_test.py` uses for its
    ground-truth counts — and disabling the trigger for the length of one statement is
    the honest way to clean up a table that is append-only ON PURPOSE. Nothing in
    `apps/` can do this; if it could, the ledger would not be one.

    `ENABLE TRIGGER` IS NOT THE INVERSE OF `DISABLE TRIGGER`, and this function used to
    assume it was. Plain `ENABLE` sets `tgenabled = 'O'` (ORIGIN) whatever the trigger
    was before, so re-arming an `ENABLE ALWAYS` trigger DEMOTES it — silently, with no
    error and no schema diff, to the exact state migration a2e9f31c605d exists to
    prevent. This suite left `platform_secrets`' two triggers in ORIGIN mode for the rest
    of the session, and `tests/ledger_truncate_immutability_test.py` is what noticed.
    So the prior mode of each trigger is READ FIRST and restored verbatim; nothing here
    decides what the right mode is, which keeps the answer in the migration where it
    belongs.
    """
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: platform_secrets is append-only"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            modes = (
                await conn.execute(
                    text(
                        "SELECT t.tgname, t.tgenabled FROM pg_trigger t "
                        "WHERE t.tgrelid = 'platform_secrets'::regclass AND NOT t.tgisinternal"
                    )
                )
            ).all()
            await conn.execute(text("ALTER TABLE platform_secrets DISABLE TRIGGER USER"))
            await conn.execute(
                text("DELETE FROM platform_secrets WHERE key = ANY(:keys)"), {"keys": list(keys)}
            )
            for name, mode in modes:
                verb = {"A": "ENABLE ALWAYS", "R": "ENABLE REPLICA", "D": "DISABLE"}.get(
                    str(mode), "ENABLE"
                )
                await conn.execute(text(f'ALTER TABLE platform_secrets {verb} TRIGGER "{name}"'))
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    await _purge(KEY, SHADOWED_KEY, "razorpay_webhook_secret")
    pc.reset_for_test()
    await pc.refresh(force=True)


# --- nothing plaintext, anywhere ------------------------------------------------


async def test_the_stored_row_contains_no_fragment_of_the_secret() -> None:
    """The claim the whole table exists to make, asserted against the BYTES on disk."""
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=await _admin_id())
        row = (
            await session.execute(
                text(
                    "SELECT ciphertext, nonce, dek_wrapped, dek_nonce, last_four "
                    "FROM platform_secrets WHERE key = :k"
                ),
                {"k": KEY},
            )
        ).first()
    assert row is not None
    blob = bytes(row[0]) + bytes(row[1]) + bytes(row[2]) + bytes(row[3])
    assert SECRET.encode() not in blob
    # The ONE plaintext fragment, and it is four characters.
    assert row[4] == "6f5"[-4:] or row[4] == SECRET[-4:]
    assert len(row[4]) <= 4


async def test_no_route_returns_the_value() -> None:
    """§7: "There is no read-back route and there will not be one." Asserted over the
    WHOLE response body rather than field by field, so a field added later that happens
    to carry the value is caught too."""
    token = await _make_admin()
    async with _client() as http:
        await http.put(
            f"/v1/ops/secrets/{KEY}",
            headers=_auth(token, secret_confirmation(KEY)),
            json={"value": SECRET, "reason": "installing for the read-back test"},
        )
        listed = await http.get("/v1/ops/secrets", headers=_auth(token))
    assert listed.status_code == 200, listed.text
    assert SECRET not in listed.text
    # And the fragment that IS published is exactly four characters.
    entry = next(s for s in listed.json()["secrets"] if s["key"] == KEY)
    assert entry["last_four"] == SECRET[-4:]
    assert entry["installed"] is True and entry["version"] == 1


async def test_a_short_credential_is_masked_entirely() -> None:
    """Below eight characters the "last four" IS most of the secret, so there is nothing
    safe to show."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            f"/v1/ops/secrets/{KEY}",
            headers=_auth(token, secret_confirmation(KEY)),
            json={"value": "abc", "reason": "a very short credential"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["last_four"] == MASKED


# --- versions, and the append-only boundary -------------------------------------


async def test_a_rotation_is_a_new_version_and_retires_the_old_one() -> None:
    admin = await _admin_id()
    async with untenanted_session() as session:
        first = await set_secret(session, key=KEY, value=SECRET, actor_id=admin)
        second = await set_secret(session, key=KEY, value="co-live-rotated-0000", actor_id=admin)
        rows = (
            await session.execute(
                text(
                    "SELECT version, retired_at IS NOT NULL FROM platform_secrets "
                    "WHERE key = :k ORDER BY version"
                ),
                {"k": KEY},
            )
        ).all()
    assert first.version == 1 and second.version == 2
    # The old row is RETIRED, never overwritten: "which key was live when this call was
    # billed" has to stay answerable a year later.
    assert [(int(v), bool(r)) for v, r in rows] == [(1, True), (2, False)]


async def test_the_ciphertext_cannot_be_edited_and_the_row_cannot_be_deleted() -> None:
    """The append-only boundary, at the database. These are the two mutations that would
    make the ledger rewritable."""
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=await _admin_id())

    for statement in (
        "UPDATE platform_secrets SET ciphertext = 'x'::bytea WHERE key = :k",
        "UPDATE platform_secrets SET last_four = 'zzzz' WHERE key = :k",
        "UPDATE platform_secrets SET version = 99 WHERE key = :k",
        "DELETE FROM platform_secrets WHERE key = :k",
    ):
        with pytest.raises(Exception) as raised:
            async with untenanted_session() as session:
                await session.execute(text(statement), {"k": KEY})
        assert "append-only" in str(raised.value), statement


async def test_the_wrapping_columns_are_the_only_ones_an_update_may_touch() -> None:
    """Derived from the LIVE schema rather than from a literal, so a column added to this
    table later fails here unless somebody decided which side of the boundary it is on."""
    async with untenanted_session() as session:
        columns = {
            str(r[0])
            for r in (
                await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'platform_secrets'"
                    )
                )
            ).all()
        }
    rewrappable = {"dek_wrapped", "dek_nonce", "kek_version", "retired_at"}
    immutable = columns - rewrappable
    assert immutable == {
        "key",
        "version",
        "ciphertext",
        "nonce",
        "last_four",
        "created_at",
        "created_by",
    }, (
        "a column was added to platform_secrets — decide whether a KEK rewrap may change "
        "it, and update migration b8e3f2a71c04's trigger accordingly"
    )


# --- the rewrap (phase 5's engine, proved here because the trigger is what allows it) ---


async def test_a_rewrap_moves_every_dek_without_touching_a_ciphertext() -> None:
    """§3 rule 3: rotation re-wraps DEKs, it does not re-encrypt secrets. Both halves are
    asserted — the wrapping changed, the payload did not, and the value still opens under
    the new key alone."""
    admin = await _admin_id()
    # The ring the row is written under, stated explicitly rather than inherited from the
    # process, so this test does not depend on how the deployment is configured.
    before_ring = build_ring(kek=_kek(b"\x31"), retired=None, app_env="prod")
    async with untenanted_session() as session:
        await _seal_under(session, admin, before_ring)
    # OUTSIDE the writing session: `untenanted_session` commits on exit, and reading the
    # row on a second connection before that commit would see nothing.
    before = await _wrapping()

    # Rotation: a new active key, the old one carried forward so historical rows still
    # open while the run is in flight. That is the documented rotation procedure.
    after_ring = build_ring(kek=_kek(b"\x32"), retired=_kek(b"\x31"), app_env="prod")
    async with untenanted_session() as session:
        result = await rewrap_all(session, ring=after_ring)
    after = await _wrapping()

    assert result.examined == 1 and result.rewrapped == 1 and result.unreadable == ()
    assert after[0] == before[0], "the payload was re-encrypted — a rotation must not"
    assert after[1] != before[1], "the wrapping did not change — nothing was re-wrapped"
    assert after[2] == after_ring.active.kek_id

    # And it opens under the NEW key with no retired key at all, which is what makes it
    # safe to drop the outgoing KEK from the environment after a rotation completes.
    only_new = build_ring(kek=_kek(b"\x32"), retired=None, app_env="prod")
    async with untenanted_session() as session:
        assert (await resolve_secrets(session, ring=only_new)).values[KEY] == SECRET


def _kek(seed: bytes) -> str:
    import base64

    return base64.b64encode(seed * 32).decode()


async def _seal_under(session: object, admin: uuid.UUID, ring: object) -> None:
    """Write one row sealed under a NAMED ring rather than the process's own.

    `set_secret` deliberately takes no ring — production has exactly one — so the row is
    written through the envelope directly here. That is the only place in this suite that
    reaches past the service, and it is what lets the rotation test control both ends.
    """
    from apps.api.core.envelope import seal as _seal

    envelope = _seal(SECRET, context=secret_context(KEY), ring=ring)  # type: ignore[arg-type]
    await session.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO platform_secrets (key, version, ciphertext, nonce, dek_wrapped, "
            "dek_nonce, kek_version, last_four, created_by) "
            "VALUES (:k, 1, :ct, :n, :dw, :dn, :kek, :l4, :by)"
        ),
        {
            "k": KEY,
            "ct": envelope.ciphertext,
            "n": envelope.nonce,
            "dw": envelope.dek_wrapped,
            "dn": envelope.dek_nonce,
            "kek": envelope.kek_id,
            "l4": SECRET[-4:],
            "by": admin,
        },
    )


async def _wrapping() -> tuple[bytes, bytes, int]:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT ciphertext, dek_wrapped, kek_version FROM platform_secrets "
                    "WHERE key = :k"
                ),
                {"k": KEY},
            )
        ).first()
    assert row is not None
    return bytes(row[0]), bytes(row[1]), int(row[2])


async def test_a_mislabelled_row_is_still_rewrapped() -> None:
    """THE CONDITION THE WHOLE FINGERPRINT DESIGN RESTS ON (D-96).

    `kek_version` is a REPORTING field. The obvious optimisation —
    `WHERE kek_version <> :active`, skip the rows already under the current key — is
    exactly what must never exist, and this test is what makes adding it fail.

    The row below is MISLABELLED: it is wrapped under key A and stamped with key B's
    fingerprint. That is what a hand-written INSERT, a bug, or a restore from a backup
    taken mid-rotation produces. A rewrap that trusted the label would skip it, report
    success, and leave it under A — and the next rotation, which drops A from the
    environment, would make it permanently unreadable. Silent, irreversible, and it is
    the counter design's failure mode wearing a hash.

    So: every row, every time. This asserts the row was EXAMINED and RE-WRAPPED despite
    its label already claiming to be current, and that it then opens under the active key
    with no retired key configured at all.
    """
    admin = await _admin_id()
    key_a = build_ring(kek=_kek(b"\x41"), retired=None, app_env="prod")
    key_b = build_ring(kek=_kek(b"\x42"), retired=None, app_env="prod")

    from apps.api.core.envelope import seal as _seal

    envelope = _seal(SECRET, context=secret_context(KEY), ring=key_a)
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_secrets (key, version, ciphertext, nonce, dek_wrapped, "
                "dek_nonce, kek_version, last_four, created_by) "
                "VALUES (:k, 1, :ct, :n, :dw, :dn, :kek, :l4, :by)"
            ),
            {
                "k": KEY,
                "ct": envelope.ciphertext,
                "n": envelope.nonce,
                "dw": envelope.dek_wrapped,
                "dn": envelope.dek_nonce,
                # THE LIE: wrapped under A, labelled B.
                "kek": key_b.active.kek_id,
                "l4": SECRET[-4:],
                "by": admin,
            },
        )

    rotated = build_ring(kek=_kek(b"\x42"), retired=_kek(b"\x41"), app_env="prod")
    async with untenanted_session() as session:
        result = await rewrap_all(session, ring=rotated)

    assert result.examined == 1, "the row was FILTERED OUT — kek_version became a filter"
    assert result.rewrapped == 1, "the row was skipped because its label already said 'current'"

    # The proof that it matters: it now opens under B alone, so dropping A is safe.
    only_b = build_ring(kek=_kek(b"\x42"), retired=None, app_env="prod")
    async with untenanted_session() as session:
        assert (await resolve_secrets(session, ring=only_b)).values[KEY] == SECRET


async def test_a_row_no_key_opens_is_reported_never_skipped_silently() -> None:
    """The condition the whole fingerprint design rests on: a rewrap must SEE a row it
    cannot open, and say so, rather than passing over it and leaving it to die at the
    next rotation."""
    admin = await _admin_id()
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=admin)

    stranger = build_ring(kek=_kek(b"\x77"), retired=None, app_env="prod")
    async with untenanted_session() as session:
        result = await rewrap_all(session, ring=stranger)
    assert result.examined == 1
    assert result.rewrapped == 0
    assert result.unreadable == (f"{KEY}#1",)


# --- resolution -----------------------------------------------------------------


async def test_a_stored_credential_reaches_get_settings() -> None:
    """The outcome the founder asked for: a key set from the console is the key the
    platform uses, with no restart and no SSH."""
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=await _admin_id())
    await pc.refresh(force=True)
    assert get_settings().meta_page_access_tokens == SECRET


async def test_the_environment_still_wins_over_a_stored_credential() -> None:
    """§4, applied to secrets, against two REAL keys rather than a simulation.

    A `.env` value must not be shadowed by a stored one, or an operator's emergency
    override stops working exactly when they need it — which is the one property that
    makes putting credentials in a database acceptable at all (§10's last mitigation).
    """
    admin = await _admin_id()
    # DECLARED HERE, not borrowed from `.env`. An empty value counts as declared on
    # purpose (`env_declares`): `COHERE_API_KEY=` is a deployment stating it has no
    # Cohere key, and pydantic hands `Settings` the empty string rather than falling
    # through to the store — so this is the real shadowing shape, not a stand-in.
    with mock.patch.dict(os.environ, {SHADOWED_KEY.upper(): ""}):
        async with untenanted_session() as session:
            await set_secret(session, key=KEY, value=SECRET, actor_id=admin)
            await set_secret(session, key=SHADOWED_KEY, value="stored-and-inert", actor_id=admin)
            resolved = await resolve_secrets(session)
            stored = (
                await session.execute(
                    text("SELECT count(*) FROM platform_secrets WHERE key = :k"),
                    {"k": SHADOWED_KEY},
                )
            ).scalar_one()

    assert resolved.values[KEY] == SECRET, "an unshadowed credential resolves"
    # The row EXISTS and is deliberately not applied. Stored-and-inert is the state the
    # console has to render as `shadowed_by_env`, or an operator rotates this key and
    # watches the platform go on using the environment's.
    assert stored == 1
    assert SHADOWED_KEY not in resolved.values


async def test_one_unreadable_credential_does_not_blank_the_others() -> None:
    """A rotation mistake on ONE key must not take every other credential in the fleet
    with it — that would turn a misconfiguration into a total outage, which is the
    failure direction §6 forbids."""
    admin = await _admin_id()
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=admin)
        # A second row, sealed under a key this deployment does not have.
        await session.execute(
            text(
                "INSERT INTO platform_secrets (key, version, ciphertext, nonce, dek_wrapped, "
                "dek_nonce, kek_version, last_four, created_by) VALUES "
                "('razorpay_webhook_secret', 1, '\\x00'::bytea, '\\x00'::bytea, '\\x00'::bytea, "
                "'\\x00'::bytea, 1, 'zzzz', :by)"
            ),
            {"by": admin},
        )
        resolved = await resolve_secrets(session)

    assert resolved.values[KEY] == SECRET, "the good credential still resolved"
    assert resolved.unreadable == ("razorpay_webhook_secret",), (
        "and the bad one is NAMED, not hidden"
    )


# --- the routes -----------------------------------------------------------------


async def test_the_list_shows_uninstalled_credentials_too() -> None:
    """ "We have never installed a Sarvam key" is the answer an operator needs; an absent
    row would render as a blank they have to interpret."""
    async with untenanted_session() as session:
        records = await read_secrets(session)
    assert {r.key for r in records} == set(manageable_secret_keys())
    assert any(r.version == 0 for r in records)


async def test_a_write_without_the_key_bound_confirmation_stores_nothing() -> None:
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            f"/v1/ops/secrets/{KEY}",
            headers=_auth(token, secret_confirmation("sarvam_api_key")),
            json={"value": SECRET, "reason": "replayed header from another key"},
        )
    assert response.status_code == 403
    async with untenanted_session() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM platform_secrets WHERE key = :k"), {"k": KEY}
            )
        ).scalar_one()
    assert count == 0


async def test_a_session_without_platform_secrets_is_refused() -> None:
    """`platform:config` does NOT open this surface — that separation is the mitigation
    §10's accepted trade rests on."""
    token = await _make_admin("operator")
    async with _client() as http:
        assert (await http.get("/v1/ops/secrets", headers=_auth(token))).status_code == 403


async def test_a_plain_config_key_cannot_be_stored_as_a_secret() -> None:
    """The complement of the config surface's refusal. One predicate decides where a key
    lives, so a key cannot end up in both stores or in neither."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            "/v1/ops/secrets/engine",
            headers=_auth(token, secret_confirmation("engine")),
            json={"value": "bolna", "reason": "not a credential"},
        )
    assert response.status_code == 422
    assert response.json()["type"].endswith("/secret_key_is_plain_config")


async def test_the_kek_can_never_be_stored_in_the_store_it_opens() -> None:
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            "/v1/ops/secrets/platform_kek",
            headers=_auth(token, secret_confirmation("platform_kek")),
            json={"value": "AAAA", "reason": "this must be impossible"},
        )
    assert response.status_code == 422
    assert response.json()["type"].endswith("/secret_key_bootstrap")


async def test_an_empty_credential_is_refused_rather_than_installed() -> None:
    """An empty row would read as installed while authenticating nothing — a rotation
    that looks done and is not."""
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await set_secret(session, key=KEY, value="   ", actor_id=await _admin_id())
    assert raised.value.code == "secret_value_empty"


# --- /test ------------------------------------------------------------------------


async def test_a_key_with_no_probe_answers_no_probe_not_a_green_tick() -> None:
    """ "We could not check this" and "this works" must never render the same."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(
            f"/v1/ops/secrets/{KEY}/test",
            headers=_auth(token),
            json={"value": SECRET},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "no_probe"
    assert body["status"] is None
    assert body["candidate_last_four"] == SECRET[-4:]
    # NOT stored: the whole point of testing before setting.
    async with untenanted_session() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM platform_secrets WHERE key = :k"), {"k": KEY}
            )
        ).scalar_one()
    assert count == 0


async def test_the_probe_reports_a_refusal_and_an_outage_differently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """401 is the vendor saying no to THIS key. 503 is the vendor having a bad day.
    Conflating them tells an operator to rotate a working key during someone else's
    outage."""
    from apps.api.ops import secret_probes

    class _Response:
        def __init__(self, status: int) -> None:
            self.status_code = status

    class _Client:
        def __init__(self, status: int) -> None:
            self._status = status

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def request(self, *_: object, **__: object) -> _Response:
            return _Response(self._status)

    for status, expected in ((200, "accepted"), (401, "rejected"), (503, "unreachable")):
        monkeypatch.setattr(
            secret_probes.httpx, "AsyncClient", lambda *_, _s=status, **__: _Client(_s)
        )
        result = await secret_probes.probe_credential("bolna_api_key", "candidate-value")
        assert result.outcome == expected, status
        assert result.status == status


async def test_an_unreachable_vendor_is_never_reported_as_a_bad_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.ops import secret_probes

    class _Exploding:
        async def __aenter__(self) -> _Exploding:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def request(self, *_: object, **__: object) -> object:
            raise OSError("dns is down")

    monkeypatch.setattr(secret_probes.httpx, "AsyncClient", lambda *_, **__: _Exploding())
    result = await secret_probes.probe_credential("bolna_api_key", "candidate-value")
    assert result.outcome == "unreachable"
    assert "NOT been checked" in result.detail


def test_every_probe_names_where_its_endpoint_came_from() -> None:
    """OPERATIONS §2: a vendor behaviour is verified or it is a MARKED assumption, never
    a silent premise. Each probe has to cite the file its endpoint was read from, and to
    state whether the refusal has actually been observed."""
    from apps.api.ops.secret_probes import PROBES

    assert PROBES, "a probe registry with nothing in it is a green tick by another name"
    for key, probe in PROBES.items():
        assert probe.source, f"{key}: no citation for the endpoint"
        assert probe.url.startswith("https://"), f"{key}: a credential over plaintext HTTP"
        assert isinstance(probe.verified, bool)


def test_the_ledger_allowance_is_scoped_to_one_file() -> None:
    """`BOUNDED_MUTATIONS` lets `secret_service.py` contain the rewrap's UPDATE. The
    allowance must be ONE MODULE WIDE, not repo wide.

    Written after a sabotage showed the claim was unproved: widening the lookup to ignore
    the file left every check green while any module in the repo could mutate
    `platform_secrets`. The database trigger is still the real enforcement — it would
    refuse a ciphertext edit from anywhere — but check 1 exists to catch the statement
    before it runs, and an allowance that silences it everywhere silences it for the
    module that has not been reviewed.
    """
    from pathlib import Path

    from scripts.check_ledger_immutability import BOUNDED_MUTATIONS, scan_source

    statement = 'await session.execute(text("UPDATE platform_secrets SET kek_version = 0"))'

    allowed_file = Path("apps/api/ops/secret_service.py")
    assert (allowed_file.as_posix(), "platform_secrets") in BOUNDED_MUTATIONS
    assert scan_source(allowed_file, statement) == [], "the registered module lost its allowance"

    # Any OTHER module writing the identical statement is still a finding.
    for elsewhere in ("apps/api/ops/config_service.py", "apps/workers/pipeline.py"):
        findings = scan_source(Path(elsewhere), statement)
        assert findings, f"{elsewhere} may now mutate platform_secrets — the allowance leaked"
        assert "platform_secrets" in findings[0]


# --- the refusals the routes own -------------------------------------------------


async def test_a_reason_that_is_only_whitespace_is_refused_and_installs_nothing() -> None:
    """The rotation record is the ONLY thing this surface leaves behind.

    A credential write stores no value anybody can read back, so `reason` in the audit row
    is the entire answer to "was this rotation ours?" — the question §10 accepts as the
    residual risk's only control. `""` and `"ab"` are refused by the length bound before
    the validator runs; `"   "` satisfies it and says nothing, which is the case the
    validator exists for and the one that would otherwise be indistinguishable from a real
    reason in the ledger.
    """
    token = await _make_admin()
    async with _client() as http:
        for reason in ("", "ab", "   ", " \t\n "):
            response = await http.put(
                f"/v1/ops/secrets/{KEY}",
                headers=_auth(token, secret_confirmation(KEY)),
                json={"value": SECRET, "reason": reason},
            )
            assert response.status_code == 422, reason
    async with untenanted_session() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM platform_secrets WHERE key = :k"), {"k": KEY}
            )
        ).scalar_one()
    assert count == 0, "a credential was installed by a request that gave no reason"


async def test_installing_a_credential_with_no_admin_identity_is_refused() -> None:
    """§10's accepted trade is DETECTION, and detection needs a name.

    A compromised admin session can point this platform at an attacker's vendor account;
    what makes that an accepted risk rather than an unmonitored one is that every install
    lands an attributed row in a hash-chained ledger and fires an alert. A write nobody
    can be attributed to would defeat that control while looking like an ordinary
    rotation, so it is refused before the value is sealed — with the step-up already
    satisfied, so what is pinned here is the identity check and not the header in front
    of it.
    """
    principal = Principal(
        realm="admin", user_id=None, clerk_user_id="user_no_mirror_row", tenant_id=None, role=None
    )
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await set_secret_route(
                SecretSetIn(value=SECRET, reason="a session with no admin row"),
                session,
                _request(),
                BackgroundTasks(),
                principal,
                KEY,
                x_confirm_action=secret_confirmation(KEY),
            )
    assert raised.value.code == "secret_actor_unknown"
    assert raised.value.kind == "auth"
    async with untenanted_session() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM platform_secrets WHERE key = :k"), {"k": KEY}
            )
        ).scalar_one()
    assert count == 0, "an unattributable credential reached the ledger"


async def test_a_credential_this_build_has_never_had_is_a_404_by_its_own_name() -> None:
    """The FIRST of five refusals, and the only one that is a typo.

    `secret_key_unknown` is what an operator meets when they mistype a key name;
    `secret_key_bootstrap` and `secret_key_is_plain_config` are what they meet when they
    misunderstand where a real key lives. Collapsing them would send somebody who
    fat-fingered `sarvem_api_key` off to read §4 about bootstrap keys. It is also the
    check that keeps the path parameter from reaching `Settings.model_fields[...]` and
    raising a `KeyError` rendered as a 500.
    """
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            "/v1/ops/secrets/no_such_credential",
            headers=_auth(token, secret_confirmation("no_such_credential")),
            json={"value": SECRET, "reason": "a typo in the key name"},
        )
    assert response.status_code == 404, response.text
    body = response.json()
    assert body["type"].endswith("/secret_key_unknown")
    assert "no_such_credential" in body["detail"]


# --- the key-management panel (§8 panel 4) ----------------------------------------


def _request() -> Request:
    """A real `Request`: the audit row's `ip` is read off `request.client`."""
    return Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/v1/ops/secrets",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
        }
    )


async def _newest_audit_id() -> str:
    async with untenanted_session() as session:
        row = (
            await session.execute(text("SELECT id FROM audit_log ORDER BY id DESC LIMIT 1"))
        ).first()
    return str(row[0]) if row is not None else str(uuid.UUID(int=0))


async def _audit_since(since: str) -> list[str]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE id > :since "
                    "AND action LIKE 'platform.kek%' ORDER BY id"
                ),
                {"since": since},
            )
        ).all()
    return [str(r[0]) for r in rows]


async def _wrappings() -> dict[str, int]:
    """Every stored version and the KEK id its row claims, straight from the table."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(text("SELECT key, version, kek_version FROM platform_secrets"))
        ).all()
    return {f"{r[0]}#{int(r[1])}": int(r[2]) for r in rows}


async def test_the_panel_counts_what_is_not_yet_under_the_active_key() -> None:
    """`pending` IS THE NUMBER THAT DECIDES WHETHER A ROTATION IS FINISHED.

    While it is above zero, `PLATFORM_KEK_RETIRED` must stay in the environment: removing
    it makes those rows permanently unreadable, which is unrecoverable data loss dressed
    as tidying up. So the count has to be real, and it is asserted against the TABLE
    rather than against the route's own arithmetic — a `pending` computed from a filtered
    query, or from the ring instead of the rows, would still be self-consistent and would
    still tell an operator it is safe to drop the key that is holding a credential up.
    """
    admin = await _admin_id()
    stranger = build_ring(kek=_kek(b"\x51"), retired=None, app_env="prod")
    async with untenanted_session() as session:
        # One row this deployment's KEK did NOT wrap — the mid-rotation state — and one it
        # did, so both counters have something to count.
        await _seal_under(session, admin, stranger)
        await set_secret(session, key=KEY, value=SECRET, actor_id=admin)

    ring = kek_ring()
    token = await _make_admin()
    async with _client() as http:
        response = await http.get("/v1/ops/secrets/kek", headers=_auth(token))
    assert response.status_code == 200, response.text
    body = response.json()

    wrappings = await _wrappings()
    assert body["active_kek_id"] == ring.active.kek_id
    assert body["has_retired_kek"] is bool(ring.retired)
    assert body["versions"] == len(wrappings)
    assert body["current"] == sum(1 for k in wrappings.values() if k == ring.active.kek_id)
    assert body["pending"] == sum(1 for k in wrappings.values() if k != ring.active.kek_id)
    assert body["pending"] >= 1, (
        "a version wrapped under another KEK reported as nothing to do — an operator "
        "reading this would drop PLATFORM_KEK_RETIRED and lose that credential"
    )
    assert SECRET not in response.text


# --- the rewrap, from the console --------------------------------------------------


async def test_a_console_rewrap_moves_every_readable_dek_and_names_the_rest() -> None:
    """THE ROTATION'S LAST STEP, WITH ITS ONE HONEST FAILURE MODE.

    After a KEK rotation this is what moves the fleet's DEKs onto the new key. Two claims
    are asserted against the table itself rather than against the response's own counters:

    * every row that COULD be opened now carries the active KEK's fingerprint;
    * the rows still under another key are EXACTLY the ones reported as `unreadable`.

    The second is the one that matters at 3am. A rewrap that quietly passed over a row it
    could not open would report a clean run, an operator would then remove
    `PLATFORM_KEK_RETIRED` on the strength of it, and that credential would be gone for
    good. Reported, it is a row somebody can still rescue while the outgoing key exists.
    """
    admin = await _admin_id()
    stranger = build_ring(kek=_kek(b"\x52"), retired=None, app_env="prod")
    async with untenanted_session() as session:
        await _seal_under(session, admin, stranger)  # version 1: no configured key opens it
        await set_secret(session, key=KEY, value=SECRET, actor_id=admin)  # version 2

    ring = kek_ring()
    since = await _newest_audit_id()
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(
            "/v1/ops/secrets/kek/rewrap", headers=_auth(token, REWRAP_CONFIRMATION), json={}
        )
    assert response.status_code == 200, response.text
    body = response.json()

    wrappings = await _wrappings()
    assert body["active_kek_id"] == ring.active.kek_id
    assert body["examined"] == len(wrappings), "a row was filtered out of the run (D-96)"
    assert f"{KEY}#1" in body["unreadable"], "a row no key opens was counted away silently"
    left_behind = sorted(k for k, kek in wrappings.items() if kek != ring.active.kek_id)
    assert left_behind == sorted(body["unreadable"]), (
        "the rows still under another KEK are not the ones the operator was told about"
    )
    assert body["rewrapped"] == len(wrappings) - len(body["unreadable"])
    assert SECRET not in response.text

    # The value still opens afterwards — a rewrap that broke what it moved would satisfy
    # every count above.
    async with untenanted_session() as session:
        assert (await resolve_secrets(session)).values[KEY] == SECRET

    assert await _audit_since(since) == ["platform.kek_rewrapped"]


async def test_an_unconfirmed_rewrap_touches_no_row() -> None:
    """The most invasive write on this router — it UPDATEs every row of an append-only
    ledger — so the confirmation is not decoration. Asserted on the wrappings rather than
    on the status code alone: a refusal that happened after the run would be a 403 over a
    completed rotation."""
    admin = await _admin_id()
    async with untenanted_session() as session:
        await _seal_under(
            session, admin, build_ring(kek=_kek(b"\x53"), retired=None, app_env="prod")
        )
    before = await _wrappings()

    token = await _make_admin()
    async with _client() as http:
        response = await http.post("/v1/ops/secrets/kek/rewrap", headers=_auth(token), json={})
    assert response.status_code == 403
    assert response.json()["type"].endswith("/step_up_required")
    assert await _wrappings() == before


async def test_an_undecryptable_row_alerts_the_operator_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE SYMPTOM POINTS AT THE WRONG SYSTEM UNLESS THIS FIRES.

    A credential row no configured KEK opens presents downstream as "the vendor is
    rejecting our key" — an operator will go and rotate a working credential at the vendor
    before they ever suspect their own `PLATFORM_KEK`. So the refresh that finds one must
    say so, with the KEY NAMED, and it must go on serving everything else: one bad row
    turning into a fleet-wide config freeze is the failure direction §6 forbids.

    The alert is asserted, not the log line, because an alert reaches a person and a log
    line at 3am does not (that is the whole argument of `core/alerting`).
    """
    fired: list[tuple[str, str, dict[str, object]]] = []
    monkeypatch.setattr(pc, "alert", lambda stage, code, **kw: fired.append((stage, code, kw)))

    admin = await _admin_id()
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=admin)
        await session.execute(
            text(
                "INSERT INTO platform_secrets (key, version, ciphertext, nonce, dek_wrapped, "
                "dek_nonce, kek_version, last_four, created_by) VALUES "
                "('razorpay_webhook_secret', 1, '\\x00'::bytea, '\\x00'::bytea, '\\x00'::bytea, "
                "'\\x00'::bytea, 1, 'zzzz', :by)"
            ),
            {"by": admin},
        )

    snap = await pc.refresh(force=True)

    unreadable = [f for f in fired if f[1] == "platform_secret_unreadable"]
    assert unreadable, "a credential nobody can decrypt passed without a word to anyone"
    stage, _, kwargs = unreadable[0]
    assert stage == "CORE_LOGIC"
    assert kwargs["keys"] == "razorpay_webhook_secret", "the alert must NAME the row"
    assert "PLATFORM_KEK" in str(kwargs.get("detail")), "and point at the right system"
    # Serving, not degraded: the good credential landed on the same pass.
    assert snap.degraded is False
    assert get_settings().meta_page_access_tokens == SECRET


def test_the_aad_namespaces_platform_secrets_away_from_tenant_secrets() -> None:
    """§11's `tenant_secrets` reuses this envelope. The context prefix is what stops a
    tenant's sealed credential ever being swapped into a platform row."""
    assert secret_context("bolna_api_key") == "platform_secret:bolna_api_key"
    assert not secret_context("x").startswith("tenant_secret:")
