"use client";

import type { UseQueryResult } from "@tanstack/react-query";

import type { AttentionKind, AttentionQueue } from "@/lib/api/attention";
import type { Me } from "@/lib/api/client";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { KIND_COPY } from "./rows";

/**
 * The triage queue, declared to the assistant (`lib/copilot/registry.ts`).
 *
 * COUNTS ONLY, never an item: each row names the thing that was stopped (a blocked call
 * carries the number it would have rung), which is what hard rule 6 keeps out of a
 * prompt. Called above the permission refusal, and the `state` fact says which screen is
 * really showing.
 *
 * The one writable control is the kind filter, declared only while the screen draws it
 * (more than one kind waiting), with exactly the options it draws.
 */
export function useAttentionCopilot(
  queue: UseQueryResult<AttentionQueue>,
  me: UseQueryResult<Me>,
  filter: { value: string; all: string; kinds: AttentionKind[]; set: (next: string) => void },
) {
  const queueCounts: Record<string, number> = queue.data?.counts ?? {};
  const refused = me.data !== undefined && !me.data.permissions.includes("leads:read");
  const filterShown = !refused && filter.kinds.length > 1;
  useCopilotSurface({
    route: "/c/{slug}/attention",
    title: "Needs your attention",
    realm: "client",
    fields: filterShown
      ? [
          {
            id: "attention-kind",
            label: "Show only this kind of item",
            type: "select",
            value: filter.value,
            options: [
              { value: filter.all, label: "All" },
              ...filter.kinds.map((kind) => ({ value: kind, label: KIND_COPY[kind].label })),
            ],
            help: "The list is ordered most urgent first.",
          },
        ]
      : [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: refused
          ? "a refusal — this session may not read leads, so the queue is not shown"
          : queue.data
            ? "the queue below has loaded, most urgent first"
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
    apply: (items) => {
      for (const item of items) {
        if (item.field_id !== "attention-kind") continue;
        const wanted = asText(item.value);
        if (wanted === filter.all || filter.kinds.some((kind) => kind === wanted)) filter.set(wanted);
      }
    },
  });
}
