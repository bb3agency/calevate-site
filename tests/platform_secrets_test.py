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

import uuid
from collections.abc import AsyncIterator

import pytest
from apps.api.core import platform_config as pc
from apps.api.core.envelope import MASKED, build_ring
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops.secret_routes import secret_confirmation
from apps.api.ops.secret_service import (
    manageable_secret_keys,
    read_secrets,
    resolve_secrets,
    rewrap_all,
    secret_context,
    set_secret,
)
from calevate_shared.config import Settings
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.admin_security_test import _make_admin

# A real `Settings` field, a credential by NAME, and absent from this repo's `.env` — so
# the resolution path is reachable without the environment shadowing it. The shadowing
# case is proved separately, against a key that IS in `.env`.
KEY = "meta_page_access_tokens"
#: A credential the environment DOES declare here, used to prove §4's precedence.
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
    """
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: platform_secrets is append-only"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE platform_secrets DISABLE TRIGGER USER"))
            await conn.execute(
                text("DELETE FROM platform_secrets WHERE key = ANY(:keys)"), {"keys": list(keys)}
            )
            await conn.execute(text("ALTER TABLE platform_secrets ENABLE TRIGGER USER"))
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


def test_the_aad_namespaces_platform_secrets_away_from_tenant_secrets() -> None:
    """§11's `tenant_secrets` reuses this envelope. The context prefix is what stops a
    tenant's sealed credential ever being swapped into a platform row."""
    assert secret_context("bolna_api_key") == "platform_secret:bolna_api_key"
    assert not secret_context("x").startswith("tenant_secret:")
