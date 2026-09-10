"""`/healthz/ready` must not construct an engine adapter on the service carrying calls.

THE DEFECT. `core/health.ready` read `runtime_config_missing_keys(get_settings())`, whose
body ends at `apps.api.engine.build_engine(cfg)` — so answering a readiness poll imported
the vendor adapter and `httpx` into whichever process served it.
`tests/voice_runtime_import_surface_test.FORBIDDEN` names both ("vendor adapters — hard
rule 2", "HTTP client — the receiver makes no outbound call"), and
`infra/nginx/calevate.conf.template` records the measurement that makes it more than a
rule violation: 381-435ms on a first call, 76-87% of hard rule 3's whole 500ms ack budget,
paid on the one event loop that has live calls on it.

THE EDGE IS NOT THE FIX, and the template says so itself. `location ^~ /healthz { return
404; }` closes the PUBLIC path on `hooks.`; the route is still served on the loopback
interface, which is where `runbooks/` send an operator during an incident — i.e. exactly
while calls are in progress. So the app-side half is a per-service probe
(`settings.READINESS_CONFIG_PROBES`) that constructs nothing.

WHY A SUBPROCESS, and it is the same argument the import-surface file makes: this pytest
process has already imported the entire monolith, every adapter and `httpx`, so a
`sys.modules` assertion made here would be vacuously true. A fresh interpreter that boots
the app the way uvicorn does, serves one `/healthz/ready`, and reports what it then holds
is the only honest instrument.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
from apps.api.core.settings import (
    READINESS_CONFIG_PROBES,
    Settings,
    runtime_config_missing_keys,
    webhook_receiver_missing_keys,
)
from calevate_shared.config import bolna_source_ips

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The two prefixes this probe exists to keep out, quoted from the import-surface file's
#: FORBIDDEN table rather than invented here — a third spelling of that ban is the drift
#: this repo treats as a defect even when both copies agree.
BANNED_ON_THE_READINESS_PATH = {
    "apps.api.engine": "vendor adapters — hard rule 2",
    "httpx": "HTTP client — the receiver makes no outbound call",
}

_READY_PROBE = """
import asyncio, json, sys
sys.path.insert(0, "apps/voice-runtime")
sys.path.insert(1, ".")
import main  # noqa: F401  — boot exactly as the ASGI server does
from httpx import ASGITransport, AsyncClient  # noqa: E402  — the DRIVER, see below

# `httpx` is the test client, so it is in this process by construction and cannot be
# measured as an acquisition. The delta below is taken AFTER it is imported, which is what
# makes the measurement honest: anything the request pulls in is new, and `httpx` arriving
# through the app would show up as `httpx.<submodule>` or, more to the point, as
# `apps.api.engine.bolna` — which imports it and is measured directly.
async def main_():
    before = sorted(sys.modules)
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://runtime") as http:
        response = await http.get("/healthz/ready")
    after = sorted(sys.modules)
    return {"status": response.status_code, "before": before, "after": after}

result = asyncio.run(main_())
with open(sys.argv[1], "w") as handle:
    json.dump(result, handle)
"""


@pytest.fixture(scope="module")
def readiness_probe() -> dict[str, object]:
    """Serve one `/healthz/ready` in a fresh voice-runtime process; report `sys.modules`.

    `APP_ENV=local` because that is the shape every other subprocess probe in this repo
    uses and the one a developer's box can satisfy. It does NOT weaken the measurement:
    the config probe runs on every branch, and the import being asserted about happens
    inside `runtime_config_missing_keys` before any environment check.

    `ENGINE=bolna` IS load-bearing, and leaving it to the ambient environment made this
    weaker than it looks: `build_engine` branches on the name, so on the default `fake`
    the revert-proof shows `apps.api.engine.fake` and NO `httpx` — the vendor adapter that
    actually costs 381-435ms is never reached. Pinning the engine every deployment runs
    measures the production shape.
    """
    out = Path(tempfile.gettempdir()) / f"calevate-readiness-surface-{uuid.uuid4().hex}.json"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _READY_PROBE, str(out)],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONPATH": "", "APP_ENV": "local", "ENGINE": "bolna"},
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert proc.returncode == 0, f"the readiness probe failed:\n{proc.stderr[-3000:]}"
        return dict(json.loads(out.read_text(encoding="utf-8")))
    finally:
        out.unlink(missing_ok=True)


def test_serving_readiness_does_not_pull_the_vendor_adapter_into_voice_runtime(
    readiness_probe: dict[str, object],
) -> None:
    """The measurement, and the one that goes red if the probe is wired back."""
    before = set(readiness_probe["before"])  # type: ignore[arg-type]
    after = set(readiness_probe["after"])  # type: ignore[arg-type]
    acquired = after - before
    banned = sorted(
        f"{module} ({reason})"
        for module in acquired
        for prefix, reason in BANNED_ON_THE_READINESS_PATH.items()
        if module == prefix or module.startswith(f"{prefix}.")
    )
    assert not banned, (
        "answering /healthz/ready pulled forbidden modules into voice-runtime:\n"
        + "\n".join(f"  - {entry}" for entry in banned)
        + "\nMeasured at 381-435ms on a first call (infra/nginx/calevate.conf.template), "
        "against a 500ms ack budget, on the event loop carrying live calls. The route is "
        "404'd at the edge but still served on loopback, which is where a runbook sends "
        "an operator mid-incident."
    )


def test_the_probe_actually_served_the_route(readiness_probe: dict[str, object]) -> None:
    """A negative control. A 404 — a route that moved, an app that did not mount it —
    would make the assertion above pass by measuring nothing at all."""
    assert readiness_probe["status"] in {200, 503}, (
        f"/healthz/ready answered {readiness_probe['status']}; the import measurement "
        "above is only evidence if the handler actually ran"
    )


def _prod(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "prod",
        "database_url": "postgresql+psycopg://u:p@localhost/db",
        "redis_url": "redis://localhost:6379/0",
        "engine": "bolna",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


def test_voice_runtime_is_the_service_that_opts_out_and_the_default_is_the_strict_probe() -> None:
    """The table, asserted rather than assumed: an unknown service gets the FULL check.

    That direction matters. An over-strict readiness probe is a red light somebody
    investigates; an under-strict one is a green light on a deployment that cannot serve,
    which is the D-104 defect (`/healthz/ready` GREEN on a credential-less engine).
    """
    assert {"voice-runtime": webhook_receiver_missing_keys} == READINESS_CONFIG_PROBES


def test_the_receiver_probe_reports_the_key_it_cannot_serve_without() -> None:
    """Readiness for a service that is CALLED BY the vendor rather than calling it.

    `PLATFORM_KEK` is what it comes down to: the console-managed configuration this
    service opts into is encrypted under it, and that configuration carries the selected
    engine and the source-IP allowlist which — Bolna signing nothing (D-31, TRD §5) — is
    the entire authenticity control. Without the KEK the rows are unreadable and the
    process runs on whatever the environment last gave it.

    THE ALLOWLIST IS NOT A SECOND ASSERTION HERE, and the reason is pinned below rather
    than left to the docstring: `parse_source_ip_allowlist` fails safe to
    `DEFAULT_BOLNA_SOURCE_IPS`, so it cannot resolve empty and a readiness branch for that
    state would be unreachable. If that ever changes, this fails and the probe gains a
    check.
    """
    assert webhook_receiver_missing_keys(_prod(platform_kek="k" * 44)) == []
    assert webhook_receiver_missing_keys(_prod()) == ["PLATFORM_KEK"]
    assert bolna_source_ips(_prod(bolna_webhook_source_ips="")), (
        "the allowlist resolver now returns an empty set for a blank configuration — it "
        "used to fail safe to the built-in default, which is why "
        "`webhook_receiver_missing_keys` reports nothing about it. Readiness for the "
        "receiver should now name BOLNA_WEBHOOK_SOURCE_IPS."
    )


def test_the_receiver_probe_does_not_demand_another_deployables_credentials() -> None:
    """The api's full probe names keys this service can neither use nor fix — the vendor
    API key it never calls, the extraction key that lives in a worker, the object-store
    credentials the recording copier uses. A probe red for a fault the process cannot have
    is the probe operators learn to ignore, which is what `runtime_config_missing_keys`'
    own comments decline to become."""
    settings = _prod()
    full = set(runtime_config_missing_keys(settings))
    receiver = set(webhook_receiver_missing_keys(settings))
    assert "BOLNA_API_KEY" in full, (
        "the full probe no longer names the engine credential — this comparison has "
        "stopped measuring the difference it exists to measure"
    )
    assert receiver < full, (
        f"the receiver probe reports {sorted(receiver - full)}, which the full probe does "
        "not — the two have diverged in the wrong direction"
    )
    assert "BOLNA_API_KEY" not in receiver
