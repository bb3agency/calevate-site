"""Negative controls for `scripts/check_idempotency_scope`.

A guard that has never been seen to fail is a comment with an exit code — `tests/
audit_ip_guard_test.py`'s opening line, and the same method here: drive the checker over
doctored trees so each way the property can be lost is DEMONSTRATED rather than asserted.

The defect being pinned is the one the reference-platform teardown found and we do not
have: an idempotency scope falling back to the client address, which behind a proxy is our
own edge — so every anonymous caller shares one replay namespace and the second one is
served the first one's stored response. Each control below reintroduces it in one of the
shapes an author could plausibly reach for.

The real tree runs FIRST, because a checker that rejects everything also rejects the
defect, and a suite that only proves refusal has not shown it accepts good input.

Run: uv run pytest -q tests/idempotency_scope_guard_test.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"

#: The real signature, copied in SHAPE rather than imported — the doctored tree has to
#: stand alone, and importing the real one would test the real one.
PRODUCER = '''
from uuid import UUID


def scope_key(*, tenant_id: UUID | None, user_id: UUID | None) -> str:
    """HMAC fingerprint of tenant/user — raw ids are never stored."""
    return _hmac(f"{tenant_id}:{user_id}")
'''

#: A call site of the shape all four real ones have.
CLEAN_CALL_SITE = """
async def call_lead(session, request, principal):
    claim = await claim_idempotency(
        session,
        scope=scope_key(tenant_id=principal.tenant_id, user_id=principal.user_id),
        route="/v1/leads/{lead_id}/call",
        method="POST",
        key=request.headers.get("Idempotency-Key"),
        request_hash=body_hash({}),
    )
    return claim
"""


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    """Run a COPY of the checker rooted at `root` — it locates its scopes from `__file__`.

    `-m` with `cwd=root`, not a bare path, because the checker imports `is_peer_read` from
    its sibling rather than restating it; the package directory has to be importable for
    the copy exactly as it is for the original.
    """
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in ("__init__.py", "check_audit_ip.py", "check_idempotency_scope.py"):
        (scripts / name).write_text((SCRIPTS / name).read_text(encoding="utf-8"))
    return subprocess.run(
        [sys.executable, "-m", "scripts.check_idempotency_scope"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _tree(root: Path, *, producer: str = PRODUCER, extra: dict[str, str] | None = None) -> None:
    """A minimal `apps/api` holding the producer plus whatever the test is about.

    The producer is always present: the checker fails when `scope_key` stops existing or
    stops being typed, so a tree that omits it fails for a reason no test below means.
    """
    reliability = root / "apps" / "api" / "reliability"
    reliability.mkdir(parents=True, exist_ok=True)
    (reliability / "service.py").write_text(producer)
    for relative, body in (extra or {}).items():
        path = root / "apps" / "api" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


def test_the_real_tree_passes() -> None:
    """First, and it is also the audit's finding: we do not have the defect."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_idempotency_scope"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "IDEMPOTENCY SCOPE: OK" in result.stdout


def test_a_faithful_copy_of_a_clean_tree_passes(tmp_path: Path) -> None:
    """Proves the doctored trees differ from a clean one only in the defect, and not in
    some accident of how they are assembled."""
    _tree(tmp_path, extra={"crm/routes.py": CLEAN_CALL_SITE})
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout


#: THE FINDING ITSELF, in the three shapes it could reach our tree. Each is a scope
#: derived from something the caller controls or shares with strangers, and each would be
#: refused for a different reason — which is why they are separate controls rather than
#: one.
FALLBACKS = {
    # The reference project's literal line, transliterated: the address as the scope.
    "socket_peer": """
async def call_lead(session, request, principal):
    return await claim_idempotency(
        session,
        scope=scope_key(tenant_id=principal.tenant_id, user_id=request.client.host),
        route="/v1/leads/{lead_id}/call",
        method="POST",
        key="k",
        request_hash="h",
    )
""",
    # The resolver-shaped version, which reads as careful and is the same fallback: a
    # CALL is the shape `client_request_ip(request)` and `fingerprint(ip)` both have.
    "resolved_address": """
async def call_lead(session, request, principal):
    return await claim_idempotency(
        session,
        scope=scope_key(tenant_id=client_request_ip(request), user_id=None),
        route="/v1/leads/{lead_id}/call",
        method="POST",
        key="k",
        request_hash="h",
    )
""",
    # A header the caller sends. Subscripting is how a cookie arrives too.
    "header": """
async def call_lead(session, request, principal):
    return await claim_idempotency(
        session,
        scope=scope_key(tenant_id=request.headers["X-Org"], user_id=None),
        route="/v1/leads/{lead_id}/call",
        method="POST",
        key="k",
        request_hash="h",
    )
""",
}


@pytest.mark.parametrize("shape", sorted(FALLBACKS))
def test_an_attacker_choosable_scope_is_refused(tmp_path: Path, shape: str) -> None:
    """The defect arriving. Two callers who can compute one scope share one response
    cache, and the replay is served before any tenant-scoped query runs — so no RLS policy
    is in a position to stop it."""
    _tree(tmp_path, extra={"crm/routes.py": FALLBACKS[shape]})
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "IDEMPOTENCY SCOPE: FAIL" in result.stdout
    assert "apps/api/crm/routes.py" in result.stdout
    assert "call_lead" in result.stdout, "the message must name the function"


def test_a_hand_built_scope_string_is_refused(tmp_path: Path) -> None:
    """The second producer. An f-string scope is not wrong on the day it is written — it is
    where the divergence starts, and `scope_key` exists partly because §4 forbids storing
    the raw ids this would store."""
    smuggled = """
async def call_lead(session, request, principal):
    return await claim_idempotency(
        session,
        scope=f"tenant:{principal.tenant_id}",
        route="/v1/leads/{lead_id}/call",
        method="POST",
        key="k",
        request_hash="h",
    )
"""
    _tree(tmp_path, extra={"crm/routes.py": smuggled})
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "rather than from `scope_key(...)`" in result.stdout


def test_one_local_hop_to_the_producer_is_accepted(tmp_path: Path) -> None:
    """The precision control. `billing/payment_routes.py` really does build the scope a few
    lines before the claim — it has to commit the claim before a network call — so a guard
    that could not follow one assignment would be one somebody switches off."""
    hopped = """
async def create_order(session, tenant_id):
    scope = scope_key(tenant_id=tenant_id, user_id=None)
    return await claim_idempotency(
        session, scope=scope, route="/v1/billing/topups", method="POST",
        key="receipt", request_hash="h",
    )
"""
    _tree(tmp_path, extra={"billing/payment_routes.py": hopped})
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout


def test_a_local_rebound_to_an_address_is_refused(tmp_path: Path) -> None:
    """...and the hop is followed rather than trusted. A name bound BOTH to the producer
    and to something else is the shape that would sneak past a guard that stopped at
    "well, it was a `scope_key` call once"."""
    rebound = """
async def create_order(session, request, tenant_id):
    scope = scope_key(tenant_id=tenant_id, user_id=None)
    if tenant_id is None:
        scope = f"anon:{request.client.host}"
    return await claim_idempotency(
        session, scope=scope, route="/v1/billing/topups", method="POST",
        key="receipt", request_hash="h",
    )
"""
    _tree(tmp_path, extra={"billing/payment_routes.py": rebound})
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "create_order" in result.stdout


@pytest.mark.parametrize(
    ("function", "argument"),
    [
        ("claim_inbox_event", "event_key"),
        ("claim_inbox_event", "provider"),
        ("enqueue_outbox_once", "dedupe_key"),
    ],
)
def test_the_other_replay_namespaces_refuse_the_peer_too(
    tmp_path: Path, function: str, argument: str
) -> None:
    """The inbox pair and the outbox dedupe key are replay namespaces with the same
    consequence as a scope: two principals sharing one means one of them is answered
    "duplicate" for work that was never done for them."""
    # Built from a keyword MAP rather than a template with an extra line appended:
    # `ast.parse` accepts a repeated keyword (the duplicate is rejected later, at compile
    # time), and the checker reads the first occurrence — so a naive template would have
    # produced a control that passed for a reason the test did not mean. It did, once.
    keywords = {"provider": '"bolna"', "event_key": '"e"', "payload_hash": '"h"'}
    if function == "enqueue_outbox_once":
        keywords = {"job": '"notify"', "payload": "{}", "dedupe_key": '"d"'}
    keywords[argument] = "request.client.host"
    rendered = "".join(f"        {name}={value},\n" for name, value in keywords.items())
    offending = f"""
async def receive(session, request):
    return await {function}(
        session,
{rendered}    )
"""
    _tree(tmp_path, extra={"ingest/routes.py": offending, "crm/routes.py": CLEAN_CALL_SITE})
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "socket peer" in result.stdout
    assert argument in result.stdout


def test_the_idempotency_key_header_itself_is_not_a_finding(tmp_path: Path) -> None:
    """The other precision control, and the distinction the whole design rests on: the
    `Idempotency-Key` is SUPPOSED to be the caller's to choose, and is safe precisely
    because the scope beside it is not. A guard that banned the header outright would be
    banning the feature."""
    _tree(tmp_path, extra={"crm/routes.py": CLEAN_CALL_SITE})
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout
    assert 'request.headers.get("Idempotency-Key")' in CLEAN_CALL_SITE


def test_widening_the_signature_to_a_string_is_refused(tmp_path: Path) -> None:
    """THE LOAD-BEARING PROPERTY. `tenant_id: UUID | None` is why mypy strict already
    refuses a header at every call site in the repo; widening it to `str` retires that
    guarantee everywhere at once, and would do so with no call site changing at all."""
    widened = PRODUCER.replace("tenant_id: UUID | None", "tenant_id: str | None")
    _tree(tmp_path, producer=widened, extra={"crm/routes.py": CLEAN_CALL_SITE})
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "THE TYPE IS THE GUARD" in result.stdout


def test_a_positional_producer_is_refused(tmp_path: Path) -> None:
    """Keyword-only is what stops a caller passing one id and meaning the other. Asserted
    separately because a signature check is exactly where "we looked at the annotations"
    hides."""
    positional = PRODUCER.replace(
        "def scope_key(*, tenant_id: UUID | None, user_id: UUID | None)",
        "def scope_key(tenant_id: UUID | None, *, user_id: UUID | None)",
    )
    _tree(tmp_path, producer=positional, extra={"crm/routes.py": CLEAN_CALL_SITE})
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "positional parameters" in result.stdout


def test_a_producer_that_moved_away_is_named_rather_than_crashed_on(tmp_path: Path) -> None:
    """`reliability/service.py` going missing is the case the whole property is about, and
    a guard that raises on its own subject reads to CI as "the check is broken" rather
    than "the guarantee left the building"."""
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert result.stderr == "", "a finding, not a traceback"
    assert "no longer defines `scope_key`" in result.stdout


def test_a_tree_with_no_claim_sites_is_refused(tmp_path: Path) -> None:
    """The must-bite control. Every rule above passes vacuously over a tree with nothing to
    examine, and the likeliest cause is not that idempotency was deleted — it is that it
    moved somewhere this check no longer reaches."""
    _tree(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout
    assert "without examining anything" in result.stdout


@pytest.mark.parametrize("mention", ["docstring", "comment"])
def test_prose_naming_the_defect_is_not_a_finding(tmp_path: Path, mention: str) -> None:
    """The checker's own module docstring quotes the fallback it bans, and so does this
    file. AST rather than grep is what makes that free — the lesson `check_model_residency`
    and `check_audit_ip` both had to learn about their own prose."""
    body = (
        '"""Never write scope=scope_key(tenant_id=request.client.host, user_id=None)."""\n'
        if mention == "docstring"
        else "# never write scope=f'anon:{request.client.host}' here\n"
    )
    _tree(tmp_path, extra={"crm/routes.py": body + CLEAN_CALL_SITE})
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout
