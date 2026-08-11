"use client";

/**
 * Admin invoice hook — GET /v1/admin/tenants/{tenantId}/invoice?month=YYYY-MM.
 *
 * Aliased from the generated schema now that the endpoint has a response model. Every
 * Decimal — money, GST rate, the line's qty, minutes_used — arrives as an exact
 * decimal STRING (hard rule 7's frontend shadow) and must STAY a string all the way to
 * the screen; `Number()` on INR is how ₹10,159.00 becomes ₹10,158.999999999998.
 *
 * `qty` in particular: the hand-written interface typed it `number | string`, hedging
 * over the plan-fee line. The server does not hedge — it builds that line with
 * `Decimal("1")` precisely so no line item ever ships a bare JSON number, and every
 * qty is a string. `qty * unit_inr` must reproduce `amount_inr` when a client checks
 * it by hand, which is why the overage rate keeps its true precision rather than being
 * rounded like a rupee.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type InvoiceLineItem = Schemas["InvoiceLineItemOut"];

/**
 * `invoice_number` is deterministic — CAL-{YYYYMM}-{tenant prefix}, one per
 * tenant-month. `line_items` is deliberately empty when nothing was billable; the
 * totals still come back, so the page renders a usage-only statement.
 */
export type Invoice = Schemas["InvoiceOut"];

export function useInvoice(tenantId: string, month?: string): UseQueryResult<Invoice> {
  return useQuery({
    queryKey: ["admin", "invoice", tenantId, month ?? "current"],
    queryFn: () =>
      apiRequest<Invoice>(
        adminSession(),
        `/v1/admin/tenants/${tenantId}/invoice${month ? `?month=${encodeURIComponent(month)}` : ""}`,
      ),
    enabled: Boolean(tenantId),
  });
}
