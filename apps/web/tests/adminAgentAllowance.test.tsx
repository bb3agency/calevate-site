import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentAllowancePanel } from "@/app/admin/tenants/[tenantId]/numbers/AgentAllowancePanel";
import type { AgentAllowance } from "@/lib/api/engineWorkspaces";

import { problem, renderAdminPage } from "./harness";

/**
 * CALLING SETUPS on the operator's Numbers page: the cap in force and where it comes from,
 * a bounded entry that sends step-up, empty for the console default (`null` on the wire), and
 * no control before the workspace exists or for an operator who cannot write.
 */

const PATH = "/v1/admin/engine-workspaces/tenants/t1/agent-allowance";

function allowance(over: Partial<AgentAllowance> = {}): AgentAllowance {
  return {
    limit: 2,
    agent_allowance: null,
    default: 2,
    in_use: 1,
    settable: true,
    min_allowance: 1,
    max_allowance: 1000,
    ...over,
  };
}

function enter(value: string) {
  const box = screen.getByRole("spinbutton", { name: "Calling setups" });
  fireEvent.change(box, { target: { value } });
  fireEvent.blur(box);
}

async function change() {
  await act(async () => {
    fireEvent.click(await screen.findByRole("button", { name: "Change" }));
  });
}

describe("calling setups", () => {
  it("shows the console default and how many are in use", async () => {
    renderAdminPage(<AgentAllowancePanel tenantId="t1" canWrite />, { [PATH]: allowance() });
    await screen.findByText("2 setups, 1 in use");
    expect(screen.getByText("Console default (2)")).toBeTruthy();
  });

  it("records a raise with step-up and returns to the default with an empty field", async () => {
    const { calls } = renderAdminPage(<AgentAllowancePanel tenantId="t1" canWrite />, {
      [PATH]: allowance(),
      [`PUT ${PATH}`]: allowance({ limit: 3, agent_allowance: 3 }),
    });
    await change();
    enter("3");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ agent_allowance: 3 });
    expect(put?.headers["X-Confirm-Action"]).toBe("set_agent_allowance:t1");
    await screen.findByText("3 setups, 1 in use");
    expect(screen.getByText("Raised by ThinnestAI for this client")).toBeTruthy();
  });

  it("sends null when the field is emptied", async () => {
    const { calls } = renderAdminPage(<AgentAllowancePanel tenantId="t1" canWrite />, {
      [PATH]: allowance({ limit: 3, agent_allowance: 3 }),
      [`PUT ${PATH}`]: allowance(),
    });
    await change();
    enter("");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({ agent_allowance: null });
  });

  it("shows a refusal under the field", async () => {
    renderAdminPage(<AgentAllowancePanel tenantId="t1" canWrite />, {
      [PATH]: allowance(),
      [`PUT ${PATH}`]: problem(422, {
        code: "engine_workspace_not_provisioned",
        detail: "This client has no voice workspace yet, so there is no cap to raise.",
      }),
    });
    await change();
    enter("3");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    await screen.findByText(/no voice workspace yet/);
  });

  it("offers no control before the workspace exists", async () => {
    renderAdminPage(<AgentAllowancePanel tenantId="t1" canWrite />, {
      [PATH]: allowance({ settable: false, in_use: null }),
    });
    await screen.findByText("2 setups");
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
    expect(screen.getByText(/No workspace yet/)).toBeTruthy();
  });

  it("offers no control to an operator who cannot write", async () => {
    renderAdminPage(<AgentAllowancePanel tenantId="t1" canWrite={false} />, { [PATH]: allowance() });
    await screen.findByText("2 setups, 1 in use");
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
  });
});
