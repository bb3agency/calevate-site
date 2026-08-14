"""The config surface end to end: refusals, step-up, audit, propagation (§7, §9).

`platform_settings` is a SHARED table on a shared database, like `platform_state`. Every
test here either writes nothing or writes one key and removes it in `finally`, and the
key is `self_serve_inr_per_min` — a `Decimal`, so the round trip through `jsonb` and back
also proves money stays exact (hard rule 7).

WHAT EACH GROUP PINS, and what would silently break if it were deleted:

* **the refusals** — five different reasons a key cannot be written, each with its own
  code. Collapse them into one `invalid_key` and an operator who mistyped a name gets the
  same screen as one who tried to put an API key in a plaintext table.
* **the step-up** — bound to the key, and a DIFFERENT string for revert. Without the
  binding, a header captured while raising a pool size switches the voice engine.
* **the audit row** — same transaction, old → new, with the operator's reason. Without
  it, "who changed the rate on the day the margin moved" is unanswerable.
* **propagation** — the write bumps the sentinel, so peers converge without a restart.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from apps.api.core import platform_config as pc
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops.config_routes import config_confirmation, revert_confirmation
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_security_test import _make_admin

KEY = "self_serve_inr_per_min"
PATH = f"/v1/ops/config/{KEY}"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _auth(token: str, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    return headers


async def _row() -> tuple[str, str | None] | None:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT value::text, note FROM platform_settings WHERE key = :k"), {"k": KEY}
            )
        ).first()
    return (str(row[0]), row[1]) if row is not None else None


async def _newest_audit_id() -> str:
    async with untenanted_session() as session:
        row = (
            await session.execute(text("SELECT id FROM audit_log ORDER BY id DESC LIMIT 1"))
        ).first()
    return str(row[0]) if row is not None else str(uuid.UUID(int=0))


async def _audit_since(since: str) -> list[tuple[str, str | None]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action, object_id FROM audit_log WHERE id > :since "
                    "AND action LIKE 'platform.config%' ORDER BY id"
                ),
                {"since": since},
            )
        ).all()
    return [(str(a), b) for a, b in rows]


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    async with untenanted_session() as session:
        await session.execute(text("DELETE FROM platform_settings WHERE key = :k"), {"k": KEY})
    pc.reset_for_test()
    await pc.refresh(force=True)


# --- the read ------------------------------------------------------------------


async def test_the_list_reports_every_managed_key_with_its_source() -> None:
    token = await _make_admin()
    async with _client() as http:
        response = await http.get("/v1/ops/config", headers=_auth(token))
    assert response.status_code == 200, response.text
    body = response.json()

    keys = {f["key"]: f for f in body["fields"]}
    assert set(keys) == set(pc.managed_fields())
    # The env escape hatch, visible on the wire: this repo's `.env` sets the bucket.
    assert keys["object_store_bucket"]["source"] == "env"
    assert keys["object_store_bucket"]["editable"] is False
    assert keys["object_store_bucket"]["env_var"] == "OBJECT_STORE_BUCKET"
    # And a key nothing sets is at its code default, editable.
    assert keys[KEY]["source"] == "default"
    assert keys[KEY]["editable"] is True
    assert keys[KEY]["kind"] == "decimal"


async def test_no_credential_is_listed() -> None:
    """§1's whole point, asserted on the WIRE rather than on the model: this response is
    what a compromised admin session would read, and it must contain no vendor key."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.get("/v1/ops/config", headers=_auth(token))
    listed = {f["key"] for f in response.json()["fields"]}
    credentials = ("bolna_api_key", "sarvam_api_key", "clerk_admin_secret_key", "smtp_password")
    for credential in credentials:
        assert credential not in listed


async def test_the_read_says_whether_it_can_still_reach_the_store() -> None:
    """§52 in one field: a console that showed values without saying whether the process
    could still refresh them would render an hour-old snapshot identically to a live
    one."""
    token = await _make_admin()
    await pc.refresh(force=True)
    async with _client() as http:
        body = (await http.get("/v1/ops/config", headers=_auth(token))).json()
    assert body["stale"] is False
    assert body["never_loaded"] is False
    assert body["config_version"] > 0


# --- authorization -------------------------------------------------------------


async def test_an_operator_without_platform_config_is_refused() -> None:
    """The permission is NOT a reuse of `admin:tenants`: an operator who onboards
    clients has no business switching the platform's voice engine (§7)."""
    token = await _make_admin("operator")
    async with _client() as http:
        assert (await http.get("/v1/ops/config", headers=_auth(token))).status_code == 403
        assert (
            await http.put(
                PATH,
                headers=_auth(token, config_confirmation(KEY)),
                json={"value": "9.00", "reason": "should never land"},
            )
        ).status_code == 403
    assert await _row() is None


async def test_an_unauthenticated_request_is_refused() -> None:
    async with _client() as http:
        assert (await http.get("/v1/ops/config")).status_code in (401, 403)


# --- the write -----------------------------------------------------------------


async def test_a_value_is_stored_validated_audited_and_in_force() -> None:
    """The happy path, and every claim §7/§9 make about it in one place."""
    token = await _make_admin()
    since = await _newest_audit_id()
    async with _client() as http:
        response = await http.put(
            PATH,
            headers=_auth(token, config_confirmation(KEY)),
            json={"value": "7.25", "reason": "Q3 self-serve price change, approved in #pricing"},
        )
    assert response.status_code == 200, response.text
    body = response.json()

    # The response describes the platform one commit from now, including the SOURCE —
    # the one thing a write changes that a form cannot predict.
    assert body["previous"] is None
    assert body["field"]["value"] == "7.25"
    assert body["field"]["source"] == "db"
    assert body["key"] == KEY

    # Money survived jsonb as a STRING, never a float.
    stored = await _row()
    assert stored is not None
    assert stored[0] == '"7.25"'
    assert stored[1] == "Q3 self-serve price change, approved in #pricing"

    # The audit row landed in the same transaction as the change.
    assert (await _audit_since(since)) == [("platform.config_set", KEY)]

    # And it is in force in this process once the snapshot catches up.
    await pc.refresh(force=True)
    assert get_settings().self_serve_inr_per_min == Decimal("7.25")


async def test_a_write_without_the_confirmation_changes_nothing() -> None:
    token = await _make_admin()
    since = await _newest_audit_id()
    async with _client() as http:
        response = await http.put(
            PATH, headers=_auth(token), json={"value": "9.00", "reason": "no header sent"}
        )
    assert response.status_code == 403
    assert response.json()["type"].endswith("/step_up_required")
    # The refusal happens BEFORE any work, so a caller that sees it knows nothing moved.
    assert await _row() is None
    assert await _audit_since(since) == []


async def test_a_confirmation_for_another_key_does_not_authorise_this_one() -> None:
    """The binding, which is the whole reason the string carries the key: consent to
    raising a pool size is not consent to switching the voice engine."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            PATH,
            headers=_auth(token, config_confirmation("db_pool_size")),
            json={"value": "9.00", "reason": "replayed header from another change"},
        )
    assert response.status_code == 403
    assert await _row() is None


async def test_a_set_confirmation_does_not_authorise_a_revert() -> None:
    token = await _make_admin()
    async with _client() as http:
        await http.put(
            PATH,
            headers=_auth(token, config_confirmation(KEY)),
            json={"value": "7.25", "reason": "setting it up for the revert test"},
        )
        response = await http.delete(PATH, headers=_auth(token, config_confirmation(KEY)))
    assert response.status_code == 403
    assert await _row() is not None, "the value must still be there"


async def test_a_reason_is_required_and_may_not_be_whitespace() -> None:
    token = await _make_admin()
    async with _client() as http:
        for reason in ("", "  ", "ab"):
            response = await http.put(
                PATH,
                headers=_auth(token, config_confirmation(KEY)),
                json={"value": "9.00", "reason": reason},
            )
            assert response.status_code == 422, reason
    assert await _row() is None


# --- the refusals, each with its own code ---------------------------------------


async def test_a_value_the_app_would_reject_is_refused_at_the_screen() -> None:
    """§7: "a value the app would reject is refused at the boundary, not at the next
    boot". The `fields[]` entry carries the model's own message, so the operator reads
    what is wrong rather than that something is."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            PATH,
            headers=_auth(token, config_confirmation(KEY)),
            json={"value": "free", "reason": "not a price"},
        )
    assert response.status_code == 422
    body = response.json()
    assert body["type"].endswith("/config_value_invalid")
    assert body["fields"] and body["fields"][0]["field"] == KEY
    assert await _row() is None

    # `engine` — the one Literal field — is proved at the unit level instead
    # (`platform_config_test`), because THIS repo's `.env` sets ENGINE, so the route
    # refuses it one step earlier with `config_key_set_in_environment`. That ordering is
    # itself correct and is asserted below; asserting it here as well would only pin
    # which of two true refusals arrives first.


async def test_a_field_constraint_is_enforced_not_only_the_type() -> None:
    """`otel_traces_sample_ratio` is `float = Field(ge=0.0, le=1.0)`. A validator built
    from the bare annotation would take 5.0, store it, and drop the next deploy."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            "/v1/ops/config/otel_traces_sample_ratio",
            headers=_auth(token, config_confirmation("otel_traces_sample_ratio")),
            json={"value": 5.0, "reason": "out of range on purpose"},
        )
    assert response.status_code == 422
    assert response.json()["type"].endswith("/config_value_invalid")


async def test_a_bootstrap_key_is_refused_by_name() -> None:
    """§4: the six may never resolve from the store, and the refusal has to say WHY —
    reading APP_ENV from the database means the database decides whether dev tokens are
    accepted."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            "/v1/ops/config/app_env",
            headers=_auth(token, config_confirmation("app_env")),
            json={"value": "local", "reason": "this must never be possible"},
        )
    assert response.status_code == 422
    assert response.json()["type"].endswith("/config_key_bootstrap")
    assert "APP_ENV" in response.json()["remediation"]


async def test_a_credential_key_is_refused_and_pointed_at_the_secret_store() -> None:
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            "/v1/ops/config/sarvam_api_key",
            headers=_auth(token, config_confirmation("sarvam_api_key")),
            json={"value": "sk-live-would-be-plaintext", "reason": "must be refused"},
        )
    assert response.status_code == 422
    assert response.json()["type"].endswith("/config_key_is_a_secret")

    async with untenanted_session() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM platform_settings WHERE key = 'sarvam_api_key'")
            )
        ).scalar_one()
    assert count == 0, "an API key reached a plaintext table"


async def test_an_unknown_key_is_a_404_not_a_silent_no_op() -> None:
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            "/v1/ops/config/no_such_setting",
            headers=_auth(token, config_confirmation("no_such_setting")),
            json={"value": "x", "reason": "typo in the key name"},
        )
    assert response.status_code == 404
    assert response.json()["type"].endswith("/config_key_unknown")


async def test_a_key_set_in_the_environment_is_refused_rather_than_stored_and_ignored() -> None:
    """§8's named defect, closed at the API rather than only in the UI. Storing a row for
    an env-declared key would leave a console that accepted the write, showed the new
    value, and changed nothing."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            "/v1/ops/config/object_store_bucket",
            headers=_auth(token, config_confirmation("object_store_bucket")),
            json={"value": "hijacked", "reason": "the environment must win"},
        )
    assert response.status_code == 409
    body = response.json()
    assert body["type"].endswith("/config_key_set_in_environment")
    assert "OBJECT_STORE_BUCKET" in body["remediation"]


# --- the revert ------------------------------------------------------------------


async def test_a_revert_removes_the_row_and_is_audited() -> None:
    token = await _make_admin()
    async with _client() as http:
        await http.put(
            PATH,
            headers=_auth(token, config_confirmation(KEY)),
            json={"value": "7.25", "reason": "about to be reverted"},
        )
        since = await _newest_audit_id()
        response = await http.delete(PATH, headers=_auth(token, revert_confirmation(KEY)))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous"] == "7.25"
    assert body["field"]["source"] == "default"
    assert body["field"]["value"] == "6.00", "back to the code default"
    assert await _row() is None
    assert await _audit_since(since) == [("platform.config_reverted", KEY)]


async def test_reverting_a_key_that_was_never_set_is_a_404() -> None:
    """A 200 here would write `platform.config_reverted` into a tamper-evident ledger
    for a change nobody made — the objection `platform_confirmation` raises against the
    empty transition, one surface along."""
    token = await _make_admin()
    since = await _newest_audit_id()
    async with _client() as http:
        response = await http.delete(PATH, headers=_auth(token, revert_confirmation(KEY)))
    assert response.status_code == 404
    assert response.json()["type"].endswith("/config_not_overridden")
    assert await _audit_since(since) == []


# --- propagation ------------------------------------------------------------------


async def test_a_write_moves_the_sentinel_so_peers_converge() -> None:
    """The API write is subject to the same trigger as a psql edit — it does not bump the
    version itself, so there is no second definition of when the config changed."""
    token = await _make_admin()
    before = (await _read_version()) or 0
    async with _client() as http:
        response = await http.put(
            PATH,
            headers=_auth(token, config_confirmation(KEY)),
            json={"value": "7.25", "reason": "propagation check"},
        )
    assert response.status_code == 200
    after = await _read_version()
    assert after > before
    assert response.json()["config_version"] == after


async def _read_version() -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(text("SELECT version FROM platform_config_version WHERE id"))
            ).scalar_one()
        )
