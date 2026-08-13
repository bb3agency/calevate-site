"use client";

/**
 * May THIS operator use the control in front of them? — the admin realm's half of the
 * answer `useWriteAccess` gives on client screens.
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
 * reason that is not true.
 *
 * ## Where the permission set comes from, and why it is read the awkward way
 *
 * `/v1/me` is the server's own answer about role and permissions, and it is the only one
 * — there is no admin-realm identity endpoint. `current_any` only consults the admin
 * realm when `X-Impersonate-Org` is present (`core/auth.py`), so a bare `adminSession()`
 * call to `/v1/me` is verified as a CLIENT token and refused. The impersonating session
 * is therefore how an admin console asks who it is, and what comes back is the ADMIN
 * role's full permission set (`ROLE_PERMISSIONS[principal.role]`, tenancy/routes.py) with
 * `realm: "admin"` — exactly the set the admin-surface write will be checked against.
 *
 * That the read costs an impersonation is not a workaround: it is `admin:impersonate`
 * doing its job, the request is a GET of a non-mutating permission, and D-22 requires
 * nothing more of it. It is also why this hook needs the tenant's SLUG rather than only
 * its id, and why it answers "we do not know yet" until the slug has arrived.
 *
 * ## It is a PREVIEW, never the enforcement
 *
 * Same doctrine as the client-realm hook and the launch-check blockers: the endpoints
 * still refuse, and every screen keeps its `ProblemNotice` as the backstop. What this
 * buys is that an operator who cannot do a thing is told so beside the control instead of
 * being handed a 403 that reads like an outage.
 *
 * REPORTED GAP: today both admin roles (`operator`, `superadmin`) hold `admin:tenants`,
 * `billing:read` and `agents:write`, so no live role is refused by this. It bites the
 * moment a narrower admin role exists — which is precisely when nobody will remember to
 * add the gate — and it already turns an unreadable identity into a sentence rather than
 * into a control that fails at the click.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { viewAsSession } from "@/lib/api/admin";
import { apiRequest, type Me } from "@/lib/api/client";

/** Who the console is, as the server sees it — read through the tenant being viewed. */
export function useAdminMe(slug: string): UseQueryResult<Me> {
  return useQuery({
    queryKey: ["admin", "me", slug],
    queryFn: () => apiRequest<Me>(viewAsSession(slug), "/v1/me"),
    enabled: Boolean(slug),
    // A role does not change inside a session; the client-realm `useMe` uses the same
    // five minutes for the same reason.
    staleTime: 5 * 60_000,
  });
}

/** What a gated control needs: whether to enable itself, and what to say when it does not. */
export interface AdminAccess {
  allowed: boolean;
  /**
   * Why not, rendered BESIDE the disabled control. Null while we do not yet know — a
   * control must never flash an explanation it is about to withdraw.
   */
  reason: string | null;
}

export function useAdminAccess(slug: string, permission: string, action: string): AdminAccess {
  const me = useAdminMe(slug);

  if (me.error) {
    // A permanently dead control with no explanation is the worst of both worlds: say we
    // could not find out, rather than implying a refusal nobody made.
    return {
      allowed: false,
      reason: `We could not check whether you may ${action}. Reload the page to try again.`,
    };
  }
  if (!me.data) return { allowed: false, reason: null };
  if (!me.data.permissions.includes(permission)) {
    return {
      allowed: false,
      reason: `Your admin account does not have the ${permission} permission, so you cannot ${action}. Ask a superadmin.`,
    };
  }
  return { allowed: true, reason: null };
}
