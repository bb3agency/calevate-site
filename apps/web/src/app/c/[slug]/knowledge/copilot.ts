"use client";

import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

/*
 * THE TEACH BOX, DECLARED TO THE SCREEN ASSISTANT.
 *
 * One field: what the owner wants the agents to know. The assistant can draft it ("write
 * our delivery areas from the profile"); the owner still presses Sort it and reviews every
 * fact and rule before anything is saved. There is no agent field: facts are the business's
 * and every agent answers from them (D-689); rules pick their agent in the review.
 */
export function useKnowledgeCopilot({
  body,
  setBody,
}: {
  body: string;
  setBody: (value: string) => void;
}) {
  useCopilotSurface({
    route: "/c/{slug}/knowledge",
    title: "Teach your agents something",
    realm: "client",
    fields: [
      {
        id: "kb-teach",
        label: "What should your agents know?",
        type: "textarea",
        value: body,
        help: "Plain words, in any language the agents speak. It is sorted into facts every agent gets and rules for one agent, and the owner checks each before it is saved.",
      },
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id === "kb-teach") setBody(asText(item.value));
      }
    },
  });
}
