import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, type RenderResult } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import InvitePage from "@/app/invite/page";

import { problem, stubApi, type ApiCall, type Routes } from "./harness";

/**
 * `/invite?token=…` — the screen a stranger reaches holding a live credential.
 *
 * Two things make this the most consequential small page in the app.
 *
 * **It is the only surface where a wrong sentence costs a person something they cannot
 * get back.** The token works once, expires in 72 hours, and the API returns it exactly
 * once at creation — there is no endpoint that can show it again. So "this invitation is
 * invalid" printed over a 503 does not merely mislead: it tells someone holding a
 * WORKING key to discard it and go ask an owner for another. BUILD-LOG §52's rule
 * (loading is a skeleton, failure is a refusal, and neither is a state) is asserted here
 * as a NEGATIVE — the invalid panel must be unreachable except from the one code that
 * means it.
 *
 * **Every state below is one a real person lands in.** The link that a chat app cut in
 * half, the colleague who signed in with their personal Gmail rather than the work
 * address the owner typed, the second click on a link already used. Each has its own
 * remedy and each is asserted with the remedy, because a refusal without one is how a
 * new member ends up phoning their account manager.
 *
 * ## What this file does NOT cover, stated rather than implied
 *
 * The suite runs in `dev` auth mode, like the rest of the frontend, so
 * `ClientRealmSignedIn` renders its children and `ClientRealmSignedOut` renders nothing —
 * the local build's identity IS the dev token, which is exactly what the API says when it
 * accepts `dev:client:<id>`. **The signed-out panel is therefore unreachable here and is
 * not asserted.** It cannot be reached the other way either: in `clerk` mode with no key
 * the provider replaces the whole surface with `ClerkNotConfigured`, and with a key it
 * would fetch clerk-js from a CDN. A route file may not export anything but page fields,
 * so the component cannot be rendered directly either. What IS covered of that branch is
 * the gate itself (`clientRealm.tsx`, in `auth.test.tsx`); its copy and its two
 * `redirect_url` links are reviewed, not tested, and this note is here so the next reader
 * does not mistake a green file for a covered one.
 */

/**
 * The link's query string, settable per test.
 *
 * `tests/setup.ts` stubs `next/navigation` with an EMPTY `URLSearchParams` for the whole
 * suite, which is right for every screen whose params are incidental. This is the one
 * page whose entire behaviour hangs off a parameter, so the stub is replaced here with a
 * mutable one. Everything below the framework boundary — the provider, the session, the
 * real `apiRequest`, problem+json parsing — stays real, per the repo's fixtures-over-
 * mocks rule.
 */
let search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => search,
  usePathname: () => "/invite",
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
}));

/** A token of the shape the API mints: `secrets.token_urlsafe`, well over the 20 the
 * request model requires, so nothing here is testing a length rule by accident. */
const TOKEN = "Zx7Qw1r8sTfL2mNp9vBkYd3HgJ4cWa6E";

const ACCEPTED = {
  tenant_id: "0192f0aa-1111-7000-8000-000000000001",
  slug: "sunrise-clinic",
  role: "staff",
};

interface InviteRender extends RenderResult {
  calls: ApiCall[];
}

async function renderInvite(query: string, routes: Routes = {}): Promise<InviteRender> {
  search = new URLSearchParams(query);
  const calls = stubApi(routes);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  let result!: RenderResult;
  // Async `act` for the same reason `renderClientPage` needs one: the page suspends on
  // its `useSearchParams` boundary and React resumes it outside the synchronous render.
  await act(async () => {
    result = render(
      <QueryClientProvider client={client}>
        <InvitePage />
      </QueryClientProvider>,
    );
  });
  return Object.assign(result, { calls });
}

/** Press the one control this page has, and let the mutation settle. */
async function accept(): Promise<void> {
  const button = screen.getByRole("button", { name: /Accept invitation|Try again/ });
  await act(async () => {
    fireEvent.click(button);
  });
}

/** The sentence that must never appear over anything but `invitation_invalid`. */
const INVALID_HEADLINE = "This invitation cannot be used";

beforeEach(() => {
  search = new URLSearchParams();
});

describe("the route exists at all", () => {
  it("renders the accept screen for a link carrying a token, and asks the API nothing yet", async () => {
    /**
     * THE DEFECT, at its simplest. `settings/team/page.tsx` mints
     * `${origin}/invite?token=…` and tells an owner to send it; `app/invite/` did not
     * exist, `next.config.ts` has no rewrite, and there is no middleware — so the
     * colleague met a 404 while holding a working single-use credential.
     *
     * The second assertion is the other half of the design: nothing is spent on arrival.
     * A page that POSTed on mount would burn the token on a page load — including
     * StrictMode's second one, whose reward is telling an invitee their brand-new
     * invitation has already been used.
     */
    const { container, calls } = await renderInvite(`token=${TOKEN}`);

    expect(container.textContent).toContain("Accept your invitation");
    screen.getByRole("button", { name: "Accept invitation" });
    expect(calls).toEqual([]);
  });
});

describe("a link with nothing to redeem", () => {
  it("blames the link, not the invitation, and never calls the API", async () => {
    // Messaging apps break long links across two lines and only the first half becomes
    // clickable, so "?token=" going missing is the ordinary failure here — and it is
    // evidence about the LINK. Calling it an invalid invitation would send someone to
    // ask for a replacement for something that is probably still sitting in their inbox.
    const { container, calls } = await renderInvite("");

    expect(container.textContent).toContain("This link is missing its invitation code");
    expect(container.textContent).not.toContain(INVALID_HEADLINE);
    // Actionable, and by them: open the original link, or ask for a fresh one.
    expect(container.textContent).toContain("Settings → Team");
    // No request may be made without a token: a POST with an empty string earns a 422
    // whose field message would then be the first thing a stranger reads.
    expect(calls).toEqual([]);
  });

  it("treats a blank token the same as an absent one", async () => {
    const { container, calls } = await renderInvite("token=%20%20");
    expect(container.textContent).toContain("This link is missing its invitation code");
    expect(calls).toEqual([]);
  });
});

describe("accepting", () => {
  it("sends the raw token with a client-realm credential and no org header", async () => {
    /**
     * `POST /v1/invitations/accept` hangs off `current_identity`, not
     * `current_principal`: the caller has no membership yet — creating one is the point.
     * So the request must carry a client-realm token and an EMPTY `X-Org-Slug`. Naming
     * a slug would be inventing a tenant this caller demonstrably is not in, and an
     * admin credential would be refused outright (`verify_token(token, "client")`).
     */
    const { calls } = await renderInvite(`token=${TOKEN}`, {
      "/v1/invitations/accept": ACCEPTED,
    });
    await accept();

    expect(calls).toHaveLength(1);
    expect(calls[0].path).toBe("/v1/invitations/accept");
    expect(calls[0].method).toBe("POST");
    expect(JSON.parse(calls[0].body ?? "{}")).toEqual({ token: TOKEN });
    expect(calls[0].headers.Authorization).toMatch(/^Bearer dev:client:/);
    expect(calls[0].headers["X-Org-Slug"]).toBe("");
  });

  it("reports only what the server returned, and points at that workspace", async () => {
    // Every word on the success panel comes from `AcceptInviteOut`. There is no
    // optimistic branch, so no path exists on which this screen welcomes somebody into
    // an account the API never put them in.
    const { container } = await renderInvite(`token=${TOKEN}`, {
      "/v1/invitations/accept": ACCEPTED,
    });
    await accept();

    expect(await screen.findByText("You are in")).toBeTruthy();
    expect(container.textContent).toContain("You joined sunrise-clinic as Staff");
    // The role's meaning, from the table the team screen uses — a new member should not
    // have to discover that billing is closed to them by clicking it.
    expect(container.textContent).toContain("phone numbers stay masked");
    expect(screen.getByRole("link", { name: /Open the dashboard/ }).getAttribute("href")).toBe(
      "/c/sunrise-clinic",
    );
  });

  it("prints a role it has no copy for rather than hiding it", async () => {
    // `role` is a bare `string` on the wire. `ROLE_COPY` is read through `lookup()`, so
    // a role the table does not own yields `undefined` rather than `Object` — and the
    // fail direction here is VISIBLE, because an unnameable role is the one worth
    // reading. Written as `constructor` deliberately: that is the exact value that used
    // to resolve to the `Object` function on a plain index (src/lib/lookup.ts).
    const { container } = await renderInvite(`token=${TOKEN}`, {
      "/v1/invitations/accept": { ...ACCEPTED, role: "constructor" },
    });
    await accept();

    expect(await screen.findByText("You are in")).toBeTruthy();
    expect(container.textContent).toContain("You joined sunrise-clinic as constructor");
    expect(container.textContent).not.toContain("native code");
  });
});

describe("the two refusals the API makes on purpose", () => {
  it("says a used-or-expired invitation is exactly that, and offers the fresh link", async () => {
    // The API answers ONE code for both states and documents why — an attacker guessing
    // tokens must learn nothing from the difference — so the copy covers both rather
    // than picking the likelier one. The server's own remediation leads.
    const { container } = await renderInvite(`token=${TOKEN}`, {
      "/v1/invitations/accept": problem(422, {
        type: "urn:calevate:business_rule/invitation_invalid",
        kind: "business_rule",
        title: "Invitation is not usable",
        detail: "This invitation has already been used or has expired.",
        remediation: "Ask your account manager for a fresh invite.",
      }),
    });
    await accept();

    expect(await screen.findByText(INVALID_HEADLINE)).toBeTruthy();
    expect(container.textContent).toContain("Ask your account manager for a fresh invite.");
    // No retry: this one cannot succeed on a second attempt, and a button that can only
    // fail is a trap rather than an affordance.
    expect(screen.queryByRole("button", { name: /Try again|Accept invitation/ })).toBeNull();
  });

  it("tells the wrong-address invitee it is their ACCOUNT that is wrong, not the link", async () => {
    /**
     * The honest failure this whole binding exists to produce well: a colleague signs in
     * with their personal address rather than the one an owner typed. The link is fine
     * and unspent — saying "invalid" here would make them ask for a replacement that
     * fails identically, which is why the API gives this its own code and its own
     * sentence, and why the screen must not flatten the two.
     */
    const { container } = await renderInvite(`token=${TOKEN}`, {
      "/v1/invitations/accept": problem(403, {
        type: "urn:calevate:permission/invitation_wrong_recipient",
        kind: "permission",
        title: "This invitation is for a different address",
        detail: "This invitation was sent to someone else's email address.",
        remediation:
          "Sign in with the address the invitation was sent to, or ask an owner of the account to invite the address you use.",
      }),
    });
    await accept();

    expect(await screen.findByText("This invitation is for a different address")).toBeTruthy();
    expect(container.textContent).toContain("has not been used up");
    expect(container.textContent).toContain("Sign in with the address the invitation was sent to");
    // The remedy is a place to go, not advice: `/sign-in` is where a signed-in visitor
    // gets the sign-out control.
    expect(screen.getByRole("link", { name: "Switch account" }).getAttribute("href")).toBe(
      "/sign-in",
    );
    // And it is NOT the invalid panel — the distinction is the entire point.
    expect(container.textContent).not.toContain(INVALID_HEADLINE);
  });
});

describe("§52: a request that failed is not a fact about the invitation", () => {
  it("refuses without ever calling a working invitation invalid", async () => {
    /**
     * THE assertion this file exists for. A 503 from the API — an outage, a restart, a
     * deploy — leaves the token untouched. Rendering "this invitation cannot be used"
     * over it tells a person holding the one copy of a single-use credential to throw it
     * away. The refusal must therefore say what happened (the request), keep the control
     * that can still work, and claim nothing about the token in either direction.
     */
    const { container } = await renderInvite(`token=${TOKEN}`, {
      "/v1/invitations/accept": problem(503, {
        type: "urn:calevate:internal/upstream_unavailable",
        kind: "internal",
        title: "Upstream unavailable",
        detail: "We could not complete that just now.",
        retryable: true,
      }),
    });
    await accept();

    await screen.findByRole("alert");
    expect(container.textContent).toContain("We could not complete that just now.");
    // Not the invalid panel, and not the wrong-address one either.
    expect(container.textContent).not.toContain(INVALID_HEADLINE);
    expect(container.textContent).not.toContain("This invitation is for a different address");
    // The way forward is still on screen.
    screen.getByRole("button", { name: "Try again" });
    expect(container.textContent).toContain("Nothing was confirmed");
  });

  it("does the same for a 401 the invitee cannot interpret", async () => {
    // `current_identity` answers `unauthorized` when the Clerk user has not been
    // mirrored into `users` yet. That is a fact about the ACCOUNT, and reading it as a
    // dead invitation is the same defect wearing a different status code.
    const { container } = await renderInvite(`token=${TOKEN}`, {
      "/v1/invitations/accept": problem(401, {
        type: "urn:calevate:auth/unauthorized",
        kind: "auth",
        title: "Unauthorized",
        detail: "This account is not provisioned.",
      }),
    });
    await accept();

    await screen.findByRole("alert");
    expect(container.textContent).toContain("This account is not provisioned.");
    expect(container.textContent).not.toContain(INVALID_HEADLINE);
  });

  it("shows no verdict at all while the request is still in flight", async () => {
    // The third state §52 names, and the one a slow connection makes ordinary. A button
    // mid-press must read as neither outcome — not "you are in", not a refusal.
    const { container } = await renderInvite(`token=${TOKEN}`, {
      "/v1/invitations/accept": ACCEPTED,
    });

    // A request that never answers, which is what "in flight" means from the screen's
    // side. Nothing releases it: the assertion is about the state the screen holds while
    // the server is silent, and releasing it would only be testing the next state again.
    vi.stubGlobal("fetch", () => new Promise<Response>(() => {}));

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));
    });

    expect(container.textContent).toContain("Accepting…");
    expect(container.textContent).not.toContain(INVALID_HEADLINE);
    expect(container.textContent).not.toContain("You are in");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
