import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ClientAccountPage from "@/app/(auth)/auth/account/page";
import { clientAuthn } from "@/lib/authn/clientAuthn";

import { problem, stubApi, type Routes } from "./harness";

/**
 * `/auth/account` — the block that says WHICH account this session is in.
 *
 * The page manages a credential (verify the address, change the password, end every
 * session) and, until this block existed, named no account while doing it: the session row
 * carries a realm, a subject id and a verified flag, none of which a person recognises. An
 * owner of two businesses, or a colleague invited to one, could not tell from this screen
 * whose password they were about to change.
 *
 * What is asserted here is the pair that makes that block trustworthy rather than
 * decorative: it prints what the SERVER answered, and when the server does not answer it
 * prints nothing at all (BUILD-LOG §52). An account name is exactly the kind of fact a
 * placeholder ruins — a dash where the name goes cannot be told apart from a dash where
 * the API died, which is the amber arm the console sidebar had to grow for the same reason.
 */

const ME = {
  user_id: "0192f0aa-0000-7000-8000-0000000000c1",
  realm: "client",
  role: "owner",
  permissions: ["org:read", "org:manage"],
  impersonating: false,
  organization: {
    id: "0192f0aa-0000-7000-8000-0000000000d1",
    name: "Sri Lakshmi Dental",
    slug: "sri-lakshmi-dental",
    status: "active",
  },
};

/** A staff member: same page, one permission fewer, a different sentence under the role. */
const STAFF_ME = { ...ME, role: "staff", permissions: ["org:read"] };

async function renderPage(routes: Routes) {
  const calls = stubApi(routes);
  await act(async () => {
    render(<ClientAccountPage />);
  });
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  clientAuthn.reset();
});

describe("the account this session is in", () => {
  it("names the account and the role the server answered with", async () => {
    await renderPage({ "/v1/me": ME });

    expect(await screen.findByText("Sri Lakshmi Dental")).toBeTruthy();
    expect(screen.getByText("sri-lakshmi-dental")).toBeTruthy();
    expect(screen.getByText("owner")).toBeTruthy();
    // The sentence under the role is derived from the PERMISSIONS the server sent, never
    // from the word "owner" — the same set every gated control on the console previews
    // itself against, so the two cannot disagree about what this person may do.
    expect(
      screen.getByText(
        "You can change this account's settings and invite colleagues.",
      ),
    ).toBeTruthy();
  });

  it("tells a staff member whose the settings are, without offering a control", async () => {
    await renderPage({ "/v1/me": STAFF_ME });

    expect(await screen.findByText("staff")).toBeTruthy();
    expect(
      screen.getByText(
        "Settings, billing and the team are your account owner's to change.",
      ),
    ).toBeTruthy();
  });

  it("refuses rather than inventing an account when the read fails", async () => {
    await renderPage({
      "/v1/me": problem(503, {
        type: "urn:calevate:common/unavailable",
        title: "Service unavailable",
        detail: "We could not reach the account service.",
        kind: "server",
      }),
    });

    // The refusal is on screen…
    expect(
      await screen.findByText(
        /this is the separate read that says which account/,
      ),
    ).toBeTruthy();
    // …and nothing on the page claims an account, a role or a slug. A placeholder here is
    // the defect, not the fallback.
    expect(screen.queryByText("Sri Lakshmi Dental")).toBeNull();
    expect(screen.queryByText("Your role")).toBeNull();
    expect(screen.queryByText("—")).toBeNull();
    // The session itself is untouched by a failed identity read: the controls this page
    // exists for are all still there.
    expect(
      screen.getByRole("button", { name: "Sign out everywhere" }),
    ).toBeTruthy();
  });

  it("offers the way back to the console, through the junction that resolves it", async () => {
    await renderPage({ "/v1/me": ME });

    const back = await screen.findByRole("link", { name: "Open your console" });
    // `/c`, not `/c/<slug>`: the junction is the one place "which console is mine" is
    // answered, and it stays right in the case a slug-built link would be dead — the read
    // that failed.
    expect(back.getAttribute("href")).toBe("/c");
  });

  it("says what a verified address is FOR, rather than that there is nothing to do", async () => {
    await renderPage({ "/v1/me": ME });

    expect(
      await screen.findByText(
        "It is the only address we email a code or a password reset link to, so keep it one you can open.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("Nothing to do here.")).toBeNull();
  });
});
