"use client";

import { LANGUAGE_NAMES } from "@/lib/agentState";
import type { AgentLanguage } from "@/lib/api/agents";
import { useBusinessCopy, type BusinessCopy } from "@/lib/api/businessCopy";
import { useClientSession } from "@/lib/api/session";

/**
 * What this business does with its callers, as the client screens use it: the capability
 * profile judged with the account's business copy (`GET /v1/business-copy`).
 *
 * Every judgement is three-valued. `null` is "not judged yet" (no copy has landed, or the
 * read is in flight), and a screen then keeps the behaviour it had before the profile
 * existed: every switch, chip and job stays on offer. Only a judged `false` hides or
 * rewords something, so a business is never shown less than it had because a read was slow.
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

/** Whether the business takes bookings or orders at all; unknown counts as yes. */
export function takesBookingsOrOrders(caps: BusinessCapabilities): boolean {
  return caps.takesBookings !== false || caps.takesOrders !== false;
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

/** The platform's starting language when nothing about the business says otherwise (BRD §1). */
export const FALLBACK_LANGUAGE: AgentLanguage = "te-IN";

/**
 * The language a new agent or a first-run step starts in: the business's own main call
 * language from its copy (`BusinessCopyOut.language`, BCP-47, any region), else the
 * platform's starting one. A language this build cannot speak falls back too.
 */
export function businessLanguage(copyLanguage: string | null | undefined): AgentLanguage {
  const base = (copyLanguage ?? "").toLowerCase().split(/[-_]/)[0];
  const known = (Object.keys(LANGUAGE_NAMES) as AgentLanguage[]).find((code) => code.split("-")[0] === base);
  return base && known ? known : FALLBACK_LANGUAGE;
}

export function useBusinessLanguage(): AgentLanguage {
  return businessLanguage(useBusinessCopy(useClientSession()).data?.language);
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
