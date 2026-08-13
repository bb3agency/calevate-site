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
 * 2. **A raw phone number.** The queue names a blocked lead by its captured name,
 *    falling back to a MASKED number (crm/attention.py) — hard rule 6 holds here as it
 *    does on the calls log, and this screen is the one an owner forwards to their staff.
 * 3. **A count that disagrees with the list.** The API caps the list and does not cap
 *    the total, so a busy account sees 50 rows under a badge reading 78. Saying which
 *    end is missing is what keeps the badge believable.
 * 4. **An item this build cannot name, dropped.** An unknown kind fails VISIBLE: hiding
 *    an item is the exact failure the screen exists to prevent.
 */

const ME: Me = {
  user_id: "u1",
  realm: "client",
  role: "staff",
  permissions: ["calls:read", "leads:read"],
  impersonating: false,
  organization: { id: "o1", name: "Sri Clinic", slug: "acme", plan_tier: "managed" },
} as unknown as Me;

/** A blocked lead with no captured name: the API sends the MASKED number as the title. */
const BLOCKED: AttentionItem = {
  kind: "lead_blocked",
  id: "0192f0aa-1111-7000-8000-000000000001",
  title: "+9198765•••10 was not called",
  detail: "This person asked not to be called. Nothing to do — we will not dial them.",
  rule: "dnc",
  occurred_at: "2026-08-13T04:30:00Z",
  href: "/leads",
} as unknown as AttentionItem;

const STALLED: AttentionItem = {
  kind: "campaign_stalled",
  id: "0192f0aa-2222-7000-8000-000000000002",
  title: "Campaign “Diwali offer” is not making calls",
  detail: "Paused with 42 contacts still to call.",
  rule: "paused",
  occurred_at: "2026-08-12T11:00:00Z",
  href: "/campaigns",
} as unknown as AttentionItem;

function queue(over: Partial<AttentionQueue> = {}): AttentionQueue {
  return {
    total: 2,
    counts: { lead_blocked: 1, campaign_stalled: 1 },
    items: [BLOCKED, STALLED],
    ...over,
  } as unknown as AttentionQueue;
}

const page = <AttentionPage params={Promise.resolve({ slug: "acme" })} />;

function routes(over: Record<string, unknown> = {}) {
  return { "/v1/me": ME, "/v1/attention": queue(), ...over };
}

describe("the needs-attention queue", () => {
  it("never puts a caller's number on screen unmasked (hard rule 6)", async () => {
    const { container } = await renderClientPage(page, routes());

    expect(await screen.findByText("+9198765•••10 was not called")).toBeTruthy();
    // Not merely "the E.164 string is absent" — the ten identifying digits in sequence
    // are what name the person, and a partial leak is still a leak.
    expect(container.textContent).not.toContain("9876543210");
    expect(container.textContent).not.toContain("+919876543210");
    // And nothing in a link target either: URLs reach logs, referrers and history.
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
    // The API merges four sources, sorts newest first and slices to `limit`; `total`
    // counts everything it found. Two rows under a badge reading 78 is how a client
    // learns to distrust the badge.
    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/attention": queue({
          total: 78,
          counts: { lead_blocked: 40, campaign_stalled: 38 },
        }),
      }),
    );

    await screen.findByText(/Showing the 2 most recent of 78/);
    // And which end is missing, because "showing 2 of 78" alone leaves an owner
    // wondering whether the important one is the one that fell off.
    expect(container.textContent).toContain("Older items are not listed.");
  });

  it("does not claim a shortfall when the whole queue is on screen", async () => {
    const { container } = await renderClientPage(page, routes());

    await screen.findByText("Campaign “Diwali offer” is not making calls");
    expect(container.textContent).not.toContain("most recent of");
  });

  it("lists an item whose kind this build has never heard of", async () => {
    const unknown = {
      ...BLOCKED,
      kind: "number_suspended" as AttentionItem["kind"],
      title: "Your number was suspended",
      detail: "Your telecom operator suspended the line.",
      href: null,
    } as unknown as AttentionItem;

    const { container } = await renderClientPage(
      page,
      routes({
        "/v1/attention": queue({ total: 1, counts: { number_suspended: 1 }, items: [unknown] }),
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
