import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RetentionLine } from "@/app/c/[slug]/calls/RetentionLine";
import LineCallersPage from "@/app/c/[slug]/inbound/[lineId]/callers/page";
import { MissedCallBackSwitch, TodayCounts } from "@/app/c/[slug]/inbound/LineToday";
import InboundPage from "@/app/c/[slug]/inbound/page";
import type { Me } from "@/lib/api/client";
import type { InboundLine } from "@/lib/api/inboundLines";
import type { LineCallBack, OwedCaller } from "@/lib/api/inboundToday";

import { renderClientPage } from "./harness";

/**
 * An inbound line's day, the people it still owes a call, its "call back missed callers"
 * switch (W4.1, W4.2), and the call log's retention line (W12.9). Every number and word here
 * is what the server answered; none is computed on the page.
 */

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["agents:read", "org:read", "org:manage", "leads:read", "leads:dispatch", "calls:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const LINE_ID = "0192f0aa-4444-7000-8000-000000000001";

const LINE: InboundLine = {
  id: LINE_ID,
  name: "Front desk",
  call_languages: ["te-IN"],
  example_limits: { turns_min: 3, turns_max: 5, line_max: 200 },
  agent_id: "agent-1",
  agent_name: "Reception",
  main_task: "",
  script: null,
  proposal: null,
  version: 1,
  published_at: "2026-11-20T04:00:00Z",
  live: true,
  actions_off: [],
  source_ids: [],
  numbers: [],
  created_at: "2026-11-16T04:00:00Z",
};

const TODAY = { line_id: LINE_ID, answered: 14, call_back: 3, missed: 2, waiting: 4 };

function caller(over: Partial<OwedCaller>): OwedCaller {
  return {
    call_id: "call-1",
    at: "2026-11-28T04:30:00Z",
    reason: "not_answered",
    tries: 1,
    name: null,
    phone_e164: "+919876543210",
    call_back_at: null,
    calling: false,
    ...over,
  };
}

const CALLERS = {
  since: "2026-11-22",
  callers: [
    caller({ call_id: "call-1", tries: 2 }),
    caller({ call_id: "call-2", reason: "asked", name: "Priya", phone_e164: "+919812345678", call_back_at: "2026-11-28T09:30:00Z" }),
    caller({ call_id: "call-3", reason: "hung_up_early", phone_e164: "+919800000003", calling: true }),
  ],
};

describe("the inbound list", () => {
  it("says what each line did today, each count a link, and one button while someone waits", async () => {
    await renderClientPage(<InboundPage params={Promise.resolve({ slug: "acme" })} />, {
      "/v1/me": ME,
      "/v1/inbound-lines": { lines: [LINE] },
      "/v1/inbound-lines/today": { day: "2026-11-28", lines: [TODAY] },
    });
    const row = (await screen.findByRole("list", { name: "Your inbound lines" })).querySelector("li") as HTMLElement;
    const answered = await within(row).findByRole("link", { name: "14 answered" });
    expect(answered.getAttribute("href")).toBe(
      `/c/acme/calls?inbound_line_id=${LINE_ID}&day=2026-11-28&status=completed&test_calls=false`,
    );
    expect(within(row).getByRole("link", { name: "2 missed" }).getAttribute("href")).toBe(
      `/c/acme/calls?inbound_line_id=${LINE_ID}&day=2026-11-28&status=missed&test_calls=false`,
    );
    expect(within(row).getByRole("link", { name: "3 want a call back" }).getAttribute("href")).toBe(
      `/c/acme/inbound/${LINE_ID}/callers?show=asked`,
    );
    expect(within(row).getByRole("link", { name: "Call back 4" }).getAttribute("href")).toBe(
      `/c/acme/inbound/${LINE_ID}/callers`,
    );
  });

  it("offers no call-back button when nobody is waiting, and says a quiet day plainly", async () => {
    await renderClientPage(<InboundPage params={Promise.resolve({ slug: "acme" })} />, {
      "/v1/me": ME,
      "/v1/inbound-lines": { lines: [LINE] },
    });
    expect(await screen.findByText("No calls yet today.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /^Call back/ })).toBeNull();
  });

  it("says so when today's calls did not load", async () => {
    await renderClientPage(<TodayCounts slug="acme" lineId={LINE_ID} day={undefined} today={undefined} failed />, {
      "/v1/me": ME,
    });
    expect(screen.getByText("Today's calls did not load.")).toBeTruthy();
  });
});

describe("the people a line owes a call", () => {
  const page = () => <LineCallersPage params={Promise.resolve({ slug: "acme", lineId: LINE_ID })} />;
  const routes = {
    "/v1/me": ME,
    [`/v1/inbound-lines/${LINE_ID}`]: LINE,
    [`/v1/inbound-lines/${LINE_ID}/callers`]: CALLERS,
  };

  it("lists each person once, with why, and one Call back that opens the call-back door", async () => {
    await renderClientPage(page(), routes);
    const list = await screen.findByRole("list", { name: "Callers to call back" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText(/Not answered/)).toBeTruthy();
    expect(within(rows[0]).getByText(/rang 2 times/)).toBeTruthy();
    expect(within(rows[0]).getByRole("link", { name: "Call back +91 98765 43210" }).getAttribute("href")).toBe(
      "/c/acme/make-a-call?call=call-1",
    );
    // Booked already, or being rung now: said, with no second button.
    expect(within(rows[1]).getByRole("link", { name: "Priya" })).toBeTruthy();
    expect(within(rows[1]).getByText(/Call-back booked/)).toBeTruthy();
    expect(within(rows[1]).queryByRole("link", { name: /^Call back/ })).toBeNull();
    expect(within(rows[2]).getByText("Calling now")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Front desk" }).getAttribute("href")).toBe(`/c/acme/inbound/${LINE_ID}`);
  });

  it("opens on the kind a link asked for, and switches with the chips", async () => {
    window.history.replaceState(null, "", "/c/acme/inbound/x/callers?show=asked");
    await renderClientPage(page(), routes);
    const list = await screen.findByRole("list", { name: "Callers to call back" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Everyone" }));
    expect(within(screen.getByRole("list", { name: "Callers to call back" })).getAllByRole("listitem")).toHaveLength(3);
    window.history.replaceState(null, "", "/");
  });

  it("says nobody is waiting when the list is empty", async () => {
    await renderClientPage(page(), { ...routes, [`/v1/inbound-lines/${LINE_ID}/callers`]: { since: "2026-11-22", callers: [] } });
    expect(await screen.findByText("Nobody is waiting for a call back.")).toBeTruthy();
  });
});

describe("the call back missed callers switch", () => {
  const off: LineCallBack = { state: "off", follow_up_id: null, covered_by: null, covered_by_name: null };

  it("switches on and shows the state the server read back", async () => {
    let current: LineCallBack = off;
    const rendered = await renderClientPage(<MissedCallBackSwitch slug="acme" lineId={LINE_ID} />, {
      "/v1/me": ME,
      [`/v1/inbound-lines/${LINE_ID}/missed-call-back`]: () => current,
      [`PUT /v1/inbound-lines/${LINE_ID}/missed-call-back`]: () => {
        current = { ...off, state: "on", follow_up_id: "fu-1" };
        return current;
      },
    });
    const toggle = await screen.findByRole("switch", { name: /Call back missed callers/ });
    expect((toggle as HTMLInputElement).checked).toBe(false);
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByText("On. Your agent rings them back once, in calling hours.")).toBeTruthy());
    const put = rendered.calls.find((c) => c.method === "PUT");
    expect(JSON.parse(put?.body ?? "null")).toEqual({ on: true });
    expect(screen.getByText("Never a number on your Do not call list.")).toBeTruthy();
  });

  it("names the account-wide follow-up that already covers the line, and cannot be switched here", async () => {
    await renderClientPage(<MissedCallBackSwitch slug="acme" lineId={LINE_ID} />, {
      "/v1/me": ME,
      [`/v1/inbound-lines/${LINE_ID}/missed-call-back`]: {
        state: "covered",
        follow_up_id: null,
        covered_by: "fu-9",
        covered_by_name: "Call back missed calls",
      },
    });
    const toggle = await screen.findByRole("switch", { name: /Call back missed callers/ });
    expect((toggle as HTMLInputElement).checked).toBe(true);
    expect((toggle as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByRole("link", { name: "Open Call back missed calls" }).getAttribute("href")).toBe(
      "/c/acme/follow-ups/fu-9",
    );
  });

  it("says why it cannot be on when no agent places calls", async () => {
    await renderClientPage(<MissedCallBackSwitch slug="acme" lineId={LINE_ID} />, {
      "/v1/me": ME,
      [`/v1/inbound-lines/${LINE_ID}/missed-call-back`]: { ...off, state: "cannot" },
    });
    expect(await screen.findByText("None of your agents can place calls yet.")).toBeTruthy();
    expect(((await screen.findByRole("switch")) as HTMLInputElement).disabled).toBe(true);
  });
});

describe("the call log's retention line", () => {
  it("says the account's own periods", async () => {
    await renderClientPage(<RetentionLine />, {
      "/v1/me": ME,
      "/v1/calls/kept": { recording_days: 120, transcript_days: 365 },
    });
    expect(await screen.findByText("We keep recordings for 120 days and transcripts for 365 days.")).toBeTruthy();
  });

  it("says nothing about a kind with no period", async () => {
    await renderClientPage(<RetentionLine />, {
      "/v1/me": ME,
      "/v1/calls/kept": { recording_days: 90, transcript_days: null },
    });
    expect(await screen.findByText("We keep recordings for 90 days.")).toBeTruthy();
  });
});
