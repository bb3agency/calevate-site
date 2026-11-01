import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentKnowledgePanel } from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/sections/knowledge";
import type { AgentKnowledge } from "@/lib/api/agentKnowledge";

import { noContent, renderAdminPage } from "./harness";

/**
 * The operator's per-agent knowledge list (D-868): every row says where it stands, and only
 * a document we did not send may be removed here.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000a1";
const AGENT = "0192f0aa-7777-7000-8000-0000000000b2";
const PATH = `/v1/admin/tenants/${TENANT}/agents/${AGENT}/knowledge`;
const WRITE = { allowed: true, refused: false, reason: null };

const VIEW: AgentKnowledge = {
  agent_id: AGENT,
  listed: true,
  items: [
    { verdict: "held", handle: "doc_1@org_a", source_id: "s1", name: "Menu", kind: "pdf", detail: null },
    { verdict: "missing", handle: "doc_2@org_a", source_id: "s2", name: "Prices", kind: "text", detail: null },
    {
      verdict: "not_sent",
      handle: null,
      source_id: "s3",
      name: "Delivery page",
      kind: "url",
      detail: "Your agents could not read that page.",
    },
    { verdict: "not_ours", handle: "doc_9@org_a", source_id: null, name: null, kind: null, detail: null },
  ],
};

describe("an agent's knowledge, for an operator", () => {
  it("says where each item stands and offers Remove only for a document we did not send", async () => {
    renderAdminPage(<AgentKnowledgePanel tenantId={TENANT} agentId={AGENT} write={WRITE} />, {
      [`GET ${PATH}`]: VIEW,
    });
    expect(await screen.findByText("Menu")).toBeTruthy();
    expect(screen.getByText("On the agent")).toBeTruthy();
    expect(screen.getByText("Missing on ThinnestAI")).toBeTruthy();
    expect(screen.getByText(/could not read that page/)).toBeTruthy();
    expect(screen.getByText("Document doc_9@org_a")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);
  });

  it("removes the document by its id", async () => {
    const page = renderAdminPage(<AgentKnowledgePanel tenantId={TENANT} agentId={AGENT} write={WRITE} />, {
      [`GET ${PATH}`]: VIEW,
      [`POST ${PATH}/remove`]: noContent(),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(page.calls.some((c) => c.method === "POST")).toBe(true));
    const posted = page.calls.find((c) => c.method === "POST");
    expect(JSON.parse(posted?.body ?? "{}")).toEqual({ handle: "doc_9@org_a" });
  });

  it("says when the platform's list could not be read", async () => {
    renderAdminPage(<AgentKnowledgePanel tenantId={TENANT} agentId={AGENT} write={WRITE} />, {
      [`GET ${PATH}`]: { ...VIEW, listed: false },
    });
    expect(await screen.findByText(/could not be read/)).toBeTruthy();
  });
});
