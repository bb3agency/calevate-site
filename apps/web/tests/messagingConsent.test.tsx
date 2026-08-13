import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MessagingConsentPage from "@/app/c/[slug]/messaging-consent/page";
import type { Me } from "@/lib/api/client";
import type { MessagingConsent } from "@/lib/api/messagingConsent";

import { problem, renderClientPage } from "./harness";

/**
 * Messaging consent — the screen that decides whether a business may message a person.
 *
 * `messagingConsentVerdict.test.tsx` already pins the one rule that outranks everything
 * else here: the verdict comes from `messageable` and is never recomputed from `status`.
 * This file is about the four ways the SCREEN around that verdict can lie, ranked by
 * what a wrong render costs:
 *
 * 1. **A failed lookup that renders a verdict.** Every box this card can paint is a
 *    claim about a person's stated wishes. "Nobody has asked them yet" on a request that
 *    never landed is the messaging twin of "nobody is suppressed" on the DNC list, and it
 *    is the sentence a client acts on when they decide to send anyway.
 * 2. **Blurring messaging consent with consent to be CALLED.** SEC-COMP §4 is explicit
 *    that a campaign's consent provenance and a callback row never satisfy this purpose
 *    and that nothing backfills it. A screen that implied otherwise would manufacture
 *    opt-ins out of call records.
 * 3. **An opt-in recorded without evidence.** `_assert_grant_is_evidenced` and a CHECK
 *    constraint both refuse it; the form must refuse it FIRST, and must never offer
 *    `staff_recorded_request` as a way to grant — that is implied consent under another
 *    name, which is exactly what the member exists to keep out.
 * 4. **The number in a URL.** Both endpoints are POSTs because the identifier IS the
 *    personal data (hard rule 6). The lookup path is asserted in the verdict file; the
 *    RECORD path is asserted here.
 *
 * `status: "none"` is deliberately NOT in that list of failures: nobody having been asked
 * is a normal state of the world and a 200, and a test below pins that it renders as a
 * plain answer rather than as an error.
 */

const LOOKUP_PATH = "/v1/compliance/messaging-consent/lookup";
const RECORD_PATH = "/v1/compliance/messaging-consent";
const RAW_PHONE = "+919876543210";

const ME: Me = {
  impersonating: false,
  permissions: ["leads:read", "leads:dispatch"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

/** `staff`: may read whether a number is messageable, may not record an answer. */
const READ_ONLY_ME: Me = { ...ME, permissions: ["leads:read"], role: "staff" };

/** D-22: an operator viewing the account. Reads keep working, every write is refused. */
const IMPERSONATING_ME: Me = { ...ME, impersonating: true };

function consent(over: Partial<MessagingConsent> = {}): MessagingConsent {
  return {
    messageable: false,
    status: "none",
    source: null,
    captured_at: null,
    expires_at: null,
    ...over,
  };
}

async function lookUp(answer: unknown, me: Me = ME) {
  const rendered = await renderClientPage(<MessagingConsentPage />, {
    "/v1/me": me,
    [LOOKUP_PATH]: answer,
  });
  fireEvent.change(await screen.findByLabelText("Phone number to check"), {
    target: { value: RAW_PHONE },
  });
  fireEvent.click(screen.getByRole("button", { name: "Check" }));
  return rendered;
}

describe("the lookup answers, or says it could not", () => {
  it("renders a refusal for a failed lookup — never a verdict", async () => {
    const { container } = await lookUp(
      problem(503, { title: "Service unavailable", detail: "We could not read the ledger." }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    // Not one of the four boxes may appear. Each is a statement about what a person
    // said, and the server said nothing.
    expect(container.textContent).not.toContain("Not messageable");
    expect(container.textContent).not.toContain("You may send this person WhatsApp messages.");
    expect(container.textContent).not.toContain("nobody has asked them yet");
  });

  it("treats `none` as a normal answer: neutral, not an error", async () => {
    // `MessagingConsentOut` says it in its docstring — nobody having asked is a 200 and
    // the normal state of the world, not a 404. It is still a no, and the screen says
    // both halves.
    const { container } = await lookUp(consent({ status: "none" }));

    await screen.findByText("Not messageable — nobody has asked them yet.");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container.textContent).toContain(
      "Campaign follow-ups will skip this number until someone records what they said",
    );
  });

  it("does not claim nobody asked when the status is one this build cannot read", async () => {
    // `status` is a bare `string` on the wire. Sharing a branch with `none` would turn
    // "we do not understand this record" into a confident factual claim about a person —
    // and the two need different actions from whoever is reading.
    const { container } = await lookUp(consent({ status: "suppressed_by_regulator" }));

    await screen.findByText("Not messageable — this record is one we cannot read.");
    expect(container.textContent).not.toContain("nobody has asked them yet");
    // The raw value is shown, because it is the only thing support can act on.
    expect(container.textContent).toContain("suppressed_by_regulator");
  });

  it("stays available to a read-only session, because the lookup is a READ permission", async () => {
    // `/v1/.../lookup` is `leads:read`; only recording is `leads:dispatch`. An
    // impersonating operator (D-22) is refused every mutating permission and keeps this
    // one — which is the whole reason the API put the lookup on a read.
    const { container } = await lookUp(consent({ status: "none" }), IMPERSONATING_ME);

    await screen.findByText("Not messageable — nobody has asked them yet.");
    expect(container.textContent).toContain("You are viewing this account read-only");
    expect(screen.queryByLabelText("Their number")).toBeNull();
  });
});

describe("messaging consent is not consent to be called", () => {
  it("says so on the screen, in both directions", async () => {
    const { container } = await renderClientPage(<MessagingConsentPage />, { "/v1/me": ME });

    await screen.findByText("Can we message this number?");
    // The purposes are separate (SEC-COMP §4, DPDP §6), nothing backfills one from the
    // other, and the do-not-call read still happens either way.
    expect(container.textContent).toContain("separate permission from calling");
    expect(container.textContent).toContain("Agreeing to a call is not agreeing to a message.");
    expect(container.textContent).toContain("This is in addition to do-not-call.");
  });

  it("never tells a messageable number that it may be CALLED", async () => {
    // The green box is the one someone screenshots. It authorises a WhatsApp message and
    // nothing else — the dial still passes the do-not-call and calling-hours gates.
    const { container } = await lookUp(
      consent({
        messageable: true,
        status: "granted",
        source: "web_form_optin",
        captured_at: "2026-06-01T10:00:00Z",
        expires_at: "2027-06-01T10:00:00Z",
      }),
    );

    await screen.findByText("You may send this person WhatsApp messages.");
    expect(container.textContent).not.toContain("may call");
    expect(container.textContent).not.toContain("not on the do-not-call list");
  });

  it("does not present itself as registrar-grade consent", async () => {
    // TCCCPR 2018 as amended (2nd Amendment, 12 Feb 2025): explicit consent under
    // Reg. 2(y) is recorded by the Consent Registrar on DLT. We cannot perform that
    // function, so what this screen captures is OUR evidence — and a client who thinks
    // otherwise will answer a regulator with it.
    const { container } = await renderClientPage(<MessagingConsentPage />, { "/v1/me": ME });

    await screen.findByText("How this record works");
    expect(container.textContent).toContain("This is your evidence, not a DLT record.");
  });
});

describe("recording an answer", () => {
  async function form(me: Me = ME, routes: Record<string, unknown> = {}) {
    const rendered = await renderClientPage(<MessagingConsentPage />, {
      "/v1/me": me,
      ...routes,
    });
    await screen.findByText("Can we message this number?");
    return rendered;
  }

  it("cannot submit an opt-in with no evidence, and says why before the click", async () => {
    await form();

    fireEvent.change(screen.getByLabelText("Their number"), { target: { value: RAW_PHONE } });
    // `.disabled` is the property the browser acts on; this suite carries no jest-dom.
    const submit = () =>
      screen.getByRole("button", { name: /Record their opt-in/ }) as HTMLButtonElement;

    // Default source is the spoken opt-in, which needs both the moment in the call and
    // the call itself. Neither is filled, so the button is refused with the first reason.
    expect(submit().disabled).toBe(true);
    expect(await screen.findByText(/An opt-in has to record what it rests on/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Where in the call"), {
      target: { value: "02:14–02:21" },
    });
    expect(submit().disabled).toBe(true);
    expect(
      await screen.findByText("A spoken opt-in has to name the call it was spoken on."),
    ).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Which call?"), { target: { value: "call-1" } });
    expect(submit().disabled).toBe(false);
  });

  it("never offers a staff-recorded source as a way to say yes", async () => {
    // `staff_recorded_request` cannot carry a `granted` row — a CHECK constraint bars it,
    // because a client employee asserting an opt-in on a consumer's behalf is implied
    // consent wearing a different name. It must be absent while answering yes and
    // present while answering no, which is the asymmetry the member exists for.
    await form();

    const staffOption = "Someone here recorded their request";
    expect(screen.queryByRole("option", { name: staffOption })).toBeNull();

    fireEvent.click(screen.getByLabelText("They do not want messages"));
    expect(await screen.findByRole("option", { name: staffOption })).toBeTruthy();
  });

  it("never obstructs a refusal — no evidence is asked for and none is required", async () => {
    await form();

    fireEvent.click(screen.getByLabelText("They do not want messages"));
    fireEvent.change(screen.getByLabelText("Their number"), { target: { value: RAW_PHONE } });

    const submit = (await screen.findByRole("button", {
      name: /Record their refusal/,
    })) as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
  });

  it("puts the number in the body of the record POST and in no URL (hard rule 6)", async () => {
    const { calls, container } = await form(ME, {
      [RECORD_PATH]: consent({ status: "withdrawn", captured_at: "2026-08-13T04:00:00Z" }),
    });

    fireEvent.click(screen.getByLabelText("They do not want messages"));
    fireEvent.change(screen.getByLabelText("Their number"), { target: { value: RAW_PHONE } });
    fireEvent.click(screen.getByRole("button", { name: /Record their refusal/ }));

    await screen.findByText("Recorded. This is where that number now stands:");
    const posted = calls.filter((c) => c.path === RECORD_PATH && c.method === "POST");
    expect(posted).toHaveLength(1);
    expect(posted[0].body).toContain(RAW_PHONE);
    for (const call of calls) {
      expect(call.url, `${call.method} ${call.path} carries the number`).not.toContain(
        "9876543210",
      );
    }
    // The ledger is append-only (hard rule 4): the screen confirms a new row, it never
    // offers to undo one.
    expect(container.textContent).toContain("Nothing is ever deleted.");
    expect(screen.queryByRole("button", { name: /delete/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /remove/i })).toBeNull();
  });

  it("renders a refusal, not a confirmation, when the write fails", async () => {
    const { container } = await form(ME, {
      [RECORD_PATH]: problem(422, {
        title: "Consent needs evidence",
        detail: "A grant must record what it rests on.",
      }),
    });

    fireEvent.click(screen.getByLabelText("They do not want messages"));
    fireEvent.change(screen.getByLabelText("Their number"), { target: { value: RAW_PHONE } });
    fireEvent.click(screen.getByRole("button", { name: /Record their refusal/ }));

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).not.toContain("Recorded. This is where that number now stands:");
  });

  it("gives a viewer without the write permission the reason instead of a 403", async () => {
    const { container } = await form(READ_ONLY_ME);

    expect(container.textContent).toContain(
      "Only an account owner can record what a customer said about being messaged.",
    );
    expect(screen.queryByLabelText("Their number")).toBeNull();
    // The read half of the screen is untouched by the write permission.
    expect(screen.getByLabelText("Phone number to check")).toBeTruthy();
  });

  it("renders no heading of its own — the shell already prints the page title", async () => {
    const { container } = await form();
    expect(container.querySelector("h1")).toBeNull();
  });
});
