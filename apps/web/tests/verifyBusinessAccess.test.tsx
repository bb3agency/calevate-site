import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import VerifyBusinessPage from "@/app/c/[slug]/verify-business/page";
import type { Me } from "@/lib/api/client";
import { KYC_PATH, type KycRecord } from "@/lib/api/kyc";
import { OWN_NUMBERS_PATHS } from "@/lib/api/ownNumbers";
import { PLEDGE_PATH, pendingRunKey } from "@/lib/api/verifyBusiness";

import { KYC_NOT_STARTED } from "./fixtures/sharedReads";
import { problem, renderClientPage, type Routes } from "./harness";

/**
 * Verify your business: who may act, and how a DigiLocker return ends.
 *
 * - A read-only member and a view-as operator see every action disabled, with the reason,
 *   before the server refuses it (uploads and the pledge are the business's own acts).
 * - The pending DigiLocker reference is kept per account and forgotten once the run has an
 *   outcome — an error included — so a stale one never greets a later visit.
 * - Where we asked for DigiLocker and it is unavailable, the page does not send the client
 *   to an upload that cannot clear the request.
 */

const OWNER: Me = {
  impersonating: false,
  withheld_acts: [],
  permissions: ["org:read", "org:manage"],
  realm: "client",
  role: "owner",
  user_id: "user_1",
  organization: null,
};

const READER: Me = { ...OWNER, permissions: ["org:read"], role: "staff" };

const OPERATOR: Me = {
  ...OWNER,
  impersonating: true,
  withheld_acts: ["compliance.kyc_documents", "compliance.outbound_pledge"],
};

const PLEDGE = {
  version: 2,
  pledge_text: "We do not cold-call.",
  text_sha256: "0".repeat(64),
  is_current: false,
  accepted_version: null,
  accepted_at: null,
};

const READY_FOR_OWNER: KycRecord = {
  ...KYC_NOT_STARTED,
  entity_type: "private_limited",
  legal_business_name: "Acme Clinic Pvt Ltd",
  gst_registered: true,
  gstin: "36AABCT1234C1Z5",
  documents: [
    {
      id: "0192f0aa-7777-7000-8000-000000000d01",
      slot: "business",
      kind: "gst",
      filename: "gst.pdf",
      content_type: "application/pdf",
      size_bytes: 1000,
      held: true,
      uploaded_at: "2026-10-08T09:00:00Z",
    },
  ],
};

function routes(me: Me, kyc: KycRecord = KYC_NOT_STARTED, extra: Routes = {}): Routes {
  return {
    "/v1/me": me,
    [KYC_PATH]: kyc,
    [PLEDGE_PATH]: PLEDGE,
    [OWN_NUMBERS_PATHS.status]: { available: false },
    ...extra,
  };
}

afterEach(() => {
  window.sessionStorage.clear();
});

describe("who may act on Verify your business", () => {
  it("lets an owner save the details and accept the pledge", async () => {
    await renderClientPage(<VerifyBusinessPage />, routes(OWNER));
    const accept = (await screen.findByRole("button", { name: "Accept the pledge" })) as HTMLButtonElement;
    expect(screen.queryByText(/Only an account owner can/)).toBeNull();
    expect(screen.queryByText(/from a view-as session/)).toBeNull();
    // Still disabled until the pledge is ticked as read, but for that reason only.
    expect(accept.disabled).toBe(true);
  });

  it("disables every action for a read-only member and says why", async () => {
    await renderClientPage(<VerifyBusinessPage />, routes(READER));
    expect(await screen.findByText("Only an account owner can accept the pledge.")).toBeTruthy();
    expect(screen.getByText("Only an account owner can verify the business.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save details" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("checkbox") as HTMLInputElement).disabled).toBe(true);
  });

  it("disables the uploads and the pledge for a view-as operator, with the server's reason", async () => {
    await renderClientPage(<VerifyBusinessPage />, routes(OPERATOR, READY_FOR_OWNER));
    expect(
      await screen.findByText(/you cannot accept the pledge from a view-as session/),
    ).toBeTruthy();
    expect(screen.getByText(/you cannot upload verification documents from a view-as session/)).toBeTruthy();
    for (const input of document.querySelectorAll<HTMLInputElement>('input[type="file"]')) {
      expect(input.disabled).toBe(true);
    }
    // Saving the details is not withheld from an operator: no reason is attached to it.
    expect(screen.getByRole("button", { name: "Save details" }).getAttribute("title")).toBeNull();
  });
});

describe("the DigiLocker return", () => {
  const COMPLETE = `POST ${KYC_PATH}/verification/complete`;

  it("ignores a run another account started in this tab", async () => {
    window.sessionStorage.setItem(pendingRunKey("other-clinic"), "run-other");
    const { calls } = await renderClientPage(<VerifyBusinessPage />, routes(OWNER));
    await screen.findByRole("button", { name: "Accept the pledge" });
    expect(calls.some((call) => call.method === "POST")).toBe(false);
    expect(window.sessionStorage.getItem(pendingRunKey("other-clinic"))).toBe("run-other");
  });

  it.each([
    ["expired", "That DigiLocker visit expired"],
    ["replay", "That DigiLocker visit was already recorded"],
  ])("says what a %s outcome means and forgets the run", async (outcome, title) => {
    window.sessionStorage.setItem(pendingRunKey("acme"), "run-1");
    const { calls } = await renderClientPage(
      <VerifyBusinessPage />,
      routes(OWNER, KYC_NOT_STARTED, { [COMPLETE]: { status: outcome, record: KYC_NOT_STARTED } }),
    );
    expect(await screen.findByText(title)).toBeTruthy();
    const sent = calls.filter((call) => call.method === "POST" && call.path.endsWith("/verification/complete"));
    expect(JSON.parse(sent[0].body ?? "{}")).toEqual({ provider_ref: "run-1" });
    expect(window.sessionStorage.getItem(pendingRunKey("acme"))).toBeNull();
  });

  it("forgets the run when completing it fails, so the error does not come back", async () => {
    window.sessionStorage.setItem(pendingRunKey("acme"), "run-gone");
    await renderClientPage(
      <VerifyBusinessPage />,
      routes(OWNER, KYC_NOT_STARTED, {
        [COMPLETE]: problem(404, {
          type: "https://calevate.tech/problems/not_found",
          detail: "We could not find that verification run.",
        }),
      }),
    );
    expect(await screen.findByText("We could not find that verification run.")).toBeTruthy();
    await waitFor(() => expect(window.sessionStorage.getItem(pendingRunKey("acme"))).toBeNull());
  });

  it("keeps the run while DigiLocker has not finished", async () => {
    window.sessionStorage.setItem(pendingRunKey("acme"), "run-2");
    await renderClientPage(
      <VerifyBusinessPage />,
      routes(OWNER, KYC_NOT_STARTED, { [COMPLETE]: { status: "pending", record: KYC_NOT_STARTED } }),
    );
    expect(await screen.findByText("DigiLocker has not finished yet")).toBeTruthy();
    expect(window.sessionStorage.getItem(pendingRunKey("acme"))).toBe("run-2");
  });
});

describe("DigiLocker asked for and unavailable", () => {
  it("does not send the client to an upload that cannot clear the request", async () => {
    await renderClientPage(
      <VerifyBusinessPage />,
      routes(OWNER, {
        ...READY_FOR_OWNER,
        status: "verified",
        is_verified: true,
        digilocker_required: true,
        digilocker_required_reason: "The owner's name did not match.",
        digilocker_outstanding: true,
        self_verification_available: false,
      }),
    );
    expect(await screen.findByText(/DigiLocker verification is temporarily unavailable/)).toBeTruthy();
    expect(screen.getByText(/Please contact us/)).toBeTruthy();
    expect(screen.queryByText(/upload the owner's ID for our review instead/)).toBeNull();
  });
});
