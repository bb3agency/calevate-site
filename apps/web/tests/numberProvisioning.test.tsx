import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PhoneNumberPage from "@/app/c/[slug]/phone-number/page";
import type { Me } from "@/lib/api/client";
import { PATHS } from "@/lib/api/numberProvisioning";

import { OWN_NUMBERS_OFF, OWN_NUMBERS_STATUS_PATH } from "./fixtures/sharedReads";
import { renderClientPage, type Routes } from "./harness";
import { NO_FORWARDING_ROUTES, PHONE_NUMBERS_SETTINGS_ROUTES } from "./fixtures/forwarding";

/**
 * A number the client holds, and the one agent that answers it. Clients buy numbers in their
 * own workspace (D-693), so nothing on this screen buys through Calevate.
 */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["calls:read", "leads:read", "org:read", "org:manage", "wallet:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

function kyc(verified: boolean): unknown {
  return {
    recorded: verified,
    is_verified: verified,
    number_purchase_available: false,
    status: verified ? "accepted" : "not_started",
  };
}

/** One number the client already holds, which is what the assignment panel hangs off. */
function heldNumbers(): unknown {
  return [
    {
      id: "num-1",
      e164: "+918041234567",
      series: "standard",
      dlt_status: "registered",
      supplied_by_us: false,
      answerable: true,
      agent_id: null,
      direction: "inbound",
    },
  ];
}

/** The screen with one number held. `extra` overrides any entry. */
function routes(extra: Routes = {}): Routes {
  return {
    "/v1/me": OWNER,
    ...NO_FORWARDING_ROUTES,
    ...PHONE_NUMBERS_SETTINGS_ROUTES,
    "/v1/campaigns/numbers": heldNumbers(),
    "/v1/agents": [{ id: "agent-1", name: "Reception", status: "live" }],
    "/v1/compliance/kyc": kyc(true),
    "/v1/billing/wallet": { prepaid: true, balance_inr: "200000.00" },
    [OWN_NUMBERS_STATUS_PATH]: OWN_NUMBERS_OFF,
    ...extra,
  };
}

describe("each number has one agent, and does what that agent does", () => {
  const AGENTS = [
    { id: "agent-1", name: "Anjali", status: "live", direction: "inbound" },
    { id: "agent-out", name: "Varsha", status: "live", direction: "outbound" },
  ];
  const number = (over: Record<string, unknown> = {}) => ({
    ...(heldNumbers() as Record<string, unknown>[])[0],
    supplied_by_us: true,
    ...over,
  });
  const assigned = (agentId: string | null) => ({
    number_id: "num-1",
    agent_id: agentId,
    bound: agentId ? 1 : 0,
    released: 0,
    failed: 0,
    unsupported: 0,
  });

  it("offers every agent, each with what it will do, and asks nothing else", async () => {
    await renderClientPage(<PhoneNumberPage />, routes({ "/v1/agents": AGENTS }));

    const select = (await screen.findByLabelText(/^agent$/i)) as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.textContent)).toEqual([
      "No agent",
      "Anjali · answers calls",
      "Varsha · makes calls",
    ]);
    expect(screen.queryByRole("radiogroup", { name: /what it does/i })).toBeNull();
  });

  it("puts an agent that only makes calls on a number", async () => {
    const { calls } = await renderClientPage(
      <PhoneNumberPage />,
      routes({ "/v1/agents": AGENTS, [`POST ${PATHS.assign("num-1")}`]: assigned("agent-out") }),
    );

    fireEvent.change(await screen.findByLabelText(/^agent$/i), { target: { value: "agent-out" } });
    const save = screen.getByRole("button", { name: /^save$/i });
    await waitFor(() => expect(save.hasAttribute("disabled")).toBe(false));
    fireEvent.click(save);

    await waitFor(() => {
      const post = calls.find((call) => call.path === PATHS.assign("num-1"));
      expect(JSON.parse(post?.body ?? "{}")).toEqual({ agent_id: "agent-out", direction: null });
    });
  });

  it("opens on the number's agent and says in plain words what happens", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({ "/v1/agents": AGENTS, "/v1/campaigns/numbers": [number({ agent_id: "agent-out" })] }),
    );

    const select = (await screen.findByLabelText(/^agent$/i)) as HTMLSelectElement;
    expect(select.value).toBe("agent-out");
    expect(await screen.findByText("Varsha calls out from this number.")).toBeTruthy();
    expect(screen.getByText("Ready")).toBeTruthy();
    // Nothing changed, so Save has nothing to do.
    expect(screen.getByRole("button", { name: /^save$/i }).hasAttribute("disabled")).toBe(true);
  });

  it("names a switched-off agent and links to switching it on", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({
        "/v1/agents": [{ ...AGENTS[0], status: "paused" }],
        "/v1/campaigns/numbers": [number({ agent_id: "agent-1" })],
      }),
    );

    expect(await screen.findByText("Anjali is off")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Switch Anjali on" }).getAttribute("href")).toBe(
      "/c/acme/agents/agent-1",
    );
  });

  it("says Setting up while an answering number is still being connected", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({
        "/v1/agents": AGENTS,
        "/v1/campaigns/numbers": [number({ agent_id: "agent-1", answerable: false })],
      }),
    );

    expect(await screen.findByText("Setting up")).toBeTruthy();
    expect(screen.getByText("Anjali answers calls to this number.")).toBeTruthy();
  });

  it("asks for an agent on a number with none", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({ "/v1/agents": AGENTS, "/v1/campaigns/numbers": [number({ agent_id: null })] }),
    );

    expect(await screen.findByText("No agent yet")).toBeTruthy();
    expect(screen.getByText("Pick an agent to use this number.")).toBeTruthy();
  });

  it("does not report a binding the carrier refused", async () => {
    await renderClientPage(
      <PhoneNumberPage />,
      routes({
        "/v1/agents": AGENTS,
        [`POST ${PATHS.assign("num-1")}`]: { ...assigned("agent-1"), bound: 0, failed: 1 },
      }),
    );

    fireEvent.change(await screen.findByLabelText(/^agent$/i), { target: { value: "agent-1" } });
    const save = screen.getByRole("button", { name: /^save$/i });
    await waitFor(() => expect(save.hasAttribute("disabled")).toBe(false));
    fireEvent.click(save);

    expect(await screen.findByText(/could not connect it to that agent/i)).toBeTruthy();
  });
});
