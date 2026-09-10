"""Calevate voice-runtime — engine webhooks + in-call tool endpoints.

Run: uv run uvicorn main:app --reload --port 8100 --app-dir apps/voice-runtime
(the directory is hyphenated by decision D-18, so it is not importable as a module
path — `--app-dir` is how it gets on sys.path.)

LATENCY-CRITICAL (root CLAUDE.md hard rule 3). Handlers must:
  - verify authenticity per engine before anything else,
  - ack in under 500ms,
  - defer all real work to ARQ,
  - do no heavy imports, no synchronous LLM calls, and no DB writes beyond the
    minimal event row.

This service is never redeployed casually — a dashboard deploy must not touch live
calls, so its deploy is never coupled to `api`. It DOES reuse `apps/api/core` as a
library (bootstrap order, problem+json, logging, queue): shared library code is not
deploy coupling, and re-implementing the error shape here would guarantee drift. The
import surface is asserted by `tests/voice_runtime_import_surface_test.py`, which is
what actually keeps the latency promise honest — it boots this module in a fresh
interpreter and reads the resulting `sys.modules`, because `make guardrails`' import
linter CANNOT see this service: grimp walks `apps` as a package tree and D-18's
hyphenated directory name is not a legal module name, so every voice-runtime module is
invisible to it.
"""

from collections.abc import AsyncIterator
from contextlib import suppress

from apps.api.core.bootstrap import create_app
from apps.api.core.errors import install_error_handlers
from apps.api.core.platform_config import start_config_refresher, stop_config_refresher
from fastapi import FastAPI
from tool_routes import router as tool_router
from webhook_routes import router as webhook_router


async def _startup() -> AsyncIterator[None]:
    """Adopt console-managed configuration (PLATFORM-CONFIG §6), deliberately.

    THIS SERVICE HAD TO DECIDE FOR ITSELF, which is why `apps/api/main.py` starts the
    same poller in its own file rather than inside the shared `create_app`: putting a
    background task into every service by default would answer hard rule 3's question —
    what may run beside the webhook path — in a file this service's owner does not read.

    The reason to say yes here is that the values that matter most to this service are
    exactly the ones an operator needs to change without a deploy: the engine source-IP
    allowlist, which is the ENTIRE authenticity control for an unsigned engine and which
    the vendor can renumber without telling us, and the selected engine itself. Before
    this, a stale allowlist meant every webhook 401'd until someone edited `.env` on the
    VPS and restarted the latency-critical service.

    The cost is bounded and is not on the request path: one Redis GET of a single integer
    every 3s in a background task, and a Postgres read only when that integer moves. The
    handler still resolves settings from an in-memory snapshot with zero IO, which is
    what hard rule 3 actually constrains. `tests/voice_runtime_import_surface_test.py` is
    the check that keeps this honest — it boots this module in a fresh interpreter and
    reads `sys.modules`, so an import that drags in something heavy fails there.

    **CONFIG ONLY, AND THE KEYWORD IS THE WHOLE POINT.** `with_secrets=False` stops the
    poll reading `platform_secrets`. With it on — which is what this line used to be — the
    refresh imported `apps.api.ops.secret_service` (a prefix this service's own FORBIDDEN
    list bans), SELECTed every stored credential and AES-GCM-unsealed all of them into
    THIS process's `Settings`, three seconds after boot. `compose.prod.yml` gives all
    three services the same `env_file`, so `PLATFORM_KEK` is here and the unseal
    succeeded: the service whose guard says "the engine holds our keys, not this service"
    held decrypted copies of the lot. It needs none of them — the only settings read on
    this path are the engine source-IP allowlist, the selected engine and `app_env`, all
    plain configuration — and the import hid from the boot graph because `_read_secrets`
    imports lazily, which is why the guard was green while the door stood open.
    `tests/voice_runtime_import_surface_test.py` §5 now measures the poll task itself.
    """
    start_config_refresher(with_secrets=False)
    try:
        yield
    finally:
        # The other half of the adoption, which had no other half: `create_app` used to
        # consume this hook to its first `yield` and abandon it, so the poll outlived
        # every drain. On an ordinary deploy that is a task reading through a session pool
        # being torn down under it — an error that reads exactly like a live incident on
        # the one service where a live incident means dropped calls.
        with suppress(Exception):
            await stop_config_refresher()


app: FastAPI = create_app(
    service="voice-runtime",
    title="Calevate voice-runtime",
    version="0.1.0",
    on_startup=_startup,
    # No CORS, no rate limiter, no load-shed middleware: no browser calls this service,
    # and an engine callback must ALWAYS land (BACKEND-PATTERNS §6 lists engine
    # webhooks among the never-shed prefixes).
    minimal=True,
)
install_error_handlers(app)
app.include_router(webhook_router)
# In-call tools (SEC-COMP §2.3's opt-out). Mounted here rather than in `apps/api`
# because it is on the caller's audio path: the engine invokes it mid-call and the
# 500ms discipline above applies to it exactly as it does to the webhook receiver.
app.include_router(tool_router)
