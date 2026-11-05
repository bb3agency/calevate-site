import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LiveApplyLine } from "@/app/admin/ops/config/LiveApplyStatus";
import type { LiveApplyRun } from "@/lib/api/opsLiveApply";

/**
 * A7-15: "Queued: live agents are about to be updated" sat beside a spinner for 22 hours,
 * naming a raw setting key that no longer existed.
 */

const RUN: LiveApplyRun = {
  id: "0192f0aa-7777-7000-8000-0000000000d1",
  scope: "platform",
  tenant_id: null,
  agent_id: null,
  reasons: ["ai_notice_introduces_agent"],
  reason_labels: ["A setting that has since been removed"],
  not_started: false,
  not_started_after_minutes: 12,
  status: "pending",
  total: null,
  applied: 0,
  failed: 0,
  retrying: 0,
  failures: [],
  created_at: "2026-11-04T15:35:00Z",
  finished_at: null,
  superseded_by: null,
};

describe("the live-apply line", () => {
  it("names the change in words, never the raw key", () => {
    const { container } = render(<LiveApplyLine run={RUN} />);
    expect(container.textContent).toContain("A setting that has since been removed");
    expect(container.textContent).not.toContain("ai_notice_introduces_agent");
  });

  it("says a run the worker never picked up has not started, without a spinner", () => {
    const { container } = render(<LiveApplyLine run={{ ...RUN, not_started: true }} />);
    expect(screen.getByText(/Not started after 12 minutes/)).toBeTruthy();
    expect(container.textContent).toContain("Check the background worker.");
    expect(container.querySelector(".animate-spin")).toBeNull();
  });
});
