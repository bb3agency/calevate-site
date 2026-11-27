import { QueryClient } from "@tanstack/react-query";
import { act, fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Me } from "@/lib/api/client";

import {
  FIXTURE_CAMPAIGN_ID as CAMPAIGN_ID,
  campaignPage,
  contactsFixture,
  contactsPath,
  CONTACTS_PAGE,
  detailRoutes,
  openTab,
  progressFixture,
} from "./campaignFixtures";
import { problem, renderClientPage, type Routes } from "./harness";

/**
 * A launched campaign's page as an owner watches it: who is on a call now, how many calls
 * run at once against the limit, when the next try is, the people list as the first tab,
 * and the name renamed in place in any status.
 */

const ME: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["leads:read", "leads:dispatch", "billing:read"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const LAUNCHED = { status: "running", launched_at: "2026-10-14T04:30:00Z" } as const;
const ON_A_CALL = `/v1/campaigns/${CAMPAIGN_ID}/contacts?limit=10&offset=0&outcome=calling`;

function routes(progress: unknown, extra: Routes = {}): Routes {
  return {
    "/v1/me": ME,
    ...detailRoutes(),
    [`/v1/campaigns/${CAMPAIGN_ID}`]: progress,
    [`/v1/campaigns/${CAMPAIGN_ID}/launch-check`]: { ready: true, blockers: [] },
    ...extra,
  };
}

const ON_CALL_PERSON = {
  id: "cc-7",
  name: "Lakshmi",
  phone_e164: "+919876500007",
  outcome: "calling" as const,
  attempts: 1,
  last_attempt_at: "2026-10-14T05:00:00Z",
  included: true,
  will_retry: false,
  next_attempt_at: null,
  call_id: "call-77",
};

describe("the live panel of a running campaign", () => {
  it("names who is on a call now, with a way into each call", async () => {
    const { container } = await renderClientPage(
      campaignPage(),
      routes(
        progressFixture({ ...LAUNCHED, contacts: { pending: 4, dialing: 2 }, total: 6, effective_concurrency: 3 }),
        { [ON_A_CALL]: contactsFixture({ total: 2, items: [ON_CALL_PERSON] }) },
      ),
    );
    await openTab("Progress & results");
    await screen.findByText("Lakshmi");
    expect(screen.getByRole("link", { name: "Open the call with Lakshmi" }).getAttribute("href")).toBe(
      "/c/acme/calls/call-77",
    );
    // One person listed of the two the count says are on a call: the rest are counted.
    expect(container.textContent).toContain("and 1 more");
    expect(container.textContent).toContain("2 of 3");
  });

  it("keeps who is on a call on screen when one re-read fails", async () => {
    const table = routes(
      progressFixture({ ...LAUNCHED, contacts: { pending: 4, dialing: 1 }, total: 5, effective_concurrency: 3 }),
      { [ON_A_CALL]: contactsFixture({ total: 1, items: [ON_CALL_PERSON] }) },
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await renderClientPage(campaignPage(), table, "acme", client);
    await openTab("Progress & results");
    await screen.findByText("Lakshmi");

    table[ON_A_CALL] = problem(503, { title: "Service unavailable" });
    await act(async () => {
      await client.refetchQueries({ predicate: (q) => q.queryKey.includes("contacts") });
    });

    // The list polls every few seconds; one failure says so and keeps the people it had.
    expect(await screen.findByText(/Couldn't (load|refresh) who is on a call./)).toBeTruthy();
    expect(screen.getByText("Lakshmi")).toBeTruthy();
  });

  it("says the account's call lines hold it to fewer calls at once than it asked for", async () => {
    await renderClientPage(
      campaignPage(),
      routes(progressFixture({ ...LAUNCHED, contacts: { pending: 4 }, total: 4, concurrency: 5, effective_concurrency: 2 }), {
        "/v1/call-lines": { call_lines: 2, in_progress: 1, on_trial: false },
      }),
    );
    await openTab("Progress & results");
    fireEvent.click(await screen.findByRole("button", { name: "About Calls at once" }));
    expect((await screen.findAllByText("Set to 5. Your account runs up to 2 calls at once.")).length).toBeGreaterThan(0);
  });

  it("asks for nobody on a call while nobody is, and names the next try", async () => {
    // An unrouted request fails the test, so the absent calling-now route is the assertion.
    const { container } = await renderClientPage(
      campaignPage(),
      routes(
        progressFixture({
          ...LAUNCHED,
          contacts: { pending: 3 },
          total: 3,
          retries_waiting: 2,
          next_retry_at: "2026-10-14T06:00:00Z",
        }),
      ),
    );
    await openTab("Progress & results");
    await screen.findByText("Next try");
    expect(container.textContent).toContain("2 waiting to be tried again");
    expect(container.textContent).not.toContain("On a call now");
  });

  it("opens on the set-up with the people in it, and the progress a tab away", async () => {
    await renderClientPage(
      campaignPage(),
      routes(progressFixture({ ...LAUNCHED, total: 1, contacts: { pending: 1 } }), {
        [contactsPath()]: contactsFixture({
          total: 1,
          counts: { ...contactsFixture().counts, not_called: 1 },
          items: [{ ...ON_CALL_PERSON, outcome: "not_called", attempts: 0, last_attempt_at: null, call_id: null }],
        }),
      }),
    );
    const people = await screen.findByRole("table", { name: "People on this campaign" });
    expect(within(people).getByText("Lakshmi")).toBeTruthy();
    expect(within(people).getByRole("columnheader", { name: "Person" })).toBeTruthy();
    expect(within(people).getByRole("columnheader", { name: "Status" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Set up" }).getAttribute("aria-selected")).toBe("true");
    await openTab("Progress & results");
    expect(await screen.findByText("Calling hours")).toBeTruthy();
  });
});

describe("renaming a campaign", () => {
  it("renames a running campaign in place, sending the name alone", async () => {
    const rendered = await renderClientPage(
      campaignPage(),
      routes(progressFixture({ ...LAUNCHED, total: 0 }), {
        [`PATCH /v1/campaigns/${CAMPAIGN_ID}`]: new Response(null, { status: 204 }),
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Edit Campaign name: Diwali offer" }));
    const field = screen.getByRole("textbox", { name: "Campaign name" });
    fireEvent.change(field, { target: { value: "  Diwali recall  " } });
    fireEvent.submit(field.closest("form")!);
    const sent = await vi.waitFor(() => {
      const call = rendered.calls.find((c) => c.method === "PATCH");
      expect(call).toBeDefined();
      return JSON.parse(call!.body ?? "{}");
    });
    expect(sent).toEqual({ name: "Diwali recall" });
  });

  it("refuses a one-letter name before sending anything", async () => {
    const rendered = await renderClientPage(campaignPage(), routes(progressFixture({ ...LAUNCHED, total: 0 })));
    fireEvent.click(await screen.findByRole("button", { name: "Edit Campaign name: Diwali offer" }));
    const field = screen.getByRole("textbox", { name: "Campaign name" });
    fireEvent.change(field, { target: { value: "D" } });
    fireEvent.submit(field.closest("form")!);
    expect(await screen.findByText("Use at least 2 characters.")).toBeTruthy();
    expect(rendered.calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("offers no rename to a viewer who may not run campaigns", async () => {
    await renderClientPage(
      campaignPage(),
      routes(progressFixture({ ...LAUNCHED, total: 0 }), {
        "/v1/me": { ...ME, role: "viewer", permissions: ["leads:read"] },
      }),
    );
    const name = (await screen.findByRole("button", { name: "Edit Campaign name: Diwali offer" })) as HTMLButtonElement;
    expect(name.disabled).toBe(true);
  });
});

describe("a page of people that loses its rows", () => {
  it("steps back to the last page that has people instead of saying nobody matches", async () => {
    const person = (i: number) => ({
      ...ON_CALL_PERSON,
      id: `cc-${i}`,
      name: `Person ${i}`,
      phone_e164: `+9198765${String(10000 + i).slice(-5)}`,
      call_id: null,
    });
    const counts = (n: number) => ({ ...contactsFixture().counts, calling: n });
    const pageTwo = contactsPath(CAMPAIGN_ID, CONTACTS_PAGE);
    const full = CONTACTS_PAGE;
    const table = routes(progressFixture({ ...LAUNCHED, total: full + 1, contacts: { dialing: full + 1 } }), {
      [contactsPath()]: contactsFixture({ total: full + 1, counts: counts(full + 1), items: Array.from({ length: full }, (_, i) => person(i)) }),
      [pageTwo]: contactsFixture({ total: full + 1, counts: counts(full + 1), items: [{ ...person(full), name: "The last one" }] }),
      [ON_A_CALL]: contactsFixture(),
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await renderClientPage(campaignPage(), table, "acme", client);
    fireEvent.click(await screen.findByRole("button", { name: "Page 2" }));
    expect(await screen.findByText("The last one")).toBeTruthy();

    // The re-read of that page comes back empty: one page's worth now, all on page 1.
    table[pageTwo] = contactsFixture({ total: full, counts: counts(full), items: [] });
    table[contactsPath()] = contactsFixture({ total: full, counts: counts(full), items: Array.from({ length: full }, (_, i) => person(i)) });
    await act(async () => {
      await client.refetchQueries({ queryKey: ["campaign"] });
    });

    expect(await screen.findByText("Person 0")).toBeTruthy();
    expect(screen.queryByText("Nobody matches.")).toBeNull();
  });
});
