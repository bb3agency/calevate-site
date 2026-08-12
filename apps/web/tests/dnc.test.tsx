import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DoNotCallPage from "@/app/c/[slug]/do-not-call/page";
import type { Me } from "@/lib/api/client";
import type { DncEntry } from "@/lib/api/dnc";

import { renderClientPage } from "./harness";

/**
 * The suppression list — ranked second, because it is the only client screen whose
 * mistakes are made of personal data rather than of copy.
 *
 * Two separate obligations meet here and they fail in opposite directions:
 *
 * - **Hard rule 5**, on the verdicts. `removable` is the server's `is_removable()`
 *   answer and the screen renders it rather than re-deriving it. A row that grows a
 *   Remove button the endpoint refuses teaches a client that our compliance rules are a
 *   bug; a consumer opt-out shown as undoable is worse than that, it is an invitation.
 * - **Hard rule 6**, on the number itself. The list is masked, and checking a number is
 *   a POST for one reason: a GET writes the number into access logs, proxies, the
 *   referrer of the next page and browser history. That is a property of the REQUEST,
 *   not of the DOM, and the harness records every request the screen made — so it can
 *   be asserted directly instead of trusted.
 *
 * The number planted below is a full E.164 string that appears NOWHERE in any masked
 * payload. Every "must not appear" assertion in this file is therefore load-bearing: if
 * it shows up, the screen put it there.
 */

const RAW_PHONE = "+919876543210";
const MASKED = "+9198••••3210";

const ME: Me = {
  impersonating: false,
  permissions: ["leads:read", "leads:dispatch"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

/** A viewer who may read and check the list but not change it (`staff`). */
const READ_ONLY_ME: Me = { ...ME, permissions: ["leads:read"], role: "staff" };

function entry(over: Partial<DncEntry> = {}): DncEntry {
  return {
    id: "0192f0aa-4444-7000-8000-000000000001",
    phone_masked: MASKED,
    added_at: "2026-07-01T10:00:00Z",
    removable: true,
    scope: "tenant",
    source: "manual",
    ...over,
  } as DncEntry;
}

async function renderList(entries: DncEntry[], me: Me = ME) {
  return await renderClientPage(<DoNotCallPage />, {
    "/v1/me": me,
    "/v1/dnc?limit=500": entries,
  });
}

describe("what the list says may be undone", () => {
  it("offers Remove only where the server said removable", async () => {
    const { container } = await renderList([entry({ source: "manual" })]);

    await screen.findByText(MASKED);
    expect(screen.getByRole("button", { name: "Remove" })).toBeDefined();
    expect(container.textContent).toContain("Added by your team");
  });

  it("renders a consumer opt-out as permanent, with no button anywhere near it", async () => {
    // The person themselves asked us to stop. The API refuses the delete
    // (`dnc_consumer_optout`); a button here would 400 and read as our bug rather than
    // as their decision.
    const { container } = await renderList([
      entry({ removable: false, source: "call_optout", scope: "tenant" }),
    ]);

    await screen.findByText(MASKED);
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    expect(container.textContent).toContain("opt-out — cannot be undone");
    // The reason takes the button's place — a row with neither is a dead end.
    expect(container.textContent).toContain("Opted out on a call");
  });

  it("shows a national-list entry, marks it, and does not offer to remove it", async () => {
    // Shown deliberately: a number you cannot un-suppress is still a number you should
    // know is suppressed. Hiding it leaves a client wondering why someone is never
    // dialled and unable to find them anywhere.
    const { container } = await renderList([
      entry({ removable: false, scope: "global", source: "regulator" }),
    ]);

    await screen.findByText(MASKED);
    expect(container.textContent).toContain("national list");
    expect(container.textContent).toContain("removed by operations only");
    expect(container.textContent).not.toContain("opt-out — cannot be undone");
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
  });

  it("keeps the row for a reason this build cannot name, rather than blanking it", async () => {
    // `DncEntryOut.source` is `string | null`. Fail VISIBLE: the row is a suppression
    // whatever we call it, and a suppression the client cannot see is one they will
    // ask us to explain.
    const { container } = await renderList([entry({ source: "a_source_added_later" })]);

    await screen.findByText(MASKED);
    expect(container.textContent).toContain("a_source_added_later");
    expect(screen.getByRole("button", { name: "Remove" })).toBeDefined();
  });

  it("withholds Remove from a viewer who lacks the permission, on a removable row", async () => {
    // `removable` and "may YOU remove it" are two different questions and the row asks
    // both. Rendering the button for a `staff` viewer would be rendering a 403.
    const { container } = await renderList([entry()], READ_ONLY_ME);

    await screen.findByText(MASKED);
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    expect(container.textContent).toContain(
      "Adding or removing numbers is done by an account owner",
    );
    // …and the row must not acquire the permanence copy it has not earned: this entry
    // IS removable, by someone else.
    expect(container.textContent).not.toContain("cannot be undone");
  });
});

describe("checking a number", () => {
  async function check(answer: unknown, me: Me = ME) {
    const rendered = await renderClientPage(<DoNotCallPage />, {
      "/v1/me": me,
      "/v1/dnc?limit=500": [],
      "/v1/dnc/check": answer,
    });
    fireEvent.change(await screen.findByLabelText("Phone number to check"), {
      target: { value: RAW_PHONE },
    });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    return rendered;
  }

  it("never puts the number in a URL — it is the personal data", async () => {
    // Hard rule 6 asserted at the wire, not at the DOM. A `useQuery` here would put the
    // number in a cache key that outlives the answer, and a GET would put it in the
    // access log of every hop between the browser and us. The harness recorded every
    // request the screen made; none of them may carry it.
    const { calls } = await check({ valid: true, suppressed: true, scope: "tenant" });

    await screen.findByText(/This number is suppressed/);
    const posted = calls.filter((c) => c.path === "/v1/dnc/check");
    expect(posted).toHaveLength(1);
    expect(posted[0].method).toBe("POST");
    expect(posted[0].body).toBe(JSON.stringify({ phone: RAW_PHONE }));

    for (const call of calls) {
      expect(call.url, `${call.method} ${call.path} carries the number in its URL`).not.toContain(
        "9876543210",
      );
    }
  });

  it("does not render a bad number as a clean bill of health", async () => {
    // The dangerous confusion on this card. `valid: false` means we could not parse it
    // at all — rendering the green "not on the do-not-call list" panel would tell a
    // client we checked a number we never looked at.
    const { container } = await check({ valid: false, suppressed: false, scope: null });

    await screen.findByText(/does not look like a phone number/);
    expect(container.textContent).not.toContain("not on the do-not-call list");
    expect(container.textContent).not.toContain("This number is suppressed");
  });

  it("says a clear number is clear WITHOUT saying it may be called", async () => {
    // The DNC list is one gate of several. "Not suppressed" is not "dial away" —
    // calling hours and consent are separate refusals, and a client who reads this
    // panel as clearance will report the next block as a fault.
    const { container } = await check({ valid: true, suppressed: false, scope: null });

    await screen.findByText(/not on the do-not-call list/);
    expect(container.textContent).toContain("Other checks — calling hours, consent — still apply");
  });

  it("names which list a suppressed number is on, because the two end differently", async () => {
    const { container } = await check({ valid: true, suppressed: true, scope: "global" });

    await screen.findByText(/This number is suppressed/);
    // A national-list hit cannot be cleared from this account at all; a tenant-list hit
    // can. Flattening the two would send a client looking for a row they cannot remove.
    expect(container.textContent).toContain("it cannot be removed from this account");
    expect(container.textContent).not.toContain("It was added to your account's list.");
  });
});
