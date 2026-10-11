import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CallQualityCard } from "@/app/c/[slug]/calls/[callId]/CallQualityCard";
import type { CallDetail } from "@/lib/api/client";

/**
 * "How the call went" on the admin view of a call (D-736): the voice platform's figures and
 * the problems it reported while the call was live, in words that name no provider. A figure
 * the platform could not measure is left out, never shown as zero.
 */

function detail(
  over: Partial<Pick<CallDetail, "quality" | "signals">>,
): Pick<CallDetail, "quality" | "signals"> {
  return { quality: null, signals: [], ...over };
}

describe("CallQualityCard", () => {
  it("shows the figures and the problems, and leaves out what was not measured", () => {
    render(
      <CallQualityCard
        detail={detail({
          quality: {
            turns: 14,
            reply_ms_median: 1180,
            reply_ms_p90: 1920,
            reply_ms_max: 3410,
            first_token_ms_median: 610,
            long_silences: 1,
            longest_silence_s: 12.4,
            interruptions: 2,
            model_errors: null,
            backup_answers: 1,
          },
          signals: [
            { kind: "slow_reply", occurred_at: "2026-10-11T09:00:00Z" },
            { kind: "lead_captured", occurred_at: null },
          ],
        })}
      />,
    );
    expect(screen.getByText("How the call went")).toBeTruthy();
    expect(screen.getByText("1.2 s / 1.9 s / 3.4 s")).toBeTruthy();
    expect(screen.getByText("1 (longest 12.4 s)")).toBeTruthy();
    expect(screen.getByText(/A reply took more than five seconds/)).toBeTruthy();
    expect(screen.getByText(/took down the caller's details/)).toBeTruthy();
    expect(screen.queryByText("Replies that failed")).toBeNull();
    expect(document.body.textContent).not.toMatch(/thinnest|cartesia|sarvam/i);
  });

  it("renders nothing for a call the platform reported nothing about", () => {
    const { container } = render(<CallQualityCard detail={detail({})} />);
    expect(container.textContent).toBe("");
  });
});
