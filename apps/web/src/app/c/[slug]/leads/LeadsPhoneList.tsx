"use client";

import Link from "next/link";

import { SwipeActions } from "@/components/arc/swipe-actions";
import { formatPhone } from "@/components/ui";
import { leadNextStep, stageSetBy } from "@/lib/leadLabels";

import { CallControl } from "./CallControl";
import { cellValue } from "./leadsTable";
import type { LeadRowKit } from "./leadRowKit";

/**
 * The leads on a phone: who, where they stand, what is next, and the follow-up actions a
 * swipe away (right: call now; left: mark, call back later, WhatsApp). The business's own
 * columns (what its agents capture) follow as one quiet line, so a phone row still shows
 * what the table would; the full set is on each lead's own screen.
 */
export function LeadsPhoneList({ kit }: { kit: LeadRowKit }) {
  const { items, columns, maySelect, ticked, toggleRow, rowFailure, hrefFor, followUp, targetOf } = kit;
  const captured = columns.filter((column) => column.kind !== "fixed");
  return (
    <ul aria-label="Leads" className="divide-y divide-line">
      {items.map((lead) => {
        const target = targetOf(lead);
        const { primary, secondary } = followUp.actionsFor(target);
        const answer = followUp.callResult(lead.id);
        const next = leadNextStep(lead);
        const details = captured
          .map((column) => ({ label: column.label, value: cellValue(lead, column.key) }))
          .filter((detail) => detail.value !== "—")
          .map((detail) => `${detail.label}: ${detail.value}`)
          .join(" · ");
        return (
          <li key={lead.id} className={ticked.has(lead.id) ? "bg-brand-soft/50" : undefined}>
            <SwipeActions label={target.name} primary={primary} secondary={secondary}>
              <div className="flex min-w-0 items-start gap-2 py-2.5">
                {maySelect ? (
                  <label className="flex h-11 w-9 shrink-0 cursor-pointer items-center justify-center">
                    <input
                      type="checkbox"
                      aria-label={`Select ${target.name}`}
                      checked={ticked.has(lead.id)}
                      onChange={() => toggleRow(lead.id)}
                      className="h-5 w-5 accent-brand-strong"
                    />
                  </label>
                ) : null}
                <Link
                  href={hrefFor(lead)}
                  className="block min-w-0 flex-1 rounded-sm py-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand"
                >
                  <span className="flex min-w-0 items-baseline justify-between gap-2">
                    <span className="truncate font-medium text-ink">{target.name}</span>
                    <span className="shrink-0 text-meta font-medium capitalize text-ink-muted">{lead.status}</span>
                  </span>
                  {lead.name ? (
                    <span className="block text-meta tabular-nums text-ink-faint">{formatPhone(lead.phone_e164)}</span>
                  ) : null}
                  {next ? <span className="mt-0.5 block truncate text-meta text-ink-muted">{next}</span> : null}
                  {details ? <span className="block truncate text-meta text-ink-faint">{details}</span> : null}
                  <span className="block text-meta text-ink-faint">{stageSetBy(lead.status_set_by)}</span>
                </Link>
              </div>
              {answer ? (
                <div className={maySelect ? "pb-2 pl-11" : "pb-2"}>
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
