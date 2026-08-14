import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import VerificationPage from "@/app/c/[slug]/verification/page";
import { PE_REGISTRATION_PATH, type PeRegistration } from "@/lib/api/dltRegistration";
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
    expect(container.textContent).not.toContain("Your business is not verified yet.");
    expect(container.textContent).not.toContain("We have not verified your business yet.");
    expect(screen.queryByText("What to send us")).toBeNull();
    expect(screen.queryByText("What this affects while it is outstanding")).toBeNull();
    expect(screen.queryByText("What we hold about your business")).toBeNull();
  });

  it("leaves a way forward rather than a dead end", async () => {
    // A blank page is the failure mode that reads as "nothing is wrong here", and a
    // refusal with no retry is the one that reads as "and there is nothing you can do".
    // The screen has to pass `onRetry` for the button to exist at all — dropping it is a
    // one-character edit that leaves a blocked client reloading the browser.
    const { container } = await renderClientPage(<VerificationPage />, {
      [KYC_PATH]: problem(503, { title: "Service unavailable", retryable: true }),
      [PE_REGISTRATION_PATH]: PE_ACTIVE,
    });

    const alert = await screen.findByRole("alert");
    expect((container.textContent ?? "").trim().length).toBeGreaterThan(0);
    expect(within(alert).getByRole("button", { name: /try again/i })).toBeTruthy();
  });

  it("offers nothing to press — no upload, no self-verification, no number to buy", async () => {
    // The three controls this screen must never grow, asserted as one: every one of them
    // is a refusal the client would reach by clicking. `number_purchase_available` is the
    // server's own selector for the third, and it is false for every account today.
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
    expect(container.textContent).toContain("There is nothing to upload here, on purpose.");
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
    const card = screen.getByText("What we hold about your business").closest("section");
    expect(card?.textContent).not.toContain("Signed for the business by");
    expect(card?.textContent).not.toContain("Our file reference");
    // No dashed rows either: an em dash beside a label we DID print reads as a value we
    // are withholding, on the one card whose subject is what we hold.
    const values = [...(card?.querySelectorAll("dd") ?? [])].map((dd) => dd.textContent);
    expect(values).not.toContain("—");
    expect(container.textContent).toContain("Not on file");
  });

  it("keeps the number-purchase card a sentence rather than a control", async () => {
    // Verified, and still no form: the second half of `number_purchase_available` is
    // whether this deployment has a telephony provider at all, and it does not. A button
    // whose only outcome is an error costs the client a support ticket.
    const { container } = await renderClientPage(<VerificationPage />, {
      [KYC_PATH]: record({ status: "verified", is_verified: true, verified_at: "2026-03-01T06:00:00Z" }),
      [PE_REGISTRATION_PATH]: PE_ACTIVE,
    });

    await screen.findByText(SCREEN);
    expect(container.textContent).toContain("not available in Calevate yet");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(container.textContent).not.toContain("Buy a number");
  });
});
