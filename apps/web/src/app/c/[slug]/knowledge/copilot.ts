"use client";

import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText, type CopilotSurface } from "@/lib/copilot/types";

/**
 * The screen a teach box sits on when it is not the Knowledge page (an agent's Training
 * tab, D-825): its route and title, plus what else that screen holds. The registry keeps
 * one live surface, so a screen with a teach box declares its other fields through it.
 */
export type TeachSurface = Pick<CopilotSurface, "route" | "title" | "fields" | "facts" | "apply">;

/*
 * THE TEACH BOX, DECLARED TO THE SCREEN ASSISTANT.
 *
 * One field: what the owner wants the agents to know. Pip can draft it ("write our
 * delivery areas from the profile"), and teaching it is Pip's own action
 * (`knowledge_teach`, D-821): the facts and rules come back to this box for the owner to
 * keep before anything is saved. There is no agent field: facts are the business's and
 * every agent answers from them (D-689); rules pick their agent in the review. When the
 * owner is answering a caller's question, its id is a fact so the teaching closes it.
 */
export function useKnowledgeCopilot({
  body,
  setBody,
  answering,
  surface,
}: {
  body: string;
  setBody: (value: string) => void;
  answering: { gapId: string | null; question: string } | null;
  surface?: TeachSurface;
}) {
  useCopilotSurface({
    route: surface?.route ?? "/c/{slug}/knowledge",
    title: surface?.title ?? "Teach your agents something",
    realm: "client",
    fields: [
      {
        id: "kb-teach",
        label: "What should your agents know?",
        type: "textarea",
        value: body,
        help: "Plain words, in any language the agents speak. It is sorted into facts every agent gets and rules for one agent, and the owner checks each before it is saved.",
      },
      ...(surface?.fields ?? []),
    ],
    facts: [
      ...(surface?.facts ?? []),
      ...(answering
        ? [
            { key: "answering_question", label: "The caller's question being answered", value: answering.question },
            ...(answering.gapId ? [{ key: "gap_id", label: "Its question id", value: answering.gapId }] : []),
          ]
        : []),
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id === "kb-teach") setBody(asText(item.value));
      }
      surface?.apply(items.filter((item) => item.field_id !== "kb-teach"));
    },
  });
}
