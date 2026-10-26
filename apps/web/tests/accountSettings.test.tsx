import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LowBalanceAlertPanel } from "@/app/c/[slug]/billing/LowBalanceAlertPanel";
import { EditEndpointDrawer } from "@/app/c/[slug]/integrations/EditEndpointDrawer";
import { AgentDrawer } from "@/app/c/[slug]/lead-sources/AgentDrawer";
import type { Agent } from "@/lib/api/agents";
import { useAgents } from "@/lib/api/agents";
import type { Endpoint } from "@/lib/api/integrations";
import type { LeadSource } from "@/lib/api/leadSources";
import { useClientSession } from "@/lib/api/session";
import type { Wallet } from "@/lib/api/wallet";

import { problem, renderClientPage } from "./harness";

/**
 * D-893 lane L6: the account settings a page and Pip share — a destination's events and
 * extras, the agent a lead source rings with, and the low-credit warning line. Each sends
 * exactly what the server's own model expects and says a refusal where it happened.
 */

const ME = {
  user_id: "u1",
  tenant_id: "t1",
  role: "owner",
  permissions: ["org:read", "org:manage", "billing:read", "wallet:read"],
  impersonating: false,
};

const ALLOWED = { allowed: true, reason: null, unknown: false };

const ENDPOINT: Endpoint = {
  id: "e1",
  kind: "webhook",
  url: "https://crm.example.com/hooks/calevate",
  events: ["lead.created"],
  active: true,
  secret_fingerprint: "ab12",
  include_recording_url: false,
  include_transcript: false,
  include_raw_transcript: false,
  created_at: "2026-10-20T10:00:00Z",
  previous_secret_expires_at: null,
};

const CATALOGUE = ["lead.created", "lead.updated", "call.completed", "call.recording_ready"];

function EditHarness({ endpoint, onClose }: { endpoint: Endpoint; onClose: () => void }) {
  return (
    <EditEndpointDrawer
      endpoint={endpoint}
      catalogue={CATALOGUE}
      session={useClientSession()}
      write={ALLOWED}
      onClose={onClose}
    />
  );
}

describe("changing what a destination is sent", () => {
  it("opens on what it sends now and saves events with the transcript extra", async () => {
    let closed = false;
    const { calls } = await renderClientPage(
      <EditHarness endpoint={ENDPOINT} onClose={() => (closed = true)} />,
      {
        "/v1/me": ME,
        "PATCH /v1/integrations/endpoints/e1": { ...ENDPOINT, events: ["lead.created", "call.completed"] },
      },
    );
    expect((screen.getByRole("checkbox", { name: /lead\.created/ }) as HTMLInputElement).checked).toBe(true);
    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: /call\.completed/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("checkbox", { name: /The transcript, redacted/ }));
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({
      events: ["lead.created", "call.completed"],
      include_recording_url: false,
      include_transcript: true,
      include_raw_transcript: false,
    });
    await waitFor(() => expect(closed).toBe(true));
  });

  it("offers a spreadsheet events only, and keeps the drawer open on a refusal", async () => {
    const sheet: Endpoint = { ...ENDPOINT, kind: "google_sheets", url: "sheet-1" };
    await renderClientPage(<EditHarness endpoint={sheet} onClose={() => undefined} />, {
      "/v1/me": ME,
      "PATCH /v1/integrations/endpoints/e1": problem(422, {
        type: "https://calevate.tech/problems/endpoint_inactive",
        title: "Nothing to change",
        detail: "This endpoint is switched off, so there is nothing to change.",
      }),
    });
    expect(screen.queryByRole("checkbox", { name: /call\.recording_ready/ })).toBeNull();
    expect(screen.queryByText(/The transcript, redacted/)).toBeNull();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    await screen.findByText(/switched off, so there is nothing to change/);
  });
});

const SOURCE: LeadSource = {
  id: "0192f3a4-5b6c-7d8e-9f01-23456789abcd",
  source: "website_form",
  ingest_path: "/hooks/v1/ingest/x",
  agent_id: null,
  active: true,
  mapping: {},
  secret_fingerprint: "cd34",
  previous_secret_expires_at: null,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:00:00Z",
};

function AgentHarness({ onClose }: { onClose: () => void }) {
  const session = useClientSession();
  return <AgentDrawer source={SOURCE} agents={useAgents(session)} session={session} onClose={onClose} />;
}

describe("choosing who answers a lead source", () => {
  it("opens on no agent and saves the chosen one", async () => {
    const agents: Partial<Agent>[] = [{ id: "a1", name: "Reception" }];
    const { calls } = await renderClientPage(<AgentHarness onClose={() => undefined} />, {
      "/v1/me": ME,
      "/v1/agents": agents,
      [`PATCH /v1/lead-sources/${SOURCE.id}`]: { id: SOURCE.id, agent_id: "a1" },
    });
    const picker = (await screen.findByRole("combobox", { name: "Agent" })) as HTMLSelectElement;
    await waitFor(() => expect(picker.options.length).toBe(2));
    expect(picker.value).toBe("");
    fireEvent.change(picker, { target: { value: "a1" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PATCH")?.body ?? "{}")).toEqual({ agent_id: "a1" });
  });
});

const WALLET = {
  low_balance_threshold_inr: "200.00",
  low_balance_alert_chosen: false,
} as Wallet;

function AlertHarness({ wallet }: { wallet: Wallet }) {
  return <LowBalanceAlertPanel session={useClientSession()} wallet={wallet} />;
}

describe("the low-credit warning", () => {
  it("names Calevate's line and saves a new one as a decimal string", async () => {
    const { calls } = await renderClientPage(<AlertHarness wallet={WALLET} />, {
      "/v1/me": ME,
      "PUT /v1/billing/wallet/low-balance-alert": { threshold_inr: "750.00", chosen: true },
    });
    await screen.findByText(/Calevate's usual line/);
    const box = screen.getByLabelText("Warn me below (₹)");
    fireEvent.change(box, { target: { value: "750" } });
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Save" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({ threshold_inr: "750" });
  });

  it("refuses commas and treats 0 as switching the warning off", async () => {
    await renderClientPage(<AlertHarness wallet={WALLET} />, { "/v1/me": ME });
    const box = await screen.findByLabelText("Warn me below (₹)");
    fireEvent.change(box, { target: { value: "1,000" } });
    expect(screen.getByText(/Digits only/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(box, { target: { value: "0" } });
    expect(screen.getByText(/Only the warning that credit has run out/)).toBeTruthy();
  });

  it("returns a chosen line to Calevate's", async () => {
    const { calls } = await renderClientPage(
      <AlertHarness wallet={{ ...WALLET, low_balance_threshold_inr: "750.00", low_balance_alert_chosen: true }} />,
      {
        "/v1/me": ME,
        "PUT /v1/billing/wallet/low-balance-alert": { threshold_inr: "200.00", chosen: false },
      },
    );
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Use Calevate's" }));
    });
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(JSON.parse(calls.find((c) => c.method === "PUT")?.body ?? "{}")).toEqual({ threshold_inr: null });
  });
});
