"""The payment capability, as something the codebase can SAY rather than only lack.

SURFACES §2c:205 documents server-side Razorpay order creation as NOT IMPLEMENTED
because this deployment holds no credentials, and that honesty is correct and stays:
`provider_order_id` is null, `provider_order_pending` is true, and `billing/payments.py`
still marks every unverified assumption about the vendor's signing scheme and payload
shape. What was wrong is that nothing could answer "does this deployment take
payments?" — each caller read `settings.razorpay_key_id` and decided for itself, which
is the defect fixed for Google Sheets last wave (`tests/sheets_endpoint_test.py`).

So these tests hold the payment surfaces to the rule that refusal implies:

1. **The seam decides, not a credential.** `PAYMENT_PROVIDER` is the statement; a named
   provider with no adapter refuses loudly; unset means this deployment takes no online
   payments.
2. **One selector, so two surfaces cannot disagree.** The intent route and the webhook
   both go through `payment_capability()`, and a deployment that could take money but
   never credit it (key id, no webhook secret) is refused on BOTH.
3. **A refusal writes nothing** — no receipt, no inbox claim, no ledger row — and it is
   RFC-9457 with the machine code as the LAST SEGMENT of `type`.
4. **The order-creation adapter exists and the CREDENTIAL still does not** (D-98).
   `PROVIDER_CREATES_ORDERS` is True because somebody wrote `RazorpayOrders.create_order`;
   `capability.creates_orders` is False on every deployment because no Razorpay account
   has been provisioned. This file pins both halves, so neither can drift into the other.
5. **No vendor library, no invented shapes.** The lockfile has no Razorpay client and no
   HTTP call is made from any payment path.

CONCURRENCY: every test mints its own tenant and mutates only the process settings
object through `monkeypatch`, which pytest restores per test.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.payment_routes import TopUpIntentIn, create_topup_intent
from apps.api.billing.payments import (
    NO_API_SECRET_REASON,
    NO_KEY_REASON,
    NO_PROVIDER_REASON,
    NO_WEBHOOK_SECRET_REASON,
    PROVIDER,
    PROVIDER_CREATES_ORDERS,
    PROVIDER_NOT_IMPLEMENTED_REASON,
    online_payments_available,
    payment_capability,
)
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from calevate_shared.config import Settings
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parent.parent


def _payments_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that CAN take payments: a provider name with an adapter behind it
    and both credentials present. Test values — they name no real account."""
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", PROVIDER)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_seamcheck")
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec_seamcheck")


async def _prepaid_tenant() -> tuple[UUID, Principal]:
    created = await admin_service.create_organization(
        name="Seam Clinic",
        slug=f"seam-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :t"),
            {"t": tenant_id},
        )
    return tenant_id, Principal(
        realm="client",
        user_id=uuid.uuid4(),
        clerk_user_id="u",
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )


# ============================================================================
# 1. The seam decides
# ============================================================================


def test_the_setting_exists_and_is_declared_in_env_parity() -> None:
    """The claim is DISCOVERABILITY, and its home moved (PLATFORM-CONFIG §4, D-95).

    This used to read `.env.example`, which was the only place a key could be declared.
    The template is now the 8-key bootstrap set, and `payment_provider` is one of the 50
    keys an operator sets at `admin.calevate.tech/ops` instead — so the check that keeps
    the original meaning is "the console offers it", which is also the exact condition
    `check_env_parity` treats as declared.
    """
    from apps.api.core.platform_config import managed_fields

    assert "payment_provider" in Settings.model_fields
    assert "payment_provider" in managed_fields()


def test_no_provider_means_this_deployment_takes_no_online_payments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The DEFAULT, and the truth today. A key id sitting in the environment is not a
    statement that the capability exists."""
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", None)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_leftover")
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec_leftover")

    capability = payment_capability()
    assert capability.available is False
    assert capability.reason == NO_PROVIDER_REASON
    assert online_payments_available() is False


def test_a_named_provider_with_no_adapter_refuses_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`PAYMENT_PROVIDER=stripe` today must fail rather than look configured — the exact
    rule `sheets_sync.get_sheets_transport` applies to an unknown Sheets provider."""
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", "stripe")
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_x")
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec_x")

    capability = payment_capability()
    assert capability.available is False
    assert capability.reason == f"{PROVIDER_NOT_IMPLEMENTED_REASON}:stripe", (
        "the reason names which provider was expected, and the name is OUR config"
    )


@pytest.mark.parametrize(
    ("missing", "expected"),
    [("razorpay_key_id", NO_KEY_REASON), ("razorpay_webhook_secret", NO_WEBHOOK_SECRET_REASON)],
)
def test_a_known_provider_still_needs_both_credentials(
    monkeypatch: pytest.MonkeyPatch, missing: str, expected: str
) -> None:
    """Both together, on purpose. A key id with no webhook secret is a deployment that
    could take a client's money and could never credit their wallet — the worst of the
    three states, and the one a per-surface check would have allowed."""
    _payments_configured(monkeypatch)
    monkeypatch.setattr(get_settings(), missing, None)

    capability = payment_capability()
    assert capability.available is False and capability.reason == expected


def test_a_fully_configured_deployment_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _payments_configured(monkeypatch)
    capability = payment_capability()
    assert capability.available is True
    assert capability.provider == PROVIDER
    assert capability.reason is None
    assert online_payments_available() is True


# ============================================================================
# 2 + 3. One selector, and a refusal that writes nothing
# ============================================================================


async def test_the_intent_refuses_in_problem_json_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, principal = await _prepaid_tenant()
    monkeypatch.setattr(get_settings(), "payment_provider", None)

    with pytest.raises(ProblemError) as raised:
        await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("2500.00")), principal)

    problem = raised.value.as_problem("/v1/billing/topups/intent")
    assert problem["type"].rsplit("/", 1)[-1] == "payments_not_configured"
    assert "code" not in problem, "RFC-9457 carries the machine code in `type`"
    # Our authored config state is logged, never returned: a client cannot act on
    # "no_webhook_secret" and naming our missing secret is an internals leak.
    assert NO_PROVIDER_REASON not in str(problem)

    async with tenant_session(tenant_id) as session:
        entries = (
            await session.execute(
                text("SELECT count(*) FROM credit_ledger WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
    assert entries == 0, "a refused intent leaves no ledger row"


async def test_the_intent_succeeds_once_the_seam_says_the_deployment_has_payments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _payments_configured(monkeypatch)
    _tenant_id, principal = await _prepaid_tenant()

    intent = await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("2500.00")), principal)
    assert intent.amount_inr == Decimal("2500.00")
    assert intent.amount_paise == 250000, "an integer count of paise, never a float"
    assert intent.key_id == "rzp_test_seamcheck"
    assert intent.notes["calevate_tenant_id"] == str(principal.tenant_id)


async def test_the_webhook_refuses_on_the_same_selector_the_intent_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deployment that could take money and never credit it, asserted from the
    OTHER side: a key id with no webhook secret refuses the receiver too, so a payment
    can never be taken by a deployment that would drop the callback."""
    from apps.api.billing.payment_routes import razorpay_webhook
    from starlette.requests import Request

    _payments_configured(monkeypatch)
    monkeypatch.setattr(get_settings(), "razorpay_webhook_secret", None)

    async def _receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/hooks/v1/razorpay",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
        },
        receive=_receive,  # type: ignore[arg-type]
    )
    with pytest.raises(ProblemError) as raised:
        await razorpay_webhook(request)
    assert raised.value.code == "payments_not_configured"


# ============================================================================
# 4. The order-creation gap stays in the contract
# ============================================================================


async def test_the_intent_still_says_the_provider_order_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SURFACES §2c:205's contract, unchanged — but for a NAMED reason now.

    A deployment with a provider, a key id and a webhook secret still cannot create an
    order, because the API SECRET is a fourth credential and no Razorpay account has been
    provisioned. The property: `available` is not pulled down by that (a deployment can
    still credit payments taken elsewhere), and `creates_orders` says so on its own.
    """
    _payments_configured(monkeypatch)
    _tenant_id, principal = await _prepaid_tenant()

    capability = payment_capability()
    assert capability.available is True, "the ORDER credential must not refuse the webhook"
    assert capability.creates_orders is False
    assert capability.orders_reason == NO_API_SECRET_REASON

    intent = await create_topup_intent(TopUpIntentIn(amount_inr=Decimal("500.00")), principal)
    assert intent.provider_order_id is None
    assert intent.provider_order_pending is True


def test_the_order_creation_constant_is_true_only_while_the_adapter_exists() -> None:
    """`PROVIDER_CREATES_ORDERS` is a claim about CODE, not about config (D-98).

    It flipped to True because `RazorpayOrders.create_order` was written. This is the
    tripwire in the other direction now: the constant may not claim an adapter that is
    not there, so the module must still contain a real HTTP POST to a real pinned host.
    """
    assert PROVIDER_CREATES_ORDERS is True
    payments = (REPO_ROOT / "apps/api/billing/payments.py").read_text(encoding="utf-8")
    assert "https://api.razorpay.com" in payments, "the constant claims an adapter"
    assert "client.post(" in payments, "the adapter must actually issue the request"


def test_the_api_version_is_pinned_rather_than_inherited() -> None:
    """An unpinned version is a silent breaking change on somebody else's release
    schedule. Razorpay versions in the PATH — their own SDK carries both `V1` and `V2` —
    so the pin is a constant in our module and the request is built from it."""
    from apps.api.billing.payments import API_VERSION_PATH, BASE_URL, ORDERS_PATH

    assert API_VERSION_PATH == "/v1"
    assert BASE_URL == "https://api.razorpay.com"
    assert f"{BASE_URL}{API_VERSION_PATH}{ORDERS_PATH}" == "https://api.razorpay.com/v1/orders"


# ============================================================================
# 5. No vendor library was added (hard rule 9)
# ============================================================================


def test_no_razorpay_client_library_entered_the_lockfile() -> None:
    """Adding a vendor SDK on a guess is the supply-chain move hard rule 9 forbids, and
    the seam exists precisely so the capability can be expressed without one."""
    lock = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "razorpay"' not in lock
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "razorpay" not in pyproject
