"use client";

import { useAgentLanguages } from "@/lib/api/agentLanguages";
import { useAgents, type Agent, type AgentLanguage } from "@/lib/api/agents";
import { useBusinessCopy, type BusinessCopy } from "@/lib/api/businessCopy";
import { useClientSession } from "@/lib/api/session";
import { baseOf } from "@/lib/languageNames";

/**
 * What this business does with its callers, as the client screens use it: the capability
 * profile judged with the account's business copy (`GET /v1/business-copy`).
 *
 * Every judgement is three-valued. `null` is "not judged yet" (no copy has landed, or the
 * read is in flight). Two readings, and a screen picks the one its question needs (audit of
 * 5 Nov 2026, G1-1):
 * - OFFERED: every switch, chip and job stays on offer until a judged `false` hides it, so a
 *   business is never shown less than it may do because a read was slow (`quotesPrices`,
 *   `goAheadLabel`).
 * - ASSUMED: words that take something for granted ("hot lead", "booking", "prices") only
 *   for a judged `true`; unknown reads neutral (`leadWords`, `callersWord`).
 * The server twins are `Capabilities.offered` / `assumed` and `tenancy/caller_words.py`.
 */

export type Applies = boolean | null;

export interface BusinessCapabilities {
  readonly takesBookings: Applies;
  readonly takesOrders: Applies;
  readonly quotesPrices: Applies;
  readonly hasPremises: Applies;
  readonly sells: Applies;
  readonly healthBusiness: Applies;
  /** What its callers are called, singular and lower case ("user", "farmer"), or null. */
  readonly callerNoun: string | null;
  readonly objections: BusinessCopy["objections"];
  readonly pipQuestions: readonly string[];
  /** The booking job's name from the copy, when it wrote one. */
  readonly bookingJobTitle: string | null;
}

export const UNKNOWN_CAPABILITIES: BusinessCapabilities = {
  takesBookings: null,
  takesOrders: null,
  quotesPrices: null,
  hasPremises: null,
  sells: null,
  healthBusiness: null,
  callerNoun: null,
  objections: [],
  pipQuestions: [],
  bookingJobTitle: null,
};

const text = (value: string | null | undefined): string | null => {
  const trimmed = (value ?? "").trim();
  return trimmed ? trimmed : null;
};

export function capabilitiesOf(copy: BusinessCopy | null | undefined): BusinessCapabilities {
  if (!copy) return UNKNOWN_CAPABILITIES;
  // A copy written before the profile existed has no `capabilities`; read it as unknown.
  const caps: Partial<BusinessCopy["capabilities"]> | undefined = copy.capabilities;
  const applies = (key: keyof BusinessCopy["capabilities"]): Applies => caps?.[key]?.applies ?? null;
  return {
    takesBookings: applies("takes_bookings"),
    takesOrders: applies("takes_orders"),
    quotesPrices: applies("quotes_prices"),
    hasPremises: applies("has_premises"),
    sells: applies("sells"),
    healthBusiness: applies("health_business"),
    callerNoun: text(copy.caller_noun)?.toLowerCase() ?? null,
    objections: copy.objections ?? [],
    pipQuestions: (copy.pip_questions ?? []).map((q) => q.trim()).filter(Boolean),
    bookingJobTitle: text(copy.placeholders?.booking_job_title),
  };
}

export function useBusinessCapabilities(): BusinessCapabilities {
  const copy = useBusinessCopy(useClientSession());
  return capabilitiesOf(copy.data);
}

/**
 * Whether prices belong on this business's screens. Off when the copy judged that it quotes
 * none, or when the business profile's wording has no price label (`price_label: null`, the
 * profile's own "no prices" answer). `priceLabel` is `undefined` while the profile is unread,
 * which, like an unjudged capability, keeps prices on offer.
 */
export function quotesPrices(caps: BusinessCapabilities, priceLabel?: string | null): boolean {
  return caps.quotesPrices !== false && priceLabel !== null;
}


/**
 * The switch that lets an agent go ahead on a caller's behalf, named for what this business
 * takes, or null when it takes neither. A business that only takes orders reads "Take
 * orders", one that only books reads its copy's own booking job ("Book visits"), and an
 * unjudged one keeps the general "Take bookings and orders".
 */
export function goAheadLabel(caps: BusinessCapabilities): string | null {
  const bookings = caps.takesBookings;
  const orders = caps.takesOrders;
  if (bookings === false && orders === false) return null;
  if (bookings === false) return "Take orders";
  if (orders === false) return caps.bookingJobTitle ?? "Take bookings";
  return "Take bookings and orders";
}

/**
 * The language a new agent or a first-run step starts in: the business's own main call
 * language from its copy (`BusinessCopyOut.language`, BCP-47, any region) when the server
 * offers it to this account, else the account's starting language, the first the server
 * offers (`offered`, from `useAgentLanguages`, the platform default first). Null only when
 * nothing is offered, which is before the server has answered.
 */
export function businessLanguage(
  copyLanguage: string | null | undefined,
  offered: readonly AgentLanguage[],
): AgentLanguage | null {
  const base = baseOf(copyLanguage);
  const own = base ? offered.find((code) => baseOf(code) === base) : undefined;
  return own ?? offered[0] ?? null;
}

/** `businessLanguage` for this account, or null until the server's language list has been
 *  read (on a failed read, from the three every account has). */
export function useBusinessLanguage(): AgentLanguage | null {
  const session = useClientSession();
  const copy = useBusinessCopy(session);
  const languages = useAgentLanguages(session);
  return languages.settled ? businessLanguage(copy.data?.language, languages.tags) : null;
}

/** A plural for the copy's singular caller noun: "user" → "users", "family" → "families". */
export function pluralNoun(noun: string): string {
  if (/[^aeiou]y$/.test(noun)) return `${noun.slice(0, -1)}ies`;
  if (/(s|x|z|ch|sh)$/.test(noun)) return `${noun}es`;
  return `${noun}s`;
}

/** What the owner calls the people on its calls, plural: the copy's noun, or `fallback`. */
export function callersWord(caps: BusinessCapabilities, fallback = "callers"): string {
  return caps.callerNoun ? pluralNoun(caps.callerNoun) : fallback;
}

/**
 * What a caller books or orders, with its article, once the business is judged to take it:
 * "a booking", "an order" or "a booking or order"; null while unjudged or when it takes
 * neither. The web twin of `BusinessFit.offer_noun`.
 */
export function offerNoun(caps: BusinessCapabilities): string | null {
  if (caps.takesBookings === true && caps.takesOrders === true) return "a booking or order";
  if (caps.takesOrders === true) return "an order";
  if (caps.takesBookings === true) return "a booking";
  return null;
}

/** Whether the copy run has judged what this business does; false shows "still learning". */
export function capabilitiesJudged(caps: BusinessCapabilities): boolean {
  return [caps.takesBookings, caps.takesOrders, caps.quotesPrices, caps.hasPremises, caps.sells].every(
    (value) => value !== null,
  );
}

/** The lead ladder's words for this business, lower case, for a sentence. */
export interface LeadWords {
  readonly lead: string;
  readonly leads: string;
  readonly newLead: string;
  readonly hotLead: string;
  readonly hotLeads: string;
}

/**
 * "lead" and "hot lead" only for a business judged to sell; otherwise the caller as the
 * business names them ("interested user", "most interested users"), or "caller" until its copy
 * names one. The web twin of `tenancy/caller_words.CallerWords`, word for word: pass
 * `useAccountCapabilities()` so an account whose agents all help customers reads callers.
 */
export function leadWords(caps: BusinessCapabilities): LeadWords {
  if (caps.sells === true) {
    return { lead: "lead", leads: "leads", newLead: "new lead", hotLead: "hot lead", hotLeads: "hot leads" };
  }
  const one = caps.callerNoun ?? "caller";
  const many = pluralNoun(one);
  return {
    lead: `interested ${one}`,
    leads: `interested ${many}`,
    newLead: `interested ${one}`,
    hotLead: `most interested ${one}`,
    hotLeads: `most interested ${many}`,
  };
}

/**
 * Whether every working agent is a support agent (`purpose: "support"`, founder 21 Nov 2026):
 * the account then reads "Callers" where it read "Leads". Archived agents are not on the
 * roster and take no calls. An empty or unread roster is `false`, so the screens keep the
 * words they had. The server twin is `tenancy/caller_words.ALL_SUPPORT_SQL`.
 */
export function allSupportAgents(agents: readonly Pick<Agent, "purpose">[] | undefined): boolean {
  return !!agents && agents.length > 0 && agents.every((agent) => agent.purpose === "support");
}

export function useAllSupport(): boolean {
  return allSupportAgents(useAgents(useClientSession()).data);
}

/**
 * The capabilities the console's sales words read: `sells` reads false when every working
 * agent helps customers, because nothing is sold on this account's calls. The server twin is
 * `CallerWords.sales_words`. Not for what an agent may offer: that is the business's own.
 */
export function accountCapabilities(caps: BusinessCapabilities, allSupport: boolean): BusinessCapabilities {
  return allSupport && caps.sells === true ? { ...caps, sells: false } : caps;
}

export function useAccountCapabilities(): BusinessCapabilities {
  return accountCapabilities(useBusinessCapabilities(), useAllSupport());
}

/**
 * The names of the leads screens and things, for headings and labels: "Leads" unless every
 * working agent helps customers. Routes and API fields keep the word "lead" either way.
 */
export interface LeadNouns {
  readonly Leads: string;
  readonly Lead: string;
  readonly leads: string;
  readonly lead: string;
  readonly LeadDetails: string;
}

const LEAD_NOUNS: LeadNouns = { Leads: "Leads", Lead: "Lead", leads: "leads", lead: "lead", LeadDetails: "Lead details" };
const CALLER_NOUNS: LeadNouns = {
  Leads: "Callers",
  Lead: "Caller",
  leads: "callers",
  lead: "caller",
  LeadDetails: "Caller details",
};

export function leadNouns(allSupport: boolean): LeadNouns {
  return allSupport ? CALLER_NOUNS : LEAD_NOUNS;
}

export function useLeadNouns(): LeadNouns {
  return leadNouns(useAllSupport());
}
