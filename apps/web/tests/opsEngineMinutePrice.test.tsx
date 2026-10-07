import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EngineMinutePricePanel, saleNote } from "@/app/admin/ops/EngineMinutePricePanel";
import { sectionOf } from "@/app/admin/ops/config/configSections";
import { settingLabel } from "@/app/admin/ops/config/configField";
import {
  ENGINE_MINUTE_PRICES_PATH,
  attestEngineMinuteConfirmation,
  type EngineMinutePrice,
} from "@/lib/api/engineMinutePricing";

import { renderAdminPage } from "./harness";

/**
 * The per-minute rate panel for an engine that reports no call cost (D-678, D-681).
 *
 * What it must get right: an unrecorded platform minute is a warning that nothing on the
 * platform is sold, each row says whether a client is sold that rate (the server's
 * `sold_as`, never a list kept here), and a recording goes out as an exact decimal string
 * under the step-up confirmation the route checks.
 */

function row(overrides: Partial<EngineMinutePrice>): EngineMinutePrice {
  return {
    engine: "thinnest",
    rate_key: "platform",
    inr_per_min: null,
    effective_from: null,
    attested_at: null,
    source_note: null,
    billable: false,
    sold_as: null,
    ...overrides,
  };
}

const ROWS: EngineMinutePrice[] = [
  row({ rate_key: "platform" }),
  row({ rate_key: "standard" }),
  row({
    rate_key: "premium",
    inr_per_min: "2.500000",
    effective_from: "2026-10-07T00:00:00Z",
    attested_at: "2026-10-07T00:00:00Z",
    source_note: "plan page, 7 Oct 2026",
    billable: true,
    sold_as: "Clear",
  }),
  row({ rate_key: "studio" }),
];

const ALLOWED = { allowed: true, reason: null };

describe("EngineMinutePricePanel", () => {
  it("warns that nothing is sold while the platform minute is unrecorded", async () => {
    renderAdminPage(<EngineMinutePricePanel access={ALLOWED} />, {
      [ENGINE_MINUTE_PRICES_PATH]: { prices: ROWS, as_of: "2026-10-07T06:30:00Z" },
    });
    expect(
      await screen.findByText("No platform rate recorded — no minute on it can be sold"),
    ).toBeTruthy();
    expect(screen.getByText("Sold to clients as Clear.")).toBeTruthy();
    expect(screen.getAllByText("Not sold to clients — recorded for cost only.")).toHaveLength(2);
  });

  it("records a rate as a decimal string under the route's step-up", async () => {
    const { calls } = renderAdminPage(<EngineMinutePricePanel access={ALLOWED} />, {
      [ENGINE_MINUTE_PRICES_PATH]: { prices: ROWS, as_of: "2026-10-07T06:30:00Z" },
      [`POST ${ENGINE_MINUTE_PRICES_PATH}/thinnest/platform`]: row({
        inr_per_min: "1.000000",
        billable: true,
      }),
    });
    const buttons = await screen.findAllByRole("button", { name: "Record a rate" });
    fireEvent.click(buttons[0]);
    fireEvent.change(screen.getByLabelText("Rupees per billed minute"), {
      target: { value: "1.00" },
    });
    fireEvent.change(screen.getByLabelText(/Read from/), {
      target: { value: "plan page, 7 Oct 2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Record the rate" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST")).toBe(true),
    );
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe(`${ENGINE_MINUTE_PRICES_PATH}/thinnest/platform`);
    expect(JSON.parse(post?.body ?? "null")).toEqual({
      inr_per_min: "1.00",
      source_note: "plan page, 7 Oct 2026",
    });
    expect(post?.headers["X-Confirm-Action"]).toBe(
      attestEngineMinuteConfirmation("thinnest", "platform"),
    );
  });

  it("disables recording for an operator without the permission, and says why", async () => {
    renderAdminPage(
      <EngineMinutePricePanel access={{ allowed: false, reason: "Needs platform:config." }} />,
      { [ENGINE_MINUTE_PRICES_PATH]: { prices: ROWS, as_of: "2026-10-07T06:30:00Z" } },
    );
    const buttons = await screen.findAllByRole("button", { name: /Record a/ });
    for (const button of buttons) expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Needs platform:config.")).toBeTruthy();
  });
});

describe("saleNote", () => {
  it("names the platform minute as the gate rather than a product", () => {
    expect(saleNote(row({ rate_key: "platform" }))).toMatch(/needed before any voice/);
  });
});

describe("ThinnestAI settings on the configuration screen", () => {
  it("land in Calling with a plain label", () => {
    for (const key of [
      "thinnest_api_key",
      "thinnest_api_base_url",
      "thinnest_byok_enabled",
      "thinnest_max_concurrent_calls",
    ]) {
      expect(sectionOf(key)).toBe("calling");
      expect(settingLabel(key)).toMatch(/ThinnestAI/);
    }
  });
});
