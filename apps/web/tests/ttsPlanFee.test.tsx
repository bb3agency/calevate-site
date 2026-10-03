import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TtsPlanFeePanel } from "@/app/admin/ops/TtsPlanFeePanel";
import {
  TTS_PLAN_FEES_PATH,
  ttsPlanFeeConfirmation,
  type TtsPlanFees,
  type TtsPlanFeeWrite,
} from "@/app/admin/ops/ttsPlanFee";

import { problem, stubApi, type Routes } from "./harness";

/**
 * The operator's half of the spend board's voice cost model: `POST
 * /v1/ops/tts-prices/{provider}/plan-fee` records what a plan-billed voice vendor invoiced
 * for one month, under a step-up header bound to the vendor and the month, and this panel
 * is the only place in the console that can record it.
 */

type Access = { allowed: boolean; reason: string | null };

const ALLOWED: Access = { allowed: true, reason: null };
const DENIED = {
  allowed: false,
  reason: "Your admin account does not have permission to change platform pricing.",
};

const ATTESTED = {
  provider: "cartesia",
  tier_label: "Studio",
  month: "2026-09",
  plan_inr: "440.00",
  effective_from: "2026-10-02T06:30:00Z",
  attested_at: "2026-10-02T06:30:00Z",
  attested_by: "00000000-0000-7000-8000-0000000000a1",
  source_note: "Cartesia Pro plan, invoice INV-2026-09-014",
  reference_plan_inr: "440.00",
};

function fees(month: string, attested: typeof ATTESTED | null): TtsPlanFees {
  return {
    month,
    as_of: "2026-10-02T06:30:00Z",
    fees: [
      {
        provider: "cartesia",
        tier_label: "Studio",
        reference_plan_inr: "440.00",
        attested,
      },
    ],
  };
}

const WRITTEN: TtsPlanFeeWrite = { plan_fee: ATTESTED, as_of: "2026-10-02T06:30:00Z" };

function renderPanel(routes: Routes, access: Access = ALLOWED) {
  const calls = stubApi(routes);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <TtsPlanFeePanel access={access} />
    </QueryClientProvider>,
  );
  return calls;
}

describe("the voice plan-fee panel", () => {
  it("says plainly when a month has no fee recorded", async () => {
    renderPanel({ [TTS_PLAN_FEES_PATH]: fees("2026-10", null) });
    expect(await screen.findByText("No fee recorded for 2026-10")).toBeTruthy();
    expect(screen.getByText("Studio voice (cartesia)")).toBeTruthy();
  });

  it("prints the attested fee from the server's string, with its invoice", async () => {
    renderPanel({ [TTS_PLAN_FEES_PATH]: fees("2026-09", ATTESTED) });
    expect(await screen.findByText("₹440.00")).toBeTruthy();
    expect(screen.getByText("Cartesia Pro plan, invoice INV-2026-09-014")).toBeTruthy();
  });

  it("sends the typed fee as a string, with the step-up header bound to vendor and month", async () => {
    const calls = renderPanel({
      [`GET ${TTS_PLAN_FEES_PATH}`]: fees("2026-09", null),
      "POST /v1/ops/tts-prices/cartesia/plan-fee": WRITTEN,
    });
    fireEvent.click(await screen.findByRole("button", { name: "Record this month's fee" }));
    fireEvent.change(screen.getByLabelText(/Rupees for the whole month/), {
      target: { value: "440.00" },
    });
    fireEvent.change(screen.getByLabelText(/Read from/), {
      target: { value: "Cartesia Pro plan, invoice INV-2026-09-014" },
    });
    const save = screen.getByRole("button", { name: "Record the fee" });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: "2026-09" } });
    fireEvent.click(save);

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/v1/ops/tts-prices/cartesia/plan-fee");
    expect(post?.headers["X-Confirm-Action"]).toBe(ttsPlanFeeConfirmation("cartesia", "2026-09"));
    expect(post?.headers["X-Confirm-Action"]).toBe("attest_tts_plan_fee:cartesia:2026-09");
    expect(JSON.parse(post?.body ?? "{}")).toEqual({
      month: "2026-09",
      plan_inr: "440.00",
      source_note: "Cartesia Pro plan, invoice INV-2026-09-014",
    });
    expect(await screen.findByText(/compares this fee with the month/i)).toBeTruthy();
  });

  it("asks for the month the operator picks", async () => {
    const calls = renderPanel({
      [TTS_PLAN_FEES_PATH]: fees("2026-10", null),
      [`${TTS_PLAN_FEES_PATH}?month=2026-08`]: fees("2026-08", null),
    });
    const picker = await screen.findByLabelText("Billing month");
    fireEvent.change(picker, { target: { value: "2026-08" } });
    expect(await screen.findByText("No fee recorded for 2026-08")).toBeTruthy();
    expect(calls.some((c) => c.path === `${TTS_PLAN_FEES_PATH}?month=2026-08`)).toBe(true);
  });

  it("keeps the control closed, with the reason, for an operator without the permission", async () => {
    renderPanel({ [TTS_PLAN_FEES_PATH]: fees("2026-09", ATTESTED) }, DENIED);
    const open = await screen.findByRole("button", { name: "Correct this month's fee" });
    expect((open as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(DENIED.reason)).toBeTruthy();
  });

  it("shows the server's refusal when the read fails", async () => {
    renderPanel({ [TTS_PLAN_FEES_PATH]: problem(503, { title: "Dependency unavailable" }) });
    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
