"use client";

/**
 * The invoice statement, in both realms (SLICE AL).
 *
 * - ops: `GET /v1/admin/tenants/{tenantId}/invoice?month=YYYY-MM`
 * - the client: `GET /v1/billing/invoice?month=YYYY-MM`
 *
 * ONE server-side computation (`billing/invoice.py::build_invoice`) behind both, and one
 * response model, so the document a client prints and the document ops prints cannot
 * disagree. `tests/invoice_gst_test.py` asserts that field for field; the hooks below are
 * deliberately two thin fetches of one shape rather than two shapes.
 *
 * Every Decimal — money, each tax component's rate and amount, the line's qty,
 * minutes_used — arrives as an exact decimal STRING (hard rule 7's frontend shadow) and
 * must STAY a string all the way to the screen; `Number()` on INR is how ₹10,159.00
 * becomes ₹10,158.999999999998.
 *
 * `qty` in particular: a hand-written interface once typed it `number | string`, hedging
 * over the plan-fee line. The server does not hedge — it builds that line with
 * `Decimal("1")` precisely so no line item ever ships a bare JSON number, and every qty
 * is a string. `qty * unit_inr` must reproduce `amount_inr` when a client checks it by
 * hand, which is why the overage rate keeps its true precision rather than being rounded
 * like a rupee.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

/**
 * The invoice document, from the generated schema.
 *
 * Two fields decide what this document IS rather than what it says. `document_type` is
 * `"tax_invoice"` or `"proforma"`, and the heading is rendered from it and never from a
 * literal — CGST s.32 forbids an unregistered person collecting tax, so a document
 * without the Rule 46 identity particulars must not present itself as a tax invoice.
 * `document_blockers` names the exact environment variables standing between this
 * document and being one, so the refusal tells an operator what to do about it.
 *
 * `tax_components` splits the tax into CGST/SGST/UTGST/IGST from the place of supply.
 * Those are three separate credit ledgers, so tax charged without naming the head cannot
 * be claimed at all — the split is the difference between a claimable invoice and a
 * decorative one. It sums to `gst_inr` on the server and is never added up in the browser.
 * `invoice_number` is deterministic — CAL-{YYYYMM}-{tenant prefix}, one per
 * tenant-month, and NOT yet Rule 46(b) compliant (19 characters against a 16-character
 * cap, and deterministic rather than consecutive). That conflict with D-46's derived
 * statement is pinned by a server-side test rather than papered over here.
 * `line_items` is deliberately empty when nothing was billable; the totals still come
 * back, so the page renders a usage-only statement.
 */
export type Invoice = Schemas["InvoiceOut"];
export type InvoiceLineItem = Schemas["InvoiceLineItemOut"];


/** The month query string both realms share, so neither can key its cache differently. */
function monthQuery(month?: string): string {
  return month ? `?month=${encodeURIComponent(month)}` : "";
}

/** Ops reading one tenant's statement. Admin realm, tenant in the path. */
export function useInvoice(tenantId: string, month?: string): UseQueryResult<Invoice> {
  return useQuery({
    queryKey: ["admin", "invoice", tenantId, month ?? "current"],
    queryFn: () =>
      apiRequest<Invoice>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/invoice${monthQuery(month)}`,
      ),
    enabled: Boolean(tenantId),
  });
}

/**
 * A client reading their OWN statement. No tenant parameter: the server takes it from the
 * principal, so there is nothing here for a caller to point elsewhere.
 *
 * `billing:read`, which owners hold and staff do not — the same gate `/v1/usage` applies,
 * and the same one the page checks before rendering so a staff member meets a sentence
 * rather than a red 403.
 */
export function useClientInvoice(session: Session, month?: string): UseQueryResult<Invoice> {
  return useQuery({
    queryKey: ["invoice", session.orgSlug, month ?? "current"],
    queryFn: () => apiRequest<Invoice>(session, `/v1/billing/invoice${monthQuery(month)}`),
  });
}

/** Current billing month in IST (YYYY-MM) — en-CA formats as YYYY-MM-DD.
 *
 * Both screens default to this: the API bills on the IST month, so a picker on any other
 * clock would disagree with the statement it is asking for.
 */
export function currentISTMonth(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }).slice(0, 7);
}
