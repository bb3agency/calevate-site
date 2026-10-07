import type { ConfigField, ConfigList, ConfigSection } from "@/lib/api/opsConfig";

import { display } from "./configField";

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
    display(field.value),
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
