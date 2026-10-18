"use client";

import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

/*
 * THE TEACH BOX, DECLARED TO THE SCREEN ASSISTANT.
 *
 * One field: what the owner wants the agents to know. Pip can draft it ("write our
 * delivery areas from the profile"), and teaching it is Pip's own action
 * (`knowledge_teach`, D-821): the facts and rules come back to this box for the owner to
 * keep before anything is saved. There is no agent field: facts are the business's and
 * every agent answers from them (D-689); rules pick their agent in the review. When the
 * owner is answering a caller's question, its id is a fact so the teaching closes it.
 *
 * On another screen (an agent's Training tab) the box sits inside a `CopilotSurfaceScope`,
 * which supplies that screen's route and title and merges this field with the rest of it.
 */
export function useKnowledgeCopilot({
  body,
  setBody,
  answering,
}: {
  body: string;
  setBody: (value: string) => void;
  answering: { gapId: string | null; question: string } | null;
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
    facts: answering
      ? [
          { key: "answering_question", label: "The caller's question being answered", value: answering.question },
          ...(answering.gapId ? [{ key: "gap_id", label: "Its question id", value: answering.gapId }] : []),
        ]
      : [],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id === "kb-teach") setBody(asText(item.value));
      }
    },
  });
}
