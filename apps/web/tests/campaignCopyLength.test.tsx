import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  BLOCKER_COPY,
  LIST_PROVENANCE_COPY,
  OWNER_BADGE,
  PAUSE_COPY,
  blockerDestination,
} from "@/app/c/[slug]/campaigns/blockerCopy";
import { campaignRun, runSentence } from "@/app/c/[slug]/campaigns/campaignProgress";
import { CONSENT_SOURCES } from "@/app/c/[slug]/campaigns/choices";
import { FILE_HINT } from "@/app/c/[slug]/campaigns/ContactEditor";
import { windowRefusal } from "@/app/c/[slug]/campaigns/NewCampaignFlow";
import { REPEAT_SKIPS, START_GIVES_UP, fireTimeLine } from "@/app/c/[slug]/campaigns/scheduleCopy";
import type { CampaignProgress, CampaignSummary, LaunchCheck } from "@/lib/api/campaigns";
import type { Me } from "@/lib/api/client";

import {
  FIXTURE_CAMPAIGN_ID,
  LIST_PATH,
  campaignPage,
  detailRoutes,
  dltRegistrationRoute,
  listPage,
  newCampaignPage,
  pageFixture,
  progressFixture,
} from "./campaignFixtures";
import { renderClientPage } from "./harness";

/**
 * BUTTONS, NOT PARAGRAPHS (founder, 28 Oct 2026): every line a client reads by default on
 * the campaign screens is short. A reason a reader wants once sits behind "Why?" or an
 * info button, and is not rendered until asked for, so it is not counted here.
 *
 * Two halves: the copy tables the screens are built from, and the rendered default view of
 * the list and of one campaign in its main states. ~60 characters is about 8 words, which
 * is one line on a 375px phone at body size.
 */
const MAX = 60;

const tooLong = (lines: string[]) => lines.filter((line) => line.length > MAX);

describe("the campaign copy tables", () => {
  it("say each blocker in one short line, with the long reason behind Why?", () => {
    const lines = Object.values(BLOCKER_COPY).map((note) => note.text);
    expect(tooLong(lines)).toEqual([]);
    const at = (path: string) => path;
    const labels = Object.keys(BLOCKER_COPY)
      .map((rule) => blockerDestination(rule, at, "id")?.label)
      .filter((label): label is string => label !== undefined);
    expect(tooLong(labels)).toEqual([]);
  });

  it("keep badges, pause notes, list sources and schedule warnings short", () => {
    const lines = [
      ...Object.values(OWNER_BADGE),
      ...Object.values(LIST_PROVENANCE_COPY).map((copy) => copy.badge),
      ...Object.values(PAUSE_COPY).flatMap((copy) => [copy.title, copy.text]),
      ...CONSENT_SOURCES.flatMap((source) => [source.label, source.hint]),
      fireTimeLine("start", "arming"),
      fireTimeLine("repeat", "arming"),
      fireTimeLine("start", "armed"),
      fireTimeLine("repeat", "armed"),
      START_GIVES_UP,
      REPEAT_SKIPS,
      FILE_HINT,
      windowRefusal("18:00", "10:00") ?? "",
      windowRefusal("08:00", "10:00") ?? "",
    ];
    expect(tooLong(lines)).toEqual([]);
  });

  it("say what a launched campaign is doing in one short line", () => {
    const states: Partial<CampaignProgress>[] = [
      { status: "completed" },
      { status: "cancelled", total: 4000, contacts: { pending: 1234 } },
      { status: "paused" },
      { status: "running", not_calling: [{ rule: "no_credits", reason: "x" }] },
      { status: "running", waiting_for_calling_hours: true, calling_hours: { start: "10:00", end: "18:00" } },
      { status: "running", contacts: { dialing: 12 }, total: 400 },
      { status: "running" },
    ];
    const lines = states.map((over) => {
      const progress = progressFixture(over);
      return runSentence(progress, campaignRun(progress));
    });
    expect(tooLong(lines)).toEqual([]);
  });
});

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["leads:read", "leads:dispatch"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

/**
 * Every line of text the page shows by default: the innermost block-level elements, with
 * a closed disclosure's body left out (it is not shown until opened).
 */
const LINE = "p, li, label, button, a, h1, h2, h3, h4, dt, dd, legend, th, td, summary, span.block";

/** An element's text as a sighted reader sees it: screen-reader-only words left out. */
function seenText(element: HTMLElement): string {
  const copy = element.cloneNode(true) as HTMLElement;
  copy.querySelectorAll(".sr-only").forEach((hidden) => hidden.remove());
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}

function visibleLines(root: HTMLElement): string[] {
  return Array.from(root.querySelectorAll<HTMLElement>(LINE))
    .filter((element) => !element.querySelector(LINE))
    .filter((element) => !element.closest(".sr-only"))
    .filter((element) => {
      const closed = element.closest("details:not([open])");
      return !closed || element.closest("summary") !== null;
    })
    .map(seenText)
    .filter((text) => text.length > 0);
}

const BLOCKERS: LaunchCheck = {
  ready: false,
  blockers: Object.keys(BLOCKER_COPY).map((rule) => ({ rule, reason: "Server reason." })),
};

function detail(progress: CampaignProgress, check: LaunchCheck = BLOCKERS) {
  return {
    "/v1/me": ME,
    ...detailRoutes(),
    "/v1/agents": [],
    "/v1/campaigns/numbers": [],
    "/v1/campaigns/templates": [],
    [`/v1/campaigns/${FIXTURE_CAMPAIGN_ID}`]: progress,
    [`/v1/campaigns/${FIXTURE_CAMPAIGN_ID}/launch-check`]: check,
  };
}

const ROW: CampaignSummary = {
  id: FIXTURE_CAMPAIGN_ID,
  name: "Diwali offer",
  status: "draft",
  classification: "service",
  contacts: 120,
  connected: 0,
  launched_at: null,
  created_at: "2026-08-10T06:00:00Z",
  consent_provenance_blocker: "consent_provenance_missing",
  pause_reason: null,
};

describe("the campaign screens' default view", () => {
  it("lists campaigns in short lines", async () => {
    const { container } = await renderClientPage(listPage(), {
      "/v1/me": ME,
      [LIST_PATH]: pageFixture([
        ROW,
        { ...ROW, id: "b", name: "Fee reminder", status: "paused", pause_reason: "out_of_credit", consent_provenance_blocker: null },
        { ...ROW, id: "c", name: "Admissions", status: "running", connected: 40, consent_provenance_blocker: null },
      ]),
    });
    await screen.findByRole("link", { name: "Diwali offer" });
    expect(tooLong(visibleLines(container))).toEqual([]);
  });

  it("shows a blocked draft's checklist in short lines, every blocker at once", async () => {
    const { container } = await renderClientPage(campaignPage(), detail(progressFixture()));
    await screen.findByText("Before you launch");
    await screen.findByText("Add the people to call.");
    expect(tooLong(visibleLines(container))).toEqual([]);
  });

  it("starts a new campaign in short lines", async () => {
    const { container } = await renderClientPage(newCampaignPage(), {
      "/v1/me": ME,
      "/v1/agents": [],
      "/v1/campaigns/numbers": [],
      "/v1/campaigns/templates": [],
      ...dltRegistrationRoute(true),
    });
    await screen.findByText("No agent is set up yet.");
    expect(screen.getByRole("link", { name: "Create an agent" })).toBeTruthy();
    expect(tooLong(visibleLines(container))).toEqual([]);
  });

  it("shows a running campaign that is not calling in short lines", async () => {
    const { container } = await renderClientPage(
      campaignPage(),
      detail(
        progressFixture({
          status: "running",
          launched_at: "2026-10-14T04:30:00Z",
          total: 120,
          contacts: { pending: 60, connected: 40, no_answer: 20 },
          not_calling: [
            { rule: "no_credits", reason: "x" },
            { rule: "national_dnd_scrub_missing", reason: "x" },
          ],
        }),
      ),
    );
    await screen.findByText("Not calling anyone right now");
    expect(tooLong(visibleLines(container))).toEqual([]);
  });
});
