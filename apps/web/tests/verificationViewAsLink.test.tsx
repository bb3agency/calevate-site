import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import VerificationPage from "@/app/c/[slug]/verification/page";
import { PE_REGISTRATION_PATH } from "@/lib/api/dltRegistration";
import { KYC_PATH } from "@/lib/api/kyc";

import { KYC_NOT_STARTED } from "./fixtures/sharedReads";
import { renderClientPage } from "./harness";

/**
 * The link from Verification to Verify your business keeps a view-as session, like every
 * other client link (`useClientRealm().href`). A bare `/c/{slug}/...` path drops the
 * `view=admin` marker, so an operator lands in the client realm with no session.
 */

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("view=admin"),
  usePathname: () => "/c/acme/verification",
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

describe("the Verify your business link", () => {
  it("carries the view-as marker in a view-as session", async () => {
    await renderClientPage(<VerificationPage />, {
      [KYC_PATH]: KYC_NOT_STARTED,
      [PE_REGISTRATION_PATH]: { recorded: false },
    });
    const link = await screen.findByRole("link", { name: "Verify your business" });
    expect(link.getAttribute("href")).toBe("/c/acme/verify-business?view=admin");
  });
});
