"use client";

/**
 * Admin invoice hook — GET /v1/admin/tenants/{tenantId}/invoice?month=YYYY-MM.
 *
 * The interface is defined locally (not aliased from the generated schema) because the
 * endpoint returns a plain dict the API stringifies at the boundary: every Decimal —
 * money, GST rate, the overage line's qty, minutes_used — arrives as an exact decimal
 * STRING (hard rule 7's frontend shadow). It must STAY a string all the way to the
 * screen; `Number()` on INR is how ₹10,159.00 becomes ₹10,158.999999999998.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "./admin";
import { apiRequest } from "./client";

export interface InvoiceLineItem {
  description: string;
  /** `1` for the plan fee; the overage line's qty is decimal MINUTES as a string. */
  qty: number | string;
  unit_inr: string;
  amount_inr: string;
}

export interface Invoice {
  /** Deterministic: CAL-{YYYYMM}-{tenant prefix} — one number per tenant-month. */
  invoice_number: string;
  /** IST billing month, YYYY-MM. */
  month: string;
  generated_at: string;
  organization: {
    id: string;
    name: string;
    billing_email: string | null;
  };
  /** Deliberately empty when nothing was billable — a usage-only statement. */
  line_items: InvoiceLineItem[];
  subtotal_inr: string;
  /** e.g. "18" — a stringified Decimal like every other numeric here. */
  gst_rate_pct: string;
  gst_inr: string;
  total_inr: string;
  usage: {
    minutes_used: string;
    calls: number;
    included_minutes: number;
  };
}

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
