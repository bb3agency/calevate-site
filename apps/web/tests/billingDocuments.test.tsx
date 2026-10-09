import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InvoiceDocument } from "@/components/invoiceDocument";
import { ReceiptDocument } from "@/components/receiptDocument";
import type { Invoice } from "@/lib/api/invoice";
import type { PaymentReceipt } from "@/lib/api/wallet";
import { GST_STATUS_SENTENCE } from "@/lib/gstStatus";

import { expectNoA11yViolations } from "./a11y";

/**
 * The two billing documents a client downloads, rendered on their own.
 *
 * The screens around them are covered by `clientInvoice`, `adminInvoice` and `credits`;
 * this file pins what the sheets themselves promise after the layout redesign: the
 * document's legal name and GST wording come from the server, and every figure on the
 * paper is the server's decimal string, formatted and never computed in the browser.
 */

function billOfSupply(over: Partial<Invoice> = {}): Invoice {
  return {
    invoice_number: "CAL-202610-0192f0aa",
    month: "2026-10",
    generated_at: "2026-10-09T04:30:00Z",
    document_type: "bill_of_supply",
    tax_note: null,
    supplier: {
      legal_name: null,
      address: null,
      gstin: null,
      state_name: null,
      sac: "998315",
    },
    organization: {
      id: "o1",
      name: "Sri Traders",
      billing_email: "accounts@sritraders.example",
      gstin: null,
      state_name: null,
    },
    place_of_supply: {
      state_code: null,
      state_name: null,
      supply_type: "unknown",
      basis: "Not determined: no registered address on file.",
    },
    line_items: [
      { description: "Monthly plan fee", qty: "1", unit_inr: "2499.00", amount_inr: "2499.00", sac: "998315" },
      { description: "Extra calling minutes", qty: "0.2", unit_inr: "5.5000", amount_inr: "1.10", sac: "998315" },
    ],
    subtotal_inr: "2500.10",
    gst_rate_pct: "0",
    gst_inr: "0.00",
    tax_components: [],
    total_inr: "2500.10",
    usage: { calls: 12, included_minutes: 500, minutes_used: "88.5" },
    ...over,
  };
}

function receipt(over: Partial<PaymentReceipt> = {}): PaymentReceipt {
  return {
    document_type: "receipt",
    payment_ref: "pay_a1b2c3",
    amount_inr: "2500.10",
    received_at: "2026-10-01T09:00:00Z",
    entries: 1,
    supplier_legal_name: "BuiltByThree Technologies",
    supplier_address: "Hyderabad",
    organization_name: "Sri Clinic",
    organization_billing_email: "owner@sriclinic.example",
    note: `This is a receipt for calling credit added to your account. ${GST_STATUS_SENTENCE}`,
    ...over,
  };
}

/** The `<dd>` beside a `<dt>` label in a totals or metadata list. */
function valueBeside(container: HTMLElement, label: string): string | null {
  const term = Array.from(container.querySelectorAll("dt")).find((dt) => dt.textContent === label);
  return term?.nextElementSibling?.textContent ?? null;
}

describe("the invoice sheet", () => {
  it("is a BILL OF SUPPLY carrying the server's GST sentence, never a tax invoice", () => {
    const { container } = render(<InvoiceDocument data={billOfSupply()} />);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("BILL OF SUPPLY");
    expect(container.textContent).not.toContain("TAX INVOICE");
    const note = screen.getByRole("note");
    expect(note.textContent).toContain("This is not a tax invoice.");
    expect(note.textContent).toContain(GST_STATUS_SENTENCE);
    // No GSTIN is printed for a supplier that has none; nothing is invented.
    expect(container.textContent).not.toMatch(/GSTIN [0-9A-Z]{15}/);
  });

  it("prints the server's own tax note when it sends one", () => {
    const sent = `Bill of supply. ${GST_STATUS_SENTENCE}`;
    render(<InvoiceDocument data={billOfSupply({ tax_note: sent })} />);

    expect(screen.getByRole("note").textContent).toContain(sent);
  });

  it("names the configured legal entity, and the trade name only when none is set", () => {
    const { container, unmount } = render(<InvoiceDocument data={billOfSupply()} />);
    const billedBy = within(container).getByRole("heading", { name: "Billed by" }).closest("section");
    expect(billedBy?.textContent).toContain("Calevate");
    unmount();

    render(
      <InvoiceDocument
        data={billOfSupply({
          supplier: { legal_name: "A. Proprietor", address: null, gstin: null, state_name: null, sac: "998315" },
        })}
      />,
    );
    const named = screen.getByRole("heading", { name: "Billed by" }).closest("section");
    expect(named?.textContent).toContain("A. Proprietor");
    expect(named?.textContent).not.toContain("Calevate");
  });

  it("prints 2500.10 as ₹2,500.10 exactly, in the totals block", () => {
    const { container } = render(<InvoiceDocument data={billOfSupply()} />);

    expect(valueBeside(container, "Subtotal")).toBe("₹2,500.10");
    expect(valueBeside(container, "Total")).toBe("₹2,500.10");
  });

  it("prints the SERVER's total and never adds the lines up itself", () => {
    // 0.1 + 0.2 in a JS number is 0.30000000000000004. The lines below sum to that in
    // floating point, and the server's total is deliberately NOT their sum: a sheet that
    // did any arithmetic would print something other than ₹0.31 here.
    const { container } = render(
      <InvoiceDocument
        data={billOfSupply({
          line_items: [
            { description: "Line one", qty: "1", unit_inr: "0.1", amount_inr: "0.1", sac: "998315" },
            { description: "Line two", qty: "1", unit_inr: "0.2", amount_inr: "0.2", sac: "998315" },
          ],
          subtotal_inr: "0.31",
          total_inr: "0.31",
        })}
      />,
    );

    expect(valueBeside(container, "Total")).toBe("₹0.31");
    expect(container.textContent).not.toContain("0.30000000000000004");
    expect(container.textContent).not.toContain("₹0.30");
    // Each line is the server's figure, padded to paise by string, not by toFixed.
    expect(screen.getByText("₹0.10").tagName).toBe("TD");
    expect(screen.getByText("₹0.20").tagName).toBe("TD");
  });

  it("groups lakhs and crores the Indian way without parsing", () => {
    const { container } = render(
      <InvoiceDocument data={billOfSupply({ subtotal_inr: "11987620.05", total_inr: "11987620.05" })} />,
    );

    expect(valueBeside(container, "Total")).toBe("₹1,19,87,620.05");
  });

  it("keeps the quantity and unit rate verbatim, as the multiplication a client checks", () => {
    render(<InvoiceDocument data={billOfSupply()} />);

    expect(screen.getByText("₹5.5000").tagName).toBe("TD");
    expect(screen.getByText("0.2").tagName).toBe("TD");
  });

  it("prints one row per head of tax on a tax invoice, as the server split it", () => {
    const { container } = render(
      <InvoiceDocument
        data={billOfSupply({
          document_type: "tax_invoice",
          supplier: {
            legal_name: "Calevate",
            address: "Plot 42, Madhapur, Hyderabad 500081",
            gstin: "36AABCC1234D1Z5",
            state_name: "Telangana",
            sac: "998315",
          },
          subtotal_inr: "10145.06",
          gst_inr: "1826.11",
          tax_components: [
            { label: "CGST", rate_pct: "9", amount_inr: "913.06" },
            { label: "SGST", rate_pct: "9", amount_inr: "913.05" },
          ],
          total_inr: "11971.17",
        })}
      />,
    );

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("TAX INVOICE");
    expect(screen.queryByRole("note")).toBeNull();
    expect(valueBeside(container, "CGST @ 9%")).toBe("₹913.06");
    expect(valueBeside(container, "SGST @ 9%")).toBe("₹913.05");
    expect(valueBeside(container, "Total")).toBe("₹11,971.17");
  });

  it("treats an unrecognised document type as NOT a tax invoice", () => {
    render(<InvoiceDocument data={billOfSupply({ document_type: "something_new" })} />);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("BILL OF SUPPLY");
  });

  it("has no accessibility violations", async () => {
    const { container } = render(<InvoiceDocument data={billOfSupply()} />);
    await expectNoA11yViolations(container, "components/invoiceDocument — bill of supply");
  });
});

describe("the payment receipt", () => {
  it("calls itself a receipt and prints the server's GST sentence", () => {
    const { container } = render(<ReceiptDocument data={receipt()} />);

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Receipt");
    expect(container.textContent).toContain(GST_STATUS_SENTENCE);
    expect(container.textContent).not.toMatch(/TAX INVOICE|GSTIN/);
  });

  it("prints 2500.10 as ₹2,500.10 exactly, once", () => {
    const { container } = render(<ReceiptDocument data={receipt()} />);

    expect(valueBeside(container, "Amount received")).toBe("₹2,500.10");
    expect(screen.getAllByText("₹2,500.10")).toHaveLength(1);
  });

  it("says when the amount is the total of several recorded parts", () => {
    render(<ReceiptDocument data={receipt({ entries: 3 })} />);

    expect(screen.getByText(/recorded in 3 parts; the amount above is the total/)).toBeTruthy();
  });

  it("leaves out the supplier card when no supplier particulars are configured", () => {
    render(<ReceiptDocument data={receipt({ supplier_legal_name: null, supplier_address: null })} />);

    expect(screen.queryByRole("heading", { name: "Paid to" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Paid by" })).toBeTruthy();
  });

  it("has no accessibility violations", async () => {
    const { container } = render(<ReceiptDocument data={receipt()} />);
    await expectNoA11yViolations(container, "components/receiptDocument");
  });
});

describe("the billing document sources", () => {
  const WEB = process.cwd();
  const SOURCES = [
    "src/components/invoiceDocument.tsx",
    "src/components/receiptDocument.tsx",
    "src/components/billing/documentParts.tsx",
  ];

  it("never turn money into a number", () => {
    // Hard rule 7's frontend shadow: the only formatting of money is string grouping in
    // `formatINR`. Comments are stripped so the rule's own explanation does not trip it.
    for (const file of SOURCES) {
      const code = readFileSync(join(WEB, file), "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/\/\/.*$/gm, "");
      expect(code, file).not.toMatch(/\b(?:Number|parseFloat|parseInt|BigInt)\s*\(|\.toFixed\(|Intl\.NumberFormat/);
    }
  });

  it("credit the layout they adapt, with its licence beside them", () => {
    const licence = readFileSync(join(WEB, "src/components/billing/LICENSE"), "utf8");
    expect(licence).toContain("MIT License");
    expect(licence).toContain("Copyright (c) 2025 Invoicely");
    for (const file of SOURCES) {
      const head = readFileSync(join(WEB, file), "utf8").slice(0, 600);
      expect(head, file).toContain("https://github.com/legions-developer/invoicely");
      expect(head, file).toContain("820d3c51604faa10d44126e019c1fad51b54d96f");
      expect(head, file).toContain("MIT licence");
      expect(licence, file).toContain(file.split("/").pop() ?? file);
    }
  });
});
