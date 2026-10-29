import { lookup } from "@/lib/lookup";

/** What a client calls each `inbound_webhooks.source`. The API's enum is the contract;
 *  this is the only place it is turned into English. */
const SOURCE_LABELS: Record<string, string> = {
  website_form: "Website form",
  meta_lead_ads: "Meta Lead Ads (Facebook / Instagram)",
  zoho: "Zoho",
  sheets: "Google Sheets",
  custom: "Something else (custom POST)",
  indiamart: "IndiaMART",
  "99acres": "99acres",
  magicbricks: "MagicBricks",
  housing: "Housing.com",
  leadsquared: "LeadSquared",
};

/** The order the picker offers them in: the two most clients use, then the rest. */
export const CREATABLE_SOURCES = [
  "website_form",
  "meta_lead_ads",
  "zoho",
  "sheets",
  "custom",
] as const;

/**
 * Senders that post to an address and cannot add our header (D-942). Their secret rides
 * in the address itself, which is shown once; `ingest/portals.py` holds each one's preset
 * field names, so the add form asks nothing about fields for them.
 */
export const PUSH_SOURCES = ["indiamart", "99acres", "magicbricks", "housing", "leadsquared"] as const;
export type PushSource = (typeof PUSH_SOURCES)[number];

export const isPushSource = (source: string): source is PushSource =>
  (PUSH_SOURCES as readonly string[]).includes(source);

/** Portals whose push an account manager switches on, rather than a screen the client uses. */
export const ACCOUNT_MANAGER_PORTALS: readonly string[] = ["99acres", "magicbricks", "housing"];

/**
 * Senders whose payload shape is the vendor's own documented, fixed one: the preset reads it
 * and there are no field names to change. The account-manager portals are not among them —
 * their preset is the list we publish and ask the manager to send (OPERATIONS gate A-14), so
 * a manager who sends other names is the case their editor stays for.
 */
export const FIXED_FIELD_SOURCES: readonly string[] = ["indiamart", "leadsquared"];

export const hasFixedFields = (source: string): boolean => FIXED_FIELD_SOURCES.includes(source);

/** The row menu's words for the drawer that holds the field names (and what the form is). */
export function fieldsMenuLabel(source: string): string {
  if (hasFixedFields(source)) return "What these leads are";
  if (ACCOUNT_MANAGER_PORTALS.includes(source)) {
    return "Adjust field names (if your manager sends others)";
  }
  return "Change field names";
}

export const sourceLabel = (source: string) => lookup(SOURCE_LABELS, source) ?? source;

/** The one kind with its own receiver, its own secret and its own setup. */
export const META_SOURCE = "meta_lead_ads" as const;

/** Every other header-authenticated kind posts to the shared-secret webhook receiver. */
export type WebhookKind = Exclude<(typeof CREATABLE_SOURCES)[number], typeof META_SOURCE>;
export const WEBHOOK_KINDS = CREATABLE_SOURCES.filter((kind): kind is WebhookKind => kind !== META_SOURCE);

/** The service whose logo stands beside a lead source's name, or null for a generic icon. */
export function sourceLogo(source: string): string | null {
  switch (source) {
    case META_SOURCE:
    case "meta":
      return "meta_cloud";
    case "zoho":
      return "zoho_crm";
    case "sheets":
      return "google_sheets";
    default:
      return null;
  }
}
