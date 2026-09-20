"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Eye, Plus, Search } from "lucide-react";

import { useAdminAccess, type AdminAccess } from "@/app/admin/access";
import {
  Card,
  EmptyState,
  FIELD_INLINE,
  FIELD_INLINE_ICON,
  FilterChip,
  NOTICE_TONES,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  ScrollRegion,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import {
  DIRECTORY_PAGE_SIZE,
  useTenants,
  type DirectorySort,
  type TenantDirectoryQuery,
} from "@/lib/api/admin";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { holdRule } from "@/lib/api/holds";
import { viewAsHref } from "@/lib/api/session";
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
 * May this session create a client? — the server's own answer, plus this screen's own
 * precondition.
 *
 * The permission half is `useAdminAccess` (`@/app/admin/access`) reading
 * `GET /v1/admin/me`: `POST /v1/admin/tenants` is `admin:tenants` (`admin/routes.py`), and
 * the identity document says whether this operator holds it. This screen used to derive
 * that from a 403 on its own directory read — sound, because the list and the create
 * carry the identical permission, but it could only answer AFTER a request had failed, it
 * answered for no other permission, and it was the second of three different mechanisms
 * for one question. The identity endpoint replaced all three.
 *
 * The second half is NOT about permissions and does not move: a directory that could not
 * be read is a directory whose slug collisions we cannot see, so the button stays dead
 * while the list is missing whatever the reason. "You may not" and "we could not find
 * out" are different sentences, and only one of them is about the operator.
 *
 * Not exported: a Next.js page module may only export the default and the framework's own
 * named exports, so this is asserted through the DOM.
 */
function createAccess(
  access: AdminAccess,
  query: { error: unknown; isLoading: boolean },
): { allowed: boolean; reason: string | null } {
  // Identity first: it is the only half that can say the refusal is about the OPERATOR,
  // and while it is unknown it already returns `allowed: false` with no sentence.
  if (!access.allowed) return { allowed: false, reason: access.reason };
  // One sentence for every read failure, 403 included. The old code split them so a 403
  // could name `admin:tenants`; the identity read answers that question above now, and a
  // 403 arriving HERE while the identity says the permission is held is not an
  // authorization fact this screen can explain — the `ProblemNotice` shows what the
  // server actually said.
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

/**
 * The statuses and billing motions the directory may be narrowed by.
 *
 * Spelled here and sent as-is. The API declares the same two sets as `Literal`s, refuses
 * anything else by name, and `tests/admin_account_management_test.py` holds THOSE against
 * the database's own CHECK constraints — so the wire is guarded at both ends and a chip
 * for a status the column cannot hold would be refused rather than silently matching
 * nothing.
 *
 * ⚠ THIS PAIR IS THE UNGUARDED LINK, and it is unguarded only until the OpenAPI snapshot
 * is regenerated: the generated `schema.d.ts` carries those `Literal`s as unions, and
 * typing these as `TenantDirectoryQuery["status"]` is what closes it. Until then a value
 * added to the API and not to this list is a filter an operator cannot reach.
 */
const STATUS_FILTERS = ["prospect", "onboarding", "active", "suspended", "churned"] as const;
const PLAN_FILTERS = ["managed", "prepaid", "self_serve", "trial"] as const;

const SORT_LABELS: Record<DirectorySort, string> = {
  recent: "Newest first",
  oldest: "Oldest first",
  name: "Name A–Z",
  name_desc: "Name Z–A",
};

export default function AdminClientsPage() {
  const [q, setQ] = useState("");
  /**
   * What the SERVER is asked for, which lags what is typed by a short pause.
   *
   * The search box drives the query key, so an undebounced value is one request — and one
   * server-side scan that opens a tenant session per matching account — per keystroke.
   * The same 300ms the leads screen uses, and deliberately the same mechanism rather than
   * a second one: the input itself stays instant, and only the request waits.
   */
  const [term, setTerm] = useState("");
  const [status, setStatus] = useState("");
  const [planTier, setPlanTier] = useState("");
  const [sort, setSort] = useState<DirectorySort>("recent");
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => setTerm(q.trim()), 300);
    return () => clearTimeout(timer);
  }, [q]);

  const query: TenantDirectoryQuery = { q: term, status, planTier, sort, offset };
  const tenants = useTenants(query);
  const page = tenants.data;
  const rows = page?.rows;
  // From the TERM, not the box: while a search is still settling the screen is showing
  // the previous answer, and calling it "narrowed" would swap the empty state under the
  // reader's cursor a beat before the rows arrive.
  const narrowed = Boolean(term || status || planTier);

  /**
   * Every change to what is being ASKED sends the reader back to the first page.
   *
   * Without this, narrowing a nine-page list while on page four asks the server for rows
   * 75-100 of a set that now has three, and the operator is shown an empty table over a
   * count that says four matched. The one place the offset survives is the sort, which
   * is why that is not routed through here — reordering a list you are paging is a
   * request to see the same set differently, not a different set.
   */
  function narrow(apply: () => void) {
    apply();
    setOffset(0);
  }

  const mayCreate = useAdminAccess("admin:tenants", "create clients");
  const create = createAccess(mayCreate, tenants);

  /*
   * THE DIRECTORY, DECLARED TO THE SCREEN ASSISTANT.
   *
   * COUNTS ONLY, AND NOT ONE ROW. This is the console's widest cross-tenant screen — every
   * client the platform has, on one table — so the shape of the declaration is decided by
   * hard rule 1 rather than by what would be convenient: a roster in the prompt would put
   * every client's name, slug and call volume into a conversation the operator is having
   * about one of them, and the model would then answer questions about the others. The
   * counts describe the SHAPE of what is on screen ("nine accounts, two of them held"),
   * which is what an operator asks about here, and they identify nobody.
   *
   * The header sentence already refuses to print a count from a list that did not arrive,
   * for the reason the module docstring gives, and this declaration inherits that refusal
   * rather than restating it as a zero.
   */
  useCopilotSurface({
    route: "/admin",
    title: "Clients",
    realm: "admin",
    fields: [],
    facts: rows && page
      ? [
          {
            key: "accounts",
            // THE MATCHING TOTAL, and the label says which number this is. The screen
            // shows one page now, so "accounts listed" would be the page size — and an
            // assistant told there are 25 clients on a platform with 312 would answer
            // questions about the platform from the size of a window onto it.
            label: narrowed
              ? "Client accounts matching the current search and filters"
              : "Client accounts on the platform",
            value: String(page.total),
          },
          {
            key: "page",
            label: "Accounts on the page being read",
            value: String(rows.length),
          },
          {
            key: "active",
            label: "Accounts with status active, on this page",
            value: String(rows.filter((tenant) => tenant.status === "active").length),
          },
          {
            key: "capped",
            label: "Accounts at their spend ceiling on this page (outbound refused pre-dispatch)",
            value: String(rows.filter((tenant) => tenant.capped).length),
          },
          {
            key: "held",
            label: "Accounts held for a human decision, on this page",
            value: String(rows.filter((tenant) => tenant.holds.length > 0).length),
          },
          {
            key: "may_create",
            label: "May this operator create a client",
            value: create.allowed ? "yes" : "no",
          },
        ]
      : [
          {
            key: "directory",
            label: "The client directory",
            value: tenants.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  return (
    <div className="space-y-4 pb-12">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="text-sm text-ink-muted">
          Every client account, and anything currently holding one up.
          {/* Only from a page that ARRIVED, and it is the MATCHING total rather than the
              number of rows on screen: a count is the most trusted thing on a directory
              and the cheapest thing to get wrong. */}
          {page &&
            ` ${formatCount(page.total)} ${page.total === 1 ? "account" : "accounts"}${
              narrowed ? " match" : ""
            }.`}
        </p>
        {/* Gated on `admin:tenants` — the permission the route behind it requires — from
            the console's own identity read (see `createAccess`). A dead control rather
            than a link to a form that will refuse the submission: the wasted work is the
            form, not the click. */}
        {create.allowed ? (
          <Link
            href="/admin/new"
            className="inline-flex items-center gap-2 rounded-lg bg-brand-strong px-3 py-2 text-sm font-semibold text-white hover:bg-brand-deep"
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

      {/* THE SEARCH AND THE FILTERS ARE THE SERVER'S. Every control here changes the
          request, never a list held in the browser: the roster is paged, so a filter
          applied to the loaded page would narrow 25 accounts and quietly claim to have
          searched the platform. */}
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative flex-1 sm:min-w-[220px]">
          <span className="sr-only">Search clients by name or slug</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
          />
          <input
            type="search"
            value={q}
            onChange={(event) => narrow(() => setQ(event.target.value))}
            placeholder="Search by business name or slug"
            className={`${FIELD_INLINE_ICON} w-full`}
          />
        </label>
        <label className="flex items-center gap-2 text-xs text-ink-muted">
          <span>Sort</span>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as DirectorySort)}
            className={FIELD_INLINE}
          >
            {(Object.keys(SORT_LABELS) as DirectorySort[]).map((value) => (
              <option key={value} value={value}>
                {SORT_LABELS[value]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-ink-faint">State</span>
        <FilterChip label="any" active={!status} onClick={() => narrow(() => setStatus(""))} />
        {STATUS_FILTERS.map((value) => (
          <FilterChip
            key={value}
            label={value}
            active={status === value}
            onClick={() => narrow(() => setStatus(status === value ? "" : value))}
          />
        ))}
        <span className="ml-4 text-xs font-medium text-ink-faint">Billing</span>
        <FilterChip label="any" active={!planTier} onClick={() => narrow(() => setPlanTier(""))} />
        {PLAN_FILTERS.map((value) => (
          <FilterChip
            key={value}
            label={value.replace(/_/g, " ")}
            active={planTier === value}
            onClick={() => narrow(() => setPlanTier(planTier === value ? "" : value))}
          />
        ))}
      </div>

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
          /* TWO EMPTY STATES, because they are two different facts about the world.
             "Nothing matched" is about the search the operator just typed and is fixed by
             changing it; "no clients yet" is about the platform. Rendering the second when
             a filter is on tells an operator with 300 clients that they have none. */
          narrowed ? (
            <EmptyState
              title="No account matches this search"
              hint="Clear the search box or the filters above to see the rest of the directory."
            />
          ) : (
            <EmptyState
              title="No clients yet"
              hint="Create the first one and it appears here, along with anything left to finish setting it up."
            />
          )
        ) : (
          <ScrollRegion label="Client directory">
            <table className="w-full min-w-[880px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th className="px-6 py-3 font-semibold">Client</th>
                  <th className="px-6 py-3 font-semibold">Status</th>
                  <th className="px-6 py-3 font-semibold">Business type</th>
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
                    <td className="px-6 py-3 text-ink-muted">
                      {tenant.vertical_template?.replace(/_/g, " ") ?? "—"}
                    </td>
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
                        href={viewAsHref(tenant.slug)}
                        className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-xs font-medium text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
                        title="Open this client's console as an operator — every view and every change is logged against you"
                      >
                        <Eye className="h-3.5 w-3.5" />
                        View as
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
      </Card>

      {/* The pager renders only when there is a page to go to, and it says WHICH rows are
          on screen rather than a page number: "26-50 of 312" is the sentence an operator
          reads back on a support call, and it cannot be wrong by an off-by-one the way a
          derived page index can. */}
      {page && page.total > page.rows.length && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-ink-muted">
          <span aria-live="polite">
            Showing {formatCount(page.offset + 1)}–{formatCount(page.offset + page.rows.length)} of{" "}
            {formatCount(page.total)}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={page.offset === 0}
              onClick={() => setOffset(Math.max(0, page.offset - DIRECTORY_PAGE_SIZE))}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              Previous
            </button>
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={page.offset + page.rows.length >= page.total}
              onClick={() => setOffset(page.offset + DIRECTORY_PAGE_SIZE)}
            >
              Next
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
