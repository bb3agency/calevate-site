"use client";

import Link from "next/link";
import { PhoneIncoming, PhoneOutgoing } from "lucide-react";

import type { CallSummary } from "@/lib/api/client";

/**
 * WHERE A CALL CAME FROM (D-1006): the campaign that placed it or the Inbound line that took
 * it. A one-off call, and a free-trial test call, has neither and shows nothing.
 */
export interface CallSource {
  kind: "campaign" | "line";
  id: string;
  name: string;
}

export function callSource(call: Pick<CallSummary, "campaign" | "inbound_line">): CallSource | null {
  if (call.campaign) return { kind: "campaign", id: call.campaign.id, name: call.campaign.name };
  if (call.inbound_line) return { kind: "line", id: call.inbound_line.id, name: call.inbound_line.name };
  return null;
}

export const SOURCE_WORD: Record<CallSource["kind"], string> = {
  campaign: "Campaign",
  line: "Inbound line",
};

/** The campaign's or the line's own page, inside the client realm. */
export function sourcePath(slug: string, source: CallSource): string {
  const id = encodeURIComponent(source.id);
  return source.kind === "campaign" ? `/c/${slug}/campaigns/${id}` : `/c/${slug}/inbound/${id}`;
}

function SourceIcon({ kind }: { kind: CallSource["kind"] }) {
  const Icon = kind === "campaign" ? PhoneOutgoing : PhoneIncoming;
  return <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" />;
}

/**
 * The source as a short label: an icon and the name, the kind said to a screen reader and in
 * the tooltip. `href` makes it a link; without one (inside a row that is itself a link, where
 * a second link cannot nest) it is plain text.
 */
export function CallSourceLabel({ source, href }: { source: CallSource; href?: string }) {
  const said = `${SOURCE_WORD[source.kind]}: ${source.name}`;
  const body = (
    <>
      <SourceIcon kind={source.kind} />
      <span className="sr-only">{SOURCE_WORD[source.kind]}:</span>{" "}
      <span className="min-w-0 truncate">{source.name}</span>
    </>
  );
  if (!href) {
    return (
      <span title={said} className="inline-flex min-w-0 max-w-full items-center gap-1 text-meta text-ink-muted">
        {body}
      </span>
    );
  }
  // `relative z-raised` lifts the link above the row's whole-row link overlay.
  return (
    <Link
      href={href}
      title={said}
      className="relative z-raised inline-flex min-w-0 max-w-full items-center gap-1 rounded-sm text-meta text-ink-muted hover:text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
    >
      {body}
    </Link>
  );
}
