import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import UsagePage from "@/app/c/[slug]/usage/page";
import type { Me } from "@/lib/api/client";
import type { Caps } from "@/lib/api/caps";
import type { UsagePanel } from "@/lib/api/hooks";

import { problem, renderClientPage } from "./harness";

/**
 * The usage panel — the screen a client checks against their own books, which makes it
 * the screen where a rounded rupee is not a rounding error but a dispute.
 *
 * `tests/money.test.tsx` already holds the ARITHMETIC (paise addition, a null fee, a
 * negative total). This file holds what the design pass could break and a type checker
 * could not see:
 *
 * 1. **A rupee amount that went through a float.** Every money field on `UsagePanelOut`
 *    is an exact decimal STRING; `Number("10159.00")` is how ₹10,159.00 becomes
 *    ₹10,158.999999999998 on an invoice a client is reading.
 * 2. **A RATE rounded to paise.** `overage_rate_inr` is NUMERIC(12,4) and the server
 *    publishes it unrounded on purpose (`billing/service.py::rate_to_display`). Printing
 *    ₹7.12 for a ₹7.1250 rate breaks the one sum a client performs by hand — qty × unit
 *    — and it breaks it in OUR favour, which is the worst possible direction.
 * 3. **A 403 dressed as an outage.** `billing:read` is an owner permission staff do not
 *    hold; the screen says so instead of rendering a red alert.
 * 4. **Figures under a failed request.** A refusal, never a comfortable ₹0.00.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["billing:read", "org:manage"],
  impersonating: false,
  organization: {
    id: "o1",
    name: "Sri Clinic",
    slug: "acme",
    status: "active",
  },
};

const STAFF: Me = {
  ...ME,
  role: "staff",
  permissions: ["calls:read", "leads:read"],
};

const CAPS: Caps = {
  capped: false,
  month: "2026-08",
  minutes_used: "120.5",
  spend_used_inr: "0.30",
  client_cap_minutes: null,
  client_cap_spend_inr: null,
  effective_cap_minutes: null,
  effective_cap_spend_inr: null,
  plan_cap_minutes: null,
  plan_cap_spend_inr: null,
};

function usage(over: Partial<UsagePanel> = {}): UsagePanel {
  return {
    month: "2026-08",
    calls: 41,
    capped: false,
    cap_minutes: null,
    minutes_left: null,
    included_minutes: 500,
    minutes_used: "120.50",
    credit_balance_inr: null,
    monthly_fee_inr: "4999.00",
    overage_cost_inr: "10159.00",
    overage_minutes: "1563.00",
    overage_minutes_premium: "1563.00",
    overage_minutes_value: "0.00",
    overage_rate_inr: "6.5000",
    overage_rate_value_inr: null,
    // D-455: the model surcharge, unset on every plan today — so a ₹0.00 total and no
    // models named is the shipped shape of this panel.
    llm_surcharge_rate_inr: null,
    llm_surcharge_minutes: "0.00",
    llm_surcharge_inr: "0.00",
    llm_surcharge_models: [],
    // THE SERVER'S OWN TOTAL of the three charge components above (retainer +
    // overage + model surcharge). Stated rather than derived, because it is a FIELD
    // now: a fixture that computed it would be re-implementing the arithmetic the
    // screen stopped doing, and would agree with a broken screen.
    month_charges_inr: "15158.00",
    plan_tier: "managed",
    spend_used_inr: "15158.00",
    ...over,
  };
}

/**
 * A month a client's own model choice made dearer (D-455).
 *
 * `plans.llm_model_surcharge` is unset on every plan today, so this is the state a
 * founder's number creates rather than one the fixtures above cover — and it is the one
 * where the panel and the invoice could disagree, which is what this exercises.
 */
function surchargedUsage(): UsagePanel {
  return usage({
    llm_surcharge_rate_inr: "1.5000",
    llm_surcharge_minutes: "40.00",
    llm_surcharge_inr: "60.00",
    llm_surcharge_models: ["gpt-4.1-mini"],
    // ₹4,999.00 + ₹10,159.00 + ₹60.00. The total MOVES with the surcharge, and a fixture
    // that left it at the base figure would let a screen printing a stale total pass.
    month_charges_inr: "15218.00",
  });
}

function routes(over: Record<string, unknown> = {}) {
  return {
    "/v1/me": ME,
    "/v1/usage": usage(),
    "/v1/billing/caps": CAPS,
    ...over,
  };
}

const page = <UsagePage />;

describe("the usage panel", () => {
  it("prints rupees from the string the API sent, without going through a float", async () => {
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Extra charges");
    // Grouped the Indian way, paise intact, and identical on the tile and in the table —
    // one amount, one shape.
    expect(container.textContent).toContain("₹10,159.00");
    // What a `Number()` on the way past would have produced, in either of its two
    // signature forms: the float artefact, or the silently dropped paise.
    expect(container.textContent).not.toContain("10158.99");
    expect(container.textContent).not.toContain("₹10159 ");
    // 4999.00 + 10159.00, added in paise.
    expect(container.textContent).toContain("₹15,158.00");
    // The currency is INR. The design this came from was priced in dollars.
    expect(container.textContent).not.toContain("$");
  });

  it("names the model upgrade on its own line and puts it in the total (D-455)", async () => {
    // THE DEFECT THIS PINS. `plans.llm_model_surcharge` prices a client's own model
    // choice, and "Total so far" used to be `plan fee + overage` — so a client who moved
    // their agents onto the dearer model would have read a total ₹60 below the statement
    // they were sent. A screen showing one number while the invoice charges another is
    // exactly what this whole slice exists to remove.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/usage": surchargedUsage() }),
    );

    await screen.findByText("Extra charges");
    // The MODEL is named, because it is the decision that caused the number, and the
    // line multiplies out: 40.00 × ₹1.5000 = ₹60.00.
    expect(container.textContent).toContain("AI model upgrade, gpt-4.1-mini");
    expect(container.textContent).toContain("40.00 min × ₹1.5000");
    expect(container.textContent).toContain("₹60.00");
    // 4999.00 + 10159.00 + 60.00, added in paise.
    expect(container.textContent).toContain("₹15,218.00");
  });

  /**
   * THE CHARGE POINTS AT THE CONTROL THAT CAUSED IT.
   *
   * A model surcharge is the one line on this panel that an owner can act on themselves:
   * D-454 made the model a client's choice, so "why am I paying this" and "how do I stop
   * paying it" have the same answer and it is a screen in this console. Without the link
   * the honest next step is a support ticket about a charge we deliberately handed them
   * the control over.
   *
   * It is conditional on the same figure as the row itself. A pointer to the model picker
   * on a month nobody was surcharged for is an invitation to spend money, printed under a
   * heading about a bill.
   */
  it("sends an owner from the upgrade charge to the setting that causes it", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/usage": surchargedUsage() }),
    );

    await screen.findByText("Extra charges");
    const link = screen.getByRole("link", { name: "AI model" });
    expect(link.getAttribute("href")).toBe("/c/acme/settings/models");
    expect(container.textContent).toContain("ran a model you chose");
  });

  it("does not offer the model picker from a month nothing was surcharged", async () => {
    await renderClientPage(page, routes());

    await screen.findByText("Extra charges");
    expect(screen.queryByRole("link", { name: "AI model" })).toBeNull();
  });

  it("prints no upgrade line on a month nothing was surcharged", async () => {
    // Every plan today quotes no surcharge, so this is the shipped shape: a ₹0.00 row
    // invites a question about nothing, and the total is what it always was.
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Extra charges");
    expect(container.textContent).not.toContain("AI model upgrade");
    expect(container.textContent).toContain("₹15,158.00");
  });

  it("quotes the per-minute rate at the precision the server published it", async () => {
    // NUMERIC(12,4). `formatINR` keeps exactly two decimals, so putting a rate through it
    // prints ₹6.50 for a ₹6.5000 rate — harmless here — and ₹7.12 for ₹7.1250, which is
    // 0.4% of every extra minute and makes the invoice line fail the client's own
    // multiplication.
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/usage": usage({ overage_rate_inr: "7.1250" }) }),
    );

    // Wait on the panel, then judge the rate — so a rounded rate fails on the assertion
    // that explains itself rather than on a "could not find the text" timeout.
    await screen.findByText("Extra charges");
    // Not "does not contain ₹7.12" — that is a prefix of the correct answer. The rate
    // must not appear TRUNCATED to two decimals anywhere on the screen.
    expect(
      container.textContent,
      "a rate must not be rounded to paise",
    ).not.toMatch(/₹7\.12(?!5)/);
    expect(container.textContent).toContain("₹7.1250 per extra minute");
  });

  it("prints the metered minutes exactly as sent, trailing zero and all", async () => {
    // `minutes_used` is a decimal string too. `Number("120.50")` renders "120.5", and a
    // client comparing the screen to the invoice finds two different figures.
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Minutes used");
    expect(container.textContent).toContain("120.50");
  });

  it("explains a missing permission instead of answering with an error", async () => {
    // `GET /v1/usage` and `GET /v1/billing/caps` both require `billing:read`, which staff
    // do not hold (SEC-COMP §5). Before the gate, a staff user reached this screen from
    // the nav and was shown a red alert — a refusal we could see coming, delivered as a
    // fault.
    const { container } = await renderClientPage(
      page,
      // The usage request still goes out and is still refused; the screen must answer
      // with the sentence, not with the 403.
      { "/v1/me": STAFF, "/v1/usage": problem(403, { title: "Forbidden" }) },
    );

    await screen.findByText(/limited to the account owner/);
    expect(
      screen.queryByRole("alert"),
      "a permission is not a fault",
    ).toBeNull();
    expect(container.textContent).not.toContain("₹");
    expect(container.textContent).not.toContain("Total so far");
    // The spending-limit form belongs to the same permission and must not appear either.
    expect(screen.queryByLabelText("Minutes")).toBeNull();
  });

  it("shows a refusal instead of figures when the request fails", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/usage": problem(503, {
          title: "Service unavailable",
          detail: "We could not read this month's usage.",
        }),
      }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    // "₹0.00" is the comfortable lie here: a client who cannot be billed reads it as a
    // free month. Nothing on the panel may render a figure the server did not send.
    expect(container.textContent).not.toContain("₹0.00");
    expect(container.textContent).not.toContain("Total so far");
    expect(container.textContent).not.toContain("Extra charges");
    expect(container.textContent).not.toContain("Billing month");
  });

  it("says a cap has stopped outgoing calls, and that incoming ones still get through", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/usage": usage({ capped: true, minutes_left: 0 }) }),
    );

    await screen.findByText(/Outgoing calls are paused for this month/);
    // The sentence that prevents the support call: a stopped account looks like an
    // outage until someone says which half of it stopped.
    expect(container.textContent).toContain(
      "People calling you still get through.",
    );
    expect(container.textContent).toContain("About 0 minutes");
  });

  it("offers no runway figure when the server did not compute one", async () => {
    // `minutes_left` is null for a managed plan with no cap. "About 0 minutes left" would
    // read as an account about to stop dialling.
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Minutes used");
    expect(container.textContent).not.toContain("of calling left this month");
  });
});
