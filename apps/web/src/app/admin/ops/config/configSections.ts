import type { ConfigField, ConfigList, ConfigSection } from "@/lib/api/opsConfig";

import { lookup } from "@/lib/lookup";

import { displayValue } from "./configControl";

/**
 * Where each platform setting is shown, and how the screen finds one.
 *
 * THE SERVER DECIDES THE GROUPING. `GET /v1/ops/config` serves the sections in order and
 * files every field under one (`apps/api/ops/config_catalog.py`), so a setting's section,
 * subsection, label and description have one definition. This module only arranges what was
 * served: it adds the two sections that are not settings (credentials, which has its own
 * permission, and a fallback for when the list could not be read), and it never guesses a
 * section from a key's prefix.
 */

/** A section in the screen's menu. */
export interface ScreenSection {
  id: string;
  label: string;
  hint: string;
}

/** Vendor credentials and key management: `platform:secrets`, not part of the settings read. */
export const CREDENTIALS_SECTION: ScreenSection = {
  id: "credentials",
  label: "Credentials and keys",
  hint: "Vendor keys the platform signs in with. A stored key can be replaced, never shown.",
};

/**
 * The one settings section offered when the section list itself is not available — the
 * read failed, was refused, or this session may not read it. It holds the refusal or the
 * failure, never a guessed layout.
 */
export const SETTINGS_FALLBACK: ScreenSection = {
  id: "settings",
  label: "Platform settings",
  hint: "Every setting this deployment can change without logging into the server.",
};

/** Where a field lands when the server filed it under a section it did not serve. */
const UNFILED: ConfigSection = {
  id: "unfiled",
  label: "Other",
  hint: "Settings this console could not place in a section. Editable like any other.",
  subsections: [],
  panels_before: [],
  panels_after: [],
};

/**
 * The served sections, plus "Other" when a field names a section that was not served — so
 * no setting the server sent can be missing from the screen.
 */
export function servedSections(config: ConfigList): ConfigSection[] {
  const ids = new Set(config.sections.map((section) => section.id));
  const orphaned = config.fields.some((field) => !ids.has(field.section));
  return orphaned ? [...config.sections, UNFILED] : config.sections;
}

/** The menu: the served sections then credentials, or the fallback then credentials. */
export function screenSections(served: ConfigSection[] | undefined): ScreenSection[] {
  const settings = served ?? [SETTINGS_FALLBACK];
  return [...settings.map(({ id, label, hint }) => ({ id, label, hint })), CREDENTIALS_SECTION];
}

/** The settings of one section, in the order the server sent them. */
export function fieldsIn(
  section: ConfigSection,
  config: ConfigList,
): ConfigField[] {
  if (section.id === UNFILED.id) {
    const ids = new Set(config.sections.map((served) => served.id));
    return config.fields.filter((field) => !ids.has(field.section));
  }
  return config.fields.filter((field) => field.section === section.id);
}

export interface FieldGroup {
  id: string;
  label: string;
  fields: ConfigField[];
}

/**
 * One section's settings split into its subsections, with the settings the current engine
 * does not read set apart. A field naming a subsection that was not served is kept, in a
 * trailing group, rather than dropped.
 */
export function groupFields(
  section: ConfigSection,
  fields: readonly ConfigField[],
): { groups: FieldGroup[]; unused: ConfigField[] } {
  const inUse = fields.filter((field) => field.used_by_current_engine);
  const unused = fields.filter((field) => !field.used_by_current_engine);
  const groups: FieldGroup[] = section.subsections
    .map((sub) => ({
      id: sub.id,
      label: sub.label,
      fields: inUse.filter((field) => field.subsection === sub.id),
    }))
    .filter((group) => group.fields.length > 0);
  const known = new Set(section.subsections.map((sub) => sub.id));
  const loose = inUse.filter((field) => !known.has(field.subsection));
  if (loose.length > 0) groups.push({ id: "more", label: "More settings", fields: loose });
  return { groups, unused };
}

/**
 * Does the value in force differ from the built-in default? A field with no default has
 * nothing to differ from. Compared as the server serialised both, so `"6.00"` is never
 * parsed into a float to be compared (hard rule 7).
 */
export function differsFromDefault(field: ConfigField): boolean {
  if (!field.has_default) return false;
  return JSON.stringify(field.value) !== JSON.stringify(field.default);
}

export interface ConfigFilter {
  query: string;
  changedOnly: boolean;
}

export function isFiltering(filter: ConfigFilter): boolean {
  return filter.query.trim() !== "" || filter.changedOnly;
}

/** Every word of the query must appear in the field's name, key, variable, text or value. */
export function matchesFilter(
  field: ConfigField,
  filter: ConfigFilter,
  sectionLabel: string,
): boolean {
  if (filter.changedOnly && !differsFromDefault(field)) return false;
  const words = filter.query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = [
    field.label,
    field.key,
    field.key.replace(/_/g, " "),
    field.env_var,
    field.description,
    sectionLabel,
    displayValue(field, field.value),
    field.value === null ? "" : String(field.value),
  ]
    .join(" ")
    .toLowerCase();
  return words.every((word) => haystack.includes(word));
}

/** The matching settings, grouped by section in section order; empty sections omitted. */
export function filterAcrossSections(
  config: ConfigList,
  filter: ConfigFilter,
): { section: ConfigSection; fields: ConfigField[] }[] {
  return servedSections(config)
    .map((section) => ({
      section,
      fields: fieldsIn(section, config).filter((field) =>
        matchesFilter(field, filter, section.label),
      ),
    }))
    .filter((group) => group.fields.length > 0);
}

/* ────────────────────────────────────────────────────────────────────────────
 * Finding everything else on the screen: sections, panels and credential names.
 *
 * The settings rows above are searched field by field. The panels (prices, the exchange
 * rate, the rate card…) and the credentials are not settings, so they are indexed here by
 * their title, the words an operator would type for them and the names they list (model
 * ids, credential key names). Never a value: a credential is found by its name only.
 * ──────────────────────────────────────────────────────────────────────────── */

/** Where a search result jumps to. `section` is the section that holds it. */
export interface SearchTarget {
  kind: "section" | "panel" | "credential";
  /** A DOM id on the screen, unique per target: what the jump scrolls to and highlights. */
  anchor: string;
  section: string;
  title: string;
  /** One line under the title saying what is there. */
  detail: string;
  words: string[];
}

/** The DOM id of a served panel's wrapper. */
export function panelAnchor(panel: string): string {
  return `config-panel-${panel}`;
}

/** The DOM id of one credential's row in the Credentials and keys section. */
export function credentialAnchor(key: string): string {
  return `credential-${key}`;
}

/** The DOM id of a section's content. */
export function sectionAnchor(section: string): string {
  return `config-section-${section}`;
}

/** The DOM id of one setting's row. */
export function settingAnchor(key: string): string {
  return `config-setting-${key}`;
}

/** The screen's route; `configHref` is the one way any other screen links into it. */
export const CONFIG_ROUTE = "/admin/ops/config";

/** What a deep link opens on: a served panel, one credential's row, or one setting's row. */
export type ConfigTarget = { panel: string } | { credential: string } | { setting: string };

/**
 * A link to one section of the configuration screen, and optionally to the panel, credential
 * or setting in it, which the screen scrolls to and outlines (`deepLinkAnchor`). Setup
 * checklists elsewhere link through this so each step lands on the thing it names.
 */
export function configHref(section: string, target?: ConfigTarget): string {
  const query = new URLSearchParams({ section });
  if (target && "panel" in target) query.set("panel", target.panel);
  if (target && "credential" in target) query.set("credential", target.credential);
  if (target && "setting" in target) query.set("setting", target.setting);
  return `${CONFIG_ROUTE}?${query.toString()}`;
}

/** The DOM id a deep link's query names, or null when it names none. */
export function deepLinkAnchor(params: { get(name: string): string | null }): string | null {
  const panel = params.get("panel");
  if (panel) return panelAnchor(panel);
  const credential = params.get("credential");
  if (credential) return credentialAnchor(credential);
  const setting = params.get("setting");
  if (setting) return settingAnchor(setting);
  return null;
}

/** Each served panel's title, what it holds, and the words an operator looks for it by. */
export const PANEL_SEARCH: Record<string, { title: string; detail: string; words: string[] }> = {
  rate_card: {
    title: "Rate card",
    detail: "What a minute sells for to self-serve clients, per voice tier.",
    words: ["rate card", "per minute", "minute price", "self-serve", "plan", "client price", "inr"],
  },
  engine_minute_price: {
    title: "Engine minute price",
    detail: "The attested per-minute rate a voice platform charges us.",
    words: ["engine", "minute price", "per minute", "voice platform", "thinnestai", "attest", "band"],
  },
  fx_rate: {
    title: "Exchange rate (USD to INR)",
    detail: "The dollar-to-rupee rate vendor costs are converted at, and how fresh it is.",
    words: ["fx", "exchange rate", "usd", "inr", "dollar", "rupee", "conversion"],
  },
  number_price: {
    title: "Phone number price",
    detail: "What a client pays per month for a number, once attested.",
    words: ["number", "phone number", "rental", "monthly", "number price"],
  },
  tts_plan_fee: {
    title: "Voice plan fee",
    detail: "A voice vendor's monthly plan fee, from its invoice.",
    words: ["tts", "voice", "plan fee", "cartesia", "monthly", "invoice", "text to speech"],
  },
  model_pricing: {
    title: "Model prices",
    detail:
      "Per-million-token prices billing uses, in dollars or rupees (rupee-billed models such as Sarvam 105B), with voice and embedding prices.",
    words: [
      "model",
      "models",
      "llm",
      "price",
      "prices",
      "per million tokens",
      "tokens",
      "usd",
      "rupees",
      "inr",
      "billed in rupees",
      "cached input",
      "attest",
      "tts",
      "voice price",
      "embedding",
    ],
  },
  in_call_data_use: {
    title: "In-call data use",
    detail: "Whether callers' speech may go through our own model's key: the attestation our own model needs.",
    words: ["in-call", "in call", "caller speech", "own model", "gemini", "google", "data use", "training", "attestation"],
  },
  dashboard_data_use: {
    title: "Dashboard AI data use",
    detail: "Which AI providers Pip and the dashboard assists may run on (Gemini first), and their data-use attestations.",
    words: ["dashboard ai", "assistant", "pip", "data use", "training", "attestation", "provider"],
  },
  server_only_keys: {
    title: "Server-only keys",
    detail: "Settings and keys only the server's environment can hold.",
    words: ["server", "environment", "env", "bootstrap", "server only", "ssh", "restart"],
  },
};

/** Extra names a panel lists, read from its own data: model ids and labels. */
export interface PanelNames {
  model_pricing?: string[];
}

/**
 * Every section, served panel and credential name, as search targets. `credentialKeys` is
 * null when this viewer may not read credentials: the section is still findable, and no
 * key name is.
 */
export function searchTargets(
  config: ConfigList,
  credentialKeys: readonly string[] | null,
  panelNames: PanelNames = {},
): SearchTarget[] {
  const targets: SearchTarget[] = [];
  for (const section of servedSections(config)) {
    targets.push({
      kind: "section",
      anchor: sectionAnchor(section.id),
      section: section.id,
      title: section.label,
      detail: section.hint,
      words: [section.label, section.hint, ...section.subsections.map((sub) => sub.label)],
    });
    for (const panel of [...section.panels_before, ...section.panels_after]) {
      const known = lookup(PANEL_SEARCH, panel);
      const listed =
        panel === "model_pricing"
          ? (panelNames.model_pricing ?? [])
          : panel === "server_only_keys"
            ? config.bootstrap.flatMap((entry) => [entry.key, entry.label])
            : [];
      targets.push({
        kind: "panel",
        anchor: panelAnchor(panel),
        section: section.id,
        title: known?.title ?? panel,
        detail: known?.detail ?? "",
        words: [...(known?.words ?? [panel]), ...listed],
      });
    }
  }
  targets.push({
    kind: "section",
    anchor: sectionAnchor(CREDENTIALS_SECTION.id),
    section: CREDENTIALS_SECTION.id,
    title: CREDENTIALS_SECTION.label,
    detail: CREDENTIALS_SECTION.hint,
    words: [CREDENTIALS_SECTION.label, "credentials", "keys", "api key", "secret", "vendor key", "rotate", "key management"],
  });
  for (const key of credentialKeys ?? []) {
    targets.push({
      kind: "credential",
      anchor: credentialAnchor(key),
      section: CREDENTIALS_SECTION.id,
      title: key,
      detail: "A vendor credential. Install or replace it here; a stored key is never shown.",
      words: [key, key.replace(/_/g, " ")],
    });
  }
  return targets;
}

/** The targets every word of the query appears in (title, detail or words), in screen order. */
export function matchTargets(targets: readonly SearchTarget[], query: string): SearchTarget[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];
  return targets.filter((target) => {
    const haystack = [target.title, target.detail, ...target.words].join(" ").toLowerCase();
    return words.every((word) => haystack.includes(word));
  });
}

/**
 * The section to suggest when nothing matches: the one whose label shares a word with the
 * query, else the first served one, so "No match" always says where to look.
 */
export function suggestedSection(config: ConfigList, query: string): ScreenSection {
  const sections = screenSections(servedSections(config));
  const words = query.toLowerCase().split(/\s+/).filter((word) => word.length > 2);
  return (
    sections.find((section) =>
      words.some((word) => `${section.label} ${section.hint}`.toLowerCase().includes(word)),
    ) ?? sections[0]
  );
}
