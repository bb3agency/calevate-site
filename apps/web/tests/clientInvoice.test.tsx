import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatINR } from "@/components/ui";
import type { Invoice } from "@/lib/api/invoice";
import { formatBillingMonth } from "@/lib/billingMonth";
import { GST_STATUS_SENTENCE } from "@/lib/gstStatus";

import { HUB_STATEMENTS_ROUTE, renderBillingHub } from "./billingHub";
import { problem } from "./harness";
import { EMPTY_WALLET_LOTS } from "./fixtures/sharedReads";

/**
 * The client's own invoice (SLICE AL / BRD §51 — the persona that pays it).
 *
 * Until this screen existed, the only way to see a Calevate invoice was the admin
 * console. What lands here is not a client-flavoured summary but THE document: the sheet
 * is `components/invoiceDocument.tsx`, shared with `/admin/tenants/[tenantId]/invoice`,
 * and the API is one computation behind two routes.
 *
 * Four things this file pins, in the order they would cost:
 *
 * 1. **The heading is the SERVER's claim, never the browser's.** A page that printed
 *    "TAX INVOICE" over a document with no GSTIN would manufacture the exact defect this
 *    slice removes, so the refusal path is tested before the happy one.
 * 2. **It asks for its own account and nothing wider.** No tenant id in the path — the
 *    server takes it from the principal.
 * 3. **A failed request is a refusal, not a ₹0.00 invoice** (§52). "You owe nothing" is a
 *    claim about a month's business and a 500 is not evidence for it.
 * 4. **Money is the server's string, formatted and never parsed** (hard rule 7).
 */

const MONTH = new Date()
  .toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" })
  .slice(0, 7);
const ROUTE = `/v1/billing/invoice?month=${encodeURIComponent(MONTH)}`;

const ME = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["wallet:read", "billing:read", "org:read"],
  impersonating: false,
  organization: {
    id: "o1",
    name: "Sri Traders",
    slug: "acme",
    status: "active",
  },
};

/**
 * A CONFIGURED, registered supply: everything Rule 46 wants, on an inter-State supply so
 * the IGST branch renders. Every figure is a STRING, as the API sends them.
 */
function invoice(over: Partial<Invoice> = {}): Invoice {
  return {
    invoice_number: "CAL-202608-0192f0aa",
    month: MONTH,
    generated_at: "2026-08-13T04:30:00Z",
    document_type: "tax_invoice",
    tax_note: null,
    supplier: {
      legal_name: "Calevate",
      address: "Plot 42, Madhapur, Hyderabad 500081",
      gstin: "36AABCC1234D1Z5",
      state_name: "Telangana",
      sac: "998315",
    },
    organization: {
      id: "o1",
      name: "Sri Traders",
      billing_email: "accounts@sritraders.example",
      gstin: "29AAACR5055K1Z6",
      state_name: "Karnataka",
    },
    place_of_supply: {
      state_code: "29",
      state_name: "Karnataka",
      supply_type: "interstate",
      basis:
        "Location of the recipient, a registered person (IGST Act s.12(2)(a)).",
    },
    line_items: [
      {
        description: "Monthly plan fee",
        qty: "1",
        unit_inr: "9999.00",
        amount_inr: "9999.00",
        sac: "998315",
      },
      {
        // Deliberately does NOT quote the rate in its text: an assertion satisfied by the
        // description would pass with the Unit column rounded to paise, which is the
        // defect the invoice tests exist to catch.
        description: "Extra calling minutes beyond the plan",
        qty: "20.5",
        unit_inr: "7.1250",
        amount_inr: "146.06",
        sac: "998315",
      },
    ],
    subtotal_inr: "10145.06",
    gst_rate_pct: "18",
    gst_inr: "1826.11",
    tax_components: [{ label: "IGST", rate_pct: "18", amount_inr: "1826.11" }],
    total_inr: "11971.17",
    usage: { minutes_used: "220.5", calls: 118, included_minutes: 200 },
    ...over,
  };
}

/**
 * WHAT THE HUB AROUND THIS DOCUMENT READS. The statement is the bottom of the Transactions
 * tab of `/c/{slug}/billing` now (D-525), and the screen reads the wallet, its history and
 * the pack rate card on mount whatever tab is open. Routed with the emptiest honest answer,
 * because an unrouted request throws in this harness. `prepaid: false` keeps a balance out
 * of assertions this file makes about a printed document.
 */
const HUB_ROUTES = {
  "/v1/billing/wallet": {
    tenant_id: "o1",
    prepaid: false,
    balance_inr: "0.00",
    is_low: false,
    low_balance_threshold_inr: "200.00",
    outbound_stopped: false,
    runway: {
      basis: "empty",
      days: null,
      daily_burn_inr: null,
      history_days: 0,
      beyond_horizon: false,
      window_days: 30,
      min_history_days: 7,
      max_days: 365,
    },
    minutes_left: null,
    drawdown: {
      calls_inr: "0.00",
      ai_assist_inr: "0.00",
      adjustments_inr: "0.00",
      spent_inr: "0.00",
      added_inr: "0.00",
      refunded_inr: "0.00",
    },
  },
  "/v1/billing/wallet/ledger?limit=50": { entries: [], payments: [] },
  "/v1/billing/topups/packs": { list_rate_inr_per_min: "8.00", packs: [] },
  // An invoiced account holds no credit lots: the route answers an empty queue.
  "/v1/billing/wallet/lots": EMPTY_WALLET_LOTS,
};

/** The month's row in the statement list, which is what opens the document. */
const STATEMENTS = {
  statements: [
    {
      month: MONTH,
      closed: false,
      document_type: "bill_of_supply",
      invoice_number: "CAL-202608-0192f0aa",
      total_inr: "10145.06",
      credit_added_inr: "0.00",
      wallet_spent_inr: "0.00",
      calls: 41,
      minutes_used: "120.50",
    },
  ],
  next_before: null,
};

/**
 * The statement is a row of the Statements view since the round-2 redesign: the list is
 * `/v1/billing/statements`, and Open shows that month's document in a drawer — portalled
 * to <body>, so `container` is the body here. A session that may not read billing gets
 * the refusal in place of the list, and there is no row to open.
 */
async function render(answer: unknown, me: unknown = ME) {
  const rendered = await renderBillingHub(
    { "/v1/me": me, [ROUTE]: answer, [HUB_STATEMENTS_ROUTE]: STATEMENTS, ...HUB_ROUTES },
    "Statements",
  );
  const mayRead = (me as { permissions?: string[] }).permissions?.includes("billing:read");
  if (mayRead) {
    fireEvent.click(
      await screen.findByRole("button", { name: `Open the statement for ${formatBillingMonth(MONTH)}` }),
    );
  }
  return { ...rendered, container: document.body };
}

describe("the client's own invoice", () => {
  it("is a bill of supply that says the one GST sentence and names no setting (D-659)", async () => {
    const { container } = await render(
      invoice({
        document_type: "bill_of_supply",
        tax_note: `Bill of supply. ${GST_STATUS_SENTENCE} No input tax credit can be claimed against this document.`,
        gst_rate_pct: "0",
        gst_inr: "0.00",
        total_inr: "10145.06",
        supplier: {
          legal_name: "Calevate",
          address: "Plot 42, Madhapur, Hyderabad 500081",
          gstin: null,
          state_name: null,
          sac: null,
        },
        place_of_supply: {
          state_code: null,
          state_name: null,
          supply_type: "undetermined",
          basis: "No GST registration is configured for Calevate.",
        },
        tax_components: [],
      }),
    );

    await screen.findByText("BILL OF SUPPLY");

    // The words that must NOT appear. A document that looks like a tax invoice and is
    // not is worse than one that admits what it is.
    expect(container.textContent).not.toContain("TAX INVOICE");
    expect(container.textContent).toContain("This is not a tax invoice.");
    expect(container.textContent).toContain(GST_STATUS_SENTENCE);
    expect(container.textContent).toContain("No input tax credit can be claimed");
    // Unregistered is the normal state, not a fault: no settings name, no "missing".
    expect(container.textContent).not.toMatch(/GST_SUPPL|Missing configuration/i);
    expect(container.textContent).toContain(formatINR("10145.06"));
  });

  it("falls back to the shared sentence when the server sends no note", async () => {
    const { container } = await render(
      invoice({ document_type: "bill_of_supply", tax_note: null, tax_components: [] }),
    );
    await screen.findByText("BILL OF SUPPLY");
    expect(container.textContent).toContain(GST_STATUS_SENTENCE);
    expect(container.textContent).not.toMatch(/GST_SUPPL/);
  });

  it("prints every Rule 46 particular once the identity is configured", async () => {
    const { container } = await render(invoice());

    await screen.findByText("TAX INVOICE");

    // Supplier: the LEGAL ENTITY and its registered address, not the brand word
    // "Calevate" that used to be hardcoded in this markup.
    expect(container.textContent).toContain("Calevate");
    expect(container.textContent).toContain(
      "Plot 42, Madhapur, Hyderabad 500081",
    );
    expect(container.textContent).toContain("36AABCC1234D1Z5");
    // Recipient GSTIN — without it a B2B client cannot claim input credit.
    expect(container.textContent).toContain("29AAACR5055K1Z6");
    // Place of supply WITH the name of the State (Rule 46(n)), and why it is that one.
    expect(container.textContent).toContain("Karnataka (29)");
    expect(container.textContent).toContain("IGST Act s.12(2)(a)");
    // SAC on the line, where Rule 46(g) wants it.
    expect(screen.getAllByText("998315").length).toBeGreaterThan(0);
    expect(container.textContent).toContain("signature not required");
  });

  it("names the head of tax rather than a flat GST line", async () => {
    const { container } = await render(invoice());

    await screen.findByText("TAX INVOICE");

    // CGST, SGST/UTGST and IGST are three different ledgers on the recipient's side; tax
    // charged without saying which one cannot be claimed.
    expect(container.textContent).toContain("IGST @ 18%");
    expect(container.textContent).toContain(formatINR("1826.11"));
  });

  it("splits an intra-State supply into CGST and SGST", async () => {
    const { container } = await render(
      invoice({
        organization: {
          id: "o1",
          name: "Sri Traders",
          billing_email: "accounts@sritraders.example",
          gstin: "36AAACR5055K1Z7",
          state_name: "Telangana",
        },
        place_of_supply: {
          state_code: "36",
          state_name: "Telangana",
          supply_type: "intrastate",
          basis:
            "Location of the recipient, a registered person (IGST Act s.12(2)(a)).",
        },
        tax_components: [
          { label: "CGST", rate_pct: "9", amount_inr: "913.06" },
          { label: "SGST", rate_pct: "9", amount_inr: "913.05" },
        ],
      }),
    );

    await screen.findByText("TAX INVOICE");

    expect(container.textContent).toContain("CGST @ 9%");
    expect(container.textContent).toContain("SGST @ 9%");
    // The two halves are the SERVER's and are printed as sent — the browser never adds
    // them up, which is why an odd paisa can differ between them without anything here
    // needing to know.
    expect(container.textContent).toContain(formatINR("913.06"));
    expect(container.textContent).toContain(formatINR("913.05"));
  });

  it("prints the RATE at the precision the server published, never rounded to paise", async () => {
    await render(invoice());

    await screen.findByText("TAX INVOICE");

    // Asserted on the CELL: the string also appears in server-composed descriptions, and
    // a `textContent` match there would be satisfied by prose while the figure was wrong.
    expect(screen.getByText("₹7.1250").tagName).toBe("TD");
    // What `formatINR` would have produced. It breaks `qty × unit = amount` on the one
    // line a client checks with a calculator, in our favour.
    expect(screen.queryByText("₹7.12")).toBeNull();
    expect(screen.getByText("20.5").tagName).toBe("TD");
  });

  it("refuses rather than printing a zero invoice when the request fails", async () => {
    const { container } = await render(
      problem(500, {
        title: "Invoice could not be built",
        detail: "The usage ledger is unavailable.",
        retryable: true,
      }),
    );

    await screen.findByRole("alert");

    // Scoped to the statement drawer: the list behind it legitimately shows the month's
    // ₹0.00 credit-added column, which is a different claim from a zero invoice.
    const sheet = screen.getByRole("dialog");
    expect(container.textContent).not.toContain("TAX INVOICE");
    expect(container.textContent).not.toContain("BILL OF SUPPLY");
    expect(sheet.textContent).not.toContain("₹0.00");
    // The server's own sentence, not a flattened "something went wrong".
    expect(container.textContent).toContain("The usage ledger is unavailable.");
    // And nothing printable: a sheet that looks like an invoice and carries no figures
    // is worse than no sheet, because it gets filed.
    const print = await screen.findByRole("button", { name: /Print/ });
    expect((print as HTMLButtonElement).disabled).toBe(true);
  });

  it("asks for its own account's month and nothing wider", async () => {
    const { calls } = await render(invoice());

    await screen.findByText("TAX INVOICE");

    // No tenant id anywhere in the request: the server takes it from the principal, so
    // there is nothing here that could be pointed at another account.
    const invoiceCalls = calls.filter((c) =>
      c.path.startsWith("/v1/billing/invoice"),
    );
    expect(invoiceCalls.map((c) => c.path)).toEqual([ROUTE]);
    expect(invoiceCalls[0]?.method).toBe("GET");
  });

  it("tells a staff member why, instead of collecting a 403 that reads like an outage", async () => {
    const { container } = await render(invoice(), {
      ...ME,
      role: "staff",
      permissions: ["leads:read", "org:read", "wallet:read"],
    });

    // `billing:read` is an owner permission (SEC-COMP §5) and the nav shows this screen
    // to everyone, so the refusal is explained here rather than met as a red alert.
    // AWAITED: `/v1/me` decides this and is in flight on the first paint — nothing is
    // refused until the server has answered, so a screen never flashes an explanation it
    // is about to withdraw.
    await screen.findByText(/Statements are limited to the account owner/);
    expect(container.textContent).not.toContain("TAX INVOICE");
  });
});
