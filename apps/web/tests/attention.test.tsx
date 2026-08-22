import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AttentionPage from "@/app/c/[slug]/attention/page";
import type { AttentionItem, AttentionQueue } from "@/lib/api/attention";
import type { Me } from "@/lib/api/client";

import { problem, renderClientPage } from "./harness";

/**
 * The "needs attention" queue — the screen that carries the platform's promise that
 * nothing it refuses to do happens silently.
 *
 * Ranked by what a wrong render costs:
 *
 * 1. **"Nothing needs you right now" under a failed request.** The one sentence this
 *    screen must never say by accident: it sends an owner away from a queue of blocked
 *    calls they have not seen. An empty Card says it just as effectively as the words.
 * 2. **A phone number in a link target.** The queue names a blocked lead by its
 *    captured name, falling back to its number IN FULL (crm/attention.py, D-436) —
 *    "ring this person" is the action the row exists to prompt. What must never carry
 *    it is an `href`, because URLs reach logs, referrers and history (hard rule 6).
 * 3. **A count that disagrees with the list.** The API caps the list and does not cap
 *    the total — `counts`/`total` are counted separately from the rows, so they are the
 *    size of the SET — and a busy account sees 50 rows under a badge reading 78. Saying
 *    which end is missing is what keeps the badge believable. The screen must print the
 *    server's numbers rather than count what it rendered: recounting would say 50 and 2,
 *    which is the under-reporting bug crm/attention.py just removed, reintroduced one
 *    layer up.
 * 4. **An item this build cannot name, dropped.** An unknown kind fails VISIBLE: hiding
 *    an item is the exact failure the screen exists to prevent.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "staff",
  permissions: ["calls:read", "leads:read"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", status: "active" },
};

/** A blocked lead with no captured name: the API composes the title from its number. */
const BLOCKED: AttentionItem = {
  kind: "lead_blocked",
  id: "0192f0aa-1111-7000-8000-000000000001",
  title: "+919876543210 was not called",
  detail: "This person asked not to be called. Nothing to do — we will not dial them.",
  rule: "dnc",
  occurred_at: "2026-08-13T04:30:00Z",
  href: "/leads",
};

const STALLED: AttentionItem = {
  kind: "campaign_stalled",
  id: "0192f0aa-2222-7000-8000-000000000002",
  title: "Campaign “Diwali offer” is not making calls",
  detail: "Paused with 42 contacts still to call.",
  rule: "paused",
  occurred_at: "2026-08-12T11:00:00Z",
  href: "/campaigns",
};

function queue(over: Partial<AttentionQueue> = {}): AttentionQueue {
  return {
    total: 2,
    counts: { lead_blocked: 1, campaign_stalled: 1 },
    items: [BLOCKED, STALLED],
    ...over,
  };
}

const page = <AttentionPage params={Promise.resolve({ slug: "acme" })} />;

function routes(over: Record<string, unknown> = {}) {
  return { "/v1/me": ME, "/v1/attention": queue(), ...over };
}

describe("the needs-attention queue", () => {
  it("prints the server's title in full and keeps it out of every link target", async () => {
    const { container } = await renderClientPage(page, routes());

    // WAS `not.toContain("+919876543210")`. D-436 reversed it: a to-do whose subject
    // cannot be dialled is a to-do nobody can do.
    expect(await screen.findByText("+919876543210 was not called")).toBeTruthy();
    // The half that did NOT change: URLs reach logs, referrers and history.
    for (const link of Array.from(container.querySelectorAll("a"))) {
      expect(link.getAttribute("href") ?? "").not.toMatch(/\d{10}/);
    }
  });

  it("refuses to report calm when it could not read the queue", async () => {
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/attention": problem(503, {
          title: "Service unavailable",
          detail: "We could not read your queue.",
        }),
      }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    // THE assertion. "Nothing needs you right now" is a claim about the business; a
    // failed request is a fact about us, and the two must never render the same.
    expect(container.textContent).not.toContain("Nothing needs you right now");
    // The empty panel says it too. A Card with nothing in it, under a notice, reads as a
    // queue with nothing in it.
    expect(container.querySelector("section"), "no panel without data to put in it").toBeNull();
  });

  it("says the queue is empty only when the server said so", async () => {
    const { container } = await renderClientPage(
      page,
      routes({ "/v1/attention": queue({ total: 0, counts: {}, items: [] }) }),
    );

    await screen.findByText("Nothing needs you right now.");
    // No chips either: an all-zeros summary row is noise, not information.
    expect(container.textContent).not.toContain("Call blocked");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("admits that the list is shorter than the count it is under", async () => {
    // A real `/v1/attention` body for a busy account: the API merges four sources, sorts
    // newest first and slices to `limit`, while `counts`/`total` are counted by their own
    // queries over the whole 14-day set (crm/attention.py). So M here is 78 — one blocked
    // lead and one stalled campaign are on screen out of 40 and 38 that exist — and the
    // screen has to say the other 76 are there. Two rows under a silent badge reading 78
    // is how a client learns to distrust the badge.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/attention": queue({
          total: 78,
          counts: { lead_blocked: 40, campaign_stalled: 38 },
        }),
      }),
    );

    // M is the server's count of what EXISTS, not the 2 rows rendered and not the 50-row
    // cap: a screen that recounted its own list would say "2 of 2" and never draw this
    // sentence at all.
    await screen.findByText(/Showing the 2 most recent of 78/);
    // And which end is missing, because "showing 2 of 78" alone leaves an owner
    // wondering whether the important one is the one that fell off.
    expect(container.textContent).toContain("Older items are not listed.");
    // The chips carry the same claim per kind: 40 blocked with one blocked row on screen.
    const summary = screen.getByRole("group", { name: "Queue summary" });
    expect(summary.textContent).toContain("40");
    expect(summary.textContent).toContain("38");
    expect(container.querySelectorAll("li").length, "one row per item, no more").toBe(2);
  });

  it("does not claim a shortfall when the whole queue is on screen", async () => {
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Campaign “Diwali offer” is not making calls");
    expect(container.textContent).not.toContain("most recent of");
  });

  it("lists an item whose kind this build has never heard of", async () => {
    // A payload our GENERATED types cannot describe, on purpose: the whole point of the
    // test is a server newer than this build. It therefore stays off the typed path and
    // rides the route map as `unknown`, which is what an unrecognised value IS to us.
    // The rejected spelling was `kind: "number_suspended" as AttentionItem["kind"]` — an
    // assertion that says the union ALREADY CONTAINS this kind, which is the opposite of
    // what is being tested, and which would keep compiling on the day somebody deletes a
    // kind from the union for real.
    const unrecognised = {
      ...BLOCKED,
      kind: "number_suspended",
      title: "Your number was suspended",
      detail: "Your telecom operator suspended the line.",
      href: null,
    };

    const { container } = await renderClientPage(
      page,
      routes({
        // Spread the CHECKED envelope, then override the one field that is deliberately
        // off-contract — so everything except the unknown kind is still type-checked.
        "/v1/attention": {
          ...queue({ total: 1, counts: { number_suspended: 1 } }),
          items: [unrecognised],
        },
      }),
    );

    await screen.findByText("Your number was suspended");
    // Fails VISIBLE: the row is there and the unfamiliar kind is printed in place of the
    // copy we have not written yet. Hiding it would be this screen failing at its one job.
    expect(container.textContent).toContain("number suspended");
    expect(container.textContent).toContain("Your telecom operator suspended the line.");
  });

  it("counts the chips from the server's own tally, not from the rows on screen", async () => {
    // The counts are per-source and the list is capped, so counting the rendered rows
    // would under-report exactly when the queue is busiest.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/attention": queue({ total: 43, counts: { lead_blocked: 41, campaign_stalled: 2 } }),
      }),
    );

    const summary = await screen.findByRole("group", { name: "Queue summary" });
    expect(summary.textContent).toContain("Call blocked");
    expect(summary.textContent).toContain("41");
    expect(summary.textContent).toContain("2");
    // A kind the response omitted is genuinely zero (the API omits empty kinds) and gets
    // no chip at all.
    expect(container.textContent).not.toContain("Delivery failed");
    expect(container.textContent).not.toContain("Knowledge not accepted");
  });

  it("explains a missing permission instead of answering with an error", async () => {
    // `GET /v1/attention` requires `leads:read`. Staff hold it — that is deliberate, they
    // work this queue — but a session that does not gets the sentence, not a red alert.
    const { container } = await renderClientPage(page, {
      "/v1/me": { ...ME, permissions: ["calls:read"] },
    });

    await screen.findByText(/needs permission to read leads/);
    expect(screen.queryByRole("alert"), "a permission is not a fault").toBeNull();
    expect(container.textContent).not.toContain("Nothing needs you right now");
  });
});
