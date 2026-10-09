import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LineProtectionPage from "@/app/c/[slug]/settings/line-protection/page";
import StatusPage from "@/app/status/page";
import { normaliseIndianMobile } from "@/lib/api/healer";

import { problem, renderClientPage, type Routes } from "./harness";

/**
 * The client's Line protection screen and the public status page (D-701).
 *
 * What matters: the problem is described in the server's own words; the backup phone is
 * an Indian mobile or nothing; turning a held line back on and approving a script rollback
 * each ask first; a failed status read never reads as "everything is working".
 */

const ME = {
  user_id: "u1",
  realm: "client",
  role: "owner",
  permissions: ["org:read", "org:manage"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

const INCIDENT = {
  id: "inc-1",
  agent_id: "agent-1",
  agent_name: "Reception",
  kind: "line_protected",
  protection: "paused",
  state: "open",
  opened_at: "2026-10-09T04:00:00Z",
  resolved_at: null,
  campaigns_paused: 0,
  requeued: 0,
  missed_calls: 0,
  must_act: false,
  can_restore: true,
  headline: "“Reception” is not taking calls properly",
  what_happened: "Most recent calls to “Reception” were cut off or went silent.",
  what_we_did: "We stopped it answering.",
  your_part: "Nothing right now.",
  call_backs: [{ call_id: "call-1", at: "2026-10-09T04:05:00Z" }],
};

const PROPOSAL = {
  id: "p-1",
  agent_id: "agent-1",
  agent_name: "Reception",
  kind: "rollback_prompt",
  status: "pending",
  title: "Go back to the previous script",
  body: "Calls started going worse soon after the script was last changed.",
  action_label: "Restore previous script",
  screen: null,
  can_apply: true,
  created_at: "2026-10-09T04:10:00Z",
  decided_at: null,
};

function routes(over: Routes = {}): Routes {
  return {
    "/v1/me": ME,
    "/v1/healer/incidents?days=30&limit=20": { open: 1, items: [INCIDENT] },
    "/v1/healer/fallback-phone": { phone_e164: null, updated_at: null, forwarding_supported: true },
    "/v1/healer/proposals?days=30&limit=20": { pending: 1, items: [PROPOSAL] },
    ...over,
  };
}

describe("normaliseIndianMobile", () => {
  it("accepts the ways people type an Indian mobile", () => {
    expect(normaliseIndianMobile("98765 43210")).toBe("+919876543210");
    expect(normaliseIndianMobile("+91 98765-43210")).toBe("+919876543210");
    expect(normaliseIndianMobile("919876543210")).toBe("+919876543210");
    expect(normaliseIndianMobile("+1 415 555 0100")).toBe("+14155550100");
  });
});

describe("the client's line protection screen", () => {
  it("shows the problem in the server's words, with the callers to ring back", async () => {
    await renderClientPage(<LineProtectionPage />, routes());
    expect(await screen.findByText(INCIDENT.headline)).toBeTruthy();
    expect(screen.getByText(INCIDENT.what_we_did)).toBeTruthy();
    expect(screen.getByRole("link", { name: /Call at/ }).getAttribute("href")).toContain(
      "/c/acme/calls/call-1",
    );
  });

  it("refuses a number that is not an Indian mobile before sending it", async () => {
    const { calls } = await renderClientPage(<LineProtectionPage />, routes());
    const input = await screen.findByLabelText("Indian mobile number");
    fireEvent.change(input, { target: { value: "+1 415 555 0100" } });
    const save = screen.getByRole("button", { name: "Save backup phone" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("saves a typed mobile in the one form the server accepts", async () => {
    const { calls } = await renderClientPage(
      <LineProtectionPage />,
      routes({
        "PUT /v1/healer/fallback-phone": {
          phone_e164: "+919876543210",
          updated_at: "2026-10-09T05:00:00Z",
          forwarding_supported: true,
        },
      }),
    );
    fireEvent.change(await screen.findByLabelText("Indian mobile number"), {
      target: { value: "98765 43210" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save backup phone" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ phone_e164: "+919876543210" });
  });

  it("asks before turning a held line back on", async () => {
    const { calls } = await renderClientPage(
      <LineProtectionPage />,
      routes({
        "POST /v1/healer/incidents/inc-1/restore": { ...INCIDENT, state: "resolved", can_restore: false },
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Turn the line back on now" }));
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Turn it back on" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/v1/healer/incidents/inc-1/restore")).toBe(true),
    );
  });

  it("asks before applying a suggested script rollback", async () => {
    const { calls } = await renderClientPage(
      <LineProtectionPage />,
      routes({ "POST /v1/healer/proposals/p-1/apply": { ...PROPOSAL, status: "applied" } }),
    );
    const buttons = await screen.findAllByRole("button", { name: "Restore previous script" });
    fireEvent.click(buttons[0]);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    const confirm = await screen.findAllByRole("button", { name: "Restore previous script" });
    fireEvent.click(confirm[confirm.length - 1]);
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/v1/healer/proposals/p-1/apply")).toBe(true),
    );
  });
});

describe("the public status page", () => {
  it("never reads as working when the status could not be loaded", async () => {
    await renderClientPage(
      <StatusPage />,
      { "/v1/public/status": problem(503, { title: "Service unavailable" }) },
    );
    expect(await screen.findByText(/could not load the current status/)).toBeTruthy();
    expect(screen.queryByText(/Everything is working normally/)).toBeNull();
  });

  it("names each part's state in words", async () => {
    await renderClientPage(<StatusPage />, {
      "/v1/public/status": {
        components: [
          { key: "calls", name: "Phone calls", state: "outage" },
          { key: "numbers", name: "Phone numbers", state: "operational" },
          { key: "dashboard", name: "Dashboard", state: "operational" },
          { key: "assistant", name: "Assistant", state: "operational" },
        ],
        incidents: [],
        updated_at: "2026-10-09T04:20:00Z",
      },
    });
    expect(await screen.findByText("Not working")).toBeTruthy();
    expect(screen.getByText(/Some parts of the service have problems/)).toBeTruthy();
  });
});
