"use client";

import { STATE_DOT, StatusPill } from "@/components/console/statusPill";
import { formatPhone } from "@/components/ui";
import type { InboundLine } from "@/lib/api/inboundLines";

/**
 * A line's state in one word. Live: its script answers its numbers. Not live yet: a script
 * is saved but the platform step did not finish, so Put it live is the next move. Draft:
 * no script saved yet.
 */
export function lineState(line: Pick<InboundLine, "live" | "script">): "live" | "not_live" | "draft" {
  if (line.live) return "live";
  return line.script ? "not_live" : "draft";
}

export function LineStatusPill({ line }: { line: Pick<InboundLine, "live" | "script"> }) {
  const state = lineState(line);
  if (state === "live") return <StatusPill tone="ok">Live</StatusPill>;
  if (state === "not_live") return <StatusPill tone="warn">Not live yet</StatusPill>;
  return (
    <StatusPill tone="neutral" dot={STATE_DOT.draft}>
      Draft
    </StatusPill>
  );
}

/** The numbers a line answers, or that it answers none yet. */
export function numbersText(line: Pick<InboundLine, "numbers">): string {
  if (line.numbers.length === 0) return "No number yet";
  return line.numbers.map((n) => formatPhone(n.e164)).join(", ");
}
