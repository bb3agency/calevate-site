import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Actions } from "@/app/c/[slug]/agents/actions/Actions";
import { costFigure } from "@/app/c/[slug]/CostPerLead";
import { teachPrompts } from "@/app/c/[slug]/knowledge/TeachBox";
import type { ActionsSettings } from "@/lib/api/actions";
import type { BusinessCopy } from "@/lib/api/businessCopy";
import type { CostWindow } from "@/lib/api/proof";
import { useClientSession } from "@/lib/api/session";
import {
  UNKNOWN_CAPABILITIES,
  businessLanguage,
  callersWord,
  capabilitiesJudged,
  capabilitiesOf,
  goAheadLabel,
  leadWords,
  quotesPrices,
} from "@/lib/businessCapabilities";
import { suggestedQuestions } from "@/lib/copilot/suggestions";

import { NO_BUSINESS_COPY, renderClientPage } from "./harness";
import { OWNER_ME } from "./fixtures/sharedReads";

/**
 * The client screens follow the business's capability profile (`GET /v1/business-copy`):
 * a judged "no" hides or rewords what does not fit, and "not judged yet" keeps everything.
 * Three businesses: an app that calls its registered users to help them and sells nothing
 * (every capability false), a shop (every capability true), and one not judged yet.
 */

function judged(applies: boolean): BusinessCopy["capabilities"] {
  const one = { reason: "judged from the business details", applies };
  return {
    takes_bookings: one,
    takes_orders: one,
    quotes_prices: one,
    has_premises: one,
    sells: one,
    health_business: one,
  };
}

/** An app that rings its registered users to help them: no bookings, orders, prices or premises. */
const HELPS_USERS: BusinessCopy = {
  ...NO_BUSINESS_COPY,
  capabilities: judged(false),
  caller_noun: "User",
  objections: [{ caller_says: "I am busy right now.", how_to_answer: "Offer to call back at a better time." }],
  pip_questions: ["which users still need help finishing setup?"],
  language: "hi-IN",
};

const SHOP: BusinessCopy = {
  ...NO_BUSINESS_COPY,
  capabilities: judged(true),
  caller_noun: "customer",
  pip_questions: [],
};

const UNKNOWN: BusinessCopy = NO_BUSINESS_COPY;

describe("the capability profile, read", () => {
  it("is unknown before any copy, and keeps every switch and question then", () => {
    expect(capabilitiesOf(undefined)).toEqual(UNKNOWN_CAPABILITIES);
    const unknown = capabilitiesOf(UNKNOWN);
    expect(goAheadLabel(unknown)).toBe("Take bookings and orders");
    expect(quotesPrices(unknown)).toBe(true);
    expect(quotesPrices(unknown, undefined)).toBe(true);
    expect(callersWord(unknown, "customers")).toBe("customers");
    expect(suggestedQuestions("/c/x/agents/a1", unknown)).toContain("How do I let it take bookings?");
    expect(suggestedQuestions("/c/x/knowledge", unknown)).toContain("How do I add my price list?");
  });

  it("names the go-ahead switch for what the business takes, or drops it", () => {
    expect(goAheadLabel(capabilitiesOf(SHOP))).toBe("Take bookings and orders");
    expect(goAheadLabel(capabilitiesOf(HELPS_USERS))).toBeNull();
    const ordersOnly = { ...capabilitiesOf(SHOP), takesBookings: false };
    expect(goAheadLabel(ordersOnly)).toBe("Take orders");
    const visitsOnly = { ...capabilitiesOf(SHOP), takesOrders: false, bookingJobTitle: "Book site visits" };
    expect(goAheadLabel(visitsOnly)).toBe("Book site visits");
  });

  it("drops prices when the copy says no prices, or the profile has no price label", () => {
    expect(quotesPrices(capabilitiesOf(HELPS_USERS), "Price")).toBe(false);
    expect(quotesPrices(capabilitiesOf(SHOP), null)).toBe(false);
    expect(quotesPrices(capabilitiesOf(SHOP), "Rate")).toBe(true);
  });

  it("calls the callers what the business calls them", () => {
    expect(callersWord(capabilitiesOf(HELPS_USERS), "customers")).toBe("users");
    expect(callersWord({ ...UNKNOWN_CAPABILITIES, callerNoun: "family" })).toBe("families");
    expect(callersWord({ ...UNKNOWN_CAPABILITIES, callerNoun: "class coach" })).toBe("class coaches");
  });

  it("starts in the business's own language when the server offers it, else in the account's first", () => {
    const offered = ["te-IN", "hi-IN", "en-IN"] as const;
    expect(businessLanguage("hi-IN", offered)).toBe("hi-IN");
    expect(businessLanguage("en", offered)).toBe("en-IN");
    expect(businessLanguage(null, offered)).toBe("te-IN");
    expect(businessLanguage("fr-FR", offered)).toBe("te-IN");
    // Tamil is not offered to this account, so it is not started in.
    expect(businessLanguage("ta-IN", offered)).toBe("te-IN");
  });

  it("starts a Tamil business in Tamil once the server offers it, and follows the server's default", () => {
    expect(businessLanguage("ta", ["te-IN", "hi-IN", "en-IN", "ta-IN"])).toBe("ta-IN");
    expect(businessLanguage(null, ["ta-IN", "en-IN"])).toBe("ta-IN");
    expect(businessLanguage(null, [])).toBeNull();
  });
});

describe("the lead ladder's words (G1-1)", () => {
  it("says lead and hot lead only for a business judged to sell", () => {
    expect(leadWords(capabilitiesOf(SHOP)).hotLead).toBe("hot lead");
    expect(leadWords(capabilitiesOf(SHOP)).leads).toBe("leads");
  });

  it("names the callers neutrally for one that sells nothing, and for one not judged yet", () => {
    expect(leadWords(capabilitiesOf(HELPS_USERS))).toEqual({
      lead: "interested user",
      leads: "interested users",
      newLead: "interested user",
      hotLead: "most interested user",
      hotLeads: "most interested users",
    });
    expect(leadWords(capabilitiesOf(UNKNOWN)).hotLeads).toBe("most interested callers");
  });

  it("knows whether the business has been judged yet", () => {
    expect(capabilitiesJudged(capabilitiesOf(UNKNOWN))).toBe(false);
    expect(capabilitiesJudged(capabilitiesOf(SHOP))).toBe(true);
  });
});

describe("Pip's empty-panel questions follow the business", () => {
  it("asks no booking or price question of a business that has neither, and asks its own", () => {
    const users = capabilitiesOf(HELPS_USERS);
    const agent = suggestedQuestions("/c/x/agents/a1", users);
    expect(agent).not.toContain("How do I let it take bookings?");
    expect(agent).toContain("How do I change what it may do?");
    expect(suggestedQuestions("/c/x/knowledge", users)).not.toContain("How do I add my price list?");
    expect(suggestedQuestions("/c/x", users)).toContain("Which users still need help finishing setup?");
    for (const route of ["/c/x", "/c/x/leads", "/c/x/agents/a1", "/c/x/knowledge"]) {
      const questions = suggestedQuestions(route, users);
      expect(questions.length).toBe(3);
      for (const q of questions) expect(q).toMatch(/^[A-Z]/);
    }
  });

  it("keeps the booking and price questions for a shop", () => {
    const shop = capabilitiesOf(SHOP);
    expect(suggestedQuestions("/c/x/agents/a1", shop)).toContain("How do I let it take bookings?");
    expect(suggestedQuestions("/c/x/knowledge", shop)).toContain("How do I add my price list?");
    expect(suggestedQuestions("/c/x", shop)).toEqual(suggestedQuestions("/c/x"));
  });
});

describe("the home screen's cost figure", () => {
  const WEEK: CostWindow = {
    days: 7,
    from_date: "2026-10-29",
    to_date: "2026-11-04",
    spent_inr: "120.00",
    answered_calls: 8,
    leads: 4,
    goals_reached: 2,
    per_answered_call_inr: "15.00",
    per_lead_inr: "30.00",
    per_goal_inr: "60.00",
  };

  it("prices a business that sells nothing by its goal, or by answered call, never by lead", () => {
    const users = capabilitiesOf(HELPS_USERS);
    expect(costFigure(WEEK, ["Setup finished"], users).label).toBe("Cost per Setup finished, 7 days");
    expect(costFigure(WEEK, [], users).label).toBe("Cost per answered call, 7 days");
    expect(costFigure(WEEK, [], users).count).toBe("8 answered calls");
  });

  it("keeps cost per lead for a shop and for a business not judged yet", () => {
    expect(costFigure(WEEK, ["Visit booked"], capabilitiesOf(SHOP)).label).toBe("Cost per lead, 7 days");
    expect(costFigure(WEEK, [], capabilitiesOf(UNKNOWN)).count).toBe("4 leads");
  });
});
/* ---------------------------------------------------------------- the actions catalogue */

const NO_ACTIONS: ActionsSettings = { api_actions_enabled: false, calendar_available: true, tools: [] };

function ActionsPanel() {
  const session = useClientSession();
  return <Actions agentId="agent-1" session={session} />;
}

function actionRoutes(copy: BusinessCopy) {
  return {
    "/v1/me": OWNER_ME,
    "/v1/agents/agent-1/actions": NO_ACTIONS,
    "/v1/integrations/credentials": [],
    "/v1/integrations/connections/status": {
      google_calendar: false,
      google_sheets: false,
      zoho_crm: false,
      hubspot: false,
      sheets_share_with: null,
    },
    "/v1/business-copy": copy,
  };
}

const offered = () =>
  Array.from(
    screen.getByRole("list", { name: "Things your agent can do" }).querySelectorAll("button .font-medium"),
  ).map((t) => t.textContent ?? "");

async function offeredJobs(copy: BusinessCopy): Promise<string[]> {
  const { calls } = await renderClientPage(<ActionsPanel />, actionRoutes(copy));
  await screen.findByRole("list", { name: "Things your agent can do" });
  await waitFor(() => expect(calls.some((c) => c.path === "/v1/business-copy")).toBe(true));
  return offered();
}

describe("the booking job", () => {
  it("is not offered to a business that takes no bookings", async () => {
    await renderClientPage(<ActionsPanel />, actionRoutes(HELPS_USERS));
    await screen.findByRole("list", { name: "Things your agent can do" });
    // The chooser is drawn before the copy is read; the job leaves once it is.
    await waitFor(() => expect(offered()).not.toContain("Take bookings"));
    expect(offered()).toContain("Know who is calling");
  });

  it("is offered to a shop and to a business not judged yet", async () => {
    expect(await offeredJobs(SHOP)).toContain("Take bookings");
  });

  it("is offered while the profile is unknown", async () => {
    expect(await offeredJobs(UNKNOWN)).toContain("Take bookings");
  });
});

describe("the teach box's prompts (G6-7)", () => {
  it("offers prices, hours and delivery only to a business they fit", () => {
    const shop = teachPrompts(capabilitiesOf(SHOP));
    expect(shop.starters).toContain("Our prices: ");
    expect(shop.placeholder).toBe("Prices, timings, where you deliver, what never to promise…");

    const app = teachPrompts(capabilitiesOf(HELPS_USERS));
    expect(app.starters).not.toContain("Our prices: ");
    expect(app.starters).not.toContain("We are open ");
    expect(app.placeholder).toBe("What you offer, what never to promise…");

    // Unknown keeps prices and hours on offer and names no delivery.
    const unknown = teachPrompts(capabilitiesOf(UNKNOWN));
    expect(unknown.starters).toContain("Our prices: ");
    expect(unknown.placeholder).toBe("Prices, timings, what never to promise…");
  });
});