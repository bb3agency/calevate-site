"""Razorpay prepaid top-ups — the half of the integration that is OURS (D-34/D-98).

The self-serve motion needs a way to pay that does not involve someone in ops reading
a UTR off a bank statement (`billing/credit_routes.py`, which stays exactly as it is
for NEFT/UPI). This module is the machine version of that same act: a payment the
provider tells us about becomes one `credit_ledger` entry.

WHAT IS REAL HERE AND WHAT IS NOT — read this before wiring it to a live account
--------------------------------------------------------------------------------
There are still no Razorpay credentials in this repository and **no call has ever been
made against their API from here**. What changed in D-98 is the EVIDENCE, not the
account: `github.com/razorpay/razorpay-python` is Razorpay's own published client, and
reading it settles several things that were previously guesses. So this module now uses
the three-rung ladder `apps/api/engine/cartesia.py` established, cited at the line:

* **READ AT SOURCE** — taken from `razorpay/razorpay-python` on `master`, fetched
  2026-08-14. Vendor-published code, so it is strong evidence about the things it
  actually touches: the API host, the version path segment, the orders path, the
  authentication scheme, the webhook digest.
* **REPORTED, NOT READ** — a search engine's summary of a `razorpay.com/docs` page.
  Weaker: **`razorpay.com` is refused by this environment's egress proxy (WebFetch →
  EGRESS_BLOCKED), so nobody here has seen those pages.** Same standing the Bolna
  adapter gives `GET /v2/agent/{agent_id}`.
* **UNVERIFIED** — our reading with nothing behind it. Every one of these fails LOUDLY
  and credits nothing.

The two long-standing marks, restated at their new standing:

- `verify_signature` — the SCHEME is now **READ AT SOURCE**: `razorpay/utility/
  utility.py::verify_signature` is `hmac.new(key=secret, msg=body,
  digestmod=hashlib.sha256).hexdigest()` compared with `hmac.compare_digest`, and
  `verify_webhook_signature(body, signature, secret)` delegates straight to it. That is
  exactly what is implemented below. The **HEADER NAME remains UNVERIFIED** — their SDK
  takes the signature as an argument and never names a header, so `X-Razorpay-Signature`
  is still our reading. Wrong header ⇒ every event refused (fail-closed).
- `extract_captured_payment` — the payload shape: `event`, and
  `payload.payment.entity.{id,amount,currency,notes}` with `amount` an integer count
  of PAISE. **UNVERIFIED** — webhook payloads are not in their Python SDK. If a field
  name is wrong the extractor returns nothing we can act on and the receiver answers 422
  without touching the ledger.

ORDER CREATION IS NOW IMPLEMENTED (D-98) — and the credential still is not
--------------------------------------------------------------------------
`RazorpayOrders.create_order` is a real server-to-server `POST /v1/orders`. Two facts
stay separate, because conflating them is the defect this module was built to avoid:

- `PROVIDER_CREATES_ORDERS` is a claim about CODE: an adapter exists in this repository.
  It is now True, and it became True because somebody wrote the adapter.
- `PaymentCapability.creates_orders` is a claim about THIS DEPLOYMENT: the adapter
  exists AND the API secret is configured. **It is False on every deployment today**,
  with reason `no_api_secret`, because no Razorpay account has been provisioned — so
  `create_topup_intent` still answers `provider_order_id: null` /
  `provider_order_pending: true` exactly as it did, and does so through a named reason
  rather than through an absence.

WHY BOTHER, IF NOBODY CAN PAY YET — the concrete thing this fixes
-----------------------------------------------------------------
`notes.calevate_tenant_id` is the ONLY way the receiver can attribute a payment, and
until now the intent merely HANDED those notes to a frontend and hoped a checkout
attached them. A checkout that forgot would put every rupee through
`payment_tenant_unresolved` — real money nobody can place. Creating the order
server-side puts the tenant into the order by construction, which is the difference
between a contract and a hope.

**No Razorpay client library is added** (hard rule 9). The adapter is `httpx` against
paths read out of their own SDK; adding `razorpay` to the lockfile would be a
supply-chain decision buying nothing but four constants we can read for free.

THE CAPABILITY IS NOW SOMETHING THE CODE CAN SAY, NOT ONLY SOMETHING IT LACKS
------------------------------------------------------------------------------
The honest hole above was right and it stays. What was wrong is that nothing in the
codebase could ANSWER "does this deployment take payments?" — every caller read
`settings.razorpay_key_id` and decided for itself, which is the defect fixed for Google
Sheets last wave (`workers/sheets_sync.py`, `integrations/routes.py`): a key id is a
credential, not a statement that the capability exists, and two independent reads of
the same settings eventually disagree. So, exactly as there:

- `PAYMENT_PROVIDER` is the statement. The only name with anything behind it is
  `razorpay`; any other name resolves to `provider_not_implemented`, on purpose, so
  `PAYMENT_PROVIDER=stripe` fails loudly rather than looking configured.
- `payment_capability()` is the ONE selector, and `online_payments_available()` is the
  boolean every caller asks — the intent route, the webhook, and any surface that later
  wants to decide whether to render a pay button. A second read of settings cannot
  disagree with it because there is no second read.
- the refusal is RFC-9457 problem+json and writes NOTHING — no intent row, no inbox
  claim, no ledger entry.
- `PROVIDER_CREATES_ORDERS` is a greppable constant rather than a note in a doc,
  because "we have credentials" and "we have an order-creation adapter" are different
  facts and the contract must not conflate them.
  `tests/payments_provider_seam_test.py` pins BOTH halves: that the constant is True
  only while a real HTTP order call is present in this module, and that the capability
  is still False without the secret.

WHAT IS OURS, AND IS FINISHED
-----------------------------
- **Idempotency on the provider's payment id.** Every payment provider replays: on
  their retry schedule, on our 5xx, and on a manual redelivery from their dashboard.
  The permanent key for "this money arrived once" is the payment id, so it is the
  ledger's `ref` — the same argument `credit_routes` makes about a bank UTR, and the
  same one `charge_for_call` makes about a call id. A `webhook_inbox_events` claim
  sits in front of it as a cheap first line, but the inbox is not the guarantee: it is
  keyed per delivery and can be swept, while a ledger row is forever.
- **The lock is taken before the lookup.** `lock_tenant_credits` covers the whole
  check-then-write, because two concurrent deliveries of one payment would otherwise
  both read "not credited yet" and both append (billing/service.py's module docstring
  spells out why a row lock is not a substitute). The lookup itself is
  `billing.service.find_topup`, which takes that same lock a second time rather than
  trusting its caller to have taken it first — one query, one lock discipline, shared
  with the manual UTR route.
- **`record_entry` is the only writer.** No hand-rolled INSERT: append-only,
  balance-carrying and audited is a property of that function, not of this one.
- **Money is Decimal end to end** (hard rule 7), in BOTH directions, through exactly two
  functions: `paise_to_inr` inbound and `inr_to_paise` outbound. Neither rounds. Paise
  are divided by an integer 100 in Decimal arithmetic, which is exact; rupees are
  multiplied by it and REFUSED if the product has a fractional part. A float on either
  path is refused, never rounded — `2500.10` through a binary float and back is how a
  paise-level dispute starts.
- **The intent is idempotent on a key WE derive** (`topup_receipt`), not on a header the
  browser chooses, so a second click cannot mint a second order. The argument, and why
  it is not a third answer, is on that function.

Deliberately NOT here: a `payment_orders` table. D-39's rule is that anything needing
a migration later is built now — and this flow still needs no such row. The order id is
replayed out of `idempotency_records`, which is the table this repository already keeps
for "the same client-initiated mutation, twice"; the signature proves the callback is
genuine; the notes carry the tenant; and the ledger is the durable record of money.
Adding a table would add a second place a payment can be half-recorded, and the thing it
would hold — an unpaid order id — is worth less than the row it costs.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.credit_packs import (
    PACK_BONUS_META_KIND,
    CreditPack,
    pack_by_id,
)
from apps.api.billing.service import (
    Balance,
    find_entry_by_ref,
    find_topup,
    get_balance,
    lock_tenant_credits,
    record_entry,
    to_paise,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.reliability.service import body_hash

log = get_logger(__name__)

PROVIDER: Final = "razorpay"

# UNVERIFIED (see module docstring): the header Razorpay is understood to sign with.
SIGNATURE_HEADER: Final = "X-Razorpay-Signature"

# The only event that moves money. Authorizations, refunds and order events are ACKed
# and ignored — an ack stops the provider retrying, and ignoring is what we would do
# with them anyway until there is a decision-log entry saying otherwise.
CAPTURED_EVENT: Final = "payment.captured"

# The key our checkout attaches to the order's `notes`, carrying the tenant through
# the provider and back. It is prefixed because `notes` is a shared free-form map.
NOTES_TENANT_KEY: Final = "calevate_tenant_id"

# The key carrying which prepaid PACK a payment was for, so the receiver can grant the
# volume bonus (`billing/credit_packs.py`) attributable to a captured payment and nothing
# else. Optional: a plain top-up (no pack) carries no such note and grants no bonus.
NOTES_PACK_KEY: Final = "calevate_pack_id"

# The ledger is INR (hard rule 7). A payment in any other currency is refused rather
# than converted: an fx rate applied at credit time is a number nobody can reproduce.
SUPPORTED_CURRENCY: Final = "INR"

PAISE_PER_RUPEE: Final = Decimal(100)

# --- the vendor's control plane, as far as their own code states it -------------
#
# READ AT SOURCE for all four: `razorpay/constants/url.py` on razorpay/razorpay-python
# (`master`, fetched 2026-08-14) defines `BASE_URL = 'https://api.razorpay.com'`,
# `V1 = '/v1'`, `V2 = '/v2'`, `ORDER_URL = "/orders"`, and `razorpay/resources/order.py`
# builds the create path as `URL.V1 + URL.ORDER_URL`, POSTed with no id segment.
BASE_URL: Final = "https://api.razorpay.com"

# PINNED DELIBERATELY. Razorpay's API is versioned in the PATH, not in a header, and
# `URL.V2` exists in the same file — so the version is a real axis they already move on,
# and "whatever the client library defaults to" is a breaking change on somebody else's
# release schedule. Pinning here means a v2 migration is a diff in this module with a
# test beside it, not a response that quietly changes shape under a running deployment.
API_VERSION_PATH: Final = "/v1"
ORDERS_PATH: Final = "/orders"

# READ AT SOURCE: `razorpay/client.py` passes `auth=` (a `(key_id, key_secret)` tuple)
# straight to `requests`, i.e. HTTP Basic, and sets `Content-Type: application/json` on
# POST. httpx spells the same thing `auth=(id, secret)`.
#
# Their client also sends a `User-Agent` of `Razorpay-Python/<version>`. We do NOT
# impersonate it: claiming to be a client library we are not is the kind of small lie
# that makes a vendor's support answer the wrong question.
USER_AGENT: Final = "Calevate/1.0 (+https://calevate.tech)"

# One order creation sits inside a client request, so the budget is a human's patience,
# not a worker's. Shorter than the engine adapter's because a slow payment provider must
# surface as OUR refusal rather than as a browser timeout with no explanation.
ORDER_TIMEOUT_S: Final = 8.0

# REPORTED, NOT READ (search summary of `razorpay.com/docs/api/orders/create`, which the
# egress proxy refuses): `receipt` is at most 40 characters, and an account MAY be
# configured to reject a duplicate receipt. We do not RELY on that — dashboard-toggled
# vendor behaviour is not an idempotency guarantee — but we do stay inside the length,
# because a receipt silently truncated by the vendor would stop being the key we derived.
RECEIPT_MAX_LEN: Final = 40
RECEIPT_PREFIX: Final = "clv"

# How long two identical top-up requests from one tenant are treated as ONE.
# The argument is on `topup_receipt`; the number is "longer than a double-click and a
# retry, shorter than a change of mind".
INTENT_REPLAY_WINDOW: Final = timedelta(minutes=15)

# --- the capability seam -------------------------------------------------------
#
# Mirrors `workers/sheets_sync.get_sheets_transport` / `sheets_delivery_available`:
# a config-named provider, ONE selector, and authored reason codes — never vendor prose.

# A provider name with no adapter behind it. Suffixed with the name in the reason so an
# alert says which one was expected; the name is OUR config, not vendor text.
PROVIDER_NOT_IMPLEMENTED_REASON: Final = "provider_not_implemented"
NO_PROVIDER_REASON: Final = "no_payment_provider"
NO_KEY_REASON: Final = "no_publishable_key"
NO_WEBHOOK_SECRET_REASON: Final = "no_webhook_secret"
# Not a refusal of PAYMENT — a deployment without the API secret can still take a
# webhook and credit a wallet. It refuses only the ORDER, which is why it rides on
# `creates_orders` and never on `available`.
NO_API_SECRET_REASON: Final = "no_api_secret"

# Is there an order-creation adapter IN THIS REPOSITORY? Yes, since D-98:
# `RazorpayOrders.create_order`, a real `POST /v1/orders`.
#
# It is a CONSTANT rather than a comment so the claim is greppable and testable — the
# same device `rates.ENGINE_REPORTS_TTS_MODEL` uses for the vendor question it is
# waiting on. It is NOT a statement that any deployment can create an order: that is
# `PaymentCapability.creates_orders`, which also requires the API secret and is False
# everywhere today. Flipping this one was never a config change and still is not.
PROVIDER_CREATES_ORDERS: Final = True


def razorpay_api_secret() -> str | None:
    """The private key half of the Razorpay pair, or None. THE only read of it.

    `razorpay_key_id` is the public half the browser may see; this one never leaves the
    server, which is why the two are separate `Settings` fields and why this accessor
    exists rather than every caller reading the field.

    A PLAIN ATTRIBUTE READ, AND IT USED TO BE A `getattr` WITH A DEFAULT. The comment
    above it said, in bold, "THIS FIELD DOES NOT EXIST ON `Settings` YET" and drew the
    consequence: that `razorpay_api_secret()` returns None on every deployment and no
    order can ever be created. `razorpay_key_secret` was declared in
    `calevate_shared.config` IN THE SAME COMMIT that wrote that sentence, so the module
    has been describing a blocker that was already closed — while the `getattr` silently
    turned any future rename or typo of the field name into "no payment provider
    configured" rather than into a red type check. What IS still true is operational and
    lives where operational facts belong: no Razorpay account is provisioned, so
    `RAZORPAY_KEY_SECRET` is unset everywhere and `creates_orders` is False everywhere —
    `PaymentCapability` reports that, and `runbooks/topup-payments.md` documents it.

    Empty string collapses to None: an env var set to `""` is an operator who meant to
    unset it, and treating it as a credential would send `Basic <id>:` to a payment
    provider and get an opaque 401 back.
    """
    return get_settings().razorpay_key_secret or None


@dataclass(frozen=True, slots=True)
class PaymentCapability:
    """What this deployment can actually do about money, as one answer.

    `reason` is non-None exactly when `available` is False, and it is an AUTHORED code
    — it names our own configuration state, never a vendor's error string.
    """

    available: bool
    provider: str | None = None
    reason: str | None = None
    # Can THIS DEPLOYMENT create a provider-side order? Adapter (`PROVIDER_CREATES_ORDERS`)
    # AND secret (`razorpay_api_secret`). Still False everywhere today, because no
    # Razorpay account has been provisioned. Carried on the capability rather than read
    # separately so a caller cannot conclude "payments work" and then assume "so an order
    # exists" — the two are one lookup and one object.
    creates_orders: bool = False
    # Non-None exactly when `available` is True and `creates_orders` is False. A separate
    # field from `reason` because they answer different questions and collapsing them
    # would make "why can I not pay" and "why is there no order" indistinguishable in an
    # alert. AUTHORED, logged, never returned.
    orders_reason: str | None = None


def payment_capability() -> PaymentCapability:
    """THE selector. Every payment surface asks this and nothing re-reads settings.

    Unset provider ⇒ this deployment takes no online payments. That is the default and
    it is the truth today. An unknown name ⇒ `provider_not_implemented`, loudly, rather
    than a surface that looks configured and refuses after the click.

    A known provider still needs its credentials, and they are checked HERE so that
    "payments are available" cannot mean one thing to the intent route and another to
    the receiver. Both are required together on purpose: a key id with no webhook secret
    is a deployment that could take money and could never credit it, which is the worst
    of the three states — money leaves the client and never reaches their wallet.
    """
    settings = get_settings()
    provider = (settings.payment_provider or "").strip().lower()
    if not provider:
        return PaymentCapability(available=False, reason=NO_PROVIDER_REASON)
    if provider != PROVIDER:
        return PaymentCapability(
            available=False,
            provider=provider,
            reason=f"{PROVIDER_NOT_IMPLEMENTED_REASON}:{provider}",
        )
    if not settings.razorpay_key_id:
        return PaymentCapability(available=False, provider=provider, reason=NO_KEY_REASON)
    if not settings.razorpay_webhook_secret:
        return PaymentCapability(
            available=False, provider=provider, reason=NO_WEBHOOK_SECRET_REASON
        )
    # The order half is a SEPARATE credential and therefore a separate answer. A
    # deployment that can verify webhooks but holds no API secret is perfectly coherent
    # — it credits payments taken elsewhere — so this must never pull `available` down.
    creates_orders = PROVIDER_CREATES_ORDERS and razorpay_api_secret() is not None
    return PaymentCapability(
        available=True,
        provider=provider,
        creates_orders=creates_orders,
        orders_reason=None if creates_orders else NO_API_SECRET_REASON,
    )


def online_payments_available() -> bool:
    """The boolean a caller wants. Deliberately the SAME selector every other caller
    uses rather than a second read of the same settings — a screen that decided for
    itself whether payment works would eventually disagree with the route behind it,
    and the disagreement reads as "it offered me a payment and then refused it"."""
    return payment_capability().available


def payments_not_configured(reason: str | None) -> ProblemError:
    """The ONE refusal, so every surface says the same thing in the same shape.

    RFC-9457: the machine code is the LAST SEGMENT of `type` and there is no `code` key.
    `reason` is OUR authored state and is logged, never returned — a client cannot act
    on "no_webhook_secret" and telling them which of our secrets is missing is an
    internals leak (user-safe messages, no internals).
    """
    log.warning("payments_unavailable", extra={"reason": reason or "unknown"})
    return ProblemError(
        kind="dependency",
        code="payments_not_configured",
        title="Online payment is unavailable",
        detail="Your account cannot start an online payment.",
        remediation="Contact us to pay by bank transfer instead.",
    )


@dataclass(frozen=True, slots=True)
class CapturedPayment:
    """OUR normalized shape. Nothing downstream of `extract_captured_payment` sees a
    vendor payload — the same discipline hard rule 2 imposes on the voice engine,
    applied here because a payment provider is just as replaceable."""

    payment_id: str
    tenant_id: UUID
    amount_inr: Decimal
    currency: str
    # Which prepaid pack this payment bought, if any (`notes.calevate_pack_id`). None for a
    # plain top-up. Carried as the raw id and resolved against the catalogue at credit time,
    # so a pack this build no longer offers resolves to "no bonus" rather than crashing.
    pack_id: str | None = None


@dataclass(frozen=True, slots=True)
class TopUpResult:
    entry_id: UUID
    balance: Balance
    # False = this payment id was already on the ledger and nothing moved.
    recorded: bool
    # The bonus ledger entry granted for a pack, when this payment bought one and was a
    # fresh credit. None on a plain top-up or a replay. `balance` already reflects the
    # bonus — it is read after both entries land.
    bonus_entry_id: UUID | None = None
    bonus_inr: Decimal | None = None


def verify_signature(*, secret: str, body: bytes, signature: str | None) -> bool:
    """HMAC-SHA256 over the RAW body, hex, constant-time compared.

    **READ AT SOURCE** (D-98): `razorpay/utility/utility.py::verify_signature` on
    razorpay/razorpay-python is `hmac.new(key=secret, msg=body,
    digestmod=hashlib.sha256).hexdigest()` compared with `hmac.compare_digest`, and
    `verify_webhook_signature(body, signature, secret)` is a one-line delegation to it.
    The digest below is that, exactly.

    The HEADER NAME is still UNVERIFIED — their SDK is handed the signature as an
    argument and never names where it came from. It has never been exercised against a
    live account either way. Two properties hold regardless of whether the scheme is
    right:

    - the comparison is `hmac.compare_digest`, so a wrong signature leaks no timing
      information about how much of it was right;
    - the body is the bytes as received. Re-serializing parsed JSON to verify it would
      compare a signature against something the sender never signed, and would pass or
      fail on key order.
    """
    if not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.strip(), expected)


def paise_to_inr(amount: Any) -> Decimal:
    """An integer count of paise → rupees, exactly.

    `Decimal(int) / Decimal(100)` is exact for every paise value; `amount / 100` on a
    float is not, and `Decimal(float)` would import the error rather than reject it.
    So a non-integer amount is REFUSED (hard rule 7) — including a JSON float that
    happens to look whole, because by the time we see it the damage has been done.

    `bool` is checked before `int` on purpose: `True` is an `int` in Python and would
    otherwise credit one paisa.
    """
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ProblemError.business_rule(
            "payment_amount_unrecognized",
            "The captured amount was not an integer number of paise.",
            remediation="A payment amount must arrive as an integer; nothing was credited.",
        )
    if amount <= 0:
        raise ProblemError.business_rule(
            "payment_amount_unrecognized",
            "The captured amount was not a positive number of paise.",
            remediation="A refund is a compensating entry, never a negative top-up.",
        )
    return Decimal(amount) / PAISE_PER_RUPEE


def inr_to_paise(amount_inr: Decimal) -> int:
    """Rupees → an integer count of paise, exactly, or a refusal. **The single most
    dangerous line in this integration**, so it is one function with one caller-visible
    behaviour and a test at every boundary.

    Hard rule 7 in the outbound direction. Three properties, each of which is a way this
    has gone wrong somewhere before:

    1. **A float is REFUSED, never converted.** `Decimal(2500.10)` is
       `2500.099999999999909050529822707176208496093750`, so importing a float here would
       import an error we can never see again. The signature says `Decimal` and mypy
       enforces it at every call site in this repository; the runtime check is still here
       because the response of a payment provider and the body of a request are the two
       places a type annotation is a promise rather than a guarantee. `bool` needs no
       separate test the way it does in `paise_to_inr` — `True` is an `int`, not a
       `Decimal`, so it is refused by the same line.
    2. **The multiplication is exact and the check is explicit.** `amount * Decimal(100)`
       is exact for every finite Decimal, and a fractional remainder means the caller
       asked for a fraction of a paisa — which is refused rather than rounded. The
       previous inline form, `int((amount * 100).to_integral_exact())`, LOOKED like it
       refused: `to_integral_exact` only SIGNALS `Inexact`, and the default decimal
       context has that trap off, so it silently rounds half-to-even. It was safe only
       because Pydantic happened to reject three-decimal input upstream — i.e. it was
       correct by accident, one validator away from a paisa going missing.
       `int()` on the result truncates, which is safe only because the line above has
       already proved there is nothing to truncate.
    3. **Zero and negatives are refused.** A refund is a compensating entry someone
       decides on (hard rule 4), never a negative order.

    NOT `to_paise()` first. Quantizing would ROUND ₹2,500.105 to ₹2,500.10 and then
    convert it happily; refusing is the whole point.
    """
    if not isinstance(amount_inr, Decimal):
        raise ProblemError.business_rule(
            "topup_amount_unrepresentable",
            "That amount could not be handled as an exact rupee value.",
            remediation='Send the amount as a decimal string, for example "2500.00".',
        )
    if not amount_inr.is_finite() or amount_inr <= 0:
        raise ProblemError.business_rule(
            "topup_amount_unrepresentable",
            "A top-up must be a positive rupee amount.",
            remediation="Enter an amount greater than zero.",
        )
    scaled = amount_inr * PAISE_PER_RUPEE
    if scaled != scaled.to_integral_value():
        raise ProblemError.business_rule(
            "topup_amount_unrepresentable",
            "That amount is finer than one paisa.",
            remediation="Round it yourself to two decimal places — we will not round it for you.",
        )
    return int(scaled)


def topup_receipt(*, tenant_id: UUID, amount_inr: Decimal, at: datetime) -> str:
    """The key for "this top-up request", derived by US. One string, three jobs.

    It is the provider's `receipt`, it is the `idempotency_records` key the intent route
    claims on, and it is the reference a client quotes on a bank transfer when this
    deployment cannot create an order at all. One string because they are one fact.

    WHY THIS IS NOT A THIRD ANSWER. This repository has already settled the two halves
    and they compose:

    * **What the key IS** — content-addressed over the request, exactly as
      `service.adjustment_ref` (D-87). A caller-minted key was rejected there for
      precisely the failure this must survive: a second CLICK mints a second key and the
      side effect happens twice. The amount goes through `to_paise` for the same reason
      it does there, so `2000` and `2000.00` are one key and not two.
    * **How a repeat is SERVED** — `reliability.claim_idempotency`, with the key derived
      server-side rather than read off a header. That is `crm.routes.call_back`'s
      pattern verbatim ("Idempotency keys off the CALL, not a client-supplied header …
      a double-click must not ring a customer twice even from two browser tabs"). A
      top-up simply has no natural durable id the way a call does, so D-87 supplies the
      material that `call_back` gets for free.

    THE WINDOW, AND ITS COST, STATED. `adjustment_ref` has no clock in it because two
    identical corrections of one entry really are one correction. A top-up is different:
    a client may legitimately pay ₹2,000 today and ₹2,000 again next week, and a timeless
    key would hand them back the order they already paid — which a checkout then refuses,
    because a paid order cannot be paid again. So the request is bucketed by
    `INTENT_REPLAY_WINDOW`. Inside one window an identical request is ONE request; across
    windows it is a new one.

    - The cost: a client who genuinely wants to pay the same amount twice within fifteen
      minutes gets the first order back. That is visible (the screen shows the order and
      the amount), and the remedy is one field away — pay the one you have, or ask for
      the combined amount.
    - The failure at a bucket boundary: two clicks a second apart, straddling the floor,
      derive different keys and create two orders. That is the BENIGN direction — an
      extra unpaid order expires and costs nobody anything, while collapsing two genuine
      payments would cost a client a top-up. Chosen deliberately in that direction.

    Truncated to 32 hex characters (128 bits) so `clv_…` fits inside the vendor's
    40-character receipt limit with room to spare. It is a dedupe key, not a secret:
    a collision needs ~2^64 requests, and the value is never authenticated on.
    """
    window = int(at.timestamp()) // int(INTENT_REPLAY_WINDOW.total_seconds())
    digest = body_hash(
        {
            "tenant_id": str(tenant_id),
            # A STRING of the quantized decimal, never a float and never the raw Decimal:
            # `body_hash` would otherwise `str()` it and make "2000" and "2000.00" two keys.
            "amount_inr": str(to_paise(amount_inr)),
            "window": window,
        }
    )
    receipt = f"{RECEIPT_PREFIX}_{digest[:32]}"
    assert len(receipt) <= RECEIPT_MAX_LEN, "the receipt must survive the vendor intact"
    return receipt


@dataclass(frozen=True, slots=True)
class ProviderOrder:
    """OUR normalized order. Nothing above the adapter sees a vendor payload — the same
    discipline hard rule 2 imposes on the voice engine."""

    order_id: str
    receipt: str
    amount_paise: int


class RazorpayOrders:
    """`POST /v1/orders`. The one place this repository talks to Razorpay.

    Constructed per request from `razorpay_orders()`; a client may be injected, which is
    how every test in this repository exercises it — **no test may reach the real API,
    and there is no fallback that would let one.**

    Errors are OURS. The vendor's message is logged with its status and never forwarded:
    a client cannot act on Razorpay's prose, and hard rule 2's argument (a vendor string
    where every caller expects one of ours) applies to a payment provider for exactly the
    reason it applies to a voice engine — they are replaceable.
    """

    def __init__(
        self,
        *,
        key_id: str,
        key_secret: str,
        client: httpx.AsyncClient | None = None,
        base_url: str = BASE_URL,
        version_path: str = API_VERSION_PATH,
    ) -> None:
        self._auth = (key_id, key_secret)
        self._client = client
        self._base_url = base_url
        self._version_path = version_path

    async def create_order(
        self, *, amount_inr: Decimal, receipt: str, notes: dict[str, str]
    ) -> ProviderOrder:
        """Create one order for one top-up, priced in whole paise.

        READ AT SOURCE for the request: path `V1 + "/orders"`, HTTP Basic with
        `(key_id, key_secret)`, `Content-Type: application/json`, and the body keys
        `amount` / `currency` / `receipt` / `notes` are the ones
        `razorpay/resources/order.py::create` documents in its own docstring.

        `payment_capture` is deliberately NOT sent. It is a fifth key their SDK names,
        and auto-capture is an account-level setting on the dashboard; sending our
        assumption would silently override whatever the operator configured, and a
        payment authorized-but-not-captured is money we do not hold and never credit
        (`CAPTURED_EVENT`). Leaving it out means the account decides, which is where that
        decision belongs.

        UNVERIFIED for the response: that the order id arrives as `id`. If it does not,
        this raises `payment_order_unreadable` and the client is told the payment could
        not be started — loud, and nothing is fabricated. A made-up order id would be
        handed to a checkout that rejects it, which turns a broken integration into a
        client who believes they have paid.
        """
        amount_paise = inr_to_paise(amount_inr)
        payload = {
            "amount": amount_paise,
            "currency": SUPPORTED_CURRENCY,
            "receipt": receipt,
            # The tenant, put INTO the order rather than handed to a frontend and hoped
            # for. `extract_captured_payment` reads it back off the payment and from
            # nothing else, so this line is what makes a captured payment attributable.
            "notes": notes,
        }
        client = self._client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=ORDER_TIMEOUT_S,
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            response = await client.post(
                f"{self._version_path}{ORDERS_PATH}", json=payload, auth=self._auth
            )
        except httpx.HTTPError as exc:
            log.warning("razorpay_order_unreachable", extra={"reason": type(exc).__name__})
            raise ProblemError(
                kind="dependency",
                code="payment_provider_unreachable",
                title="The payment provider did not respond",
                detail="We could not start a payment just now.",
                remediation="Try again in a minute, or contact us to pay by bank transfer.",
            ) from exc
        finally:
            if self._client is None:
                await client.aclose()

        if response.status_code >= 400:
            # No payload, no vendor prose, and NO RECEIPT either: the receipt is derived
            # from the tenant and the amount, and hard rule 6's habit is to log ids.
            log.warning("razorpay_order_rejected", extra={"status": response.status_code})
            raise ProblemError(
                kind="dependency",
                code="payment_provider_rejected",
                title="The payment provider refused this payment",
                detail="We could not start a payment for that amount.",
                remediation="Contact us to pay by bank transfer instead.",
            )

        try:
            body = response.json()
        except ValueError:
            body = None
        order_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(order_id, str) or not order_id.strip():
            log.warning("razorpay_order_unreadable", extra={"status": response.status_code})
            raise ProblemError(
                kind="dependency",
                code="payment_order_unreadable",
                title="The payment provider returned an unusable order",
                detail="We could not start a payment just now.",
                remediation="Try again in a minute, or contact us to pay by bank transfer.",
            )

        # The amount echo, checked when present. A MISMATCH is a money fact and is
        # refused; an ABSENT field is an unverified-shape fact and only logged, because
        # failing on it would make a working integration depend on a field name nobody
        # here has confirmed. Getting those two the wrong way round is how a shape guess
        # becomes an outage, or how a wrong amount becomes a dispute.
        echoed = body.get("amount") if isinstance(body, dict) else None
        if isinstance(echoed, int) and not isinstance(echoed, bool):
            if echoed != amount_paise:
                log.error("razorpay_order_amount_mismatch", extra={"order_id": order_id})
                raise ProblemError(
                    kind="dependency",
                    code="payment_order_amount_mismatch",
                    title="The payment provider priced this differently",
                    detail="The payment was set up for a different amount, so we stopped.",
                    remediation="Nothing has been charged. Contact us before trying again.",
                )
        else:
            log.info("razorpay_order_amount_not_echoed", extra={"order_id": order_id})

        return ProviderOrder(order_id=order_id.strip(), receipt=receipt, amount_paise=amount_paise)


def razorpay_orders() -> RazorpayOrders:
    """Build the adapter from settings. Call ONLY behind `capability.creates_orders`.

    The asserts are not a second check — they are the statement that the capability
    already made both of them true. A caller that reaches here without asking the seam
    gets an AssertionError in a test rather than an unauthenticated call in production.
    """
    settings = get_settings()
    key_id = settings.razorpay_key_id
    key_secret = razorpay_api_secret()
    assert key_id is not None, "the capability check proved the key id is set"
    assert key_secret is not None, "the capability check proved the API secret is set"
    return RazorpayOrders(key_id=key_id, key_secret=key_secret)


def event_name(envelope: Any) -> str:
    """UNVERIFIED field: the top-level `event` string."""
    if not isinstance(envelope, dict):
        return ""
    value = envelope.get("event")
    return value if isinstance(value, str) else ""


def extract_captured_payment(envelope: Any) -> CapturedPayment:
    """Vendor envelope → `CapturedPayment`, or a refusal that credits nothing.

    EVERY field path read here is UNVERIFIED (module docstring). They are all read in
    this one function so that verifying the contract against a real account is a
    single-function change, and so that being wrong is visible: a missing or oddly
    shaped field produces `payment_payload_unrecognized`, never a guess and never a
    partial credit.
    """
    entity: Any = None
    if isinstance(envelope, dict):
        payload = envelope.get("payload")
        if isinstance(payload, dict):
            payment = payload.get("payment")
            if isinstance(payment, dict):
                entity = payment.get("entity")
    if not isinstance(entity, dict):
        raise ProblemError.business_rule(
            "payment_payload_unrecognized",
            "This payment event did not match the shape this deployment can read.",
            remediation="Nothing was credited. Check the provider's payload contract.",
        )

    payment_id = entity.get("id")
    if not isinstance(payment_id, str) or not payment_id.strip():
        raise ProblemError.business_rule(
            "payment_payload_unrecognized",
            "This payment event carried no payment identifier.",
            remediation="Nothing was credited: the identifier is what makes a credit idempotent.",
        )

    currency = entity.get("currency")
    if not isinstance(currency, str) or currency.upper() != SUPPORTED_CURRENCY:
        raise ProblemError.business_rule(
            "payment_currency_unsupported",
            "This account settles in Indian rupees only.",
            remediation="Nothing was credited. A non-INR payment needs a manual adjustment.",
        )

    amount_inr = paise_to_inr(entity.get("amount"))

    notes = entity.get("notes")
    raw_tenant = notes.get(NOTES_TENANT_KEY) if isinstance(notes, dict) else None
    try:
        tenant_id = UUID(str(raw_tenant))
    except (TypeError, ValueError) as exc:
        # The tenant is the ONE fact the provider cannot supply on its own — our
        # checkout puts it in `notes`. Without it a payment is real money we cannot
        # attribute, which is an ops problem, not a wallet to guess at.
        raise ProblemError.business_rule(
            "payment_tenant_unresolved",
            "This payment did not say which account it was for.",
            remediation=(
                "Nothing was credited. Record it manually against the right account "
                "once the payer is identified."
            ),
        ) from exc

    # The pack id is OPTIONAL and never fatal: a plain top-up carries none, and a value we
    # cannot read (or one this build no longer offers) simply grants no bonus — it must not
    # refuse a real payment. Only the tenant is load-bearing enough to refuse on.
    raw_pack = notes.get(NOTES_PACK_KEY) if isinstance(notes, dict) else None
    pack_id = raw_pack.strip() if isinstance(raw_pack, str) and raw_pack.strip() else None

    return CapturedPayment(
        payment_id=payment_id.strip(),
        tenant_id=tenant_id,
        amount_inr=amount_inr,
        currency=SUPPORTED_CURRENCY,
        pack_id=pack_id,
    )


async def credit_captured_payment(
    session: AsyncSession, *, payment: CapturedPayment, ip: str | None = None
) -> TopUpResult:
    """Put one captured payment on the wallet, exactly once.

    The caller supplies a `tenant_session(payment.tenant_id)` — `credit_ledger`'s RLS
    policy is what isolates this, exactly as on the manual top-up route.

    Order is the whole correctness argument:

    1. `lock_tenant_credits` FIRST, before the lookup. Two deliveries of one payment
       (the provider's retry racing its own first attempt) would otherwise both read
       "not credited" and both append. `find_topup` takes the same lock itself, so the
       ordering holds even for a caller that forgets this line.
    2. the lookup on `ref = payment_id`, which is permanent — unlike an inbox row.
    3. `record_entry`, the only writer, and `write_audit` in the SAME transaction, so
       money that moved without an audit row is not a reachable state.
    """
    await lock_tenant_credits(session, payment.tenant_id)

    existing = await find_topup(session, tenant_id=payment.tenant_id, ref=payment.payment_id)
    if existing is not None:
        entry_id, amount = existing.entry_id, existing.amount_inr
        if amount != payment.amount_inr:
            # One payment id, two amounts. Absorbing this as a replay would swallow the
            # difference silently; refusing is how anyone finds out.
            raise ProblemError.conflict(
                "payment_amount_conflict",
                "That payment is already on this wallet for a different amount.",
                remediation="Nothing was credited a second time. Reconcile against the provider.",
            )
        log.info(
            "razorpay_topup_replay",
            extra={"tenant_id": str(payment.tenant_id), "entry_id": str(entry_id)},
        )
        return TopUpResult(
            entry_id=entry_id,
            balance=await get_balance(session, tenant_id=payment.tenant_id),
            recorded=False,
        )

    paid_meta: dict[str, Any] = {"source": PROVIDER, "currency": payment.currency}
    if payment.pack_id is not None:
        # Stamped on the PAID row too, so the pack a payment bought is recoverable even from
        # the topup entry alone — the ledger stamp survives the catalogue changing later.
        paid_meta["pack_id"] = payment.pack_id
    balance = await record_entry(
        session,
        tenant_id=payment.tenant_id,
        delta=payment.amount_inr,
        reason="topup",
        ref=payment.payment_id,
        meta=paid_meta,
    )
    written = await find_topup(session, tenant_id=payment.tenant_id, ref=payment.payment_id)
    assert written is not None, "the row was inserted in this transaction"

    await write_audit(
        session,
        action="credit.topup",
        # No human took this action, and naming one would be a lie in the one log that
        # is supposed to be evidence. The provider callback is a system actor.
        actor_type="system",
        tenant_id=payment.tenant_id,
        object_type="credit_ledger",
        object_id=str(written.entry_id),
        ip=ip,
        summary={
            "source": PROVIDER,
            "payment_ref": payment.payment_id,
            "amount_inr": str(payment.amount_inr),
            "balance_after_inr": str(balance.amount_inr),
        },
    )
    log.info(
        "razorpay_topup_recorded",
        extra={"tenant_id": str(payment.tenant_id), "entry_id": str(written.entry_id)},
    )

    # The volume bonus, in the SAME transaction as the paid credit, so a wallet can never
    # hold the paid credits of a pack without its bonus (or vice versa). Idempotent on the
    # payment id under `reason='bonus'` (`ux_credit_ledger_bonus_ref`); a payment carrying no
    # pack, or a pack this build no longer offers, grants nothing and leaves `balance` as the
    # paid-only figure above.
    pack = pack_by_id(payment.pack_id) if payment.pack_id is not None else None
    if pack is None:
        return TopUpResult(entry_id=written.entry_id, balance=balance, recorded=True)
    return await _grant_pack_bonus(
        session, payment=payment, pack=pack, paid_entry_id=written.entry_id, ip=ip
    )


async def _grant_pack_bonus(
    session: AsyncSession,
    *,
    payment: CapturedPayment,
    pack: CreditPack,
    paid_entry_id: UUID,
    ip: str | None,
) -> TopUpResult:
    """Append the pack's bonus credits as one `bonus` ledger entry, exactly once.

    Keyed on the payment id under `reason='bonus'`, a namespace distinct from the paid
    `topup` row (which is keyed on the same id under `reason='topup'`), so the two never
    collide and each is independently idempotent. The `find_entry_by_ref` guard makes a
    re-run a no-op rather than an IntegrityError against the unique index — the same
    check-then-write-under-lock discipline `credit_captured_payment` uses for the paid leg.

    A zero bonus (the 0%-bonus starter pack) writes nothing: `record_entry` returns early on
    a zero delta anyway, and a ₹0 ledger row is noise, so the paid-only balance is returned.
    """
    bonus_inr = pack.bonus_credits
    if bonus_inr <= 0:
        return TopUpResult(
            entry_id=paid_entry_id,
            balance=await get_balance(session, tenant_id=payment.tenant_id),
            recorded=True,
        )

    existing_bonus = await find_entry_by_ref(
        session, tenant_id=payment.tenant_id, reason="bonus", ref=payment.payment_id
    )
    if existing_bonus is not None:
        log.info(
            "razorpay_pack_bonus_replay",
            extra={"tenant_id": str(payment.tenant_id), "entry_id": str(existing_bonus.entry_id)},
        )
        return TopUpResult(
            entry_id=paid_entry_id,
            balance=await get_balance(session, tenant_id=payment.tenant_id),
            recorded=True,
            bonus_entry_id=existing_bonus.entry_id,
            bonus_inr=existing_bonus.amount_inr,
        )

    balance = await record_entry(
        session,
        tenant_id=payment.tenant_id,
        delta=bonus_inr,
        reason="bonus",
        ref=payment.payment_id,
        meta={
            "kind": PACK_BONUS_META_KIND,
            "source": PROVIDER,
            "pack_id": pack.pack_id,
            # The paid row this bonus was earned on, so an auditor can pair the two without
            # string surgery. A digit STRING (hard rule 7): a bonus that goes into JSON as a
            # number comes back a float in some reader.
            "paid_entry_id": str(paid_entry_id),
            "amount_inr": str(bonus_inr),
        },
    )
    written_bonus = await find_entry_by_ref(
        session, tenant_id=payment.tenant_id, reason="bonus", ref=payment.payment_id
    )
    assert written_bonus is not None, "the bonus row was inserted in this transaction"

    await write_audit(
        session,
        action="credit.pack_bonus",
        actor_type="system",
        tenant_id=payment.tenant_id,
        object_type="credit_ledger",
        object_id=str(written_bonus.entry_id),
        ip=ip,
        summary={
            "source": PROVIDER,
            "pack_id": pack.pack_id,
            "payment_ref": payment.payment_id,
            "paid_entry_id": str(paid_entry_id),
            "bonus_inr": str(bonus_inr),
            "balance_after_inr": str(balance.amount_inr),
        },
    )
    log.info(
        "razorpay_pack_bonus_recorded",
        extra={
            "tenant_id": str(payment.tenant_id),
            "entry_id": str(written_bonus.entry_id),
            "pack_id": pack.pack_id,
        },
    )
    return TopUpResult(
        entry_id=paid_entry_id,
        balance=balance,
        recorded=True,
        bonus_entry_id=written_bonus.entry_id,
        bonus_inr=bonus_inr,
    )


__all__ = [
    "API_VERSION_PATH",
    "BASE_URL",
    "CAPTURED_EVENT",
    "INTENT_REPLAY_WINDOW",
    "NOTES_PACK_KEY",
    "NOTES_TENANT_KEY",
    "NO_API_SECRET_REASON",
    "NO_KEY_REASON",
    "NO_PROVIDER_REASON",
    "NO_WEBHOOK_SECRET_REASON",
    "ORDERS_PATH",
    "PROVIDER",
    "PROVIDER_CREATES_ORDERS",
    "PROVIDER_NOT_IMPLEMENTED_REASON",
    "RECEIPT_MAX_LEN",
    "SIGNATURE_HEADER",
    "SUPPORTED_CURRENCY",
    "CapturedPayment",
    "PaymentCapability",
    "ProviderOrder",
    "RazorpayOrders",
    "TopUpResult",
    "credit_captured_payment",
    "event_name",
    "extract_captured_payment",
    "find_topup",
    "inr_to_paise",
    "online_payments_available",
    "paise_to_inr",
    "payment_capability",
    "payments_not_configured",
    "razorpay_api_secret",
    "razorpay_orders",
    "topup_receipt",
    "verify_signature",
]
