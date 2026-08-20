"""`make redis-reset` empties the store AND its snapshot — the half a flush leaves behind.

THE DEFECT, AND WHY A COMMENT WAS NOT ENOUGH. CLAUDE.md hard rule 10 has always said to
start the coverage ratchet from an empty Redis, and the recipe it printed was
`redis-cli -n <db> flushdb`. That empties the LIVE dataset and leaves `dump.rdb` on disk
holding every key it just removed. `redis-server` loads that file from its working
directory at boot, so the moment anything restarts Redis — a container bounce, a
developer's `redis-server` in the repo root — the keys come back and
`check_coverage_ratchet` REFUSES TO SCORE, naming a contamination the developer believes
they already cleared. It cost that twice in one session before the cause was found.

WHAT IS TESTED HERE, mirroring `db_reset_test`'s split for the same reason. The
destructive path is NOT driven: a test that flushes the database out from under four
concurrently running suites is a worse defect than the one it guards. What IS driven is
the GUARD — the part with a decision in it — plus the shape of the recipe, because a
script nothing invokes is the half-wired change this repo names by name, and because the
whole point of this file is that the RECIPE was the thing that was wrong.

`_hermetic_env` is `db_reset_test`'s, and for its exact reason: `redis_reset` reads `.env`
through `core.settings.effective_env`, so `monkeypatch.delenv` neutralises nothing and a
refusal test that relied on it would flush the developer's store instead of asserting a
refusal. Autouse and empty by default, so a test that forgets to declare a URL gets a
refusal — the safe direction.
"""

from __future__ import annotations

import pathlib

import pytest
from scripts import redis_reset
from scripts.redis_reset import reset_redis

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    declared: dict[str, str] = {}
    monkeypatch.setattr(redis_reset, "effective_env", lambda: declared)
    return declared


def test_it_refuses_outside_a_local_environment(_hermetic_env: dict[str, str]) -> None:
    _hermetic_env["APP_ENV"] = "prod"
    _hermetic_env["REDIS_URL"] = "redis://localhost:6380/0"
    with pytest.raises(SystemExit) as refused:
        reset_redis()
    assert "APP_ENV" in str(refused.value)


def test_it_refuses_a_url_that_is_not_loopback(_hermetic_env: dict[str, str]) -> None:
    """The second, independent fact. A tunnel makes a remote server look like localhost
    and a copied `.env` keeps `APP_ENV=local`; either alone is one mistake away from
    flushing a real store, so the guard needs both to agree."""
    _hermetic_env["APP_ENV"] = "local"
    _hermetic_env["REDIS_URL"] = "redis://cache.example.com:6379/0"
    with pytest.raises(SystemExit) as refused:
        reset_redis()
    assert "loopback" in str(refused.value)


def test_it_refuses_without_a_url(_hermetic_env: dict[str, str]) -> None:
    _hermetic_env["APP_ENV"] = "local"
    with pytest.raises(SystemExit) as refused:
        reset_redis()
    assert "REDIS_URL" in str(refused.value)


class _FakeRedis:
    """Enough of redis-py to record the ORDER of the calls, which is the whole claim."""

    def __init__(self, *, keys: int, keys_after: int | None = None) -> None:
        self._keys = keys
        self._after = keys if keys_after is None else keys_after
        self.calls: list[str] = []

    def dbsize(self) -> int:
        self.calls.append("dbsize")
        return self._keys if "flushdb" not in self.calls else self._after

    def flushdb(self) -> None:
        self.calls.append("flushdb")

    def save(self) -> None:
        self.calls.append("save")

    def close(self) -> None:
        self.calls.append("close")


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeRedis) -> None:
    monkeypatch.setattr(redis_reset.redis.Redis, "from_url", staticmethod(lambda *a, **k: fake))


def test_the_snapshot_is_rewritten_after_the_flush_and_not_before(
    _hermetic_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one behaviour that distinguishes this from `redis-cli flushdb`.

    ORDER IS THE ASSERTION, not merely that both happened: a `SAVE` before the flush
    writes the CONTAMINATED dataset to disk and makes the problem permanent instead of
    fixing it. Reversing the two lines in `reset_redis` must fail this test.
    """
    _hermetic_env["APP_ENV"] = "local"
    _hermetic_env["REDIS_URL"] = "redis://localhost:6380/0"
    fake = _FakeRedis(keys=25, keys_after=0)
    _install(monkeypatch, fake)

    reset_redis()

    assert "flushdb" in fake.calls and "save" in fake.calls, (
        "a reset that does not SAVE leaves `dump.rdb` holding the keys it just deleted — "
        "which is exactly `redis-cli flushdb`, the thing this script exists to replace"
    )
    assert fake.calls.index("flushdb") < fake.calls.index("save"), (
        "SAVE ran BEFORE FLUSHDB: that persists the contaminated dataset to disk, so the "
        "next restart restores it and the reset has made things strictly worse"
    )


def test_a_store_that_refills_itself_is_reported_rather_than_declared_clean(
    _hermetic_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker still running writes keys back between the flush and the check. Printing
    "emptied" there is the false green the ratchet's whole provenance machinery exists to
    prevent, so it exits instead."""
    _hermetic_env["APP_ENV"] = "local"
    _hermetic_env["REDIS_URL"] = "redis://127.0.0.1:6380/0"
    _install(monkeypatch, _FakeRedis(keys=25, keys_after=3))
    with pytest.raises(SystemExit) as refused:
        reset_redis()
    assert "3 keys remain" in str(refused.value)


def test_the_ratchet_recipe_no_longer_tells_anyone_to_flush_by_hand() -> None:
    """The seam, asserted where it is wired. `scripts/redis_reset.py` existing is worth
    nothing while the three places that TELL a developer what to run still print the
    incomplete recipe — which is how the original defect survived being documented."""
    makefile = (REPO / "Makefile").read_text()
    assert "\nredis-reset:" in makefile, "the redis-reset target is gone"
    assert "scripts.redis_reset" in makefile, "redis-reset no longer calls the reset script"

    for name, path in (
        ("CLAUDE.md hard rule 10", REPO / "CLAUDE.md"),
        ("the ratchet's own remedy", REPO / "scripts" / "check_coverage_ratchet.py"),
    ):
        text = path.read_text()
        assert "make redis-reset" in text, f"{name} does not name the reset that works"
        # PROSE about FLUSHDB is the point — both files now explain at length why it is
        # not sufficient. What must not survive is the runnable INVOCATION, which is what
        # a hurried reader copies: a line carrying both `redis-cli` and `flushdb` is a
        # command, not an explanation, and it may only appear while being contradicted.
        for line in text.splitlines():
            lowered = line.lower()
            if "redis-cli" in lowered and "flushdb" in lowered:
                assert "not" in lowered, (
                    f"{name} still prints a runnable bare flushdb as the remedy: "
                    f"{line.strip()!r}. It leaves `dump.rdb` holding the keys."
                )
