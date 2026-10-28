import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import VerifyBusinessPage from "@/app/c/[slug]/verify-business/page";
import { PE_REGISTRATION_PATH, type PeRegistration } from "@/lib/api/dltRegistration";
import { KYC_PATH, type KycRecord } from "@/lib/api/kyc";
import { OWN_NUMBERS_PATHS } from "@/lib/api/ownNumbers";
import { PLEDGE_PATH, type OutboundPledge } from "@/lib/api/verifyBusiness";

import { OWNER_ME } from "./fixtures/sharedReads";
import { problem, renderClientPage } from "./harness";

/**
 * Verify your business as the GATE it explains (D-875 folded the read-only Verification
 * screen into it): what it may say when it does not know, what it says about inbound, and
 * the record it shows.
 *
 * `verificationVerdict.test.tsx` owns which sentence goes with which record. This file owns
 * the failures around it:
 *
 * 1. **A request that did not land produces a refusal, not a state.** "You are verified"
 *    tells a blocked client to stop chasing us, and "not verified" sends a cleared one
 *    hunting for a certificate; neither may be printed on a failed read, and the page must
 *    not go blank either.
 * 2. **No control sets a status, and none sells a number.** The client supplies details,
 *    documents and the pledge; our review or a DigiLocker result decides (Telecom Act 2023
 *    s.3(7)), and the number is ours to provide.
 */

function record(over: Partial<KycRecord> = {}): KycRecord {
  return {
    recorded: true,
    status: "submitted",
    is_verified: false,
    number_purchase_available: false,
    verification_source: "operator",
    verification_provider: null,
    verification_reference: null,
    verified_name: null,
    self_verification_available: false,
    kyc_path: null,
    legal_business_name: null,
    gst_registered: null,
    gstin: null,
    owner_id_type: null,
    owner_id_masked: null,
    name_match: null,
    digilocker_required: false,
    digilocker_required_reason: null,
    digilocker_outstanding: false,
    documents: [],
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

const PLEDGE_ACCEPTED: OutboundPledge = {
  version: 1,
  pledge_text: "We do not cold-call.",
  text_sha256: "0".repeat(64),
  is_current: true,
  accepted_version: 1,
  accepted_at: "2026-02-01T06:00:00Z",
};

/** Active on purpose: these cases are about the KYC half. */
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

function render(kyc: unknown) {
  return renderClientPage(<VerifyBusinessPage />, {
    "/v1/me": OWNER_ME,
    [KYC_PATH]: kyc,
    [PLEDGE_PATH]: PLEDGE_ACCEPTED,
    [PE_REGISTRATION_PATH]: PE_ACTIVE,
    [OWN_NUMBERS_PATHS.status]: { available: false },
  });
}

const VERIFIED = record({ status: "verified", is_verified: true, verified_at: "2026-03-01T06:00:00Z" });

describe("Verify your business under a failed read", () => {
  it("refuses to answer at all when the record could not be read", async () => {
    const { container } = await render(
      problem(503, { title: "Service unavailable", detail: "We could not read your verification." }),
    );

    expect(await screen.findByRole("alert")).toBeTruthy();
    const text = container.textContent ?? "";
    expect(text).not.toContain("Your business is verified.");
    expect(text).not.toContain("Your business is not verified yet.");
    expect(text).not.toContain("We have not verified your business yet.");
    expect(text).not.toContain("Outgoing calls are open");
    expect(text).not.toContain("Outgoing calls are paused");
    expect(screen.queryByText("Steps to open outgoing calls")).toBeNull();
    expect(screen.queryByText("What we hold about your business")).toBeNull();
  });

  it("leaves a way forward rather than a dead end", async () => {
    const { container } = await render(problem(503, { title: "Service unavailable", retryable: true }));

    const alert = await screen.findByRole("alert");
    expect((container.textContent ?? "").trim().length).toBeGreaterThan(0);
    expect(within(alert).getByRole("button", { name: /try again/i })).toBeTruthy();
  });

  it("never says outgoing calls are open when the pledge did not load", async () => {
    // A verified business with an unknown pledge: the summary has no answer, so it gives none.
    const { container } = await renderClientPage(<VerifyBusinessPage />, {
      "/v1/me": OWNER_ME,
      [KYC_PATH]: VERIFIED,
      [PLEDGE_PATH]: problem(503, { title: "Service unavailable", detail: "The pledge is unavailable." }),
      [PE_REGISTRATION_PATH]: PE_ACTIVE,
      [OWN_NUMBERS_PATHS.status]: { available: false },
    });
    expect(await screen.findByText("The pledge is unavailable.")).toBeTruthy();
    expect(container.textContent).not.toContain("Outgoing calls are open");
  });
});

describe("what the page offers", () => {
  it("has nothing to fill in once the business is verified and the pledge accepted", async () => {
    const { container } = await render(VERIFIED);

    expect(await screen.findByText("Outgoing calls are open")).toBeTruthy();
    expect(container.querySelector('input[type="file"]')).toBeNull();
    expect(container.querySelectorAll("form")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /verif/i })).toBeNull();
  });

  it("tells a client where their number comes from, and never offers to sell one", async () => {
    // The number is ours to provide (founder, 2 Oct 2026), and no provider is named to a
    // client (white label, 6 Oct 2026). No price and no timeline is promised here.
    const { container } = await render(VERIFIED);

    await screen.findByText("Outgoing calls are open");
    const text = container.textContent ?? "";
    expect(text).toContain("Calevate provides your calling number.");
    expect(text).toContain("our own telephony account");
    for (const provider of ["Plivo", "Exotel", "Thinnest"]) {
      expect(text).not.toContain(provider);
    }
    expect(text).not.toContain("subscriber of record");
    expect(text).not.toContain("Buy a number");
    expect(text).not.toContain("₹");
    expect(text).not.toContain("we will arrange");
  });

  it("does not print a record it does not hold", async () => {
    // "What we hold about your business" answers a DPDP question, so an invented row is a
    // false statement about our own processing: empty fields are dropped, never dashed.
    const { container } = await render(NOTHING_ON_FILE);

    await screen.findByText("Outgoing calls are paused");
    const held = container.querySelector('[data-section="on-file"]');
    expect(held?.textContent).not.toContain("Signed for the business by");
    expect(held?.textContent).not.toContain("Our file reference");
    const values = [...(held?.querySelectorAll("dd") ?? [])].map((dd) => dd.textContent);
    expect(values).not.toContain("—");
    expect(held?.textContent).toContain("Not on file");
  });

  it("says the record shown is the whole record", async () => {
    const { container } = await render(VERIFIED);
    await screen.findByText("What we hold about your business");
    expect(container.textContent).toContain(
      "That is the whole record. There is nothing else stored about your identity.",
    );
  });
});

/**
 * The refusals this page states as facts about the product, pinned as words. "Only a masked
 * owner ID" and "never take a full Aadhaar number" are the storage promises D-692 makes and
 * the schema CHECKs; "do not accept a copy of an Aadhaar card" is D-696's manual path; "calls
 * coming in are unaffected" is the one piece of good news on a page somebody opened because
 * their calls stopped.
 */
describe("the refusals stated on the page", () => {
  async function unverified() {
    const rendered = await render(NOTHING_ON_FILE);
    await screen.findByText("Outgoing calls are paused");
    return rendered;
  }

  it("says inbound is unaffected before anything else", async () => {
    const { container } = await unverified();
    const text = container.textContent ?? "";
    const inbound = text.indexOf("Incoming calls still work.");
    expect(inbound).toBeGreaterThan(-1);
    expect(inbound).toBeLessThan(text.indexOf("Steps to open outgoing calls"));
    expect(text).toContain("Incoming calls: unaffected, on every plan.");
  });

  it("refuses identity documents in words, not only in the schema", async () => {
    const { container } = await unverified();
    const text = container.textContent ?? "";
    expect(text).toContain("Only a masked owner ID.");
    expect(text).toContain("We do not accept a copy of an Aadhaar card, and we never take a full Aadhaar number.");
    expect(text).toContain("The document itself is never sent to us or stored.");
    expect(text).toContain("Verification is ours to do, not yours to declare.");
  });

  it("puts the steps above the explanation", async () => {
    // The page's job is "what do I do now", so the thing the client CAN do outranks the
    // list of what they cannot. Position, not merely presence.
    const { container } = await unverified();
    const text = container.textContent ?? "";
    const steps = text.indexOf("Steps to open outgoing calls");
    const consequences = text.indexOf("What this affects while it is outstanding");
    expect(steps).toBeGreaterThan(-1);
    expect(consequences).toBeGreaterThan(steps);
  });

  it("names the one next thing and jumps to it", async () => {
    await unverified();
    expect(screen.getByText("Next: add your business details.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to step 1" }).getAttribute("href")).toBe("#step-details");
    expect(document.getElementById("step-details")).not.toBeNull();
  });

  it("says we provide the number, and what the client's part is", async () => {
    const { container } = await unverified();
    const text = container.textContent ?? "";
    expect(text).toContain("Calevate provides your calling number.");
    expect(text).toContain("Your part is passing our business verification");
    expect(text).toContain("Then keep your caller details accurate.");
    expect(text).toContain("Your verification is still outstanding.");
    expect(text).not.toContain("API credentials");
  });
});
