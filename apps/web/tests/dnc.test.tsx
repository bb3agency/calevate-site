import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DoNotCallPage from "@/app/c/[slug]/do-not-call/page";
import type { Me } from "@/lib/api/client";
import { DNC_LIST_LIMIT, type DncEntry } from "@/lib/api/dnc";

import { problem, renderClientPage } from "./harness";

/**
 * The suppression list — ranked second, because it is the only client screen whose
 * mistakes are made of personal data rather than of copy.
 *
 * Three separate obligations meet here and they fail in different directions:
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
 * - **The refusal, on every path that could otherwise print a compliance claim.** "Nobody
 *   is suppressed yet" under a failed list request reads as "nobody is suppressed", and
 *   "not on the do-not-call list" under a failed check reads as clearance to dial. Both
 *   are sentences about a request that never landed, and both have a test below.
 *
 * The number below is what the list renders since D-436 — the whole E.164 string, so a
 * client can check it against the caller complaining that we rang them again. One
 * constant serves both the payload and the box an operator types into, which is the
 * point: they are the same number and the screen no longer renders it two ways. What is
 * still asserted is that it never reaches a URL (hard rule 6): the check is a POST body
 * and the delete carries an id.
 */

const PHONE = "+919876543210";
/** The national-format digits, which is the form a URL would carry. */
const PHONE_DIGITS = "9876543210";

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

const LIST_PATH = `/v1/dnc?limit=${DNC_LIST_LIMIT}`;

function entry(over: Partial<DncEntry> = {}): DncEntry {
  return {
    id: "0192f0aa-4444-7000-8000-000000000001",
    phone_e164: PHONE,
    added_at: "2026-07-01T10:00:00Z",
    removable: true,
    scope: "tenant",
    source: "manual",
    ...over,
  };
}

/**
 * Every Remove button on screen, by its ACCESSIBLE name rather than its label.
 *
 * The buttons are named for the row they act on ("Remove +919876543210 from the
 * do-not-call list") because forty identically-named buttons are forty identical
 * announcements to a screen reader. A literal `{ name: "Remove" }` would therefore match none of them and
 * every `queryByRole(...).toBeNull()` in this file would pass without testing anything.
 */
function removeButtons(): HTMLElement[] {
  return screen.queryAllByRole("button", { name: /^Remove / });
}

/**
 * Answer the un-suppress confirmation, having first checked that the row's own press
 * sent NOTHING.
 *
 * The order is the assertion. A helper that only clicked through would pass just as well
 * against a screen that fired the DELETE on the first press and put a dialog up
 * afterwards, which is the defect this dialog exists to fix.
 */
async function confirmUnsuppress(calls: { method: string }[]): Promise<void> {
  const dialog = await screen.findByRole("dialog");
  expect(
    calls.filter((call) => call.method === "DELETE"),
    "the row's Remove button must open the dialog and send nothing",
  ).toEqual([]);
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Un-suppress this number" }),
  );
}

async function renderList(entries: DncEntry[], me: Me = ME) {
  return await renderClientPage(<DoNotCallPage />, {
    "/v1/me": me,
    [LIST_PATH]: entries,
  });
}

describe("what the list says may be undone", () => {
  it("offers Remove only where the server said removable", async () => {
    const { container } = await renderList([entry({ source: "manual" })]);

    await screen.findByText(PHONE);
    expect(removeButtons()).toHaveLength(1);
    expect(container.textContent).toContain("Added by your team");
  });

  it("renders a consumer opt-out as permanent, with no button anywhere near it", async () => {
    // The person themselves asked us to stop. The API refuses the delete
    // (`dnc_consumer_optout`); a button here would 400 and read as our bug rather than
    // as their decision.
    const { container } = await renderList([
      entry({ removable: false, source: "call_optout", scope: "tenant" }),
    ]);

    await screen.findByText(PHONE);
    expect(removeButtons()).toHaveLength(0);
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

    await screen.findByText(PHONE);
    expect(container.textContent).toContain("national list");
    expect(container.textContent).toContain("removed by operations only");
    expect(container.textContent).not.toContain("opt-out — cannot be undone");
    expect(removeButtons()).toHaveLength(0);
  });

  it("withholds Remove when the SERVER says not removable, whatever our own rule would say", async () => {
    // THE POINT OF `removable`. This row is `manual` + `tenant`, which is exactly the
    // pair `is_removable()` currently answers true for — so a screen that re-derived the
    // rule instead of rendering the flag would put a button here, and every such button
    // is a 400 the client reads as our bug. The flag is the only input.
    const { container } = await renderList([
      entry({ removable: false, source: "manual", scope: "tenant" }),
    ]);

    await screen.findByText(PHONE);
    expect(removeButtons()).toHaveLength(0);
    expect(container.textContent).toContain("cannot be undone");
  });

  it("offers Remove when the SERVER says removable, for a source our own rule would refuse", async () => {
    // The same assertion from the other side, and the one that catches a "helpful"
    // client-side filter on `source`: if the server ever widens `REMOVABLE_SOURCES`, the
    // screen must follow it that day and not at the next frontend release.
    await renderList([entry({ removable: true, source: "call_optout", scope: "tenant" })]);

    await screen.findByText(PHONE);
    expect(removeButtons()).toHaveLength(1);
  });

  it("keeps the row for a reason this build cannot name, rather than blanking it", async () => {
    // `DncEntryOut.source` is `string | null`. Fail VISIBLE: the row is a suppression
    // whatever we call it, and a suppression the client cannot see is one they will
    // ask us to explain.
    const { container } = await renderList([entry({ source: "a_source_added_later" })]);

    await screen.findByText(PHONE);
    expect(container.textContent).toContain("a_source_added_later");
    expect(removeButtons()).toHaveLength(1);
  });

  it("withholds Remove from a viewer who lacks the permission, on a removable row", async () => {
    // `removable` and "may YOU remove it" are two different questions and the row asks
    // both. Rendering the button for a `staff` viewer would be rendering a 403.
    const { container } = await renderList([entry()], READ_ONLY_ME);

    await screen.findByText(PHONE);
    expect(removeButtons()).toHaveLength(0);
    expect(container.textContent).toContain("Only an account owner can add or remove numbers");
    // …and the row must not acquire the permanence copy it has not earned: this entry
    // IS removable, by someone else.
    expect(container.textContent).not.toContain("cannot be undone");
    // The write form goes with the permission, rather than waiting to answer 403.
    expect(screen.queryByLabelText("Numbers to suppress")).toBeNull();
  });

  it("deletes by entry id, and never sends the number anywhere", async () => {
    const { calls } = await renderList([entry()]);

    await screen.findByText(PHONE);
    fireEvent.click(removeButtons()[0]);
    // Un-suppressing is confirmed now (🔒 DNC-1): the press opens the dialog and the
    // DELETE is the SECOND press. `confirmUnsuppress` asserts the first press sent
    // nothing, so this test still fails if the confirmation is ever removed.
    await confirmUnsuppress(calls);

    const deletes = () => calls.filter((call) => call.method === "DELETE");
    await waitFor(() => expect(deletes()).toHaveLength(1));
    expect(deletes()[0].path).toBe("/v1/dnc/0192f0aa-4444-7000-8000-000000000001");
    // The number does not travel at all: the row is addressed by its own id, so the
    // one string a URL must never carry (hard rule 6) is absent from it.
    expect(deletes()[0].url).not.toContain(PHONE_DIGITS);
  });
});

describe("when the list itself does not load", () => {
  it("refuses, and does NOT report that nobody is suppressed", async () => {
    // The worst sentence this screen can print. "Nobody is suppressed yet" under a
    // request that never landed is not an empty state, it is a compliance claim made on
    // no evidence — and the client acts on it by launching a campaign.
    const { container } = await renderClientPage(<DoNotCallPage />, {
      "/v1/me": ME,
      [LIST_PATH]: problem(503, {
        title: "Service unavailable",
        detail: "We could not read your suppression list.",
      }),
    });

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).not.toContain("Nobody is suppressed yet");
    // …and no rows either: a failed list renders no number at all.
    expect(container.textContent).not.toContain(PHONE);
  });

  it("says so when it cannot even find out whether you may write", async () => {
    // `/v1/me` failing used to delete the Add card in silence — "we could not ask" and
    // "you may not" rendered identically, as empty space, and the client's only clue was
    // a form that had been there yesterday.
    const { container } = await renderClientPage(<DoNotCallPage />, {
      "/v1/me": problem(503, { title: "Service unavailable" }),
      [LIST_PATH]: [],
    });

    await screen.findByText(/We could not check whether you can add or remove numbers/);
    expect(screen.queryByLabelText("Numbers to suppress")).toBeNull();
    expect(container.textContent).not.toContain("Only an account owner");
  });

  it("does not print the row count as a total when the response is at the endpoint's ceiling", async () => {
    // `/v1/dnc` clamps to `MAX_LIST` and has no offset, so a full-length response is a
    // TRUNCATION. Calling its length "500 entries" would be the Leads table's old stage
    // tally all over again: a number about our query, read as a number about the client.
    const rows = Array.from({ length: DNC_LIST_LIMIT }, (_, i) =>
      entry({
        id: `0192f0aa-4444-7000-8000-${String(i).padStart(12, "0")}`,
        phone_e164: `+9198765400${String(i % 100).padStart(2, "0")}`,
      }),
    );
    const { container } = await renderClientPage(<DoNotCallPage />, {
      "/v1/me": ME,
      [LIST_PATH]: rows,
    });

    await screen.findByText("Showing the 500 most recently added", { exact: false });
    expect(container.textContent).not.toContain("500 entries");
    // A real full-length list, so the timeout is explicit and generous rather than left
    // at vitest's 5s default: this renders five hundred rows, and it shares a machine
    // with `wireLookupGuard`'s whole-program `tsc` build. It runs in under two seconds
    // idle and blew the default the first time the suite ran them together — and a guard
    // that fails on a busy machine is a guard somebody deletes.
  }, 30_000);

  it("renders no heading of its own — the shell already prints the page title", async () => {
    const { container } = await renderList([]);

    await screen.findByText("Nobody is suppressed yet");
    expect(container.querySelector("h1")).toBeNull();
  });
});

describe("adding numbers", () => {
  async function addTwo(answer: unknown) {
    const rendered = await renderClientPage(<DoNotCallPage />, {
      "/v1/me": ME,
      [LIST_PATH]: [],
      "/v1/dnc": answer,
    });
    const box = (await screen.findByLabelText("Numbers to suppress")) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: `${PHONE}\n9876543211` } });
    fireEvent.click(screen.getByRole("button", { name: /^Add 2 numbers/ }));
    return { ...rendered, box };
  }

  it("sends the numbers in the body and never in a URL", async () => {
    const { calls } = await addTwo({ added: 2, already_suppressed: 0, malformed: 0 });

    await screen.findByText("Added");
    const posted = calls.filter((c) => c.path === "/v1/dnc" && c.method === "POST");
    expect(posted).toHaveLength(1);
    expect(posted[0].body).toContain("9876543211");
    for (const call of calls) {
      expect(
        call.url,
        `${call.method} ${call.path} carries a number in its URL`,
      ).not.toContain(PHONE_DIGITS);
    }
  });

  it("answers with counts only — never with which number went where", async () => {
    // `AddNumbersOut` is three integers BY DESIGN: who asked us to stop calling them is
    // itself personal data, so neither the response nor the audit row carries numbers.
    // A screen that echoed the pasted list back as a per-number result would reintroduce
    // exactly what the API refused to send.
    const { container, box } = await addTwo({
      added: 1,
      already_suppressed: 1,
      malformed: 0,
    });

    await screen.findByText("Added");
    expect(container.textContent).toContain("Already on the list");
    expect(container.textContent).toContain("Not a usable number");
    // Cleared on success, so the numbers do not sit on screen next to a result that
    // cannot speak about them individually.
    expect(box.value).toBe("");
    expect(container.textContent).not.toContain("9876543210");
    expect(container.textContent).not.toContain("9876543211");
  });

  it("renders a refusal instead of counts when the add fails", async () => {
    const { container } = await addTwo(
      problem(422, { title: "Too many numbers", detail: "Add up to 2,000 at a time." }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    // No tile may appear: "Added 0" beside a failed request reads as "we processed your
    // list and none of it counted", which is a different and much worse sentence.
    expect(container.textContent).not.toContain("Suppressed from now on");
  });
});

describe("checking a number", () => {
  async function check(answer: unknown, me: Me = ME) {
    const rendered = await renderClientPage(<DoNotCallPage />, {
      "/v1/me": me,
      [LIST_PATH]: [],
      "/v1/dnc/check": answer,
    });
    fireEvent.change(await screen.findByLabelText("Phone number to check"), {
      target: { value: PHONE },
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
    expect(posted[0].body).toBe(JSON.stringify({ phone: PHONE }));

    for (const call of calls) {
      expect(call.url, `${call.method} ${call.path} carries the number in its URL`).not.toContain(
        "9876543210",
      );
    }
  });

  it("stays available to a viewer who may not write, because the read permission differs", async () => {
    // `/v1/dnc/check` is `leads:read`; only add/remove are `leads:dispatch`. Gating the
    // check on the write permission would take the answer away from `staff` and from a
    // read-only support session — the two principals most likely to be asking it.
    await check({ valid: true, suppressed: true, scope: "tenant" }, READ_ONLY_ME);
    await screen.findByText(/This number is suppressed/);
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

  it("renders a refusal, not a verdict, when the check itself fails", async () => {
    // Same shape as the list failure and a worse consequence: this card's green panel is
    // the one a client reads as permission to dial, so a request that never landed must
    // produce no panel at all.
    const { container } = await check(problem(503, { title: "Service unavailable" }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).not.toContain("not on the do-not-call list");
    expect(container.textContent).not.toContain("This number is suppressed");
    expect(container.textContent).not.toContain("does not look like a phone number");
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

/**
 * DNC-1 🔒 — putting a person back in the dial pool is a decision, not a click.
 *
 * "Remove" used to call the DELETE straight out of `onClick`. The consequence is that
 * agents will ring that person again, immediately: this screen's own header says the list
 * is checked live before every single call, which is as true of a removal as it is of an
 * addition. Under TCCCPR a wrongly-removed suppression is a call that should not have
 * happened, and the friction on this lane was inverted before this — `/data-rights` makes
 * a client type the word ERASE to destroy a person's data, while returning a person to the
 * dial pool cost one press.
 *
 * The tests are about the ORDER of effects, because that is the whole of the fix: nothing
 * may leave the browser until the second press.
 */
describe("un-suppressing is confirmed before it happens", () => {
  it("sends nothing on the first press, and names the number in the dialog", async () => {
    const { calls } = await renderList([entry()]);

    await screen.findByText(PHONE);
    fireEvent.click(removeButtons()[0]);

    const dialog = await screen.findByRole("dialog");
    expect(calls.filter((call) => call.method === "DELETE")).toEqual([]);
    // Target, not merely intent: a confirmation that cannot say WHICH number confirms
    // that a removal was meant and says nothing about whose.
    expect(within(dialog).getByText(PHONE)).toBeTruthy();
    // …and the consequence, in the client's terms rather than as a restatement of the
    // command (NN/g, *Preventing User Errors*).
    expect(dialog.textContent).toContain("able to ring this person again");
  });

  it("leaves the number suppressed when the client backs out", async () => {
    const { calls } = await renderList([entry()]);

    await screen.findByText(PHONE);
    fireEvent.click(removeButtons()[0]);
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Keep it suppressed" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.filter((call) => call.method === "DELETE")).toEqual([]);
    // The row is still there, still offering the control — cancelling is not a state the
    // screen has to be reloaded out of.
    expect(removeButtons()).toHaveLength(1);
  });

  it("is a real modal: labelled, and focus is inside it", async () => {
    // `aria-modal` without a focus trap is the half of the contract that leaves a
    // keyboard user typing into the page behind the dialog. `useFocusTrap` is the shared
    // implementation and this is the assertion that this dialog actually uses it.
    await renderList([entry()]);

    await screen.findByText(PHONE);
    fireEvent.click(removeButtons()[0]);

    const dialog = await screen.findByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("aria-labelledby")).toBeTruthy();
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("stays open, showing the server's refusal, when the delete fails", async () => {
    // A dialog that closed on a failure would say the number is no longer suppressed
    // when it still is — a compliance claim made about a request that was refused.
    const { calls } = await renderClientPage(<DoNotCallPage />, {
      "/v1/me": ME,
      [LIST_PATH]: [entry()],
      "/v1/dnc/0192f0aa-4444-7000-8000-000000000001": problem(422, {
        title: "Request rejected by a business rule",
        detail: "This number recorded a consumer opt-out and cannot be removed.",
        kind: "business_rule",
      }),
    });

    await screen.findByText(PHONE);
    fireEvent.click(removeButtons()[0]);
    await confirmUnsuppress(calls);

    const dialog = await screen.findByRole("dialog");
    await waitFor(() =>
      expect(dialog.textContent).toContain("recorded a consumer opt-out"),
    );
  });
});
