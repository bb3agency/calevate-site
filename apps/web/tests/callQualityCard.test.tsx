import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CallQualityCard } from "@/app/c/[slug]/calls/[callId]/CallQualityCard";
import type { CallDetail } from "@/lib/api/client";

/**
 * "How the call went" (D-736, D-902): all of the voice platform's figures and each turn's
 * wait for an operator viewing the call as the client; only the wait for an answer and the
 * knowledge lookups for the client. Words name no provider, and a figure the platform could
 * not measure is left out, never shown as zero.
 */

type Detail = Pick<CallDetail, "quality" | "signals" | "timeline">;

function detail(over: Partial<Detail>): Detail {
  return { quality: null, signals: [], timeline: null, ...over };
}

const TURN: NonNullable<CallDetail["timeline"]>[number] = {
  turn: 2,
  first_sound_ms: 900,
  first_sound_kind: "filler",
  answer_ms: 2150,
  answer_estimated: true,
  wait_before_decision_ms: 480,
  recogniser_ms: 210,
  ear_check_ms: null,
  model_first_sentence_ms: 1320,
  voice_ms: 350,
  model_asked_ms: -120,
};

describe("CallQualityCard", () => {
  it("shows an operator the figures and the problems, and leaves out what was not measured", () => {
    render(
      <CallQualityCard
        operator
        detail={detail({
          quality: {
            turns: 14,
            answer_ms_median: 1480,
            answer_ms_p90: 2310,
            answer_ms_max: 3900,
            reply_ms_median: 1180,
            reply_ms_p90: 1920,
            reply_ms_max: 3410,
            first_token_ms_median: 610,
            long_silences: 1,
            longest_silence_s: 12.4,
            interruptions: 2,
            model_errors: null,
            backup_answers: 1,
            knowledge_turns: 3,
          },
          signals: [
            { kind: "slow_reply", occurred_at: "2026-10-11T09:00:00Z" },
            { kind: "lead_captured", occurred_at: null },
          ],
        })}
      />,
    );
    expect(screen.getByText("How the call went")).toBeTruthy();
    expect(screen.getByText("Wait for an answer (typical / slow / longest)")).toBeTruthy();
    expect(screen.getByText("1.5 s / 2.3 s / 3.9 s")).toBeTruthy();
    expect(screen.getByText("1.2 s / 1.9 s / 3.4 s")).toBeTruthy();
    expect(screen.getByText("Replies that looked up knowledge")).toBeTruthy();
    expect(screen.getByText("1 (longest 12.4 s)")).toBeTruthy();
    expect(screen.getByText(/A reply took over 5 seconds/)).toBeTruthy();
    expect(screen.getByText(/took the caller's details/)).toBeTruthy();
    expect(screen.queryByText("Replies that failed")).toBeNull();
    expect(document.body.textContent).not.toMatch(/thinnest|cartesia|sarvam/i);
  });

  it("gives an operator each turn's wait step by step and marks an estimated answer", () => {
    render(<CallQualityCard operator detail={detail({ timeline: [TURN] })} />);
    const table = screen.getByRole("table");
    expect(table.textContent).toContain("2,150 est.");
    expect(table.textContent).toContain("900 filler");
    expect(table.textContent).toContain("-120");
    // The Ear check did not happen off Ear: a dash, never zero.
    const cells = Array.from(table.querySelectorAll("tbody td")).map((c) => c.textContent);
    expect(cells).toContain("–");
    expect(cells).not.toContain("0");
  });

  it("shows a call from before answer times without an answer row rather than zero", () => {
    render(
      <CallQualityCard operator detail={detail({ quality: { reply_ms_median: 900, answer_ms_median: null } })} />,
    );
    expect(screen.queryByText(/Wait for an answer/)).toBeNull();
    expect(screen.getByText("First sound, a filler included (typical / slow / longest)")).toBeTruthy();
  });

  it("shows a client only the wait for an answer and the lookups, never the split", () => {
    const { container } = render(
      <CallQualityCard
        detail={detail({
          quality: {
            turns: 9,
            answer_ms_median: 1480,
            reply_ms_median: 900,
            knowledge_turns: 3,
            interruptions: 2,
            lookups_needed: 2,
            lookups_needed_done_min: 2,
            lookups_needed_done_max: 2,
          },
          signals: [{ kind: "slow_reply", occurred_at: null }],
          timeline: [TURN],
        })}
      />,
    );
    expect(screen.getByText("Typical wait for an answer")).toBeTruthy();
    expect(screen.getByText("1.5 s")).toBeTruthy();
    expect(screen.getByText("Looked up your information when it was needed")).toBeTruthy();
    expect(screen.getByText("2 of 2")).toBeTruthy();
    // Never a share of every reply: "3 of 9" read as a failure on a step-by-step call.
    expect(screen.queryByText("3 of 9")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(container.textContent).not.toMatch(/first sound|filler|five seconds|talked over/i);
  });

  it("says no reply needed a lookup on a step-by-step call, never 0 of 0", () => {
    const { container } = render(
      <CallQualityCard
        detail={detail({
          quality: {
            turns: 12,
            knowledge_turns: 0,
            lookups_needed: 0,
            lookups_needed_done_min: 0,
            lookups_needed_done_max: 0,
          },
        })}
      />,
    );
    expect(screen.getByText("No reply needed a lookup.")).toBeTruthy();
    expect(container.textContent).not.toMatch(/of 0|of 12/);
  });

  it("shows 0 of 1 when a stuck caller got no lookup, and 1 of 1 when a question did", () => {
    const stuck = render(
      <CallQualityCard
        detail={detail({
          quality: { knowledge_turns: 0, lookups_needed: 1, lookups_needed_done_min: 0, lookups_needed_done_max: 0 },
        })}
      />,
    );
    expect(stuck.getByText("0 of 1")).toBeTruthy();
    stuck.unmount();
    render(
      <CallQualityCard
        detail={detail({
          quality: { knowledge_turns: 1, lookups_needed: 1, lookups_needed_done_min: 1, lookups_needed_done_max: 1 },
        })}
      />,
    );
    expect(screen.getByText("1 of 1")).toBeTruthy();
  });

  it("says up to when the count cannot say which replies looked up, and leaves out an unmeasured one", () => {
    const range = render(
      <CallQualityCard
        detail={detail({
          quality: { knowledge_turns: 2, lookups_needed: 2, lookups_needed_done_min: 0, lookups_needed_done_max: 2 },
        })}
      />,
    );
    expect(range.getByText("Up to 2 of 2")).toBeTruthy();
    range.unmount();
    render(<CallQualityCard detail={detail({ quality: { answer_ms_median: 900, lookups_needed: 1 } })} />);
    expect(screen.queryByText("Looked up your information when it was needed")).toBeNull();
  });

  it("renders nothing for a call the platform reported nothing about", () => {
    const { container } = render(<CallQualityCard operator detail={detail({})} />);
    expect(container.textContent).toBe("");
    const client = render(<CallQualityCard detail={detail({ quality: { reply_ms_median: 900 } })} />);
    expect(client.container.textContent).toBe("");
  });
});
