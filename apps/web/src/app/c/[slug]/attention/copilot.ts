"use client";

import type { UseQueryResult } from "@tanstack/react-query";

import type { AttentionQueue } from "@/lib/api/attention";
import type { Me } from "@/lib/api/client";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

/**
 * The triage queue, declared to the assistant (`lib/copilot/registry.ts`).
 *
 * COUNTS ONLY, never an item: each row names the thing that was stopped (a blocked call
 * carries the number it would have rung), which is what hard rule 6 keeps out of a
 * prompt. Called above the permission refusal, and the `state` fact says which screen is
 * really showing.
 */
export function useAttentionCopilot(queue: UseQueryResult<AttentionQueue>, me: UseQueryResult<Me>) {
  const queueCounts: Record<string, number> = queue.data?.counts ?? {};
  useCopilotSurface({
    route: "/c/{slug}/attention",
    title: "Needs your attention",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value:
          me.data !== undefined && !me.data.permissions.includes("leads:read")
            ? "a refusal — this session may not read leads, so the queue is not shown"
            : queue.data
              ? "the queue below has loaded"
              : queue.error
                ? "the queue failed to load, so nothing is listed"
                : "still loading",
      },
      ...(queue.data
        ? [
            { key: "total", label: "Things waiting", value: String(queue.data.total) },
            {
              key: "by_kind",
              label: "What kind of thing is waiting, and how many of each",
              value:
                Object.entries(queueCounts)
                  .map(([kind, count]) => `${kind}: ${count}`)
                  .join(", ") || "nothing is waiting",
            },
            { key: "items_listed", label: "Rows rendered in the list", value: String(queue.data.items.length) },
          ]
        : []),
    ],
    apply: noFill,
  });
}
