import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AgentCallHandlingRows } from "@/app/c/[slug]/agents/panels/callHandling";
import ClientCallHandlingPage from "@/app/c/[slug]/settings/call-handling/page";
import type { Me } from "@/lib/api/client";
import type { AgentCallHandling, OrganizationCallHandling } from "@/lib/api/callHandling";

import { problem, renderClientPage } from "./harness";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/c/acme/settings/call-handling",
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

/**
 * THE PAUSE BEFORE AN AGENT REPLIES AND HANGING UP WHEN IT HAS FINISHED (D-751), on the
 * organisation's settings and on one agent's Call handling: the value in force with where it
 * comes from, the choices, the body each save sends (null to inherit, a field left out
 * untouched), the quiet notice when the hang-up is off, and no vendor named.
 */

const OWNER: Me = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["agents:read", "org:read", "org:manage"],
  impersonating: false,
  withheld_acts: [],
  organization: { id: "o1", name: "Sri Stores", slug: "acme", status: "active" },
};
const STAFF: Me = { ...OWNER, role: "staff", permissions: ["agents:read", "org:read"] };

const BOUNDS = {
  turn_silence_min_ms: 200,
  turn_silence_max_ms: 3000,
  platform_turn_silence_ms: 250,
  platform_end_call_on_finish: true,
};

function organization(over: Partial<OrganizationCallHandling> = {}): OrganizationCallHandling {
  return {
    turn_silence_ms: null,
    turn_silence_ms_effective: 250,
    end_call_on_finish: null,
    end_call_on_finish_effective: true,
    bounds: BOUNDS,
    ...over,
  };
}

function agent(over: Partial<AgentCallHandling> = {}): AgentCallHandling {
  return {
    agent_id: "agent-1",
    turn_silence_ms: 700,
    turn_silence_ms_effective: 700,
    turn_silence_source: "agent",
    end_call_on_finish: null,
    end_call_on_finish_effective: true,
    end_call_on_finish_source: "platform",
    organization_turn_silence_ms: 500,
    organization_end_call_on_finish: null,
    bounds: BOUNDS,
    ...over,
  };
}

const ORG_PATH = "/v1/organization/call-handling";
const AGENT_PATH = "/v1/agents/agent-1/call-handling";

async function press(name: RegExp | string) {
  await act(async () => {
    fireEvent.click(await screen.findByRole("button", { name }));
  });
}

async function pick(name: RegExp | string) {
  await act(async () => {
    fireEvent.click(await screen.findByRole("radio", { name }));
  });
}

describe("organisation call handling", () => {
  it("shows each value in force and where it comes from", async () => {
    const { container } = await renderClientPage(<ClientCallHandlingPage />, {
      "/v1/me": OWNER,
      [ORG_PATH]: organization(),
    });
    await screen.findByText("Quick (0.25 s)");
    expect(screen.getAllByText("Calevate default")).toHaveLength(2);
    expect(screen.getByText("On")).toBeTruthy();
    expect(container.textContent).not.toMatch(/thinnest/i);
  });

  it("saves a preset with the other setting unchanged", async () => {
    const { calls } = await renderClientPage(<ClientCallHandlingPage />, {
      "/v1/me": OWNER,
      [ORG_PATH]: organization(),
      [`PUT ${ORG_PATH}`]: organization({ turn_silence_ms: 700, turn_silence_ms_effective: 700 }),
    });
    const [pauseChange] = await screen.findAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(pauseChange);
    });
    await pick(/Patient \(0\.7 s\)/);
    await press("Save pause");
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ turn_silence_ms: 700, end_call_on_finish: null });
    await screen.findByText("Patient (0.7 s)");
  });

  it("says plainly, in one quiet line, that a finished call is charged while the hang-up is off", async () => {
    await renderClientPage(<ClientCallHandlingPage />, {
      "/v1/me": OWNER,
      [ORG_PATH]: organization({ end_call_on_finish: false, end_call_on_finish_effective: false }),
    });
    await screen.findByText(/Finished calls stay connected, and charged, until the caller hangs up\./);
    expect(screen.getByRole("button", { name: /About Calls left connected/ })).toBeTruthy();
  });

  it("offers no change to someone who cannot make it", async () => {
    await renderClientPage(<ClientCallHandlingPage />, {
      "/v1/me": STAFF,
      [ORG_PATH]: organization(),
    });
    await screen.findByText("Quick (0.25 s)");
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
  });

  it("renders the server's refusal rather than a default when the read fails", async () => {
    await renderClientPage(<ClientCallHandlingPage />, {
      "/v1/me": OWNER,
      [ORG_PATH]: problem(503, { title: "Unavailable", detail: "Try again shortly." }),
    });
    await screen.findByRole("alert");
    expect(screen.queryByText(/0\.25 s/)).toBeNull();
  });
});

describe("one agent's call handling", () => {
  it("names the agent's own value and offers the organisation default by its value", async () => {
    const { calls } = await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": OWNER,
      [AGENT_PATH]: agent(),
      [`PATCH ${AGENT_PATH}`]: agent({
        turn_silence_ms: null,
        turn_silence_ms_effective: 500,
        turn_silence_source: "organization",
      }),
    });
    await screen.findByText("Patient (0.7 s)");
    expect(screen.getByText("Set for this agent")).toBeTruthy();
    const [pauseChange] = screen.getAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(pauseChange);
    });
    await pick("Organisation default (0.5 s)");
    await press("Save pause");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    // Only the pause: the hang-up is left out, so it is untouched.
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({
      turn_silence_ms: null,
    });
    await screen.findByText("Your organisation default");
  });

  it("refuses a custom pause outside the range before sending it", async () => {
    const { calls } = await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": OWNER,
      [AGENT_PATH]: agent({ turn_silence_ms: null, turn_silence_source: "organization" }),
    });
    const [pauseChange] = await screen.findAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(pauseChange);
    });
    await pick(/^Custom/);
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Seconds"), { target: { value: "5" } });
    });
    expect(screen.getByRole("alert").textContent).toContain("between 0.2 s and 3 s");
    const save = screen.getByRole("button", { name: "Save pause" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("switches the hang-up off for this agent alone", async () => {
    const { calls } = await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": OWNER,
      [AGENT_PATH]: agent(),
      [`PATCH ${AGENT_PATH}`]: agent({
        end_call_on_finish: false,
        end_call_on_finish_effective: false,
        end_call_on_finish_source: "agent",
      }),
    });
    const changes = await screen.findAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(changes[1]);
    });
    const group = screen.getByRole("group", { name: "Hang up when the conversation ends" });
    await act(async () => {
      fireEvent.click(within(group).getByRole("radio", { name: /^Off/ }));
    });
    await press("Save");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({
      end_call_on_finish: false,
    });
    await screen.findByText(/Finished calls stay connected, and charged/);
  });
});
