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
from collections.abc import Callable
import catches the intent before the millisecond.

Measured as the REAL import graph — a fresh interpreter that imports the app exactly as
`uvicorn --app-dir apps/voice-runtime` does, then reports `sys.modules`. Not a grep:
a grep sees `from apps.api.reliability.service import body_hash` and stops, where the
truth is whatever that pulls behind it, three levels down. A subprocess is also the only
honest way to ask the question from inside pytest, whose own process has already
imported the entire monolith, every adapter and half of PyPI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from main import app as voice_app

REPO_ROOT = Path(__file__).resolve().parents[1]

ENGINE_EGRESS_IP = "198.51.100.7"
EDGE_PROXY_IP = "127.0.0.1"
HOOK = "/hooks/v1/engine/bolna"

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
        return frozenset(json.loads(out.read_text()))
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
    """One pass over every branch the handler has: refused, oversized, unreadable,
    unkeyable, accepted, duplicate."""
    headers = {"CF-Connecting-IP": ENGINE_EGRESS_IP}
    body = {"execution_id": f"exec_{tag}", "status": f"completed-{tag}"}
    await http.post(HOOK, json=body)  # 401: not allowlisted
    await http.post(HOOK, content=b"x" * 2_000_000, headers=headers)  # 413
    await http.post(HOOK, content=b"{not json", headers=headers)  # unreadable
    await http.post(HOOK, json={"status": "completed"}, headers=headers)  # unkeyable
    await http.post(HOOK, json=body, headers=headers)  # accepted
    await http.post(HOOK, json=body, headers=headers)  # duplicate


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
    """
    source_ip_allowlist(ENGINE_EGRESS_IP)

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


def test_the_docstring_that_promises_this_file_names_this_file() -> None:
    """`main.py` cites its import guard by name. It cited a file that did not exist for
    long enough that nobody noticed — which is exactly how a guardrail rots. If the name
    drifts again, this fails and says so."""
    main_py = (REPO_ROOT / "apps" / "voice-runtime" / "main.py").read_text()
    assert Path(__file__).name in main_py, (
        f"apps/voice-runtime/main.py should cite {Path(__file__).name} as its import guard"
    )


__all__: list[Any] = []
