"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { formatIST } from "@/components/ui";
import type { AttentionItem, AttentionKind } from "@/lib/api/attention";
import { lookup } from "@/lib/lookup";

/**
 * Per-kind label, dot, action and urgency. Plain words, not system nouns ("Call blocked",
 * not `lead_blocked`). `Record<AttentionKind, …>` over the GENERATED union, so a new kind
 * on the server is a type error here rather than an unlabelled row nobody notices.
 *
 * `action` names what the row's link lets the owner do on the page the server points it
 * at (`crm/attention.py` sets each kind's `href`). `rank` orders the list: calls nobody
 * answers come first, things that already happened safely (a number we did not ring) last.
 */
export const KIND_COPY: Record<AttentionKind, { label: string; dot: string; action: string; rank: number }> = {
  inbound_stopped: { label: "Calls not being answered", dot: "bg-danger", action: "Add credits", rank: 0 },
  action_broken: { label: "Action needs a connection", dot: "bg-danger", action: "Reconnect", rank: 1 },
  delivery_failed: { label: "Delivery failed", dot: "bg-danger", action: "Check the connection", rank: 2 },
  campaign_stalled: { label: "Campaign stalled", dot: "bg-warn", action: "Open campaigns", rank: 3 },
  lead_blocked: { label: "Call blocked", dot: "bg-warn", action: "Open leads", rank: 4 },
  kb_rejected: { label: "Knowledge not accepted", dot: "bg-ink-faint", action: "Open knowledge", rank: 5 },
};

/** Most urgent first, newest first within one kind. An unknown kind sorts after the known ones. */
export function byUrgency(items: AttentionItem[]): AttentionItem[] {
  const rank = (item: AttentionItem) => lookup(KIND_COPY, item.kind)?.rank ?? Object.keys(KIND_COPY).length;
  return [...items].sort(
    (a, b) => rank(a) - rank(b) || Date.parse(b.occurred_at) - Date.parse(a.occurred_at),
  );
}

/**
 * One item. The whole row is the link to the fix (UX-DOCTRINE §4, one target per row),
 * and the action it leads to is named in words on the right; a row with no `href` is not
 * a link and names no action. The title is the server's own sentence, and a kind this
 * build has never heard of still gets its row, with the raw kind in place of a label.
 */
export function Row({ item, to }: { item: AttentionItem; to: string | null }) {
  const copy = lookup(KIND_COPY, item.kind);
  const body = (
    <>
      <span className="inline-flex items-center gap-1.5 text-meta text-ink-muted">
        <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${copy?.dot ?? "bg-ink-faint"}`} />
        {copy?.label ?? item.kind.replace(/_/g, " ")}
        <span aria-hidden>·</span>
        <span className="whitespace-nowrap text-ink-faint">{formatIST(item.occurred_at)}</span>
      </span>
      {/* `break-words`: the title can carry an E.164 number, which has no space to wrap at. */}
      <span className="mt-0.5 block min-w-0 break-words text-body font-medium text-ink">{item.title}</span>
      <span className="mt-0.5 block text-meta text-ink-muted">{item.detail}</span>
    </>
  );
  return (
    <li className="relative flex flex-col gap-2 py-3.5 transition-colors duration-(--duration-fast) has-[a:hover]:bg-ink/[0.03] sm:flex-row sm:items-center sm:gap-6">
      <div className="min-w-0 flex-1">
        {to ? (
          <Link
            href={to}
            className="block rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand after:absolute after:inset-0"
          >
            {body}
          </Link>
        ) : (
          body
        )}
      </div>
      {to && copy && (
        <span className="inline-flex shrink-0 items-center gap-1 text-body font-medium text-brand-strong dark:text-brand-bright">
          {copy.action}
          <ChevronRight aria-hidden className="h-4 w-4" />
        </span>
      )}
    </li>
  );
}
