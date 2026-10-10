"""The caller lookup: ThinnestAI asks our API who is ringing before its agent answers (D-716).

ThinnestAI calls an agent's `voice.callStartUrl` when an inbound phone or WhatsApp call is
about to be answered, and fills the agent's `{{...}}` placeholders from the answer
(docs.thinnest.ai channels/voice "Who-is-calling lookup" and api-reference/agents/
update-agent `callStartUrl`, read 10 Oct 2026). Callers and their history live in OUR
database, so the address is always ours, per agent, set at publish and kept there by the
drift sweep (founder decision, 10 Oct 2026): caller data never goes to a third-party URL.

THE SECRET IS THE VENDOR'S, NOT OURS, which is the difference from `engine_actions`. The
vendor mints it and shows it once, on the response to the request that set a new address
or sent `callStartSecret: "rotate"`. So:

* we hold the only readable copy, sealed under `PLATFORM_KEK` on the route row;
* when we hold none we can use (first publish, a lost KEK, a rolled-back publish that had
  already set the address) we ROTATE, which invalidates the old one at once;
* a console edit that moved the address is put back, which mints a new secret too.

Failures here never fail a publish: without the lookup a call still goes ahead, only
without the caller's name (the vendor's own rule: "no answer in 2 seconds ... and the call
goes ahead without them"). The drift sweep converges it and alarms when it had to.
"""

from __future__ import annotations

from typing import Any, Final, Literal
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.envelope import Envelope, seal, unseal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings, is_public_callback_base
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_actions import ThinnestActions, thinnest_actions

log = get_logger(__name__)

THINNEST: Final = "thinnest"
LOOKUP_ENGINES: Final = frozenset({THINNEST})

#: Under `/v1/worker/` for `engine_actions.ACTIONS_PATH`'s reason: a caller is waiting.
LOOKUPS_PATH: Final = "/v1/worker/engine-lookups"
AGENT_QUERY_PARAM: Final = "agent"
#: `voice.callStartUrl` is at most 500 characters (update-agent `AgentVoiceInput`).
URL_MAX: Final = 500

_SECRET_COLUMNS: Final = (
    "call_start_secret_ciphertext, call_start_secret_nonce, call_start_secret_dek_wrapped, "
    "call_start_secret_dek_nonce, call_start_secret_kek_version"
)


def lookup_url(engine: str, engine_agent_ref: str) -> str | None:
    """Our lookup address for this vendor agent, or None while the API has no public base."""
    base = (get_settings().engine_actions_base_url or "").strip().rstrip("/")
    if not is_public_callback_base(base):
        return None
    url = f"{base}{LOOKUPS_PATH}/{engine}?{urlencode({AGENT_QUERY_PARAM: engine_agent_ref})}"
    return url if len(url) <= URL_MAX else None


def call_start_secret_context(engine: str, engine_agent_ref: str) -> str:
    """The AAD binding the sealed secret to ONE route row."""
    return f"engine_call_start_secret:{engine}:{engine_agent_ref}"


def envelope_of(row: tuple[Any, ...]) -> Envelope | None:
    if any(value is None for value in row):
        return None
    ct, nonce, dw, dn, kek = row
    return Envelope(
        ciphertext=bytes(ct),
        nonce=bytes(nonce),
        dek_wrapped=bytes(dw),
        dek_nonce=bytes(dn),
        kek_id=int(kek),
    )


def open_call_start_secret(envelope: Envelope, *, engine: str, engine_agent_ref: str) -> str | None:
    """The plaintext, or None when no configured key opens it (`unseal` logged why)."""
    try:
        return unseal(envelope, context=call_start_secret_context(engine, engine_agent_ref))
    except ProblemError:
        return None


async def read_call_start_secret(
    session: AsyncSession, *, engine: str, engine_agent_ref: str, lock: bool = False
) -> tuple[bool, str | None, UUID | None, UUID | None]:
    """(route exists and is active, usable secret, tenant, agent). Works in an untenanted
    session: `engine_agent_routes` is the listed RLS exemption."""
    row = (
        await session.execute(
            text(
                f"SELECT {_SECRET_COLUMNS}, tenant_id, agent_id, active "
                "FROM engine_agent_routes WHERE engine = :engine AND engine_agent_ref = :ref"
                + (" FOR UPDATE" if lock else "")
            ),
            {"engine": engine, "ref": engine_agent_ref},
        )
    ).first()
    if row is None or not row[7]:
        return False, None, None, None
    envelope = envelope_of(tuple(row[:5]))
    secret = (
        open_call_start_secret(envelope, engine=engine, engine_agent_ref=engine_agent_ref)
        if envelope is not None
        else None
    )
    return True, secret, UUID(str(row[5])), UUID(str(row[6]))


async def _store_secret(
    session: AsyncSession, *, engine: str, engine_agent_ref: str, secret: str
) -> None:
    envelope = seal(secret, context=call_start_secret_context(engine, engine_agent_ref))
    await session.execute(
        text(
            "UPDATE engine_agent_routes SET call_start_secret_ciphertext = :ct, "
            "call_start_secret_nonce = :n, call_start_secret_dek_wrapped = :dw, "
            "call_start_secret_dek_nonce = :dn, call_start_secret_kek_version = :kek, "
            "updated_at = now() WHERE engine = :engine AND engine_agent_ref = :ref"
        ),
        {
            "ct": envelope.ciphertext,
            "n": envelope.nonce,
            "dw": envelope.dek_wrapped,
            "dn": envelope.dek_nonce,
            "kek": envelope.kek_id,
            "engine": engine,
            "ref": engine_agent_ref,
        },
    )


LookupOutcome = Literal["not_applicable", "no_public_address", "in_sync", "set", "rotated"]


def _no_secret_returned() -> ProblemError:
    return ProblemError(
        kind="dependency",
        code="engine_call_start_secret_missing",
        title="The voice platform did not return the caller lookup's signing secret",
        detail="The caller lookup address was saved, but its signing secret was not shown.",
        remediation="The next settings check asks for a new secret.",
    )


async def ensure_call_start(
    session: AsyncSession,
    *,
    engine: str,
    engine_agent_ref: str,
    client: ThinnestActions | None = None,
) -> LookupOutcome:
    """Make the vendor agent's caller lookup point at our endpoint with a secret we hold.

    Call it in the tenant session that wrote the agent's `engine_agent_routes` row. The row
    is locked so two publishes cannot both mint (and the second invalidate the first's)."""
    if engine not in LOOKUP_ENGINES:
        return "not_applicable"
    wanted = lookup_url(engine, engine_agent_ref)
    if wanted is None:
        return "no_public_address"
    exists, secret, _tenant, _agent = await read_call_start_secret(
        session, engine=engine, engine_agent_ref=engine_agent_ref, lock=True
    )
    if not exists:
        return "not_applicable"
    vendor = client or thinnest_actions()
    held = await vendor.call_start_url(engine_agent_ref)
    if held == wanted and secret is not None:
        return "in_sync"
    # Same address and no secret we can read: only a rotation mints one. A different
    # address mints one by itself (update-agent `callStartUrl`: "a new address creates a
    # new secret").
    rotate = held == wanted
    minted = await vendor.set_call_start(engine_agent_ref, wanted, rotate=rotate)
    if minted is None and not rotate:
        # The address was saved and its secret not shown (the documented 500 case arrives
        # as an error; this is the same outcome on a 2xx). Ask again for a new one.
        rotate = True
        minted = await vendor.set_call_start(engine_agent_ref, wanted, rotate=True)
    if minted is None:
        raise _no_secret_returned()
    await _store_secret(session, engine=engine, engine_agent_ref=engine_agent_ref, secret=minted)
    log.info("engine_call_start_converged", extra={"engine": engine, "rotated": rotate})
    return "rotated" if rotate else "set"


async def ensure_call_start_quietly(
    session: AsyncSession, *, engine: str, engine_agent_ref: str, agent_id: UUID
) -> LookupOutcome | None:
    """`ensure_call_start` for the publish path: a failure is logged, never raised, because
    an agent without a caller lookup still takes every call. None when it failed."""
    try:
        return await ensure_call_start(session, engine=engine, engine_agent_ref=engine_agent_ref)
    except Exception as exc:  # the publish must not fail on an enrichment
        code = exc.code if isinstance(exc, ProblemError) else type(exc).__name__
        log.warning("engine_call_start_not_set", extra={"agent_id": str(agent_id), "reason": code})
        return None


LookupDrift = Literal["in_sync", "repaired", "unchecked"]


async def check_call_start(
    *, tenant_id: UUID, engine: str, engine_agent_ref: str, client: ThinnestActions | None = None
) -> LookupDrift | None:
    """The drift sweep's leg: read `voice.callStartUrl` back and put it right. None when not
    applicable; `unchecked` when the vendor or our settings could not be read."""
    if engine not in LOOKUP_ENGINES:
        return None
    try:
        async with tenant_session(tenant_id) as session:
            outcome = await ensure_call_start(
                session, engine=engine, engine_agent_ref=engine_agent_ref, client=client
            )
    except ProblemError as exc:
        log.info("engine_call_start_check_skipped", extra={"engine": engine, "reason": exc.code})
        return "unchecked"
    if outcome in ("set", "rotated"):
        return "repaired"
    if outcome == "in_sync":
        return "in_sync"
    return "unchecked" if outcome == "no_public_address" else None


__all__ = [
    "AGENT_QUERY_PARAM",
    "LOOKUPS_PATH",
    "LOOKUP_ENGINES",
    "LookupDrift",
    "LookupOutcome",
    "call_start_secret_context",
    "check_call_start",
    "ensure_call_start",
    "ensure_call_start_quietly",
    "lookup_url",
    "open_call_start_secret",
    "read_call_start_secret",
]
