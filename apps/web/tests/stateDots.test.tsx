import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { dueSoon } from "@/app/c/[slug]/callbacks/CallbacksScreen";
import { STATUSES } from "@/app/c/[slug]/leads/StatusSelect";
import { LEAD_STAGE_DOT, StatusBadge } from "@/components/ui";

describe("lead stage dots", () => {
  it("gives every stage its own dot", () => {
    expect(Object.keys(LEAD_STAGE_DOT).sort()).toEqual([...STATUSES].sort());
    const dots = STATUSES.map((stage) => LEAD_STAGE_DOT[stage]);
    expect(new Set(dots).size).toBe(dots.length);
  });

  it("draws the stage's dot beside the word, which still says the stage", () => {
    const { container } = render(<StatusBadge value="interested" />);
    expect(container.querySelector("span[aria-hidden]")?.className).toContain("bg-series-2");
    expect(container.textContent).toBe("Interested");
  });
});

describe("a waiting call-back's due mark", () => {
  const now = new Date("2026-11-03T10:00:00Z");
  const row = (requested_at: string, extra: Partial<{ status: string; held: boolean }> = {}) => ({
    status: "scheduled",
    held: false,
    requested_at,
    ...extra,
  });

  it("says nothing for one more than an hour away", () => {
    expect(dueSoon(row("2026-11-03T11:30:00Z"), now)).toBeNull();
  });

  it("counts down within the hour", () => {
    expect(dueSoon(row("2026-11-03T10:25:00Z"), now)).toEqual({ overdue: false, words: "In 25 min" });
  });

  it("says overdue once its time has passed", () => {
    expect(dueSoon(row("2026-11-03T09:50:00Z"), now)).toEqual({ overdue: true, words: "Overdue" });
  });

  it("says nothing for one that is held, ringing or settled", () => {
    expect(dueSoon(row("2026-11-03T09:50:00Z", { held: true }), now)).toBeNull();
    expect(dueSoon(row("2026-11-03T09:50:00Z", { status: "dialing" }), now)).toBeNull();
    expect(dueSoon(row("2026-11-03T09:50:00Z", { status: "completed" }), now)).toBeNull();
  });
});
