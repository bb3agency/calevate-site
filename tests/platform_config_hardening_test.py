"""The four promises the ops console makes about a change, each pinned by a test.

D-95 says a config or credential change needs NO RESTART. That is true, and it is only
half the sentence an operator needs. The other half is what this file exists for, and
each section names the promise and the exact thing that would silently break it.

1. **`applies` tells the truth.** A key reported `live` that is really snapshotted at
   process start is a lie that costs an outage. The classification is enumerated, and
   the entries that say `on_restart` are pinned AGAINST THE CODE THAT CACHES — so if
   somebody makes `usd_inr_rate` genuinely live, a test goes red and tells them to move
   the label with it.
2. **A losing write is refused, not merged.** Two operators, one key, real concurrency.
3. **Rewriting the same value is a no-op.** No row, no sentinel, no audit, no fleet
   re-read.
4. **A unit of work never straddles a refresh.** The founder's actual question: a call
   is in progress and the config changes underneath it.

The store is a SHARED table on a shared database. Every test here writes at most one or
two keys and clears them in the fixture.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from _pytest.outcomes import Failed
from apps.api.core import platform_config as pc
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings, settings_scope
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops import config_service as cs
from apps.api.ops.config_routes import require_if_match
from calevate_shared.config import Settings
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from scripts import check_config_applies as guard
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from tests.admin_security_test import _make_admin

#: A `Decimal` money field, so every round trip here also proves hard rule 7.
KEY = "self_serve_inr_per_min"
#: A second, unrelated key — the one that proves the concurrency token is scoped to a
#: ROW and not to the fleet.
OTHER_KEY = "alerts_email"
PATH = f"/v1/ops/config/{KEY}"
#: tests/ -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
TOUCHED = (KEY, OTHER_KEY, "usd_inr_rate", "whatsapp_template_locale")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, confirm: str, etag: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Confirm-Action": confirm,
        "If-Match": etag,
    }


async def _admin_id() -> uuid.UUID:
    async with untenanted_session() as session:
        row = (await session.execute(text("SELECT id FROM admin_users LIMIT 1"))).first()
        if row is not None:
            return uuid.UUID(str(row[0]))
        admin = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:i, 'Hardening Test', 'superadmin', now(), now())"
            ),
            {"i": admin},
        )
        return admin


async def _revision(key: str) -> int:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT revision FROM platform_settings WHERE key = :k"), {"k": key}
            )
        ).first()
    return 0 if row is None else int(row[0])


async def _sentinel() -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(text("SELECT version FROM platform_config_version WHERE id"))
            ).scalar_one()
        )


async def _audit_count(action: str = "platform.config_set") -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM audit_log WHERE action = :a"), {"a": action}
                )
            ).scalar_one()
        )


async def _write(key: str, value: str, *, expected: int = 0) -> cs.WriteResult:
    """A write through the SERVICE, on its own transaction, as one operator."""
    async with untenanted_session() as session:
        result = await cs.set_value(
            session,
            key=key,
            value=value,
            note="platform_config_hardening_test",
            actor_id=await _admin_id(),
            expected_revision=expected,
        )
        await session.commit()
    return result


@contextmanager
def _named(key: str) -> Iterator[None]:
    """Name the key in a failure from a loop of them. A `DID NOT RAISE` with no subject
    sends the reader to count tuples."""
    try:
        yield
    except AssertionError as exc:  # pragma: no cover - only on a red run
        raise AssertionError(f"{key}: {exc}") from exc
    except Failed as exc:  # pragma: no cover - only on a red run
        raise AssertionError(f"{key}: {exc}") from exc


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM platform_settings WHERE key = ANY(:keys)"), {"keys": list(TOUCHED)}
        )
    pc.reset_for_test()
    await pc.refresh(force=True)


# --- 1. the `applies` classification tells the truth ----------------------------


def test_every_managed_key_says_when_a_change_takes_effect() -> None:
    """THE CLASSIFICATION IS EXHAUSTIVE, AND IT CANNOT SILENTLY ROT.

    The managed set is computed from the `Settings` model (D-96), so a field added
    tomorrow is managed the day it is added — and would arrive with no classification.
    `describe()` fails safe on that (below), and this is the check that turns the safe
    silence into a CI failure. It is the guard's own function rather than a re-derivation
    here, so a guard that stopped checking fails this test too.
    """
    assert guard.check_every_key_is_classified() == []
    assert guard.check_no_stale_entries() == []
    assert guard.check_reasons() == []


def test_an_unclassified_field_is_never_offered_as_editable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAIL-SAFE, NOT FAIL-CONVENIENT. The direction of the default is the whole design.

    A missing classification means "this build does not know when a change would take
    effect". Defaulting that to `live` — which is what the previous implementation did
    for every key outside its two small dicts — is the failure mode with the outage in
    it: an operator changes a value, the console says it is live, and it is not.

    Asserted on a REAL managed key with its entry removed, so this exercises the same
    path a new `Settings` field would take.
    """
    entries = dict(pc.FIELD_APPLIES)
    entries.pop(KEY)
    monkeypatch.setattr(pc, "FIELD_APPLIES", entries)

    field = next(f for f in pc.describe(get_settings()) if f.key == KEY)
    assert field.applies == "unclassified"
    assert field.editable is False, "an unclassified field was offered for editing"
    assert field.caveat and "FIELD_APPLIES" in field.caveat, "the console must say what to fix"


async def test_an_unclassified_field_cannot_be_stored_either(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`editable: false` on the screen is a hint; the refusal at the write is the control.

    A console is not the only caller — a runbook curl is one too — so the read-side
    honesty has to be backed by a write-side refusal or it protects only the browser.
    """
    entries = dict(pc.FIELD_APPLIES)
    entries.pop(KEY)
    monkeypatch.setattr(pc, "FIELD_APPLIES", entries)

    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await cs.set_value(
                session,
                key=KEY,
                value="9.00",
                note="should never land",
                actor_id=await _admin_id(),
                expected_revision=0,
            )
    assert raised.value.code == "config_key_unclassified"
    assert await _revision(KEY) == 0, "an unclassifiable value reached the store"


async def test_the_fx_rate_is_on_restart_because_the_engine_captured_it() -> None:
    """`usd_inr_rate` IS NOT LIVE, AND THE CONSOLE NOW SAYS SO. This is the audit finding.

    `get_engine()` caches one adapter per engine name for the life of the process, and
    `BolnaEngine.__init__` copies the rate into `self._fx_rate`. So a rate changed in the
    console reaches `get_settings()` in a few seconds and does NOT reach the conversion
    that stamps `usage_events.meta` — the platform keeps costing minutes at the old rate
    until every process restarts. It was classified `live`, which is the worst possible
    answer on a money path: the operator sees no error and believes the change took.

    THIS TEST PINS THE CODE AND THE LABEL TOGETHER. If somebody makes the adapter read
    the rate per call — which would be the better fix and is reported as such — this goes
    red and the `on_restart` entry has to move with it. That is the point: the label may
    not drift from the behaviour in either direction.
    """
    from apps.api.engine import get_engine, reset_engine_cache

    reset_engine_cache()
    await _write("usd_inr_rate", "88.00")
    await pc.refresh(force=True)
    settings = get_settings().model_copy(update={"engine": "bolna"})
    engine = get_engine(settings)
    captured = engine._fx_rate  # type: ignore[attr-defined]
    assert captured == Decimal("88.00")

    # A new rate, fully propagated into this process's settings...
    await _write("usd_inr_rate", "91.50", expected=await _revision("usd_inr_rate"))
    await pc.refresh(force=True)
    assert get_settings().usd_inr_rate == Decimal("91.50")

    # ...and the adapter that actually converts money has not moved.
    assert get_engine(get_settings().model_copy(update={"engine": "bolna"}))._fx_rate == Decimal(  # type: ignore[attr-defined]
        "88.00"
    ), "the engine picked the new rate up — make `usd_inr_rate` live in FIELD_APPLIES"
    assert pc.applies_rule("usd_inr_rate").applies == pc.ON_RESTART
    reset_engine_cache()


def test_the_clerk_jwks_keys_are_on_restart_because_the_client_is_built_once() -> None:
    """The three Clerk keys decide a JWKS URL that is baked into a cached `PyJWKClient`.

    `core/auth._jwk_clients` holds one client per realm for the life of the process, and
    the URL is computed when it is constructed. Changing the publishable key or the
    frontend API in the console therefore changes nothing until a restart — and all
    three were reported `live`. On an AUTH path, "the operator believes the change took"
    is a worse outcome than on most.
    """
    from apps.api.core import auth

    assert "_jwk_clients" in vars(auth), "the cache moved — re-derive these classifications"
    for key in (
        "clerk_admin_publishable_key",
        "clerk_client_publishable_key",
        "clerk_frontend_api",
    ):
        assert pc.applies_rule(key).applies == pc.ON_RESTART, key
        assert "PyJWKClient" in (pc.applies_rule(key).caveat or "") or "same" in (
            pc.applies_rule(key).caveat or ""
        )


async def test_db_pool_size_is_env_only_and_the_store_refuses_it() -> None:
    """A THIRD FAILURE MODE THE OLD TWO-VALUE VOCABULARY COULD NOT EXPRESS.

    `db_pool_size` was `on_restart`, which PROMISES that a restart applies the stored
    value. It does not: `db/session.get_engine` builds the engine from a bare
    `Settings()` — the environment only — and it has to, because reading
    `platform_settings` requires a connection from the pool it would be sizing. So a
    console value can never apply, restart or not, and the honest answer is a refusal
    naming the variable to set instead.
    """
    assert pc.applies_rule("db_pool_size").applies == pc.ENV_ONLY
    field = next(f for f in pc.describe(get_settings()) if f.key == "db_pool_size")
    assert field.editable is False
    assert "DB_POOL_SIZE" in (field.caveat or "")

    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await cs.set_value(
                session,
                key="db_pool_size",
                value=24,
                note="would never take effect",
                actor_id=await _admin_id(),
                expected_revision=0,
            )
    assert raised.value.code == "config_key_env_only"
    assert await _revision("db_pool_size") == 0


def test_the_engine_and_the_webhook_url_need_a_republish_not_a_restart() -> None:
    """The category that neither `live` nor `on_restart` can express honestly.

    Both are baked into an agent's engine-side config at publish time
    (`agents/service._to_config` builds `webhook_url` from BOTH), and `agents.engine`
    records which vendor the agent was created on. Waiting does not fix it and neither
    does a restart: every live agent has to be published again. A console that said
    `live` would be telling an operator their engine switch had taken effect while every
    existing agent still routed to the previous vendor.
    """
    for key in ("webhook_base_url", "engine"):
        rule = pc.applies_rule(key)
        assert rule.applies == pc.NEEDS_REPUBLISH, key
        assert "publish" in (rule.caveat or "").lower(), key


def test_a_string_field_with_a_pattern_is_not_rendered_as_money() -> None:
    """`_kind_of` USED TO GUESS `decimal` FROM "string with a pattern".

    That is `Decimal`'s serialization schema — and also the schema of any string field
    carrying a `Field(pattern=…)`. The first one to exist (`webhook_base_url`, whose
    pattern now requires an http(s) scheme) rendered in the console as a money editor.
    The kind is read off the ANNOTATION now, which cannot be confused by a constraint.
    """
    kinds = {f.key: f.kind for f in pc.describe(get_settings())}
    assert kinds["webhook_base_url"] == "string"
    assert kinds["usd_inr_rate"] == "decimal"
    assert kinds["self_serve_inr_per_min"] == "decimal"


# --- 2. a losing write is refused, not merged -----------------------------------


async def test_two_operators_writing_one_key_at_once_leave_exactly_one_winner() -> None:
    """A REAL RACE, not two sequential calls with a comment saying "concurrent".

    Two independent database sessions, both holding the token they read, both writing at
    the same instant through `asyncio.gather`. Postgres decides the order; the property
    is that the second one to arrive is REFUSED rather than silently overwriting the
    first. Without the per-key advisory lock both would read revision N, both would pass
    the precondition and both would write — which is last-write-wins with a version
    column bolted on to look handled.
    """
    await _write(KEY, "6.50")
    token = await _revision(KEY)
    actor = await _admin_id()

    async def attempt(value: str) -> str:
        async with untenanted_session() as session:
            try:
                await cs.set_value(
                    session,
                    key=KEY,
                    value=value,
                    note=f"concurrent attempt {value}",
                    actor_id=actor,
                    expected_revision=token,
                )
                await session.commit()
            except ProblemError as exc:
                await session.rollback()
                return exc.code
        return "won"

    outcomes = await asyncio.gather(attempt("7.00"), attempt("8.00"))

    assert sorted(outcomes) == ["config_value_changed", "won"], outcomes
    async with untenanted_session() as session:
        stored = (
            await session.execute(
                text("SELECT value::text FROM platform_settings WHERE key = :k"), {"k": KEY}
            )
        ).scalar_one()
    # Whichever won, the value is ONE of the two attempts and never a merge or the
    # pre-race value.
    assert stored in ('"7.00"', '"8.00"')


async def test_the_per_key_lock_serializes_writers_and_only_within_the_key() -> None:
    """THE PART A VERSION COLUMN USUALLY SHIPS WITHOUT, and the test above cannot see.

    A precondition is only a control if check-then-write is ATOMIC. Two writers that both
    read revision N both satisfy it and both write; the second silently wins, and the
    column is decoration. The lock is what makes the second writer read the FIRST one's
    revision.

    Written as a DIRECT test of the lock because the end-to-end race above could not
    distinguish the two: removing the lock left it green — psycopg's round trips over
    loopback happen to serialize the two coroutines, so the interleaving the lock exists
    to survive never occurred. A test that cannot produce the condition it guards against
    is not evidence, and the honest fix is to assert the mechanism where it IS
    observable: a second transaction asking for the same key must WAIT, and one asking
    for a different key must not.

    `lock_timeout` covers advisory locks (verified against this Postgres: the second
    acquisition raises `LockNotAvailable` rather than hanging), which is what makes the
    "it blocked" half assertable without a test that can hang forever.
    """
    async with untenanted_session() as holder:
        await cs._lock_key(holder, KEY)

        async with untenanted_session() as rival:
            await rival.execute(text("SET LOCAL lock_timeout = '400ms'"))
            with pytest.raises(OperationalError) as raised:
                await cs._lock_key(rival, KEY)
            assert "lock timeout" in str(raised.value), (
                "a second writer of this key did not wait — check-then-write is not atomic"
            )

        # SCOPED TO THE KEY, not to the table: an operator changing `alerts_email` must
        # never queue behind one changing the price.
        async with untenanted_session() as neighbour:
            await neighbour.execute(text("SET LOCAL lock_timeout = '400ms'"))
            await cs._lock_key(neighbour, OTHER_KEY)


async def test_the_refusal_says_what_the_value_is_now_and_hands_back_a_usable_token() -> None:
    """A 409 THAT ONLY SAYS "CONFLICT" IS LAST-WRITE-WINS WITH EXTRA STEPS.

    An operator who is told "somebody else got there first" and nothing else retries
    blindly, because retrying is the only move the message leaves them. The refusal has
    to carry the value that is in force NOW, who put it there, and the fresh token — so
    the next act is a DECISION rather than a reflex.
    """
    token_admin = await _make_admin()
    await _write(KEY, "6.50")
    stale = '"0"'  # what an operator's screen said before anybody stored anything

    async with _client() as http:
        response = await http.put(
            PATH,
            headers=_headers(token_admin, f"set_config:{KEY}", stale),
            json={"value": "9.00", "reason": "writing over a value I never saw"},
        )

    assert response.status_code == 412, response.text
    body = response.json()
    assert body["type"].endswith("/config_value_changed")
    assert "6.50" in body["detail"], "the operator cannot decide without the current value"
    assert body["remediation"] and "If-Match" in body["remediation"]
    # The fresh token, on the header a conditional client already reads.
    assert response.headers["ETag"] == f'"{await _revision(KEY)}"'
    async with untenanted_session() as session:
        assert (
            await session.execute(
                text("SELECT value::text FROM platform_settings WHERE key = :k"), {"k": KEY}
            )
        ).scalar_one() == '"6.50"', "the loser's value was merged in"


async def test_an_unrelated_key_changing_does_not_invalidate_this_edit() -> None:
    """WHY THE TOKEN IS PER KEY AND NOT THE FLEET SENTINEL.

    `platform_config_version` already exists and would have been the easy token. It moves
    on EVERY key, so an operator editing `alerts_email` would invalidate another
    operator's in-flight edit to the price — a conflict that is not one. False conflicts
    are how people learn to hit retry without reading, which is the failure this feature
    exists to prevent.

    Asserted by moving the fleet sentinel between the read and the write and requiring
    the write to still land.
    """
    await _write(KEY, "6.50")
    token = await _revision(KEY)
    before = await _sentinel()

    await _write(OTHER_KEY, "ops@example.test")  # somebody else's unrelated change
    assert await _sentinel() > before, "the fleet sentinel did not move — the test proves nothing"

    result = await _write(KEY, "7.75", expected=token)
    assert result.recorded is True
    assert result.new == "7.75"


async def test_a_token_read_before_a_revert_can_never_write_afterwards() -> None:
    """THE REASON THE TOKEN IS A SEQUENCE AND NOT A PER-ROW COUNTER.

    A per-row `revision = revision + 1` restarts at 1 when the row is deleted and
    recreated, so a token an operator read BEFORE a revert would match the row that
    replaced it — the exact stale write this refuses, wearing a fresh row. A global
    sequence never reissues a value, so the token dies with the row.
    """
    await _write(KEY, "6.50")
    stale = await _revision(KEY)

    async with untenanted_session() as session:
        await cs.clear_value(session, key=KEY, actor_id=await _admin_id(), expected_revision=stale)
        await session.commit()
    await _write(KEY, "7.00")  # somebody sets it again from scratch

    assert await _revision(KEY) > stale, "the sequence reissued a token"
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await cs.set_value(
                session,
                key=KEY,
                value="99.00",
                note="a token from two lifetimes ago",
                actor_id=await _admin_id(),
                expected_revision=stale,
            )
    assert raised.value.code == "config_value_changed"


async def test_a_refusal_after_a_revert_says_the_value_is_gone_rather_than_inventing_one() -> None:
    """THE OTHER SHAPE OF A LOST UPDATE, and it needs its own sentence.

    Operator A reads the price. Operator B reverts the key to its code default. A's write
    must be refused — their token is dead — and the refusal must say what actually
    happened. "It is now null, set by nobody" would be a fabrication: there is no row and
    therefore no value, no actor and no timestamp to report. The message says the row was
    reverted, which is the fact, and it is the fact that tells A their next act is to
    decide whether the default is now correct rather than to re-send.
    """
    await _write(KEY, "6.50")
    stale = await _revision(KEY)
    async with untenanted_session() as session:
        await cs.clear_value(session, key=KEY, actor_id=await _admin_id(), expected_revision=stale)
        await session.commit()

    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await cs.set_value(
                session,
                key=KEY,
                value="9.00",
                note="writing over a row that was reverted underneath me",
                actor_id=await _admin_id(),
                expected_revision=stale,
            )
    problem = raised.value
    assert problem.code == "config_value_changed"
    assert problem.status == 412
    assert "reverted" in (problem.detail or ""), problem.detail
    assert problem.headers["ETag"] == '"0"', "the fresh token for an absent row is 0"


async def test_repairing_a_row_that_no_longer_parses_is_a_real_write_not_a_no_op() -> None:
    """THE TWO HARDENING RULES MEET HERE, AND ONE OF THEM HAS TO GIVE.

    §6 says a stored value that stops parsing after a code change must be refused by the
    snapshot and skipped — so the platform keeps serving. §3 says writing the value that
    is already stored is a no-op. Put together naively they strand the operator: the row
    is bad, the console shows the EFFECTIVE (default) value, and an operator who types
    that same value to repair the row would be told "already the value" while the bad row
    stays exactly where it is, still being skipped on every refresh, for ever.

    So a row that does not parse is never a no-op. `_is_noop` asks `typed_strict`, which
    RAISES rather than folding a broken row into `None` — the lenient spelling would make
    a bad row compare equal to an incoming `null` and swallow the repair.
    """
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_settings (key, value, updated_by, note) "
                "VALUES (:k, '\"not a number\"'::jsonb, :by, 'written by an older build') "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ),
            {"k": KEY, "by": await _admin_id()},
        )
        await session.commit()

    # The snapshot refuses the bad row and keeps serving the code default (§6).
    await pc.refresh(force=True)
    assert KEY not in (await pc.refresh(force=True)).overrides

    result = await _write(KEY, "6.00", expected=await _revision(KEY))
    assert result.recorded is True, "the repair was swallowed as 'already the value'"
    await pc.refresh(force=True)
    assert get_settings().self_serve_inr_per_min == Decimal("6.00")


async def test_a_write_with_no_if_match_is_refused_and_says_which_header() -> None:
    """REQUIRED, NOT OPTIONAL. An optional precondition protects only the callers who
    remember to send one, which makes "a losing write is refused" a property of one
    client rather than of the surface."""
    token = await _make_admin()
    async with _client() as http:
        response = await http.put(
            PATH,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": f"set_config:{KEY}",
            },
            json={"value": "9.00", "reason": "unconditional write"},
        )
    assert response.status_code == 428, response.text
    assert response.json()["type"].endswith("/config_if_match_required")
    assert await _revision(KEY) == 0


@pytest.mark.parametrize("header", ["*", 'W/"3"', '"3", "4"', "3", "", '""'])
def test_the_precondition_refuses_every_shape_that_would_weaken_it(header: str) -> None:
    """`*` MEANS "ANY CURRENT REPRESENTATION", WHICH IS THE UNCONDITIONAL WRITE.

    RFC 9110 permits `*`, weak tags and comma lists on `If-Match`; every one of them
    would put back some of what this control removes. `*` is an unconditional write with
    a header in front of it, a weak tag asserts semantic equivalence nobody can claim
    about two values of an FX rate, and a list makes "which value did I overwrite"
    unanswerable in the audit row.
    """
    with pytest.raises(ProblemError) as raised:
        require_if_match(header, key=KEY)
    assert raised.value.code == "config_if_match_invalid"


# --- 3. rewriting the same value changes nothing --------------------------------


async def test_storing_the_value_that_is_already_stored_writes_nothing_at_all() -> None:
    """A DOUBLE-CLICKED SAVE MUST NOT COST THE FLEET A ROUND TRIP.

    Four things must not happen, and each is checked, because any one of them alone
    would still be a defect: no row is touched (the revision does not move), the sentinel
    does not move (so no process re-reads Postgres for a change that did not happen), no
    audit row lands (`audit_log` is hash-chained and is the answer to "who changed
    this"), and the response says `recorded: false` so the console can render "already
    the value" instead of a change nobody made — D-82's convention.
    """
    first = await _write(KEY, "7.25")
    assert first.recorded is True

    revision_before = await _revision(KEY)
    sentinel_before = await _sentinel()
    audits_before = await _audit_count()

    second = await _write(KEY, "7.25", expected=revision_before)

    assert second.recorded is False
    assert second.old == second.new == "7.25"
    assert await _revision(KEY) == revision_before, "the row was rewritten"
    assert await _sentinel() == sentinel_before, "every process just re-read for nothing"
    assert await _audit_count() == audits_before


async def test_the_no_op_is_decided_on_the_validated_value_not_the_raw_input() -> None:
    """`9.5` AND `"9.50"` ARE THE SAME MONEY AND MUST NOT LOOK LIKE A CHANGE.

    A comparison against the raw request body would call those two different values,
    bump the sentinel and put a second audit row in the chain — a change nobody made,
    caused by a form that formats its number differently from the one that stored it.
    """
    await _write(KEY, "9.50")
    sentinel_before = await _sentinel()
    result = await _write(KEY, 9.5, expected=await _revision(KEY))
    assert result.recorded is False
    assert await _sentinel() == sentinel_before


async def test_a_no_op_over_http_writes_no_audit_row_and_makes_no_process_re_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same property through the ROUTE, where the audit row and the FLEET RE-READ are
    decided — neither is visible from the service.

    `propagate()` is counted rather than assumed. Found by sabotage: scheduling it
    unconditionally left this test green when it only checked the audit row, so the claim
    "no process in the fleet re-reads Postgres for a change that changed nothing" was
    asserted by a docstring and by nothing else. `propagate` forces a snapshot rebuild in
    THIS process and republishes the sentinel, which is the work every peer then repeats.
    """
    calls = 0

    async def _counting_propagate() -> int:
        nonlocal calls
        calls += 1
        return await cs.propagate()

    monkeypatch.setattr("apps.api.ops.config_routes.propagate", _counting_propagate)

    token = await _make_admin()
    async with _client() as http:
        first = await http.put(
            PATH,
            headers=_headers(token, f"set_config:{KEY}", '"0"'),
            json={"value": "7.25", "reason": "the first click"},
        )
        assert first.status_code == 200, first.text
        assert first.json()["recorded"] is True
        etag = first.json()["etag"]
        assert calls == 1, "a real change must propagate"

        audits_before = await _audit_count()
        second = await http.put(
            PATH,
            headers=_headers(token, f"set_config:{KEY}", etag),
            json={"value": "7.25", "reason": "the second click, 200ms later"},
        )

    assert second.status_code == 200, second.text
    body = second.json()
    assert body["recorded"] is False
    assert body["etag"] == etag, "a no-op moved the token"
    assert second.headers["ETag"] == etag
    assert await _audit_count() == audits_before, "a double click wrote a second audit row"
    assert calls == 1, "a double click made every process in the fleet re-read Postgres"


# --- 4. no unit of work straddles a refresh -------------------------------------


async def test_two_keys_that_must_agree_are_never_observed_half_applied() -> None:
    """THE TORN READ, RACED RATHER THAN REASONED ABOUT.

    A refresher flips a PAIR of keys between two internally consistent states while a
    reader reads them. The pair here is a rate and a price; on a money path, observing
    the new rate with the old price is a WRONG number, not a stale one.

    Both halves are asserted, because they are different guarantees:

    * a single `get_settings()` is coherent — the override layer is REPLACED as one
      dict and the cache cleared behind it, never mutated key by key;
    * a `settings_scope()` holds one answer across many reads, which is what a request
      or a job actually does.

    The refresher runs `apply_platform_overrides` directly rather than through the
    database so the flip happens hundreds of times inside the test rather than a handful,
    which is what makes the absence of a torn read evidence instead of luck.
    """
    from apps.api.core.settings import apply_platform_overrides

    # Two consistent states. A reader that ever sees a mixed pair has torn.
    low = {"usd_inr_rate": Decimal("80.00"), KEY: Decimal("5.00")}
    high = {"usd_inr_rate": Decimal("95.00"), KEY: Decimal("9.00")}
    consistent = {(Decimal("80.00"), Decimal("5.00")), (Decimal("95.00"), Decimal("9.00"))}
    stop = False
    torn: list[tuple[Decimal, Decimal]] = []
    # PRIMED BEFORE EITHER TASK RUNS. Without this the reader's very first read lands
    # before the flipper's first scheduling slice and sees the code defaults — a mixed
    # pair that is not a tear, which would make this test fail for a reason that has
    # nothing to do with what it asserts.
    apply_platform_overrides(low)

    async def flipper() -> None:
        state = low
        while not stop:
            apply_platform_overrides(state)
            state = high if state is low else low
            await asyncio.sleep(0)

    async def reader() -> None:
        for _ in range(2_000):
            settings = get_settings()
            pair = (settings.usd_inr_rate, settings.self_serve_inr_per_min)
            if pair not in consistent:
                torn.append(pair)
            await asyncio.sleep(0)

    flip = asyncio.create_task(flipper())
    try:
        await reader()
    finally:
        stop = True
        await flip
        apply_platform_overrides({})

    assert torn == [], f"a request saw a half-applied configuration: {torn[:3]}"

    # And the scope holds ONE of those states for its whole life, ACROSS a flip: the pin
    # is opened on `low`, `high` lands underneath it, and every read inside still returns
    # `low` — both halves of it, which is the property a money path needs.
    apply_platform_overrides(low)
    try:
        with settings_scope() as pinned:
            apply_platform_overrides(high)
            assert get_settings() is pinned
            assert (get_settings().usd_inr_rate, get_settings().self_serve_inr_per_min) == (
                Decimal("80.00"),
                Decimal("5.00"),
            )
    finally:
        apply_platform_overrides({})


async def test_a_request_keeps_the_configuration_it_started_with() -> None:
    """THE FOUNDER'S QUESTION: work is already running when the config changes.

    A refresh that lands mid-request must not change the answer the request has already
    acted on. Without the pin, `get_settings()` before and after the refresh return
    different objects and a handler that reads a value twice acts on two configurations.

    Raced against a REAL refresh (`apply_platform_overrides`, the one door a store value
    comes through), and asserted on the VALUE rather than on object identity alone — an
    implementation that returned a fresh-but-equal object would pass an identity check
    and still be wrong the moment the value differed.
    """
    from apps.api.core.settings import apply_platform_overrides

    apply_platform_overrides({KEY: Decimal("4.00")})
    try:
        with settings_scope():
            before = get_settings().self_serve_inr_per_min
            apply_platform_overrides({KEY: Decimal("12.00")})  # the console lands mid-request
            after = get_settings().self_serve_inr_per_min
            assert before == after == Decimal("4.00"), (
                "the request changed configuration mid-flight"
            )
        # Outside the scope the process is on the new value immediately — the pin bounds
        # a unit of work, it does not delay propagation.
        assert get_settings().self_serve_inr_per_min == Decimal("12.00")
    finally:
        apply_platform_overrides({})


async def test_a_nested_scope_reuses_the_outer_pin_rather_than_re_resolving() -> None:
    """An inner unit of work is PART of the outer one.

    Re-resolving on entry would put the straddle back exactly where it is hardest to
    see: a helper that opens its own scope inside a request would silently run on a
    different configuration from its caller.
    """
    from apps.api.core.settings import apply_platform_overrides

    apply_platform_overrides({KEY: Decimal("4.00")})
    try:
        with settings_scope() as outer:
            apply_platform_overrides({KEY: Decimal("12.00")})
            with settings_scope() as inner:
                assert inner is outer
                assert inner.self_serve_inr_per_min == Decimal("4.00")
    finally:
        apply_platform_overrides({})


async def test_an_http_request_is_pinned_by_the_middleware() -> None:
    """The wiring, not just the primitive. A `settings_scope()` nothing enters is a
    half-wired feature: the API and voice-runtime share `create_app`, so one middleware
    covers both, and this proves it is actually in the chain."""
    from apps.api.core.settings import _pinned

    seen: list[bool] = []

    @app.get("/_test/pinned", include_in_schema=False)
    async def _probe() -> dict[str, bool]:
        seen.append(_pinned.get() is not None)
        return {"pinned": seen[-1]}

    try:
        async with _client() as http:
            body = (await http.get("/_test/pinned")).json()
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", None) != "/_test/pinned"
        ]
    assert body["pinned"] is True, "requests are not pinned — a refresh can land mid-handler"


def test_the_halt_and_the_load_shed_mode_are_deliberately_not_settings() -> None:
    """WHICH VALUES ARE LIVE-IMMEDIATE, AND WHY THAT IS A DIFFERENT MECHANISM.

    The big red switch must take effect MID-TICK — that is the whole point of a global
    outbound halt — so pinning it per unit of work would be exactly wrong. It is not a
    `Settings` field at all: it lives in `platform_state` and is read through
    `core/loadshed`, whose TTL is bounded under one dispatch tick, and
    `compliance.check_dispatch` re-reads it PER CONTACT rather than per tick.

    That separation is the doctrine, and this test is what stops it eroding: anything
    that must interrupt work in progress is STATE and goes in that table; anything
    reachable from `Settings` is configuration and is pinned for the work that read it.
    A halt that arrived as a `Settings` field would be silently pinned by the middleware
    above and would stop dialling one tick later than an operator expects.
    """
    fields = set(Settings.model_fields)
    for state in ("outbound_halted", "halt_reason", "load_shed_mode", "tm_registration_status"):
        assert state not in fields, (
            f"{state} became a Settings field — it would now be pinned per unit of work, "
            "and a halt that takes effect a tick late is not a halt"
        )


# --- 5. a bad value must not brick the fleet ------------------------------------


def test_a_type_valid_but_catastrophic_value_is_refused_by_the_field_itself() -> None:
    """BOUNDS BELONG ON THE FIELD, so the write path, the boot-time load and the console
    all read them from one place.

    Every value below passes its TYPE and breaks something real: a zero FX rate bills
    every Bolna minute at nothing, a zero price makes every self-serve minute free, port
    0 never connects, and a pool of 500 across four voice-runtime processes asks for
    2000 backends against `max_connections = 200`.
    """
    for key, bad in (
        ("usd_inr_rate", "0"),
        ("usd_inr_rate", "-1"),
        ("self_serve_inr_per_min", "0"),
        ("smtp_port", 0),
        ("smtp_port", 70_000),
        ("db_pool_size", 500),
        ("webhook_base_url", "hooks.calevate.tech"),  # no scheme: the engine calls nothing
        ("gst_supplier_address", "x" * 1001),  # a novel in a column every process re-reads
        ("alerts_email", "x" * 400),
    ):
        with pytest.raises(ValidationError), _named(key):
            pc.validate_value(key, bad)

    # A bound that refuses a value a CONSUMER already degrades on gracefully would turn a
    # survivable misconfiguration into a process that cannot boot. `gst_supplier_gstin`
    # is the case: `billing/gst.parse_gstin` treats a malformed one as absent and renders
    # a proforma naming the missing key, so the model caps its LENGTH and does not check
    # its shape. This pins that direction, because the obvious "improvement" is to make
    # the model exact — and `invoice_gst_test` is where that goes red.
    assert pc.validate_value("gst_supplier_gstin", "36AABCC1234D1Z") == "36AABCC1234D1Z"

    # And the neighbouring good values still pass, so the bound is a bound and not a ban.
    assert pc.validate_value("usd_inr_rate", "91.50") == "91.50"
    assert pc.validate_value("smtp_port", 587) == 587
    assert pc.validate_value("webhook_base_url", "https://hooks.calevate.tech") == (
        "https://hooks.calevate.tech"
    )


def test_every_managed_field_is_bounded() -> None:
    """The bound is DERIVED, so a field added tomorrow is checked without anybody
    remembering this test exists. Runs the guard's own function: a guard that stopped
    checking fails here too."""
    assert guard.check_bounds() == []


async def test_one_unparseable_row_is_refused_and_the_rest_of_the_refresh_lands() -> None:
    """A CODE CHANGE THAT NARROWS A TYPE MUST NOT FREEZE THE FLEET'S CONFIGURATION.

    `smtp_port` now carries `le=65535`. A row written by an older build with `70000` in
    it is type-valid JSON and no longer a valid value — and the refresh has to refuse
    THAT KEY and keep serving every other one. Failing the whole refresh would leave
    every process stuck on its last snapshot, which is the failure §6 forbids, triggered
    by a deploy rather than by an outage.

    Written straight to the table, bypassing the API, because the API refuses it — which
    is the point: this is the row that exists BECAUSE the code changed after it was
    written.
    """
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_settings (key, value, updated_by, note) "
                "VALUES ('smtp_port', '70000'::jsonb, :by, 'written by an older build') "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ),
            {"by": await _admin_id()},
        )
        await session.commit()
    try:
        await _write(KEY, "8.25")
        snapshot = await pc.refresh(force=True)

        assert snapshot.degraded is False, "one bad row degraded the whole snapshot"
        assert "smtp_port" not in snapshot.overrides, "an invalid value reached Settings"
        assert get_settings().smtp_port == Settings.model_fields["smtp_port"].get_default(
            call_default_factory=True
        )
        assert get_settings().self_serve_inr_per_min == Decimal("8.25"), "the good row was dropped"
    finally:
        async with untenanted_session() as session:
            await session.execute(text("DELETE FROM platform_settings WHERE key = 'smtp_port'"))
            await session.commit()


# --- 6. the restart that IS genuinely needed still drains -----------------------


#: A whole service, in a subprocess, killed mid-request.
#:
#: A SUBPROCESS AND NOT AN IN-PROCESS SERVER, for one reason: this test sends SIGTERM,
#: and the defect it pins is precisely that SIGTERM used to raise `KeyboardInterrupt`
#: out of the event loop. Delivered to the pytest process, that would end the suite
#: rather than fail one test — a test that takes the run down with it when it fails is
#: not a test.
_DRAIN_PROBE = """
import asyncio, os, signal, sys
import httpx, uvicorn
from fastapi import FastAPI
from apps.api.core.bootstrap import create_app

app: FastAPI = create_app(service="drainprobe", title="drain probe", minimal=True)

@app.get("/slow")
async def slow() -> dict[str, str]:
    await asyncio.sleep(1.5)
    return {"ok": "finished"}

async def main() -> None:
    # PORT 0: the kernel picks a free one and uvicorn reports it back. A fixed port
    # made this test fail whenever another run of the suite held it — a red that says
    # "the drain broke" when nothing drained wrong is worse than no test.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical"))
    serve = asyncio.create_task(server.serve())
    for _ in range(400):
        if server.started:
            break
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]

    async def call() -> None:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get("http://127.0.0.1:%d/slow" % port)
                print("INFLIGHT", response.status_code, flush=True)
        except Exception as exc:
            print("INFLIGHT-ABORTED", type(exc).__name__, flush=True)

    inflight = asyncio.create_task(call())
    await asyncio.sleep(0.4)          # the request is now sleeping inside the handler
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.gather(serve, inflight, return_exceptions=True)

try:
    asyncio.run(main())
except BaseException as exc:
    print("ESCAPED", type(exc).__name__, flush=True)
"""


def test_a_sigterm_mid_request_drains_it_instead_of_aborting_it(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """THE FOUNDER'S FEAR, MEASURED — and it was real before this slice.

    "if any calls are happening in that moment they will fail". `_install_signal_handlers`
    documented itself as adding an alert to uvicorn's drain, and instead REPLACED
    uvicorn's handler with one that raised `KeyboardInterrupt`: `Server.serve()` installs
    its handlers and only then runs the lifespan, so ours ran second and won. Measured
    with this exact probe before the fix, the output was `ESCAPED KeyboardInterrupt` —
    the in-flight request never completed, `Server.shutdown()` (close the sockets, then
    WAIT for open connections) never ran, and the lifespan's own `finally` never ran, so
    Redis was not closed and pending spans were dropped.

    `hooks.calevate.tech` is voice-runtime, the only service with live calls on it, and
    Bolna webhooks are at-most-once with no retry (D-31): every deploy dropped whatever
    was in flight, and `stop_grace_period: 30s` in compose.prod.yml had nothing to give
    its 30 seconds to.

    Asserted on the REQUEST rather than on the handler, because the handler is not the
    property: what matters is that a request already accepted is answered.
    """
    script = tmp_path / "drain_probe.py"
    script.write_text(_DRAIN_PROBE)
    completed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=90,
        cwd=str(REPO_ROOT),
        # The repo root on the path, exactly as pytest's own `pythonpath = ["."]` puts
        # it there: `apps` is a virtual workspace member imported by path, so a bare
        # subprocess cannot import it.
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    output = completed.stdout + completed.stderr

    assert "ESCAPED" not in output, (
        "SIGTERM escaped the event loop — uvicorn's drain never ran:\n" + output[-2000:]
    )
    assert "INFLIGHT 200" in output, (
        "a request already in flight was aborted by SIGTERM instead of being answered:\n"
        + output[-2000:]
    )
