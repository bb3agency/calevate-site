import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BestHoursCard } from "@/components/improve/BestHoursCard";
import { OpeningTestCard, listSizeWords } from "@/components/improve/OpeningTestCard";
import { RetrySpreadCard } from "@/components/improve/RetrySpreadCard";
import type { CampaignInsights } from "@/lib/api/campaignWorkspace";

import { expectNoA11yViolations } from "./a11y";
import { insightsFixture } from "./campaignFixtures";
import { renderClientPage } from "./harness";

/*
 * The Improve tab's cards (D-992 item 8): each says where it stands (nothing yet, too few,
 * measuring, ready, done) and offers one press when there is something to do, with Undo
 * after it. Every state is scanned by axe.
 */

const CAMPAIGN = "0192f0aa-8888-7000-8000-00000000c0a1";
const BASE = `/v1/campaigns/${CAMPAIGN}`;

type BestHours = CampaignInsights["best_hours"];
type Opening = CampaignInsights["opening"];

const block = (start: string, end: string, people: number, reached: number, chance: number | null) => ({
  start,
  end,
  people,
  reached,
  rate: people ? reached / people : 0,
  chance,
});

function bestHours(over: Partial<BestHours> = {}): BestHours {
  return {
    state: "empty",
    best: null,
    blocks: [],
    hours: [],
    min_people_per_block: 50,
    chance_needed: 0.9875,
    calling_hours: null,
    applied: null,
    auto: false,
    ...over,
  };
}

const MEASURED: Partial<BestHours> = {
  state: "actionable",
  best: block("18:00", "21:00", 60, 50, 0.999),
  blocks: [block("09:00", "12:00", 60, 10, 0.0), block("18:00", "21:00", 60, 50, 0.999)],
  hours: [
    { hour: 10, people: 60, reached: 10, rate: 0.17 },
    { hour: 19, people: 60, reached: 50, rate: 0.83 },
  ],
};

function opening(over: Partial<Opening> = {}): Opening {
  return {
    opening_b: null,
    state: "off",
    chance_b_better: null,
    goal_chance_b_better: null,
    openings: [],
    min_answered_per_opening: 388,
    win_chance: 0.95,
    stayed_seconds: 20,
    list_size: { people: 2000, answer_rate: 0.5, answered_needed: 776, large_enough: true },
    decision: null,
    ...over,
  };
}

const insights = (over: Partial<CampaignInsights> = {}): CampaignInsights => insightsFixture(over);

const card = (data: BestHours) => (
  <BestHoursCard campaignId={CAMPAIGN} data={data} canWrite refusal={undefined} />
);

describe("the best time to call card", () => {
  it("says there is nothing yet, with no button, before any call", async () => {
    const view = await renderClientPage(card(bestHours()), {});
    expect(screen.getByText(/No calls yet/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Call only/ })).toBeNull();
    await expectNoA11yViolations(view.container, "best hours, empty");
  });

  it("says how many people a block needs while there are too few", async () => {
    const view = await renderClientPage(
      card(bestHours({ state: "too_few", hours: [{ hour: 10, people: 8, reached: 1, rate: 0.125 }] })),
      {},
    );
    expect(screen.getByText(/Each block needs 50 people tried/)).toBeTruthy();
    expect(screen.getByText("1/8 people")).toBeTruthy();
    await expectNoA11yViolations(view.container, "best hours, too few");
  });

  it("says it is measuring when no block stands out", async () => {
    await renderClientPage(card(bestHours({ state: "measuring", hours: MEASURED.hours })), {});
    expect(screen.getByText(/No block of the day stands out yet/)).toBeTruthy();
  });

  it("offers one press that narrows the hours, then Undo", async () => {
    const applied = bestHours({
      ...MEASURED,
      calling_hours: { start: "18:00", end: "21:00" },
      applied: {
        block: { start: "18:00", end: "21:00" },
        before: null,
        by: "owner",
        at: "2026-11-24T10:00:00Z",
      },
    });
    const view = await renderClientPage(card(bestHours(MEASURED)), {
      [`POST ${BASE}/best-hours/apply`]: insights({ best_hours: applied }),
    });
    await expectNoA11yViolations(view.container, "best hours, actionable");
    fireEvent.click(screen.getByRole("button", { name: "Call only 6pm to 9pm" }));
    await waitFor(() => expect(view.calls.some((c) => c.path === `${BASE}/best-hours/apply`)).toBe(true));
  });

  it("shows what was applied, by whom, with Undo", async () => {
    const view = await renderClientPage(
      card(
        bestHours({
          ...MEASURED,
          applied: {
            block: { start: "18:00", end: "21:00" },
            before: { start: "09:00", end: "21:00" },
            by: "pip",
            at: "2026-11-24T10:00:00Z",
          },
          auto: true,
        }),
      ),
      { [`POST ${BASE}/best-hours/undo`]: insights() },
    );
    expect(screen.getByText("Calls only 6pm to 9pm.")).toBeTruthy();
    expect(screen.getByText(/Pip narrowed the hours/)).toBeTruthy();
    expect((screen.getByRole("switch") as HTMLInputElement).checked).toBe(true);
    await expectNoA11yViolations(view.container, "best hours, applied");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(view.calls.some((c) => c.path === `${BASE}/best-hours/undo`)).toBe(true));
  });

  it("starts Pip's switch off and sends the owner's choice", async () => {
    const view = await renderClientPage(card(bestHours(MEASURED)), {
      [`PUT ${BASE}/best-hours/auto`]: insights(),
    });
    const toggle = screen.getByRole("switch", { name: /Let Pip do this/ }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    fireEvent.click(toggle);
    await waitFor(() => {
      const sent = view.calls.find((c) => c.path === `${BASE}/best-hours/auto`);
      expect(sent?.body).toBe(JSON.stringify({ on: true }));
    });
  });
});

describe("the retry card", () => {
  it("shows the switch on with the tries and gaps, and sends off", async () => {
    const view = await renderClientPage(
      <RetrySpreadCard campaignId={CAMPAIGN} data={insights().retry} canWrite />,
      { [`PUT ${BASE}/retry-spread`]: insights() },
    );
    expect(screen.getByText(/Up to 3 tries, at least 30 minutes, then 2 hours apart/)).toBeTruthy();
    await expectNoA11yViolations(view.container, "retries");
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() => {
      const sent = view.calls.find((c) => c.path === `${BASE}/retry-spread`);
      expect(sent?.body).toBe(JSON.stringify({ on: false }));
    });
  });
});

const openingCard = (data: Opening) => (
  <OpeningTestCard campaignId={CAMPAIGN} data={data} canWrite refusal={undefined} />
);

describe("the opening test card", () => {
  it("says a list is large enough before it starts", async () => {
    const view = await renderClientPage(openingCard(opening()), {});
    expect(screen.getByText(/Large enough: each opening needs 388 people who pick up/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start the test" })).toBeTruthy();
    await expectNoA11yViolations(view.container, "opening, off");
  });

  it("offers a small list the practice comparison instead, and shows its result", async () => {
    const small = opening({
      list_size: { people: 40, answer_rate: null, answered_needed: 776, large_enough: false },
    });
    expect(listSizeWords(small)).toMatch(/Too small/);
    const view = await renderClientPage(openingCard(small), {
      [`POST ${BASE}/opening-practice`]: {
        own: { line: "Hello, this is Asha.", mistakes: [] },
        second: { line: "Hello [name]", mistakes: ["It says a bracket aloud."] },
        fewer: "a",
      },
    });
    expect(screen.queryByRole("button", { name: "Start the test" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Second opening"), { target: { value: "Hello [name]" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare in practice" }));
    expect(await screen.findByText("The script's own opening has fewer mistakes.")).toBeTruthy();
    expect(screen.getByText("It says a bracket aloud.")).toBeTruthy();
    await expectNoA11yViolations(view.container, "opening, practice");
  });

  it("shows progress while too few have picked up", async () => {
    const view = await renderClientPage(
      openingCard(
        opening({
          opening_b: "A second line.",
          state: "too_few",
          chance_b_better: 0.6,
          openings: [
            { variant: "a", people: 120, answered: 100, stayed: 40, goal_reached: 5, stayed_rate: 0.4, goal_rate: 0.05 },
            { variant: "b", people: 120, answered: 90, stayed: 50, goal_reached: 6, stayed_rate: 0.56, goal_rate: 0.07 },
          ],
        }),
      ),
      {},
    );
    expect(screen.getByText(/90 of 388/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Stop the test" })).toBeTruthy();
    await expectNoA11yViolations(view.container, "opening, too few");
  });

  it("gives the chance, not a verdict, while measuring", async () => {
    await renderClientPage(
      openingCard(
        opening({
          opening_b: "A second line.",
          state: "measuring",
          chance_b_better: 0.72,
          openings: [
            { variant: "a", people: 500, answered: 400, stayed: 200, goal_reached: 5, stayed_rate: 0.5, goal_rate: 0.01 },
            { variant: "b", people: 500, answered: 400, stayed: 210, goal_reached: 6, stayed_rate: 0.53, goal_rate: 0.02 },
          ],
        }),
      ),
      {},
    );
    expect(screen.getByText(/keeps more people: 72%\. It wins on its own at 95%/)).toBeTruthy();
  });

  it("says the second opening won and offers Undo", async () => {
    const view = await renderClientPage(
      openingCard(
        opening({
          decision: {
            winner: "b",
            chance_b_better: 0.97,
            applied: true,
            opening_b: "A second line.",
            at: "2026-11-24T10:00:00Z",
            undone: false,
            can_undo: true,
          },
        }),
      ),
      { [`POST ${BASE}/opening-test/undo`]: insights() },
    );
    expect(screen.getByText(/It is now this campaign's opening/)).toBeTruthy();
    await expectNoA11yViolations(view.container, "opening, decided");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(view.calls.some((c) => c.path === `${BASE}/opening-test/undo`)).toBe(true),
    );
  });
});
