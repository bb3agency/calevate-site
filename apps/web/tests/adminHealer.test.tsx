import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import OpsHealerPage from "@/app/admin/ops/healer/page";
import {
  HEALER_LIST_LIMIT,
  type HealerAction,
  type HealerIncident,
  type HealerOverview,
} from "@/lib/api/opsHealer";
import openapi from "@/lib/api/openapi.json";
import { useAssistantRequests, type AssistantRequest } from "@/lib/copilot/launcher";

import { renderAdminRoute } from "./adminRoute";
import { stillLoading } from "./harness";

/**
 * The auto-healer screen in plain words (founder, 11 Oct 2026: the rows read
 * "money review · engine_charge_mismatch … 0 attempts · last: escalated").
 *
 * The words come from the API's one catalogue (`apps/api/healer/wording.py`, whose
 * coverage of every openable code `tests/healer_wording_test.py` enforces). These pin the
 * screen's half: it renders those words rather than codes, keeps the code reachable for
 * log searches, and keeps the step-up confirmation on "Mark as handled".
 */

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-8888-7000-8000-0000000000a2",
  role: "operator",
  permissions: ["ops:manage"],
};

const MONEY = "019f1000-0000-7000-8000-0000000000m1";
const OUTBOX = "019f1000-0000-7000-8000-0000000000o1";

function incident(over: Partial<HealerIncident>): HealerIncident {
  return {
    id: MONEY,
    ref: "000000m1",
    playbook: "money_review",
    trigger_code: "engine_charge_mismatch",
    scope: "platform",
    tenant_id: null,
    agent_id: null,
    state: "escalated",
    attempts: 0,
    next_attempt_at: null,
    component: null,
    public: false,
    public_title: null,
    last_outcome: "escalated",
    opened_at: "2026-10-10T12:47:00Z",
    mitigated_at: null,
    escalated_at: "2026-10-10T12:48:00Z",
    resolved_at: null,
    kind: {
      code: "engine_charge_mismatch",
      title: "Call charges don't match our records",
      meaning: "For some calls, what ThinnestAI charged differs from what we metered.",
      next_step: "Compare the named calls in ThinnestAI's Usage → Calls with ours.",
    },
    group: "Money: needs your review",
    automatic: false,
    progress: "Not fixable automatically, handed to you",
    finding:
      "3 of 14 charged calls differ since 09 Oct 19:12 IST. premium: we hold ₹2.50/min, charges imply ₹2.75/min. One rate explains all. Alarm open.",
    ...over,
  };
}

const INCIDENTS: HealerIncident[] = [
  incident({}),
  incident({
    id: OUTBOX,
    ref: "000000o1",
    finding: null,
    playbook: "outbox_replay",
    trigger_code: "outbox_dead_letter",
    state: "resolved",
    attempts: 3,
    last_outcome: "verified",
    resolved_at: "2026-10-10T14:00:00Z",
    kind: {
      code: "outbox_dead_letter",
      title: "Background jobs failed after every retry",
      meaning: "Some queued jobs used up all their attempts.",
      next_step: "Nothing unless it is handed to you.",
    },
    group: "Failed background jobs",
    automatic: true,
    progress: "Fixed automatically after 3 tries",
    postmortem: "Background jobs failed after every retry.\nTimeline:\n- 10 Oct 19:30 IST act ok",
  }),
  incident({
    id: "019f1000-0000-7000-8000-0000000000w1",
    ref: "000000w1",
    finding: null,
    playbook: "engine_webhooks",
    trigger_code: "engine_webhook_sweep_incomplete",
    state: "mitigated",
    attempts: 1,
    last_outcome: "acted",
    kind: {
      code: "engine_webhook_sweep_incomplete",
      title: "Some agents' call-update links could not be checked",
      meaning: "The check could not reach some agents' links.",
      next_step: "Nothing at first.",
    },
    group: "Call updates from the voice platform",
    automatic: true,
    progress: "Automatic fix tried (1 try); checking that it worked",
  }),
];

const OVERVIEW: HealerOverview = {
  enabled: true,
  paused: ["outbox_replay", "not_a_playbook"],
  unknown_paused: ["not_a_playbook"],
  shadow: [],
  playbooks: [
    {
      key: "outbox_replay",
      title: "Failed background jobs",
      triggers: ["outbox_dead_letter"],
      woken_by: [INCIDENTS[1]!.kind],
      action: "Put each job's dead letters back on the queue.",
      verify: "That job's dead-letter count is back to zero.",
      undo: "None needed.",
      max_attempts: 2,
      cooldown_s: 1800,
      blast_radius: "platform",
      job: null,
      automatic: true,
      pausable: true,
      paused: true,
    },
    {
      key: "money_review",
      title: "Money: needs your review",
      triggers: ["engine_charge_mismatch"],
      woken_by: [INCIDENTS[0]!.kind],
      action: "Open an incident and page. The healer never moves money.",
      verify: "A person resolves the incident.",
      undo: "Not applicable.",
      max_attempts: 0,
      cooldown_s: 86400,
      blast_radius: "platform",
      job: null,
      automatic: false,
      pausable: true,
      paused: false,
    },
  ],
  paging: {
    whatsapp_available: true,
    whatsapp_reason: null,
    whatsapp_enabled: true,
    founder_number_set: true,
    founder_number_from_console: true,
    email_set: true,
  },
  open_incidents: 2,
  escalated_incidents: 1,
  metrics: { days: 7, actions: 4, failed: 1, undone: 0, shadow: 0, recurrences: 1 },
};

const ACTIONS: HealerAction[] = [
  {
    id: "019f1000-0000-7000-8000-0000000000l1",
    at: "2026-10-10T13:00:00Z",
    incident_id: MONEY,
    playbook: "money_review",
    step: "escalate",
    outcome: "ok",
    attempt: 0,
    tenant_id: null,
    agent_id: null,
    alarm_code: "engine_charge_mismatch",
    detail: null,
    actor_type: "healer",
  },
];

function routes(extra: Record<string, unknown> = {}) {
  return {
    [ADMIN_ME_PATH]: ME,
    "/v1/ops/healer": OVERVIEW,
    "/v1/ops/healer/incidents?days=7&limit=51": { items: INCIDENTS },
    "/v1/ops/healer/actions?limit=51": { items: ACTIONS },
    ...extra,
  };
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

function row(title: string): HTMLElement {
  const li = screen.getByText(title, { selector: "p" }).closest("li");
  if (!li) throw new Error(`no row for ${title}`);
  return li;
}

describe("auto-healer screen in plain words", () => {
  it("names each problem in words and says where it stands", async () => {
    await renderAdminRoute(<OpsHealerPage />, routes());
    await settle();
    const money = row("Call charges don't match our records");
    expect(money.textContent).toContain("Money: needs your review");
    expect(money.textContent).toContain("Not fixable automatically, handed to you");
    expect(money.textContent).toContain("Needs you");
    expect(money.textContent).toContain("What to do:");
    expect(row("Background jobs failed after every retry").textContent).toContain(
      "Fixed automatically after 3 tries",
    );
  });

  it("says when the problems and the actions are more than it shows", async () => {
    const problems = Array.from({ length: HEALER_LIST_LIMIT + 1 }, (_, n) =>
      incident({ id: `019f1000-0000-7000-8000-${String(n).padStart(12, "0")}`, ref: `r${n}` }),
    );
    const actions = Array.from({ length: HEALER_LIST_LIMIT + 1 }, (_, n) => ({
      ...ACTIONS[0]!,
      id: `019f2000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    }));
    await renderAdminRoute(
      <OpsHealerPage />,
      routes({
        "/v1/ops/healer/incidents?days=7&limit=51": { items: problems },
        "/v1/ops/healer/actions?limit=51": { items: actions },
      }),
    );
    await settle();
    expect(screen.getByText(/most recent problems of the last 7 days; there are more/)).toBeTruthy();
    expect(screen.getByText(/older ones are not listed/)).toBeTruthy();
  });

  it("says nothing about more when the lists are whole", async () => {
    await renderAdminRoute(<OpsHealerPage />, routes());
    await settle();
    expect(screen.queryByText(/there are more/)).toBeNull();
    expect(screen.queryByText(/older ones are not listed/)).toBeNull();
  });

  it("keeps codes off the visible rows", async () => {
    const { container } = await renderAdminRoute(<OpsHealerPage />, routes());
    await settle();
    const text = container.textContent ?? "";
    for (const leaked of [
      "engine_charge_mismatch",
      "money review",
      "0 attempts",
      "last: escalated",
      "Run next step now",
      "Resolve",
    ]) {
      expect(text).not.toContain(leaked);
    }
  });

  it("keeps the raw code reachable behind the ⓘ for log searches", async () => {
    await renderAdminRoute(<OpsHealerPage />, routes());
    await settle();
    const money = row("Call charges don't match our records");
    fireEvent.click(
      within(money).getByRole("button", { name: "About Call charges don't match our records" }),
    );
    expect(await screen.findByText("engine_charge_mismatch")).toBeTruthy();
  });

  it("labels the counters for what they count", async () => {
    await renderAdminRoute(<OpsHealerPage />, routes());
    await settle();
    expect(screen.getByText("Open problems")).toBeTruthy();
    expect(screen.getByText("Waiting for you")).toBeTruthy();
    // Counted from the playbooks actually switched off, not the raw list (which names a
    // playbook that does not exist).
    const off = screen.getByText("Repairs switched off").parentElement!;
    expect(off.textContent).toContain("1");
    expect(off.textContent).not.toContain("2");
  });

  it("shows the healer's own track record and a closed problem's summary", async () => {
    await renderAdminRoute(<OpsHealerPage />, routes());
    await settle();
    const record = screen.getByText("Repairs, last 7 days").parentElement!;
    expect(record.textContent).toContain("1 failed, 0 undone, 0 dry run.");
    expect(screen.getByText("Problems that came back")).toBeTruthy();
    const closed = row("Background jobs failed after every retry");
    expect(within(closed).getByText("What happened")).toBeTruthy();
    expect(closed.textContent).toContain("Timeline:");
  });

  it("offers a re-check only where the healer acts itself", async () => {
    await renderAdminRoute(<OpsHealerPage />, routes());
    await settle();
    const money = row("Call charges don't match our records");
    expect(within(money).queryByRole("button", { name: "Check again now" })).toBeNull();
    expect(within(money).getByRole("button", { name: "Mark as handled" })).toBeTruthy();
    const webhooks = row("Some agents' call-update links could not be checked");
    expect(within(webhooks).getByRole("button", { name: "Check again now" })).toBeTruthy();
    // A closed problem has nothing to press.
    const closed = row("Background jobs failed after every retry");
    expect(within(closed).queryByRole("button", { name: "Mark as handled" })).toBeNull();
  });

  it("asks before marking handled and sends the step-up words", async () => {
    const { calls } = await renderAdminRoute(
      <OpsHealerPage />,
      routes({
        [`POST /v1/ops/healer/incidents/${MONEY}/resolve`]: {
          ...INCIDENTS[0],
          state: "resolved",
        },
      }),
    );
    await settle();
    fireEvent.click(
      within(row("Call charges don't match our records")).getByRole("button", {
        name: "Mark as handled",
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Any line it is holding is given back");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Mark as handled" }));
    await settle();
    const post = calls.find((c) => c.method === "POST" && c.path.endsWith("/resolve"));
    expect(post?.headers["X-Confirm-Action"]).toBe(`resolve_heal_incident:${MONEY}`);
  });

  it("holds every other re-check, with its reason, while one is out", async () => {
    const webhooks = INCIDENTS[2]!;
    const second = incident({
      ...webhooks,
      id: "019f1000-0000-7000-8000-0000000000w2",
      ref: "000000w2",
      kind: { ...webhooks.kind, title: "Some numbers could not be checked" },
    });
    const { calls } = await renderAdminRoute(
      <OpsHealerPage />,
      routes({
        "/v1/ops/healer/incidents?days=7&limit=51": { items: [...INCIDENTS, second] },
        [`POST /v1/ops/healer/incidents/${webhooks.id}/retry`]: stillLoading(),
      }),
    );
    await settle();
    const first = within(row(webhooks.kind.title)).getByRole("button", { name: "Check again now" });
    fireEvent.click(first);
    await settle();
    expect(first.getAttribute("aria-busy")).toBe("true");
    const other = within(row("Some numbers could not be checked")).getByRole("button", { name: "Check again now" });
    expect(other.getAttribute("aria-disabled")).toBe("true");
    expect(row("Some numbers could not be checked").textContent).toContain("Waiting for the other check to start.");
    fireEvent.click(other);
    await settle();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
  });

  it("hands Pip each open problem by its ref, prefilled and not sent", async () => {
    const asked: AssistantRequest[] = [];
    function Listener() {
      useAssistantRequests((request) => asked.push(request));
      return null;
    }
    render(<Listener />);
    const { calls } = await renderAdminRoute(<OpsHealerPage />, routes());
    await settle();
    const money = row("Call charges don't match our records");
    fireEvent.click(within(money).getByRole("button", { name: /^Ask Pip to fix this: / }));
    expect(asked).toHaveLength(1);
    expect(asked[0]?.prompt).toContain("(ref 000000m1)");
    expect(asked[0]?.prompt).toContain("Call charges don't match our records");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    const closed = row("Background jobs failed after every retry");
    expect(within(closed).queryByRole("button", { name: /Ask Pip/ })).toBeNull();
  });

  it("shows Pip's finding on an open money problem as a quiet notice", async () => {
    await renderAdminRoute(<OpsHealerPage />, routes());
    await settle();
    const money = row("Call charges don't match our records");
    const finding = within(money).getByText(/charges imply ₹2\.75\/min/);
    expect(finding.closest("[data-notice='neutral']")).toBeTruthy();
    expect(money.textContent).toContain("Pip found:");
  });

  it("presents the healer as Pip's work", async () => {
    await renderAdminRoute(<OpsHealerPage />, routes());
    await settle();
    expect(screen.getByText(/Pip watches the platform/)).toBeTruthy();
    expect(screen.getByText("What Pip did")).toBeTruthy();
  });

  it("the API contract carries the plain words on every incident", () => {
    const schemas = (openapi as { components: { schemas: Record<string, { required?: string[] }> } })
      .components.schemas;
    for (const field of ["ref", "kind", "group", "automatic", "progress"]) {
      expect(schemas.IncidentOut?.required).toContain(field);
    }
    expect(schemas.IncidentKindOut?.required).toEqual(
      expect.arrayContaining(["code", "title", "meaning", "next_step"]),
    );
  });
});

/**
 * Journey audit E5-03: `PUT /v1/ops/healer/incidents/{id}/status` and its hook existed, but no
 * control called it, so an open problem's public notice (the outage playbook's automatic
 * one, or one posted by hand) could not be corrected or taken down until the problem closed.
 */
describe("an open problem's status page notice", () => {
  const OUTAGE = "019f1000-0000-7000-8000-0000000000p1";
  const outage = incident({
    id: OUTAGE,
    ref: "000000p1",
    finding: null,
    playbook: "engine_outage",
    trigger_code: "engine_platform_outage",
    state: "mitigated",
    component: "calls",
    public: true,
    public_title: "Calls are not connecting for some customers",
    kind: {
      code: "engine_platform_outage",
      title: "Calls are failing for many clients",
      meaning: "The voice platform is failing.",
      next_step: "Confirm with the platform's status page.",
    },
    group: "Voice platform outage",
    automatic: true,
    progress: "Lines held; waiting for the platform",
  });
  const withOutage = (extra: Record<string, unknown> = {}) =>
    routes({
      "/v1/ops/healer/incidents?days=7&limit=51": { items: [outage, ...INCIDENTS] },
      ...extra,
    });

  it("shows what the public reads and takes it off with the step-up words", async () => {
    const { calls } = await renderAdminRoute(
      <OpsHealerPage />,
      withOutage({
        [`PUT /v1/ops/healer/incidents/${OUTAGE}/status`]: { ...outage, public: false, public_title: null },
      }),
    );
    await settle();
    const live = row("Calls are failing for many clients");
    expect(live.textContent).toContain("Calls are not connecting for some customers");
    fireEvent.click(within(live).getByRole("button", { name: "Take it off the status page" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Take it off" }));
    await settle();
    const put = calls.find((c) => c.method === "PUT" && c.path.endsWith(`/${OUTAGE}/status`));
    expect(put?.headers["X-Confirm-Action"]).toBe(`post_status:${OUTAGE}`);
    expect(JSON.parse(put?.body ?? "{}")).toEqual({ title: null, component: "calls" });
  });

  it("changes the words the public reads", async () => {
    const { calls } = await renderAdminRoute(
      <OpsHealerPage />,
      withOutage({ [`PUT /v1/ops/healer/incidents/${OUTAGE}/status`]: outage }),
    );
    await settle();
    fireEvent.click(
      within(row("Calls are failing for many clients")).getByRole("button", {
        name: "Change what the public reads",
      }),
    );
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("What the public reads"), {
      target: { value: "Calls in one region are not connecting" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Change it" }));
    await settle();
    const put = calls.find((c) => c.method === "PUT");
    expect(JSON.parse(put?.body ?? "{}")).toEqual({
      title: "Calls in one region are not connecting",
      component: "calls",
    });
  });

  it("offers an open problem that is not public a way onto the page, and a closed one none", async () => {
    await renderAdminRoute(<OpsHealerPage />, withOutage());
    await settle();
    const money = row("Call charges don't match our records");
    expect(within(money).getByRole("button", { name: "Show on the status page" })).toBeTruthy();
    const closed = row("Background jobs failed after every retry");
    expect(within(closed).queryByRole("button", { name: "Show on the status page" })).toBeNull();
  });
});
