import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import VerificationPage from "@/app/c/[slug]/verification/page";
import { KYC_PATH, type KycRecord } from "@/lib/api/kyc";

import { renderClientPage } from "./harness";
import { PE_REGISTRATION_PATH } from "@/lib/api/dltRegistration";
import { DLT_NOT_RECORDED } from "./fixtures/sharedReads";

/**
 * The green tick comes from `is_verified`, never from `status === "verified"`.
 *
 * They agree almost always, which is what makes the difference dangerous: a KYC record
 * whose paperwork has lapsed still carries `status: "verified"` while the server's
 * `is_verified` has gone false, and the gates that refuse the account's calls read the
 * second one. A screen that keyed on `status` would tell a client they are cleared
 * while every outbound call is being refused — and it would type-check, because both
 * fields are on the same model.
 *
 * That is not hypothetical here: the verdict box DID key its headline and its colour on
 * `status` (`KYC_STATUS_COPY[status]`) while the panels underneath keyed on the boolean,
 * so a lapsed record rendered "Your business is verified. Nothing here is holding up
 * your calls." in green, directly above the two cards telling the same client how to get
 * verified. The assertions below now cover the box as well as the panels.
 */

/**
 * The lead paragraph — present on every state, and only after the query has answered.
 *
 * Anchoring on it rather than on a heading: the app shell renders the page title from
 * the nav list, so the screen deliberately has no `<h1>` of its own to wait for.
 */
// Anchored to the header sentence: the number card says "Indian telecom rules require …" too.
const SCREEN = /To verify it, or to accept the no-cold-calls pledge/;

function record(over: Partial<KycRecord> = {}): KycRecord {
  return {
    recorded: true,
    status: "verified",
    is_verified: true,
    number_purchase_available: true,
    rejection_reason: null,
    document_kind: "cin",
    document_ref: "U72900TG2020PTC000001",
    entity_type: "private_limited",
    evidence_ref: "dpdp/kyc/2026/0001",
    signatory_name: "A Reddy",
    submitted_at: "2026-01-04T06:00:00Z",
    verified_at: "2026-01-09T06:00:00Z",
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
    ...over,
  };
}

async function renderWith(data: KycRecord) {
  return await renderClientPage(<VerificationPage />, {
    [KYC_PATH]: data,
    // The DLT half of the screen, registered and active, so every sentence about what is
    // still outstanding on this screen belongs to the KYC verdict under test.
    [PE_REGISTRATION_PATH]: {
      ...DLT_NOT_RECORDED,
      recorded: true,
      status: "active",
      tm_link_status: "active",
      pe_id: "1101234567890123456",
      entity_name: "Sri Clinic Pvt Ltd",
      registered_at: "2026-07-01T04:00:00Z",
      verified_at: "2026-08-01T04:00:00Z",
      is_active: true,
      calevate_tm_id: "1102345678901234567",
      calevate_tm_active: true,
    },
  });
}

describe("business verification verdict", () => {
  it("does NOT render a lapsed record as cleared, though its status still says verified", async () => {
    // The whole point. `status` is the last decision written down; `is_verified` is the
    // gate's live answer, and only the second one may paint the box green.
    const { container } = await renderWith(
      record({
        status: "verified",
        is_verified: false,
        number_purchase_available: false,
      }),
    );

    await screen.findByText(SCREEN);
    expect(container.textContent).toContain("Calls coming IN are unaffected");
    // The not-verified branch renders the two remediation panels; the cleared one does not.
    expect(
      screen.queryByText("What this affects while it is outstanding"),
    ).not.toBeNull();
    expect(screen.queryByText("What we need")).not.toBeNull();

    // THE VERDICT BOX ITSELF, which is the sentence the client reads first and the half
    // that was wrong: it carried `KYC_STATUS_COPY["verified"]` — headline, "next" and
    // the green tone — off the STATUS, directly above the two cards explaining how to
    // get verified. Either sentence alone is a lie in a different direction; together
    // they are a screen that cannot be acted on.
    expect(container.textContent).not.toContain("Your business is verified.");
    expect(container.textContent).not.toContain(
      "Nothing here is holding up your calls.",
    );
    expect(container.textContent).toContain(
      "Your business is not verified yet.",
    );
  });

  it("does not withhold the cleared state because the status is one it cannot name", async () => {
    // The same rule read the other way, and the reason `verdictCopy` covers both
    // directions: the server says this account is verified, so a status string this
    // build predates must not send the client chasing a block that does not exist.
    const { container } = await renderWith(
      record({ status: "verified_by_operator" }),
    );

    await screen.findByText(SCREEN);
    expect(container.textContent).toContain("Your business is verified.");
    expect(screen.queryByText("What we need")).toBeNull();
    // Fails VISIBLE: the unrecognised word is still on screen, in the record we hold,
    // so a client can quote it back to us.
    expect(container.textContent).toContain("verified_by_operator");
  });

  it("renders the cleared state only when the server says verified", async () => {
    const { container } = await renderWith(record());

    await screen.findByText(SCREEN);
    expect(
      screen.queryByText("What this affects while it is outstanding"),
    ).toBeNull();
    expect(screen.queryByText("What we need")).toBeNull();
    expect(container.textContent).not.toContain(
      "Calls coming IN are unaffected",
    );
  });

  it("treats a status this build has never heard of as not cleared", async () => {
    // A future status must fall back to "not verified yet, ask us" — vaguer than we
    // would like and the only answer that cannot be wrong.
    const { container } = await renderWith(
      record({ status: "under_appeal", is_verified: false, verified_at: null }),
    );

    await screen.findByText("Your business is not verified yet.");
    expect(container.textContent).toContain(
      "Ask us where your verification stands.",
    );
  });

  it("survives a status that collides with an Object prototype key", async () => {
    // `isKnownKycStatus` used `value in KYC_STATUS_COPY`, which is TRUE for
    // "constructor" — the copy lookup then returned `Object` and the verdict box
    // rendered with no headline and an undefined tone class instead of the fallback.
    const { container } = await renderWith(
      record({ status: "constructor", is_verified: false, verified_at: null }),
    );

    await screen.findByText("Your business is not verified yet.");
    expect(container.textContent).not.toContain("undefined");
  });

  it("shows a leftover refusal reason only while the account is still not cleared", async () => {
    // The reason is the last thing we told them and the thing they are answering — but
    // under a verified record it would explain a decision that has since been reversed.
    const reason =
      "The registration number does not match the name on the account.";

    const stillHeld = await renderWith(
      record({
        status: "rejected",
        is_verified: false,
        rejection_reason: reason,
      }),
    );
    await screen.findByText(SCREEN);
    expect(stillHeld.container.textContent).toContain(reason);
    stillHeld.unmount();

    const cleared = await renderWith(record({ rejection_reason: reason }));
    await screen.findByText(SCREEN);
    expect(cleared.container.textContent).not.toContain(reason);
  });
});
