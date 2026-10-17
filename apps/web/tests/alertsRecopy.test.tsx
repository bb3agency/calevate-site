import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ADMIN_ME_PATH, type AdminMe } from "@/app/admin/access";
import AlertsPage from "@/app/admin/ops/alerts/page";
import type { AlertEpisode, AlertReport, RecordingRecopy } from "@/lib/api/alerts";

import { renderAdminRoute } from "./adminRoute";

/**
 * The recording alarms' one action (D-808): a `recording_copy_*` episode names a call, and
 * its drawer asks for that call's recording to be copied again. Pinned here: the button is
 * offered only on those alarms and only when the episode names both the client and the call,
 * it posts to that client's call, and the server's sentence is what the operator reads.
 */

const TENANT = "0192f0aa-7777-7000-8000-0000000000bb";
const CALL = "0192f0aa-7777-7000-8000-0000000000c1";
const RECOPY_PATH = `/v1/ops/tenants/${TENANT}/calls/${CALL}/recording/recopy`;

const ME: AdminMe = {
  realm: "admin",
  user_id: "0192f0aa-8888-7000-8000-0000000000a2",
  role: "superadmin",
  permissions: ["ops:manage"],
};

function episode(over: Partial<AlertEpisode>): AlertEpisode {
  return {
    id: "0192f0aa-9999-7000-8000-000000000001",
    code: "recording_copy_at_risk",
    stage: "WORKER_DELIVERY",
    severity: "page",
    service: "workers",
    detail: "1 call(s) with no recording copy are within 7 days of the voice platform deleting theirs",
    ids: { tenant_id: TENANT, call_id: CALL, call_ids: CALL },
    first_seen_at: "2026-10-17T03:51:00Z",
    last_seen_at: "2026-10-17T04:51:00Z",
    occurrences: 2,
    emailed: true,
    emailed_at: "2026-10-17T03:51:05Z",
    cleared_at: null,
    ...over,
  };
}

function report(episodes: AlertEpisode[]): AlertReport {
  return {
    window_days: 7,
    episodes,
    open_by_severity: { page: 1, attention: 1 },
    open_unmailed_pages: 0,
    complete: true,
  };
}

const QUEUED: RecordingRecopy = {
  tenant_id: TENANT,
  call_id: CALL,
  queued: true,
  outcome: "queued",
  note: "Queued. The recording is copied from the voice platform within a few minutes.",
};

function routes(episodes: AlertEpisode[], extra: Record<string, unknown> = {}) {
  return {
    [ADMIN_ME_PATH]: ME,
    "/v1/ops/alerts?days=7": report(episodes),
    ...extra,
  };
}

async function openDrawer(code: string): Promise<HTMLElement> {
  fireEvent.click(await screen.findByRole("button", { name: code }));
  return screen.findByRole("dialog");
}

describe("copying a missing recording again from its alarm", () => {
  it("posts to the call the alarm names and prints the server's answer", async () => {
    const { calls } = await renderAdminRoute(
      <AlertsPage />,
      routes([episode({})], { [`POST ${RECOPY_PATH}`]: QUEUED }),
    );

    const dialog = await openDrawer("recording_copy_at_risk");
    fireEvent.click(within(dialog).getByRole("button", { name: "Copy recording again" }));

    await waitFor(() => expect(within(dialog).getByText(QUEUED.note)).toBeTruthy());
    const posts = calls.filter((call) => call.method === "POST");
    expect(posts.map((call) => call.path)).toEqual([RECOPY_PATH]);
  });

  it("is not offered on an alarm that is not about a missing recording", async () => {
    await renderAdminRoute(
      <AlertsPage />,
      routes([episode({ code: "recording_copy_failed", severity: "attention" })]),
    );

    const dialog = await openDrawer("recording_copy_failed");
    expect(within(dialog).queryByRole("button", { name: "Copy recording again" })).toBeNull();
  });

  it("is not offered when the alarm names no client", async () => {
    /* The sweep that reached no tenant still alarms, with no ids: there is no call to copy. */
    await renderAdminRoute(
      <AlertsPage />,
      routes([episode({ code: "recording_copy_missing", severity: "attention", ids: {} })]),
    );

    const dialog = await openDrawer("recording_copy_missing");
    expect(within(dialog).queryByRole("button", { name: "Copy recording again" })).toBeNull();
  });
});
