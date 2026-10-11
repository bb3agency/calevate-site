/**
 * THREE QUESTIONS WORTH ASKING ON THIS SCREEN, shown in an empty assistant panel
 * (founder, REDESIGN-2) so a person sees what it is for before typing. Picked by the
 * screen's route, which is either a declared pattern (`/c/{slug}/calls/{callId}`) or the
 * fallback's masked path (`/c/:hidden/calls`), so both are read by segment position.
 *
 * Plain questions an owner would ask, neutral across trades; none promises an action the
 * assistant cannot take (every change still waits for the person where it must).
 */

type Screen =
  | "dashboard"
  | "attention"
  | "calls"
  | "call"
  | "leads"
  | "lead"
  | "agents"
  | "agent"
  | "campaigns"
  | "integrations"
  | "billing"
  | "knowledge"
  | "other";

const QUESTIONS: Record<Screen, readonly string[]> = {
  dashboard: ["What needs me today?", "How did calls go this week?", "Which leads should I call back first?"],
  attention: ["What needs me first?", "Why did a campaign pause?", "How do I teach an agent an answer?"],
  calls: ["Which calls need a follow-up?", "Summarise today's calls", "Who called more than once this week?"],
  call: ["What did this caller want?", "Should I call them back?", "What did the agent promise?"],
  leads: ["Which hot leads should I call first?", "What are people asking for most?", "Show this week's new leads"],
  lead: ["What does this person want?", "When did we last speak to them?", "What should I do next?"],
  agents: ["Which agents are answering right now?", "What does each agent do?", "How do I test an agent?"],
  agent: ["Is this agent working right now?", "What does it say when it answers?", "How do I let it take bookings?"],
  campaigns: ["Which campaign is running?", "Why can't my campaign launch?", "How many people did we reach?"],
  integrations: ["What is connected?", "Why did a delivery fail?", "How do I send leads to my CRM?"],
  billing: ["How long will my credit last?", "What did I spend this month?", "Where did my credit go?"],
  knowledge: ["What does my agent know?", "What couldn't it answer this week?", "How do I add my price list?"],
  other: ["What can you do on this screen?", "What needs me today?", "How are my calls going?"],
};

/**
 * The panel's first line, in the words of the screen it sits beside (founder, REDESIGN-2):
 * what a person can ask here, never a list of features and never a count of anything.
 */
const OPENINGS: Record<Screen, string> = {
  dashboard: "I can tell you what needs you today and how this week went.",
  attention: "I can go through what needs you, one thing at a time.",
  calls: "I can find a call, sum up a day of calls, or tell you who needs a call back.",
  call: "Ask me what this caller wanted, or whether to call them back.",
  leads: "I can tell you who to call first and what people are asking for.",
  lead: "Ask me what this person wants and what to do next.",
  agents: "I can tell you what each agent does and whether it is answering.",
  agent: "Ask me how this agent is doing, or how to change what it says.",
  campaigns: "I can tell you how a campaign is going, or why one cannot start.",
  integrations: "Ask me what is connected and whether your leads are getting through.",
  billing: "I can tell you how long your credit will last and where it went.",
  knowledge: "Ask me what your agents know and what they could not answer.",
  other: "Ask me about this screen, or anything in your account.",
};

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
      return deeper ? "agent" : "agents";
    case "campaigns":
    case "campaign-review":
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

export function suggestedQuestions(route: string): readonly string[] {
  return QUESTIONS[screenOf(route)];
}

/** The empty panel's opening line for this screen; a screen with fields adds that the
 * assistant can fill them in. */
export function openingLine(route: string, hasFields: boolean): string {
  const line = OPENINGS[screenOf(route)];
  return hasFields ? `${line} Or tell me what to fill in here.` : line;
}
