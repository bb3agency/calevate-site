/**
 * Razorpay Standard Checkout — loaded on demand, opened with the server's own values.
 *
 * ## The evidence this rests on, and its class
 *
 * `razorpay.com` is refused by this environment's egress proxy (re-measured 25 Aug 2026:
 * `checkout.razorpay.com` answers `403` on CONNECT and `razorpay.com/docs/...` is refused
 * by the fetch tool), so **nobody here has read their documentation pages** — the same
 * statement `runbooks/topup-payments.md` makes about the server half, and the same
 * three-rung ladder is used at each line below.
 *
 * READ AT SOURCE — Razorpay's own published code, fetched 25 Aug 2026:
 *
 * - `github.com/razorpay/razorpay-mcp-server`, `pkg/razorpay/integrations/
 *   frontend_templates.go` on `main` (their own MCP server, which emits the integration
 *   snippet they hand to developers). It gives, verbatim: the script
 *   `https://checkout.razorpay.com/v1/checkout.js` injected as a `<script>` with
 *   `onload`/`onerror` **only when `window.Razorpay` is absent**; the options object
 *   `{ key, amount, currency, name, order_id, handler, modal: { ondismiss }, theme }`;
 *   `new window.Razorpay(options)`; `razorpay.on('payment.failed', (r) => … r.error.
 *   description)`; and `razorpay.open()`. The handler's `response` is POSTed to the
 *   merchant's own verify endpoint — it is never trusted in the browser.
 * - `github.com/razorpay/razorpay-woocommerce`, `woo-razorpay.php` on `master` — their own
 *   plugin — names the three callback fields as the constants `razorpay_payment_id`,
 *   `razorpay_order_id`, `razorpay_signature`, and loads the same script URL. Those three
 *   are also what `apps/api/billing/payment_routes.py::CheckoutCallbackIn` requires, so
 *   the two ends agree without either being guessed.
 *
 * REPORTED, NOT READ — WebSearch summaries of `razorpay.com/docs/payments/payment-gateway/
 * web-integration/standard/integration-steps/`, 25 Aug 2026: that `modal.ondismiss` fires
 * when the user closes the modal, and that the signature must be verified server-side and
 * a mismatch treated as fraudulent rather than retried. Both are corroborated by the code
 * above and by our own server, and neither is load-bearing on its own: if `ondismiss`
 * never fires the screen keeps its "checkout is open" state and its cancel affordance,
 * and verification is the server's business in either case.
 *
 * UNVERIFIED, and therefore not relied on: the exact shape of the `payment.failed`
 * payload beyond `error` existing. Nothing here reads a field off it — see
 * `paymentFailedProblem` for why the vendor's sentence is not shown at all.
 *
 * ## Why the script is injected here rather than in a layout
 *
 * It is a third-party script on a console that holds other businesses' customer data, and
 * it is needed by exactly one panel on one screen, only after a client has decided to pay.
 * A `next/script` in the root layout would put it on the critical path of every page in
 * both realms — including the signed-out ones — for a control most sessions never touch.
 * So it is fetched from a click, once per document, and its failure is a sentence rather
 * than a dead button (`checkoutUnavailableProblem`).
 *
 * ## The Content-Security-Policy already covers this, and this line used to say there was
 * none
 *
 * `infra/nginx/snippets/calevate-headers.conf` sets no CSP — stated there as a decision,
 * because a nonce-based policy belongs in the tier that mints the nonce — and this comment
 * stopped one sentence short of the truth: the APP tier does serve one
 * (`lib/security/csp.ts`, emitted per request by `middleware.ts`), and it already names
 * this origin twice. `script-src` carries `https://checkout.razorpay.com` so the tag below
 * may execute, and `frame-src` carries it plus `https://api.razorpay.com` because Checkout
 * renders its own iframe inside our page. So adding the payment window needs NO change to
 * the policy, and nothing here is a reason to widen one.
 *
 * It is `Content-Security-Policy-Report-Only` today, so a mistake in it surfaces as a
 * report rather than as a client's dashboard going white — which also means the policy is
 * not what would stop this script if it were wrong. The edge headers are unaffected either
 * way: `X-Frame-Options: DENY` and `Cross-Origin-Opener-Policy: same-origin` both hold,
 * because Checkout renders INSIDE our page and opens no cross-origin window handle we keep
 * a reference to.
 */

import { ApiProblem } from "@/lib/api/client";

/** The one script URL, READ AT SOURCE in both repositories cited above. */
export const RAZORPAY_CHECKOUT_SRC = "https://checkout.razorpay.com/v1/checkout.js";

/**
 * How long a script tag may hang before we call it a failure.
 *
 * `onerror` covers a refusal; it does NOT cover a network that accepts the connection and
 * then says nothing, which is what a captive portal or a filtering proxy does — and that
 * is the case that would otherwise leave a client watching a spinner with no way out. The
 * same argument `TimeoutProblem` makes for the API transport.
 */
const LOAD_TIMEOUT_MS = 15_000;

/** The three fields Checkout hands back on success — forwarded verbatim, never read. */
export interface RazorpayCheckoutSuccess {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

interface RazorpayOptions {
  key: string;
  amount: number;
  currency: string;
  order_id: string;
  name: string;
  description: string;
  notes: Record<string, string>;
  handler: (response: RazorpayCheckoutSuccess) => void;
  modal: { ondismiss: () => void };
  theme: { color: string };
}

export interface RazorpayInstance {
  open(): void;
  on(event: "payment.failed", handler: (response: unknown) => void): void;
}

export type RazorpayConstructor = new (options: RazorpayOptions) => RazorpayInstance;

declare global {
  interface Window {
    Razorpay?: RazorpayConstructor;
  }
}

/**
 * The payment window could not be opened — as the `ApiProblem` every screen renders.
 *
 * `AuthProblem`'s and `TimeoutProblem`'s shape, and for their reason (lib/api/client.ts):
 * `ProblemNotice` is the only failure channel these screens have, and a bare `Error`
 * renders there as "Something went wrong" plus a connection hint — neither of which tells
 * a client what to do. `status: 0` says no HTTP exchange failed, because none happened.
 *
 * `retryable: true` is honest: a blocked or dropped script load is exactly the failure a
 * second attempt fixes, and the bank-transfer path is named as the way out that does not
 * depend on the browser at all.
 */
export function checkoutUnavailableProblem(): ApiProblem {
  return new ApiProblem(0, {
    kind: "transient",
    type: "urn:calevate:browser/checkout_unavailable",
    title: "We could not open the payment window",
    detail:
      "The secure payment window did not load in this browser, so nothing has been charged.",
    remediation:
      "Check your connection and try again. A browser extension or an office network that " +
      "blocks payment scripts will also cause this — another browser usually works. You can " +
      "always pay by bank transfer instead: ask your account manager for the details.",
    retryable: true,
  });
}

/**
 * The payment attempt failed — in OUR words, deliberately.
 *
 * The vendor's `error.description` is not shown and is not logged. It is a third-party
 * string of unknown wording rendered to a client of a client, which is the same judgement
 * `payment_capability().reason` makes on the server ("an authored code naming OUR
 * configuration state — never a vendor error string", runbooks/topup-payments.md §1), and
 * the same one `engine/` makes about vendor payloads. It would also be the one place a
 * payment identifier could reach a log line (hard rule 6).
 *
 * What IS asserted is only what our own system knows: we credit a wallet on the captured
 * payment webhook and nowhere else (`apps/api/billing/payments.py`), so "no credit has
 * been added" is a fact about us, not a claim about the client's bank.
 */
export function paymentFailedProblem(): ApiProblem {
  return new ApiProblem(0, {
    kind: "transient",
    type: "urn:calevate:browser/payment_failed",
    title: "The payment did not go through",
    detail: "The payment was not completed, so no credit has been added to your account.",
    remediation:
      "You can try again with the same or a different payment method. If your bank shows " +
      "the amount debited, send us the reference on this page and we will trace it.",
    retryable: true,
  });
}

/**
 * The in-flight injection, so two clicks do not append two script tags.
 *
 * Only the IN-FLIGHT promise is held, never a resolved one: the constructor is read back
 * off `window` on every call, so a cached success cannot outlive the document it belongs
 * to, and a cached failure cannot make a later retry answer from memory. Cleared in
 * `finally` for the same reason.
 */
let injecting: Promise<void> | null = null;

function injectScript(): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    // `done` closes over `timer`, which is created below: the deadline has to be armed
    // AFTER the handlers exist, and every call of `done` happens later still, so the
    // temporal dead zone is never entered.
    const done = (outcome: () => void) => {
      clearTimeout(timer);
      script.onload = null;
      script.onerror = null;
      outcome();
    };
    // The tag is removed on failure so a retry appends a fresh one; a `<script>` that has
    // already errored never fires again, so leaving it would make every retry silent.
    const giveUp = () => done(() => {
      script.remove();
      reject(checkoutUnavailableProblem());
    });
    script.src = RAZORPAY_CHECKOUT_SRC;
    script.async = true;
    script.onload = () => done(resolve);
    script.onerror = giveUp;
    const timer = setTimeout(giveUp, LOAD_TIMEOUT_MS);
    document.head.appendChild(script);
  });
}

/**
 * Fetch Checkout if this document does not already have it.
 *
 * Rejects with `checkoutUnavailableProblem()` — never with a bare `Error` and never
 * silently — including the case the vendor's own snippet does not consider: a script that
 * loads but leaves no `window.Razorpay` behind.
 */
export async function loadRazorpayCheckout(): Promise<RazorpayConstructor> {
  if (typeof window === "undefined") throw checkoutUnavailableProblem();
  const present = window.Razorpay;
  if (present) return present;
  if (injecting === null) {
    injecting = injectScript().finally(() => {
      injecting = null;
    });
  }
  await injecting;
  const loaded = window.Razorpay;
  if (!loaded) throw checkoutUnavailableProblem();
  return loaded;
}

/**
 * What Checkout needs, all of it minted by the API.
 *
 * `amountPaise` is the server's own integer and passes through untouched — there is no
 * rupee-to-paise conversion anywhere in this console, because hard rule 7's failure mode
 * here is not a rounding error on a screen, it is charging a different amount than the
 * one that was agreed. `apps/api/billing/payments.py` does the conversion in `Decimal`
 * and the order it created carries that same integer; a second conversion in the browser
 * would be a second source of the number.
 */
export interface CheckoutRequest {
  keyId: string;
  orderId: string;
  amountPaise: number;
  currency: string;
  receipt: string;
  notes: Record<string, string>;
  /** Checkout reported a completed payment. The three fields go to OUR server to verify. */
  onSuccess: (response: RazorpayCheckoutSuccess) => void;
  /** The client closed the window without paying. Not an error. */
  onDismissed: () => void;
  /** The provider reported a failed attempt. */
  onFailed: () => void;
}

/**
 * Load Checkout and open it. Throws `checkoutUnavailableProblem()` if it cannot be loaded.
 *
 * The three callbacks are forwarded RAW rather than being made mutually exclusive here,
 * and that is deliberate. Checkout closes its modal after a successful payment, so
 * `handler` and `ondismiss` both fire on the happy path; with the provider's in-modal
 * retry, `payment.failed` can fire and be followed by a success. Any "first one wins"
 * rule written at this seam gets one of those two wrong. The caller owns a MONOTONIC
 * state machine instead (`TopUp.tsx`), where "we are already verifying a payment" is a
 * state that a later dismissal cannot walk back — which is the only ordering rule that is
 * safe when money has moved.
 */
export async function openRazorpayCheckout(request: CheckoutRequest): Promise<void> {
  const Checkout = await loadRazorpayCheckout();
  const checkout = new Checkout({
    key: request.keyId,
    amount: request.amountPaise,
    currency: request.currency,
    order_id: request.orderId,
    name: "Calevate",
    // The receipt is the reference the client already sees on screen and the one our
    // support and the provider's dashboard both key on, so it is worth having in front of
    // them while they pay.
    description: `Calling credit · ${request.receipt}`,
    notes: request.notes,
    handler: request.onSuccess,
    modal: { ondismiss: request.onDismissed },
    // `brand-strong` (#0F6B3D), the resting colour of our primary button — see
    // `components/ui.tsx`. Cosmetic only.
    theme: { color: "#0F6B3D" },
  });
  checkout.on("payment.failed", () => request.onFailed());
  checkout.open();
}
