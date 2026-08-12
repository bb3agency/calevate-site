import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import VerificationPage from "@/app/c/[slug]/verification/page";
import { KYC_PATH, type KycRecord } from "@/lib/api/kyc";

import { renderClientPage } from "./harness";

/**
 * The green tick comes from `is_verified`, never from `status === "verified"`.
 *
 * They agree almost always, which is what makes the difference dangerous: a KYC record
 * whose paperwork has lapsed still carries `status: "verified"` while the server's
 * `is_verified` has gone false, and the gates that refuse the account's calls read the
 * second one. A screen that keyed on `status` would tell a client they are cleared
 * while every outbound call is being refused — and it would type-check, because both
 * fields are on the same model.
 */

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
    ...over,
  };
}

async function renderWith(data: KycRecord) {
  return await renderClientPage(<VerificationPage />, { [KYC_PATH]: data });
}

describe("business verification verdict", () => {
  it("does NOT render a lapsed record as cleared, though its status still says verified", async () => {
    // The whole point. `status` is the last decision written down; `is_verified` is the
    // gate's live answer, and only the second one may paint the box green.
    const { container } = await renderWith(
      record({ status: "verified", is_verified: false, number_purchase_available: false }),
    );

    await screen.findByText(/business verification/i);
    expect(container.textContent).toContain("Calls coming IN are unaffected");
    // The not-verified branch renders the two remediation panels; the cleared one does not.
    expect(screen.queryByText("What this affects while it is outstanding")).not.toBeNull();
    expect(screen.queryByText("What to send us")).not.toBeNull();
  });

  it("renders the cleared state only when the server says verified", async () => {
    const { container } = await renderWith(record());

    await screen.findByText(/business verification/i);
    expect(screen.queryByText("What this affects while it is outstanding")).toBeNull();
    expect(screen.queryByText("What to send us")).toBeNull();
    expect(container.textContent).not.toContain("Calls coming IN are unaffected");
  });

  it("treats a status this build has never heard of as not cleared", async () => {
    // A future status must fall back to "not verified yet, ask us" — vaguer than we
    // would like and the only answer that cannot be wrong.
    const { container } = await renderWith(
      record({ status: "under_appeal", is_verified: false, verified_at: null }),
    );

    await screen.findByText("Your business is not verified yet.");
    expect(container.textContent).toContain("Ask your account manager where your verification stands.");
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
    const reason = "The registration number does not match the name on the account.";

    const stillHeld = await renderWith(record({ status: "rejected", is_verified: false, rejection_reason: reason }));
    await screen.findByText(/business verification/i);
    expect(stillHeld.container.textContent).toContain(reason);
    stillHeld.unmount();

    const cleared = await renderWith(record({ rejection_reason: reason }));
    await screen.findByText(/business verification/i);
    expect(cleared.container.textContent).not.toContain(reason);
  });
});
