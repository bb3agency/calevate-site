"""Resolution order, write-time validation, and propagation (PLATFORM-CONFIG §4, §6).

The three claims this slice makes, and what would silently break each:

1. **`os.environ` beats the store, always.** A key set in `.env` cannot be changed from
   the console, and the console has to SAY so. Break it by resolving the store first and
   the console gains a field that appears to work and does nothing — §8's named defect.
2. **A value the app would reject is refused at the WRITE, not at the next boot.** Break
   it by validating against the bare annotation instead of the field (dropping its
   `Field(ge=…, le=…)` metadata) and `otel_traces_sample_ratio = 5.0` is stored happily
   and crashes the next deploy.
3. **A change propagates to a process that did not make it, in under 10 seconds, with no
   restart.** Break it by bumping the version in the application rather than in the
   database and a psql edit propagates to nobody.

The store is a SHARED table on a shared database, like `platform_state`: every test here
either writes nothing, or writes one key and removes it in `finally`. The key used is
`self_serve_inr_per_min`, deliberately — it is a `Decimal`, so the round trip also proves
money survives `jsonb` exactly (hard rule 7).
"""

from __future__ import annotations

import asyncio
import signal
import time
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from apps.api.core import platform_config as pc
from apps.api.core.redis import get_redis
from apps.api.core.settings import ENV_ONLY_KEYS, apply_platform_overrides, get_settings
from apps.api.db.session import untenanted_session
from calevate_shared.config import Settings
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from pydantic import ValidationError
from sqlalchemy import text

DEMO_KEY = "self_serve_inr_per_min"


async def _admin_id() -> uuid.UUID:
    async with untenanted_session() as session:
        row = (await session.execute(text("SELECT id FROM admin_users LIMIT 1"))).first()
        if row is not None:
            return uuid.UUID(str(row[0]))
        admin = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:i, :c, 'Config Test', 'superadmin', now(), now())"
            ),
            {"i": admin, "c": f"admin_{uuid.uuid4().hex[:12]}"},
        )
        return admin


async def _write_row(key: str, value: str) -> None:
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_settings (key, value, updated_by, note) "
                "VALUES (:k, CAST(:v AS jsonb), :by, 'platform_config_test') "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
            ),
            {"k": key, "v": value, "by": await _admin_id()},
        )


async def _drop_row(key: str) -> None:
    async with untenanted_session() as session:
        await session.execute(text("DELETE FROM platform_settings WHERE key = :k"), {"k": key})


@pytest.fixture(autouse=True)
async def _clean_layer() -> AsyncIterator[None]:
    """No test here may leave an override layer behind: `get_settings()` is process-wide
    and every other suite on this event loop reads it."""
    yield
    await _drop_row(DEMO_KEY)
    pc.reset_for_test()


# --- resolution order ---------------------------------------------------------


async def test_a_stored_value_reaches_get_settings() -> None:
    await _write_row(DEMO_KEY, '"9.50"')
    await pc.refresh(force=True)
    # Exact, and a Decimal — not a float that is nearly 9.50 (hard rule 7).
    assert get_settings().self_serve_inr_per_min == Decimal("9.50")


async def test_the_environment_beats_the_store() -> None:
    """§4's escape hatch, and the property the whole design rests on: you can always
    take control back from the console with a `.env` edit and a restart."""
    # `object_store_bucket` IS declared in this repo's `.env`, so the store must not be
    # able to move it.
    stored = pc._resolve(
        {"object_store_bucket": "hijacked"},
        {"OBJECT_STORE_BUCKET": "real-bucket"},
    )
    assert stored == {}


async def test_a_key_absent_from_the_environment_resolves_from_the_store() -> None:
    assert pc._resolve({DEMO_KEY: "9.50"}, {}) == {DEMO_KEY: Decimal("9.50")}


async def test_the_console_reports_an_env_sourced_key_as_read_only_with_the_env_var() -> None:
    """A field that silently does nothing is worse than no field (§8). The console needs
    three things to render the refusal: the source, `editable: false`, and WHICH variable
    to change instead."""
    fields = {f.key: f for f in pc.describe(get_settings())}
    bucket = fields["object_store_bucket"]
    assert bucket.source == "env"
    assert bucket.editable is False
    assert bucket.env_var == "OBJECT_STORE_BUCKET"


async def test_the_bootstrap_six_are_never_managed_and_never_appliable() -> None:
    """§4: the bootstrap set can never move to the database. Enforced in two independent
    places, and both are asserted, because either one alone is a single point of failure
    on a security posture: the key is not offered, AND the settings layer refuses it even
    if something offers it anyway."""
    managed = set(pc.managed_fields())
    assert not (managed & ENV_ONLY_KEYS)
    assert {
        "app_env",
        "database_url",
        "alembic_database_url",
        "platform_kek",
        "platform_kek_retired",
        "redis_url",
    } == ENV_ONLY_KEYS

    before = get_settings().app_env
    # A value that DIFFERS from the one in force. Injecting the current value would make
    # this assertion pass with the filter deleted — the test would be asserting that
    # `local` equals `local`, which is true however the code behaves. (Found by
    # sabotage: removing the filter left this green.)
    other = "staging" if before != "staging" else "prod"
    apply_platform_overrides({"app_env": other, DEMO_KEY: Decimal("1.00")})
    try:
        # The forbidden key was dropped; the harmless one beside it still landed, so the
        # filter is selective rather than a blanket refusal of the whole batch.
        assert get_settings().app_env == before, "the DATABASE just decided the environment"
        assert get_settings().self_serve_inr_per_min == Decimal("1.00")
    finally:
        apply_platform_overrides({})


async def test_a_credential_shaped_key_is_not_managed() -> None:
    """§1: a plaintext row for an API key is the failure mode the two-table design
    exists to prevent, and the rule that stops it is derived from field NAMES rather
    than from a hand-kept list that the next key would not be on."""
    managed = set(pc.managed_fields())
    for credential in (
        "bolna_api_key",
        "sarvam_api_key",
        "clerk_admin_secret_key",
        "smtp_password",
        "razorpay_webhook_secret",
        "google_sheets_service_account_json",
        "meta_page_access_tokens",
        "sentry_dsn",
        "backup_heartbeat_url",
    ):
        assert credential in Settings.model_fields, f"{credential} was renamed — update this list"
        assert credential not in managed, f"{credential} would be stored in PLAINTEXT"


async def test_a_row_for_an_unknown_key_is_dropped_rather_than_applied() -> None:
    """A field this build has never had — a rename, or a hand-inserted row. It must not
    reach `model_copy`, which does not validate and would happily attach it."""
    assert pc._resolve({"no_such_setting": 1}, {}) == {}


async def test_one_bad_row_does_not_stop_the_good_ones() -> None:
    """This resolution runs in every process on a background refresh. A single row
    written by an older build against a field that has since narrowed must not be able
    to freeze a fleet's configuration."""
    resolved = pc._resolve({DEMO_KEY: "not a number", "webhook_base_url": "https://x"}, {})
    assert resolved == {"webhook_base_url": "https://x"}


# --- write-time validation ----------------------------------------------------


def test_a_value_the_app_would_reject_is_refused_at_the_boundary() -> None:
    """§7: "validated against the `Settings` model before it is stored; a value the app
    would reject is refused at the boundary, not at the next boot"."""
    with pytest.raises(ValidationError):
        pc.validate_value("engine", "twilio")
    with pytest.raises(ValidationError):
        pc.validate_value("self_serve_inr_per_min", "free")


def test_field_constraints_are_enforced_not_just_the_type() -> None:
    """THE ONE THAT A NAIVE IMPLEMENTATION MISSES. `otel_traces_sample_ratio` is
    `float = Field(ge=0.0, le=1.0)`; validating against the bare annotation would accept
    5.0, store it, and take the next deploy down at `Settings()` construction. This is
    why `_adapter` uses `FieldInfo.rebuild_annotation()` rather than `.annotation`."""
    assert pc.validate_value("otel_traces_sample_ratio", 0.25) == 0.25
    for bad in (5.0, -0.1):
        with pytest.raises(ValidationError):
            pc.validate_value("otel_traces_sample_ratio", bad)
    with pytest.raises(ValidationError):
        pc.validate_value("db_pool_size", 0)  # Field(ge=1)


def test_money_is_stored_as_a_string_never_as_a_json_float() -> None:
    """Hard rule 7 through a `jsonb` column: `88.50` as an IEEE double is not 88.50, and
    a rate stamped into `usage_events.meta` has to be reproducible a year later."""
    stored = pc.validate_value("usd_inr_rate", "88.50")
    assert stored == "88.50" and isinstance(stored, str)
    assert pc._typed("usd_inr_rate", stored) == Decimal("88.50")


def test_no_second_field_list_exists() -> None:
    """The managed set is DERIVED from `Settings`, so a field added tomorrow is managed
    (or excluded by name) with no edit here. This pins the derivation, not the contents:
    it fails if somebody replaces the computation with a literal list."""
    derived = {
        name
        for name in Settings.model_fields
        if name not in ENV_ONLY_KEYS and not pc.is_secret_key(name)
    }
    assert set(pc.managed_fields()) == derived
    assert len(derived) == len(Settings.model_fields) - len(ENV_ONLY_KEYS) - sum(
        pc.is_secret_key(n) for n in Settings.model_fields
    )


def test_every_managed_field_can_be_described_and_rendered() -> None:
    """A field whose type the console cannot render is a row that renders as an empty
    box. Asserted over the WHOLE managed set rather than a sample, so a new `Settings`
    field of an unsupported shape fails here rather than on screen."""
    for field in pc.describe(get_settings()):
        assert field.kind in {"string", "integer", "number", "boolean", "enum", "decimal"}
        assert (field.options != ()) == (field.kind == "enum")
        assert field.source in {"env", "db", "default"}
        assert field.applies in {"live", "on_restart"}


# --- propagation --------------------------------------------------------------


async def test_a_write_bumps_the_sentinel_even_when_the_application_does_not() -> None:
    """The trigger, asserted directly. This is what makes an operator's psql edit — and
    a data-fix migration, and the next code path somebody adds — propagate."""
    async with untenanted_session() as session:
        before = (
            await session.execute(text("SELECT version FROM platform_config_version WHERE id"))
        ).scalar_one()
    await _write_row(DEMO_KEY, '"9.50"')
    async with untenanted_session() as session:
        after = (
            await session.execute(text("SELECT version FROM platform_config_version WHERE id"))
        ).scalar_one()
    assert after > before


async def test_a_write_that_publishes_through_is_seen_by_the_next_poll() -> None:
    """THE NORMAL PATH, which is how the console's own writes propagate: the row is
    written, the sentinel is bumped by the trigger, and the writing process publishes the
    new integer to Redis after COMMIT — so every peer sees it on its very next poll,
    within `_POLL_INTERVAL_S`.
    """
    await pc.refresh(force=True)
    first = pc.snapshot()
    await _write_row(DEMO_KEY, '"11.00"')
    await pc.publish_version(await pc._read_version())

    # NOT `force=True`: the poll must decide for itself that something changed.
    second = await pc.refresh()
    assert second.version > first.version
    assert get_settings().self_serve_inr_per_min == Decimal("11.00")


async def test_a_row_changed_out_of_band_is_picked_up_when_the_cached_sentinel_expires() -> None:
    """THE WORST CASE, which is the one the <10s target has to survive: nobody published
    anything — an operator edited the row in psql, or the writing process died between
    COMMIT and publish. The Redis copy then carries the OLD version until its TTL runs
    out, after which the poll falls through to Postgres and finds the truth.

    Deleting the key stands in for that expiry so this test does not sleep for
    `_SENTINEL_TTL_S`; the real elapsed time was measured across two processes when this
    slice landed (a psql write reached a separate Python process in 4.9 seconds).

    What this pins is that Redis is a CACHE and never the truth: with it empty, the
    answer still arrives.
    """
    await pc.refresh(force=True)
    first = pc.snapshot()
    await _write_row(DEMO_KEY, '"11.00"')
    await get_redis().delete(pc._SENTINEL_KEY)

    second = await pc.refresh()
    assert second.version > first.version
    assert get_settings().self_serve_inr_per_min == Decimal("11.00")


async def test_an_unchanged_sentinel_does_not_rebuild() -> None:
    """The whole point of the sentinel: the common case costs one integer read. If this
    fails, every process is re-reading the config table on every poll."""
    await pc.refresh(force=True)
    first = pc.snapshot()
    again = await pc.refresh()
    assert again.loaded_at == first.loaded_at, "rebuilt without the version moving"


async def test_an_unreachable_store_keeps_serving_the_last_good_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6: "a store that is unreachable keeps serving the last good snapshot and alerts —
    a config lookup must never be able to take the phone system down"."""
    await _write_row(DEMO_KEY, '"12.00"')
    await pc.refresh(force=True)
    assert get_settings().self_serve_inr_per_min == Decimal("12.00")

    async def _explode() -> int:
        raise RuntimeError("postgres is gone")

    monkeypatch.setattr(pc, "_sentinel", _explode)
    snap = await pc.refresh(force=True)

    assert snap.degraded is True
    assert snap.loaded_at is not None, "this is 'stale', not 'never loaded'"
    # The values in force are unchanged — the phone system does not notice.
    assert get_settings().self_serve_inr_per_min == Decimal("12.00")


class _DeadRedis:
    """A Redis that is down in the only two ways this module can meet one.

    Not a `MagicMock`: what has to be exercised is the EXCEPTION escaping the client, and
    a mock that returns a sentinel would exercise the happy path with a strange value.
    """

    async def get(self, _key: str) -> str:
        raise ConnectionError("redis is gone")

    async def set(self, *_: object, **__: object) -> None:
        raise ConnectionError("redis is gone")


async def test_a_redis_outage_costs_a_postgres_read_and_changes_no_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REDIS IS A COST OPTIMISATION HERE, NEVER THE TRUTH.

    The sentinel lives in Redis so that the common case — nothing changed — costs a
    sub-millisecond GET instead of a database connection in four processes. That is the
    whole reason the key exists, and it is also the reason the ordering has to be
    asserted: if a Redis incident propagated out of `_sentinel`, `refresh` would catch it
    and mark the snapshot DEGRADED, so a cache outage would present to an operator as
    "the platform cannot read its configuration" and would freeze every process's config
    at whatever it last saw. With the fallback, a Redis outage is invisible to config
    propagation — the answer is identical, it just costs one small SELECT.

    Asserted against the DATABASE's own version rather than against "it did not raise",
    because a fallback that returned `_UNKNOWN_VERSION` would also not raise — and would
    make every process rebuild its snapshot on every poll.
    """
    await _write_row(DEMO_KEY, '"9.50"')
    expected = await pc._read_version()

    monkeypatch.setattr(pc, "get_redis", _DeadRedis)
    assert await pc._sentinel() == expected
    assert expected > 0, "the store has been written to, so the version cannot be 'nothing'"

    # And the refresh built on top of it is a NORMAL one, not a degraded one: the values
    # reach `get_settings()` with the cache still down.
    snap = await pc.refresh(force=True)
    assert snap.degraded is False
    assert get_settings().self_serve_inr_per_min == Decimal("9.50")


async def test_publishing_the_sentinel_is_best_effort_and_never_reaches_the_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CONFIG WRITE MUST NOT FAIL BECAUSE THE CACHE IS DOWN.

    `publish_version` runs after an operator's write has committed — from
    `config_service.propagate`, on a background task — and it is a SPEED-UP over the
    mechanism that actually guarantees delivery (the trigger's bump plus every process's
    own poll). If this raised, an operator whose change had already landed would see a
    failure for a value that is in force, and the background task would log an exception
    for a store that is doing its job.

    Two things are asserted, because "it did not raise" alone would also pass on a
    function that swallowed the error AND corrupted the shared cache: nothing raises, and
    the key in the real Redis is untouched by a publish that never happened — so the next
    reader falls through to Postgres rather than reading a half-written version.
    """
    await pc.refresh(force=True)
    before = await get_redis().get(pc._SENTINEL_KEY)

    monkeypatch.setattr(pc, "get_redis", _DeadRedis)
    await pc.publish_version(999_999)  # must not raise

    monkeypatch.undo()
    after = await get_redis().get(pc._SENTINEL_KEY)
    assert after == before, "a publish that could not happen must not leave a partial value"
    assert after != "999999"


async def test_a_recovered_store_clears_the_stale_flag_without_a_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RECOVERY IS AN EVENT THE CONSOLE HAS TO SEE.

    `stale` is what stops a snapshot from an hour ago rendering identically to a live one
    (§52). It is set the moment a refresh fails — and if nothing ever cleared it, a single
    transient blip would leave every console for that process reading "possibly stale"
    until it restarted, which trains an operator to ignore the one field that tells them
    their change has not propagated.

    The clearing happens on the CHEAP path, and that is the subtle part: after a recovery
    the version has usually NOT moved, so the refresh returns early without re-reading the
    table. This asserts both halves — the flag is cleared, and `loaded_at` is unchanged,
    proving the recovery cost one sentinel read rather than a full rebuild.
    """
    await _write_row(DEMO_KEY, '"9.50"')
    healthy = await pc.refresh(force=True)
    assert healthy.degraded is False

    async def _explode() -> int:
        raise RuntimeError("postgres is gone")

    monkeypatch.setattr(pc, "_sentinel", _explode)
    assert (await pc.refresh(force=True)).degraded is True

    monkeypatch.undo()
    # NOT `force=True`: this is the ordinary poll that follows a recovery, and the version
    # has not moved, so it takes the early-return path.
    recovered = await pc.refresh()
    assert recovered.degraded is False, "the console would say 'stale' forever after one blip"
    assert recovered.loaded_at == healthy.loaded_at, "it rebuilt the snapshot to clear a flag"
    assert recovered.version == healthy.version
    assert get_settings().self_serve_inr_per_min == Decimal("9.50")


async def test_starting_the_refresher_twice_leaves_exactly_one_poller() -> None:
    """IDEMPOTENT, because the adoption surface invites a second call.

    `start_config_refresher()` is documented as safe to call "from any lifespan, once or
    ten times" — and a lifespan really can run twice in one process (a test harness
    entering the context, an ASGI server reloading). Two live pollers would double every
    process's database reads for ever, and worse: two rebuilds racing means the OLDER of
    two reads can be installed last, which is a config that goes backwards with no error
    anywhere.

    Asserted on the task IDENTITY rather than on a count, because that is the fact the
    guard actually establishes: the second call adopted the running poller instead of
    replacing it.
    """
    await pc.stop_config_refresher()
    try:
        pc.start_config_refresher()
        first = pc._refresher
        assert first is not None and not first.done()

        pc.start_config_refresher()
        assert pc._refresher is first, "a second poller is now reading the store in parallel"
    finally:
        await pc.stop_config_refresher()
    assert pc._refresher is None


async def test_a_cold_start_with_no_store_serves_env_and_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE COLD-START DECISION, pinned. A process that has never reached the store runs
    on `os.environ` + code defaults rather than refusing to boot: that is the
    configuration every process ran on before this feature existed, the bootstrap set is
    env-only regardless, and making a phone system depend on a table that is empty on
    every deployment today would be inventing a single point of failure."""
    pc.reset_for_test()

    async def _explode() -> int:
        raise RuntimeError("postgres is gone")

    monkeypatch.setattr(pc, "_sentinel", _explode)
    snap = await pc.refresh(force=True)

    assert snap.loaded_at is None, "never loaded is a DIFFERENT state from stale"
    assert snap.degraded is True
    assert snap.overrides == {}
    # The code default, unchanged, and the process is serving.
    assert get_settings().self_serve_inr_per_min == Settings.model_fields[DEMO_KEY].get_default(
        call_default_factory=True
    )


async def test_the_read_path_does_no_io() -> None:
    """Hard rule 3's requirement, measured rather than asserted in prose: voice-runtime
    reads `get_settings()` inside a 500ms ack budget, and a config lookup that opened a
    connection would put a database round trip on the webhook path."""
    await pc.refresh(force=True)
    started = time.perf_counter()
    for _ in range(10_000):
        get_settings()
    elapsed_ms = (time.perf_counter() - started) * 1000
    # Ten thousand reads in well under a single millisecond of budget. A DB round trip
    # is ~1ms EACH, so this bound cannot be met by anything that touches the network.
    assert elapsed_ms < 50, f"10k get_settings() took {elapsed_ms:.1f}ms — is it doing IO?"


# --- adoption: which deployables actually poll --------------------------------


async def test_voice_runtime_adopts_console_config_when_it_boots() -> None:
    """The adoption is a ONE-LINE decision in `apps/voice-runtime/main.py`, and a
    deployable that does not make it runs on env + defaults forever without saying so.

    voice-runtime is the deployable where that matters most and where hard rule 3 makes
    it least obvious: the engine source-IP allowlist is the ENTIRE authenticity control
    for an unsigned engine, and the vendor can renumber without telling us. Before the
    refresher, that meant editing `.env` on the VPS and restarting the latency-critical
    service while every webhook 401'd. So "the console can change it without a deploy"
    is a recovery-time property of this service, not a convenience.

    Asserted through the REAL lifespan, from a process state that has never read the
    store, and against a VALUE rather than against a flag: the store's rupee figure has
    to be the one `get_settings()` answers with once the service is up. Checking only
    that a task exists would pass on a poller that reads nothing.
    """
    # A cold process — otherwise another suite's poll could satisfy this test.
    await pc.stop_config_refresher()
    pc.reset_for_test()
    assert pc.snapshot().loaded_at is None, "this test must start from a process that never read"

    await _write_row(DEMO_KEY, '"13.25"')
    # Uvicorn owns the process signals in production; the lifespan installs handlers for
    # them, and pytest is not a process this test may leave changed.
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        async with voice_app.router.lifespan_context(voice_app):
            # The refresher reads FIRST and sleeps afterwards, so this settles in one
            # scheduler turn on a healthy box; the bounded loop is only so a sick one
            # fails with this test's message instead of hanging. A `for` rather than a
            # `while` because ruff's ASYNC110 is right in general — there is no event to
            # await here, the poller publishes nothing but its snapshot.
            for _ in range(250):
                if pc.snapshot().loaded_at is not None:
                    break
                await asyncio.sleep(0.02)
            snapshot = pc.snapshot()
            in_force = get_settings().self_serve_inr_per_min
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)
        await pc.stop_config_refresher()

    assert snapshot.loaded_at is not None, (
        "voice-runtime booted without ever reading the store — an allowlist rotation "
        "would now need a redeploy of the latency-critical service"
    )
    assert snapshot.degraded is False
    # Hard rule 7: the exact rupee figure, as a Decimal, not a float that happens to
    # compare equal.
    assert in_force == Decimal("13.25")
    assert str(in_force) == "13.25"
