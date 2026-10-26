import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PlanCard, type PlanDecision } from "@/components/copilot/PlanCard";
import { useClientRealm } from "@/lib/api/session";

import { expectNoA11yViolations } from "./a11y";
import { renderClientPage, type ApiCall } from "./harness";
import { PLAN_ID, planFixture } from "./planFixture";

const PLAN_PATH = `/v1/copilot/plans/${PLAN_ID}`;

function Card(props: { decision?: PlanDecision; onChange?: () => void; onDecided?: () => void }) {
  const { session } = useClientRealm();
  return <PlanCard session={session} planId={PLAN_ID} {...props} />;
}

function posted(calls: ApiCall[], path: string): ApiCall | undefined {
  return calls.find((call) => call.method === "POST" && call.path === path);
}

afterEach(() => {
  vi.useRealTimers();
});

describe("the plan card says who, why, when and what it costs before anything happens", () => {
  it("draws the server's sentences, the count going ahead, and who is left out with why", async () => {
    const { container } = await renderClientPage(<Card />, {
      [PLAN_PATH]: planFixture({
        target_count: 140,
        excluded_count: 12,
        exclusions: [
          { reason: "On your do-not-call list", count: 9 },
          { reason: "Already contacted", count: 3 },
        ],
        estimate_inr: "84.00",
        estimate_note: "About 1 minute a call at your Clear rate.",
      }),
    });

    const card = await screen.findByRole("region", { name: /Plan: Set 140 leads to contacted/ });
    expect(within(card).getByText("Plan — nothing has happened yet")).toBeTruthy();
    expect(within(card).getByText(/You asked to mark last week's missed callers/)).toBeTruthy();
    // 140 matched, 12 left out: the "who" line counts the ones it will act on.
    expect(within(card).getByText(/^128 leads — Leads that came in/)).toBeTruthy();
    expect(within(card).getByText("9 — On your do-not-call list")).toBeTruthy();
    expect(within(card).getByText("3 — Already contacted")).toBeTruthy();
    expect(within(card).getByText(/About 1 minute a call/)).toBeTruthy();
    expect(within(card).getByText("As soon as you approve")).toBeTruthy();
    await expectNoA11yViolations(container, "PlanCard (proposed)");
  });

  it("wraps every server sentence so a phone-width panel never scrolls sideways", async () => {
    const long = "Leads-who-came-in-from-the-Gachibowli-hoarding-campaign".repeat(4);
    await renderClientPage(<Card />, { [PLAN_PATH]: planFixture({ who: long, title: long }) });
    const card = await screen.findByRole("region", { name: /Plan:/ });
    for (const node of within(card).getAllByText(new RegExp(long.slice(0, 30)))) {
      expect(node.className).toContain("[overflow-wrap:anywhere]");
    }
  });

  it("lists the targets a page at a time, only once asked", async () => {
    const targets = Array.from({ length: 25 }, (_, i) => ({
      target_id: `t-${i}`,
      position: i,
      excluded: i === 0,
      status: "pending",
      reason: i === 0 ? "On your do-not-call list" : null,
      label: `Caller ${i + 1}`,
      finished_at: null,
    }));
    const { calls } = await renderClientPage(<Card />, {
      [PLAN_PATH]: planFixture({ target_count: 40 }),
      [`${PLAN_PATH}/targets?limit=25&offset=0`]: { targets, total: 40, limit: 25, offset: 0 },
      [`${PLAN_PATH}/targets?limit=25&offset=25`]: {
        targets: [{ ...targets[1], target_id: "t-last", label: "Caller 26" }],
        total: 40,
        limit: 25,
        offset: 25,
      },
    });
    const open = await screen.findByRole("button", { name: "See all 40 leads" });
    expect(calls.some((call) => call.path.includes("/targets"))).toBe(false);
    fireEvent.click(open);
    expect(await screen.findByText("Caller 2")).toBeTruthy();
    expect(screen.getByText("Left out")).toBeTruthy();
    expect(screen.getByText("1–25 of 40")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Caller 26")).toBeTruthy();
  });
});

describe("one click, through the door the card was opened from", () => {
  it("approves a plan with the hash it was drawn from", async () => {
    const onDecided = vi.fn();
    const { calls } = await renderClientPage(<Card onDecided={onDecided} />, {
      [PLAN_PATH]: planFixture(),
      [`POST ${PLAN_PATH}/approve`]: planFixture({ status: "approved", can_approve: false }),
    });
    fireEvent.click(await screen.findByRole("button", { name: /Approve — Set 140 leads/ }));
    await vi.waitFor(() => expect(posted(calls, `${PLAN_PATH}/approve`)).toBeTruthy());
    expect(JSON.parse(posted(calls, `${PLAN_PATH}/approve`)?.body ?? "{}")).toEqual({
      plan_hash: "a".repeat(64),
    });
    await vi.waitFor(() => expect(onDecided).toHaveBeenCalledTimes(1));
  });

  it("confirms Pip's proposal with its signed token", async () => {
    const { calls } = await renderClientPage(
      <Card decision={{ kind: "proposal", token: "signed.token", confirmAction: null }} />,
      {
        [PLAN_PATH]: planFixture(),
        "POST /v1/copilot/confirm": {
          tool: "leads_bulk_update",
          applied: true,
          detail: "Approved. It runs in the background.",
          plan_id: PLAN_ID,
        },
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: /Approve — / }));
    await vi.waitFor(() => expect(posted(calls, "/v1/copilot/confirm")).toBeTruthy());
    expect(JSON.parse(posted(calls, "/v1/copilot/confirm")?.body ?? "{}")).toEqual({
      token: "signed.token",
    });
    expect(posted(calls, `${PLAN_PATH}/approve`)).toBeUndefined();
  });

  it("approves a staged plan through the inbox's own approval", async () => {
    const { calls } = await renderClientPage(
      <Card decision={{ kind: "approval", actionId: "act-1", confirmAction: null }} />,
      {
        [PLAN_PATH]: planFixture(),
        "POST /v1/copilot/approvals/act-1/approve": {
          tool: "leads_bulk_update",
          applied: true,
          detail: "Approved.",
          plan_id: PLAN_ID,
        },
      },
    );
    fireEvent.click(await screen.findByRole("button", { name: /Approve — / }));
    await vi.waitFor(() => expect(posted(calls, "/v1/copilot/approvals/act-1/approve")).toBeTruthy());
  });

  it("puts the request back for a change, and cancels without doing anything", async () => {
    const onChange = vi.fn();
    const { calls } = await renderClientPage(<Card onChange={onChange} />, {
      [PLAN_PATH]: planFixture(),
      [`POST ${PLAN_PATH}/cancel`]: planFixture({ status: "cancelled", can_approve: false, can_cancel: false }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Change" }));
    expect(onChange).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /Cancel — / }));
    await vi.waitFor(() => expect(posted(calls, `${PLAN_PATH}/cancel`)).toBeTruthy());
    expect(posted(calls, `${PLAN_PATH}/approve`)).toBeUndefined();
  });

  it("arms a plan that reaches callers only after a beat, in the danger colour", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderClientPage(<Card />, {
      [PLAN_PATH]: planFixture({ tool: "calls_place_bulk", title: "Call 140 leads" }),
    });
    const approve = (await screen.findByRole("button", { name: /Approve — Call 140 leads/ })) as HTMLButtonElement;
    expect(approve.disabled).toBe(true);
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(approve.disabled).toBe(false);
  });
});

describe("while it runs and once it has finished", () => {
  it("shows progress and a Stop while it runs", async () => {
    const { container } = await renderClientPage(<Card />, {
      [PLAN_PATH]: planFixture({
        status: "running",
        can_approve: false,
        started_at: "2026-10-27T10:00:01Z",
        done_count: 30,
        skipped_count: 5,
        failed_count: 5,
      }),
    });
    expect(await screen.findByText("Working on it")).toBeTruthy();
    expect(screen.getByText("40 of 140 done")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Stop — / })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Approve — / })).toBeNull();
    await expectNoA11yViolations(container, "PlanCard (running)");
  });

  it("states the server's result once done", async () => {
    await renderClientPage(<Card />, {
      [PLAN_PATH]: planFixture({
        status: "done",
        can_approve: false,
        can_cancel: false,
        done_count: 138,
        skipped_count: 2,
        result: "138 set to contacted; 2 had already moved on.",
      }),
    });
    const result = await screen.findByText("138 set to contacted; 2 had already moved on.");
    expect(result.getAttribute("role")).toBe("status");
    expect(screen.getByText("Finished")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Approve — |Stop — / })).toBeNull();
  });
});
