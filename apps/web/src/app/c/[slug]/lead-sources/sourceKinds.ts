import { lookup } from "@/lib/lookup";

/** What a client calls each `inbound_webhooks.source`. The API's enum is the contract;
 *  this is the only place it is turned into English. */
const SOURCE_LABELS: Record<string, string> = {
  website_form: "Website form",
  meta_lead_ads: "Meta Lead Ads (Facebook / Instagram)",
  zoho: "Zoho",
  sheets: "Google Sheets",
  custom: "Something else (custom POST)",
};

/** The order the picker offers them in: the two most clients use, then the rest. */
export const CREATABLE_SOURCES = [
  "website_form",
  "meta_lead_ads",
  "zoho",
  "sheets",
  "custom",
] as const;

export const sourceLabel = (source: string) => lookup(SOURCE_LABELS, source) ?? source;

/** The one kind with its own receiver, its own secret and its own setup. */
export const META_SOURCE = "meta_lead_ads";

/** Every other kind posts to the shared-secret webhook receiver. */
export const WEBHOOK_KINDS = CREATABLE_SOURCES.filter((kind) => kind !== META_SOURCE);

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
