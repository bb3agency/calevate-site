import { focusManager } from "@tanstack/react-query";
import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import AlertsPage from "@/app/admin/ops/alerts/page";
import type { AlertEpisode, AlertReport } from "@/lib/api/alerts";

import { problem, renderAdminPage } from "./harness";

/** Frontend audit round 5, lane Y8 (admin operations): cases not owned by another suite. */

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-8888-7000-8000-0000000000a8",
  role: "superadmin",
  permissions: ["ops:manage"],
};

const STOPPED: AlertEpisode = {
  id: "0192f0aa-9999-7000-8000-0000000000y8",
  code: "webhook_delivery_failed",
  stage: "WORKER_DELIVERY",
  severity: "attention",
  service: "workers",
  detail: null,
  ids: {},
  first_seen_at: "2026-11-09T03:51:00Z",
  last_seen_at: "2026-11-09T04:51:00Z",
  occurrences: 3,
  emailed: false,
  emailed_at: null,
  cleared_at: "2026-11-09T05:51:00Z",
};

const QUIET: AlertReport = {
  window_days: 7,
  episodes: [STOPPED],
  open_by_severity: {},
  open_unmailed_pages: 0,
  complete: true,
};

afterEach(() => focusManager.setFocused(undefined));

/** Make every query refetch, as the board's own poll or a returning tab does. */
function refocus() {
  focusManager.setFocused(false);
  focusManager.setFocused(true);
}

describe("the alert board when a later read fails", () => {
  it("withdraws its all-clear instead of showing the last answer as current", async () => {
    let failing = false;
    renderAdminPage(<AlertsPage />, {
      [ADMIN_ME_PATH]: ME,
      "/v1/ops/alerts?days=7": () =>
        failing
          ? problem(503, { title: "Service unavailable", detail: "The alert store is not reachable.", retryable: true })
          : QUIET,
    });
    await screen.findByText("Nothing is happening right now");

    failing = true;
    refocus();

    await screen.findByText("The alert store is not reachable.");
    // An alarm may have started since the last good read; "nothing is happening" and a row
    // of zeroes are claims the board can no longer make.
    expect(screen.queryByText("Nothing is happening right now")).toBeNull();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});
