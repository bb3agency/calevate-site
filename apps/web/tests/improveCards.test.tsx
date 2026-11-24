import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ImproveTab } from "@/app/c/[slug]/campaigns/CampaignBoosters";
import { DiagnoseCards } from "@/components/improve/DiagnoseCards";
import { DropOffCard } from "@/components/improve/DropOffCard";
import { GiveCallersTimeCard } from "@/components/improve/GiveCallersTimeCard";
import { MistakesCard } from "@/components/improve/MistakesCard";
import { OpeningLossCard } from "@/components/improve/OpeningLossCard";
import { RefusalReasonsCard } from "@/components/improve/RefusalReasonsCard";
import { TestCallReviewCard } from "@/components/improve/TestCallReviewCard";
import type { Me } from "@/lib/api/client";
import type { Holder, HolderDiagnosis } from "@/lib/api/improve";

import { expectNoA11yViolations } from "./a11y";
import { FIXTURE_CAMPAIGN_ID, detailRoutes } from "./campaignFixtures";
import { EMPTY_DIAGNOSIS, GIVE_TIME_ON } from "./fixtures/diagnosis";
import { renderClientPage, stillLoading, type Routes } from "./harness";

/**
 * The Diagnose cards on a campaign's Improve tab and an Inbound line's Improve section
 * (founder, 24 Nov 2026). One component per card serves both holders: each is driven here
 * for its empty, too-few-calls and data states, and each press for its pending face and its
 * request, on a campaign and on a line.
 */

const CAMPAIGN: Holder = { kind: "campaign", id: "camp-1" };
const LINE: Holder = { kind: "inbound_line", id: "line-1" };
const DIAGNOSIS = { campaign: "/v1/campaigns/camp-1/diagnosis", line: "/v1/inbound-lines/line-1/diagnosis" };

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "leads:read", "leads:dispatch", "org:manage", "kb:write"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

function diagnosis(over: Partial<HolderDiagnosis> = {}): HolderDiagnosis {
  return { ...EMPTY_DIAGNOSIS, ...over };
}

const STEPS: HolderDiagnosis["drop_off"] = {
  judged_calls: 12,
  min_calls: 10,
  worst_step: 2,
  steps: [
    { step: 1, name: "Remembers the app", reached: 12, not_reached: 0, unclear: 0, lost_here: 0 },
    { step: 2, name: "Installs it", reached: 6, not_reached: 6, unclear: 0, lost_here: 6 },
    { step: 3, name: "Logs in", reached: 4, not_reached: 8, unclear: 0, lost_here: 2 },
  ],
};

async function render(ui: React.ReactElement, holder: Holder, data: HolderDiagnosis, extra: Routes = {}) {
  return await renderClientPage(ui, {
    "/v1/me": OWNER,
    [holder.kind === "campaign" ? DIAGNOSIS.campaign : DIAGNOSIS.line]: data,
    ...extra,
  });
}

function sent(calls: { method: string; path: string; body: string | null }[], method: string, path: string) {
  const call = calls.find((c) => c.method === method && c.path === path);
  return call?.body ? (JSON.parse(call.body) as Record<string, unknown>) : null;
}

describe("Where people drop off", () => {
  it("says no calls were checked yet", async () => {
    await render(<DropOffCard slug="acme" holder={CAMPAIGN} canWrite />, CAMPAIGN, diagnosis());
    expect(await screen.findByText("No calls checked yet.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Fix this step" })).toBeNull();
  });

  it("says too few calls instead of drawing noise", async () => {
    const few = { ...STEPS, judged_calls: 4, worst_step: null };
    await render(<DropOffCard slug="acme" holder={CAMPAIGN} canWrite />, CAMPAIGN, diagnosis({ drop_off: few }));
    expect(await screen.findByText("Too few calls to say yet: 4 of 10 checked.")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Calls that reached each step" })).toBeNull();
  });

  it("draws a bar per step, names the worst, and asks Pip to fix it on a campaign", async () => {
    const { calls, container } = await render(
      <DropOffCard slug="acme" holder={CAMPAIGN} canWrite />,
      CAMPAIGN,
      diagnosis({ drop_off: STEPS }),
      { "POST /v1/campaigns/camp-1/script/proposal": stillLoading() },
    );
    const list = await screen.findByRole("list", { name: "Calls that reached each step" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[1]!.textContent).toContain("6 lost here");
    expect(rows[1]!.textContent).toContain("most people stop here");
    expect(screen.getByText("Most people stop at step 2: Installs it.")).toBeTruthy();
    await expectNoA11yViolations(container, "DropOffCard");

    fireEvent.click(screen.getByRole("button", { name: "Fix this step" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Fix this step" }).getAttribute("aria-busy")).toBe("true"));
    const body = sent(calls, "POST", "/v1/campaigns/camp-1/script/proposal");
    expect(body?.instruction).toContain('step 2, "Installs it"');
  });

  it("asks the line's own route on a line, and says where to review it", async () => {
    const { calls } = await render(<DropOffCard slug="acme" holder={LINE} canWrite />, LINE, diagnosis({ drop_off: STEPS }), {
      "POST /v1/inbound-lines/line-1/proposal": { id: "p1", status: "drafting" },
      "/v1/inbound-lines/line-1": stillLoading(),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Fix this step" }));
    expect(await screen.findByText("Pip is writing it.", { exact: false })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Review it in Script" }).getAttribute("href")).toBe("#line-script");
    expect(sent(calls, "POST", "/v1/inbound-lines/line-1/proposal")?.instruction).toContain("step 2");
  });
});

describe("Mistakes on these calls", () => {
  it("says none were found", async () => {
    await render(<MistakesCard slug="acme" holder={LINE} />, LINE, diagnosis());
    expect(await screen.findByText("No mistakes found in the last 30 days.")).toBeTruthy();
  });

  it("lists each kind with its count, its fix in the call page's words and its latest call", async () => {
    const { container } = await render(
      <MistakesCard slug="acme" holder={CAMPAIGN} />,
      CAMPAIGN,
      diagnosis({
        mistakes: [
          { kind: "said_again", label: "Said the same line again", calls: 3, last_call_id: "call-9", last_seen_at: "2026-11-20T10:00:00Z", status: "repaired" },
          { kind: "asked_again", label: "Asked the same question again, word for word", calls: 1, last_call_id: "call-4", last_seen_at: "2026-11-19T10:00:00Z", status: "told" },
        ],
      }),
    );
    const rows = within(await screen.findByRole("list", { name: "Mistakes on these calls" })).getAllByRole("listitem");
    expect(rows[0]!.textContent).toContain("3 calls");
    expect(rows[0]!.textContent).toContain("Fixed in your script");
    expect(rows[1]!.textContent).toContain("Our team has been told");
    expect(within(rows[0]!).getByRole("link").getAttribute("href")).toContain("/c/acme/calls/call-9");
    await expectNoA11yViolations(container, "MistakesCard");
  });
});

describe("Openings that lose people", () => {
  it("says no answered calls yet, and too few to judge", async () => {
    await render(<OpeningLossCard slug="acme" holder={CAMPAIGN} canWrite />, CAMPAIGN, diagnosis());
    expect(await screen.findByText("No answered calls yet.")).toBeTruthy();
  });

  it("says too few answered calls", async () => {
    const few = { ...diagnosis().early_hang_ups, answered: 6, early: 3 };
    await render(<OpeningLossCard slug="acme" holder={LINE} canWrite />, LINE, diagnosis({ early_hang_ups: few }));
    expect(await screen.findByText("Too few calls to say yet: 6 of 20 answered.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Rewrite the opening" })).toBeNull();
  });

  it("compares with the other campaigns and rewrites the opening keeping the notices", async () => {
    const data = diagnosis({
      early_hang_ups: { answered: 40, early: 12, rate: 0.3, others_answered: 50, others_rate: 0.1, min_answered: 20, early_seconds: 20 },
    });
    const { calls, container } = await render(<OpeningLossCard slug="acme" holder={CAMPAIGN} canWrite />, CAMPAIGN, data, {
      "POST /v1/campaigns/camp-1/script/proposal": stillLoading(),
    });
    expect(await screen.findByText("30%")).toBeTruthy();
    expect(screen.getByText(/Your other campaigns: 10%/)).toBeTruthy();
    expect(screen.getByText("More than on your other campaigns.")).toBeTruthy();
    // The notices are never offered as the thing to cut (hard rule 5).
    expect(container.textContent).not.toMatch(/remove|turn off|switch off/i);
    await expectNoA11yViolations(container, "OpeningLossCard");
    fireEvent.click(screen.getByRole("button", { name: "Rewrite the opening" }));
    await waitFor(() => expect(sent(calls, "POST", "/v1/campaigns/camp-1/script/proposal")).not.toBeNull());
    const instruction = String(sent(calls, "POST", "/v1/campaigns/camp-1/script/proposal")?.instruction);
    expect(instruction).toContain("Keep the AI and recording notices");
    expect(instruction).toContain("why we are calling");
  });
});

describe("Why people said no", () => {
  it("says no reason was given", async () => {
    await render(<RefusalReasonsCard slug="acme" holder={CAMPAIGN} />, CAMPAIGN, diagnosis());
    expect(await screen.findByText("No one gave a reason for no in the last 30 days.")).toBeTruthy();
  });

  it("counts each reason and teaches an answer as a question every agent keeps", async () => {
    const { calls, container } = await render(
      <RefusalReasonsCard slug="acme" holder={LINE} />,
      LINE,
      diagnosis({ refusal_reasons: [{ reason: "price", calls: 5 }, { reason: "busy_now", calls: 2 }] }),
      {
        "/v1/kb/knows": {
          facts: [{ id: "f1", text: "Call back at a better time.", question: "What do we say when someone is busy right now?", pinned: true, origin: "taught", created_at: "2026-11-20T10:00:00Z" }],
          facts_state: "live",
          items: [],
          pinned_not_yet_on: [],
        },
        "POST /v1/kb/facts": stillLoading(),
      },
    );
    const rows = within(await screen.findByRole("list", { name: "Why people said no" })).getAllByRole("listitem");
    expect(rows[0]!.textContent).toContain("The price");
    expect(rows[0]!.textContent).toContain("5 calls");
    await waitFor(() => expect(within(rows[1]!).getByText("Answer taught")).toBeTruthy());
    await expectNoA11yViolations(container, "RefusalReasonsCard");

    fireEvent.click(within(rows[0]!).getByRole("button", { name: "Teach an answer: The price" }));
    const box = screen.getByLabelText("What do we say when someone says the price is too high?");
    fireEvent.change(box, { target: { value: "We have a smaller plan." } });
    fireEvent.click(screen.getByRole("button", { name: "Save answer" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save answer" }).getAttribute("aria-busy")).toBe("true"));
    expect(sent(calls, "POST", "/v1/kb/facts")).toEqual({
      text: "We have a smaller plan.",
      question: "What do we say when someone says the price is too high?",
      pinned: true,
    });
  });
});

describe("Your latest test call", () => {
  it("asks for a test call when there is none", async () => {
    await render(<TestCallReviewCard slug="acme" holder={CAMPAIGN} />, CAMPAIGN, diagnosis(), {
      "/v1/campaigns/camp-1/test-calls": [],
    });
    expect(await screen.findByText("No test call yet. Call yourself to hear it first.")).toBeTruthy();
  });

  it("waits while the call is on", async () => {
    await render(<TestCallReviewCard slug="acme" holder={LINE} />, LINE, diagnosis(), {
      "/v1/inbound-lines/line-1/test-calls": [
        { call_id: "call-7", placed_at: "2026-11-24T05:00:00Z", status: "in_progress", duration_s: null, has_recording: false },
      ],
    });
    expect(await screen.findByText("The call is still on. Its review shows here once it ends.")).toBeTruthy();
  });

  it("shows the steps reached and the mistakes found, with the call's page", async () => {
    const { container } = await render(<TestCallReviewCard slug="acme" holder={LINE} />, LINE, diagnosis(), {
      "/v1/inbound-lines/line-1/test-calls": [
        { call_id: "call-7", placed_at: "2026-11-24T05:00:00Z", status: "completed", duration_s: 60, has_recording: false },
      ],
      "/v1/calls/call-7": {
        steps: [
          { step: 1, name: "Greets", state: "reached", turn_idx: 1 },
          { step: 2, name: "Books a visit", state: "not_reached", turn_idx: null },
        ],
        mistakes: [{ kind: "said_again", label: "Said the same line again", instead: "", turn_idx: 3, fix: "repairing" }],
      },
    });
    const steps = within(await screen.findByRole("list", { name: "Steps on the test call" })).getAllByRole("listitem");
    expect(steps[0]!.textContent).toContain("Done");
    expect(steps[1]!.textContent).toContain("Not done");
    expect(screen.getByText("Fixing it in your script")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the test call" }).getAttribute("href")).toContain("/c/acme/calls/call-7");
    await expectNoA11yViolations(container, "TestCallReviewCard");
  });
});

describe("the five cards together", () => {
  it("each shows its loading state while the reading is on its way", async () => {
    await renderClientPage(<DiagnoseCards slug="acme" holder={CAMPAIGN} canWrite />, {
      "/v1/me": OWNER,
      [DIAGNOSIS.campaign]: stillLoading(),
      "/v1/campaigns/camp-1/test-calls": stillLoading(),
    });
    expect(screen.getByText("Reading where calls stop")).toBeTruthy();
    expect(screen.getByText("Reading how many hang up early")).toBeTruthy();
    expect(screen.getByText("Reading why people said no")).toBeTruthy();
    expect(screen.getByText("Reading the mistakes on these calls")).toBeTruthy();
    expect(screen.getByText("Loading your test calls")).toBeTruthy();
  });
});

describe("where the cards are placed", () => {
  it("leads a campaign's Improve tab", async () => {
    await renderClientPage(
      <ImproveTab slug="acme" campaignId={FIXTURE_CAMPAIGN_ID} canWrite agentId="agent-1" status="running" />,
      { "/v1/me": OWNER, ...detailRoutes(FIXTURE_CAMPAIGN_ID) },
    );
    await screen.findByText("No calls checked yet.");
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(titles.slice(0, 5)).toEqual([
      "Where people drop off",
      "Openings that lose people",
      "Why people said no",
      "Mistakes on these calls",
      "Your latest test call",
    ]);
    expect(titles).toContain("Best time to call");
    expect(titles).toContain("Give callers time");
  });
});

describe("Give callers time on a campaign or line (founder, 25 Nov 2026)", () => {
  const PATH = { campaign: "/v1/campaigns/camp-1/give-callers-time", line: "/v1/inbound-lines/line-1/give-callers-time" };

  it("says it is on because the script asks callers to act, and the owner can turn it off", async () => {
    const { calls, container } = await renderClientPage(
      <GiveCallersTimeCard slug="acme" holder={LINE} canWrite />,
      {
        "/v1/me": OWNER,
        [`GET ${PATH.line}`]: GIVE_TIME_ON,
        [`PUT ${PATH.line}`]: { ...GIVE_TIME_ON, on: false, owner_choice: false },
      },
    );
    expect(
      await screen.findByText("On, because the script asks callers to do things on their phone."),
    ).toBeTruthy();
    await expectNoA11yViolations(container, "Give callers time, on by the script");
    const toggle = screen.getByRole("switch", { name: /Give quiet callers time/ }) as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    fireEvent.click(toggle);
    await screen.findByText("Off. You turned it off.");
    const sent = calls.filter((c) => c.method === "PUT" && c.path === PATH.line);
    expect(sent).toHaveLength(1);
    expect(JSON.parse(sent[0].body ?? "{}")).toEqual({ on: false });
  });

  it("holds the switch and says why for someone who cannot change it", async () => {
    await renderClientPage(
      <GiveCallersTimeCard slug="acme" holder={CAMPAIGN} canWrite={false} refusal="Only an account owner can start or run campaigns." />,
      { "/v1/me": OWNER, [PATH.campaign]: { ...GIVE_TIME_ON, on: false, script_asks: false } },
    );
    const toggle = (await screen.findByRole("switch", { name: /Give quiet callers time/ })) as HTMLInputElement;
    expect(toggle.disabled).toBe(true);
    expect(screen.getByText("Off. The script does not ask callers to do things on their phone.")).toBeTruthy();
    expect(screen.getByText("Only an account owner can start or run campaigns.")).toBeTruthy();
  });
});
