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
        # D-591. `alerting` reads it on every `alert()` call to decide whether the alarm
        # mails — a frozen dict of 224 strings and three pure functions, with no import of
        # its own beyond `typing`. Library code by every test this list applies: it holds
        # no product behaviour, touches no database and cannot fail. It is here rather than
        # inlined in `alerting` because the file's whole content is the CLASSIFICATION
        # ARGUMENT, one code at a time, and burying that in a delivery module is how it
        # stops being reviewed.
        "apps.api.core.alarm_severity",
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
        # NOT OURS, AND NOT AVOIDABLE. `starlette.requests` imports `starlette.
        # formparsers` at module scope, which imports `python_multipart` at module scope
        # the moment the package is present in the environment — so this appeared here on
        # the day the KB upload lane added the dependency for `apps/api`'s ONE multipart
        # route, without voice-runtime importing anything new. It is not on this service's
        # hot path: nothing here declares a `Form` or `File` parameter, and every webhook
        # body is read as bytes. Removing it from the boot graph would mean removing it
        # from the venv, which is a change to a different service's dependencies for no
        # measured gain (~46KB of pure Python). Pinned and vetted at `apps/api/pyproject.
        # toml:38-55` (hard rule 9), which is what this list is asking about.
        "python_multipart",
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
# notice, a daemon thread drains it, and `alerting._deliver` imports the transport into
# this process at runtime. It never fires in the other tests because `ALERTS_EMAIL` is
# unset there, so `_recipient()` returns None and nothing is queued at all.
#
# THIS SECTION USED TO RECORD A GAP, AND THE GAP IS CLOSED. The transport lived at
# `apps/workers/transport.py`, so delivering one alert pulled `apps.workers` — a package
# this file's FORBIDDEN list names — into a latency-critical process. D-49 had recorded
# the opposite as a property ("the import happens inside the delivery thread so the
# forbidden surface stays clean"); deferring the import moved it out of the BOOT graph,
# which was the only thing anything checked, and did not keep it out of the process.
#
# The module was never worker code in any real sense — an SMTP client importing nothing
# but stdlib, `calevate_shared.config` and `apps.api.core` — and it now lives at
# `apps/api/core/transport.py`, the tree voice-runtime already borrows as a library. So
# `RUNTIME_IMPORTS_ON_THE_ALERT_THREAD` and the consistency test that pinned it are
# DELETED rather than emptied: a recorded gap that outlives the gap is a hole with a
# comment on it, and an empty dict with a test iterating it is a guard that agrees with
# anything. What survives is the measurement — the equality below still fails the moment
# this thread acquires anything undeclared.

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
    # The SMTP/console/null transport `_deliver` sends through. It is here rather than in
    # a gap list because no rule bans it: `apps.api.core` is the library tree this service
    # already imports at boot. The cost is bounded and stated — its only imports are
    # stdlib (`smtplib`, `email`), `calevate_shared.config` and two `apps.api.core`
    # modules already resident, so the delta is this one module and it lands on a daemon
    # thread, never the ack path. `httpx` is NOT here: the Resend transport imports it
    # inside the send, so a deployment on SMTP or console never pays for it.
    "apps.api.core.transport": (
        "the SMTP/console/null transport `alerting._deliver` sends through. Intended: "
        "`apps.api.core` is the tree this service borrows as a library, the import is "
        "stdlib-light and lands on the delivery thread. This does not close."
    ),
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
    # D-591. `alerting._handle` writes one row per alarm EPISODE, which is both the whole
    # of `/admin/ops/alerts` and the thing that decides whether a `page` is an onset or a
    # repeat. It satisfies hard rule 3 on the same three terms as its two neighbours and
    # one more that matters here specifically:
    #
    #   * LAZY AND ON THE DELIVERY THREAD. `alerting` imports it under `TYPE_CHECKING`
    #     only; the runtime import happens inside `_handle`, which the ack path reaches
    #     through a `put_nowait` on a bounded queue and never waits for.
    #   * NO NEW DISTRIBUTION. `psycopg` does not appear in the measured delta because
    #     SQLAlchemy's async engine already holds it at boot — THIS TEST IS THE PROOF, the
    #     same proof it gives for `redis` one entry up.
    #   * BOUNDED AND FAILS OPEN. One short-lived connection with `connect_timeout` and a
    #     libpq-level `statement_timeout`, both `RECORD_TIMEOUT_S` (3s), and a failure
    #     returns `None` — which `_handle` reads as "I cannot tell whether this is new" and
    #     MAILS. So the database can only ever suppress a repeat, never an alarm.
    #   * IT DOES NOT MAKE THE ALERT PATH DEPEND ON THE THING IT REPORTS ON. That is the
    #     module docstring's founding argument for keeping this off the outbox, and the
    #     line above is what keeps it true one component over.
    # AND THE DRIVER IT PULLS WITH IT, declared separately because it is a DISTRIBUTION
    # and not one of our modules. In production this costs the alert thread NOTHING: this
    # service's webhook receiver already imports `apps.api.db.session` at boot and writes
    # the minimal event row hard rule 3 allows it, so `postgresql+psycopg` is resident long
    # before any alarm fires — the probe only sees it because it alerts on a freshly booted
    # process that has not yet opened a connection. The worst case is therefore a
    # first-alarm-before-first-webhook import on a DAEMON thread, which no ack waits on.
    # The compiled half of the same distribution (`psycopg[binary]`, the extra this repo
    # pins). Its own top-level name, so it needs its own row; the argument is the row
    # above's, word for word.
    "psycopg_binary": (
        "the compiled half of `psycopg[binary]`, pulled by the row below and covered by "
        "the same argument: already this service's own driver, daemon thread, never the "
        "ack path."
    ),
    "psycopg": (
        "the database driver `alert_records` connects through, covering its submodules. "
        "Already this service's own driver (`apps/api/db/session.py`, "
        "`postgresql+psycopg`), so in production it is resident before the first alarm; "
        "the delta here is a freshly booted probe. Daemon thread, never the ack path."
    ),
    "apps.api.core.alert_records": (
        "the alert EPISODE recorder (D-591) — one row per alarm, and the onset/repeat "
        "answer that decides whether a `page` mails. Lazy, delivery thread only, no new "
        "distribution (psycopg is already resident), 3s bounded, fails OPEN so it can "
        "only suppress a repeat. Intended — this does not close."
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
delivered = flushed and "apps.api.core.transport" in set(after) - set(before)
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
    # A DECLARED NAME COVERS ITS SUBMODULES, which stdlib already got for free one line
    # up (`module.split(".")[0] not in sys.stdlib_module_names`). `psycopg` brings forty
    # private submodules in one `import psycopg`; listing each would make the declaration
    # unreadable and would say nothing the top-level entry does not — the question this
    # test asks is "what DISTRIBUTION did the delivery thread reach for", and forty rows
    # for one answer is how a pinned set stops being read. Anything not under a declared
    # name is still reported by its full path.
    declared = set(INTENDED_RUNTIME_IMPORTS_ON_THE_ALERT_THREAD)
    acquired = {
        module
        for module in set(measured["after"]) - set(measured["before"])
        if module.split(".")[0] not in sys.stdlib_module_names and not module.startswith("_")
    }
    acquired = {
        next((name for name in declared if module == name or module.startswith(f"{name}.")), module)
        for module in acquired
    }
    expected = declared
    assert acquired == expected, (
        "delivering one alert changed what this latency-critical process holds:\n"
        + "\n".join(f"  - {module}" for module in sorted(acquired))
        + "\n\nIf something NEW appeared, it is on the shared-process side of hard rule "
        "3 and needs the same argument as any boot import: declare it in "
        "INTENDED_RUNTIME_IMPORTS_ON_THE_ALERT_THREAD with what it costs the ack path, or "
        "make the delivery thread stop reaching for it."
    )


# --- 5. and what the BACKGROUND CONFIG POLL acquires, three seconds after boot ---
#
# THE FOURTH DOOR, and it was open. The sections above measure three of them — the boot
# graph, the request path and the alert thread; none can see the poll task, because it does
# not exist until the LIFESPAN runs and it does its work on a timer after that. Every
# guard in this file booted the module, read `sys.modules` and finished looking before the
# task had done anything.
#
# What it did: `_startup` calls `start_config_refresher()`, whose loop refreshes FIRST and
# sleeps after, and `platform_config.refresh` called `_read_secrets()` unconditionally —
# a LAZY import of `apps.api.ops.secret_service` (invisible to the boot graph by
# construction), a SELECT of `platform_secrets`, and an AES-GCM unseal of every stored
# vendor credential into this process's `Settings`. Measured, not argued: the poll added
# `apps.api.ops`, `apps.api.ops.config_service` and `apps.api.ops.secret_service`, three
# of which the first section of this file names FORBIDDEN by prefix. `compose.prod.yml`
# gives all three services the same `env_file`, so `PLATFORM_KEK` was present and the
# unseal succeeded.
#
# The fix is `start_config_refresher(with_secrets=False)` in `apps/voice-runtime/main.py`:
# this service reads the source-IP allowlist, the selected engine and `app_env`, and no
# credential at any point. This section is the measurement that keeps it that way — and it
# is deliberately a MEASUREMENT of the running task rather than an assertion about the
# keyword, because the keyword is one refactor away from meaning something else.


#: What the poll may add to this process. EMPTY, and that is the assertion: a config
#: refresh reads two rows through machinery the boot graph already holds, so acquiring
#: anything at all means a new door — the credential path returning, a driver faulted in
#: late, or a module reached from inside `refresh`.
INTENDED_POLL_IMPORTS: dict[str, str] = {}

#: The tables the poll is allowed to read. `platform_config_version` is the sentinel and
#: `platform_settings` is the payload; `platform_secrets` is the one that must never
#: appear. This is also the correction to `voice_runtime_deploy_independence_test.py`,
#: whose SCHEMA_SURFACE covers the REQUEST path only — the poll's two reads are this
#: deployable's other schema surface, and they were unmeasured and undeclared.
POLL_TABLES: frozenset[str] = frozenset({"platform_config_version", "platform_settings"})

_POLL_PROBE = """
import asyncio, json, re, sys
sys.path.insert(0, "apps/voice-runtime")
sys.path.insert(1, ".")
import main  # noqa: F401  — boot exactly as the ASGI server does
from apps.api.core import platform_config
from apps.api.db.session import get_engine
from sqlalchemy import event

statements = []


def _on_execute(_conn, _cursor, statement, *_rest):
    statements.append(" ".join(statement.split()))


async def go():
    event.listen(get_engine().sync_engine, "before_cursor_execute", _on_execute)
    # AFTER the probe's own imports and after the engine exists, so the delta is the
    # POLL's and nothing else's.
    before = sorted(sys.modules)
    async with main.app.router.lifespan_context(main.app):
        # Wait for the first refresh to actually land rather than sleeping a fixed
        # interval: a probe that measured a poll which had not run yet would report a
        # clean process and prove nothing.
        for _ in range(200):
            if platform_config.snapshot().loaded_at is not None:
                break
            await asyncio.sleep(0.05)
        after = sorted(sys.modules)
        snapshot = platform_config.snapshot()
        loaded = snapshot.loaded_at is not None and not snapshot.degraded
    named = set()
    for statement in statements:
        named.update(re.findall(r"(?:into|from|update)\\s+(\\w+)", statement.lower()))
    tables = sorted(named)
    with open(sys.argv[1], "w") as handle:
        json.dump({"before": before, "after": after, "loaded": loaded, "tables": tables}, handle)


asyncio.run(go())
"""


def _poll_measurement() -> dict[str, Any]:
    out = Path(tempfile.gettempdir()) / f"calevate-poll-surface-{uuid.uuid4().hex}.json"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _POLL_PROBE, str(out)],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONPATH": ""},
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert proc.returncode == 0, f"the poll probe failed:\n{proc.stderr[-3000:]}"
        measured: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    finally:
        out.unlink(missing_ok=True)
    assert measured["loaded"], (
        "the config poll never completed a refresh, so this measured nothing — the probe "
        "needs a reachable database and Redis, exactly as the rest of the suite does"
    )
    return measured


@pytest.fixture(scope="module")
def poll_measurement() -> dict[str, Any]:
    return _poll_measurement()


def test_the_config_poll_acquires_nothing_this_service_is_not_allowed_to_hold(
    poll_measurement: dict[str, Any],
) -> None:
    """The door the other three sections cannot see, measured with the same instrument."""
    acquired = {
        module
        for module in set(poll_measurement["after"]) - set(poll_measurement["before"])
        if module.split(".")[0] not in sys.stdlib_module_names and not module.startswith("_")
    }
    banned = sorted(
        f"{module} ({reason})"
        for module in acquired
        for prefix, reason in FORBIDDEN.items()
        if module == prefix or module.startswith(f"{prefix}.")
    )
    assert not banned, (
        "the background config poll pulled FORBIDDEN modules into this latency-critical "
        "process:\n" + "\n".join(f"  - {entry}" for entry in banned) + "\n\nA lazy import "
        "inside the refresh is invisible to the boot graph and to the request-path guard: "
        "the poll runs seconds after both have finished looking."
    )
    assert acquired == set(INTENDED_POLL_IMPORTS), (
        "the config poll changed what this process holds:\n"
        + "\n".join(f"  - {module}" for module in sorted(acquired))
        + "\n\nDeclare it in INTENDED_POLL_IMPORTS with what it costs, or make the refresh "
        "stop reaching for it."
    )


def test_the_config_poll_reads_no_credential_row(poll_measurement: dict[str, Any]) -> None:
    """The blast radius half of the same finding, in SQL rather than in imports.

    `platform_secrets` here would mean this process had decrypted every stored vendor
    credential into its own `Settings` — a service that calls no vendor, holding the whole
    credential store, on the box that answers live-call webhooks.
    """
    tables = set(poll_measurement["tables"])
    assert "platform_secrets" not in tables, (
        "the config poll read `platform_secrets`: voice-runtime is decrypting credentials "
        "it never uses. `apps/voice-runtime/main.py` must call "
        "`start_config_refresher(with_secrets=False)`."
    )
    assert tables <= POLL_TABLES, (
        f"the config poll now reads {sorted(tables - POLL_TABLES)}. Every table beyond the "
        "sentinel and its payload is a release schedule this deployable does not control "
        "(hard rule 3's last clause)."
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
