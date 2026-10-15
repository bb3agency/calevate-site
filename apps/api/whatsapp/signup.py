"""Connecting a client's own WhatsApp through Meta's Embedded Signup (D-784).

Calevate is a Meta Tech Provider (founder decision, 15 Oct 2026). The client signs in to
Facebook in Meta's own window on our page, chooses or creates their WhatsApp Business
Account (WABA), verifies their own SIM number with Meta's code, and grants Calevate's app
access. Meta then hands the browser the WABA id, the phone number id and a code; this
module does the rest server to server:

1. exchange the code for the client's BUSINESS TOKEN (the code lives 30 seconds), and seal
   it as their `integration_credentials` row (kind `meta_cloud`), never logged, never shown;
2. record the account (`whatsapp_accounts`);
3. subscribe Calevate's app to the WABA's webhooks;
4. register the number with a fresh 6-digit two-step verification PIN, shown to the owner
   ONCE and never stored (Meta has no API to turn two-step verification off, so the owner
   needs it to ever move the number; two-step-verification.md, read 15 Oct 2026). A number
   on the WhatsApp Business app (coexistence) is already registered and skips this;
5. read the number's display name, quality rating and messaging limit;
6. queue Calevate's standard templates (`templates.seed_standard`, an outbox job).

A step that fails leaves the account `needs_attention` with the step named, and
`finish_setup` re-runs the unfinished steps; nothing is repeated that already succeeded.

WHO PAYS. Meta bills the client's own card, which they add in WhatsApp Manager; "Once your
customer adds a payment method, they are fully onboarded" (onboarding-customers-as-a-tech-
provider.md, Step 5). Calevate adds no mark-up and never sends from its own WABA on a
client's behalf (founder decisions 2 and 8).

THE WEEKLY LIMIT. Meta lets a Tech Provider onboard "up to 10 new business customers in a
rolling 7-day window", 200 after business verification, app review and access verification
(embedded-signup/overview.md). The count is the audit trail of successful connects, which
`audit_log` already holds for every tenant; a new signup is refused before Meta's window
opens once the configured limit is reached, so a client is not sent through a flow Meta
will refuse at the end.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import credentials as creds
from apps.api.actions.oauth import (
    StatePurpose,
    mint_purpose_state,
    spend_purpose_state,
    verify_purpose_state,
)
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox_once
from apps.api.whatsapp import graph

log = get_logger(__name__)

#: The audit action of a successful connect; also what the weekly count reads.
CONNECTED_ACTION: Final = "whatsapp.connected"
SEED_TEMPLATES_JOB: Final = "seed_whatsapp_templates"
ONBOARDING_WINDOW: Final = timedelta(days=7)
#: Alarm when the week's count reaches this share of the limit.
LIMIT_WARNING_SHARE: Final = 0.8

#: Meta's signup is long (sign in, choose a business, verify a number), so the state lives
#: thirty minutes, not OAuth's ten.
SIGNUP_STATE: Final = StatePurpose(
    kind="whatsapp_signup",
    label="WhatsApp",
    audience="calevate:whatsapp-signup-state",
    kdf_info=b"calevate:whatsapp-signup-state:v1",
    ttl=timedelta(minutes=30),
)

#: The `event` values Embedded Signup's session logging reports on success
#: (embedded-signup/implementation.md, read 15 Oct 2026), and what each means to us.
FINISH_EVENTS: Final[dict[str, str]] = {
    "FINISH": "new",
    "FINISH_ONLY_WABA": "new",
    "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING": "business_app",
    "FINISH_GRANT_ONLY_API_ACCESS": "grant_access",
}

Choice = Literal["new", "business_app", "grant_access"]


@dataclass(frozen=True, slots=True)
class SignupSetup:
    """What the client's screen needs to open Meta's window, or why it cannot."""

    available: bool
    #: Why not, as a code the screen maps to words: `not_configured`, `weekly_limit`.
    reason: str | None
    app_id: str | None
    config_id: str | None
    graph_version: str
    coexistence: bool
    week_count: int
    weekly_limit: int


def _configured() -> bool:
    s = get_settings()
    return bool(s.meta_app_id and s.whatsapp_signup_config_id and s.meta_app_secret)


async def onboardings_this_week(session: AsyncSession) -> int:
    """Successful connects across every client in the last 7 days. `audit_log` is the one
    table every session can read across tenants (`RLS_EXEMPT_TENANT_COLUMNS`)."""
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = :action "
                    "AND at > now() - make_interval(days => 7)"
                ),
                {"action": CONNECTED_ACTION},
            )
        ).scalar_one()
    )


async def signup_setup(session: AsyncSession) -> SignupSetup:
    s = get_settings()
    from apps.api.actions.whatsapp import META_GRAPH_VERSION

    week = await onboardings_this_week(session)
    configured = _configured()
    at_limit = week >= s.whatsapp_onboarding_weekly_limit
    reason = (
        None
        if configured and not at_limit
        else ("not_configured" if not configured else "weekly_limit")
    )
    return SignupSetup(
        available=reason is None,
        reason=reason,
        app_id=s.meta_app_id if configured else None,
        config_id=s.whatsapp_signup_config_id if configured else None,
        graph_version=META_GRAPH_VERSION,
        coexistence=configured and s.whatsapp_coexistence_enabled,
        week_count=week,
        weekly_limit=s.whatsapp_onboarding_weekly_limit,
    )


def signup_unavailable(reason: str) -> ProblemError:
    if reason == "weekly_limit":
        return ProblemError.business_rule(
            "whatsapp_signup_weekly_limit",
            "Meta lets us connect a limited number of new WhatsApp accounts each week, and "
            "this week's are used.",
            remediation="Try again in a few days, or connect with a key from your provider.",
        )
    return ProblemError.business_rule(
        "whatsapp_signup_not_configured",
        "Connecting WhatsApp through Meta is not switched on yet.",
        remediation="Use a key from your WhatsApp provider for now.",
    )


def state_refused() -> ProblemError:
    return ProblemError(
        kind="permission",
        code="whatsapp_signup_state_invalid",
        title="This WhatsApp connection was not started here",
        detail="The connection did not start on this screen, or it took longer than 30 minutes.",
        remediation="Press Connect WhatsApp and go through Meta's window again.",
    )


async def start(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID
) -> tuple[SignupSetup, str]:
    setup = await signup_setup(session)
    if not setup.available:
        raise signup_unavailable(setup.reason or "not_configured")
    return setup, mint_purpose_state(SIGNUP_STATE, tenant_id=tenant_id, user_id=user_id)


@dataclass(frozen=True, slots=True)
class ConnectIn:
    state: str
    code: str
    event: str
    waba_id: str
    phone_number_id: str | None
    business_id: str | None


@dataclass(slots=True)
class ConnectOutcome:
    account_id: UUID
    status: str
    #: The two-step verification PIN, set now and shown once. None when not set.
    pin: str | None = None
    failed_step: str | None = None
    steps: dict[str, bool] = field(default_factory=dict)


def _digits(value: str | None, *, what: str) -> str | None:
    if value is None or value == "":
        return None
    if not value.isdigit() or len(value) > 64:
        raise ProblemError(
            kind="validation",
            code="whatsapp_signup_bad_id",
            title="Meta's answer could not be read",
            detail=f"The {what} Meta returned is not in the expected form.",
            remediation="Press Connect WhatsApp and try again.",
        )
    return value


def new_pin() -> str:
    """Six digits, never all one digit (Meta's own two-step PIN form refuses a trivial PIN in
    the app; the API states only "a 6-digit number")."""
    while True:
        pin = f"{secrets.randbelow(10**6):06d}"
        if len(set(pin)) > 1:
            return pin


async def _record_account(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    credential_id: UUID,
    waba_id: str,
    phone_number_id: str | None,
    business_id: str | None,
    onboarding: str,
) -> UUID:
    account_id = uuid7()
    try:
        async with session.begin_nested():
            await session.execute(
                text(
                    "INSERT INTO whatsapp_accounts (id, tenant_id, credential_id, waba_id, "
                    "phone_number_id, business_id, onboarding, status, created_at, updated_at) "
                    "VALUES (:id, :tid, :cid, :waba, :pnid, :bid, :onb, 'connecting', now(), now())"
                ),
                {
                    "id": account_id,
                    "tid": tenant_id,
                    "cid": credential_id,
                    "waba": waba_id,
                    "pnid": phone_number_id,
                    "bid": business_id,
                    "onb": onboarding,
                },
            )
    except IntegrityError as exc:
        # `ux_whatsapp_accounts_live_waba`: this WABA is live on an account (this one's, or
        # another client's). Refused in the same words either way.
        raise ProblemError.conflict(
            "whatsapp_account_already_connected",
            "This WhatsApp account is already connected to Calevate.",
        ) from exc
    return account_id


async def run_setup_steps(
    session: AsyncSession,
    *,
    account_id: UUID,
    token: str,
    waba_id: str,
    phone_number_id: str | None,
    onboarding: str,
    registered: bool,
    subscribed: bool,
) -> ConnectOutcome:
    """Subscribe, register, read the number. Each step that already succeeded is skipped."""
    outcome = ConnectOutcome(account_id=account_id, status="connected")
    try:
        if not subscribed:
            await graph.subscribe_app(waba_id=waba_id, token=token)
            await session.execute(
                text("UPDATE whatsapp_accounts SET webhooks_subscribed = true WHERE id = :id"),
                {"id": account_id},
            )
        outcome.steps["webhooks"] = True
        if phone_number_id is None:
            phone_number_id = await graph.first_phone_number_id(waba_id=waba_id, token=token)
            if phone_number_id is None:
                raise graph.GraphError("phone_list", status=200, meta_code=None)
            await session.execute(
                text("UPDATE whatsapp_accounts SET phone_number_id = :p WHERE id = :id"),
                {"id": account_id, "p": phone_number_id},
            )
        if onboarding == "business_app" or registered:
            outcome.steps["registered"] = True
        else:
            pin = new_pin()
            await graph.register_number(phone_number_id=phone_number_id, token=token, pin=pin)
            await session.execute(
                text("UPDATE whatsapp_accounts SET registered = true WHERE id = :id"),
                {"id": account_id},
            )
            outcome.pin = pin
            outcome.steps["registered"] = True
        info = await graph.phone_info(phone_number_id=phone_number_id, token=token)
        await session.execute(
            text(
                "UPDATE whatsapp_accounts SET display_phone_number = :dpn, verified_name = :vn, "
                "quality_rating = :qr, name_status = :ns, messaging_limit = :ml, "
                "status = 'connected', setup_error = NULL, "
                "connected_at = COALESCE(connected_at, now()), updated_at = now() WHERE id = :id"
            ),
            {
                "id": account_id,
                "dpn": info.display_phone_number,
                "vn": info.verified_name,
                "qr": info.quality_rating,
                "ns": info.name_status,
                "ml": info.messaging_limit,
            },
        )
        outcome.steps["number"] = True
    except graph.GraphError as exc:
        outcome.status = "needs_attention"
        outcome.failed_step = exc.step
        await session.execute(
            text(
                "UPDATE whatsapp_accounts SET status = 'needs_attention', setup_error = :err, "
                "updated_at = now() WHERE id = :id"
            ),
            {"id": account_id, "err": exc.code},
        )
        log.warning(
            "whatsapp_setup_step_failed",
            extra={"account_id": str(account_id), "step": exc.step, "meta_code": exc.meta_code},
        )
    return outcome


async def connect(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, payload: ConnectIn
) -> ConnectOutcome:
    """Finish one Embedded Signup. The code is exchanged before any other network call: it
    expires 30 seconds after Meta issues it."""
    jti = verify_purpose_state(
        SIGNUP_STATE, payload.state, tenant_id=tenant_id, user_id=user_id, refusal=state_refused()
    )
    await spend_purpose_state(SIGNUP_STATE, jti, refusal=state_refused())
    onboarding = FINISH_EVENTS.get(payload.event)
    if onboarding is None:
        raise ProblemError(
            kind="validation",
            code="whatsapp_signup_not_finished",
            title="Meta's window did not finish",
            detail="WhatsApp was not connected because Meta's window closed before the end.",
            remediation="Press Connect WhatsApp and go through every step in Meta's window.",
        )
    if not _configured():
        raise signup_unavailable("not_configured")
    waba_id = _digits(payload.waba_id, what="account id") or ""
    if not waba_id:
        raise ProblemError.business_rule(
            "whatsapp_signup_bad_id", "Meta did not return a WhatsApp account id."
        )
    phone_number_id = _digits(payload.phone_number_id, what="phone number id")
    business_id = _digits(payload.business_id, what="business id")
    s = get_settings()
    token = await graph.exchange_code(
        app_id=str(s.meta_app_id), app_secret=str(s.meta_app_secret), code=payload.code
    )
    credential = await creds.create_credential(
        session,
        tenant_id=tenant_id,
        kind="meta_cloud",
        label="WhatsApp (connected through Meta)",
        secret=token,
        non_secret={
            "waba_id": waba_id,
            "phone_number_id": phone_number_id,
            "business_id": business_id,
            "connected_via": "embedded_signup",
        },
    )
    account_id = await _record_account(
        session,
        tenant_id=tenant_id,
        credential_id=credential.id,
        waba_id=waba_id,
        phone_number_id=phone_number_id,
        business_id=business_id,
        onboarding=onboarding,
    )
    outcome = await run_setup_steps(
        session,
        account_id=account_id,
        token=token,
        waba_id=waba_id,
        phone_number_id=phone_number_id,
        onboarding=onboarding,
        registered=False,
        subscribed=False,
    )
    if outcome.status == "connected":
        await queue_templates(session, account_id=account_id, tenant_id=tenant_id)
    await _warn_if_near_limit(session)
    return outcome


async def queue_templates(session: AsyncSession, *, account_id: UUID, tenant_id: UUID) -> None:
    await enqueue_outbox_once(
        session,
        job=SEED_TEMPLATES_JOB,
        payload={"tenant_id": str(tenant_id), "account_id": str(account_id)},
        dedupe_key=f"whatsapp-templates:{account_id}",
    )


async def _warn_if_near_limit(session: AsyncSession) -> None:
    limit = get_settings().whatsapp_onboarding_weekly_limit
    # +1: this connect's audit row is written by the route after this returns.
    week = await onboardings_this_week(session) + 1
    if week >= limit * LIMIT_WARNING_SHARE:
        alert(
            "CORE_LOGIC",
            "whatsapp_onboarding_limit_near",
            detail=(
                f"{week} of {limit} new WhatsApp connections in the last 7 days. Meta refuses "
                "signups past its limit; raise it by completing Meta's verifications "
                "(runbooks/whatsapp-tech-provider.md) and the console setting."
            ),
        )


__all__ = [
    "CONNECTED_ACTION",
    "FINISH_EVENTS",
    "SEED_TEMPLATES_JOB",
    "SIGNUP_STATE",
    "ConnectIn",
    "ConnectOutcome",
    "SignupSetup",
    "connect",
    "new_pin",
    "onboardings_this_week",
    "queue_templates",
    "run_setup_steps",
    "signup_setup",
    "signup_unavailable",
    "start",
    "state_refused",
]
