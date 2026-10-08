"""Per-agent engine webhook endpoints: registered at publish, kept switched on (D-678).

ThinnestAI delivers `call.completed` / `call.analysed` / `contact.opted_out` to an endpoint
registered per agent, returns its signing secret ONCE, retries a failed attempt on a fixed
schedule, and switches the endpoint off after five events in a row that failed every attempt
(`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/webhooks.md:36-40,
:110-117, :149-155`). So one function answers "make this agent's endpoint exist, be ours,
and be on", and both callers use it: the publish path (`ensure_agent_webhook`) and the sweep
(`apps/workers/engine_webhooks.py`).

WHY A REPUBLISH CANNOT DUPLICATE. The endpoint id and its sealed secret live on the
agent's `engine_agent_routes` row, read `FOR UPDATE`; a row that already holds an endpoint
is checked, not re-created. A secret lost between `POST /webhooks` and our commit cannot be
recovered (the vendor shows it once), so an endpoint at our url that we hold no secret for
is deleted and replaced rather than kept unverifiable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import urlencode

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings, is_public_callback_base
from apps.api.engine.thinnest_webhooks import (
    AGENT_QUERY_PARAM,
    SUBSCRIBED_EVENTS,
    ThinnestWebhooks,
    WebhookEndpoint,
    thinnest_webhooks,
)
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.reliability.engine_intake_keys import seal_webhook_secret

log = get_logger(__name__)

THINNEST: Final = "thinnest"

#: Engines whose deliveries are signed with a per-agent endpoint secret we must register.
WEBHOOK_ENGINES: Final = frozenset({THINNEST})

WebhookOutcome = Literal[
    "not_applicable", "registered", "replaced", "healthy", "reenabled", "resubscribed"
]


@dataclass(frozen=True, slots=True)
class WebhookRegistration:
    outcome: WebhookOutcome
    webhook_id: str | None = None


def agent_webhook_url(engine: str, engine_agent_ref: str) -> str:
    """The voice-runtime receiver, naming the agent whose secret signs the delivery."""
    base = (get_settings().webhook_base_url or "").strip().rstrip("/")
    query = urlencode({AGENT_QUERY_PARAM: engine_agent_ref})
    return f"{base}/hooks/v1/engine/{engine}?{query}"


def _refuse_private_base() -> None:
    # `url` must be `https://` and "addresses inside our own network are refused"
    # (webhooks.md:61-64): refuse here with our sentence rather than relay their 400.
    if not is_public_callback_base(get_settings().webhook_base_url):
        raise ProblemError(
            kind="validation",
            code="engine_webhook_url_not_public",
            title="The webhook address is not reachable from the internet",
            detail="WEBHOOK_BASE_URL must be a public, secure address before agents publish.",
            remediation=(
                "Set WEBHOOK_BASE_URL to the voice-runtime's public secure address, "
                "such as hooks.calevate.tech, and publish again."
            ),
        )


def _is_absent(exc: EngineRejectedError) -> bool:
    return exc.vendor_status == 404


async def _held_endpoint(
    session: AsyncSession, engine: str, engine_agent_ref: str
) -> tuple[bool, str | None]:
    """(route exists, webhook id held). Locks the row so two publishes cannot both register."""
    row = (
        await session.execute(
            text(
                "SELECT webhook_id FROM engine_agent_routes "
                "WHERE engine = :engine AND engine_agent_ref = :ref FOR UPDATE"
            ),
            {"engine": engine, "ref": engine_agent_ref},
        )
    ).first()
    if row is None:
        return False, None
    return True, row[0]


async def _store(
    session: AsyncSession, *, engine: str, engine_agent_ref: str, webhook_id: str, secret: str
) -> None:
    envelope = seal_webhook_secret(secret, engine=engine, engine_agent_ref=engine_agent_ref)
    await session.execute(
        text(
            "UPDATE engine_agent_routes SET webhook_id = :wid, "
            "webhook_secret_ciphertext = :ct, webhook_secret_nonce = :n, "
            "webhook_secret_dek_wrapped = :dw, webhook_secret_dek_nonce = :dn, "
            "webhook_secret_kek_version = :kek, webhook_checked_at = now(), updated_at = now() "
            "WHERE engine = :engine AND engine_agent_ref = :ref"
        ),
        {
            "wid": webhook_id,
            "ct": envelope.ciphertext,
            "n": envelope.nonce,
            "dw": envelope.dek_wrapped,
            "dn": envelope.dek_nonce,
            "kek": envelope.kek_id,
            "engine": engine,
            "ref": engine_agent_ref,
        },
    )


async def _mark_checked(session: AsyncSession, engine: str, engine_agent_ref: str) -> None:
    await session.execute(
        text(
            "UPDATE engine_agent_routes SET webhook_checked_at = now() "
            "WHERE engine = :engine AND engine_agent_ref = :ref"
        ),
        {"engine": engine, "ref": engine_agent_ref},
    )


async def _register(
    session: AsyncSession, client: ThinnestWebhooks, *, engine: str, engine_agent_ref: str, url: str
) -> str:
    """Delete every endpoint at OUR url for this agent (we hold no secret for any of them),
    then create one and store its secret sealed."""
    for orphan in await client.list_for_agent(engine_agent_ref):
        if orphan.url == url:
            await client.delete(orphan.webhook_id)
    created = await client.create(engine_agent_ref=engine_agent_ref, url=url)
    await _store(
        session,
        engine=engine,
        engine_agent_ref=engine_agent_ref,
        webhook_id=created.endpoint.webhook_id,
        secret=created.signing_secret,
    )
    return created.endpoint.webhook_id


async def ensure_agent_webhook(
    session: AsyncSession,
    *,
    engine: str,
    engine_agent_ref: str,
    client: ThinnestWebhooks | None = None,
) -> WebhookRegistration:
    """Make this agent's endpoint exist, point at our receiver, and be switched on.

    Call it in the SAME tenant session that wrote the agent's `engine_agent_routes` row, after
    that write. A no-op (`not_applicable`) for an engine that does not sign per endpoint, so
    the publish path may call it for every engine.

    `reenabled` means the vendor had switched the endpoint off — deliveries were being lost —
    and the caller decides how loud that is (the sweep alarms on it).
    """
    if engine not in WEBHOOK_ENGINES:
        return WebhookRegistration(outcome="not_applicable")
    exists, held = await _held_endpoint(session, engine, engine_agent_ref)
    if not exists:
        raise ProblemError(
            kind="conflict",
            code="engine_route_absent",
            title="The agent has no engine route yet",
            detail="The webhook endpoint is registered against the agent's engine route.",
            remediation="Save the agent's engine route in this same transaction first.",
        )
    _refuse_private_base()
    url = agent_webhook_url(engine, engine_agent_ref)
    webhooks = client or thinnest_webhooks()

    if held is None:
        webhook_id = await _register(
            session, webhooks, engine=engine, engine_agent_ref=engine_agent_ref, url=url
        )
        log.info("engine_webhook_registered", extra={"engine": engine, "webhook_id": webhook_id})
        return WebhookRegistration(outcome="registered", webhook_id=webhook_id)

    current: WebhookEndpoint | None
    try:
        current = await webhooks.get(held)
    except EngineRejectedError as exc:
        if not _is_absent(exc):
            raise
        current = None
    if current is None or current.url != url:
        # Deleted on their side, or registered under a WEBHOOK_BASE_URL we no longer use.
        if current is not None:
            await webhooks.delete(current.webhook_id)
        webhook_id = await _register(
            session, webhooks, engine=engine, engine_agent_ref=engine_agent_ref, url=url
        )
        log.warning(
            "engine_webhook_replaced",
            extra={"engine": engine, "webhook_id": webhook_id, "was": held},
        )
        return WebhookRegistration(outcome="replaced", webhook_id=webhook_id)
    # An endpoint registered before a subscription was added (D-691 added
    # `contact.opted_out`) is brought up to date in place: re-creating it would rotate a
    # secret for no reason. `("*",)` is every event, which includes ours.
    resubscribed = current.events not in (SUBSCRIBED_EVENTS, ("*",))
    if resubscribed:
        await webhooks.subscribe(held, SUBSCRIBED_EVENTS)
    if not current.enabled:
        await webhooks.enable(held)
        await _mark_checked(session, engine, engine_agent_ref)
        return WebhookRegistration(outcome="reenabled", webhook_id=held)
    await _mark_checked(session, engine, engine_agent_ref)
    return WebhookRegistration(
        outcome="resubscribed" if resubscribed else "healthy", webhook_id=held
    )


__all__ = [
    "THINNEST",
    "WEBHOOK_ENGINES",
    "WebhookOutcome",
    "WebhookRegistration",
    "agent_webhook_url",
    "ensure_agent_webhook",
]
