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

import { CLIENT_ACCEPT_INVITE_PATH } from "@/lib/authn/clientAuthn";
import { LINK_TOKEN_PARAM } from "@/lib/authn/useLinkToken";

import { apiRequest, type Session } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Member = Schemas["MemberOut"];
export type PendingInvitation = Schemas["InvitationOut"];
export type CreatedInvitation = Schemas["InvitationCreatedOut"];
export type MemberRemoved = Schemas["MemberRemovedOut"];
export type MemberRole = Schemas["MemberRoleIn"]["role"];

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

/**
 * Where an invite link points, and the parameter its token rides in — ONE definition.
 *
 * `settings/team/page.tsx` built `${origin}/invite?token=…` inline once, and two
 * spellings of one URL is how `/invite` came to be a 404 for eight days while the team
 * screen handed the link to owners. This is where they were promised to land.
 *
 * IT NOW POINTS AT `/auth/accept-invitation` (D-177). There were two invite pages —
 * the Clerk-era `/invite`, which asked an invitee to sign up with a vendor first, and
 * D-174's `/auth/accept-invitation`, which takes a password and creates the account in
 * the same call. Two ways to redeem one invitation is a defect by CLAUDE.md even while
 * both work, so newly minted links name the surviving page directly and `/invite`
 * survives only as a redirect for the links already sitting in people's inboxes.
 *
 * Both constants are RE-EXPORTS rather than new values: `CLIENT_ACCEPT_INVITE_PATH` and
 * `LINK_TOKEN_PARAM` are owned by `lib/authn/`, which owns the page. Restating them here
 * is how the two spellings would come back.
 *
 * `origin` is a parameter rather than read from `window` here so the function is usable
 * during server rendering, where the team screen falls back to a relative link.
 */
export const INVITE_PATH = CLIENT_ACCEPT_INVITE_PATH;
export const INVITE_TOKEN_PARAM = LINK_TOKEN_PARAM;

export function inviteLink(token: string, origin?: string): string {
  const path = `${INVITE_PATH}?${INVITE_TOKEN_PARAM}=${encodeURIComponent(token)}`;
  return origin ? `${origin}${path}` : path;
}
