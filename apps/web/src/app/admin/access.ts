"use client";

/**
 * May THIS operator use the control — or reach the screen — in front of them? The admin
 * realm's half of the answer `useWriteAccess` gives on client screens.
 *
 * ## Where the answer comes from
 *
 * `GET /v1/admin/me` (apps/api/admin/routes.py): the admin realm's own identity read,
 * answered from `admin_users` and the role table with NO tenant involved. It replaces
 * three separate workarounds that existed only because the endpoint did not:
 *
 * 1. this hook reading `/v1/me` through an IMPERSONATING session — the only way an admin
 *    token could reach that route, since `current_any` consults the admin realm only when
 *    `X-Impersonate-Org` is present (core/auth.py). It needed a tenant SLUG, so a
 *    cross-tenant screen could not ask at all, and it spent `admin:impersonate` entering
 *    a client nobody had opened just to find out who we are;
 * 2. `/admin` deriving "may I create a client" from a 403 on the directory read;
 * 3. `/admin/ops` deriving "may I move a switch" from a 403 on the platform read.
 *
 * (2) and (3) were sound — read and write carried the identical permission on both — but
 * they answer only for the one permission that screen happens to read, they say nothing
 * until a request has failed, and they cannot answer for a screen the session has not
 * opened. The nav has to ask about screens nobody has opened, which is what made one
 * mechanism necessary rather than merely tidier.
 *
 * ## Why the client-realm hook cannot be reused
 *
 * `useWriteAccess` (lib/api/hooks.ts) refuses EVERY permission to an impersonating
 * principal, because on a `/c/[slug]` screen impersonation is the whole question: the
 * request would be sent with the impersonating session and `requires()` refuses every
 * member of `MUTATING_PERMISSIONS` for it (D-22). On these screens the opposite is true.
 * A tenant screen reads through impersonation and WRITES through the admin surface with
 * the tenant in the path (`admin.ts` builds both sessions on purpose), so the write is
 * never impersonating and `impersonating` says nothing about whether it will be allowed.
 * Reusing the client hook here would disable every control on every admin screen with a
 * reason that is not true — which is also why `/v1/admin/me` carries no `impersonating`
 * field to be misread.
 *
 * ## THREE states, and why callers fail in opposite directions
 *
 * `allowed` is "the server says you may", `refused` is "the server says you may not",
 * and neither is "we do not know yet, or could not find out". Two booleans rather than
 * one, because the two kinds of caller must treat the unknown differently:
 *
 * - a CONTROL fails closed (`allowed`): offering a button whose only outcome is a 403 is
 *   the failure this hook exists to remove;
 * - NAVIGATION fails open (`refused`): the API is the enforcement, every gated screen
 *   explains its own refusal, and an identity read that is merely slow or down must not
 *   be able to lock an operator out of the console mid-incident. `/v1/ops` is on
 *   `ALWAYS_ALLOWED_PREFIXES` (BACKEND-PATTERNS §6) for that exact reason, and a nav that
 *   went dark on an unknown would undo it in the browser.
 *
 * ## It is a PREVIEW, never the enforcement
 *
 * Same doctrine as the client-realm hook and the launch-check blockers: the endpoints
 * still refuse, and every screen keeps its `ProblemNotice` as the backstop. What this
 * buys is that an operator who cannot do a thing is told so beside the control instead of
 * being handed a 403 that reads like an outage.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { adminSession } from "@/lib/api/admin";
import { apiRequest } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

/** The admin realm's identity document — `MeOut` minus everything tenant-shaped. */
export type AdminMe = components["schemas"]["AdminMeOut"];

export const ADMIN_ME_PATH = "/v1/admin/me";

/**
 * Who the console is, as the server sees it.
 *
 * One query key for the whole realm — no slug, nothing tenant-derived — so the shell,
 * the directory and every tenant screen share one request and one answer instead of
 * asking again per tenant.
 */
export function useAdminMe(): UseQueryResult<AdminMe> {
  return useQuery({
    queryKey: ["admin", "me"],
    queryFn: () => apiRequest<AdminMe>(adminSession(), ADMIN_ME_PATH),
    // A role does not change inside a session; the client-realm `useMe` uses the same
    // five minutes for the same reason.
    staleTime: 5 * 60_000,
  });
}

/** What a gated control or nav entry needs: whether to offer itself, and what to say. */
export interface AdminAccess {
  /** The server ANSWERED and this session holds the permission. */
  allowed: boolean;
  /**
   * The server ANSWERED and this session does not hold it. False while the answer is
   * missing — including when the identity read failed, because "we could not ask" is
   * not a refusal and must never be rendered as one.
   */
  refused: boolean;
  /**
   * Why not, rendered BESIDE the disabled control. Null while we do not yet know — a
   * control must never flash an explanation it is about to withdraw.
   */
  reason: string | null;
}

/**
 * The verdict, as a pure function of an identity query.
 *
 * Separate from the hook so the sidebar can ask about every nav entry from ONE
 * `useAdminMe()` call — a hook per item would break the rules of hooks the moment the
 * nav list changed length.
 */
export function adminAccess(
  me: UseQueryResult<AdminMe>,
  permission: string,
  action: string,
): AdminAccess {
  if (me.error) {
    // A permanently dead control with no explanation is the worst of both worlds: say we
    // could not find out, rather than implying a refusal nobody made.
    return {
      allowed: false,
      refused: false,
      reason: `We could not check whether you may ${action}. Reload the page to try again.`,
    };
  }
  if (!me.data) return { allowed: false, refused: false, reason: null };
  if (!me.data.permissions.includes(permission)) {
    return {
      allowed: false,
      refused: true,
      reason: `Your admin account does not have the ${permission} permission, so you cannot ${action}. Ask a superadmin.`,
    };
  }
  return { allowed: true, refused: false, reason: null };
}

export function useAdminAccess(permission: string, action: string): AdminAccess {
  return adminAccess(useAdminMe(), permission, action);
}
