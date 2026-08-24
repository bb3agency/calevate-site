import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import TenantInvoicePage from "@/app/admin/tenants/[tenantId]/invoice/page";
import { formatINR } from "@/components/ui";
import type { Invoice } from "@/lib/api/invoice";

import { problem } from "./harness";
import { renderAdminRoute, routeParams } from "./adminRoute";

/**
 * The invoice screen, ranked FIRST of this slice — it is the only one that produces a
 * document leaving the company.
 *
 * Everything else an operator gets wrong here is recoverable by looking again. A wrong
 * figure on this page is printed, filed by an accountant, and argued about months later
 * against the client's own books; and the direction the old code was wrong in — a rate
 * rounded to paise — is wrong IN OUR FAVOUR, which is the version a regulator asks about.
 *
 * The three failures pinned below, in the order they would cost:
 *
 * 1. **A rate must keep its published precision.** `overage_rate_inr` is NUMERIC(12,4)
 *    and `billing/service.py::rate_to_display` publishes it unrounded ON PURPOSE, because
 *    the invoice promises `qty × unit = amount`. Put ₹7.1250/min through `formatINR` and
 *    the document says ₹7.12, the multiplication stops working, and the only arithmetic a
 *    client performs on an invoice fails in the direction that looks like overcharging.
 * 2. **A failed request must not render a ₹0.00 invoice.** "You owe nothing" is a claim
 *    about a month's business. A 500 is not evidence for it, and a printable sheet is the
 *    worst possible place for a plausible-looking zero.
 * 3. **Totals must agree with the client's own usage screen to the paisa.** Both format
 *    the SERVER's decimal string with `formatINR` and neither parses it; a `Number()`
 *    anywhere on this path is how ₹10,159.00 becomes ₹10,158.999999999998 on the one
 *    screen a client checks against their books.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000aa";
const PATH = `/v1/admin/tenants/${TENANT}/invoice`;

/** The current IST month, exactly as the page computes it for its default request. */
function currentISTMonth(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }).slice(0, 7);
}

const MONTH = currentISTMonth();
const ROUTE = `${PATH}?month=${encodeURIComponent(MONTH)}`;

/**
 * A two-rung overage month: the shape that makes the rounding question decidable.
 *
 * Every figure is a STRING, as the API sends them. The premium rung is quoted at four
 * decimals — a real plan shape, and the one `formatINR` would silently destroy.
 *
 * The identity block is a CONFIGURED, GST-registered supply (SLICE AL), so this file
 * keeps testing the money questions it was written for. What the document does when the
 * identity is absent is `clientInvoice.test.tsx`'s first test, on the same shared sheet.
 */
function invoice(over: Partial<Invoice> = {}): Invoice {
  return {
    invoice_number: "CAL-202608-0192f0aa",
    month: MONTH,
    generated_at: "2026-08-13T04:30:00Z",
    document_type: "tax_invoice",
    document_blockers: [],
    supplier: {
      legal_name: "Calevate Technologies Private Limited",
      address: "Plot 42, Madhapur, Hyderabad 500081",
      gstin: "36AABCC1234D1Z5",
      state_name: "Telangana",
      sac: "998315",
    },
    organization: {
      id: TENANT,
      name: "Sri Traders",
      billing_email: "accounts@sritraders.example",
      gstin: "29AAACR5055K1Z6",
      state_name: "Karnataka",
    },
    place_of_supply: {
      state_code: "29",
      state_name: "Karnataka",
      supply_type: "interstate",
      basis: "Location of the recipient, a registered person (IGST Act s.12(2)(a)).",
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
        // Deliberately does NOT quote the rate: the server's real description does, and
        // an assertion satisfied by the description text would pass with the Unit column
        // rounded to paise — which is the exact defect this file exists to catch.
        description: "Extra calling minutes beyond the plan",
        qty: "20.5",
        unit_inr: "7.1250",
        amount_inr: "146.06",
        sac: "998315",
      },
    ],
    subtotal_inr: "1015900.00",
    gst_rate_pct: "18",
    gst_inr: "182862.00",
    tax_components: [{ label: "IGST", rate_pct: "18", amount_inr: "182862.00" }],
    total_inr: "1198762.00",
    usage: { minutes_used: "220.5", calls: 118, included_minutes: 200 },
    ...over,
  };
}

async function render(answer: unknown) {
  return await renderAdminRoute(<TenantInvoicePage params={routeParams({ tenantId: TENANT })} />, {
    [ROUTE]: answer,
  });
}

describe("the tenant invoice", () => {
  it("prints the RATE at the precision the server published, never rounded to paise", async () => {
    const { container } = await render(invoice());

    await screen.findByText("TAX INVOICE");

    // The whole point: four decimals survive to the CELL — asserted on the cell itself,
    // because the string also appears in some server-composed descriptions and a
    // `textContent` match there would be satisfied by prose while the figure was wrong.
    expect(screen.getByText("₹7.1250").tagName).toBe("TD");
    // The rounding `formatINR` would have produced. It breaks `qty × unit = amount` on
    // the one line a client checks with a calculator, in our favour.
    expect(screen.queryByText("₹7.12")).toBeNull();
    expect(screen.queryByText("₹7.13")).toBeNull();
    // And the quantity is the server's decimal string, not a parsed number.
    expect(screen.getByText("20.5").tagName).toBe("TD");
    expect(container.textContent).toContain("Extra calling minutes beyond the plan");
  });

  it("groups the TOTALS the way the client's own usage screen does, to the paisa", async () => {
    const data = invoice();
    const { container } = await render(data);

    await screen.findByText("TAX INVOICE");

    // Indian grouping, two decimals, digits untouched — the same function, on the same
    // string, as `/c/[slug]/usage`. A disagreement of one paisa between the two is a
    // support ticket at best.
    expect(container.textContent).toContain(formatINR(data.subtotal_inr));
    expect(container.textContent).toContain(formatINR(data.gst_inr));
    expect(container.textContent).toContain(formatINR(data.total_inr));
    expect(container.textContent).toContain("₹11,98,762.00");
    // The ungrouped form is what the screen used to print by interpolating the raw
    // string, and it is unreadable on a document meant for a human.
    expect(container.textContent).not.toContain("₹1198762.00");
    // The GST RATE is a rate: 18%, not ₹18.00.
    expect(container.textContent).toContain("18%");
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

    // No document at all — not an empty one, and above all not a ₹0.00 one.
    expect(container.textContent).not.toContain("TAX INVOICE");
    expect(container.textContent).not.toContain("₹0.00");
    expect(container.textContent).not.toContain("No charges this month");
    // The server's own sentence, not a flattened "something went wrong": an operator on
    // a support call needs to know whether to retry or to escalate.
    expect(container.textContent).toContain("The usage ledger is unavailable.");
  });

  it("will not print what has not loaded", async () => {
    await render(
      problem(403, { detail: "You do not have permission to do this.", retryable: false }),
    );

    // A sheet of paper that looks like an invoice and carries no figures is worse than
    // no sheet: it gets filed. The control says so by being unavailable.
    const print = await screen.findByRole("button", { name: /Print/ });
    expect((print as HTMLButtonElement).disabled).toBe(true);
  });

  it("renders a usage-only statement when nothing was billable, and still shows the totals", async () => {
    const { container } = await render(
      invoice({
        line_items: [],
        subtotal_inr: "0.00",
        gst_inr: "0.00",
        total_inr: "0.00",
      }),
    );

    await screen.findByText("TAX INVOICE");

    // An empty `line_items` is the API's deliberate answer (a ₹0.00 line invites a
    // dispute about nothing), so here the zero IS the fact — the difference from the
    // failing case above is that the server said it.
    expect(container.textContent).toContain("No charges this month");
    expect(container.textContent).toContain("₹0.00");
    expect(container.textContent).toContain("118");
  });

  it("asks for one tenant's month and nothing wider", async () => {
    const { calls } = await render(invoice());

    await screen.findByText("TAX INVOICE");

    // One request, tenant in the path, month in the query — a cross-tenant screen that
    // fetched the directory to find one row is how a detail page costs the whole console.
    expect(calls.map((c) => c.path)).toEqual([ROUTE]);
    expect(calls[0]?.method).toBe("GET");
  });
});
