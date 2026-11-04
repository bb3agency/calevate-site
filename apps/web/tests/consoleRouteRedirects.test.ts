import { describe, expect, it, vi } from "vitest";

const redirect = vi.fn((to: string) => {
  throw new Error(`NEXT_REDIRECT ${to}`);
});

vi.mock("next/navigation", () => ({ redirect: (to: string) => redirect(to) }));

const { default: SetupRedirect } = await import("@/app/c/[slug]/setup/page");
const { default: ExistingNumberRedirect } = await import("@/app/c/[slug]/setup/existing-number/page");
const { default: PhoneNumbersRedirect } = await import("@/app/c/[slug]/settings/phone-numbers/page");

type RetiredPage = (props: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) => Promise<void>;

/**
 * Screens folded into another keep their old address as a server redirect, so an email
 * already sent, a bookmark or an old link lands on the screen that replaced them. Every
 * query parameter rides along: `view=admin` keeps an operator's view-as session.
 */
async function landing(page: RetiredPage, search: Record<string, string | string[] | undefined>): Promise<string> {
  redirect.mockClear();
  await expect(page({ params: Promise.resolve({ slug: "acme" }), searchParams: Promise.resolve(search) })).rejects.toThrow(
    "NEXT_REDIRECT",
  );
  return redirect.mock.calls[0][0];
}

describe("Business setup, now a mode of Business profile", () => {
  it("opens the business profile one question at a time", async () => {
    expect(await landing(SetupRedirect, {})).toBe("/c/acme/settings/business?mode=steps");
  });

  it("keeps the step the old link named, and the view-as marker", async () => {
    expect(await landing(SetupRedirect, { step: "hours", view: "admin" })).toBe(
      "/c/acme/settings/business?step=hours&view=admin&mode=steps",
    );
  });
});

describe("Settings > Phone numbers, now a section of Phone numbers", () => {
  it("opens Phone numbers on Your existing number", async () => {
    expect(await landing(PhoneNumbersRedirect, { view: "admin" })).toBe("/c/acme/phone-number?view=admin&section=existing");
  });

  it("sends the existing-number guide to its new address", async () => {
    expect(await landing(ExistingNumberRedirect, {})).toBe("/c/acme/phone-number/existing-number");
  });
});
