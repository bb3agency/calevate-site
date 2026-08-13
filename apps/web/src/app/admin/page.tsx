"use client";

import Link from "next/link";
import { Eye, Plus } from "lucide-react";

import {
  Card,
  EmptyState,
  NOTICE_TONES,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import { useTenants } from "@/lib/api/admin";
import { ApiProblem } from "@/lib/api/client";
import { holdRule } from "@/lib/api/holds";
import { VIEW_AS_ADMIN, VIEW_AS_PARAM } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

/**
 * The client directory — who our clients are, and which of them is in trouble.
 *
 * `/admin/health` answers "which account needs me this week" and this one answers "who
 * are they at all", which is why this screen lists everybody including the healthy and
 * the health board lists nobody who is fine.
 *
 * The honesty rule the design pass had to survive here is the same one the client
 * dashboard states: every number comes from the API or is not shown. The old header read
 * `{tenants.data?.length ?? 0} accounts`, which printed "0 accounts · health at a glance"
 * while the request was in flight AND after it failed — an operator glancing at a
 * console that says they have no clients has been told something false in the calmest
 * possible voice. The count now renders only from a list that arrived, and a failed read
 * renders the refusal instead of an empty table, because an empty table IS the sentence
 * "you have no clients".
 *
 * Hard rule 6: this is a CROSS-TENANT screen and it carries accounts only — a name, a
 * slug, counts, and the gates that hold them. No phone number, no person, no reviewer
 * prose; everything identifying stays behind the permission that opens the account.
 */

/**
 * How a tenant's lifecycle state is painted.
 *
 * `TenantSummary.status` is a bare `string` on the wire (the enum grows server-side), so
 * it is read through `lookup` — a table indexed with a wire string reaches
 * `Object.prototype` and `"constructor"` resolves to the `Object` FUNCTION, which `??`
 * does not treat as missing (src/lib/lookup.ts). Fails VISIBLE: an unknown status keeps
 * its neutral pill and still prints itself, because a state we have no colour for is the
 * one worth reading.
 */
const TENANT_STATUS_TONES: Record<string, string> = {
  active: "border-brand/30 bg-brand-soft text-brand-strong dark:bg-brand-strong/20",
};

/**
 * May this session create a client? — derived from the READ, not from a role list.
 *
 * There is no admin-realm identity endpoint to ask: `/v1/me` resolves an admin principal
 * only when the impersonation header is present (`core/auth.py`), so an admin token asking
 * it is refused as a client token. What makes the answer available anyway is that
 * `GET /v1/admin/tenants` and `POST /v1/admin/tenants` carry the IDENTICAL permission
 * (`admin:tenants`, `admin/routes.py`): a 403 on the list is the server's own answer to
 * the question the button is about to ask, so the refusal can be given before the click
 * rather than as a 403 afterwards that reads like a fault.
 *
 * Anything else that stopped the read disables it too, and says something different —
 * "you may not" and "we could not find out" are different sentences, and only one of them
 * is about the operator. It never returns `allowed: true` without a response in hand,
 * because a directory that could not be read is also a directory whose slug collisions we
 * cannot see.
 *
 * `useAdminAccess` (admin/tenants/access.ts) is the repo's other answer and the better one
 * where it applies: it asks `/v1/me` through an IMPERSONATING session, which is the only
 * way an admin token can reach that endpoint, and gets the admin role's real permission
 * set back. It needs a tenant SLUG to impersonate into, and this screen is the one that
 * has none — it is the cross-tenant directory, and in the case that matters (the 403)
 * there is no list to borrow a slug from. Borrowing some arbitrary client's slug to ask
 * who we are would also put an `admin:impersonate` audit entry against a tenant nobody
 * opened. So this screen takes the same route `opsAccess` (admin/ops/page.tsx) takes,
 * which is sound for the same reason: read and write share one permission.
 *
 * Not shared with `opsAccess` as code: the two differ in the permission, the sentence and
 * the query, and the common part is three lines of `instanceof`. If a third screen needs
 * it, it belongs beside `useAdminAccess` as its permission-shaped sibling.
 *
 * Not exported: a Next.js page module may only export the default and the framework's own
 * named exports, so this is asserted through the DOM.
 */
function createAccess(query: { error: unknown; isLoading: boolean }): {
  allowed: boolean;
  reason: string | null;
} {
  if (query.error instanceof ApiProblem && query.error.status === 403) {
    return {
      allowed: false,
      reason:
        "Your admin account cannot create clients — that needs admin:tenants. It is the " +
        "same permission that lists them, which is why the directory could not be read " +
        "either.",
    };
  }
  if (query.error) {
    return {
      allowed: false,
      reason:
        "Creating a client is disabled because the directory could not be read: we cannot " +
        "tell you whether this business is already on the platform.",
    };
  }
  if (query.isLoading) return { allowed: false, reason: null };
  return { allowed: true, reason: null };
}

export default function AdminClientsPage() {
  const tenants = useTenants();
  const rows = tenants.data;
  const create = createAccess(tenants);

  return (
    <div className="space-y-4 pb-12">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="text-sm text-ink-muted">
          Every client account, with the gates that are holding any of them.
          {/* Only from a list that ARRIVED. A count is the most trusted thing on a
              directory and the cheapest thing to get wrong. */}
          {rows && ` ${formatCount(rows.length)} ${rows.length === 1 ? "account" : "accounts"}.`}
        </p>
        {/* Gated on `admin:tenants` — the permission the route behind it requires — using
            the read's own refusal (see `createAccess`). A dead link rather than a link to
            a form that will refuse the submission: the wasted work is the form, not the
            click. */}
        {create.allowed ? (
          <Link
            href="/admin/new"
            className="inline-flex items-center gap-2 rounded-lg bg-brand-strong px-3 py-2 text-sm font-semibold text-white hover:bg-brand"
          >
            <Plus className="h-4 w-4" />
            New client
          </Link>
        ) : (
          <span
            aria-disabled
            className="inline-flex cursor-not-allowed items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-semibold text-ink-faint"
          >
            <Plus className="h-4 w-4" />
            New client
          </span>
        )}
      </div>

      {/* Beside the dead control, not instead of it: the reason is what turns a greyed-out
          button from a bug into an answer. Renders nothing while we do not yet know. */}
      <RestrictionNote reason={create.reason} />

      {tenants.error && <ProblemNotice error={tenants.error} onRetry={() => void tenants.refetch()} />}

      <Card bodyClassName="p-0">
        {tenants.isLoading ? (
          <div className="p-6">
            <Skeleton rows={5} />
          </div>
        ) : tenants.error ? (
          /* Deliberately NOT the empty state, and deliberately not an empty table either:
             both of those read as "there are no clients", which is a claim about the world
             that a failed read is not evidence for. */
          <div className="p-6 text-sm text-ink-muted">
            The client directory could not be read, so this is not a list of your clients.
          </div>
        ) : !rows?.length ? (
          <EmptyState
            title="No clients yet"
            hint="Create the first one and it appears here with its onboarding gates."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th className="px-6 py-3 font-semibold">Client</th>
                  <th className="px-6 py-3 font-semibold">Status</th>
                  <th className="px-6 py-3 font-semibold">Vertical</th>
                  <th className="px-6 py-3 font-semibold">Live agents</th>
                  <th className="px-6 py-3 font-semibold">Calls 7d</th>
                  <th className="px-6 py-3 font-semibold">Leads</th>
                  <th className="px-6 py-3 font-semibold">Last call</th>
                  <th className="px-6 py-3 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((tenant) => (
                  <tr key={tenant.id} className="align-top hover:bg-black/[0.02] dark:hover:bg-white/[0.03]">
                    <td className="px-6 py-3">
                      <Link
                        href={`/admin/tenants/${tenant.id}`}
                        className="font-semibold text-ink hover:underline"
                      >
                        {tenant.name}
                      </Link>
                      <div className="text-xs text-ink-faint">/c/{tenant.slug}</div>
                    </td>
                    <td className="px-6 py-3">
                      <div className="flex flex-wrap items-center gap-1">
                        <span
                          className={`rounded-full border px-2 py-0.5 text-xs font-medium capitalize ${
                            lookup(TENANT_STATUS_TONES, tenant.status) ?? NOTICE_TONES.neutral
                          }`}
                        >
                          {tenant.status}
                        </span>
                        {/* A capped tenant's outbound is refused pre-dispatch (TRD §9), so
                            it belongs here rather than being discovered in support. */}
                        {tenant.capped && (
                          <span
                            className={`rounded-full border px-2 py-0.5 text-xs font-medium ${NOTICE_TONES.stop}`}
                          >
                            capped
                          </span>
                        )}
                        {/* The same two R-11 gates the work list is built from, on the
                            screen an operator already reads. `TenantSummary.holds` comes
                            from `read_tenant_holds` — the blockers themselves — so this
                            flag and the queue cannot disagree about who is stuck. The
                            label is the rule's operator name where we know it and the
                            gate's own name where we do not; either way it links to the
                            queue, which is where the remedy lives. */}
                        {tenant.holds.map((rule) => (
                          <Link
                            key={rule}
                            href="/admin/holds"
                            className={`rounded-full border px-2 py-0.5 text-xs font-medium hover:underline ${NOTICE_TONES.warn}`}
                            title="Held for a human decision — see the work list"
                          >
                            {holdRule(rule)?.label ?? rule}
                          </Link>
                        ))}
                      </div>
                    </td>
                    <td className="px-6 py-3 text-ink-muted">{tenant.vertical_template ?? "—"}</td>
                    <td className="px-6 py-3 tabular-nums text-ink">
                      {formatCount(tenant.live_agents)}
                    </td>
                    <td className="px-6 py-3 tabular-nums text-ink">{formatCount(tenant.calls_7d)}</td>
                    <td className="px-6 py-3 tabular-nums text-ink">{formatCount(tenant.leads)}</td>
                    <td className="px-6 py-3 text-xs text-ink-muted">
                      {formatIST(tenant.last_call_at)}
                    </td>
                    <td className="px-6 py-3">
                      {/* The marker tells the client shell to build the impersonating
                          session (admin token + X-Impersonate-Org). See
                          lib/api/session.tsx — it selects a credential, it grants none. */}
                      <Link
                        href={`/c/${tenant.slug}?${VIEW_AS_PARAM}=${VIEW_AS_ADMIN}`}
                        className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
                        title="Read-only view as this client (D-22) — every page view is logged"
                      >
                        <Eye className="h-3.5 w-3.5" />
                        View as
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
