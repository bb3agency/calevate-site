/**
 * Client-realm actions that ask for a code typed for them (D-730): exporting calls or
 * leads, storing or replacing an integration credential, adding an outbound endpoint and
 * renting a phone number, among others.
 *
 * The action string is `<verb>:<org slug>` (`apps/api/core/stepup.client_confirmation`),
 * bound to the account the request is made in. The first attempt carries it as
 * `X-Confirm-Action`; if the API asks for a code, the client realm's prompt
 * (`components/authn/stepUpPrompt.tsx`, mounted by `lib/api/session.tsx`) asks for one
 * FOR THIS ACTION and the request is sent once more. That is safe because the gate refuses
 * before the route does anything.
 */

import { needsReauthentication } from "@/lib/authn/problems";
import { withActionCode } from "@/lib/authn/stepUpPrompt";

import type { Session } from "./client";

export function accountAction(session: Session, verb: string): string {
  return `${verb}:${session.orgSlug}`;
}

export function withAccountCode<T>(
  action: string,
  reason: string,
  send: () => Promise<T>,
): Promise<T> {
  return withActionCode(action, reason, send, needsReauthentication);
}
