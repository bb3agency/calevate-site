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
