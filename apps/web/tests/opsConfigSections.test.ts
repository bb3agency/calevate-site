import { describe, expect, it } from "vitest";

import {
  differsFromDefault,
  filterAcrossSections,
  groupFields,
  matchesFilter,
  screenSections,
  servedSections,
} from "@/app/admin/ops/config/configSections";
import type { ConfigField, ConfigList } from "@/lib/api/opsConfig";

import { OPS_CONFIG_SECTIONS, SELF_SERVE_PRICE_META, placed } from "./fixtures/opsConfig";

/**
 * The arithmetic behind the platform configuration screen, without a render: where a
 * setting is placed, and what search finds. How a value is shown and edited is
 * `opsConfigControl.test.ts`.
 */

function field(over: Partial<ConfigField> = {}): ConfigField {
  return {
    key: "self_serve_inr_per_min",
    env_var: "SELF_SERVE_INR_PER_MIN",
    value: "4.00",
    source: "default",
    default: "4.00",
    has_default: true,
    kind: "decimal",
    options: [],
    editable: true,
    applies: "live",
    caveat: null,
    etag: '"0"',
    updated_by: null,
    updated_at: null,
    note: null,
    ...SELF_SERVE_PRICE_META,
    ...over,
  };
}

function list(fields: ConfigField[]): ConfigList {
  return {
    fields,
    sections: OPS_CONFIG_SECTIONS,
    bootstrap: [],
    config_version: 1,
    stale: false,
    never_loaded: false,
    config_changed_at: null,
  };
}

describe("placement", () => {
  it("adds credentials after the served sections, and a fallback when none were served", () => {
    expect(screenSections(OPS_CONFIG_SECTIONS).at(-1)?.id).toBe("credentials");
    expect(screenSections(undefined).map((s) => s.id)).toEqual(["settings", "credentials"]);
  });

  it("adds Other only when a field names a section that was not served", () => {
    expect(servedSections(list([field()])).some((s) => s.id === "unfiled")).toBe(false);
    const orphan = field({ key: "x", ...placed("nowhere", "x", "X") });
    expect(servedSections(list([field(), orphan])).at(-1)?.id).toBe("unfiled");
  });

  it("keeps a field whose subsection was not served, in a trailing group", () => {
    const section = OPS_CONFIG_SECTIONS.find((s) => s.id === "billing");
    if (!section) throw new Error("fixture lost billing");
    const { groups } = groupFields(section, [field(), field({ key: "y", subsection: "later" })]);
    expect(groups.map((g) => g.label)).toEqual(["Prices", "More settings"]);
  });
});

describe("search and the changed filter", () => {
  it("compares values as the server serialised them", () => {
    expect(differsFromDefault(field())).toBe(false);
    expect(differsFromDefault(field({ value: "4.50" }))).toBe(true);
    expect(differsFromDefault(field({ has_default: false, default: null }))).toBe(false);
  });

  it("matches every word against label, key, variable, description, section and value", () => {
    const f = field();
    const filter = (query: string) => ({ query, changedOnly: false });
    expect(matchesFilter(f, filter("self serve"), "Billing")).toBe(true);
    expect(matchesFilter(f, filter("SELF_SERVE_INR"), "Billing")).toBe(true);
    expect(matchesFilter(f, filter("billing 4.00"), "Billing")).toBe(true);
    expect(matchesFilter(f, filter("price carrier"), "Billing")).toBe(false);
  });

  it("groups matches by section in section order", () => {
    const bucket = field({
      key: "object_store_bucket",
      env_var: "OBJECT_STORE_BUCKET",
      ...placed("infrastructure", "storage", "Storage bucket"),
    });
    const groups = filterAcrossSections(list([bucket, field()]), {
      query: "",
      changedOnly: false,
    });
    expect(groups.map((g) => g.section.id)).toEqual(["billing", "infrastructure"]);
  });
});
