"use client";

import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

/*
 * THE "TEACH IT SOMETHING" FORM, DECLARED TO THE SCREEN ASSISTANT.
 *
 * Two loose `useState` scalars, so `apply` is two setter calls — no DOM, no draft object
 * to thread. There is no agent field: the knowledge is the business's and every agent
 * answers from it (D-689), so there is nothing for the assistant to choose.
 *
 * This is the screen where a fill is most obviously worth having: the body is a page of
 * prose about a business, and "write the cancellation policy from what is in the
 * intake sheet" is the whole job.
 */
export function useKnowledgeCopilot({
  name,
  setName,
  body,
  setBody,
}: {
  name: string;
  setName: (value: string) => void;
  body: string;
  setBody: (value: string) => void;
}) {
  useCopilotSurface({
    route: "/c/{slug}/knowledge",
    title: "Teach your agents something",
    realm: "client",
    fields: [
      {
        id: "kb-title",
        label: "Title",
        type: "text",
        value: name,
        help: "What this note is about — shown in the list, not read to callers.",
      },
      {
        id: "kb-body",
        label: "What it should know",
        type: "textarea",
        value: body,
        help: "Prose, in the language the agents answer in. It is shared by every agent on the account, and once it has reached them it becomes part of what each agent already knows when it picks up.",
      },
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id === "kb-title") setName(asText(item.value));
        else if (item.field_id === "kb-body") setBody(asText(item.value));
      }
    },
  });
}
