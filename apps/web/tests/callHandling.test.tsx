import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AgentCallHandlingRows } from "@/app/c/[slug]/agents/panels/callHandling";
import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import { ToastProvider } from "@/components/arc/toast";
import TenantCallHandlingPage from "@/app/admin/tenants/[tenantId]/call-handling/page";
import type { Me } from "@/lib/api/client";
import type { AgentCallHandling, OrganizationCallHandling } from "@/lib/api/callHandling";

import {
  CALL_HANDLING_BOUNDS,
  VOICE_EFFECTIVE_DEFAULTS,
  VOICE_ORGANIZATION_NONE,
  VOICE_OWN_NONE,
  VOICE_SOURCES_PLATFORM,
} from "./fixtures/sharedReads";
import { renderAdminRoute, routeParams } from "./adminRoute";
import { problem, renderClientPage } from "./harness";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
  usePathname: () => "/c/acme/agents/agent-1",
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
 * THE PAUSE BEFORE AN AGENT REPLIES AND HANGING UP WHEN IT HAS FINISHED (D-751), on one
 * agent's Settings and the operator's console: the value in force with where it comes from,
 * the choices, "Just this agent" or "All my agents" and the door each save takes, the body it
 * sends (null to inherit, a field left out untouched), the quiet notice when the hang-up is
 * off, and no vendor named.
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

const BOUNDS = CALL_HANDLING_BOUNDS;

function organization(over: Partial<OrganizationCallHandling> = {}): OrganizationCallHandling {
  return {
    turn_silence_ms: null,
    turn_silence_ms_effective: 250,
    end_call_on_finish: null,
    end_call_on_finish_effective: true,
    ...VOICE_OWN_NONE,
    ...VOICE_EFFECTIVE_DEFAULTS,
    agents_with_own: [],
    agents_with_own_total: 0,
    bounds: BOUNDS,
    ...over,
  };
}

/** An agent in the account read that set some values of its own. */
function ownAgent(
  over: Partial<OrganizationCallHandling["agents_with_own"][number]> = {},
): OrganizationCallHandling["agents_with_own"][number] {
  return {
    agent_id: "agent-1",
    name: "Anjali",
    turn_silence_ms: null,
    end_call_on_finish: null,
    ...VOICE_OWN_NONE,
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
    opening_waits_for_caller: false,
    ...VOICE_OWN_NONE,
    ...VOICE_EFFECTIVE_DEFAULTS,
    ...VOICE_SOURCES_PLATFORM,
    ...VOICE_ORGANIZATION_NONE,
    bounds: BOUNDS,
    ...over,
  };
}

const ORG_PATH = "/v1/organization/call-handling";
const ALL_PATH = "/v1/organization/call-handling/all-agents";
const AGENT_PATH = "/v1/agents/agent-1/call-handling";

function allAgents(organizationRead: OrganizationCallHandling, agentsReset: number) {
  return { organization: organizationRead, agents_reset: agentsReset };
}

/** The agent's rows inside the toast host, so a save's confirmation can be read. */
function rows() {
  return (
    <ToastProvider>
      <AgentCallHandlingRows agentId="agent-1" />
    </ToastProvider>
  );
}

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

/** Ticks or unticks a "Use the … default" checkbox. */
async function toggle(name: RegExp | string) {
  await act(async () => {
    fireEvent.click(await screen.findByRole("checkbox", { name }));
  });
}

describe("one agent's call handling", () => {
  it("names the agent's own value and offers the organisation default by its value", async () => {
    const { calls } = await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": OWNER,
      [ORG_PATH]: organization(),
      [AGENT_PATH]: agent(),
      [`PATCH ${AGENT_PATH}`]: agent({
        turn_silence_ms: null,
        turn_silence_ms_effective: 500,
        turn_silence_source: "organization",
      }),
    });
    await screen.findByText("Unhurried (0.7 s)");
    expect(screen.getByText("Just this agent")).toBeTruthy();
    const [pauseChange] = screen.getAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(pauseChange);
    });
    expect(((await screen.findByRole("radio", { name: /^Just this agent/ })) as HTMLInputElement).checked).toBe(true);
    await toggle("Use the setting your agents share: Relaxed (0.5 s)");
    await press("Save pause");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    // Only the pause: the hang-up is left out, so it is untouched.
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({
      turn_silence_ms: null,
    });
    await screen.findByText("All my agents");
  });

  it("holds a custom pause inside the server's range and saves it in milliseconds", async () => {
    const { calls } = await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": OWNER,
      [ORG_PATH]: organization(),
      [AGENT_PATH]: agent({ turn_silence_ms: null, turn_silence_source: "organization" }),
      [`PATCH ${AGENT_PATH}`]: agent({ turn_silence_ms: 3000, turn_silence_ms_effective: 3000 }),
    });
    const [pauseChange] = await screen.findAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(pauseChange);
    });
    await toggle(/^Use the setting your agents share/);
    const slider = screen.getByLabelText("Pause") as HTMLInputElement;
    expect([slider.min, slider.max, slider.step]).toEqual(["200", "3000", "50"]);
    expect(screen.getByText("0.2 s")).toBeTruthy();
    // Past the top of the range, the slider stops at the server's maximum.
    await act(async () => {
      fireEvent.change(slider, { target: { value: "5000" } });
    });
    expect(slider.getAttribute("aria-valuetext")).toBe("3 s");
    // Off the presets, none of them reads as chosen.
    const presets = screen.getByRole("radiogroup", { name: "Pause before the agent replies" });
    expect(within(presets).queryByRole("radio", { checked: true })).toBeNull();
    expect(screen.getByText("A pause of your own.")).toBeTruthy();
    await press("Save pause");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({
      turn_silence_ms: 3000,
    });
  });

  it("switches the hang-up off for this agent alone", async () => {
    const { calls } = await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": OWNER,
      [ORG_PATH]: organization(),
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
    await toggle("Use the Calevate default: On");
    const hangUp = screen.getByRole("switch", { name: /^Hang up when the agent has finished/ });
    expect((hangUp as HTMLInputElement).checked).toBe(true);
    await act(async () => {
      fireEvent.click(hangUp);
    });
    expect(screen.getByText("The call stays connected, and charged, until the caller hangs up.")).toBeTruthy();
    await press("Save");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({
      end_call_on_finish: false,
    });
    await screen.findByText(/Finished calls stay connected, and charged/);
  });

  it("switches waiting for the person's hello on, with its one plain line", async () => {
    const { calls, container } = await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": OWNER,
      [ORG_PATH]: organization(),
      [AGENT_PATH]: agent(),
      [`PATCH ${AGENT_PATH}`]: agent({ opening_waits_for_caller: true }),
    });
    await screen.findByText("Wait for them to say hello");
    // Off, the row's line says what off does, never what on would.
    expect(screen.getByText("Your agent speaks as soon as the call connects.")).toBeTruthy();
    expect(screen.queryByText(/Your agent speaks right after the first words of the person who picks up/)).toBeNull();
    const changes = screen.getAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(changes[2]);
    });
    // The agent's own setting: no default to follow, so no "Use the … default" box.
    expect(screen.queryByRole("checkbox", { name: /^Use the/ })).toBeNull();
    const waits = screen.getByRole("switch", { name: /^Wait for them to say hello/ });
    expect((waits as HTMLInputElement).checked).toBe(false);
    await act(async () => {
      fireEvent.click(waits);
    });
    await press("Save");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({
      opening_waits_for_caller: true,
    });
    await waitFor(() => expect(screen.queryByRole("switch", { name: /^Wait for them/ })).toBeNull());
    expect(container.textContent).not.toMatch(/thinnest|cartesia|sarvam/i);
  });

  it("hides how long to wait for hello until the platform offers it", async () => {
    await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": OWNER,
      [ORG_PATH]: organization(),
      [AGENT_PATH]: agent({ opening_waits_for_caller: true }),
    });
    await screen.findByText("Wait for them to say hello");
    expect(screen.getByText(/or after 4 s if they stay silent/)).toBeTruthy();
    expect(screen.queryByText("How long to wait for hello")).toBeNull();
  });

  it("sets how long to wait for hello for this agent, under the switch, in tenths", async () => {
    const offered = {
      ...BOUNDS,
      opening_wait_available: true,
      platform_opening_wait_ms: 1500,
    };
    const { calls, container } = await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": OWNER,
      [ORG_PATH]: organization({ bounds: offered }),
      [AGENT_PATH]: agent({
        opening_waits_for_caller: true,
        opening_wait_ms_effective: 1500,
        bounds: offered,
      }),
      [`PATCH ${AGENT_PATH}`]: agent({
        opening_waits_for_caller: true,
        opening_wait_ms: 1000,
        opening_wait_ms_effective: 1000,
        opening_wait_ms_source: "agent",
        bounds: offered,
      }),
    });
    await screen.findByText("How long to wait for hello");
    expect(screen.getByText(/or after 1.5 s if they stay silent/)).toBeTruthy();
    expect(screen.getByText(/If nobody speaks, your agent opens after this\. Calevate default\./)).toBeTruthy();
    const changes = screen.getAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(changes[3]);
    });
    await toggle(/^Use the Calevate default: 1.5 s/);
    const slider = screen.getByLabelText("Wait") as HTMLInputElement;
    expect([slider.min, slider.max, slider.step]).toEqual(["500", "10000", "100"]);
    await act(async () => {
      fireEvent.change(slider, { target: { value: "1400" } });
    });
    await press("Save wait");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({
      opening_wait_ms: 1400,
    });
    expect(container.textContent).not.toMatch(/thinnest|cartesia|sarvam/i);
  });

  it("saves a pause for all agents through the account's door, with Calevate's as the default", async () => {
    const { calls } = await renderClientPage(rows(), {
      "/v1/me": OWNER,
      [ORG_PATH]: organization({
        agents_with_own: [
          // This agent is not counted: it is the one being changed.
          ownAgent({ turn_silence_ms: 700 }),
          ownAgent({ agent_id: "agent-2", name: "Ravi", turn_silence_ms: 500 }),
          ownAgent({ agent_id: "agent-3", name: "Sita", turn_silence_ms: 300 }),
        ],
        agents_with_own_total: 3,
      }),
      [AGENT_PATH]: agent(),
      [`POST ${ALL_PATH}`]: allAgents(organization({ turn_silence_ms: 700, turn_silence_ms_effective: 700 }), 3),
    });
    const [pauseChange] = await screen.findAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(pauseChange);
    });
    // Just this agent, unchanged: nothing to save yet.
    expect(screen.queryByRole("button", { name: "Save pause" })).toBeNull();
    await pick(/^All my agents/);
    expect(screen.getByText("Every agent uses this. 2 agents that have their own setting will change too.")).toBeTruthy();
    // For every agent, the default to follow is Calevate's, not the shared one being set.
    expect(screen.getByRole("checkbox", { name: "Use the Calevate default: Quick (0.25 s)" })).toBeTruthy();
    // The same value as this agent's own is still a change: the other agents move to it.
    await press("Save for all agents");
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(ALL_PATH);
    expect(JSON.parse(post?.body ?? "{}")).toEqual({ turn_silence_ms: 700 });
    await screen.findByText("Saved for all your agents");
  });

  it("keeps the editor open with the server's refusal beside it when a save for all agents fails", async () => {
    await renderClientPage(rows(), {
      "/v1/me": OWNER,
      [ORG_PATH]: organization(),
      [AGENT_PATH]: agent(),
      [`POST ${ALL_PATH}`]: problem(403, {
        title: "Not allowed",
        detail: "Only the account owner can change every agent.",
      }),
    });
    const changes = await screen.findAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(changes[1]);
    });
    await pick(/^All my agents/);
    expect(screen.getByText("Every agent uses this, and so will new ones.")).toBeTruthy();
    await press("Save for all agents");
    await screen.findAllByText("Only the account owner can change every agent.");
    // The editor stays open on the choice made, so the owner can change it and try again.
    expect((screen.getByRole("radio", { name: /^All my agents/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("button", { name: /Save for all agents|Try again/ })).toBeTruthy();
  });

  it("keeps waiting for hello to this agent alone", async () => {
    await renderClientPage(rows(), {
      "/v1/me": OWNER,
      [ORG_PATH]: organization(),
      [AGENT_PATH]: agent(),
    });
    const changes = await screen.findAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(changes[2]);
    });
    expect(screen.queryByRole("radio", { name: /^All my agents/ })).toBeNull();
  });

  it("offers no change to the switch to someone who cannot make it", async () => {
    await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": STAFF,
      [AGENT_PATH]: agent({ opening_waits_for_caller: true }),
    });
    await screen.findByText("Wait for them to say hello");
    expect(screen.getByText(/Your agent speaks right after the first words of the person who picks up/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
  });
});

/**
 * F3, F9: if the caller goes quiet, the lines said while the agent looks something up, and a
 * background sound. Each row sends only its own fields, for this agent or for all of them,
 * offers the default by what it resolves to, and checks the server's limits before sending.
 */
describe("the voice settings", () => {
  it("saves never asking for all agents, naming the agent with its own that changes too", async () => {
    const { calls, container } = await renderClientPage(rows(), {
      "/v1/me": OWNER,
      [ORG_PATH]: organization({
        agents_with_own: [ownAgent({ agent_id: "agent-2", name: "Ravi", nudge_after_seconds: 30 })],
        agents_with_own_total: 1,
      }),
      [AGENT_PATH]: agent(),
      [`POST ${ALL_PATH}`]: allAgents(organization({ nudge_after_seconds: 0, nudge_after_seconds_effective: 0 }), 1),
    });
    await screen.findByText("Asks after 8 s, once · hangs up after 20 s of silence");
    const changes = screen.getAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(changes[3]);
    });
    await pick(/^All my agents/);
    expect(screen.getByText("Every agent uses this. 1 agent that has its own setting will change too.")).toBeTruthy();
    await toggle("Use the Calevate default: asks after 8 s");
    await pick("Never ask");
    await press("Save for all agents");
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "POST")?.body ?? "{}")).toEqual({
      nudge_after_seconds: 0,
      nudge_count: null,
      nudge_phrase: null,
      end_after_silence_seconds: null,
    });
    // Never the agent's own door: the change is for every agent.
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
    await screen.findByText("Saved for all your agents");
    expect(container.textContent).not.toMatch(/thinnest|cartesia|sarvam/i);
  });

  it("sets the wait, the count, the agent's own question and the hang-up, each inside the server's range", async () => {
    const { calls } = await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": OWNER,
      [ORG_PATH]: organization(),
      [AGENT_PATH]: agent(),
      [`PATCH ${AGENT_PATH}`]: agent({
        nudge_after_seconds: 12,
        nudge_after_seconds_effective: 12,
        nudge_count: 3,
        nudge_count_effective: 3,
        end_after_silence_seconds: 180,
        end_after_silence_seconds_effective: 180,
      }),
    });
    await screen.findByText("Asks after 8 s, once · hangs up after 20 s of silence");
    const changes = screen.getAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(changes[3]);
    });
    // Nothing is offered as a bare number box; the rule for an empty box is gone with it.
    expect(screen.queryByRole("spinbutton")).toBeNull();
    expect(screen.queryByText(/empty:/)).toBeNull();

    await toggle("Use the Calevate default: asks after 8 s");
    const wait = screen.getByLabelText("Quiet before asking") as HTMLInputElement;
    expect([wait.min, wait.max, wait.value]).toEqual(["5", "180", "8"]);
    await act(async () => {
      fireEvent.change(wait, { target: { value: "12" } });
    });
    expect(wait.getAttribute("aria-valuetext")).toBe("12 s");
    const times = screen.getByRole("radiogroup", { name: "How many times" });
    expect(within(times).getAllByRole("radio")).toHaveLength(5);
    await act(async () => {
      fireEvent.click(within(times).getByRole("radio", { name: "3" }));
    });

    await toggle("Use the Calevate default: the standard question");
    await pick("Our own words");
    const question = screen.getByLabelText("The question");
    await act(async () => {
      fireEvent.change(question, { target: { value: "   " } });
    });
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => {
      fireEvent.change(question, { target: { value: " Hello, still with me? " } });
    });

    await toggle("Use the Calevate default: hangs up after 20 s");
    await act(async () => {
      fireEvent.change(screen.getByLabelText("Silence before hanging up"), { target: { value: "999" } });
    });
    await press("Save");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({
      nudge_after_seconds: 12,
      nudge_count: 3,
      nudge_phrase: "Hello, still with me?",
      end_after_silence_seconds: 180,
    });
  });

  it("sends an agent's own lines, trimmed, and refuses a line that is too long", async () => {
    const { calls } = await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": OWNER,
      [ORG_PATH]: organization(),
      [AGENT_PATH]: agent(),
      [`PATCH ${AGENT_PATH}`]: agent({
        filler_lines: ["One moment please"],
        filler_lines_effective: ["One moment please"],
        filler_lines_source: "agent",
      }),
    });
    await screen.findByText("The standard lines");
    const changes = screen.getAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(changes[4]);
    });
    await toggle("Use the Calevate default: the standard lines");
    await pick("Our own lines");
    const box = screen.getByLabelText(/One line per row/);
    await act(async () => {
      fireEvent.change(box, { target: { value: "x".repeat(61) } });
    });
    expect(screen.getByText("Each line can be up to 60 characters.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save lines" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => {
      fireEvent.change(box, { target: { value: "  One moment please  \n\n" } });
    });
    await press("Save lines");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({
      filler_lines: ["One moment please"],
    });
    await screen.findByText("1 line of your own");
  });

  it("switches an office sound on at a volume, and offers the default by its value", async () => {
    const { calls } = await renderClientPage(<AgentCallHandlingRows agentId="agent-1" />, {
      "/v1/me": OWNER,
      [ORG_PATH]: organization(),
      [AGENT_PATH]: agent(),
      [`PATCH ${AGENT_PATH}`]: agent({
        ambience: "office",
        ambience_effective: "office",
        ambience_volume_pct: 30,
        ambience_volume_pct_effective: 30,
        ambience_source: "agent",
      }),
    });
    await screen.findByText("Background sound");
    const changes = screen.getAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(changes[5]);
    });
    const followDefault = screen.getByRole("checkbox", { name: "Use the Calevate default: Off" });
    expect((followDefault as HTMLInputElement).checked).toBe(true);
    await act(async () => {
      fireEvent.click(followDefault);
    });
    await pick("Office");
    await act(async () => {
      fireEvent.change(screen.getByLabelText(/^Volume/), { target: { value: "30" } });
    });
    await press("Save sound");
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({
      ambience: "office",
      ambience_volume_pct: 30,
    });
    await screen.findByText("Office at 30%");
  });
});

describe("a client's call handling defaults, from the operator console", () => {
  const TENANT = "t1";
  const ADMIN_PATH = `/v1/admin/organizations/${TENANT}/call-handling`;
  const operator = (permissions: string[]): AdminMe => ({
    realm: "admin",
    user_id: "op-1",
    role: "operator",
    permissions,
  });
  const routes = (permissions: string[]) => ({
    [ADMIN_ME_PATH]: operator(permissions),
    [`/v1/admin/tenants/${TENANT}`]: { id: TENANT, name: "Sri Stores", slug: "acme" },
    [ADMIN_PATH]: organization({ turn_silence_ms: 500, turn_silence_ms_effective: 500 }),
  });

  it("saves through the operator's own door, not a view-as session", async () => {
    const { calls } = await renderAdminRoute(
      <TenantCallHandlingPage params={routeParams({ tenantId: TENANT })} />,
      {
        ...routes(["org:read", "admin:tenants"]),
        [`PUT ${ADMIN_PATH}`]: organization({ turn_silence_ms: 700, turn_silence_ms_effective: 700 }),
      },
    );
    await screen.findByText("Relaxed (0.5 s)");
    expect(screen.getByText("This client's default")).toBeTruthy();
    const [pauseChange] = await screen.findAllByRole("button", { name: "Change" });
    await act(async () => {
      fireEvent.click(pauseChange!);
    });
    expect(
      (screen.getByRole("checkbox", { name: /^Use the Calevate default/ }) as HTMLInputElement).checked,
    ).toBe(false);
    await pick("Unhurried");
    await press("Save pause");
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.path).toBe(ADMIN_PATH);
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ turn_silence_ms: 700, end_call_on_finish: null });
    await screen.findByText("Unhurried (0.7 s)");
  });

  it("names the agent that plays its own sound while the client's default is off, linked to it", async () => {
    await renderAdminRoute(<TenantCallHandlingPage params={routeParams({ tenantId: TENANT })} />, {
      ...routes(["org:read", "admin:tenants"]),
      [ADMIN_PATH]: organization({
        agents_with_own: [ownAgent({ ambience: "office", ambience_volume_pct: 15 })],
        agents_with_own_total: 1,
      }),
    });
    const link = await screen.findByRole("link", { name: "Anjali" });
    expect(link.getAttribute("href")).toBe(`/admin/tenants/${TENANT}/agents/agent-1/prompt?section=limits`);
    expect(link.parentElement?.textContent).toBe("Anjali uses its own: Office at 15%");
    // The opening wait is an agent's own setting: never offered as an account default.
    expect(screen.queryByText("Wait for them to say hello")).toBeNull();
  });

  it("offers no change to an operator without the tenant permission", async () => {
    await renderAdminRoute(
      <TenantCallHandlingPage params={routeParams({ tenantId: TENANT })} />,
      routes(["org:read"]),
    );
    await screen.findByText("Relaxed (0.5 s)");
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
  });

  it("renders the server's refusal when the read fails", async () => {
    await renderAdminRoute(<TenantCallHandlingPage params={routeParams({ tenantId: TENANT })} />, {
      ...routes(["org:read", "admin:tenants"]),
      [ADMIN_PATH]: problem(404, { title: "Not found", detail: "No such client." }),
    });
    await screen.findByText("No such client.");
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
  });
});
