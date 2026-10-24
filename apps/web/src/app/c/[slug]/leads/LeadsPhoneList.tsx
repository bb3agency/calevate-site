"use client";

import Link from "next/link";

import { SwipeActions } from "@/components/arc/swipe-actions";
import { formatIST, formatPhone } from "@/components/ui";
import { needsAttention, outcomeWords } from "@/lib/callReview";
import { leadNextStep } from "@/lib/leadLabels";

import { CallControl } from "./CallControl";
import { cellValue } from "./leadsTable";
import type { LeadRowKit } from "./leadRowKit";

/**
 * The leads on a phone (founder, 24 Oct 2026): who and why on the left — name, number and
 * what the last call was about (its headline, else what is next) — and how it ended and
 * when on the right, with the follow-up actions a swipe away (right: call now; left: mark,
 * call back later, WhatsApp). The row fits the screen, so a sideways swipe only ever means
 * the actions. The business's own captured fields follow as one quiet line; the full set
 * is on the lead's own screen. No select box: picking many is the wider table's job.
 */
export function LeadsPhoneList({ kit }: { kit: LeadRowKit }) {
  const { items, columns, rowFailure, hrefFor, followUp, targetOf } = kit;
  const captured = columns.filter((column) => column.kind !== "fixed");
  return (
    <ul aria-label="Leads" className="divide-y divide-line">
      {items.map((lead) => {
        const target = targetOf(lead);
        const { primary, secondary } = followUp.actionsFor(target);
        const answer = followUp.callResult(lead.id);
        const reason = lead.last_call_headline ?? leadNextStep(lead);
        const call = { outcome_tag: lead.last_call_outcome ?? null, business_outcome_label: lead.last_call_business_outcome_label };
        // A lead no call has reached yet is described by its stage instead.
        const outcome = lead.last_call_id ? outcomeWords(call) : null;
        const warn = outcome !== null && needsAttention({ outcome_tag: call.outcome_tag, callback: null });
        const when = formatIST(lead.last_call_at ?? lead.created_at);
        const details = captured
          .map((column) => ({ label: column.label, value: cellValue(lead, column.key) }))
          .filter((detail) => detail.value !== "—")
          .map((detail) => `${detail.label}: ${detail.value}`)
          .join(" · ");
        return (
          <li key={lead.id}>
            <SwipeActions label={target.name} primary={primary} secondary={secondary}>
              <Link
                href={hrefFor(lead)}
                className="block min-w-0 px-3 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand"
              >
                <span className="flex min-w-0 items-start justify-between gap-3">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-ink">{target.name}</span>
                    {lead.name ? (
                      <span className="block text-meta tabular-nums text-ink-faint">{formatPhone(lead.phone_e164)}</span>
                    ) : null}
                    {reason ? <span className="mt-0.5 block line-clamp-2 text-meta text-ink-muted">{reason}</span> : null}
                    {details ? <span className="block truncate text-meta text-ink-faint">{details}</span> : null}
                  </span>
                  <span className="flex max-w-[42%] shrink-0 flex-col items-end text-right">
                    <span className={`text-meta font-medium ${warn ? "text-warn" : "text-ink"} ${outcome ? "" : "capitalize"}`}>
                      {outcome ?? lead.status}
                    </span>
                    <span className="text-meta tabular-nums text-ink-faint">{when}</span>
                  </span>
                </span>
              </Link>
              {answer ? (
                <div className="px-3 pb-3">
                  <CallControl result={answer} pending={false} onCall={() => followUp.startCall(target)} />
                </div>
              ) : null}
              {rowFailure(lead)}
            </SwipeActions>
          </li>
        );
      })}
    </ul>
  );
}
