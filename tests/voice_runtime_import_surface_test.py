"""What voice-runtime is allowed to have in memory. Hard rule 3's "no heavy imports".

`apps/voice-runtime/main.py` has always claimed "the import surface is asserted by
`import_surface_test.py`, which is what actually keeps the latency promise honest".
That file did not exist. Neither did any other check covering it: `make guardrails`
runs `lint-imports`, whose `root_packages = ["apps"]` is walked by grimp as a PACKAGE
tree — and `apps/voice-runtime` is hyphenated by D-18, so it is not a legal module name
and grimp never sees it. Confirmed rather than assumed:

    >>> import grimp; g = grimp.build_graph("apps")
    >>> [m for m in g.modules if "webhook_routes" in m or "engine_intake" in m]
    []

109 modules in the graph, none of them this service. The comment in pyproject.toml's
engine-isolation contract — "the voice-runtime twin is its own tiny module ... and never
imports an adapter either" — was therefore a statement of intent with nothing behind it.
This file is the thing behind it.

WHY THE IMPORT SURFACE AND NOT A TIMER. The ack budget is 500ms and Bolna's delivery is
at-most-once with no retry (D-31), so a slow receiver does not get retried — it loses
calls. But a wall-clock assertion on a CI box is flaky, and flaky latency assertions get
deleted. What is NOT flaky is the set of modules the process holds: an LLM SDK, an
engine adapter or the ORM model registry cannot appear in it by accident, and each one
arrives with a matching pile of work someone intended to do on this path. Catching the
import catches the intent before the millisecond.

Measured as the REAL import graph — a fresh interpreter that imports the app exactly as
`uvicorn --app-dir apps/voice-runtime` does, then reports `sys.modules`. Not a grep:
a grep sees `from apps.api.reliability.service import body_hash` and stops, where the
truth is whatever that pulls behind it, three levels down. A subprocess is also the only
honest way to ask the question from inside pytest, whose own process has already
imported the entire monolith, every adapter and half of PyPI.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import webhook_routes
from apps.api.core.errors import ProblemError
from httpx import ASGITransport, AsyncClient
from main import app as voice_app

REPO_ROOT = Path(__file__).resolve().parents[1]

ENGINE_EGRESS_IP = "198.51.100.7"
EDGE_PROXY_IP = "127.0.0.1"
HOOK = "/hooks/v1/engine/bolna"
TOOL = "/tools/v1/bolna/opt-out"
BOOK = "/tools/v1/bolna/callback"
CANCEL_CALLBACK = "/tools/v1/bolna/callback/cancel"
HANDOFF = "/tools/v1/bolna/handoff"

#: A date the booking endpoint will accept as "far enough ahead", computed rather than
#: written down: a literal would silently start failing `too_soon` the day it passed, and
#: the branch this drive exists to reach would go unmeasured with nothing going red.
_SOON = (datetime.now(UTC) + timedelta(days=3)).strftime("%Y-%m-%d")

# --- the boot graph ----------------------------------------------------------

# Reproduces `uvicorn main:app --app-dir apps/voice-runtime` from the repo root: the
# service directory first (D-18 — hyphenated, so `main` is only importable this way),
# the repo root behind it for `apps.api.core` and friends.
_PROBE = """
import json, sys
sys.path.insert(0, "apps/voice-runtime")
sys.path.insert(1, ".")
import main  # noqa: F401  — the app object, exactly as the ASGI server builds it
# Not stdout: creating the app configures logging and writes its own lines there.
with open(sys.argv[1], "w") as handle:
    json.dump(sorted(sys.modules), handle)
"""


def _boot_modules() -> frozenset[str]:
    """Every module a freshly booted voice-runtime process holds."""
    out = Path(tempfile.gettempdir()) / f"calevate-import-surface-{uuid.uuid4().hex}.json"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE, str(out)],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONPATH": ""},
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert proc.returncode == 0, f"voice-runtime failed to boot:\n{proc.stderr[-3000:]}"
        return frozenset(json.loads(out.read_text(encoding="utf-8")))
    finally:
        out.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def boot_modules() -> frozenset[str]:
    return _boot_modules()


# --- 1. the things that must never be in memory ------------------------------

# Each entry is a prefix (the module itself or anything under it) plus the reason it is
# banned, so a failure explains itself without a code archaeology session.
FORBIDDEN: dict[str, str] = {
    # Hard rule 2: only `apps/api/engine/` and its voice-runtime twin
    # (`engine_intake.py`) may see vendor payload shapes. The factory imports both
    # adapters, so importing the package at all drags the vendor SDK surface in.
    "apps.api.engine": "vendor adapters — hard rule 2; the twin is engine_intake.py",
    # The post-call pipeline is the work this endpoint exists to DEFER. Importing it
    # here is one refactor away from calling it here.
    "apps.workers": "worker code — hard rule 3 defers all real work to ARQ",
    # Business modules: each pulls its ORM models, its services and its own
    # dependencies. The receiver resolves no tenant, prices nothing and extracts
    # nothing; it needs none of them.
    "apps.api.agents": "business module — the receiver resolves no agent",
    "apps.api.billing": "business module — metering happens in the worker (hard rule 7)",
    "apps.api.campaigns": "business module",
    "apps.api.compliance": "business module — the compliance gate is on the launch path",
    "apps.api.crm": "business module — extraction is post-call",
    "apps.api.ingest": "business module",
    "apps.api.integrations": "business module",
    "apps.api.kb": "business module — in-call retrieval is the engine's built-in KB (D-33)",
    "apps.api.tenancy": "business module — the receiver never resolves a tenant",
    "apps.api.admin": "business module",
    "apps.api.ops": "business module",
    # The declarative model registry. `db.session` gives this service everything it
    # needs; `db.registry` imports every model module in the repo, which is both the
    # heaviest import available and a deploy coupling to `api` (hard rule 3's last
    # clause) — a model added for a dashboard feature would change this service's boot.
    "apps.api.db.registry": "the whole ORM model registry — deploy coupling to api",
    # Model providers. CLAUDE.md: never call one from a request handler. The SDK not
    # being importable is the version of that rule a refactor cannot talk its way past.
    "openai": "LLM SDK — no synchronous model calls on the ack path",
    "anthropic": "LLM SDK",
    "google": "Google SDK namespace (genai/cloud) — LLM fallback belongs in workers",
    "sarvam": "STT/LLM/TTS SDK (D-36) — the engine holds our keys, not this service",
    "cohere": "embeddings SDK",
    "litellm": "LLM router",
    "langchain": "LLM framework",
    "langfuse": "LLM tracing — the redaction hook runs in workers",
    "tiktoken": "tokenizer",
    "transformers": "model runtime",
    "torch": "model runtime",
    "sentence_transformers": "model runtime",
    # Numerics. Nothing on this path does arithmetic beyond a millisecond subtraction.
    "numpy": "numerics — import cost with no caller here",
    "pandas": "dataframes",
    "scipy": "numerics",
    "sklearn": "numerics",
    # Outbound I/O. The receiver reads one body and writes two rows; it fetches
    # NOTHING. The authenticated Get Execution — the fetch that is the truth (D-31) —
    # is the worker's job.
    "httpx": "HTTP client — the receiver makes no outbound call",
    "aiohttp": "HTTP client",
    "requests": "HTTP client",
    "boto3": "object storage — recordings are copied by the worker",
    "botocore": "object storage",
}


def test_the_receiver_boots_without_a_single_forbidden_import(
    boot_modules: frozenset[str],
) -> None:
    """The one that would have to be deleted before an LLM call, a vendor adapter or
    the ORM model registry could reach the ack path."""
    found = {
        prefix: reason
        for prefix, reason in FORBIDDEN.items()
        if any(m == prefix or m.startswith(f"{prefix}.") for m in boot_modules)
    }
    assert not found, "voice-runtime imported modules it is not allowed to hold:\n" + "\n".join(
        f"  - {prefix}: {reason}" for prefix, reason in sorted(found.items())
    )


# --- 2. the surface is pinned, not merely un-forbidden -----------------------

# A blocklist only catches what someone thought of. These two allowlists catch the
# rest: anything new has to be added HERE, by a person, with this docstring in front of
# them. Subset assertions, not equality — dropping a dependency must not fail a build.

ALLOWED_APPS_MODULES: frozenset[str] = frozenset(
    {
        "apps",
        "apps.api",
        # `core` is the shared library main.py's docstring defends reusing: bootstrap
        # order, problem+json, structured logging, the ARQ pool, the Redis client. A
        # library, not a deploy coupling — but the list is pinned so "library" cannot
        # quietly grow into "the monolith".
        "apps.api.core",
        "apps.api.core.alerting",
        "apps.api.core.bootstrap",
        "apps.api.core.context",
        "apps.api.core.errors",
        "apps.api.core.health",
        "apps.api.core.loadshed",
        "apps.api.core.logging",
        "apps.api.core.middleware",
        "apps.api.core.observability",
        # Console-managed configuration (PLATFORM-CONFIG §6, D-95). Added DELIBERATELY,
        # and this test is why the addition had to be argued rather than noticed: it
        # failed the moment `main.py` imported it, which is the guardrail working.
        #
        # It qualifies as library code on the same terms as `settings` beside it — it
        # resolves configuration and owns no product behaviour. What it buys this service
        # specifically is the ability to change the engine source-IP allowlist without a
        # deploy. That allowlist is the ENTIRE authenticity control for an unsigned
        # engine and the vendor can renumber it without telling us; before this, a stale
        # one meant every webhook 401'd until somebody edited `.env` on the VPS and
        # restarted the latency-critical service.
        #
        # The cost is a background Redis GET of one integer every 3s. Nothing moves onto
        # the request path: handlers still read an in-memory snapshot with zero IO, which
        # is what hard rule 3 constrains. The companion test above — "boots without a
        # single forbidden import" — is what proves this module drags nothing heavy in.
        "apps.api.core.platform_config",
        "apps.api.core.queue",
        # Reached ONLY through `core.middleware`, which is already on this list and which
        # `core.bootstrap` imports at module scope — so this arrives with `create_app`
        # rather than by anything this service does with it. `create_app(minimal=True)`
        # (what `main.py` calls) never installs `RateLimitMiddleware`: the receiver's
        # limits are nginx's `webhooks` zone, and hard rule 3 would not tolerate a Redis
        # round trip inside the 500ms ack anyway.
        #
        # It qualifies as library code on the same terms as `errors` and `logging`: a
        # profile table, a regex matcher and one INCR. Its whole import list is stdlib
        # plus `core.errors`, `core.logging` and `core.redis`, all already held — which
        # is what the "boots without a single forbidden import" test above proves rather
        # than asserts by hand.
        "apps.api.core.ratelimit",
        "apps.api.core.redis",
        "apps.api.core.settings",
        # Sessions and uuid7 only. NOT `db.registry` — see FORBIDDEN.
        "apps.api.db",
        "apps.api.db.base",
        "apps.api.db.result",
        "apps.api.db.session",
        # The inbox claim: the dedupe that carries the guarantee (BACKEND-PATTERNS §4).
        "apps.api.reliability",
        "apps.api.reliability.service",
    }
)


def test_the_apps_surface_this_service_holds_is_the_pinned_one(
    boot_modules: frozenset[str],
) -> None:
    """`main.py` argues that reusing `apps/api/core` as a LIBRARY is not deploy coupling
    (hard rule 3's "never couple its deploy to api changes"). That argument holds only
    while the borrowed surface stays small and boring. This is the assertion that keeps
    it small and boring."""
    held = {m for m in boot_modules if m == "apps" or m.startswith("apps.")}
    unexpected = sorted(held - ALLOWED_APPS_MODULES)
    assert not unexpected, (
        "voice-runtime's borrowed surface from `apps` grew:\n"
        + "\n".join(f"  - {m}" for m in unexpected)
        + "\n\nEach addition is a module whose next change can break a live-call service. "
        "Add it to ALLOWED_APPS_MODULES only if it is genuinely library code."
    )


# Third-party top-level packages. Stdlib is filtered by `sys.stdlib_module_names`
# rather than listed, so a Python upgrade does not turn into a test edit.
ALLOWED_THIRD_PARTY: frozenset[str] = frozenset(
    {
        # First-party. `apps` is pinned module-by-module by ALLOWED_APPS_MODULES above;
        # `calevate_shared` is the Settings/normalized-models package, which by its own
        # import-linter contract depends on no app code.
        "apps",
        "calevate_shared",
        # The service's own modules (importable only via --app-dir; D-18).
        "main",
        "webhook_routes",
        # The in-call tool endpoints (D-56's opt-out). It imports `webhook_routes`'
        # ack/bounded-read helpers and `engine_intake`'s source check and nothing else —
        # deliberately, because it runs while a caller is on the line.
        "tool_routes",
        "engine_intake",
        # The web layer.
        "fastapi",
        "starlette",
        "anyio",
        "sniffio",
        "idna",
        # Config + validation at the boundary (Pydantic v2 is a repo convention).
        "pydantic",
        "pydantic_core",
        "pydantic_settings",
        "annotated_types",
        "annotated_doc",
        "typing_extensions",
        "typing_inspection",
        "dotenv",
        "email_validator",
        # The two rows and the queue.
        "sqlalchemy",
        "greenlet",
        "psycopg",
        "psycopg_binary",
        "psycopg_pool",
        "redis",
        "hiredis",
        "arq",
        "msgpack",
        "uuid_utils",
        # Pulled in by the shared core (JWT verification lives in `core.auth`).
        "jwt",
        "cryptography",
        "cffi",
        # Interpreter/venv furniture, not dependencies.
        "sitecustomize",
        "cython_runtime",
        "pkg_resources",
        "setuptools",
        "_distutils_hack",
    }
)


def test_no_unpinned_third_party_package_is_loaded_at_boot(
    boot_modules: frozenset[str],
) -> None:
    """The catch-all for "no heavy imports": every non-stdlib top-level package this
    process holds was put there deliberately. The failure message is the review."""
    tops = {m.split(".")[0] for m in boot_modules}
    third_party = {
        t for t in tops if t not in sys.stdlib_module_names and not t.startswith("_")
    } - ALLOWED_THIRD_PARTY
    assert not third_party, (
        "voice-runtime loaded third-party packages that are not pinned: "
        f"{sorted(third_party)}\n"
        "Every import here is paid at boot and its transitive graph is paid with it. "
        "If it genuinely belongs on a latency-critical webhook receiver, add it to "
        "ALLOWED_THIRD_PARTY with a reason."
    )


# --- 3. and nothing is imported LAZILY, on the hot path ----------------------


def _client(peer_ip: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=voice_app, client=(peer_ip, 44444), raise_app_exceptions=False),
        base_url="http://runtime",
    )


async def _drive(http: AsyncClient, tag: str) -> None:
    """One pass over EVERY branch either handler has, the error ones included.

    It used to be the receiver's six happy-ish branches — refused, oversized, unreadable,
    unkeyable, accepted, duplicate. That left the whole in-call tool endpoint out of the
    measurement, and every branch reached only by a failure: a hang-up mid-body, a body
    that never finishes, a 409 out of the inbox, an unhandled driver error. Those are
    precisely where a lazy import hides — an error path is where somebody reaches for a
    formatter, a traceback helper or a client "just to report it" — and none of them was
    being watched.
    """
    headers = {"CF-Connecting-IP": ENGINE_EGRESS_IP}
    body = {"execution_id": f"exec_{tag}", "status": f"completed-{tag}"}
    tool = {"execution_id": f"exec_{tag}", "reason": "remove me", "language": "te"}

    await http.post(HOOK, json=body)  # 401: not allowlisted
    await http.post(HOOK, content=b"x" * 2_000_000, headers=headers)  # 413
    await http.post(HOOK, content=b"{not json", headers=headers)  # unreadable
    await http.post(HOOK, json={"status": "completed"}, headers=headers)  # unkeyable
    await http.post(HOOK, json=body, headers=headers)  # accepted
    await http.post(HOOK, json=body, headers=headers)  # duplicate

    await http.post(TOOL, json=tool)  # 401
    await http.post(TOOL, content=b"y" * 8_192, headers=headers)  # 413 at the tool's cap
    await http.post(TOOL, json={"reason": "no id"}, headers=headers)  # 422
    await http.post(TOOL, json=tool, headers=headers)  # 202

    # THE CALL-BACK PAIR (D-514), every branch, for this function's own reason: the
    # booking endpoint's THREE outcomes are all reached by ordinary conversation rather
    # than by error, so leaving two of them undriven would watch the path a caller almost
    # never takes and miss the two they do. `resolve_slot` is the only computation this
    # service performs before deferring, and an import reached from inside it — a date
    # parser somebody thought would be more forgiving — is exactly what this measures.
    await http.post(BOOK, json={"execution_id": f"exec_{tag}"})  # 401
    await http.post(BOOK, json={"execution_id": f"exec_{tag}"}, headers=headers)  # unreadable
    await http.post(
        BOOK,
        json={"execution_id": f"exec_{tag}", "callback_date": _SOON, "callback_time": "04:00"},
        headers=headers,
    )  # outside calling hours
    await http.post(
        BOOK,
        json={"execution_id": f"exec_{tag}", "callback_date": _SOON, "callback_time": "16:00"},
        headers=headers,
    )  # needs confirmation
    await http.post(
        BOOK,
        json={
            "execution_id": f"exec_{tag}",
            "callback_date": _SOON,
            "callback_time": "16:00",
            "confirmed": True,
        },
        headers=headers,
    )  # 202
    await http.post(CANCEL_CALLBACK, json={"execution_id": f"exec_{tag}"}, headers=headers)  # 202

    # THE HANDOVER NOTICE (D-533), every branch. It carries the model's own `reason` and
    # `summary` — free-form prose about a live conversation — and prose is exactly where a
    # lazy import for a formatter, a truncator or a redaction helper would be reached for.
    # Nothing on this path may look at those strings; the worker redacts them.
    await http.post(HANDOFF, json={"execution_id": f"exec_{tag}"})  # 401
    await http.post(HANDOFF, json={"reason": "no id"}, headers=headers)  # 422
    await http.post(
        HANDOFF,
        json={
            "execution_id": f"exec_{tag}",
            "reason": "caller asked for the owner",
            "summary": "Wants a refund on an order from last week.",
        },
        headers=headers,
    )  # 202

    await _hang_up_mid_body(HOOK)  # 400: ClientDisconnect out of the stream
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            webhook_routes,
            "WEBHOOK_ACK",
            replace(webhook_routes.WEBHOOK_ACK, body_deadline_s=0.05),
        )
        await http.post(HOOK, content=_trickle(), headers=headers)  # 408
        patch.setattr(webhook_routes, "claim_inbox_event", _conflict)
        await http.post(HOOK, json=body, headers=headers)  # 409 from the inbox
        patch.setattr(webhook_routes, "claim_inbox_event", _explode)
        await http.post(HOOK, json=body, headers=headers)  # 500, the catch-all


async def _trickle() -> AsyncIterator[bytes]:
    """A body slow enough to outlast any deadline this test sets."""
    yield b'{"execution_id":"exec_slow"'
    for _ in range(5):
        await asyncio.sleep(0.05)
        yield b" "
    yield b"}"


async def _conflict(*_args: Any, **_kwargs: Any) -> Any:
    raise ProblemError.conflict("webhook_payload_mismatch", "different content")


async def _explode(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("the driver fell over")


async def _hang_up_mid_body(path: str) -> None:
    """Drive the app directly: `httpx` always finishes a body, a disconnecting client
    does not."""
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"runtime"),
            (b"content-type", b"application/json"),
            (b"cf-connecting-ip", ENGINE_EGRESS_IP.encode()),
            (b"content-length", b"400"),
        ],
        "client": (EDGE_PROXY_IP, 44444),
        "server": ("runtime", 80),
    }
    inbox: list[dict[str, Any]] = [
        {"type": "http.request", "body": b'{"execution_id":"exec_cut"', "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive() -> dict[str, Any]:
        return inbox.pop(0) if inbox else {"type": "http.disconnect"}

    async def send(_message: dict[str, Any]) -> None:
        return None

    await voice_app(scope, receive, send)


async def test_no_module_is_imported_while_serving_a_request(
    source_ip_allowlist: Callable[..., None],
) -> None:
    """A module imported lazily INSIDE the handler is a heavy import that hid from the
    boot graph — and it is worse than one paid at startup, because the first request
    after every deploy pays it while a call is in flight.

    The warm-up pass below is what makes the second pass meaningful: whatever the first
    request would fault in, it has already faulted in. After that, a correct receiver
    imports nothing at all.

    The one deliberate exception is `opentelemetry.trace` in `_server_span()`, which is
    reached only when a collector is configured and is documented and measured where it
    lives. This test runs with tracing off, i.e. the deployment shape it is asserting
    about — so if that import ever escapes its `tracing_enabled()` guard, this fails.

    **TWO WINDOWS, BECAUSE THE WARM-UP HIDES THE FIRST TIME.** The strict "nothing at all"
    assertion can only see the SECOND pass — whatever the first request faults in is by
    construction already there. That leaves a ONE-TIME lazy import on a rarely-taken branch
    invisible to every guard in this file: the boot graph never sees it (it is inside a
    function) and the warm-up swallows it (it happens once). Found by sabotage, not by
    reading: an `import apps.api.compliance.service` planted on the `ClientDisconnect`
    branch passed this test green. So the cold window is measured too, against `FORBIDDEN`
    rather than against everything — the first request legitimately faults in framework
    internals, and a banned module is never legitimate at any point in the process's life.
    """
    source_ip_allowlist(ENGINE_EGRESS_IP)

    cold = set(sys.modules)
    async with _client(EDGE_PROXY_IP) as http:
        await _drive(http, uuid.uuid4().hex[:12])  # warm-up
        before = set(sys.modules)
        await _drive(http, uuid.uuid4().hex[:12])  # the measured pass
        after = set(sys.modules)

    newly_imported = sorted(after - before)
    assert not newly_imported, (
        "serving a webhook imported modules: "
        f"{newly_imported}\nHard rule 3 budgets 500ms for the whole ack; an import is "
        "tens to hundreds of milliseconds of it, paid on a live call."
    )

    banned = sorted(
        f"{module} ({reason})"
        for module in after - cold
        for prefix, reason in FORBIDDEN.items()
        if module == prefix or module.startswith(f"{prefix}.")
    )
    assert not banned, (
        "serving a webhook pulled in a FORBIDDEN module on some branch:\n"
        + "\n".join(f"  - {entry}" for entry in banned)
        + "\nOnce is enough: the branch that does it is an error path, so the import is "
        "paid by whichever live call happens to hit it first."
    )


# --- 4. what the process acquires AFTER boot, on the alert thread ------------
#
# The two sections above measure the boot graph and the request path. Between them they
# miss one door, and it is open in production and shut in every test: `alert()` queues a
# notice, a daemon thread drains it, and `alerting._deliver` does
# `from apps.workers.transport import get_transport` — an import of a package this file's
# FORBIDDEN list names, into this process, at runtime. It never fires here because
# `ALERTS_EMAIL` is unset in the test environment, so `_recipient()` returns None and
# nothing is queued at all.
#
# D-49 recorded the opposite as a property: "the import happens inside the delivery thread
# so voice-runtime's forbidden `apps.workers` import surface stays clean". Deferring the
# import moved it out of the BOOT graph, which is the only thing anything was checking; it
# did not keep it out of the process. Measured below rather than argued.

#: What a voice-runtime process acquires the first time an alert is DELIVERED.
#:
#: An equality-pinned exception, in the shape this repo already uses for a recorded gap
#: (`check_redaction_exposure.KNOWN_SAFE_FIELDS`): the day it is closed this test goes red
#: and the entry is deleted with it.
#:
#: WHY IT IS RECORDED RATHER THAN CLOSED HERE. The module is not worker code in any real
#: sense — it is an SMTP client, stdlib-only, shared by `workers/notifications.py` and by
#: `core/alerting.py` — and the fix is to move it to `apps/api/core/transport.py`, which is
#: the tree voice-runtime already borrows as a library. That is a rename across two
#: importers, a colocated unit test and three suites, i.e. a change whose whole cost is in
#: files this slice does not own. What is NOT deferred is the visibility: the hole is now
#: measured, named, and fails loudly the moment it grows.
#:
#: The harm today is bounded and stated: the import is stdlib-light (`smtplib`, `email`,
#: `ssl`) and lands on a daemon thread, so it costs the ack path GIL contention for the
#: duration of one import rather than a stall. The harm the FORBIDDEN list is really
#: guarding against is the next reader concluding that `apps.workers` is reachable from
#: here and reaching for something else in it.
RUNTIME_IMPORTS_ON_THE_ALERT_THREAD: dict[str, str] = {
    "apps.workers": (
        "namespace package of `apps.workers.transport`, imported by "
        "`alerting._deliver`. Closes when the SMTP transport moves under "
        "`apps/api/core/`, which is the tree this service already borrows."
    ),
    "apps.workers.transport": (
        "the SMTP/console/null transport `alerting._deliver` sends through. "
        "Closes with the move above."
    ),
}

#: Modules the delivery thread acquires ON PURPOSE, which no rule bans.
#:
#: A SEPARATE constant from the dict above, and the split is the point. That one records
#: a GAP — modules `FORBIDDEN` names, present anyway, each with a sentence about what
#: closes it, pinned by `test_the_recorded_runtime_exception_is_forbidden_at_boot` so it
#: cannot outlive the ban it excepts. This one records a DECISION. Merging them would
#: have made that test demand a ban on `apps.api.core`, which voice-runtime imports as a
#: library by design — so the two lists would have had to contradict each other to stay
#: green, and the cheapest way out would have been deleting the assertion.
#:
#: The measured set below is compared against the UNION: an intended import still has to
#: be declared, or an equality guard cannot tell it from an accidental one.
INTENDED_RUNTIME_IMPORTS_ON_THE_ALERT_THREAD: dict[str, str] = {
    # `alerting._admit_shared` asks Redis whether a SIBLING WORKER has already sent this
    # fingerprint, because `compose.prod.yml` runs this service with `--workers=4` and an
    # in-process window cannot see the other three (D-160).
    #
    # It satisfies hard rule 3 the same way the transport does, and more cheaply. The
    # import is lazy and lands on the delivery thread, never the ack path. It pulls no new
    # distribution, because `redis` is already resident — arq and `core/redis.py` both
    # hold it — and THIS TEST IS THE PROOF, since `redis` does not appear in the measured
    # delta. The call it makes is bounded at `alert_admission.SOCKET_TIMEOUT_S` (0.5s) and
    # fails OPEN, so a Redis outage costs deduplication and never an alarm.
    "apps.api.core.alert_admission": (
        "the cross-process alert suppression gate (D-160). Lazy, delivery thread only, "
        "no new distribution, 0.5s bounded, fails open. Intended — this does not close."
    ),
}

_ALERT_PROBE = """
import json, sys, uuid
sys.path.insert(0, "apps/voice-runtime")
sys.path.insert(1, ".")
import main  # noqa: F401  — boot exactly as the ASGI server does
from apps.api.core.alerting import alert, flush_alerts

before = sorted(sys.modules)
# A FRESH CODE EVERY RUN (D-160). The suppression window is shared through Redis now and
# survives process exit by design — a restart must not re-page an operator — so a fixed
# code meant the second probe within fifteen minutes was suppressed before it reached the
# transport, and measured an import set with the transport missing. Uniqueness makes the
# probe hermetic without depending on Redis being reachable or resettable.
alert("ROUTE_HANDLER", f"import_surface_probe_{uuid.uuid4().hex}", engine="bolna")
flushed = flush_alerts(timeout=20.0)
after = sorted(sys.modules)
# `flush_alerts` only proves the QUEUE drained, which is also what a suppressed notice
# does — so on its own it is not evidence that anything was sent. The transport module
# appearing in the delta is: it is imported by `_deliver` and by nothing else on this
# path. Reported separately so a failure says which of the two went wrong.
delivered = flushed and "apps.workers.transport" in set(after) - set(before)
with open(sys.argv[1], "w") as handle:
    json.dump(
        {"before": before, "after": after, "delivered": delivered, "flushed": flushed},
        handle,
    )
"""


def test_the_alert_delivery_thread_acquires_only_the_recorded_exception() -> None:
    """Fire one alert in a freshly booted voice-runtime and diff `sys.modules`.

    A subprocess for the same reason `_boot_modules` uses one: this pytest process has
    already imported the entire monolith, so a delta measured inside it would be empty and
    would prove nothing. `ALERTS_EMAIL` is set because that is the production shape —
    OPERATIONS §8 makes "alerts firing to Sri's phone" a pre-launch gate, so a deployment
    where this path never runs is a deployment that has failed its own gate.

    `SMTP_HOST` is deliberately left unset: `get_transport()` then hands back the console
    transport, so the probe exercises the IMPORT — which is the subject — without opening a
    socket.
    """
    out = Path(tempfile.gettempdir()) / f"calevate-alert-surface-{uuid.uuid4().hex}.json"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _ALERT_PROBE, str(out)],
            cwd=REPO_ROOT,
            env={
                **os.environ,
                "PYTHONPATH": "",
                "ALERTS_EMAIL": "ops@example.test",
                "SMTP_HOST": "",
                "APP_ENV": "local",
            },
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert proc.returncode == 0, f"the alert probe failed:\n{proc.stderr[-3000:]}"
        measured = json.loads(out.read_text(encoding="utf-8"))
    finally:
        out.unlink(missing_ok=True)

    assert measured["delivered"], (
        "the alert was never delivered, so this measured nothing — check that "
        "ALERTS_EMAIL still selects a recipient and the console transport still reports "
        "success"
    )
    acquired = {
        module
        for module in set(measured["after"]) - set(measured["before"])
        if module.split(".")[0] not in sys.stdlib_module_names and not module.startswith("_")
    }
    expected = set(RUNTIME_IMPORTS_ON_THE_ALERT_THREAD) | set(
        INTENDED_RUNTIME_IMPORTS_ON_THE_ALERT_THREAD
    )
    assert acquired == expected, (
        "delivering one alert changed what this latency-critical process holds:\n"
        + "\n".join(f"  - {module}" for module in sorted(acquired))
        + "\n\nIf the transport has moved out of `apps.workers`, delete the matching "
        "RUNTIME_IMPORTS_ON_THE_ALERT_THREAD entries — a recorded gap that outlives the "
        "gap is a hole with a comment on it. If something NEW appeared, it is on the "
        "shared-process side of hard rule 3 and needs the same argument as any boot import."
    )


def test_the_recorded_runtime_exception_is_forbidden_at_boot() -> None:
    """The two lists must not drift into contradicting each other.

    Everything in `RUNTIME_IMPORTS_ON_THE_ALERT_THREAD` is a module FORBIDDEN above. That
    is what makes it an exception rather than a second opinion: if somebody legitimises
    `apps.workers` in `FORBIDDEN`, this fails and the runtime record has to be revisited
    in the same change rather than quietly becoming redundant.
    """
    for module in RUNTIME_IMPORTS_ON_THE_ALERT_THREAD:
        assert any(module == prefix or module.startswith(f"{prefix}.") for prefix in FORBIDDEN), (
            f"{module} is recorded as a runtime exception to a rule that no longer bans it"
        )


def test_the_docstring_that_promises_this_file_names_this_file() -> None:
    """`main.py` cites its import guard by name. It cited a file that did not exist for
    long enough that nobody noticed — which is exactly how a guardrail rots. If the name
    drifts again, this fails and says so."""
    main_py = (REPO_ROOT / "apps" / "voice-runtime" / "main.py").read_text(encoding="utf-8")
    assert Path(__file__).name in main_py, (
        f"apps/voice-runtime/main.py should cite {Path(__file__).name} as its import guard"
    )


__all__: list[Any] = []
