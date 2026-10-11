import { act, fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import OpsHealerPage from "@/app/admin/ops/healer/page";
import type { HealerAction, HealerIncident, HealerOverview } from "@/lib/api/opsHealer";
import openapi from "@/lib/api/openapi.json";

import { renderAdminRoute } from "./adminRoute";

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
    ...over,
  };
}

const INCIDENTS: HealerIncident[] = [
  incident({}),
  incident({
    id: OUTBOX,
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
  }),
  incident({
    id: "019f1000-0000-7000-8000-0000000000w1",
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
    "/v1/ops/healer/incidents?days=7&limit=50": { items: INCIDENTS },
    "/v1/ops/healer/actions?limit=50": { items: ACTIONS },
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

  it("the API contract carries the plain words on every incident", () => {
    const schemas = (openapi as { components: { schemas: Record<string, { required?: string[] }> } })
      .components.schemas;
    for (const field of ["kind", "group", "automatic", "progress"]) {
      expect(schemas.IncidentOut?.required).toContain(field);
    }
    expect(schemas.IncidentKindOut?.required).toEqual(
      expect.arrayContaining(["code", "title", "meaning", "next_step"]),
    );
  });
});
