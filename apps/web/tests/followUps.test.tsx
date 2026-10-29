import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FollowUpPage from "@/app/c/[slug]/follow-ups/[followUpId]/page";
import FollowUpsPage from "@/app/c/[slug]/follow-ups/page";
import { NEW_FOLLOW_UP_PROMPT } from "@/app/c/[slug]/follow-ups/Starters";
import { stepLines, triggerWords } from "@/app/c/[slug]/follow-ups/followUpCopy";
import type { BulkSelection } from "@/app/c/[slug]/leads/BulkActionBar";
import { StartFollowUp } from "@/app/c/[slug]/leads/StartFollowUp";
import { ToastProvider } from "@/components/arc/toast";
import type { Me } from "@/lib/api/client";
import type {
  FollowUpListOut,
  FollowUpOut,
  FollowUpResultsOut,
  FollowUpRunListOut,
  FollowUpStarterListOut,
  FollowUpStep,
} from "@/lib/api/followUps";
import type { WhatsAppTemplate } from "@/lib/api/whatsapp";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";

import { expectNoA11yViolations } from "./a11y";
import { problem, renderClientPage } from "./harness";

/**
 * Follow-ups (D-940): the list, the ready-made ones, one Follow-up's steps with their
 * small edits, publishing with problems, the leads in it and its results. Built against
 * the HTTP contract in docs/FOLLOW-UPS.md.
 */

function me(role: "owner" | "staff", permissions: string[]): Me {
  return {
    user_id: "u1",
    realm: "client",
    role,
    permissions,
    impersonating: false,
    withheld_acts: [],
    organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
  };
}

const OWNER = me("owner", ["leads:read", "leads:dispatch"]);
const STAFF = me("staff", ["leads:read", "leads:write"]);

const ID = "0192f0aa-7777-7000-8000-000000000001";
const PATH = `/v1/follow-ups/${ID}`;

const STEPS: FollowUpStep[] = [
  {
    id: "s1",
    kind: "call",
    summary: "Call with Riya, try 3 times, an hour apart",
    agent_id: "agent-1",
    wait_minutes: 0,
    retries: 2,
    retry_minutes: 60,
    exits: { answered: "s2", not_reached: "s5" },
  },
  { id: "s2", kind: "decide", summary: "How did the call go?", on: { interested: "s3", not_interested: null }, other: "s4" },
  { id: "s3", kind: "assign", summary: "Give them to Kiran", user_id: "u2", next: null },
  { id: "s4", kind: "wait", summary: "Wait 1 day", days: 1, next: null },
  { id: "s5", kind: "whatsapp", summary: "Send “we tried to reach you”", template_id: "t1", exits: { sent: null, not_sent: null } },
];

function followUp(overrides: Partial<FollowUpOut> = {}): FollowUpOut {
  return {
    id: ID,
    name: "Qualify new leads",
    status: "live",
    starter: "qualify_new_leads",
    trigger: { kind: "new_lead", source_ids: null },
    settings: { max_days: 14 },
    steps: STEPS,
    has_unpublished_changes: false,
    live_version: { number: 2, published_at: "2026-10-29T05:00:00Z" },
    counts: { running: 2, waiting: 3, done_30d: 10, goal_30d: 4 },
    problems: [],
    updated_at: "2026-10-30T05:00:00Z",
    ...overrides,
  };
}

const LIST: FollowUpListOut = {
  items: [
    {
      id: ID,
      name: "Qualify new leads",
      status: "live",
      starter: "qualify_new_leads",
      trigger: { kind: "new_lead", source_ids: null },
      has_unpublished_changes: false,
      counts: { running: 2, waiting: 3, done_30d: 10, goal_30d: 4 },
      updated_at: "2026-10-30T05:00:00Z",
    },
    {
      id: "0192f0aa-7777-7000-8000-000000000002",
      name: "Win back",
      status: "paused",
      starter: null,
      trigger: { kind: "manual" },
      has_unpublished_changes: true,
      counts: { running: 0, waiting: 0, done_30d: 1, goal_30d: 0 },
      updated_at: "2026-10-30T05:00:00Z",
    },
  ],
};

const STARTERS: FollowUpStarterListOut = {
  items: [
    { key: "qualify_new_leads", name: "Qualify new leads", trigger: { kind: "new_lead", source_ids: null }, steps: STEPS, settings: {} },
    {
      key: "missed_call_callback",
      name: "Call back missed calls",
      trigger: { kind: "call_ended", agent_ids: null, calls: "inbound", outcomes: ["missed"] },
      steps: [STEPS[3]],
      settings: {},
    },
  ],
};

const TEMPLATES: WhatsAppTemplate[] = [
  {
    id: "t1",
    account_id: "wa1",
    body: "We tried to reach you.",
    category: "UTILITY",
    category_changed_to: null,
    decided_at: "2026-10-01T05:00:00Z",
    language: "en",
    name: "tried_to_reach",
    origin: "client",
    purpose: null,
    rejection_code: null,
    status: "approved",
    submitted_at: "2026-10-01T04:00:00Z",
    variables: [],
  },
  {
    id: "t2",
    account_id: "wa1",
    body: "Your visit is tomorrow.",
    category: "UTILITY",
    category_changed_to: null,
    decided_at: "2026-10-01T05:00:00Z",
    language: "en",
    name: "visit_reminder",
    origin: "client",
    purpose: null,
    rejection_code: null,
    status: "approved",
    submitted_at: "2026-10-01T04:00:00Z",
    variables: [],
  },
];

function detail(routes: Record<string, unknown>, who: Me = OWNER) {
  return renderClientPage(
    <ToastProvider>
      <FollowUpPage params={Promise.resolve({ slug: "acme", followUpId: ID })} />
    </ToastProvider>,
    { "/v1/me": who, [PATH]: followUp(), ...routes },
  );
}

describe("the step tree", () => {
  it("indents a decision's branches under their outcome and keeps single exits flat", () => {
    const lines = stepLines(STEPS);
    expect(lines.map((line) => [line.type, line.type === "end" ? null : line.step.id, line.depth, line.branch])).toEqual([
      ["step", "s1", 0, null],
      ["step", "s2", 1, "Answered"],
      ["step", "s3", 2, "Interested"],
      ["end", null, 2, "Not interested"],
      ["step", "s4", 2, "Anything else"],
      ["step", "s5", 1, "Not reached"],
    ]);
  });

  it("never hides a step nothing points at, and points back to one already drawn", () => {
    const lines = stepLines([
      { id: "a", kind: "wait", summary: "Wait", minutes: 5, next: "b" },
      { id: "b", kind: "end", summary: "End" },
      { id: "c", kind: "call", summary: "Lonely call", exits: { answered: "b", not_reached: null } },
    ]);
    expect(lines.map((line) => `${line.type}:${line.type === "end" ? line.branch : line.step.id}`)).toEqual([
      "step:a",
      "step:b",
      "step:c",
      "goto:b",
      "end:Not reached",
    ]);
  });

  it("names what starts a Follow-up in plain words", () => {
    expect(triggerWords({ kind: "lead_date", field: "visit_date", offset_days: -1, at: "10:00" })).toBe(
      "1 day before the lead's visit date",
    );
    expect(triggerWords({ kind: "call_ended", agent_ids: null, calls: "inbound", outcomes: ["missed"] })).toBe(
      "An incoming call ends, missed",
    );
  });
});

describe("the Follow-ups list", () => {
  it("lists each one with what starts it, its state and its counts, and is accessible", async () => {
    const { container } = await renderClientPage(<FollowUpsPage />, {
      "/v1/me": OWNER,
      "/v1/follow-ups": LIST,
      "/v1/follow-ups/starters": STARTERS,
    });
    const table = await screen.findByRole("table", { name: "Your Follow-ups" });
    const first = within(table).getByRole("link", { name: "Qualify new leads" }).closest("tr");
    expect(first?.textContent).toContain("A new lead arrives");
    expect(first?.textContent).toContain("On");
    expect(first?.textContent).toContain("5");
    const second = within(table).getByRole("link", { name: "Win back" }).closest("tr");
    expect(second?.textContent).toContain("Paused");
    expect(second?.textContent).toContain("Changes not published");
    await expectNoA11yViolations(container, "follow-ups-list");
  });

  it("says so when there are none, and only from a list the server sent", async () => {
    await renderClientPage(<FollowUpsPage />, {
      "/v1/me": OWNER,
      "/v1/follow-ups": { items: [] },
      "/v1/follow-ups/starters": STARTERS,
    });
    expect(await screen.findByText("No Follow-ups yet.")).toBeTruthy();
  });

  it("does not claim none on a failed read", async () => {
    await renderClientPage(<FollowUpsPage />, {
      "/v1/me": OWNER,
      "/v1/follow-ups": problem(500, { title: "Down", detail: "We could not load that." }),
      "/v1/follow-ups/starters": STARTERS,
    });
    expect(await screen.findByText("We could not load that.")).toBeTruthy();
    expect(screen.queryByText("No Follow-ups yet.")).toBeNull();
  });

  it("opens Pip with the request written, and sends nothing", async () => {
    const asked: AssistantRequest[] = [];
    function Listener() {
      useAssistantRequests((request) => asked.push(request));
      return null;
    }
    render(<Listener />);
    const { calls } = await renderClientPage(<FollowUpsPage />, {
      "/v1/me": OWNER,
      "/v1/follow-ups": LIST,
      "/v1/follow-ups/starters": STARTERS,
    });
    fireEvent.click(await screen.findByRole("button", { name: "New Follow-up" }));
    expect(asked).toEqual([{ prompt: NEW_FOLLOW_UP_PROMPT }]);
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("offers the ready-made ones the account does not have, and makes a draft from one", async () => {
    const { calls } = await renderClientPage(<FollowUpsPage />, {
      "/v1/me": OWNER,
      "/v1/follow-ups": LIST,
      "/v1/follow-ups/starters": STARTERS,
      "POST /v1/follow-ups": followUp({ id: "new-1", status: "draft", live_version: null }),
    });
    const starter = await screen.findByRole("button", { name: "Use ready-made: Call back missed calls" });
    // Already made from this starter, so not offered twice.
    expect(screen.queryByRole("button", { name: "Use ready-made: Qualify new leads" })).toBeNull();
    await act(async () => {
      fireEvent.click(starter);
    });
    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    const sent = JSON.parse(calls.find((call) => call.method === "POST")?.body ?? "{}");
    expect(sent.starter).toBe("missed_call_callback");
    expect(sent.name).toBe("Call back missed calls");
    expect(sent.trigger.kind).toBe("call_ended");
  });

  it("shows a role without leads:dispatch no button that would be refused", async () => {
    const { calls } = await renderClientPage(<FollowUpsPage />, {
      "/v1/me": STAFF,
      "/v1/follow-ups": LIST,
    });
    expect(await screen.findByRole("table", { name: "Your Follow-ups" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "New Follow-up" })).toBeNull();
    expect(screen.queryByText("Ready-made")).toBeNull();
    expect(calls.some((call) => call.path === "/v1/follow-ups/starters")).toBe(false);
  });
});

describe("one Follow-up's steps", () => {
  it("draws branches under their outcome, one line per step, and is accessible", async () => {
    const { container } = await detail({});
    expect(await screen.findByRole("heading", { level: 1, name: "Qualify new leads" })).toBeTruthy();
    const steps = screen.getByRole("list", { name: "Steps" });
    expect(steps.textContent).toContain("Call with Riya, try 3 times, an hour apart");
    expect(steps.textContent).toContain("If “Interested”");
    expect(steps.textContent).toContain("If anything else");
    expect(steps.textContent).toContain("Stops here");
    // No Publish while nothing differs from what runs.
    expect(screen.queryByRole("button", { name: "Publish" })).toBeNull();
    await expectNoA11yViolations(container, "follow-up-detail");
  });

  it("changes a wait through PATCH with step_edits", async () => {
    const { calls } = await detail({
      [`PATCH ${PATH}`]: followUp({ has_unpublished_changes: true }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "More actions for Wait 1 day" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Change the wait" }));
    const dialog = await screen.findByRole("dialog", { name: "Change the wait" });
    fireEvent.change(within(dialog).getByLabelText("Wait"), { target: { value: "2" } });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    });
    await waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((call) => call.method === "PATCH")?.body ?? "{}")).toEqual({
      step_edits: [{ step_id: "s4", wait: { days: 2 } }],
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("changes a WhatsApp step's message to another approved one", async () => {
    const { calls } = await detail({
      "/v1/whatsapp/templates": TEMPLATES,
      [`PATCH ${PATH}`]: followUp({ has_unpublished_changes: true }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "More actions for Send “we tried to reach you”" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Change the message" }));
    const dialog = await screen.findByRole("dialog", { name: "Change the message" });
    fireEvent.change(await within(dialog).findByLabelText("Message"), { target: { value: "t2" } });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    });
    await waitFor(() => expect(calls.some((call) => call.method === "PATCH")).toBe(true));
    expect(JSON.parse(calls.find((call) => call.method === "PATCH")?.body ?? "{}")).toEqual({
      step_edits: [{ step_id: "s5", template_id: "t2" }],
    });
  });

  it("removes a step at once and sends the removal", async () => {
    const without = followUp({ steps: STEPS.filter((step) => step.id !== "s3"), has_unpublished_changes: true });
    let removed = false;
    const { calls } = await detail({
      [`GET ${PATH}`]: () => (removed ? without : followUp()),
      [`PATCH ${PATH}`]: () => {
        removed = true;
        return without;
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: "More actions for Give them to Kiran" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Remove this step" }));
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Remove it" }));
    });
    await waitFor(() => expect(screen.queryByText("Give them to Kiran")).toBeNull());
    expect(JSON.parse(calls.find((call) => call.method === "PATCH")?.body ?? "{}")).toEqual({
      step_edits: [{ step_id: "s3", remove: true }],
    });
  });

  it("answers a colleague's earlier change the way other screens do", async () => {
    await detail({
      [`PATCH ${PATH}`]: problem(409, {
        type: "https://calevate.tech/problems/follow_up_changed",
        title: "Changed",
        detail: "Someone changed this Follow-up.",
      }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "More actions for Wait 1 day" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Change the wait" }));
    const dialog = await screen.findByRole("dialog", { name: "Change the wait" });
    fireEvent.change(within(dialog).getByLabelText("Wait"), { target: { value: "3" } });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    });
    expect(await screen.findByText("A colleague changed this first")).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("publishing", () => {
  it("lists the problems as buttons that open their step, and sends the time it read", async () => {
    const draft = followUp({
      has_unpublished_changes: true,
      problems: [{ step_id: "s5", code: "template_not_approved", message: "This message is not approved yet." }],
    });
    const { calls } = await detail({
      [PATH]: draft,
      [`POST ${PATH}/publish`]: problem(422, {
        type: "https://calevate.tech/problems/follow_up_invalid",
        title: "Fix first",
        detail: "This Follow-up has problems.",
      }),
    });
    const fix = await screen.findByRole("button", { name: /This message is not approved yet\./ });
    fireEvent.click(fix);
    await waitFor(() =>
      expect(document.activeElement?.id).toBe("follow-up-step-s5"),
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    });
    await waitFor(() => expect(calls.some((call) => call.path === `${PATH}/publish`)).toBe(true));
    expect(JSON.parse(calls.find((call) => call.path === `${PATH}/publish`)?.body ?? "{}")).toEqual({
      expected_updated_at: draft.updated_at,
    });
    // The problems are already listed; the 422's sentence is not repeated under them.
    expect(screen.queryByText("This Follow-up has problems.")).toBeNull();
  });
});

describe("the status controls", () => {
  it("confirms turning off before stopping every lead in it", async () => {
    const { calls } = await detail({ [`POST ${PATH}/turn-off`]: followUp({ status: "off" }) });
    fireEvent.click(await screen.findByRole("button", { name: "Turn off" }));
    const dialog = await screen.findByRole("dialog", { name: "Turn off “Qualify new leads”?" });
    expect(dialog.textContent).toContain("Every lead in it now stops.");
    expect(calls.some((call) => call.method === "POST")).toBe(false);
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Turn it off" }));
    });
    await waitFor(() => expect(calls.some((call) => call.path === `${PATH}/turn-off`)).toBe(true));
  });

  it("shows a read-only role no button that would be refused", async () => {
    const { calls } = await detail({}, STAFF);
    expect(await screen.findByRole("heading", { level: 1, name: "Qualify new leads" })).toBeTruthy();
    for (const name of ["Pause", "Turn off", "Publish"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByRole("button", { name: /More actions for/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Ask Pip to change it/ })).toBeNull();
    expect(calls.some((call) => call.method !== "GET")).toBe(false);
  });
});

describe("the leads in it", () => {
  const RUNS: FollowUpRunListOut = {
    items: [
      {
        id: "r1",
        follow_up_id: ID,
        lead_id: "lead-1",
        lead_name: "Anil Kumar",
        status: "waiting",
        step_id: "s4",
        last_result: "branch:call_back",
        started_at: "2026-10-29T06:00:00Z",
        ended_at: null,
        end_reason: null,
        goal_reached: false,
      },
      {
        id: "r2",
        follow_up_id: ID,
        lead_id: "lead-2",
        lead_name: "Lakshmi",
        status: "done",
        step_id: "s3",
        last_result: "answered",
        started_at: "2026-10-28T06:00:00Z",
        ended_at: "2026-10-28T07:00:00Z",
        end_reason: "goal",
        goal_reached: true,
      },
    ],
    next_cursor: null,
  };

  it("lists each lead with where they are and stops one after confirming", async () => {
    const { calls } = await detail({
      [`${PATH}/runs`]: RUNS,
      [`POST ${PATH}/runs/r1/stop`]: { ...RUNS.items[0], status: "stopped" },
    });
    fireEvent.click(await screen.findByRole("tab", { name: "Leads" }));
    const table = await screen.findByRole("table", { name: "Leads in this Follow-up" });
    const anil = within(table).getByRole("link", { name: "Anil Kumar" });
    expect(anil.getAttribute("href")).toBe("/c/acme/leads/lead-1");
    expect(anil.closest("tr")?.textContent).toContain("Wait 1 day");
    expect(anil.closest("tr")?.textContent).toContain("Went: Call back");
    expect(within(table).getByRole("link", { name: "Lakshmi" }).closest("tr")?.textContent).toContain("Reached goal");
    // Only a lead still in it can be stopped.
    expect(within(table).queryByRole("button", { name: "Stop for Lakshmi" })).toBeNull();
    fireEvent.click(within(table).getByRole("button", { name: "Stop for Anil Kumar" }));
    const dialog = await screen.findByRole("dialog", { name: "Stop for Anil Kumar?" });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Stop it" }));
    });
    await waitFor(() => expect(calls.some((call) => call.path === `${PATH}/runs/r1/stop`)).toBe(true));
  });

  it("pages with the server's cursor", async () => {
    const { calls } = await detail({
      [`${PATH}/runs`]: { ...RUNS, next_cursor: "c2" },
      [`${PATH}/runs?cursor=c2`]: { items: [], next_cursor: null },
    });
    fireEvent.click(await screen.findByRole("tab", { name: "Leads" }));
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Show more" }));
    });
    await waitFor(() => expect(calls.some((call) => call.path === `${PATH}/runs?cursor=c2`)).toBe(true));
  });
});

describe("the results", () => {
  const RESULTS: FollowUpResultsOut = {
    days: 30,
    started: 40,
    finished: 31,
    goal_reached: 12,
    steps: [
      { step_id: "s1", reached: 40, exits: { answered: 28, not_reached: 12 } },
      { step_id: "s2", reached: 28, exits: { interested: 12, other: 16 } },
    ],
  };

  it("shows the totals and each step's count and exits in a table", async () => {
    await detail({ [`${PATH}/results`]: RESULTS });
    fireEvent.click(await screen.findByRole("tab", { name: "Results" }));
    expect(await screen.findByText("Started, 30 days")).toBeTruthy();
    const table = await screen.findByRole("table", { name: "Each step, last 30 days" });
    const call = within(table).getByText("Call with Riya, try 3 times, an hour apart").closest("tr");
    expect(call?.textContent).toContain("40");
    expect(call?.textContent).toContain("Answered 28");
    expect(call?.textContent).toContain("Not reached 12");
  });
});

describe("starting a Follow-up for picked leads", () => {
  const MANUAL_ID = "0192f0aa-7777-7000-8000-000000000009";
  const STARTABLE: FollowUpListOut = {
    items: [
      ...LIST.items,
      {
        id: MANUAL_ID,
        name: "Payment reminder",
        status: "live",
        starter: null,
        trigger: { kind: "manual" },
        has_unpublished_changes: false,
        counts: { running: 0, waiting: 0, done_30d: 0, goal_30d: 0 },
        updated_at: "2026-10-30T05:00:00Z",
      },
    ],
  };

  function view(selection: BulkSelection, routes: Record<string, unknown>) {
    return renderClientPage(
      <StartFollowUp
        session={{ orgSlug: "acme" }}
        slug="acme"
        href={(path) => path}
        selection={selection}
        lens={{ status: "hot" }}
        filteredTotal={3}
        canStart
        startReason={null}
        renderPlan={(planId) => <p>Plan {planId}</p>}
        onStarted={() => {}}
      />,
      { "/v1/follow-ups": STARTABLE, ...routes },
    );
  }

  it("offers only Follow-ups that are on and started by hand, and sends the ticked leads", async () => {
    const { container, calls } = await view(
      { ids: ["lead-1", "lead-2"], wholeQuery: false },
      { [`POST /v1/follow-ups/${MANUAL_ID}/start`]: { started: 2, skipped: 0, plan_id: null } },
    );
    const select = await screen.findByLabelText("Start a Follow-up");
    expect(Array.from((select as HTMLSelectElement).options).map((option) => option.text)).toEqual([
      "Payment reminder",
    ]);
    await expectNoA11yViolations(container, "start-follow-up");
    fireEvent.click(screen.getByRole("button", { name: "Start for 2 leads" }));
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Start for 2" }));
    });
    await waitFor(() => expect(calls.some((call) => call.method === "POST")).toBe(true));
    expect(JSON.parse(calls.find((call) => call.method === "POST")?.body ?? "{}")).toEqual({
      lead_ids: ["lead-1", "lead-2"],
    });
    expect(await screen.findByText(/Started “Payment reminder” for 2/)).toBeTruthy();
  });

  it("sends the table's lens with the confirmed count for every matching lead", async () => {
    const { calls } = await view(
      { ids: [], wholeQuery: true },
      { [`POST /v1/follow-ups/${MANUAL_ID}/start`]: { started: 0, skipped: 0, plan_id: "plan-9" } },
    );
    fireEvent.click(await screen.findByRole("button", { name: "Start for 3 leads" }));
    await act(async () => {
      fireEvent.click(await screen.findByRole("button", { name: "Start for 3" }));
    });
    expect(await screen.findByText("Plan plan-9")).toBeTruthy();
    expect(JSON.parse(calls.find((call) => call.method === "POST")?.body ?? "{}")).toEqual({
      lens: { status: "hot" },
      expected_count: 3,
    });
  });
});
