import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import VerificationPage from "@/app/c/[slug]/verification/page";
import {
  PE_REGISTRATION_PATH,
  type PeRegistration,
} from "@/lib/api/dltRegistration";
import { KYC_PATH, type KycRecord } from "@/lib/api/kyc";

import { problem, renderClientPage } from "./harness";

/**
 * The verification screen as a GATE: what it may say when it does not know, and what it
 * may offer when the answer is no.
 *
 * `verificationVerdict.test.tsx` owns the verdict itself — which sentence goes with
 * which record. This file owns the two failures around it, both of which are invisible
 * to a type checker and expensive in opposite directions:
 *
 * 1. **A request that did not land must produce a refusal, not a state.** Every branch of
 *    this screen is reassuring to somebody: "you are verified" tells a blocked client to
 *    stop chasing us, and "send us your registration number" tells a cleared client to
 *    chase us for nothing. Neither may be printed on the strength of a request that
 *    failed, and the screen must not go BLANK either — an empty page on the screen a
 *    client opened because their calls stopped says "nothing is wrong here".
 * 2. **No control may exist that the client's own realm would be refused.** There is no
 *    client-realm write in `kyc.ts` at all: identity is the provider's to verify (Telecom
 *    Act 2023 s.3(7)), and the API stores a public registry REFERENCE, never a document —
 *    a CHECK constraint even refuses a bare twelve-digit `document_ref` so an Aadhaar
 *    cannot be typed into a business field. A file input or a "mark verified" button here
 *    would be a 403 with a DPDP incident attached.
 */

function record(over: Partial<KycRecord> = {}): KycRecord {
  return {
    recorded: true,
    status: "submitted",
    is_verified: false,
    number_purchase_available: false,
    rejection_reason: null,
    document_kind: "gstin",
    document_ref: "29ABCDE1234F1Z5",
    entity_type: "private_limited",
    evidence_ref: "dpdp/kyc/2026/0007",
    signatory_name: "A Reddy",
    submitted_at: "2026-02-01T06:00:00Z",
    verified_at: null,
    ...over,
  };
}

/** Nothing on file — a 200, and the state most likely to be confused with a failure. */
const NOTHING_ON_FILE: KycRecord = record({
  recorded: true,
  status: null,
  document_kind: null,
  document_ref: null,
  entity_type: null,
  evidence_ref: null,
  signatory_name: null,
  submitted_at: null,
});

/**
 * The DLT half of the screen, answering 200 with an ACTIVE registration.
 *
 * Present in every route table below because the screen now makes two independent reads
 * and the harness throws on an unrouted one. Active on purpose: these cases are about the
 * KYC half, and a blocked DLT registration would add a second verdict box to every
 * assertion about what the screen says.
 */
const PE_ACTIVE: PeRegistration = {
  recorded: true,
  status: "active",
  tm_link_status: "active",
  pe_id: "1101234567890123456",
  entity_name: "Sri Clinic Pvt Ltd",
  registered_at: "2026-01-05T06:00:00Z",
  verified_at: "2026-02-01T06:00:00Z",
  is_active: true,
  calevate_tm_id: "1234567890123456789",
  calevate_tm_active: true,
};

const SCREEN = /Indian telecom rules/;

describe("the verification gate under failure", () => {
  it("refuses to answer at all when the record could not be read", async () => {
    // THE assertion this file exists for. Both verdicts are absent, because we do not
    // have one — and "not verified" is as wrong here as "verified": it sends a client
    // hunting for a registration certificate to answer a question we never asked.
    const { container } = await renderClientPage(<VerificationPage />, {
      [KYC_PATH]: problem(503, {
        title: "Service unavailable",
        detail: "We could not read your verification.",
      }),
      [PE_REGISTRATION_PATH]: PE_ACTIVE,
    });

    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(container.textContent).not.toContain("Your business is verified.");
    expect(container.textContent).not.toContain(
      "Your business is not verified yet.",
    );
    expect(container.textContent).not.toContain(
      "We have not verified your business yet.",
    );
    expect(screen.queryByText("What to send us")).toBeNull();
    expect(
      screen.queryByText("What this affects while it is outstanding"),
    ).toBeNull();
    expect(screen.queryByText("What we hold about your business")).toBeNull();
  });

  it("leaves a way forward rather than a dead end", async () => {
    // A blank page is the failure mode that reads as "nothing is wrong here", and a
    // refusal with no retry is the one that reads as "and there is nothing you can do".
    // The screen has to pass `onRetry` for the button to exist at all — dropping it is a
    // one-character edit that leaves a blocked client reloading the browser.
    const { container } = await renderClientPage(<VerificationPage />, {
      [KYC_PATH]: problem(503, {
        title: "Service unavailable",
        retryable: true,
      }),
      [PE_REGISTRATION_PATH]: PE_ACTIVE,
    });

    const alert = await screen.findByRole("alert");
    expect((container.textContent ?? "").trim().length).toBeGreaterThan(0);
    expect(
      within(alert).getByRole("button", { name: /try again/i }),
    ).toBeTruthy();
  });

  it("offers nothing to press — no upload, no self-verification, no number to buy", async () => {
    // The three controls this screen must never grow, asserted as one: every one of them
    // is a refusal the client would reach by clicking. The third can never exist at all —
    // Calevate does not supply numbers (Model B), and `number_purchase_available` is the
    // server's own selector saying so for every account in every deployment.
    const { container } = await renderClientPage(<VerificationPage />, {
      [KYC_PATH]: record(),
      [PE_REGISTRATION_PATH]: PE_ACTIVE,
    });

    await screen.findByText(SCREEN);
    expect(container.querySelector('input[type="file"]')).toBeNull();
    expect(container.querySelectorAll("form")).toHaveLength(0);
    // Not "no button called Verify" — NO button at all. A page whose every write lives in
    // the admin realm has nothing to press, and naming the buttons individually is how
    // the fourth one gets added without anyone noticing.
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(container.textContent).toContain(
      "There is nothing to upload here, on purpose.",
    );
  });

  it("does not print a record it does not hold", async () => {
    // "What we hold about your business" is an answer to a DPDP question, so an invented
    // row is a false statement about our own processing. Fields we hold nothing in are
    // dropped rather than dashed, and the status label prints what is filed.
    const { container } = await renderClientPage(<VerificationPage />, {
      [KYC_PATH]: NOTHING_ON_FILE,
      [PE_REGISTRATION_PATH]: PE_ACTIVE,
    });

    await screen.findByText(SCREEN);
    const card = screen
      .getByText("What we hold about your business")
      .closest("section");
    expect(card?.textContent).not.toContain("Signed for the business by");
    expect(card?.textContent).not.toContain("Our file reference");
    // No dashed rows either: an em dash beside a label we DID print reads as a value we
    // are withholding, on the one card whose subject is what we hold.
    const values = [...(card?.querySelectorAll("dd") ?? [])].map(
      (dd) => dd.textContent,
    );
    expect(values).not.toContain("—");
    expect(container.textContent).toContain("Not on file");
  });

  it("tells a verified client where their number comes from, and never offers to get one", async () => {
    // Verified, and still no control — because there is nothing we could sell them. The
    // card has to survive two ways: it must not promise that Calevate obtains a number
    // (Model B, published Terms clause 3), and it must name the operators and what to
    // send back, or the client comes back with a support ticket.
    const { container } = await renderClientPage(<VerificationPage />, {
      [KYC_PATH]: record({
        status: "verified",
        is_verified: true,
        verified_at: "2026-03-01T06:00:00Z",
      }),
      [PE_REGISTRATION_PATH]: PE_ACTIVE,
    });

    await screen.findByText(SCREEN);
    const text = container.textContent ?? "";
    expect(text).toContain(
      "Calevate does not sell, rent or supply telephone numbers",
    );
    expect(text).toContain("Exotel");
    expect(text).toContain("Plivo");
    expect(text).toContain("Vobiz");
    expect(text).toContain("subscriber of");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(text).not.toContain("Buy a number");
    // The Model A promises this screen used to make, named so they cannot come back.
    expect(text).not.toContain("we will arrange");
    expect(text).not.toContain("We buy and register numbers");
  });
});

/**
 * The refusals this screen states as facts about the product, pinned as words.
 *
 * Each one is load-bearing outside this file. "There is nothing to upload" and "never
 * send an Aadhaar" are the sentences that keep an identity document off a business
 * field the schema has a CHECK against. "Verification is ours to do" is why
 * `readiness.ROW_COPY` tells a client to SEND us something rather than to type it here
 * (`tests/readiness_copy_actionability_test.py`). And "calls coming IN are unaffected" is
 * the one piece of good news on a page somebody opened because their calls stopped —
 * losing it turns an outbound block into a client believing their receptionist is down.
 */
describe("verification — the refusals stated on the screen", () => {
  async function unverified() {
    const rendered = await renderClientPage(<VerificationPage />, {
      [KYC_PATH]: NOTHING_ON_FILE,
      [PE_REGISTRATION_PATH]: PE_ACTIVE,
    });
    await screen.findByText(SCREEN);
    return rendered;
  }

  it("tells a blocked client their inbound line is still answering", async () => {
    const { container } = await unverified();
    expect(container.textContent).toContain(
      "Calls coming IN are unaffected — your agent keeps answering the phone.",
    );
    expect(container.textContent).toContain(
      "Incoming calls: unaffected, on every plan.",
    );
  });

  it("refuses identity documents in words, not only in the schema", async () => {
    const { container } = await unverified();
    expect(container.textContent).toContain(
      "There is nothing to upload here, on purpose.",
    );
    expect(container.textContent).toContain(
      "Never send an Aadhaar or an individual's PAN.",
    );
    expect(container.textContent).toContain(
      "No scan, no photograph and no copy of any document is stored",
    );
  });

  it("says verification is ours to do, which is why the copy sends them to us", async () => {
    const { container } = await unverified();
    expect(container.textContent).toContain(
      "Verification is ours to do, not yours to declare.",
    );
    expect(container.textContent).toContain(
      "Send these to your account manager",
    );
  });

  it("puts the action above the explanation while it is outstanding", async () => {
    // UX-DOCTRINE §1/§5: this screen's job is "what do I do now", so the thing the client
    // CAN do outranks the list of what they cannot. Position, not merely presence.
    const { container } = await unverified();
    const text = container.textContent ?? "";
    const action = text.indexOf("What to send us");
    const consequences = text.indexOf(
      "What this affects while it is outstanding",
    );
    expect(action).toBeGreaterThan(-1);
    expect(consequences).toBeGreaterThan(-1);
    expect(action).toBeLessThan(consequences);
  });

  it("says we do not supply numbers, and what the client does instead", async () => {
    const { container } = await unverified();
    expect(container.textContent).toContain(
      "Calevate does not sell, rent or supply telephone numbers.",
    );
    expect(container.textContent).toContain(
      "You stay the subscriber of record",
    );
    expect(container.textContent).toContain(
      "you can withdraw them at any time",
    );
  });

  it("says the record shown is the whole record", async () => {
    const { container } = await renderClientPage(<VerificationPage />, {
      [KYC_PATH]: record({
        is_verified: true,
        status: "verified",
        verified_at: "2026-02-02T06:00:00Z",
      }),
      [PE_REGISTRATION_PATH]: PE_ACTIVE,
    });
    await screen.findByText("What we hold about your business");
    expect(container.textContent).toContain(
      "That is the whole record — there is nothing else stored about your identity.",
    );
  });
});
