import type { ConfigField } from "@/lib/api/opsConfig";

/**
 * The platform-configuration screen's sections (D-661), and which setting lives in which.
 *
 * A setting is placed by PREFIX MATCHING on its key, in section order, first match wins —
 * not by a per-key table. A per-key table would be a second list of every setting, which is
 * the drift the API side avoids by serving the field list itself. A key that matches no
 * prefix lands in "Other", which is a section of its own and only appears when it has
 * something in it, so a `Settings` field added server-side is on this screen the day it
 * ships, editable, with no edit here.
 *
 * Sections that also mount a PANEL (the rate card, model prices, credentials) say so in
 * `panels`; the screen renders those whether or not any plain setting matched.
 */
export type ConfigSectionId =
  | "calling"
  | "voices-models"
  | "billing"
  | "compliance"
  | "messaging"
  | "integrations"
  | "access"
  | "platform"
  | "other"
  | "credentials";

export interface ConfigSectionSpec {
  id: ConfigSectionId;
  label: string;
  /** One line under the section heading. */
  hint: string;
  prefixes: readonly string[];
  /** Which permission the section's content is read and written under. */
  permission: "platform:config" | "platform:secrets";
}

export const CONFIG_SECTIONS: readonly ConfigSectionSpec[] = [
  {
    id: "calling",
    label: "Calling",
    hint: "Which platform places calls, how it reaches us, and how much capacity outbound may use.",
    // `plivo_` matches nothing today: the carrier credentials are env-only and held by the
    // voice worker's own secret set. It is here so a console-managed half lands with the
    // engine rather than under "Other".
    prefixes: [
      "engine",
      "webhook_base_url",
      "cartesia_",
      "pipecat_",
      "carrier",
      "vobiz_",
      "plivo_",
      "inbound_reserve",
      "number_provider",
    ],
    permission: "platform:config",
  },
  {
    id: "voices-models",
    label: "Voices and models",
    hint: "What an agent hears with, which model answers, and the prices that make a model available.",
    prefixes: [
      "sarvam_",
      "stt_",
      "azure_openai_",
      "platform_llm_model",
      "retrieval_",
      "supermemory_",
    ],
    permission: "platform:config",
  },
  {
    id: "billing",
    label: "Billing and rates",
    hint: "What a minute sells for, the exchange rate behind vendor costs, and how invoices are issued.",
    prefixes: ["usd_inr_rate", "self_serve_inr", "gst_", "payment_provider", "razorpay_"],
    permission: "platform:config",
  },
  {
    id: "compliance",
    label: "Compliance",
    hint: "How long consent and registration checks stay valid, and who verifies identity.",
    prefixes: [
      "campaign_consent_",
      "pe_verification_",
      "number_resale_",
      "kyc_verification_",
    ],
    permission: "platform:config",
  },
  {
    id: "messaging",
    label: "Messaging and alerts",
    hint: "Where hot-lead alerts, client email and operator alarms are sent from and to.",
    // `email_provider` sits with the alerts: an operator looking for why an alarm did not
    // arrive looks here, and it decides whether any mail transport exists at all.
    prefixes: ["email_provider", "smtp_", "notifications_", "alerts_", "resend_", "whatsapp_"],
    permission: "platform:config",
  },
  {
    id: "integrations",
    label: "Integrations",
    hint: "Lead sources and outside services this deployment connects to.",
    prefixes: ["google_sheets_", "meta_", "google_oauth_"],
    permission: "platform:config",
  },
  {
    id: "access",
    label: "Sign-in and sign-up",
    hint: "The switch over all sign-in, and whether new clients can sign themselves up.",
    prefixes: ["first_party_auth", "self_serve_signup"],
    permission: "platform:config",
  },
  {
    id: "platform",
    label: "Platform",
    hint: "Storage, database, tracing and maintenance notice — and the settings only the server can hold.",
    prefixes: [
      "maintenance_notice_",
      "object_store_",
      "db_",
      "tls_",
      "otel_",
      "release_",
    ],
    permission: "platform:config",
  },
  {
    id: "other",
    label: "Other",
    hint: "Settings this console has no section for yet — editable like any other.",
    prefixes: [],
    permission: "platform:config",
  },
  {
    id: "credentials",
    label: "Credentials and keys",
    hint: "Vendor keys the platform signs in with. A stored key can be replaced, never shown.",
    prefixes: [],
    permission: "platform:secrets",
  },
];

/** The section a setting belongs to. Never undefined: an unmatched key is "other". */
export function sectionOf(key: string): ConfigSectionId {
  for (const section of CONFIG_SECTIONS) {
    if (section.prefixes.some((prefix) => key.startsWith(prefix))) return section.id;
  }
  return "other";
}

/** The settings of one section, in the order the server sent them. */
export function fieldsIn(section: ConfigSectionId, fields: readonly ConfigField[]): ConfigField[] {
  return fields.filter((field) => sectionOf(field.key) === section);
}

/**
 * The sections the menu offers. "Other" appears only when the server sent a key no section
 * claims, and only once the list has been read — an unread list is not evidence of an
 * empty one, so the menu does not grow or shrink on a guess.
 */
export function visibleSections(fields: readonly ConfigField[] | undefined): ConfigSectionSpec[] {
  const hasOther = fields !== undefined && fields.some((field) => sectionOf(field.key) === "other");
  return CONFIG_SECTIONS.filter((section) => section.id !== "other" || hasOther);
}
