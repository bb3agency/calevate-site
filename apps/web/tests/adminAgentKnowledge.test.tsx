import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentKnowledgePanel } from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/sections/knowledge";
import type { AgentKnowledge } from "@/lib/api/agentKnowledge";

import { noContent, renderAdminPage } from "./harness";

/**
 * The operator's per-agent knowledge list (D-868), one group per engine agent carrying the
 * agent (D-1019): every row says where it stands, and only a document we did not send may be
 * removed here, from the engine agent that holds it.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000a1";
const AGENT = "0192f0aa-7777-7000-8000-0000000000b2";
const PATH = `/v1/admin/tenants/${TENANT}/agents/${AGENT}/knowledge`;
const WRITE = { allowed: true, refused: false, reason: null };

const VIEW: AgentKnowledge = {
  agent_id: AGENT,
  holders: [
    {
      kind: "line",
      name: "Appointments",
      engine_agent_ref: "agent_line@org_a",
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
    },
    {
      kind: "campaign",
      name: "Rabi follow-up",
      engine_agent_ref: "agent_camp@org_a",
      listed: false,
      items: [
        { verdict: "held", handle: "doc_5@org_a", source_id: "s1", name: "Menu", kind: "pdf", detail: null },
      ],
    },
  ],
};

describe("an agent's knowledge, for an operator", () => {
  it("groups by the line or campaign holding it and offers Remove only for a document we did not send", async () => {
    renderAdminPage(<AgentKnowledgePanel tenantId={TENANT} agentId={AGENT} write={WRITE} />, {
      [`GET ${PATH}`]: VIEW,
    });
    expect(await screen.findByRole("region", { name: "Inbound line: Appointments" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Campaign: Rabi follow-up" })).toBeTruthy();
    expect(screen.getAllByText("Menu")).toHaveLength(2);
    expect(screen.getByText("Missing on ThinnestAI")).toBeTruthy();
    expect(screen.getByText(/could not read that page/)).toBeTruthy();
    expect(screen.getByText("Document doc_9@org_a")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);
  });

  it("says nothing carries the agent when no line, campaign or test copy holds it", async () => {
    renderAdminPage(<AgentKnowledgePanel tenantId={TENANT} agentId={AGENT} write={WRITE} />, {
      [`GET ${PATH}`]: { agent_id: AGENT, holders: [] },
    });
    expect(await screen.findByText(/Nothing carries this agent to callers yet/)).toBeTruthy();
  });

  it("asks before removing, and Cancel removes nothing", async () => {
    const page = renderAdminPage(<AgentKnowledgePanel tenantId={TENANT} agentId={AGENT} write={WRITE} />, {
      [`GET ${PATH}`]: VIEW,
      [`POST ${PATH}/remove`]: noContent(),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Remove Document doc_9@org_a from Inbound line: Appointments",
    });
    expect(dialog.textContent).toContain("cannot be put back");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(page.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("removes the document from the engine agent that holds it", async () => {
    const page = renderAdminPage(<AgentKnowledgePanel tenantId={TENANT} agentId={AGENT} write={WRITE} />, {
      [`GET ${PATH}`]: VIEW,
      [`POST ${PATH}/remove`]: noContent(),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove it" }));
    await waitFor(() => expect(page.calls.some((c) => c.method === "POST")).toBe(true));
    const posted = page.calls.find((c) => c.method === "POST");
    expect(JSON.parse(posted?.body ?? "{}")).toEqual({
      holder_ref: "agent_line@org_a",
      handle: "doc_9@org_a",
    });
  });

  it("says when the platform's list for one engine agent could not be read", async () => {
    renderAdminPage(<AgentKnowledgePanel tenantId={TENANT} agentId={AGENT} write={WRITE} />, {
      [`GET ${PATH}`]: VIEW,
    });
    const campaign = await screen.findByRole("region", { name: "Campaign: Rabi follow-up" });
    expect(campaign.textContent).toMatch(/could not be read/);
  });
});
