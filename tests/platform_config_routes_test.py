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

import json
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from apps.api.core import platform_config as pc
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.core.stepup import StepUp
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops import config_service
from apps.api.ops.config_routes import (
    ConfigSetIn,
    _field,
    _projected_field,
    config_confirmation,
    revert_config,
    revert_confirmation,
    set_config,
)
from apps.api.ops.config_service import WriteResult
from calevate_shared.model_lifecycle import ATTESTATION_PATH
from fastapi import BackgroundTasks, Response
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from starlette.requests import Request
from tests.admin_security_test import _make_admin

KEY = "self_serve_inr_per_min"
PATH = f"/v1/ops/config/{KEY}"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _auth(token: str, confirm: str | None = None, etag: str | None = '"0"') -> dict[str, str]:
    """Admin token, optional step-up, and the conditional-write token.

    `etag` defaults to `"0"` — the token of a key with no stored row — because that is
    what the overwhelming majority of these cases are writing over, and threading it
    through fifteen call sites would bury the assertion each one exists for. That it is
    REQUIRED is not defaulted away: `test_a_write_without_an_if_match_is_refused` sends
    `etag=None` and is the test that would go green if the requirement were dropped.
    """
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    if etag is not None:
        headers["If-Match"] = etag
    return headers


async def _etag(key: str = KEY) -> str:
    """The key's current token, read the way the console reads it."""
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT revision FROM platform_settings WHERE key = :k"), {"k": key}
            )
        ).first()
    return f'"{0 if row is None else int(row[0])}"'


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


#: Every key this suite sends a PUT for. The teardown clears ALL of them, not just the
#: one the happy path uses.
#:
#: Found the hard way: a sabotage run that removed the field-constraint check let
#: `otel_traces_sample_ratio = 5.0` — a value the app would refuse at boot — be STORED by
#: a test that then failed on the status code. The row outlived the test, because the
#: teardown only knew about one key. A refusal test writes nothing when the code is
#: right, which is exactly why its cleanup has to be written for the case where the code
#: is wrong.
_WRITTEN_KEYS = (KEY, "otel_traces_sample_ratio", "engine", "object_store_bucket", "db_pool_size")


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM platform_settings WHERE key = ANY(:keys)"),
            {"keys": list(_WRITTEN_KEYS)},
        )
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
    """Two refusals with one message, and the second one is the one that was missing.

    `""`, `"  "` and `"ab"` are all shorter than three characters, so they never reach the
    validator at all — `Field(min_length=3)` refuses them first. `"   "` and `"  a  "` are
    the cases the validator EXISTS for: they satisfy the length bound and carry nothing.
    Without them a `reason` of three spaces would be stored as the note an operator reads
    six months later when they find this value in force, which is the same as no reason
    and looks like one.
    """
    token = await _make_admin()
    async with _client() as http:
        for reason in ("", "  ", "ab", "   ", "  a  ", "\t\n \t"):
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
        # The token from the row that now exists — a revert is conditional on the value
        # it is removing, exactly as a set is on the value it replaces.
        response = await http.delete(
            PATH, headers=_auth(token, revert_confirmation(KEY), etag=await _etag())
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["previous"] == "7.25"
    assert body["field"]["source"] == "default"
    assert body["field"]["value"] == "5.00", "back to the code default (D-466 reprice)"
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


# --- attribution, and the two internal refusals -----------------------------------


def _request() -> Request:
    """A real `Request` rather than a stub: `write_audit` reads `request.client`, and a
    stub that happened to have the attribute would stop matching the day it reads
    another."""
    return Request(
        {
            "type": "http",
            "method": "PUT",
            "path": PATH,
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
        }
    )


def _anonymous_operator() -> Principal:
    """An admin-realm principal carrying no `admin_users` row.

    Reached through the ROUTE FUNCTION rather than through HTTP, deliberately: the auth
    dependency will not mint one of these today, which is exactly why the handler's guard
    is untested by every request-level test in this file. The state is not hypothetical —
    a Clerk user whose mirror row has not landed yet resolves to precisely this — and the
    guard is what turns it into a sentence instead of a NOT NULL violation rendered as a
    500 by the global handler.
    """
    return Principal(realm="admin", user_id=None, tenant_id=None, role=None)


async def test_a_set_by_a_session_with_no_admin_identity_is_refused_and_stores_nothing() -> None:
    """§9's row names an ACTOR, and `platform_settings.updated_by` is NOT NULL.

    "Who changed the price on the day the margin moved" is the question this table exists
    to answer, so a write nobody can be attributed to must not land at all. Asserted with
    the step-up already satisfied, so what is being pinned is the identity check itself
    rather than the confirmation in front of it.
    """
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await set_config(
                ConfigSetIn(value="9.00", reason="a session with no admin row"),
                session,
                _request(),
                Response(),
                BackgroundTasks(),
                _anonymous_operator(),
                KEY,
                # The gate a request resolves through `Depends(step_up_gate)`; called
                # directly, the test supplies it. `present=False` is the shape a
                # caller with no first-party admin cookie has (D-178).
                StepUp(present=False, verified_at=None),
                x_confirm_action=config_confirmation(KEY),
                if_match='"0"',
            )
    assert raised.value.code == "config_actor_unknown"
    assert raised.value.kind == "auth"
    assert await _row() is None, "an unattributable value reached the store"


async def test_a_revert_by_a_session_with_no_admin_identity_is_refused_too() -> None:
    """The same guard on the DELETE, asserted separately because it is a separate `if`.

    A revert puts a value nobody has looked at in months back into force; it is not the
    small sibling of setting, and an unattributable one is worse — there is no `note`
    column left afterwards, so the audit row is the only record that it happened.
    """
    token = await _make_admin()
    async with _client() as http:
        await http.put(
            PATH,
            headers=_auth(token, config_confirmation(KEY)),
            json={"value": "7.25", "reason": "a row for the revert to find"},
        )

    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await revert_config(
                session,
                _request(),
                Response(),
                BackgroundTasks(),
                _anonymous_operator(),
                KEY,
                # The gate a request resolves through `Depends(step_up_gate)`; called
                # directly, the test supplies it. `present=False` is the shape a
                # caller with no first-party admin cookie has (D-178).
                StepUp(present=False, verified_at=None),
                x_confirm_action=revert_confirmation(KEY),
                if_match=await _etag(),
            )
    assert raised.value.code == "config_actor_unknown"
    assert await _row() is not None, "the row was removed by a caller with no identity"


async def test_reading_one_key_back_never_invents_a_row_for_an_unmanaged_key() -> None:
    """A CONFIG SURFACE THAT FABRICATES A FIELD IS WORSE THAN ONE THAT 500s.

    `_field` assembles a single key's view from the same function the list uses, so the
    two can never disagree about a `source` or an `editable`. That means the key has to be
    IN the list — and if it is not (a field renamed between the write and the read back,
    a managed set computed differently in two places) the honest answer is a named
    internal error an operator can report, never a placeholder the console would render
    as a real setting with a real value.

    Both directions: a managed key comes back with its own facts, and an unmanaged one
    refuses by name.
    """
    async with untenanted_session() as session:
        field = await _field(session, KEY)
        assert field.key == KEY
        assert field.env_var == "SELF_SERVE_INR_PER_MIN"
        assert field.kind == "decimal", "money must not render as a number the browser rounds"
        assert field.editable is True

        with pytest.raises(ProblemError) as raised:
            await _field(session, "no_such_setting")
    assert raised.value.code == "config_key_vanished"
    assert raised.value.kind == "internal"
    assert "no_such_setting" in (raised.value.detail or "")


def test_the_projected_response_refuses_to_describe_a_key_it_cannot_find() -> None:
    """The same refusal on the WRITE path, where the stakes are higher.

    This response is rendered from a projection — this process's settings with the write
    applied — because the caller's transaction has not committed yet. A projection that
    could not find its own key and returned the FIRST field instead would report another
    setting's value back to the operator who just changed this one, and they would believe
    it. So the miss is a named error rather than anything that looks like an answer.
    """
    with pytest.raises(ProblemError) as raised:
        _projected_field(
            WriteResult(key="no_such_setting", old='"9.00"', new=None, version=7, revision=0)
        )
    assert raised.value.code == "config_key_vanished"
    assert raised.value.kind == "internal"


async def _read_version() -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(text("SELECT version FROM platform_config_version WHERE id"))
            ).scalar_one()
        )


# --- FN-2: the attestation gate on azure_openai_resource ----------------------
#
# `azure_openai_resource` decides WHERE the language leg's traffic is processed, and its
# region is a property of the Azure resource that no automated check in this tree can read
# from the name. So a console write of it is refused unless the repo-committed attestation
# (`docs/evidence/azure-deployment-attestation.json`, OPERATIONS §2 gate 20) NAMES the
# resource being set. These pin that gate: refused with no/mismatched attestation, allowed
# when it matches, and wired into `set_value` before any database work.

_ATTESTED_RESOURCE = "calevate-eastus2"


def _write_attestation(root: Path, resource: str) -> None:
    path = root / ATTESTATION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "resource": resource,
                "resource_location": "eastus2",
                "deployment_model": "gpt-4o-mini",
                "deployment_type": "standard-regional",
                "read_on": "2026-08-24",
                "read_by": "founder",
            }
        ),
        encoding="utf-8",
    )


def test_the_resource_gate_refuses_when_no_attestation_is_filed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config_service, "_ATTESTATION_ROOT", tmp_path)
    with pytest.raises(ProblemError) as raised:
        config_service._assert_resource_attested(_ATTESTED_RESOURCE)
    assert raised.value.code == "config_resource_unattested"
    assert "no attestation" in raised.value.detail.lower()


def test_the_resource_gate_refuses_a_resource_the_attestation_does_not_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_attestation(tmp_path, _ATTESTED_RESOURCE)
    monkeypatch.setattr(config_service, "_ATTESTATION_ROOT", tmp_path)
    with pytest.raises(ProblemError) as raised:
        config_service._assert_resource_attested("calevate-southindia")
    assert raised.value.code == "config_resource_unattested"
    # The refusal names both sides so the operator knows what to file.
    assert _ATTESTED_RESOURCE in raised.value.detail
    assert "calevate-southindia" in raised.value.detail


def test_the_resource_gate_refuses_a_revert_to_the_unattested_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A revert would put the code default (unset) back in force, which the attestation
    does not name — so it is refused the same way a set to an unnamed resource is."""
    _write_attestation(tmp_path, _ATTESTED_RESOURCE)
    monkeypatch.setattr(config_service, "_ATTESTATION_ROOT", tmp_path)
    with pytest.raises(ProblemError) as raised:
        config_service._assert_resource_attested(None)
    assert raised.value.code == "config_resource_unattested"
    assert "unset default" in raised.value.detail


def test_the_resource_gate_reports_a_malformed_attestation_as_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ATTESTATION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(config_service, "_ATTESTATION_ROOT", tmp_path)
    with pytest.raises(ProblemError) as raised:
        config_service._assert_resource_attested(_ATTESTED_RESOURCE)
    assert raised.value.code == "config_resource_attestation_unreadable"


def test_the_resource_gate_passes_when_the_attestation_names_the_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_attestation(tmp_path, _ATTESTED_RESOURCE)
    monkeypatch.setattr(config_service, "_ATTESTATION_ROOT", tmp_path)
    # No raise: the attested resource is exactly the incoming one.
    config_service._assert_resource_attested(_ATTESTED_RESOURCE)


async def test_set_value_refuses_an_unattested_resource_before_touching_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate is wired into `set_value` and runs BEFORE the lock and the read: the
    session is never used on the refusal path, so an unattested write costs no database
    work and cannot half-happen."""
    monkeypatch.setattr(config_service, "_ATTESTATION_ROOT", tmp_path)  # empty: no file
    session = MagicMock()
    with pytest.raises(ProblemError) as raised:
        await config_service.set_value(
            session,
            key="azure_openai_resource",
            value=_ATTESTED_RESOURCE,
            note="pointing at a new resource",
            actor_id=uuid.uuid4(),
            expected_revision=0,
        )
    assert raised.value.code == "config_resource_unattested"
    session.execute.assert_not_called()


async def test_set_value_allows_an_attested_resource_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The allowed path end to end through `set_value`: with the attestation naming the
    resource, the write lands. Done inside one transaction and rolled back so the shared
    `platform_settings` table is left as it was found."""
    _write_attestation(tmp_path, _ATTESTED_RESOURCE)
    monkeypatch.setattr(config_service, "_ATTESTATION_ROOT", tmp_path)
    async with untenanted_session() as session:
        row = (await session.execute(text("SELECT id FROM admin_users LIMIT 1"))).first()
        if row is not None:
            actor = uuid.UUID(str(row[0]))
        else:
            actor = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                    "VALUES (:i, 'Resource Gate Test', 'superadmin', now(), now())"
                ),
                {"i": actor},
            )
        result = await config_service.set_value(
            session,
            key="azure_openai_resource",
            value=_ATTESTED_RESOURCE,
            note="attested move",
            actor_id=actor,
            expected_revision=0,
        )
        assert result.new == _ATTESTED_RESOURCE
        assert result.recorded is True
        # Leave the shared table untouched for every other suite on this database.
        await session.execute(
            text("DELETE FROM platform_settings WHERE key = 'azure_openai_resource'")
        )
