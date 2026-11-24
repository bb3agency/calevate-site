import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ImprovePage from "@/app/c/[slug]/improve/page";
import { CompareCard } from "@/components/improve/account/CompareCard";
import { ContactHealthCard } from "@/components/improve/account/ContactHealthCard";
import { CostPerResultCard } from "@/components/improve/account/CostPerResultCard";
import { FollowUpsCard } from "@/components/improve/account/FollowUpsCard";
import { KnowledgeGapsCard } from "@/components/improve/account/KnowledgeGapsCard";
import { MistakePatternsCard } from "@/components/improve/account/MistakePatternsCard";
import { NumberHealthCard } from "@/components/improve/account/NumberHealthCard";
import { PipFixesCard } from "@/components/improve/account/PipFixesCard";
import { WeeklySummaryCard } from "@/components/improve/account/WeeklySummaryCard";
import type { AccountImprove } from "@/lib/api/accountImprove";
import type { Me } from "@/lib/api/client";
import { clientNavigation } from "@/lib/clientNav";

import { expectNoA11yViolations } from "./a11y";
import {
  CALLER_QUESTION,
  EMPTY_ACCOUNT_IMPROVE,
  FULL_ACCOUNT_IMPROVE,
  WEEKLY_SUMMARY,
} from "./fixtures/accountImprove";
import { FIXTURE_CAMPAIGN_ID, campaignPage, detailRoutes, progressFixture } from "./campaignFixtures";
import { renderClientPage, stillLoading, type Routes } from "./harness";

/**
 * The account Improve page (founder, 24-25 Nov 2026): each card's empty, too-few and data
 * states, its one-press action where it has one, and the page under axe.
 */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "leads:read", "leads:dispatch", "kb:write", "billing:read", "calls:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const IMPROVE = "/v1/improve";
const LATEST = "/v1/improve/weekly-summaries?limit=1";

function account(over: Partial<AccountImprove> = {}): AccountImprove {
  return { ...EMPTY_ACCOUNT_IMPROVE, ...over };
}

async function render(ui: React.ReactElement, data: AccountImprove, extra: Routes = {}) {
  return await renderClientPage(ui, { "/v1/me": OWNER, [IMPROVE]: data, ...extra });
}

describe("the sidebar", () => {
  it("has one Improve entry right after Needs attention", () => {
    const items = clientNavigation("acme")[0]!.items.map((i) => i.label);
    expect(items.filter((l) => l === "Improve")).toHaveLength(1);
    expect(items.indexOf("Improve")).toBe(items.indexOf("Needs attention") + 1);
  });
});

describe("Number health", () => {
  it("says no calls yet", async () => {
    await render(<NumberHealthCard slug="acme" />, account());
    expect(await screen.findByText("No calls placed from your numbers yet.")).toBeTruthy();
  });

  it("says too few calls to judge", async () => {
    const few = { ...FULL_ACCOUNT_IMPROVE.numbers, numbers: [FULL_ACCOUNT_IMPROVE.numbers.numbers[1]!] };
    await render(<NumberHealthCard slug="acme" />, account({ numbers: few }));
    expect(await screen.findByText(/Too few calls to judge yet: each number needs 30 calls/)).toBeTruthy();
    expect(screen.queryByText("May be labelled spam")).toBeNull();
  });

  it("flags the number that dropped and links to the phone numbers", async () => {
    const { container } = await render(<NumberHealthCard slug="acme" />, account({ numbers: FULL_ACCOUNT_IMPROVE.numbers }));
    const rows = within(await screen.findByRole("list", { name: "Your calling numbers" })).getAllByRole("listitem");
    expect(rows[0]!.textContent).toContain("Last week 10%");
    expect(rows[0]!.textContent).toContain("before 50%");
    expect(within(rows[0]!).getByText("May be labelled spam")).toBeTruthy();
    expect(screen.getByText("One number is being answered far less than before.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open your phone numbers" }).getAttribute("href")).toBe("/c/acme/phone-number");
    await expectNoA11yViolations(container, "NumberHealthCard");
  });
});

describe("Your week", () => {
  it("says when the first summary comes", async () => {
    await render(<WeeklySummaryCard />, account(), { [LATEST]: [] });
    expect(await screen.findByText("The first one comes the Monday after a week with calls.")).toBeTruthy();
  });

  it("shows the latest paragraph with its figures, and past weeks on request", async () => {
    const earlier = { ...WEEKLY_SUMMARY, id: "sum-0", week_start: "2026-11-09", paragraph: "A quieter week." };
    const { container } = await render(<WeeklySummaryCard />, account(), {
      [LATEST]: [WEEKLY_SUMMARY],
      "/v1/improve/weekly-summaries?limit=26": [WEEKLY_SUMMARY, earlier],
    });
    expect(await screen.findByText(WEEKLY_SUMMARY.paragraph)).toBeTruthy();
    expect(screen.getByText("50%")).toBeTruthy();
    await expectNoA11yViolations(container, "WeeklySummaryCard");
    fireEvent.click(screen.getByRole("button", { name: "Past weeks" }));
    const past = await screen.findByRole("list", { name: "Past weeks" });
    expect(within(past).getByText("A quieter week.")).toBeTruthy();
  });
});

describe("Compare your campaigns", () => {
  it("says no campaign has calls yet", async () => {
    await render(<CompareCard slug="acme" />, account());
    expect(await screen.findByText("No campaign or line has calls in the last 30 days.")).toBeTruthy();
  });

  it("says too few calls to name a best one", async () => {
    const compare = { ...FULL_ACCOUNT_IMPROVE.compare, best_id: null, differences: [] };
    await render(<CompareCard slug="acme" />, account({ compare }));
    expect(await screen.findByText(/Too few calls to name a best one yet/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Use what works/ })).toBeNull();
  });

  it("names the best, links each row down to its Improve, and asks Pip for what works", async () => {
    const { calls, container } = await render(<CompareCard slug="acme" />, account({ compare: FULL_ACCOUNT_IMPROVE.compare }), {
      "POST /v1/campaigns/camp-other/script/proposal": stillLoading(),
    });
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("link", { name: "Rytu Khata installs" }).getAttribute("href")).toBe(
      "/c/acme/campaigns/camp-best?tab=improve",
    );
    expect(within(table).getByRole("link", { name: "Front desk" }).getAttribute("href")).toBe(
      "/c/acme/inbound/line-1#line-improve",
    );
    expect(screen.getByText(/reaching its goal on 50% of/)).toBeTruthy();
    expect(screen.getByText(/8 words; the others 30 words/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Change the calling hours on Renewals" })).toBeTruthy();
    await expectNoA11yViolations(container, "CompareCard");

    fireEvent.click(screen.getByRole("button", { name: "Use what works: opening line" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Use what works: opening line" }).getAttribute("aria-busy")).toBe("true"),
    );
    const sent = calls.find((c) => c.method === "POST" && c.path === "/v1/campaigns/camp-other/script/proposal");
    expect(String(JSON.parse(sent?.body ?? "{}").instruction)).toContain("about 8 words");
  });

  it("sends a line's draft to the line's own route", async () => {
    const { calls } = await render(<CompareCard slug="acme" />, account({ compare: FULL_ACCOUNT_IMPROVE.compare }), {
      "POST /v1/inbound-lines/line-1/proposal": stillLoading(),
    });
    fireEvent.change(await screen.findByLabelText("Use what works on"), { target: { value: "line-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Use what works: opening line" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/v1/inbound-lines/line-1/proposal")).toBe(true));
    expect(screen.queryByRole("link", { name: /Change the calling hours/ })).toBeNull();
  });
});

describe("Mistakes across campaigns", () => {
  it("needs two campaigns or lines with calls", async () => {
    await render(<MistakePatternsCard slug="acme" />, account());
    expect(await screen.findByText("This needs calls on two or more campaigns or lines.")).toBeTruthy();
  });

  it("says none repeat", async () => {
    await render(<MistakePatternsCard slug="acme" />, account({ compare: FULL_ACCOUNT_IMPROVE.compare }));
    expect(await screen.findByText(/No mistake shows on more than one campaign or line/)).toBeTruthy();
  });

  it("flags a shared mistake as the agent's or training's and links to both", async () => {
    const { container } = await render(
      <MistakePatternsCard slug="acme" />,
      account({ compare: FULL_ACCOUNT_IMPROVE.compare, patterns: FULL_ACCOUNT_IMPROVE.patterns }),
    );
    const row = within(await screen.findByRole("list", { name: "Mistakes across campaigns" })).getByRole("listitem");
    expect(row.textContent).toContain("7 calls on 3 campaigns and lines");
    expect(row.textContent).toContain("Likely the agent or company training, not one script.");
    expect(within(row).getByRole("link", { name: /Asha's settings/ }).getAttribute("href")).toBe("/c/acme/agents/agent-1");
    expect(within(row).getByRole("link", { name: /Company training/ }).getAttribute("href")).toBe(
      "/c/acme/knowledge?tab=training",
    );
    await expectNoA11yViolations(container, "MistakePatternsCard");
  });
});

describe("Questions no agent could answer", () => {
  it("says every question had an answer", async () => {
    await render(<KnowledgeGapsCard slug="acme" />, account(), { "/v1/teach/questions": { items: [], open_count: 0 } });
    expect(await screen.findByText("Your agents had an answer for everything callers asked.")).toBeTruthy();
  });

  it("lists callers' questions across agents and opens the teach flow on one", async () => {
    const setup = { ...CALLER_QUESTION, key: "hours", question: "When are you open?", why: "setup" as const, callers: 0 };
    const { container } = await render(<KnowledgeGapsCard slug="acme" />, account(), {
      "/v1/teach/questions": { items: [CALLER_QUESTION, setup], open_count: 2 },
    });
    const rows = within(await screen.findByRole("list", { name: "Questions no agent could answer" })).getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(rows[0]!.textContent).toContain("Asked on 6 calls to 2 agents");
    expect(within(rows[0]!).getByRole("link", { name: /Teach an answer/ }).getAttribute("href")).toBe(
      "/c/acme/knowledge?question=delivery",
    );
    expect(screen.getByRole("link", { name: "What your agents know" })).toBeTruthy();
    await expectNoA11yViolations(container, "KnowledgeGapsCard");
  });
});

describe("Counts that open other pages", () => {
  it("says no one is waiting, and the lists look clean", async () => {
    await render(
      <>
        <FollowUpsCard slug="acme" />
        <ContactHealthCard slug="acme" />
      </>,
      account(),
    );
    expect(await screen.findByText("No one is waiting on a follow-up or a call-back.")).toBeTruthy();
    expect(screen.getByText("Your contact lists look clean.")).toBeTruthy();
  });

  it("counts people waiting and contact problems, linking to the filtered pages", async () => {
    const { container } = await render(
      <>
        <FollowUpsCard slug="acme" />
        <ContactHealthCard slug="acme" />
      </>,
      account({ follow_ups: FULL_ACCOUNT_IMPROVE.follow_ups, contacts: FULL_ACCOUNT_IMPROVE.contacts }),
    );
    const waiting = within(await screen.findByRole("list", { name: "People waiting on you" })).getAllByRole("link");
    expect(waiting[0]!.getAttribute("href")).toBe("/c/acme/leads?status=hot");
    expect(waiting[0]!.textContent).toContain("4");
    expect(waiting[1]!.getAttribute("href")).toBe("/c/acme/callbacks");
    expect(screen.getByText("Called by two or more campaigns in 7 days.")).toBeTruthy();
    // No press that would do nothing: there is no setting to leave people out yet.
    expect(screen.queryByRole("button", { name: /Leave them out/ })).toBeNull();
    await expectNoA11yViolations(container, "FollowUpsCard+ContactHealthCard");
  });
});

describe("Cost per result", () => {
  it("is refused, not dashed, for a role without billing", async () => {
    const compare = {
      ...FULL_ACCOUNT_IMPROVE.compare,
      total_spend_inr: null,
      total_cost_per_goal_inr: null,
      holders: FULL_ACCOUNT_IMPROVE.compare.holders.map((h) => ({ ...h, spend_inr: null, cost_per_goal_inr: null })),
    };
    await render(<CostPerResultCard />, account({ compare }));
    expect(await screen.findByText("Only people who can see billing see what results cost.")).toBeTruthy();
  });

  it("says nothing was spent", async () => {
    await render(<CostPerResultCard />, account());
    expect(await screen.findByText("Nothing spent on calls in the last 30 days.")).toBeTruthy();
  });

  it("ranks the cheapest goal first, in rupees under the display rule", async () => {
    const { container } = await render(<CostPerResultCard />, account({ compare: FULL_ACCOUNT_IMPROVE.compare }));
    const rows = within(await screen.findByRole("list", { name: "Cost per result" })).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Rytu Khata installs"),
      expect.stringContaining("Renewals"),
      expect.stringContaining("no goal yet"),
    ]);
    expect(rows[0]!.textContent).toContain("₹10");
    // The display rule rounds rupees for reading (`numberDisplay.formatINR`).
    expect(screen.getByText("₹17")).toBeTruthy();
    await expectNoA11yViolations(container, "CostPerResultCard");
  });
});

describe("Pip's fixes", () => {
  it("says nothing changed on its own", async () => {
    await render(<PipFixesCard slug="acme" />, account());
    expect(await screen.findByText("No changes made on their own in the last 30 days.")).toBeTruthy();
  });

  it("lists each change with a link to its holder's versions", async () => {
    const { container } = await render(<PipFixesCard slug="acme" />, account({ fixes: FULL_ACCOUNT_IMPROVE.fixes }));
    const rows = within(await screen.findByRole("list", { name: "Pip's fixes" })).getAllByRole("listitem");
    expect(rows[0]!.textContent).toContain("Repaired lines the script checks found");
    expect(rows[1]!.textContent).toContain("Set the calling hours to 10:00 to 13:00");
    expect(within(rows[0]!).getByRole("link").getAttribute("href")).toBe("/c/acme/campaigns/camp-other");
    expect(within(rows[2]!).getByRole("link").getAttribute("href")).toBe("/c/acme/inbound/line-1#line-script");
    await expectNoA11yViolations(container, "PipFixesCard");
  });
});

describe("the page", () => {
  it("draws every section from one read and passes axe", async () => {
    const { calls, container } = await renderClientPage(<ImprovePage params={Promise.resolve({ slug: "acme" })} />, {
      "/v1/me": OWNER,
      [IMPROVE]: FULL_ACCOUNT_IMPROVE,
      [LATEST]: [WEEKLY_SUMMARY],
      "/v1/teach/questions": { items: [CALLER_QUESTION], open_count: 1 },
    });
    expect(await screen.findByText(WEEKLY_SUMMARY.paragraph)).toBeTruthy();
    for (const title of [
      "Compare your campaigns",
      "Number health",
      "Mistakes across campaigns",
      "Questions no agent could answer",
      "Cost per result",
      "People waiting on you",
      "Contact list health",
      "Pip's fixes",
    ]) {
      expect(await screen.findByRole("heading", { level: 2, name: title })).toBeTruthy();
    }
    expect(calls.filter((c) => c.method === "GET" && c.path === IMPROVE)).toHaveLength(1);
    await expectNoA11yViolations(container, "ImprovePage");
  });
});

describe("the links down", () => {
  it("open a campaign on its Improve tab", async () => {
    window.history.pushState({}, "", `/c/acme/campaigns/${FIXTURE_CAMPAIGN_ID}?tab=improve`);
    await renderClientPage(campaignPage(), {
      "/v1/me": OWNER,
      ...detailRoutes(),
      [`/v1/campaigns/${FIXTURE_CAMPAIGN_ID}`]: progressFixture(),
      [`/v1/campaigns/${FIXTURE_CAMPAIGN_ID}/launch-check`]: { ready: true, blockers: [] },
    });
    const tab = await screen.findByRole("tab", { name: "Improve" });
    expect(tab.getAttribute("aria-selected")).toBe("true");
  });
});
