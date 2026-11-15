import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import HeldAccountsPage from "@/app/admin/holds/page";
import NewClientPage from "@/app/admin/new/page";
import { PipProposal } from "@/app/c/[slug]/agents/[agentId]/script/PipProposal";
import { TaughtRules } from "@/app/c/[slug]/agents/[agentId]/script/TaughtRules";
import { END, sectionsOf } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import { Actions } from "@/app/c/[slug]/agents/actions/Actions";
import { SpendPanel } from "@/app/c/[slug]/billing/SpendPanel";
import CallbacksPage from "@/app/c/[slug]/callbacks/page";
import DataRightsPage from "@/app/c/[slug]/data-rights/page";
import DoNotCallPage from "@/app/c/[slug]/do-not-call/page";
import IntegrationsPage from "@/app/c/[slug]/integrations/page";
import { ToastProvider } from "@/components/arc/toast";
import type { ActionTool } from "@/lib/api/actions";
import type { ScheduledCallback } from "@/lib/api/callbacks";
import type { Me, Session } from "@/lib/api/client";
import { DNC_LIST_LIMIT } from "@/lib/api/dnc";
import { HOLDS_PATH } from "@/lib/api/holds";
import { OUTBOUND_CONSENT_POLICY_PATH } from "@/lib/api/outboundConsent";
import { EMPTY_SCRIPT, type CallScript, type ScriptProposal } from "@/lib/api/script";
import { useClientSession } from "@/lib/api/session";

import { WHATSAPP_OFF_ROUTES } from "./fixtures/whatsapp";
import { problem, renderAdminPage, renderClientPage, stillLoading, type Routes } from "./harness";

/** Deep audit 10 Nov 2026, D1 (the web app). Each block fails on the source before its fix. */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["calls:read", "calls:read_raw", "leads:read", "org:read", "org:manage"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

describe("D1-01 the rights desk answers an erasure request when the erasure completes", () => {
  const DESK = "/v1/compliance/rights-requests?limit=100";
  const REGISTER = "/v1/compliance/deletion-requests?limit=100";
  const REF = "b1946ac92492d2347c6235b4d2611184";
  const ROW = {
    id: "r1",
    kind: "erasure",
    channel: "phone",
    status: "open",
    received_at: "2026-11-10T04:00:00Z",
    due_at: "2027-02-08T04:00:00Z",
    days_left: 90,
    due_soon: false,
    overdue: false,
    subject_ref: REF,
    outcome: null,
    closed_at: null,
    deletion_request_id: null,
  };
  const deskOf = (items: unknown[]) => ({
    items,
    open: 1,
    due_soon: 0,
    overdue: 0,
    response_days: 90,
    reminder_days: 14,
  });
  const pending = {
    request_id: "0192f0aa-4444-7000-8000-0000000000ab",
    subject_ref: REF,
    status: "pending",
    requested_at: "2026-11-10T05:00:00Z",
    completed_at: null,
    has_certificate: false,
  };

  function rights(routes: Routes) {
    return renderClientPage(
      <ToastProvider>
        <DataRightsPage />
      </ToastProvider>,
      { "/v1/me": OWNER, ...routes },
    );
  }

  it("does not mark the row answered when the erasure is only filed", async () => {
    const view = await rights({
      [DESK]: deskOf([ROW]),
      [REGISTER]: [],
      "POST /v1/compliance/deletion-requests": {
        request_id: pending.request_id,
        subject_ref: REF,
        status: "pending",
        requested_at: pending.requested_at,
        completed_at: null,
        proof: null,
        already_open: false,
      },
      [`/v1/compliance/deletion-requests/${pending.request_id}`]: { ...pending, proof: null },
    });
    const row = (await screen.findByText("Erase their data", { selector: "span" })).closest("li")!;
    fireEvent.click(within(row).getByRole("button", { name: "Erase their data" }));
    const drawer = await screen.findByRole("dialog", { name: "Erase someone's data" });
    fireEvent.change(within(drawer).getByLabelText(/Number to erase permanently/), {
      target: { value: "+919876543210" },
    });
    fireEvent.change(within(drawer).getByLabelText(/Type ERASE to confirm/), { target: { value: "ERASE" } });
    fireEvent.click(within(drawer).getByRole("button", { name: /Erase this person's data/ }));
    await waitFor(() =>
      expect(view.calls.some((c) => c.method === "POST" && c.path === "/v1/compliance/deletion-requests")).toBe(true),
    );
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Erase someone's data" })).toBeNull());
    expect(view.calls.some((c) => c.path.endsWith("/close"))).toBe(false);
  });

  it("says the row is being erased, and offers nothing to press", async () => {
    await rights({ [DESK]: deskOf([ROW]), [REGISTER]: [pending] });
    expect(await screen.findByText("Being erased. This is marked answered when it finishes.")).toBeTruthy();
    const row = screen.getByText("Being erased. This is marked answered when it finishes.").closest("li")!;
    expect(within(row).queryByRole("button")).toBeNull();
  });
});

describe("D1-02 a taught rule added as a step is reached, and the limit is the account's", () => {
  const RULES = "/v1/agents/a1/script/proposed-rules";
  const RULE = {
    id: "rule1",
    agent_id: "a1",
    text: "Never promise Sunday delivery",
    status: "pending",
    created_at: "2026-11-10T04:00:00Z",
  };
  const step = (id: string, otherwise = "") => ({
    id,
    name: id,
    mode: "guide" as const,
    instruction: "Talk.",
    sounds_like: "",
    branches: [],
    otherwise,
    collect: [],
    procedure: [],
    position: null,
  });
  const scriptOf = (stages: ReturnType<typeof step>[]): CallScript => ({
    ...EMPTY_SCRIPT,
    schema_version: 2,
    stages,
  });

  async function taught(script: CallScript, maxSections = 12) {
    const changes: CallScript[] = [];
    await renderClientPage(
      <ToastProvider>
        <TaughtRules
          agentId="a1"
          script={script}
          maxSections={maxSections}
          canWrite
          onChange={(next) => changes.push(next)}
        />
      </ToastProvider>,
      { "/v1/me": OWNER, [RULES]: [RULE], [`POST ${RULES}/rule1`]: { ...RULE, status: "applied" } },
    );
    return changes;
  }

  it("hands the last step's end of call to the new step, so the call reaches it", async () => {
    const changes = await taught(scriptOf([step("hello"), step("bye", END)]));
    fireEvent.click(await screen.findByRole("button", { name: "Add as a step" }));
    // The draft takes the step once the rule is marked used.
    await waitFor(() => expect(changes).toHaveLength(1));
    const stages = sectionsOf(changes[0]!);
    expect(stages.map((s) => s.otherwise)).toEqual(["", "", END]);
    expect(stages[2]!.instruction).toBe(RULE.text);
  });

  it("follows the account's step limit rather than a number of its own", async () => {
    await taught(scriptOf([step("one"), step("two")]), 2);
    const add = (await screen.findByRole("button", { name: "Add as a step" })) as HTMLButtonElement;
    expect(add.disabled).toBe(true);
  });
});

describe("D1-03 a suggestion's Add and Discard wait for each other", () => {
  const SCRIPT: CallScript = { ...EMPTY_SCRIPT, opening_line: "Namaskaram andi." };
  const PROPOSAL: ScriptProposal = {
    id: "p1",
    mode: "change",
    documents: [],
    status: "ready",
    request: "Make the opening line warmer",
    base_script: SCRIPT,
    script: { ...SCRIPT, opening_line: "Namaskaram andi, thanks for calling!" },
    unplaced: [],
    left_out: [],
    disclosure: null,
    note: null,
    requested_at: "2026-10-19T10:00:00+00:00",
  };

  it("says Adding… and holds Discard while the suggestion is being cleared", async () => {
    await renderClientPage(
      <PipProposal agentId="agent-1" script={SCRIPT} canWrite onKeep={() => undefined} />,
      {
        "/v1/me": OWNER,
        "/v1/agents/agent-1/script/proposal": { proposal: PROPOSAL },
        "DELETE /v1/agents/agent-1/script/proposal/p1": stillLoading(),
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Add it to my draft" }));
    const adding = (await screen.findByRole("button", { name: "Adding…" })) as HTMLButtonElement;
    expect(adding.disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Discard" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("D1-04 a call-back's due mark counts down on an open screen", () => {
  afterEach(() => vi.useRealTimers());

  it("turns In 2 min into Overdue without a reload, and re-reads the list meanwhile", async () => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2026-11-10T10:00:00Z"));
    const row: ScheduledCallback = {
      id: "0192f0aa-3333-7000-8000-000000000001",
      agent_id: "0192f0aa-2222-7000-8000-000000000002",
      lead_id: null,
      phone_e164: "+91******3211",
      requested_at: "2026-11-10T10:01:30Z",
      status: "scheduled",
      attempts: 0,
      explanation: "Booked for the time the caller asked for.",
      last_call_id: null,
      settled_at: null,
      held: false,
      note: null,
      follow_up: null,
    };
    const list = "/v1/callbacks?limit=200&open_only=false";
    const view = await renderClientPage(<CallbacksPage />, {
      "/v1/me": { ...OWNER, permissions: ["leads:read", "leads:dispatch"] },
      [list]: [row],
    });
    expect((await screen.findAllByText("In 2 min")).length).toBeGreaterThan(0);
    const reads = () => view.calls.filter((c) => c.url.includes("/v1/callbacks?")).length;
    const before = reads();
    act(() => {
      vi.advanceTimersByTime(3 * 60_000);
    });
    await waitFor(() => expect(screen.getAllByText("Overdue").length).toBeGreaterThan(0));
    expect(screen.queryByText("In 2 min")).toBeNull();
    await waitFor(() => expect(reads()).toBeGreaterThan(before));
  });
});

describe("D1-05/06 the new-client success box says the status in words and the next steps D-692 makes true", () => {
  it("reads Onboarding, and does not send the operator to register with DLT by hand", async () => {
    const { container } = renderAdminPage(<NewClientPage />, {
      "/v1/admin/tenants": {
        id: "0192f0aa-7777-7000-8000-000000000001",
        slug: "sunrise-clinic",
        status: "onboarding",
        vertical_template: "clinic",
        invitation_id: "0192f0aa-7777-7000-8000-0000000000e1",
      },
      "/v1/admin/me": {
        realm: "admin",
        user_id: "0192f0aa-7777-7000-8000-0000000000f2",
        role: "operator",
        permissions: ["org:read", "agents:read", "agents:write", "admin:tenants"],
      },
      "/v1/admin/onboarding/unfinished": [],
    });
    fireEvent.change(screen.getByPlaceholderText("Sri Traders"), { target: { value: "Sunrise Clinic" } });
    fireEvent.click(screen.getByRole("radio", { name: /^Clinic/ }));
    fireEvent.change(screen.getByPlaceholderText("owner@business.com"), {
      target: { value: "owner@sunrise.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create and invite" }));
    await screen.findByText("Account created and owner invited");
    const text = container.textContent ?? "";
    expect(text).toContain("status Onboarding.");
    expect(text).not.toContain("status onboarding");
    expect(text).not.toMatch(/registering with/);
    expect(text).toContain("no-cold-calls pledge");
  });
});

describe("D1-07 a failed holds queue says so once", () => {
  it("draws one alert box, with Try again, for one failure", async () => {
    const { container } = renderAdminPage(<HeldAccountsPage />, {
      [HOLDS_PATH]: problem(503, { title: "Unavailable", status: 503, retryable: true }),
    });
    await screen.findByText(/could not be read/);
    expect(container.querySelectorAll("[data-notice]").length).toBe(1);
    expect(screen.getByRole("button", { name: /try again/i })).toBeTruthy();
  });
});

describe("D1-08 the month's spend tiles name the month in words", () => {
  it("says November 2026, not 2026-11", async () => {
    const { container } = await renderClientPage(
      <SpendPanel session={{ orgSlug: "acme" } as Session} slug="acme" month="2026-11" />,
      {
        "/v1/me": OWNER,
        "/v1/billing/spend?month=2026-11": {
          month: "2026-11",
          charge_basis: "allocated",
          calls: 2,
          minutes_used: "18.5000",
          retainer_inr: null,
          period_charge_inr: "1200.00",
          itemised_charge_inr: "1200.00",
          itemisation_residual_inr: "0.00",
          residual_reason: null,
          by_agent: [],
          top_calls: [],
          top_calls_truncated: false,
        },
      },
    );
    await screen.findByText("Calls · November 2026");
    expect(container.textContent).not.toContain("2026-11");
  });
});

describe("D1-09 a view-as operator is not offered switching an action on", () => {
  const VIEW_AS: Me = {
    user_id: "op1",
    realm: "client",
    role: "owner",
    permissions: ["org:read", "org:manage"],
    impersonating: true,
    withheld_acts: ["actions.switch_on", "actions.test_unapproved"],
    organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
  };
  const OFF: ActionTool = {
    id: "tool-1",
    agent_id: "agent-1",
    kind: "custom_api",
    name: "Look up an order",
    description: "Finds the caller's order by its number.",
    trigger: "during_call",
    enabled: false,
    params: [],
    config: {},
    credential_id: null,
    pre_call_message: null,
    provider: null,
  };

  function Panel() {
    const session = useClientSession();
    return <Actions agentId="agent-1" session={session} />;
  }

  it("holds the switches that would turn something on, and says why", async () => {
    await renderClientPage(<Panel />, {
      "/v1/me": VIEW_AS,
      "/v1/agents/agent-1/actions": { api_actions_enabled: false, calendar_available: false, tools: [OFF] },
      "/v1/integrations/credentials": [],
    });
    const master = await screen.findByRole("switch", { name: /use actions on calls/i });
    await waitFor(() => expect(master.matches(":disabled")).toBe(true));
    expect(screen.getByRole("switch", { name: "Look up an order" }).matches(":disabled")).toBe(true);
    expect(screen.getByText(/cannot switch an action on from a view-as session/)).toBeTruthy();
  });

  it("still lets the operator switch one off", async () => {
    await renderClientPage(<Panel />, {
      "/v1/me": VIEW_AS,
      "/v1/agents/agent-1/actions": {
        api_actions_enabled: true,
        calendar_available: false,
        tools: [{ ...OFF, enabled: true }],
      },
      "/v1/integrations/credentials": [],
    });
    const row = await screen.findByRole("switch", { name: "Look up an order" });
    await waitFor(() => expect(row.matches(":disabled")).toBe(false));
  });
});

describe("D1-09 a view-as operator is not offered the owner's acts on do-not-call and integrations", () => {
  const OPERATOR: Me = {
    user_id: "op1",
    realm: "client",
    role: "owner",
    permissions: ["org:read", "org:manage", "leads:read", "leads:dispatch"],
    impersonating: true,
    withheld_acts: ["compliance.dnc_optout_restore", "integrations.connect"],
    organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
  };

  it("does not offer Restore on a person's opt-out", async () => {
    await renderClientPage(<DoNotCallPage />, {
      "/v1/me": OPERATOR,
      [OUTBOUND_CONSENT_POLICY_PATH]: { outbound_requires_consent: false },
      [`/v1/dnc?limit=${DNC_LIST_LIMIT}`]: [
        {
          id: "0192f0aa-4444-7000-8000-0000000000aa",
          phone_e164: "+919876543210",
          added_at: "2026-07-01T10:00:00Z",
          removable: false,
          restorable: true,
          scope: "tenant",
          source: "call_optout",
        },
      ],
    });
    expect(await screen.findByText("opt-out — an owner can restore it")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Restore / })).toBeNull();
  });

  it("lets the operator check an account but not add or remove one", async () => {
    await renderClientPage(<IntegrationsPage />, {
      "/v1/me": OPERATOR,
      "/v1/integrations/credentials": [
        {
          id: "cred-1",
          kind: "aisensy",
          label: "AiSensy key",
          last_four: "1234",
          version: 1,
          non_secret: {},
          created_at: "2026-08-01T10:00:00Z",
          updated_at: "2026-08-01T10:00:00Z",
        },
      ],
      ...WHATSAPP_OFF_ROUTES,
      "/v1/integrations/connections/status": {
        google_calendar: false,
        zoho_crm: false,
        hubspot: false,
        sheets_share_with: null,
      },
      "/v1/integrations/endpoints": [],
      "/v1/integrations/events": { events: ["lead.created"], sheets_delivery_available: false },
      "/v1/integrations/deliveries": [],
    });
    const add = (await screen.findByRole("button", { name: "Add a key" })) as HTMLButtonElement;
    await waitFor(() => expect(add.disabled).toBe(true));
    expect((screen.getByRole("button", { name: "Disconnect AiSensy key" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Check AiSensy key" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText(/cannot connect or remove an account from a view-as session/)).toBeTruthy();
  });
});
