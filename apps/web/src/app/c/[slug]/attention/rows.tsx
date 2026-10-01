"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { formatIST } from "@/components/ui";
import type { AttentionItem, AttentionKind } from "@/lib/api/attention";
import { lookup } from "@/lib/lookup";

/**
 * Per-kind label and dot. Plain words, not system nouns ("Call blocked", not
 * `lead_blocked`). `Record<AttentionKind, …>` over the GENERATED union, so a new kind on the
 * server is a type error here rather than an unlabelled row nobody notices.
 */
export const KIND_COPY: Record<AttentionKind, { label: string; dot: string }> = {
  lead_blocked: { label: "Call blocked", dot: "bg-warn" },
  delivery_failed: { label: "Delivery failed", dot: "bg-danger" },
  campaign_stalled: { label: "Campaign stalled", dot: "bg-warn" },
  inbound_stopped: { label: "Calls not being answered", dot: "bg-danger" },
  kb_rejected: { label: "Knowledge not accepted", dot: "bg-ink-faint" },
};

/**
 * One item. The whole row is the link to the fix (UX-DOCTRINE §4, one target per row);
 * a row with no `href` is not a link. The title is the server's own sentence, and a kind
 * this build has never heard of still gets its row, with the raw kind in place of a label.
 */
export function Row({ item, to }: { item: AttentionItem; to: string | null }) {
  const copy = lookup(KIND_COPY, item.kind);
  const body = (
    <>
      <span className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="inline-flex items-center gap-1.5 text-[12px] text-ink-muted">
          <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${copy?.dot ?? "bg-ink-faint"}`} />
          {copy?.label ?? item.kind.replace(/_/g, " ")}
        </span>
        {/* `break-words`: the title can carry an E.164 number, which has no space to wrap at. */}
        <span className="min-w-0 break-words text-sm font-medium text-ink">{item.title}</span>
      </span>
      <span className="mt-0.5 block text-[13px] text-ink-muted">{item.detail}</span>
    </>
  );
  return (
    <li className="relative flex items-start gap-3 px-4 py-3 transition-colors duration-(--duration-fast) has-[a:hover]:bg-ink/[0.03]">
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
      <span className="shrink-0 whitespace-nowrap pt-0.5 text-xs text-ink-faint">{formatIST(item.occurred_at)}</span>
      {to && <ChevronRight aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />}
    </li>
  );
}
