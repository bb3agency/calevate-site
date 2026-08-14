"use client";

/**
 * The team surface (ROADMAP M3, "client staff roles").
 *
 * Three API decisions this module keeps intact rather than smoothing away, because
 * each of them is a rule the screen must not be able to break:
 *
 * - **A role change carries the role the screen was SHOWING.** `expected_role` is a
 *   compare-and-swap (BACKEND-PATTERNS §5): if another owner changed that person in the
 *   meantime the API answers 409 rather than applying a click made against a stale
 *   picture. So the mutation takes the value the row rendered, never a value re-read
 *   from a cache at submit time.
 * - **Addresses come back MASKED and there is no unmasked variant to ask for.**
 *   `email` is in the API's `RAW_PII_FIELDS`; `GET /v1/members` omits it entirely and
 *   the invitation list carries `email_masked`. Nothing here reconstructs one.
 * - **The invitation token is returned exactly once.** It is never stored (only its
 *   SHA-256 is) and there is no endpoint that can show it again, so the create response
 *   is held in component state and deliberately NOT written into the query cache — a
 *   cached credential outlives the moment it was needed.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { clientRealmSession } from "@/lib/auth/clientRealm";

import { ApiProblem, apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Member = Schemas["MemberOut"];
export type PendingInvitation = Schemas["InvitationOut"];
export type CreatedInvitation = Schemas["InvitationCreatedOut"];
export type MemberRemoved = Schemas["MemberRemovedOut"];
export type MemberRole = Schemas["MemberRoleIn"]["role"];
export type AcceptedInvitation = Schemas["AcceptInviteOut"];

export const teamKeys = {
  members: (org: string) => ["members", org] as const,
  invitations: (org: string) => ["invitations", org] as const,
};

export function useMembers(session: Session): UseQueryResult<Member[]> {
  return useQuery({
    queryKey: teamKeys.members(session.orgSlug),
    queryFn: () => apiRequest<Member[]>(session, "/v1/members"),
    // A team changes when somebody on this screen changes it; the mutations below
    // invalidate the key when they do.
    staleTime: 60_000,
  });
}

export function usePendingInvitations(session: Session): UseQueryResult<PendingInvitation[]> {
  return useQuery({
    queryKey: teamKeys.invitations(session.orgSlug),
    queryFn: () => apiRequest<PendingInvitation[]>(session, "/v1/invitations"),
    staleTime: 60_000,
  });
}

/** Both lists move together: accepting, revoking and removing all touch each other. */
function invalidateTeam(client: ReturnType<typeof useQueryClient>, org: string) {
  void client.invalidateQueries({ queryKey: teamKeys.members(org) });
  void client.invalidateQueries({ queryKey: teamKeys.invitations(org) });
}

export function useSetMemberRole(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      userId,
      role,
      expectedRole,
    }: {
      userId: string;
      role: MemberRole;
      /** What the row was showing when the button was pressed — the CAS guard. */
      expectedRole: MemberRole;
    }) =>
      apiRequest<Member>(session, `/v1/members/${userId}`, {
        method: "PATCH",
        body: { role, expected_role: expectedRole },
      }),
    onSuccess: () => invalidateTeam(client, session.orgSlug),
  });
}

export function useRemoveMember(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      apiRequest<MemberRemoved>(session, `/v1/members/${userId}`, { method: "DELETE" }),
    onSuccess: () => invalidateTeam(client, session.orgSlug),
  });
}

export function useInviteMember(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ email, role }: { email: string; role: MemberRole }) =>
      apiRequest<CreatedInvitation>(session, "/v1/invitations", {
        method: "POST",
        body: { email, role },
      }),
    onSuccess: () => invalidateTeam(client, session.orgSlug),
  });
}

export function useRevokeInvitation(session: Session) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (invitationId: string) =>
      apiRequest<PendingInvitation>(session, `/v1/invitations/${invitationId}`, {
        method: "DELETE",
      }),
    onSuccess: () => invalidateTeam(client, session.orgSlug),
  });
}

/**
 * The INVITEE's half of the flow — the only call in this module made by somebody who is
 * not a member of the account yet.
 *
 * `POST /v1/invitations/accept` hangs off `current_identity` (core/auth.py), not
 * `current_principal`: the caller is a Clerk-verified user with no `memberships` row,
 * and creating that row is what the call does. So it carries a client-realm token and
 * an EMPTY org slug — `clientRealmSession("")`, the same shape and the same reason as
 * `signup.ts::signupSession()`, which is the other pre-membership route. Naming a slug
 * here would be inventing a tenant the caller demonstrably is not in; the token names
 * its own tenant through the invitation row.
 *
 * The session is built inside the hook rather than passed in, because there is no
 * `/c/<slug>` layout above this caller to hand them one — `/invite` is outside both
 * shells, which is the whole point of the route.
 */
export function useAcceptInvitation() {
  return useMutation({
    mutationFn: (token: string) =>
      apiRequest<AcceptedInvitation>(clientRealmSession(""), "/v1/invitations/accept", {
        method: "POST",
        body: { token },
      }),
    // No cache invalidation, deliberately: nothing this browser has queried is about the
    // tenant the caller just joined. The console loads its own data behind `/c/<slug>`,
    // with a session that did not exist when this call was made.
  });
}

/**
 * The two refusals `/v1/invitations/accept` makes ON PURPOSE, named so the screen can
 * answer each with its own sentence instead of one red box for everything.
 *
 * Modelled on `signup.ts::isSignupClosed`/`isSignupDeferred` — same problem (a business
 * rule arriving as a refusal), same solution, one spelling.
 *
 * Everything NOT matched by these two is an ordinary failure: a 401, a 500, a dropped
 * connection. BUILD-LOG §52 cuts hardest right here — rendering "this invitation is
 * invalid" for a request that never got an answer tells someone holding a working,
 * single-use credential to throw it away, and they only get one.
 */
export function isInvitationUnusable(error: unknown): error is ApiProblem {
  // The API answers ONE code for expired and already-used together, and says why: an
  // attacker guessing tokens must not learn which of the two they hit. So the screen
  // cannot split them either, and the copy above this predicate's call site covers both
  // rather than guessing at one.
  return error instanceof ApiProblem && error.code === "invitation_invalid";
}

/** The invitation is real and unused, but it was sent to a different address. */
export function isInvitationForSomeoneElse(error: unknown): error is ApiProblem {
  return error instanceof ApiProblem && error.code === "invitation_wrong_recipient";
}

/**
 * What the two roles actually mean, in the words a business owner uses.
 *
 * Kept beside the control that sets them rather than in a tooltip: "owner" and "staff"
 * are OUR words, and someone deciding whether a receptionist should be one is deciding
 * about billing access and full phone numbers without being told so anywhere else.
 * The list mirrors `ROLE_PERMISSIONS` in `apps/api/core/rbac.py` — if that table gains
 * a permission that matters to a client, this copy is the other half of the change.
 */
export const ROLE_COPY: Record<string, { label: string; can: string }> = {
  owner: {
    label: "Owner",
    can: "Everything, including billing, full phone numbers in exports, launching campaigns, and managing this team.",
  },
  staff: {
    label: "Staff",
    can: "Day-to-day work: leads, calls and agents. No billing, no team changes, and phone numbers stay masked.",
  },
};
