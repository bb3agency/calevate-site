import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PromptLayersPanel } from "@/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/sections/told";

import { renderAdminRoute } from "./adminRoute";
import { problem } from "./harness";
import { agentPromptLayers, promptHolder } from "./fixtures/sharedReads";

/**
 * "What it is told" on the operator's agent page (D-882): one anatomy per campaign, Inbound
 * line and test copy holding an engine agent (D-1019). For the holder picked, the server's
 * layers in order with owner, size and text, the length against the platform's limit, the
 * rest of what a publish sends, whether that differs from the last publish, and the last
 * drift verdict. Nothing is recomposed here.
 */

const PATH = "/v1/admin/tenants/t1/agents/agent-1/prompt/layers";

function render(body: unknown) {
  return renderAdminRoute(<PromptLayersPanel tenantId="t1" agentId="agent-1" />, {
    [PATH]: body,
  });
}

function withHolders(...holders: ReturnType<typeof promptHolder>[]) {
  return { agent_id: "agent-1", holders, more_holders: 0 };
}

describe("what the agent is told", () => {
  it("lists every layer of the holder in order with its owner, size and text", async () => {
    await render(agentPromptLayers());
    expect(await screen.findByRole("heading", { level: 3, name: "Diwali orders" })).toBeTruthy();
    const layers = screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent);
    expect(layers.slice(0, 3)).toEqual([
      "Calevate's opening rules",
      "The client's script",
      "Truthful answers (AI and recording)",
    ]);
    expect(screen.getByText("93 characters")).toBeTruthy();
    expect(screen.getAllByText("Same for every agent")).toHaveLength(1);
    expect(screen.getByText(/You are Asha, answering calls/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Copy The client's script" })).toBeTruthy();
    expect(screen.getByText("The voice platform holds this")).toBeTruthy();
    expect(screen.getByText("Live matches what would be sent now")).toBeTruthy();
    expect(screen.getByText(/not part of this text/)).toBeTruthy();
    expect(screen.getByText(/205 characters of 20,000 used/)).toBeTruthy();
  });

  it("shows the rest of what a publish sends, read-only", async () => {
    await render(agentPromptLayers());
    expect(await screen.findByRole("heading", { level: 4, name: "First words" })).toBeTruthy();
    for (const name of ["Steps", "Settings", "Tools and actions", "Knowledge"]) {
      expect(screen.getByRole("heading", { level: 4, name })).toBeTruthy();
    }
    expect(screen.getByText("Take the order")).toBeTruthy();
    expect(screen.getByText("600 s")).toBeTruthy();
    expect(screen.getByText("Hand over to a person")).toBeTruthy();
    expect(screen.getByText("save_order")).toBeTruthy();
    expect(screen.getByText("Menu")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("says plainly when it changed since the last publish", async () => {
    await render(withHolders(promptHolder({ changed_since_publish: true })));
    expect(await screen.findByText("Changed since last publish: republish")).toBeTruthy();
  });

  it("shows each holder and switches to the one picked", async () => {
    await render(
      withHolders(
        promptHolder(),
        promptHolder({
          kind: "line",
          holder_id: "line-1",
          name: "Front desk",
          status: "live",
          drift_state: "not_applied",
          training_cut_chars: 1564,
        }),
      ),
    );
    const line = await screen.findByRole("button", { name: /Front desk/ });
    expect(line.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(line);
    expect(await screen.findByRole("heading", { level: 3, name: "Front desk" })).toBeTruthy();
    expect(screen.getByText("The voice platform holds something different")).toBeTruthy();
    expect(screen.getByText(/shortened by 1,564/)).toBeTruthy();
  });

  it("says an over-long prompt will be refused", async () => {
    await render(withHolders(promptHolder({ limit_chars: 200, over_chars: 5 })));
    expect(await screen.findByText(/5 characters over/)).toBeTruthy();
  });

  it("says when nothing of the agent is on the platform", async () => {
    await render(withHolders());
    expect(
      await screen.findByText("Nothing of this agent's is on the voice platform yet."),
    ).toBeTruthy();
  });

  it("shows an empty state for a holder with nothing written", async () => {
    await render(
      withHolders(
        promptHolder({ has_script: false, layers: [], total_chars: 0, sent_now: null }),
      ),
    );
    expect(await screen.findByText("Nothing has been written for this yet.")).toBeTruthy();
  });

  it("shows the failure, never an empty list, when the read fails", async () => {
    await render(problem(500, { title: "Server error" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.queryByRole("heading", { level: 3 })).toBeNull();
  });
});
