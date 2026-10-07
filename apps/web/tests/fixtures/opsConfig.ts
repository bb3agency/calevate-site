import type { ConfigField, ConfigSection } from "@/lib/api/opsConfig";

/**
 * THE SECTIONS `GET /v1/ops/config` SERVES, in its order (`apps/api/ops/config_catalog.py`).
 *
 * A fixture, not a second source: the screen renders whatever the server sends, and these
 * are here so a test renders the layout an operator actually sees. Every subsection a test
 * fixture files a field under is listed; the server omits empty ones, which the screen does
 * not depend on.
 */
function section(
  id: string,
  label: string,
  subsections: [string, string][],
  panels: { before?: string[]; after?: string[] } = {},
): ConfigSection {
  return {
    id,
    label,
    hint: `${label} hint.`,
    subsections: subsections.map(([sub, subLabel]) => ({ id: sub, label: subLabel })),
    panels_before: panels.before ?? [],
    panels_after: panels.after ?? [],
  };
}

export const OPS_CONFIG_SECTIONS: ConfigSection[] = [
  section(
    "voice-engine",
    "Voice engine",
    [
      ["engine", "Active engine"],
      ["thinnest", "ThinnestAI"],
      ["pipecat", "Our own runtime (Pipecat)"],
    ],
    { after: ["engine_minute_price"] },
  ),
  section("telephony", "Telephony and carrier", [
    ["carrier", "Carrier"],
    ["numbers", "Phone numbers"],
  ]),
  section("calling-limits", "Calling limits and pacing", [["limits", "Limits"]]),
  section(
    "language-models",
    "Language models and tiers",
    [
      ["tiers", "Client tiers"],
      ["default", "Platform default"],
      ["azure", "Azure OpenAI"],
    ],
    { after: ["model_pricing", "dashboard_data_use"] },
  ),
  section("speech", "Speech", [["stt", "Speech-to-text (STT)"]]),
  section(
    "billing",
    "Billing and pricing",
    [["prices", "Prices"]],
    { before: ["rate_card"], after: ["fx_rate", "number_price", "tts_plan_fee"] },
  ),
  section("security", "Security and access", [["access", "Access"]]),
  section(
    "infrastructure",
    "Infrastructure",
    [
      ["database", "Database"],
      ["storage", "Object storage"],
    ],
    { after: ["server_only_keys"] },
  ),
];

/** The served half of a field that is about placement and wording, for the default fixture. */
export const SELF_SERVE_PRICE_META: Pick<
  ConfigField,
  | "nullable"
  | "label"
  | "description"
  | "section"
  | "subsection"
  | "engine_scope"
  | "used_by_current_engine"
> = {
  nullable: false,
  label: "Self-serve price per minute (INR)",
  description: "The self-serve list price per calling minute.",
  section: "billing",
  subsection: "prices",
  engine_scope: null,
  used_by_current_engine: true,
};

/** Placement and wording for another key, in one call. */
export function placed(
  section: string,
  subsection: string,
  label: string,
): Pick<ConfigField, "section" | "subsection" | "label"> {
  return { section, subsection, label };
}
