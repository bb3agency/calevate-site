"""`make redis-reset` — the OTHER empty store the coverage ratchet requires.

WHY THIS EXISTS AT ALL, given that `redis-cli flushdb` is one line. Because that one
line is not the whole reset, and the gap has already cost this repo a red CI-shaped
failure. `FLUSHDB` empties the LIVE dataset; it does not touch `dump.rdb`. A redis
started from the repo root loads `dump.rdb` out of its working directory at boot, so the
sequence "flush, restart redis, run the gate" hands the suite back every key the flush
removed — and `check_coverage_ratchet`'s pre-suite probe then REFUSES TO SCORE a run
that looks contaminated, naming a cause the developer believes they already fixed.
That is the exact loop this script closes, and CLAUDE.md hard rule 10 documents the
symptom without having had a cure.

WHY `SAVE` RATHER THAN DELETING THE FILE, which is the obvious alternative. Unlinking
`dump.rdb` needs to know where it is (`CONFIG GET dir` + `dbfilename`), needs the file to
be on THIS filesystem, and leaves redis's own view of its persistence inconsistent with
the disk. `SAVE` after the flush asks redis to rewrite the snapshot from the dataset it
now has, which reaches the same end state through redis's own API: no path assumptions,
no filesystem access, correct for a remote server, and — the part that matters — it
persists the OTHER databases untouched rather than destroying a snapshot they share.
`SAVE` is explicit and is not governed by the `save` config, so it still works on a
server started with `--save ''`.

WHAT IT DOES NOT DO. It flushes ONE database — the one `REDIS_URL` names, which is the
one the suite and `check_coverage_ratchet`'s `dbsize()` probe both read. `FLUSHALL` was
rejected: a developer's other db indexes are not this gate's business, and a reset that
destroys more than it was asked to is one people stop running.

THE GUARD is `db_reset.py`'s, deliberately identical and for the identical reason: two
independent facts rather than one. `APP_ENV` must be `local` AND the DSN's host must be
a loopback name, because a copied `.env` keeps `APP_ENV=local` while pointing elsewhere,
and a tunnel makes a remote server look like `localhost`. There is no `--force`.
"""

from __future__ import annotations

import sys
from typing import cast
from urllib.parse import urlsplit

import redis
from apps.api.core.settings import effective_env

from scripts.db_reset import LOOPBACK_HOSTS


def _redis_url() -> str:
    url = effective_env().get("REDIS_URL")
    if not url:
        raise SystemExit(
            "REDIS_URL is not set. Copy .env.example to .env — this script resets the "
            "store the suite and the coverage ratchet both read."
        )
    return url


def _refuse_unless_local(url: str) -> None:
    app_env = effective_env().get("APP_ENV", "")
    host = urlsplit(url).hostname or ""
    if app_env != "local":
        raise SystemExit(
            f"redis-reset refuses: APP_ENV is {app_env!r}, not 'local'. This deletes every "
            "key in the target database. If this really is a development store, say so by "
            "setting APP_ENV=local."
        )
    if host not in LOOPBACK_HOSTS:
        raise SystemExit(
            f"redis-reset refuses: REDIS_URL points at host {host!r}, which is not loopback. "
            "APP_ENV says local and the DSN does not, and the two disagreeing is exactly "
            "the state this guard exists for."
        )


def reset_redis() -> None:
    url = _redis_url()
    _refuse_unless_local(url)

    client = redis.Redis.from_url(url, socket_connect_timeout=2.0, socket_timeout=5.0)
    try:
        # `cast` rather than a bare `int(...)`: redis-py's `Redis` class serves both the
        # sync and the async client, so `dbsize()` is typed as possibly-awaitable. Same
        # idiom as `check_coverage_ratchet._probe_redis`, which reads the same value.
        before = int(cast(int, client.dbsize()))
        client.flushdb()
        # The half `flushdb` alone leaves undone — see the module docstring. Without it a
        # restart re-reads the pre-flush snapshot and the gate refuses to score.
        client.save()
        after = int(cast(int, client.dbsize()))
    finally:
        client.close()

    if after:
        raise SystemExit(
            f"redis-reset: {after} keys remain after FLUSHDB — something is writing to "
            "this database while the reset runs (a worker, or another suite). Stop it and "
            "run this again; a store that refills itself is not a store the gate can score."
        )
    db = urlsplit(url).path.lstrip("/") or "0"
    print(f"redis-reset: db {db} emptied ({before} keys) and the snapshot rewritten")


if __name__ == "__main__":  # pragma: no cover - entrypoint
    reset_redis()
    sys.exit(0)
