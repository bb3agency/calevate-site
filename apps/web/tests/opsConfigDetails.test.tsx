import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConfigRow } from "@/app/admin/ops/config/ConfigRow";
import type { ConfigField } from "@/lib/api/opsConfig";

import { SELF_SERVE_PRICE_META } from "./fixtures/opsConfig";
import { renderAdminPage } from "./harness";

/**
 * A7-13: a setting's description is one line; what an engineer needs (a vendor's field name,
 * a vendor figure with its source and date) moved to `details`, shown under Details.
 */

const FIELD: ConfigField = {
  key: "thinnest_max_concurrent_calls",
  env_var: "THINNEST_MAX_CONCURRENT_CALLS",
  value: 5,
  source: "default",
  default: 5,
  has_default: true,
  kind: "integer",
  options: [],
  editable: true,
  applies: "live",
  caveat: null,
  etag: '"0"',
  updated_by: null,
  updated_at: null,
  note: null,
  ...SELF_SERVE_PRICE_META,
  label: "Simultaneous calls on the ThinnestAI workspace",
  description: "Calls at once across every client, inbound and outbound. Set what ThinnestAI granted.",
  details: "ThinnestAI set 20 on our pay-as-you-go account on 23 Oct 2026 (VENDOR-STATED).",
};

describe("a console setting", () => {
  it("shows one line, and the rest under Details", () => {
    renderAdminPage(<ConfigRow field={FIELD} access={{ allowed: true, reason: null }} />, {});
    expect(screen.getByText(FIELD.description)).toBeTruthy();
    expect(screen.getByText(FIELD.details ?? "")).toBeTruthy();
  });
});
