/**
 * The CLIENT realm's session — `app.calevate.tech`, a tenant's own staff (D-174).
 *
 * The twin of `adminAuthn.ts`, and duplicated on purpose. See that file and `realm.ts`
 * for the argument; the short version is CLAUDE.md's "never share session logic" plus
 * AUTH-MIGRATION §3's reason for it, and the duplication here is two module-scoped
 * instances rather than two copies of the machinery.
 *
 * Invitation redemption lives here for the mirror of the reason bootstrap lives there: it
 * is declared only on the client realm (`invite_router` in `apps/api/authn/routes.py`),
 * and there is no admin-realm spelling of it.
 */

import { clientConsoleUrl } from "@/lib/consoleOrigin";

import { nextFromLocation } from "./nextPath";
import { createRealmAuthn } from "./realm";
import { authnRequest } from "./transport";

/** The client realm's session. One instance, module-scoped, never re-created. */
export const clientAuthn = createRealmAuthn("client");

export const CLIENT_SIGN_IN_PATH = "/auth/sign-in";
export const CLIENT_ACCOUNT_PATH = "/auth/account";
/**
 * Where a signed-in client user actually WORKS — the destination of a successful sign-in.
 *
 * Not a console URL, because there isn't one until the slug is known: `/c` is the junction
 * that reads `/v1/me` and forwards. Distinct from `CLIENT_ACCOUNT_PATH` for the reason
 * D-441 separated the admin pair — that page says "you are signed in" and offers two
 * sign-out buttons, so landing there after signing in is a dead end with a link on it.
 */
export const CLIENT_CONSOLE_PATH = "/c";
export const CLIENT_FORGOT_PATH = "/auth/forgot-password";
export const CLIENT_RESET_PATH = "/auth/reset-password";
export const CLIENT_ACCEPT_INVITE_PATH = "/auth/accept-invitation";

/** What redeeming an invitation gets you — all three fields the server's own. */
export interface AcceptedInvitation {
  tenant_id: string;
  slug: string;
  role: string;
}

/**
 * Redeem an invitation: create the account, set its password, join the workspace.
 *
 * One call where the Clerk-era flow took two, because there is no vendor to have made the
 * account first. **The address comes from the INVITATION and never from this request** —
 * which is why there is no email field here to get wrong, and why the old
 * `invitation_wrong_recipient` refusal cannot arise on this path at all.
 *
 * Not on `clientAuthn` itself because its path is outside the realm prefix this factory
 * builds (`/v1/auth/client/invitations/accept` is mounted by a separate router), and
 * routing it through `clientAuthn.request` would mean inventing a path shape that does not
 * exist. The response sets the client-realm session cookie, so the realm cache is dropped
 * afterwards for the same reason `signIn` drops it.
 */
export async function acceptInvitation(input: {
  token: string;
  password: string;
  name?: string;
}): Promise<AcceptedInvitation> {
  const accepted = await authnRequest<AcceptedInvitation>("/v1/auth/client/invitations/accept", {
    method: "POST",
    body: input,
  });
  clientAuthn.reset();
  return accepted;
}

/**
 * Where a successful sign-in sends a client: the console page in `?next=` when it is a
 * path inside `/c`, otherwise `/c`, which decides where a signed-in person belongs (their
 * workspace, or setup when they have none). The sign-in form and `ClientGuestOnly` both
 * call this, so the two navigations that fire together after a sign-in agree.
 */
export function clientSignedInDestination(): string {
  return clientConsoleUrl(nextFromLocation(CLIENT_CONSOLE_PATH) ?? CLIENT_CONSOLE_PATH);
}

// ─────────────────────── self-serve account and Google sign-in (D-703) ───────────────

/** Which doors this deployment has open, so a page renders only buttons that work. */
export interface SignInOptions {
  google: boolean;
  self_serve_signup: boolean;
}

export function readSignInOptions(): Promise<SignInOptions> {
  return authnRequest<SignInOptions>("/v1/auth/client/sign-in-options");
}

/**
 * Email a sign-up code. The server answers the same way for an address that already has an
 * account (it mails that owner instead), so the page always moves on to "enter the code".
 */
export async function startEmailSignup(email: string): Promise<void> {
  await authnRequest<void>("/v1/auth/client/signup/start", { method: "POST", body: { email } });
}

/** Spend the code and choose a password; the response sets the session cookie. */
export async function completeEmailSignup(input: {
  email: string;
  code: string;
  password: string;
  name?: string;
}): Promise<void> {
  await authnRequest<{ subject_id: string }>("/v1/auth/client/signup/complete", {
    method: "POST",
    body: input,
  });
  clientAuthn.reset();
}

/** Where Google sends the person back (`google_signin_redirect_uri` points here). */
export const GOOGLE_CALLBACK_PATH = "/auth/google/callback";

/**
 * Held for the Google round trip only. The invitation token stays in this tab and is sent
 * again on completion, never put in the URL Google sees.
 */
const GOOGLE_INVITE_KEY = "calevate.google-invite";

/**
 * Begin "Continue with Google": the API sets a browser-binding cookie and returns Google's
 * consent URL, and this tab goes there.
 */
export async function startGoogleSignIn(input: {
  next?: string | null;
  invitationToken?: string | null;
}): Promise<void> {
  const begun = await authnRequest<{ authorize_url: string }>("/v1/auth/client/google/start", {
    method: "POST",
    body: { next: input.next ?? null },
  });
  try {
    if (input.invitationToken) sessionStorage.setItem(GOOGLE_INVITE_KEY, input.invitationToken);
    else sessionStorage.removeItem(GOOGLE_INVITE_KEY);
  } catch {
    // Storage blocked (private mode): the sign-in still works; the invitation is then
    // accepted from its own link afterwards.
  }
  window.location.assign(begun.authorize_url);
}

export interface GoogleSignedIn {
  next: string | null;
  account_created: boolean;
  joined_slug: string | null;
  invitation_mismatch: boolean;
}

/** Finish the Google sign-in from the callback page; the response sets the session cookie. */
export async function completeGoogleSignIn(input: {
  code: string;
  state: string;
}): Promise<GoogleSignedIn> {
  let invitationToken: string | null = null;
  try {
    invitationToken = sessionStorage.getItem(GOOGLE_INVITE_KEY);
    sessionStorage.removeItem(GOOGLE_INVITE_KEY);
  } catch {
    invitationToken = null;
  }
  const done = await authnRequest<GoogleSignedIn>("/v1/auth/client/google/complete", {
    method: "POST",
    body: { ...input, invitation_token: invitationToken },
  });
  clientAuthn.reset();
  return done;
}
