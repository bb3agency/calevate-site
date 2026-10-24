import { describe, expect, it, vi } from "vitest";

const redirect = vi.fn((to: string) => {
  throw new Error(`NEXT_REDIRECT ${to}`);
});

vi.mock("next/navigation", () => ({ redirect: (to: string) => redirect(to) }));

const { default: VerificationRedirect } = await import("@/app/c/[slug]/verification/page");

/**
 * `/c/{slug}/verification` was folded into Verify your business (D-875). Old emails and
 * bookmarks still point at it, so it answers with a redirect that keeps every query
 * parameter: `view=admin` is what keeps an operator's view-as session on the next page.
 */
async function landing(search: Record<string, string | string[] | undefined>): Promise<string> {
  redirect.mockClear();
  await expect(
    VerificationRedirect({ params: Promise.resolve({ slug: "acme" }), searchParams: Promise.resolve(search) }),
  ).rejects.toThrow("NEXT_REDIRECT");
  return redirect.mock.calls[0][0];
}

describe("the retired verification route", () => {
  it("lands on Verify your business", async () => {
    expect(await landing({})).toBe("/c/acme/verify-business");
  });

  it("carries the view-as marker and every other parameter", async () => {
    expect(await landing({ view: "admin", provider_ref: "run-1", tag: ["a", "b"] })).toBe(
      "/c/acme/verify-business?view=admin&provider_ref=run-1&tag=a&tag=b",
    );
  });
});
