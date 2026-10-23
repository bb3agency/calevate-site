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

import { fireEvent, screen } from "@testing-library/react";

import { formatDateLong, todayIST } from "@/components/arc/ist-dates";

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
    number_id: null,
    consent_source: null,
    consent_collected_at: null,
    created_at: "2026-08-10T06:00:00Z",
    retry_policy: { max_attempts: 3, gaps_minutes: [30, 120] },
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
  return { items: [], total: 0, counts: { ...NO_OUTCOMES }, ...over };
}

export function resultsFixture(over: Partial<CampaignResults> = {}): CampaignResults {
  return {
    contacts: 0,
    outcomes: { ...NO_OUTCOMES },
    tried: 0,
    pickup_rate: null,
    calls: 0,
    connected_calls: 0,
    average_call_s: null,
    talk_seconds: 0,
    outcome_tags: {},
    sentiment: {},
    leads: 0,
    hot_leads: 0,
    recent_leads: [],
    opt_outs: 0,
    credits_spent_inr: "0.00",
    ...over,
  };
}

/** The first page of the people table, as the detail page asks for it. */
export const contactsPath = (id: string = FIXTURE_CAMPAIGN_ID) =>
  `/v1/campaigns/${id}/contacts?limit=50&offset=0`;

/**
 * Picks `iso` in the kit `DatePicker` labelled `label`: opens it, steps month by month
 * towards the day (from today, where an empty picker opens), and presses the day.
 */
export async function pickDate(label: string, iso: string): Promise<void> {
  fireEvent.click(screen.getByRole("button", { name: label }));
  const day = new RegExp(`^${formatDateLong(iso)}`);
  const step = iso < todayIST() ? "Previous month" : "Next month";
  await screen.findByRole("grid");
  for (let moves = 0; moves < 240; moves += 1) {
    const cell = screen.queryByRole("button", { name: day });
    if (cell) {
      fireEvent.click(cell);
      return;
    }
    fireEvent.click(screen.getByRole("button", { name: step }));
  }
  throw new Error(`${iso} never appeared in the ${label} calendar`);
}

/** A launched campaign's day-by-day read (`CampaignTimeline`): the server's whole year. */
export const timelinePath = (id: string = FIXTURE_CAMPAIGN_ID) =>
  `/v1/analytics/campaigns?days=366&campaign_id=${id}`;

/** The reads every render of one campaign makes, besides the progress and launch check. */
export function detailRoutes(id: string = FIXTURE_CAMPAIGN_ID): Routes {
  return {
    [contactsPath(id)]: contactsFixture(),
    [`/v1/campaigns/${id}/results`]: resultsFixture(),
    "/v1/campaigns/lead-pool": { matching: 0, limit: 5000 },
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
  return { items, total: items.length, status_counts: counts };
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
