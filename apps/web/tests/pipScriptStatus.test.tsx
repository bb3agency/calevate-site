import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PipFailed, PipWriting, elapsed, failedTitle, retryable } from "@/app/c/[slug]/campaigns/PipScriptStatus";
import type { CampaignProposal } from "@/lib/api/campaignWorkspace";

import { renderClientPage } from "./harness";

function failed(reason: string | null, note = "Pip's script still broke a call rule after its repairs."): CampaignProposal {
  return {
    id: "p1",
    status: "failed",
    requested_at: new Date().toISOString(),
    base_script: null,
    script: null,
    note,
    disclosure: null,
    left_out: [],
    reason,
  };
}

describe("Pip's campaign script when it could not be written", () => {
  it("says what went wrong and offers Try again, which asks again", async () => {
    const onRetry = vi.fn();
    await renderClientPage(
      <PipFailed
        proposal={failed("assist_answer_unusable")}
        canWrite
        retrying={false}
        dismissing={false}
        onRetry={onRetry}
        onDismiss={() => {}}
      />,
      {},
    );
    expect(screen.getByText("Pip's script broke a call rule")).toBeTruthy();
    expect(screen.getByText(/still broke a call rule after its repairs/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeTruthy();
  });

  it("sends a used-up allowance to the allowance page instead of a retry that cannot work", async () => {
    await renderClientPage(
      <PipFailed
        proposal={failed("ai_quota_exceeded", "This month's AI help is used up.")}
        canWrite
        retrying={false}
        dismissing={false}
        onRetry={() => {}}
        onDismiss={() => {}}
      />,
      {},
    );
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    expect(screen.getByRole("link", { name: "See AI allowance" }).getAttribute("href")).toContain("/ai-assist");
  });

  it("names each cause, and a cause it does not know plainly", () => {
    expect(failedTitle("stale")).toBe("Pip stopped before it finished");
    expect(failedTitle("provider_unavailable")).toBe("Pip's AI did not answer");
    expect(failedTitle("something_new")).toBe("Pip could not write the script");
    expect(retryable(null)).toBe(true);
    expect(retryable("ai_paused_platform_wide")).toBe(false);
  });
});

describe("Pip's campaign script while it is written", () => {
  it("shows the time so far and a Stop", async () => {
    const onStop = vi.fn();
    await renderClientPage(
      <PipWriting proposal={{ ...failed(null), status: "drafting", note: null }} stopping={false} onStop={onStop} />,
      {},
    );
    expect(screen.getByRole("status").textContent).toContain("Pip is writing the script");
    expect(screen.getByText(/usually about a minute/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("counts minutes and seconds, never below zero", () => {
    const start = "2026-11-15T12:00:00Z";
    expect(elapsed(start, Date.parse(start) + 75_000)).toBe("1:15");
    expect(elapsed(start, Date.parse(start) - 5_000)).toBe("0:00");
  });
});
