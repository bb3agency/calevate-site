import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Actions } from "@/app/c/[slug]/agents/actions/Actions";
import { ScriptBuilder } from "@/app/c/[slug]/agents/[agentId]/script/ScriptBuilder";
import { costFigure } from "@/app/c/[slug]/CostPerLead";
import type { ActionsSettings } from "@/lib/api/actions";
import type { BusinessCopy } from "@/lib/api/businessCopy";
import type { CostWindow } from "@/lib/api/proof";
import { EMPTY_SCRIPT, type CallScript, type ScriptOut } from "@/lib/api/script";
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
import { businessProfileFixture, NEUTRAL_WORDING } from "./businessProfileFixture";
import { OWNER_ME, agentRow, settledPending } from "./fixtures/sharedReads";

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

  it("starts in the business's own language, and in the platform's when it has none this build speaks", () => {
    expect(businessLanguage("hi-IN")).toBe("hi-IN");
    expect(businessLanguage("en")).toBe("en-IN");
    expect(businessLanguage(null)).toBe("te-IN");
    expect(businessLanguage("fr-FR")).toBe("te-IN");
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

/* ---------------------------------------------------------------- the script screen */

const SCRIPT: CallScript = {
  ...EMPTY_SCRIPT,
  opening_line: "Hello.",
  business_line: "A business",
  identity: "You answer the phone.",
  goal: "Help the caller.",
  objections: [{ objection: "", response: "" }],
};

function scriptOut(): ScriptOut {
  return {
    script: SCRIPT,
    draft: null,
    stored_schema_version: 2,
    context: null,
    version: 1,
    is_freeform: false,
    has_pending: false,
    standard_variables: [],
  };
}

function scriptRoutes(copy: BusinessCopy, priceLabel: string | null = "Price") {
  return {
    "/v1/me": OWNER_ME,
    "/v1/agents/agent-1": agentRow(),
    "/v1/agents/agent-1/script": scriptOut(),
    "POST /v1/agents/agent-1/script/preview": { compiled: "", instructions_chars: 10, instructions_limit: 8000, native_steps: 0 },
    "/v1/agents/agent-1/script/proposed-rules": [],
    "/v1/agents/agent-1/pending": settledPending(),
    "/v1/agents/agent-1/script/proposal": { proposal: null },
    "/v1/business-profile": businessProfileFixture({ wording: { ...NEUTRAL_WORDING, price_label: priceLabel } }),
    "/v1/business-copy": copy,
  };
}

const scriptPage = (
  <ScriptBuilder agentId="agent-1" knowledgeHref="/c/acme/knowledge" trainingHref="/c/acme/agents/agent-1?section=training" />
);

describe("What it may do", () => {
  it("shows only the call back to a business with no prices, bookings or orders", async () => {
    await renderClientPage(scriptPage, scriptRoutes(HELPS_USERS));
    expect(await screen.findByRole("switch", { name: /Offer a call back/ })).toBeTruthy();
    // The prices and bookings switches stay away once the copy is read.
    await screen.findByPlaceholderText("I am busy right now.");
    expect(screen.queryByRole("switch", { name: /Tell callers prices/ })).toBeNull();
    expect(screen.queryByRole("switch", { name: /Take bookings|Take orders/ })).toBeNull();
    expect(screen.getByText(/Timings and answers, shared by all your agents/)).toBeTruthy();
  });

  it("shows all three switches to a shop", async () => {
    await renderClientPage(scriptPage, scriptRoutes(SHOP));
    expect(await screen.findByRole("switch", { name: /Tell callers prices/ })).toBeTruthy();
    expect(screen.getByRole("switch", { name: /Take bookings and orders/ })).toBeTruthy();
    expect(screen.getByRole("switch", { name: /Offer a call back/ })).toBeTruthy();
  });

  it("hides prices for a shop whose profile quotes none", async () => {
    await renderClientPage(scriptPage, scriptRoutes(SHOP, null));
    expect(await screen.findByRole("switch", { name: /Take bookings and orders/ })).toBeTruthy();
    await screen.findByText(/Timings and answers/);
    expect(screen.queryByRole("switch", { name: /Tell callers prices/ })).toBeNull();
  });

  it("keeps every switch while the business is not judged, with a neutral push-back example", async () => {
    await renderClientPage(scriptPage, scriptRoutes(UNKNOWN));
    expect(await screen.findByRole("switch", { name: /Tell callers prices/ })).toBeTruthy();
    expect(screen.getByRole("switch", { name: /Take bookings and orders/ })).toBeTruthy();
    expect(screen.getByPlaceholderText("I need to think about it.")).toBeTruthy();
    expect(screen.queryByPlaceholderText("It is too expensive.")).toBeNull();
  });

  it("offers Pip's price idea only where prices apply", async () => {
    await renderClientPage(scriptPage, scriptRoutes(HELPS_USERS));
    await screen.findByPlaceholderText("I am busy right now.");
    expect(screen.queryByRole("button", { name: /Price is too high/ })).toBeNull();
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
