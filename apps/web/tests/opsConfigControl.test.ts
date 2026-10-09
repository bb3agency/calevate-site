import { describe, expect, it } from "vitest";

import {
  appliesCopy,
  compareDecimal,
  confirmPhrase,
  controlKind,
  displayValue,
  draftOf,
  optionText,
  serverFieldMessage,
  settingState,
  validateDraft,
  valueOf,
} from "@/app/admin/ops/config/configControl";
import type { ConfigField } from "@/lib/api/opsConfig";

import { SELF_SERVE_PRICE_META, control, option } from "./fixtures/opsConfig";

/**
 * How a setting is shown and edited, from the control the server serves (D-704): values in
 * human form, drafts that round-trip without a float touching money, checks while typing,
 * and a confirmation phrase that names what is about to apply.
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

const seconds = field({
  key: "trial_call_max_seconds",
  kind: "integer",
  value: 180,
  default: 180,
  control: control("duration", { unit: "seconds", minimum: "60", maximum: "1200", step: "1" }),
});
const yesNo = field({ key: "healer_enabled", kind: "boolean", value: true, default: true, control: control("switch") });
const plan = field({
  key: "thinnest_customer_plan",
  kind: "enum",
  value: "payg",
  default: "payg",
  options: [option("payg", "Pay as you go"), option("pro", "Pro", { hint: "Up to 100 client workspaces." })],
  control: control("select"),
});
const share = field({
  key: "inbound_reserve_ratio",
  kind: "number",
  value: 0.3,
  default: 0.3,
  control: control("percent", { minimum: "0", maximum: "1" }),
});
const trialNumber = field({
  key: "trial_caller_number",
  kind: "string",
  nullable: true,
  value: "+918041234567",
  default: null,
  control: control("entity_picker", { source: "trial_numbers", max_length: 13 }),
});
const playbooks = field({
  key: "healer_paused_playbooks",
  kind: "string",
  value: "",
  default: "",
  options: [option("engine_drift", "Agent settings drift repair"), option("kb_drift", "Knowledge drift check")],
  control: control("multi_select", { multiple: true }),
});

describe("showing a value", () => {
  it("says it the way a person reads it", () => {
    expect(displayValue(field(), "4.00")).toBe("₹4.00 per minute");
    expect(displayValue(seconds, 180)).toBe("3 minutes");
    expect(displayValue(yesNo, false)).toBe("Off");
    expect(displayValue(plan, "payg")).toBe("Pay as you go");
    expect(displayValue(share, 0.3)).toBe("30%");
    expect(displayValue(trialNumber, "+918041234567")).toBe("+91 80412 34567");
    expect(displayValue(trialNumber, null)).toBe("Not set");
    expect(displayValue(playbooks, "kb_drift,engine_drift")).toBe(
      "Knowledge drift check, Agent settings drift repair",
    );
    expect(displayValue(playbooks, "")).toBe("None");
  });

  it("labels an option with its provider and the default, never the raw id alone", () => {
    expect(optionText(plan, plan.options[0])).toBe("Pay as you go · default");
    const model = option("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite", {
      provider: "google",
      unavailable_reason: "no key",
    });
    expect(optionText(field({ options: [model], default: model.value }), model)).toBe(
      "Gemini 2.5 Flash Lite · Google Gemini · default · not available to clients yet",
    );
  });

  it("states the setting's state in plain words", () => {
    expect(settingState(field()).label).toBe("Default");
    expect(settingState(field({ source: "env", editable: false })).label).toBe("Locked by the server");
    expect(
      settingState(field({ source: "db", updated_by: "Sri", updated_at: "2026-10-09T05:30:00Z" })).label,
    ).toMatch(/^Changed by Sri on /);
    expect(appliesCopy(field({ applies: "needs_republish" })).label).toBe(
      "Applies after agents are republished",
    );
    expect(appliesCopy(field({ applies: "teleport" })).label).toBe("Timing not known");
  });

  it("falls back to text for a control kind this build does not know", () => {
    expect(controlKind(field({ control: control("colour_wheel") }))).toBe("unknown");
  });
});

describe("drafts round-trip to the value sent", () => {
  it("keeps money a string and converts what is unambiguous", () => {
    expect(valueOf(field(), "7.25")).toBe("7.25");
    expect(valueOf(seconds, "240")).toBe(240);
    expect(valueOf(yesNo, "false")).toBe(false);
    expect(draftOf(share, 0.3)).toBe("30");
    expect(valueOf(share, "45")).toBe(0.45);
    expect(valueOf(trialNumber, "")).toBeNull();
    expect(valueOf(playbooks, "kb_drift,,kb_drift, engine_drift")).toBe("kb_drift,engine_drift");
    expect(valueOf(playbooks, "")).toBe("");
  });

  it("stores an Indian mobile with its country code", () => {
    const phone = field({ nullable: true, control: control("phone_in") });
    expect(draftOf(phone, "+919876543210")).toBe("9876543210");
    expect(valueOf(phone, "98765 43210")).toBe("+919876543210");
    expect(validateDraft(phone, "98765")).toMatch(/ten-digit/);
  });
});

describe("checking while typing", () => {
  it("applies the served bounds exactly, without a float", () => {
    expect(validateDraft(seconds, "30")).toBe("Must be at least 60 seconds.");
    expect(validateDraft(seconds, "1500")).toBe("Must be at most 1,200 seconds.");
    expect(validateDraft(seconds, "2.5")).toBe("Use a whole number.");
    expect(validateDraft(seconds, "600")).toBeNull();
    expect(validateDraft(field(), "0")).toBe("Must be more than ₹0.00.");
    expect(validateDraft(field(), "4.505")).toMatch(/rupees/);
    expect(validateDraft(share, "120")).toBe("Must be at most 100%.");
    expect(compareDecimal("10.10", "10.1")).toBe(0);
    expect(compareDecimal("9.99", "10")).toBe(-1);
  });

  it("checks the server's own pattern and the shape of an address", () => {
    const url = field({ kind: "string", control: control("url", { pattern: "^https://[^\\s]+$" }) });
    expect(validateDraft(url, "api.calevate.tech")).toMatch(/full address/);
    expect(validateDraft(url, "http://api.calevate.tech")).toBe("Not in the right format.");
    expect(validateDraft(url, "https://api.calevate.tech")).toBeNull();
  });

  it("says the server's refusal in words rather than a validator rule", () => {
    const refusal = { fields: [{ field: "trial_caller_number", rule: "string_pattern_mismatch", message: "String should match pattern" }] };
    expect(serverFieldMessage(trialNumber, refusal)).toBe("Not in the right format.");
    expect(serverFieldMessage(seconds, refusal)).toBeNull();
  });
});

describe("the confirmation phrase", () => {
  it("is the value about to apply, so it changes with every change", () => {
    expect(confirmPhrase(field(), "7.25")).toBe("7.25");
    expect(confirmPhrase(yesNo, false)).toBe("Off");
    expect(confirmPhrase(plan, "pro")).toBe("Pro");
    expect(confirmPhrase(trialNumber, null)).toBe("Not set");
  });
});
