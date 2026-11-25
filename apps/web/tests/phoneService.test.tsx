import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { UseMutationResult } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { EngineHealthPanel } from "@/app/admin/ops/EngineHealthPanel";
import { TestCallForm } from "@/app/c/[slug]/campaigns/CampaignBoosters";
import { CampaignStatusPill } from "@/app/c/[slug]/campaigns/campaignStatus";
import { PhoneServiceBanner } from "@/components/phoneService";
import { ProblemNotice } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import {
  SAVED_GOES_LIVE_LATER,
  TEST_CALLS_PAUSED,
  isSavedGoesLiveLater,
} from "@/lib/api/phoneServiceCodes";

import { expectNoA11yViolations } from "./a11y";
import { renderAdminPage, renderClientPage } from "./harness";

/**
 * What an owner sees while the phone service is not answering, and that it all goes away
 * when it answers. The backend owns the state (`tests/engine_outage_test.py`); these assert
 * the words and the buttons, and that no provider is named on any of them.
 */

vi.mock("@/lib/api/trialCalls", async (original) => ({
  ...(await original<typeof import("@/lib/api/trialCalls")>()),
  useTestRingsFrom: () => ({ data: undefined }),
}));

const DOWN = { state: "not_answering", since: "2026-11-25T18:53:00Z" };
const UP = { state: "answering", since: null };
const PROVIDER = /thinnest|vendor|engine/i;

describe("the calls-paused banner", () => {
  it("says calls are paused in one line, with the rest behind Details", async () => {
    const view = await renderClientPage(<PhoneServiceBanner />, { "/v1/phone-service": DOWN });
    const status = await view.findByRole("status");
    expect(status.textContent).toContain("Calls are paused: our phone service is not answering.");
    expect(status.textContent).toContain("Your calls resume by themselves.");
    const details = view.getByRole("button", { name: "Details" });
    expect(details.getAttribute("aria-expanded")).toBe("false");
    expect(view.getByText(/Calls to your own numbers may not connect/).closest("ul")?.hidden).toBe(true);
    fireEvent.click(details);
    expect(view.getByRole("button", { name: "Hide details" }).getAttribute("aria-expanded")).toBe("true");
    const list = view.getByText(/Calls to your own numbers may not connect/).closest("ul");
    expect(list?.hidden).toBe(false);
    expect(list?.textContent).toContain("Since 26 Nov");
    expect(status.textContent).not.toMatch(PROVIDER);
  });

  it("renders nothing while the phone service answers", async () => {
    const view = await renderClientPage(<PhoneServiceBanner />, { "/v1/phone-service": UP });
    await waitFor(() => expect(view.calls.some((c) => c.path === "/v1/phone-service")).toBe(true));
    expect(view.container.textContent).toBe("");
  });
});

function testForm(error: Error | null = null) {
  const call = {
    mutate: vi.fn(),
    isPending: false,
    data: undefined,
    error,
  } as unknown as UseMutationResult<
    { status: "queued" | "blocked" },
    Error,
    { number: string; numberIsMine: boolean }
  >;
  return (
    <TestCallForm
      slug="acme"
      call={call}
      saved={{ data: { numbers: ["+919000000001"] }, error: null, refetch: vi.fn() } as never}
      canWrite
    />
  );
}

describe("the test-call button", () => {
  it("is paused with its reason while the phone service is down, and presses do nothing", async () => {
    const form = testForm();
    const view = await renderClientPage(form, { "/v1/phone-service": DOWN });
    const button = await view.findByRole("button", { name: /Call me/ });
    await waitFor(() => expect(button.getAttribute("aria-disabled")).toBe("true"));
    expect(view.getByText(TEST_CALLS_PAUSED)).toBeTruthy();
    fireEvent.click(button);
    expect((form.props.call as { mutate: ReturnType<typeof vi.fn> }).mutate).not.toHaveBeenCalled();
  });

  it("is pressable while the phone service answers", async () => {
    const view = await renderClientPage(testForm(), { "/v1/phone-service": UP });
    const button = await view.findByRole("button", { name: /Call me/ });
    await waitFor(() => expect(view.calls.some((c) => c.path === "/v1/phone-service")).toBe(true));
    expect(button.getAttribute("aria-disabled")).not.toBe("true");
    expect(view.queryByText(TEST_CALLS_PAUSED)).toBeNull();
  });

  it("shows a refused press as the pause, not as a red failure", async () => {
    const refused = new ApiProblem(503, {
      type: "https://calevate.tech/problems/phone_service_down",
      title: "Test calls are paused",
      detail: "Our phone service is not answering right now.",
      kind: "dependency",
      retryable: true,
    });
    const view = await renderClientPage(testForm(refused), { "/v1/phone-service": UP });
    expect(await view.findByText(TEST_CALLS_PAUSED)).toBeTruthy();
    expect(view.queryByRole("alert")).toBeNull();
  });
});

describe("a save kept while the phone service is down", () => {
  const kept = new ApiProblem(503, {
    type: "https://calevate.tech/problems/saved_goes_live_later",
    title: "Saved",
    detail: "It goes live when our phone service answers again, usually within minutes.",
    kind: "dependency",
    retryable: true,
  });

  it("reads as one plain line, not an error", () => {
    expect(isSavedGoesLiveLater(kept)).toBe(true);
    render(<ProblemNotice error={kept} onRetry={() => undefined} />);
    const line = screen.getByRole("status");
    expect(line.textContent).toBe(SAVED_GOES_LIVE_LATER);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});

describe("a running campaign while the phone service is down", () => {
  it("waits, in words that are not the owner's pause", () => {
    render(<CampaignStatusPill status="running" phoneServiceDown />);
    expect(screen.getByText("Waiting for the phone service")).toBeTruthy();
  });

  it("an owner's pause still reads as their pause", () => {
    render(<CampaignStatusPill status="paused" pauseReason="person" phoneServiceDown />);
    expect(screen.getByText("Paused")).toBeTruthy();
  });
});

describe("the operator's engine-health panel", () => {
  it("shows since when, the run, the last error and its route", async () => {
    const view = renderAdminPage(<EngineHealthPanel />, {
      "/v1/ops/engine-health": {
        engine: "thinnest",
        failing: true,
        since: "2026-11-25T18:53:00Z",
        consecutive_failures: 14,
        outage_after_failures: 3,
        last_failure_at: "2026-11-25T18:57:00Z",
        last_kind: "unreachable",
        last_error: "ReadTimeout",
        last_route: "/calls",
        last_answer_at: null,
        recovered_at: null,
        window_minutes: 5,
        spike_threshold: 10,
        window_server_errors: 0,
        window_unreachable: 14,
        alarm_open_since: "2026-11-25T18:55:00Z",
      },
    });
    expect(await view.findByText(/Not answering since/)).toBeTruthy();
    expect(view.container.textContent).toContain("14 failed in a row");
    expect(view.getByText("ReadTimeout")).toBeTruthy();
    expect(view.getByText("/calls")).toBeTruthy();
    expect(view.container.textContent).toContain("Open since");
  });
});

describe("accessibility", () => {
  it("the banner, closed and open, and the paused button have no violations", async () => {
    const banner = await renderClientPage(<PhoneServiceBanner />, { "/v1/phone-service": DOWN });
    await banner.findByRole("status");
    await expectNoA11yViolations(banner.container, "phone service banner (closed)");
    fireEvent.click(banner.getByRole("button", { name: "Details" }));
    await expectNoA11yViolations(banner.container, "phone service banner (open)");
    banner.unmount();

    const form = await renderClientPage(testForm(), { "/v1/phone-service": DOWN });
    await form.findByText(TEST_CALLS_PAUSED);
    await expectNoA11yViolations(form.container, "paused test-call button");
  });
});
