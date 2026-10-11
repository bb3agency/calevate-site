import { describe, expect, it } from "vitest";

import {
  differsFromDefault,
  filterAcrossSections,
  groupFields,
  matchTargets,
  matchesFilter,
  screenSections,
  searchTargets,
  servedSections,
  suggestedSection,
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

describe("search beyond the settings rows", () => {
  const KEYS = ["sarvam_api_key", "cartesia_api_key", "thinnest_api_key"];
  const MODELS = ["gpt-4o-mini", "sarvam-105b", "Sarvam 105B"];
  const find = (query: string, keys: string[] | null = KEYS) =>
    matchTargets(searchTargets(list([field()]), keys, { model_pricing: MODELS }), query);

  it("finds both the Sarvam key and the Sarvam 105B price for 'sarvam'", () => {
    const hits = find("sarvam");
    expect(hits.map((hit) => [hit.kind, hit.anchor])).toEqual([
      ["panel", "config-panel-model_pricing"],
      ["credential", "credential-sarvam_api_key"],
    ]);
    expect(hits[0].section).toBe("language-models");
    expect(hits[1].section).toBe("credentials");
  });

  it("finds the Cartesia key by name", () => {
    expect(find("cartesia").map((hit) => hit.anchor)).toContain("credential-cartesia_api_key");
  });

  it("finds the exchange-rate panel for 'usd'", () => {
    const hits = find("usd");
    expect(hits.map((hit) => hit.anchor)).toContain("config-panel-fx_rate");
    expect(hits.find((hit) => hit.anchor === "config-panel-fx_rate")?.section).toBe("billing");
  });

  it("finds a section by its name, and the credentials section without its key names", () => {
    expect(find("telephony").map((hit) => hit.anchor)).toEqual(["config-section-telephony"]);
    const withheld = find("sarvam", null);
    expect(withheld.map((hit) => hit.kind)).toEqual(["panel"]);
    expect(find("credentials", null).map((hit) => hit.anchor)).toEqual([
      "config-section-credentials",
    ]);
  });

  it("indexes every served panel by its title", () => {
    for (const [query, anchor] of [
      ["rate card", "config-panel-rate_card"],
      ["engine minute", "config-panel-engine_minute_price"],
      ["number price", "config-panel-number_price"],
      ["plan fee", "config-panel-tts_plan_fee"],
      ["data use", "config-panel-dashboard_data_use"],
      ["server-only", "config-panel-server_only_keys"],
    ]) {
      expect(find(query).map((hit) => hit.anchor)).toContain(anchor);
    }
  });

  it("suggests a section to browse when nothing matches", () => {
    expect(find("zzzz")).toEqual([]);
    expect(suggestedSection(list([field()]), "zzzz").id).toBe("voice-engine");
    expect(suggestedSection(list([field()]), "billing thing").id).toBe("billing");
  });
});
