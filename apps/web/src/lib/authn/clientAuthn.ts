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
 * D-432 separated the admin pair — that page says "you are signed in" and offers two
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
