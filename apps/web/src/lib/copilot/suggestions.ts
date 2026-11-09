/**
 * THREE QUESTIONS WORTH ASKING ON THIS SCREEN, shown in an empty assistant panel
 * (founder, REDESIGN-2) so a person sees what it is for before typing. Picked by the
 * screen's route, which is either a declared pattern (`/c/{slug}/calls/{callId}`) or the
 * fallback's masked path (`/c/:hidden/calls`), so both are read by segment position.
 *
 * Plain questions an owner would ask, neutral across trades; none promises an action the
 * assistant cannot take (every change still waits for the person where it must). A question
 * that fits only some businesses (bookings, a price list) is asked only where the business's
 * capability profile has not ruled it out, and the business's own question (`pip_questions`
 * in its copy) takes the last place on the screens about its calls.
 */

import type { BusinessCapabilities } from "@/lib/businessCapabilities";

type Screen =
  | "dashboard"
  | "attention"
  | "calls"
  | "call"
  | "leads"
  | "lead"
  | "agents"
  | "agent"
  | "first_agent"
  | "campaigns"
  | "integrations"
  | "billing"
  | "knowledge"
  | "other";

const BOOKINGS_QUESTION = "How do I let it take bookings?";
const PRICES_QUESTION = "How do I add my price list?";

const QUESTIONS: Record<Screen, readonly string[]> = {
  dashboard: ["What needs me today?", "How did calls go this week?", "Who should I call back first?"],
  attention: ["What needs me first?", "Why did a campaign pause?", "How do I teach an agent an answer?"],
  calls: ["Which calls still need someone?", "Summarise today's calls", "Who called more than once this week?"],
  call: ["What did this caller want?", "Should I call them back?", "What did the agent promise?"],
  leads: ["Who should I call back first?", "What are people asking for most?", "Show this week's new leads"],
  lead: ["What does this person want?", "When did we last speak to them?", "What should I do next?"],
  agents: ["Which agents are answering right now?", "What does each agent do?", "How do I test an agent?"],
  agent: ["Is this agent working right now?", "What does it say when it answers?", BOOKINGS_QUESTION],
  first_agent: ["Answer my calls", "Call new leads instantly", "Run calling campaigns"],
  campaigns: ["Which campaign is running?", "Why can't my campaign launch?", "How many people did we reach?"],
  integrations: ["What is connected?", "Why did a delivery fail?", "How do I send leads to my CRM?"],
  billing: ["How long will my credit last?", "What did I spend this month?", "Where did my credit go?"],
  knowledge: ["What does my agent know?", "What couldn't it answer this week?", PRICES_QUESTION],
  other: ["What can you do on this screen?", "What needs me today?", "How are my calls going?"],
};

/**
 * The empty panel's only line, the same on every screen (founder, 9 Nov 2026: make it as
 * simple as ChatGPT's home). What fits the screen is said by the questions under it, not by
 * a sentence above them. A screen that leads its own conversation passes its own `intro`.
 */
export const EMPTY_PANEL_QUESTION = "What can I help with?";

function screenOf(route: string): Screen {
  const parts = route.split("/").filter(Boolean);
  // Client routes are /c/<slug>/<section>/<id?>; admin and anything else are "other".
  if (parts[0] !== "c") return "other";
  const section = parts[2];
  const deeper = parts.length > 3;
  switch (section) {
    case undefined:
      return "dashboard";
    case "attention":
      return "attention";
    case "calls":
      return deeper ? "call" : "calls";
    case "leads":
      return deeper ? "lead" : "leads";
    case "agents":
      if (parts[3] === "first") return "first_agent";
      return deeper ? "agent" : "agents";
    case "campaigns":
      return "campaigns";
    case "integrations":
    case "lead-sources":
      return "integrations";
    case "billing":
    case "credits":
    case "usage":
    case "spend":
      return "billing";
    case "knowledge":
      return "knowledge";
    default:
      return "other";
  }
}

/** The screens whose last question gives way to one of the business's own. */
const OWN_QUESTION_SCREENS: ReadonlySet<Screen> = new Set<Screen>(["dashboard", "calls", "leads", "other"]);

const capitalised = (q: string) => q.charAt(0).toUpperCase() + q.slice(1);

/**
 * The questions for this screen. Without `business` (the operator's console, or before the
 * copy is read) they are the general ones.
 */
export function suggestedQuestions(route: string, business?: BusinessCapabilities): readonly string[] {
  const screen = screenOf(route);
  const base = QUESTIONS[screen];
  if (!business) return base;
  const fitted = base.map((q) => {
    if (q === BOOKINGS_QUESTION) {
      if (business.takesBookings === false && business.takesOrders === false) return "How do I change what it may do?";
      if (business.takesBookings === false) return "How do I let it take orders?";
    }
    if (q === PRICES_QUESTION && business.quotesPrices === false) return "How do I add answers to common questions?";
    return q;
  });
  const own = business.pipQuestions.map(capitalised).find((q) => !fitted.includes(q));
  return own && OWN_QUESTION_SCREENS.has(screen) ? [...fitted.slice(0, -1), own] : fitted;
}
