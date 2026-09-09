"use client";

import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";
import type { Agent } from "@/lib/api/agents";

/*
 * THE "TEACH IT SOMETHING" FORM, DECLARED TO THE SCREEN ASSISTANT.
 *
 * Three loose `useState` scalars, so `apply` is three setter calls — no DOM, no draft
 * object to thread. The agent picker is offered as a `select` over the SAME query the
 * control renders from, so the assistant cannot name an agent this account does not
 * have; a value outside the list is dropped rather than written, because the picker
 * would render blank and the submit would post an id nobody chose.
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
  selectedAgentId,
  setAgentId,
  agentOptions,
}: {
  name: string;
  setName: (value: string) => void;
  body: string;
  setBody: (value: string) => void;
  selectedAgentId: string;
  setAgentId: (id: string) => void;
  agentOptions: Agent[];
}) {
  useCopilotSurface({
    route: "/c/{slug}/knowledge",
    title: "Teach your agent something",
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
        help: "Prose, in the language the agent answers in. Once it is approved it becomes part of what the agent already knows when it picks up.",
      },
      {
        id: "kb-agent",
        label: "Which agent learns this",
        type: "select",
        value: selectedAgentId,
        options: agentOptions.map((agent) => ({ value: agent.id, label: agent.name })),
        help: "Knowledge belongs to one agent.",
      },
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id === "kb-title") setName(asText(item.value));
        else if (item.field_id === "kb-body") setBody(asText(item.value));
        else if (
          item.field_id === "kb-agent" &&
          agentOptions.some((agent) => agent.id === item.value)
        ) {
          setAgentId(asText(item.value));
        }
      }
    },
  });
}
