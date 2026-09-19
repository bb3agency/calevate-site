import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import TenantCreditsPage from "@/app/admin/tenants/[tenantId]/credits/page";
import type { TenantSummary } from "@/lib/api/admin";
import {
  LEDGER_LIMIT,
  creditGrantConfirmation,
  creditsPath,
  grantsPath,
  type Credits,
  type GrantResult,
  type LedgerEntry,
  type Payment,
} from "@/lib/api/credits";
import { refundsPath, type RefundResult } from "@/lib/api/refunds";
import { trialPath } from "@/lib/api/trials";

import { expectNoA11yViolations } from "./a11y";
import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, type Routes } from "./harness";

/**
 * THE TWO WRITES ON THIS WALLET THAT HAD NO CALLER — money back out, and money given away.
 *
 * `POST .../refunds` shipped with a claim table, a provider call outside any transaction
 * and a ceiling enforced by a committed row; `POST .../credits/grants` shipped with a
 * ceiling, a mandatory reason, an unconditional step-up and an audit row written in the
 * same transaction as the money. Neither had a console caller, so the only way to refund
 * a client or to make the goodwill credit the founder asked for by name was a
 * hand-assembled request against production — or the provider's own dashboard, where no
 * ledger entry follows at all.
 *
 * What these tests pin, worst failure first:
 *
 * 1. **`recorded: false` ON A REFUND IS NOT A FAILURE.** It means the provider accepted
 *    it and the ledger entry lands on the webhook. An operator who reads it as "did not
 *    work" issues a second refund — a second amount out of our account for one payment.
 *    Both arms must read as success and say "do not issue it again".
 * 2. **A refund is irreversibly outbound, so it carries a typed confirmation the API
 *    never asked for** — the payment's own reference, re-keyed, invalidated when the
 *    payment changes. That is the opposite call from `plan-tier`, and deliberately so.
 * 3. **The grant's step-up header carries the AMOUNT at two decimals**, unconditionally,
 *    and a changed figure invalidates the typed confirmation — a ceremony captured while
 *    granting ₹5,000 must not be replayable to grant ₹50,000.
 * 4. **Money crosses the wire as a STRING both ways** (hard rule 7), and an absent refund
 *    amount is ABSENT — never `"0"`, which is a different request the route refuses.
 * 5. **The ceiling is previewed where the operator types**, before the confirmation, in
 *    the route's own ordering: a ₹5,00,000 typo is told the number is impossible, not
 *    that its header is wrong.
 * 6. **Paid and given never blur** — the grant panel prints both lifetime figures at the
 *    moment one of them moves, which is the founder's guardrail on this feature.
 */

const TENANT = "0192f0aa-5555-7000-8000-0000000000f1";
const TENANT_PATH = `/v1/admin/tenants/${TENANT}`;
const CREDITS_READ = `${creditsPath(TENANT)}?limit=${LEDGER_LIMIT}`;
const REFUND_PATH = refundsPath(TENANT);
const GRANT_PATH = grantsPath(TENANT);
const REF = "pay_QK9xLm2026";

function tenant(): TenantSummary {
  return {
    id: TENANT,
    name: "Sri Traders",
    slug: "sri-traders",
    status: "active",
    plan_tier: "prepaid",
    vertical_template: "clinic",
    live_agents: 1,
    calls_7d: 0,
    leads: 0,
    last_call_at: null,
    holds: [],
    capped: false,
  };
}

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-5555-7000-8000-0000000000f2",
  role: "operator",
  permissions: ["org:read", "billing:read", "admin:tenants"],
};

const READER: AdminMe = { ...ME, role: "support", permissions: ["org:read"] };

function entry(): LedgerEntry {
  return {
    id: "0192f0aa-5555-7000-8000-0000000000f3",
    delta_inr: "2500.00",
    reason: "topup",
    ref: REF,
    balance_after_inr: "2500.00",
    occurred_at: "2026-09-12T05:30:00Z",
    reversible_inr: "2500.00",
  };
}

function payment(over: Partial<Payment> = {}): Payment {
  return {
    payment_ref: REF,
    credited_inr: "2500.00",
    entries: 1,
    first_at: "2026-09-12T05:30:00Z",
    ...over,
  };
}

function credits(over: Partial<Credits> = {}): Credits {
  return {
    tenant_id: TENANT,
    balance_inr: "2500.00",
    is_low: false,
    low_balance_threshold_inr: "200.00",
    granted_inr: "0.00",
    paid_inr: "2500.00",
    entries: [entry()],
    payments: [payment()],
    lots: [],
    override_packs: [],
    ...over,
  };
}

function refundResult(over: Partial<RefundResult> = {}): RefundResult {
  return {
    refund_id: "rfnd_QK9xLm77",
    payment_id: REF,
    amount_inr: "2500.00",
    recorded: true,
    balance_inr: "0.00",
    processing_days: 7,
    ...over,
  };
}

function grantResult(over: Partial<GrantResult> = {}): GrantResult {
  return {
    tenant_id: TENANT,
    entry_id: "0192f0aa-5555-7000-8000-0000000000f4",
    grant_ref: "console-abc",
    ref: "grant:console-abc",
    amount_inr: "5000.00",
    balance_inr: "7500.00",
    is_low: false,
    paid_inr: "2500.00",
    granted_inr: "5000.00",
    recorded: true,
    ...over,
  };
}

function render(routes: Partial<Routes> = {}) {
  return renderAdminRoute(<TenantCreditsPage params={routeParams({ tenantId: TENANT })} />, {
    [TENANT_PATH]: tenant(),
    [ADMIN_ME_PATH]: ME,
    [CREDITS_READ]: credits(),
    [trialPath(TENANT)]: null,
    ...routes,
  });
}

const REFUND_SUBMIT = { name: /Refund this payment/ };
const GRANT_SUBMIT = { name: /Give this credit/ };

function button(query: { name: RegExp }): HTMLButtonElement {
  return screen.getByRole("button", query) as HTMLButtonElement;
}

/**
 * Fill the refund form and WAIT for the control to go live.
 *
 * The wait is load-bearing: every admin control is disabled until `GET /v1/admin/me` has
 * answered (`useAdminAccess` fails CLOSED on the unknown), so an assertion made before
 * that settles would pass for a reason unrelated to the rule under test.
 */
async function fillRefund(over: { amount?: string; confirm?: string } = {}) {
  fireEvent.change(await screen.findByLabelText("Payment to refund"), {
    target: { value: REF },
  });
  fireEvent.change(screen.getByLabelText(/How much to refund/), {
    target: { value: over.amount ?? "" },
  });
  fireEvent.change(screen.getByLabelText("Why", { selector: "#refund-reason" }), {
    target: { value: "double charged on the September top-up" },
  });
  fireEvent.change(screen.getByLabelText(/Type the payment reference again/), {
    target: { value: over.confirm ?? REF },
  });
  await waitFor(() => expect(button(REFUND_SUBMIT).disabled).toBe(false));
}

async function fillGrant(amount = "5000", confirm?: string) {
  fireEvent.change(await screen.findByLabelText("How much to give"), {
    target: { value: amount },
  });
  fireEvent.change(screen.getByLabelText("Why", { selector: "#grant-reason" }), {
    target: { value: "apology for the outage on 14 Sep" },
  });
  fireEvent.change(screen.getByLabelText(/Type the grant amount again/), {
    target: { value: confirm ?? "5000.00" },
  });
  await waitFor(() => expect(button(GRANT_SUBMIT).disabled).toBe(false));
}

describe("refunding a payment", () => {
  it("sends the payment reference and the reason, with no amount when refunding all of it", async () => {
    const { calls } = await render({ [`POST ${REFUND_PATH}`]: refundResult() });

    await fillRefund();
    fireEvent.click(button(REFUND_SUBMIT));

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === REFUND_PATH)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === REFUND_PATH);
    const body = JSON.parse(post?.body ?? "{}");
    expect(body.payment_id).toBe(REF);
    expect(body.reason).toBe("double charged on the September top-up");
    // ABSENT, not `"0"` and not `null`: absent means "the whole top-up recorded for this
    // payment", which the route reads off the ledger so nobody retypes a figure.
    expect("amount_inr" in body).toBe(false);
    // The route accepts no confirmation header — a header the API ignores is a
    // confirmation of nothing. The ceremony here is the re-keyed reference on screen.
    expect(post?.headers["X-Confirm-Action"]).toBeUndefined();
    expect(post?.headers["X-Impersonate-Org"]).toBeUndefined();
  });

  it("sends a partial amount as the exact STRING that was typed", async () => {
    const { calls } = await render({
      [`POST ${REFUND_PATH}`]: refundResult({ amount_inr: "500.10" }),
    });

    await fillRefund({ amount: "500.10" });
    fireEvent.click(button(REFUND_SUBMIT));

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === REFUND_PATH)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === REFUND_PATH);
    // hard rule 7: a `Number()` anywhere on this path turns ₹500.10 into a paise dispute,
    // and the route refuses the JSON number outright.
    expect(JSON.parse(post?.body ?? "{}").amount_inr).toBe("500.10");
  });

  it("reads an in-flight refund as ACCEPTED, never as a failure", async () => {
    const { container } = await render({
      // `recorded: false` = the provider took it and the ledger entry lands on the
      // `refund.processed` webhook. THE defect this panel exists to prevent is rendering
      // this as "did not work" and having the operator refund a second time.
      [`POST ${REFUND_PATH}`]: refundResult({ recorded: false, balance_inr: null }),
    });

    await fillRefund();
    fireEvent.click(button(REFUND_SUBMIT));

    await waitFor(() => {
      expect(container.textContent).toContain("accepted by the provider");
    });
    expect(container.textContent).toContain("Do not issue it again");
    expect(container.textContent).toContain("has not settled yet");
    expect(container.textContent).not.toContain("did not");
  });

  it("reads a processed refund as credited, with the balance after it", async () => {
    const { container } = await render({ [`POST ${REFUND_PATH}`]: refundResult() });

    await fillRefund();
    fireEvent.click(button(REFUND_SUBMIT));

    await waitFor(() => {
      expect(container.textContent).toContain("refunded to Sri Traders");
    });
    expect(container.textContent).toContain("matching entry is on this wallet");
    expect(container.textContent).toContain("rfnd_QK9xLm77");
  });

  it("states the absence when the answer carried no balance, rather than printing ₹0.00", async () => {
    const { container } = await render({
      // Processed, so the entry was written — but the route answered without a balance.
      // "We could not derive it" is a different fact from "the wallet is empty".
      [`POST ${REFUND_PATH}`]: refundResult({ balance_inr: null }),
    });

    await fillRefund();
    fireEvent.click(button(REFUND_SUBMIT));

    await waitFor(() => {
      expect(container.textContent).toContain("refunded to Sri Traders");
    });
    expect(container.textContent).toContain("balance was not reported with this answer");
    expect(container.textContent).not.toContain("Balance is now ₹0.00");
  });

  it("will not issue a refund until the payment reference is re-keyed", async () => {
    const { calls } = await render({ [`POST ${REFUND_PATH}`]: refundResult() });

    await fillRefund();
    fireEvent.change(screen.getByLabelText(/Type the payment reference again/), {
      target: { value: "" },
    });

    expect(button(REFUND_SUBMIT).disabled).toBe(true);
    fireEvent.click(button(REFUND_SUBMIT));
    expect(calls.some((c) => c.method === "POST" && c.path === REFUND_PATH)).toBe(false);
  });

  it("refuses an amount larger than the payment, before the round trip", async () => {
    const { calls, container } = await render({ [`POST ${REFUND_PATH}`]: refundResult() });

    await fillRefund();
    fireEvent.change(screen.getByLabelText(/How much to refund/), {
      target: { value: "9999.00" },
    });

    expect(button(REFUND_SUBMIT).disabled).toBe(true);
    fireEvent.click(button(REFUND_SUBMIT));
    expect(calls.some((c) => c.method === "POST" && c.path === REFUND_PATH)).toBe(false);
    expect(container.textContent).toContain("more than the ₹2500.00 this payment credited");
  });

  it("says which payments it cannot move, rather than letting the provider say it", async () => {
    const { container } = await render();

    await screen.findByText("Only a payment the provider captured");
    expect(container.textContent).toContain("has never seen");
    expect(container.textContent).toContain("compensating adjustment");
  });

  it("renders the provider's own refusal when the refund is rejected", async () => {
    const { container } = await render({
      [`POST ${REFUND_PATH}`]: problem(502, {
        title: "The payment provider refused this refund",
        detail: "We could not refund that payment.",
      }),
    });

    await fillRefund();
    fireEvent.click(button(REFUND_SUBMIT));

    await waitFor(() => {
      expect(container.textContent).toContain("We could not refund that payment.");
    });
  });

  it("offers no form when there is no payment to refund", async () => {
    const { container } = await render({
      [CREDITS_READ]: credits({ payments: [], entries: [] }),
    });

    await screen.findByText(/There is nothing here to refund/);
    expect(screen.queryByLabelText("Payment to refund")).toBeNull();
    expect(container.textContent).toContain("it cannot create one");
  });
});

describe("granting credit out of nothing", () => {
  it("sends a string amount with the step-up header bound to that amount", async () => {
    const { calls } = await render({ [`POST ${GRANT_PATH}`]: grantResult() });

    await fillGrant();
    fireEvent.click(button(GRANT_SUBMIT));

    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === GRANT_PATH)).toBe(true);
    });
    const post = calls.find((c) => c.method === "POST" && c.path === GRANT_PATH);
    const body = JSON.parse(post?.body ?? "{}");
    expect(body.amount_inr).toBe("5000");
    expect(body.reason).toBe("apology for the outage on 14 Sep");
    // Minted by the console, one per opened form: a second CLICK converges on it, a
    // second DECISION does not. Two genuine ₹5,000 gifts two months apart are ordinary.
    expect(typeof body.grant_ref).toBe("string");
    expect(body.grant_ref.length).toBeGreaterThan(2);
    // UNCONDITIONAL and bound to the figure, quantized to two decimals exactly as
    // `credit_grant_confirmation` does — `5000` and `5000.00` are one grant.
    expect(post?.headers["X-Confirm-Action"]).toBe(creditGrantConfirmation("5000"));
    expect(creditGrantConfirmation("5000")).toBe("grant_credits:5000.00");
    expect(post?.headers["X-Impersonate-Org"]).toBeUndefined();
  });

  it("invalidates the typed confirmation when the amount changes", async () => {
    const { calls } = await render({ [`POST ${GRANT_PATH}`]: grantResult() });

    await fillGrant();
    // The operator adds a zero. The confirmation named ₹5,000 — and so would the header,
    // which is exactly what stops a ceremony for one figure authorising another.
    fireEvent.change(screen.getByLabelText("How much to give"), {
      target: { value: "50000" },
    });

    expect(button(GRANT_SUBMIT).disabled).toBe(true);
    fireEvent.click(button(GRANT_SUBMIT));
    expect(calls.some((c) => c.method === "POST" && c.path === GRANT_PATH)).toBe(false);
  });

  it("tells an operator a figure is impossible before asking about the ceremony", async () => {
    const { calls, container } = await render({ [`POST ${GRANT_PATH}`]: grantResult() });

    await fillGrant();
    fireEvent.change(screen.getByLabelText("How much to give"), {
      target: { value: "500000" },
    });

    await waitFor(() => {
      expect(container.textContent).toContain("A grant is between ₹1.00 and ₹50000.00");
    });
    // The route's own ordering: the ceiling first, so a typo is not sent to fix a header
    // and re-submitted unchanged.
    expect(container.textContent).toContain("grant it in parts");
    expect(button(GRANT_SUBMIT).disabled).toBe(true);
    fireEvent.click(button(GRANT_SUBMIT));
    expect(calls.some((c) => c.method === "POST" && c.path === GRANT_PATH)).toBe(false);
  });

  it("shows what the wallet has been PAID for beside what it has been GIVEN", async () => {
    const { container } = await render({
      [CREDITS_READ]: credits({ paid_inr: "2500.00", granted_inr: "15000.00" }),
    });

    await screen.findByText("Give this client credit");
    // The founder's guardrail: the two never blur, and the running total is in front of
    // the operator at the moment they add to it — not on a screen they might not open.
    expect(container.textContent).toContain("Paid for, lifetime");
    expect(container.textContent).toContain("Given, lifetime");
    expect(container.textContent).toContain("₹15,000.00");
  });

  it("reports a replayed grant as having moved nothing", async () => {
    const { container } = await render({
      [`POST ${GRANT_PATH}`]: grantResult({ recorded: false }),
    });

    await fillGrant();
    fireEvent.click(button(GRANT_SUBMIT));

    await waitFor(() => {
      expect(container.textContent).toContain("already on this wallet");
    });
    expect(container.textContent).toContain("has not been credited a second time");
  });

  it("says a grant is not a payment, on the panel itself", async () => {
    const { container } = await render();

    await screen.findByText("Give this client credit");
    expect(container.textContent).toContain("no payment behind it");
    expect(container.textContent).toContain("reports it separately");
  });

  it("disables both controls, with their reasons, for a session that may not write", async () => {
    const { calls } = await render({
      [ADMIN_ME_PATH]: READER,
      [`POST ${GRANT_PATH}`]: grantResult(),
      [`POST ${REFUND_PATH}`]: refundResult(),
    });

    await screen.findByText(/refund a payment/);
    expect(screen.getByText(/give a client credit/)).toBeDefined();
    expect(button(REFUND_SUBMIT).disabled).toBe(true);
    expect(button(GRANT_SUBMIT).disabled).toBe(true);
    fireEvent.click(button(REFUND_SUBMIT));
    fireEvent.click(button(GRANT_SUBMIT));
    expect(
      calls.some(
        (c) => c.method === "POST" && (c.path === REFUND_PATH || c.path === GRANT_PATH),
      ),
    ).toBe(false);
  });
});

/**
 * Both new panels, scanned with a payment on the wallet.
 *
 * The credits screen is in the `a11y.test.tsx` sweep, but its fixture there is what that
 * table needs for the screen as a whole; these two panels render their FORMS only when
 * the wallet has a payment on it, and the refund panel's confirmation and amount fields
 * only after one is chosen. So the states that carry the markup are scanned here.
 */
describe("the two new panels' accessibility", () => {
  it("has no axe violations with a payment chosen for refund", async () => {
    const { container } = await render({ [`POST ${REFUND_PATH}`]: refundResult() });

    await fillRefund();
    await fillGrant();
    await expectNoA11yViolations(
      container,
      "admin/tenants/[tenantId]/credits (refund + grant open)",
    );
  });
});
