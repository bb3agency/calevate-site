import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import TeamPage from "@/app/c/[slug]/settings/team/page";
import type { Me } from "@/lib/api/client";
import { INVITE_PATH, INVITE_TOKEN_PARAM, inviteLink } from "@/lib/api/members";

import { renderClientPage } from "./harness";

/**
 * The invite link points at a page that exists — the defect this repo has already paid
 * for once, guarded rather than remembered.
 *
 * `POST /v1/invitations/accept` shipped on 2026-08-11 and the team screen started
 * printing `${origin}/invite?token=…` for owners to send out. There was no `/invite`
 * route for eight days, so every one of those links was a 404 served to somebody holding
 * a live, single-use credential to a client's account. The route landed later, and the
 * path was then spelled out in TWO places — the page's own local constant and the team
 * screen's template literal — which is the same defect one edit away from recurring.
 *
 * `inviteLink` is now the single definition, and since D-177 it points at
 * `/auth/accept-invitation` — the surviving invite page, after the Clerk-era `/invite` was
 * collapsed into it. Three things have to stay true and none is checkable by a type:
 *
 * 1. **It names a real Next route.** A constant and a directory can disagree silently;
 *    `tsc` has no opinion about either. So the path is resolved against `src/app`, through
 *    the ROUTE GROUPS — `(auth)` is invisible to the router and very visible to the
 *    filesystem, which is exactly the kind of gap this test exists to close.
 * 2. **The screen that hands the link to a human builds it from that definition**, rather
 *    than from a string of its own that happens to match today.
 * 3. **The dead URL still resolves.** `/invite?token=` is in inboxes that cannot be
 *    edited, so it has a page whose whole job is to forward the token. A 404 there would
 *    be the original defect back, aimed at everyone who was ever invited.
 */

const APP_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..", "src", "app");

const ME: Me = {
  impersonating: false,
  permissions: ["org:read", "org:manage", "leads:read"],
  realm: "client",
  role: "owner",
  user_id: "0192f0aa-6666-7000-8000-0000000000f1",
  organization: null,
};

describe("the invite link", () => {
  it("resolves to a page that exists in the app router", () => {
    expect(INVITE_PATH.startsWith("/")).toBe(true);
    // Route GROUPS are directories the router ignores, so a path→file check has to try
    // them. Written as a search rather than a hard-coded `(auth)` because a page moving
    // between groups is a refactor, and a page ceasing to exist is the defect.
    const candidates = ["", "(auth)"].map((group) =>
      resolve(APP_DIR, group, `.${INVITE_PATH}`, "page.tsx"),
    );
    expect(
      candidates.some(existsSync),
      `${INVITE_PATH} has no page at any of ${candidates.join(", ")}`,
    ).toBe(true);
  });

  it("leaves the Clerk-era /invite URL answering, because it is already in inboxes", () => {
    // D-177 collapsed two invite pages into one. The old URL cannot be deleted: every
    // owner who has used the team screen has sent it to somebody, those messages are not
    // editable, and a 404 tells a person holding a live single-use credential that their
    // invitation is broken. They get one.
    expect(existsSync(resolve(APP_DIR, "invite", "page.tsx"))).toBe(true);
    expect(INVITE_PATH).not.toBe("/invite");
  });

  it("carries the token in the parameter the page reads", () => {
    const link = inviteLink("a-token-with/slash");
    const url = new URL(link, "https://app.calevate.tech");
    expect(url.pathname).toBe(INVITE_PATH);
    expect(url.searchParams.get(INVITE_TOKEN_PARAM)).toBe("a-token-with/slash");
  });

  it("is NOT printed on the team screen any more — the invitee's mailbox is the only place it goes", async () => {
    // The inversion of the assertion this replaces, and the reason is D-190. The screen
    // used to print the raw token and tell the owner to forward it, which is the last half
    // of D-185: a token anyone but the invitee can see is a token anyone but the invitee
    // can redeem, and an owner could squat a stranger's address with it. The response no
    // longer carries a token at all, so there is nothing to print.
    const created = {
      id: "0192f0aa-6666-7000-8000-0000000000c1",
      email: "priya@clinic.example",
      role: "staff",
      invited_at: "2026-08-15T04:00:00Z",
      expires_at: "2026-08-18T04:00:00Z",
      delivery: "queued",
    };
    const { container } = await renderClientPage(<TeamPage />, {
      "/v1/me": ME,
      "/v1/members": [{ id: ME.user_id, name: "Anita", role: "owner" }],
      "/v1/invitations": created,
    });

    await screen.findByText("Anita");
    fireEvent.change(screen.getByRole("textbox", { name: "Email address to invite" }), {
      target: { value: "priya@clinic.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Create invite link/ }));

    // The confirmation appears…
    await screen.findByText(/Invitation sent to/);
    // …and no element renders a link or a token. Asserting the absence of the testid AND
    // of the token substring, because a screen that stopped using the testid while still
    // interpolating the secret somewhere would pass a check for either one alone.
    expect(screen.queryByTestId("invite-link")).toBeNull();
    expect(container.textContent).not.toContain(INVITE_PATH);
    expect(container.textContent).not.toContain("tok_");
  });
});
