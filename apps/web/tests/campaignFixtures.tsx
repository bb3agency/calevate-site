import CampaignPage from "@/app/c/[slug]/campaigns/[campaignId]/page";
import CampaignsPage from "@/app/c/[slug]/campaigns/page";
import NewCampaignPage from "@/app/c/[slug]/campaigns/new/page";
import type {
  CampaignPage as CampaignPageOut,
  CampaignProgress,
  CampaignResults,
  CampaignSummary,
  ContactResults,
} from "@/lib/api/campaigns";
import type {
  CampaignInsights,
  JobNotes,
  CampaignSettings,
  CampaignWorkspace,
} from "@/lib/api/campaignWorkspace";
import type { ScriptVersions } from "@/lib/api/scriptVersions";

import { fireEvent, screen, within } from "@testing-library/react";

import { formatDateLong, todayIST } from "@/components/arc/ist-dates";

import { EMPTY_DIAGNOSIS, GIVE_TIME_ON } from "./fixtures/diagnosis";
import { jobTeamAlert } from "./fixtures/sharedReads";
import type { Routes } from "./harness";

/**
 * The campaign screens' shared wire fixtures (D-773): one campaign as the detail page
 * reads it, the paged list, and the reads every detail render makes. A suite overrides
 * only the fields its premise is about.
 */

export const SLUG = "acme";
export const FIXTURE_CAMPAIGN_ID = "0192f0aa-2222-7000-8000-000000000001";
export const FIXTURE_AGENT_ID = "0192f0aa-3333-7000-8000-000000000002";

export function progressFixture(over: Partial<CampaignProgress> = {}): CampaignProgress {
  return {
    id: FIXTURE_CAMPAIGN_ID,
    name: "Diwali offer",
    classification: "promotional",
    agent_id: FIXTURE_AGENT_ID,
    agent_name: "Outbound follow-up",
    purpose: "Our Diwali offer on service plans",
    goal: "They book a service visit",
    number_id: null,
    consent_source: null,
    consent_collected_at: null,
    created_at: "2026-08-10T06:00:00Z",
    retry_policy: { max_attempts: 3, gaps_minutes: [30, 120], spread: true },
    pause_reason: null,
    complaint_review_required: false,
    complaint_reviewed_at: null,
    not_calling: [],
    waiting_for_calling_hours: false,
    effective_concurrency: 3,
    status: "draft",
    launched_at: null,
    concurrency: 3,
    contacts: {},
    total: 0,
    retries_waiting: 0,
    next_retry_at: null,
    ...over,
  };
}

const NO_OUTCOMES = {
  connected: 0,
  no_answer: 0,
  busy: 0,
  voicemail: 0,
  failed: 0,
  do_not_call: 0,
  calling: 0,
  not_called: 0,
};

export function contactsFixture(over: Partial<ContactResults> = {}): ContactResults {
  return { items: [], total: 0, counts: { ...NO_OUTCOMES }, included: 0, everyone: 0, ...over };
}

export function resultsFixture(over: Partial<CampaignResults> = {}): CampaignResults {
  return {
    contacts: 0,
    outcomes: { ...NO_OUTCOMES },
    tried: 0,
    pickup_rate: null,
    calls: 0,
    connected_calls: 0,
    people_answered: 0,
    average_call_s: null,
    talk_seconds: 0,
    outcome_tags: {},
    sentiment: {},
    leads: 0,
    hot_leads: 0,
    interested_leads: 0,
    recent_leads: [],
    opt_outs: 0,
    credits_spent_inr: "0.00",
    business_outcomes: [],
    business_outcomes_unset: 0,
    fields: [],
    ...over,
  };
}

/** The people table's page size (`DraftPeople`, 0.4.37). */
export const CONTACTS_PAGE = 10;

/** A page of the people table, as the detail page asks for it. */
export const contactsPath = (id: string = FIXTURE_CAMPAIGN_ID, offset = 0) =>
  `/v1/campaigns/${id}/contacts?limit=${CONTACTS_PAGE}&offset=${offset}`;

/**
 * Picks `iso` in the kit `DatePicker` labelled `label`: opens it, steps month by month
 * towards the day (from today, where an empty picker opens), and presses the day.
 */
export async function pickDate(label: string, iso: string): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: label }));
  const day = new RegExp(`^${formatDateLong(iso)}`);
  const step = iso < todayIST() ? "Previous month" : "Next month";
  const grid = await screen.findByRole("grid");
  // Role queries walk the whole accessibility tree, so on a full campaign page dozens of
  // month steps over `screen` take seconds; the calendar's own panel holds every control used.
  const panel = within((grid.closest('[role="dialog"]') as HTMLElement | null) ?? document.body);
  for (let moves = 0; moves < 240; moves += 1) {
    const cell = panel.queryByRole("button", { name: day });
    if (cell) {
      fireEvent.click(cell);
      return;
    }
    fireEvent.click(panel.getByRole("button", { name: step }));
  }
  throw new Error(`${iso} never appeared in the ${label} calendar`);
}

/** Opens one of a campaign's tabs (Script, People, Checks, Progress, ...), whatever count its label carries. */
export async function openTab(name: string): Promise<void> {
  const label = new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}( \\(|$)`);
  fireEvent.click(await screen.findByRole("tab", { name: label }));
}

/** A launched campaign's day-by-day read (`CampaignTimeline`): the server's whole year. */
export const timelinePath = (id: string = FIXTURE_CAMPAIGN_ID) =>
  `/v1/analytics/campaigns?days=366&campaign_id=${id}`;

/** `GET /v1/campaigns/{id}/workspace`: a main task saved, no sources, no script yet. */
export function workspaceFixture(over: Partial<CampaignWorkspace> = {}): CampaignWorkspace {
  return {
    campaign_id: FIXTURE_CAMPAIGN_ID,
    agent_id: FIXTURE_AGENT_ID,
    status: "draft",
    main_task: "Tell customers about our Diwali offer on service plans.",
    source_ids: [],
    proposal: null,
    script: null,
    script_live_version: null,
    step_outcomes_pending: false,
    step_outcomes_by_owner: false,
    ...over,
  };
}

/** `GET .../script/versions` (D-1039): one version, the owner's own, which is the script now. */
export function scriptVersionsFixture(over: Partial<ScriptVersions> = {}): ScriptVersions {
  return {
    current_version_id: "0192f0aa-9999-7000-8000-000000000001",
    put_back: { version: null, unavailable: "already_current" },
    versions: [
      {
        id: "0192f0aa-9999-7000-8000-000000000001",
        author: "owner",
        owner_made: true,
        reason: "You saved the script.",
        created_at: "2026-11-23T10:40:00Z",
      },
    ],
    ...over,
  };
}

/** `GET /v1/campaigns/{id}/insights` before any call: no hours, no second opening. */
export function insightsFixture(over: Partial<CampaignInsights> = {}): CampaignInsights {
  return {
    best_hours: {
      state: "empty",
      best: null,
      blocks: [],
      hours: [],
      min_people_per_block: 50,
      chance_needed: 0.9875,
      calling_hours: null,
      applied: null,
      auto: false,
    },
    retry: { spread: true, max_attempts: 3, gaps_minutes: [30, 120] },
    opening: {
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
    },
    ...over,
  };
}

/** `GET /v1/campaigns/{id}/settings` (D-994, D-1027): the agent's languages, none set by the campaign. */
export function settingsFixture(over: Partial<CampaignSettings> = {}): CampaignSettings {
  return {
    agent_id: FIXTURE_AGENT_ID,
    agent_name: "Outbound follow-up",
    applied_now: false,
    defaults: { language_primary: "te-IN", languages_extra: [] },
    offered_languages: ["te-IN", "hi-IN", "en-IN"],
    example_limits: { turns_min: 3, turns_max: 5, line_max: 200 },
    overrides: {},
    ...over,
  };
}

/** `GET /v1/campaigns/{id}/notes` (D-1028): an empty list. */
export function notesFixture(over: Partial<JobNotes> = {}): JobNotes {
  return {
    agent_id: FIXTURE_AGENT_ID,
    agent_name: "Outbound follow-up",
    fields: [],
    core_fields: [],
    digest: "empty",
    applied_now: false,
    ...over,
  };
}

/** The reads every render of one campaign makes, besides the progress and launch check. */
export function detailRoutes(id: string = FIXTURE_CAMPAIGN_ID): Routes {
  return {
    [contactsPath(id)]: contactsFixture(),
    [`/v1/campaigns/${id}/results`]: resultsFixture(),
    [`/v1/campaigns/${id}/workspace`]: workspaceFixture({ campaign_id: id }),
    [`/v1/campaigns/${id}/insights`]: insightsFixture(),
    // The Improve tab's Questions to answer, and its count on the tab: none yet.
    [`/v1/campaigns/${id}/questions`]: [],
    // The Improve tab's Diagnose readings: no calls yet.
    [`/v1/campaigns/${id}/diagnosis`]: EMPTY_DIAGNOSIS,
    [`/v1/campaigns/${id}/give-callers-time`]: GIVE_TIME_ON,
    // The Improve tab's WhatsApp follow-up card: connected, nothing set up yet.
    [`/v1/campaigns/${id}/whatsapp-follow-up`]: {
      phase: "none",
      connected: true,
      failure: null,
      made: null,
    },
    [`/v1/campaigns/${id}/settings`]: settingsFixture(),
    [`/v1/campaigns/${id}/notes`]: notesFixture(),
    [`/v1/campaigns/${id}/team-alert`]: jobTeamAlert("campaign", id),
    // The Test call section's list of calls made from the campaign: none yet.
    [`/v1/campaigns/${id}/test-calls`]: [],
    // The account's saved test numbers, offered under Test call: none yet.
    [`/v1/campaigns/${id}/test-numbers`]: { numbers: [] },
    // Other call settings' number it calls from: none bought yet.
    "/v1/campaigns/numbers": [],
    // Other call settings' ceiling on calls at once: the account's call lines.
    "/v1/call-lines": { call_lines: 3, in_progress: 0, max_lines: 10, on_trial: false, being_applied: false },
    // The Sources fold's pick list: What your agents know, empty.
    "/v1/kb/notes": { notes: [] },
    "/v1/kb/uploads": [],
    // The Set up tab's agent picker, for every status.
    "/v1/agents": [],
    ...dltRegistrationRoute(),
    [timelinePath(id)]: {
      window: { days: 366, from_date: "2025-10-25", to_date: "2026-10-24", timezone: "Asia/Kolkata" },
      campaigns: [],
    },
  };
}

export function pageFixture(items: CampaignSummary[]): CampaignPageOut {
  const counts: Record<string, number> = {
    draft: 0,
    scheduled: 0,
    running: 0,
    paused: 0,
    completed: 0,
    cancelled: 0,
  };
  for (const item of items) counts[item.status] = (counts[item.status] ?? 0) + 1;
  return { items, total: items.length, status_counts: counts, archived_total: 0 };
}

/** The list page's first read, unfiltered. */
export const LIST_PATH = "/v1/campaigns/page?limit=25&offset=0";

export function campaignPage(id: string = FIXTURE_CAMPAIGN_ID) {
  return <CampaignPage params={Promise.resolve({ slug: SLUG, campaignId: id })} />;
}

export function listPage() {
  return <CampaignsPage params={Promise.resolve({ slug: SLUG })} />;
}

export function newCampaignPage() {
  return <NewCampaignPage params={Promise.resolve({ slug: SLUG })} />;
}

/**
 * `GET /v1/compliance/dlt-registration` as the campaign form reads it: whether Calevate's
 * telemarketer registration is live, which decides whether Promotional is offered (D-838).
 */
export function dltRegistrationRoute(tmActive = false): Routes {
  return {
    "/v1/compliance/dlt-registration": {
      recorded: false,
      status: null,
      tm_link_status: null,
      pe_id: null,
      entity_name: null,
      registered_at: null,
      verified_at: null,
      is_active: false,
      calevate_tm_id: tmActive ? "1701000000000000001" : null,
      calevate_tm_active: tmActive,
    },
  };
}
