import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PromptLayersPanel } from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/sections/told";

import { renderAdminRoute } from "./adminRoute";
import { problem } from "./harness";
import { agentPromptLayers } from "./fixtures/sharedReads";

/**
 * "What it is told" on the operator's agent page (D-882): the server's layers in order, each
 * with its owner, size and full text, the length against the platform's limit, and the last
 * drift verdict. The text is the server's; nothing is recomposed here.
 */

const PATH = "/v1/admin/tenants/t1/agents/agent-1/prompt/layers";

function render(body: unknown) {
  return renderAdminRoute(<PromptLayersPanel tenantId="t1" agentId="agent-1" />, {
    [PATH]: body,
  });
}

describe("what the agent is told", () => {
  it("lists every layer in order with its owner, size and text", async () => {
    await render(agentPromptLayers());
    const headings = await screen.findAllByRole("heading", { level: 3 });
    expect(headings.map((h) => h.textContent)).toEqual([
      "Calevate's opening rules",
      "The client's script",
      "Truthful answers (AI and recording)",
    ]);
    expect(screen.getByText("93 characters")).toBeTruthy();
    expect(screen.getAllByText("Same for every agent")).toHaveLength(1);
    expect(screen.getByText(/You are Asha, answering calls/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Copy The client's script" })).toBeTruthy();
    expect(screen.getByText("The voice platform holds this")).toBeTruthy();
    expect(screen.getByText(/not part of this text/)).toBeTruthy();
    expect(screen.getByText(/205 characters of 20,000 used/)).toBeTruthy();
  });

  it("says when the platform holds something different", async () => {
    await render({ ...agentPromptLayers(), drift_state: "not_applied" });
    expect(
      await screen.findByText("The voice platform holds something different"),
    ).toBeTruthy();
  });

  it("says an over-long prompt will be refused", async () => {
    await render({ ...agentPromptLayers(), limit_chars: 200, over_chars: 5 });
    expect(await screen.findByText(/5 characters over/)).toBeTruthy();
  });

  it("shows an empty state for an agent with nothing written", async () => {
    await render({
      ...agentPromptLayers(),
      has_script: false,
      layers: [],
      total_chars: 0,
      on_engine: false,
      drift_state: null,
      drift_checked_at: null,
    });
    expect(
      await screen.findByText("Nothing has been written for this agent yet."),
    ).toBeTruthy();
  });

  it("shows the failure, never an empty list, when the read fails", async () => {
    await render(problem(500, { title: "Server error" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.queryByRole("heading", { level: 3 })).toBeNull();
  });
});
