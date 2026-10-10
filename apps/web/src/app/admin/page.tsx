"use client";

import { EmptySketch } from "@/components/console/emptySketch";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Plus, Search } from "lucide-react";

import { useAdminAccess, type AdminAccess } from "@/app/admin/access";
import { CreditLeft } from "@/components/admin/credit";
import { ADMIN_PAGE_WIDE, HAIRLINE_LIST, LIST_HEAD, ROW_HOVER, StatusPill, sentenceCase } from "@/components/admin/kit";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { RowMenu } from "@/components/console/rowMenu";
import {
  FIELD_INLINE,
  FIELD_INLINE_ICON,
  FilterChip,
  PRIMARY_BUTTON,
  type NoticeTone,
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
  type TenantSummary,
} from "@/lib/api/admin";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { holdRule } from "@/lib/api/holds";
import { viewAsHref } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { NoOwnerAccounts } from "./NoOwnerAccounts";

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
const TENANT_STATUS_TONES: Record<string, NoticeTone> = {
  active: "ok",
  suspended: "warn",
  churned: "stop",
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
 * THIS PAIR IS THE UNGUARDED LINK, and it is unguarded only until the OpenAPI snapshot
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
    <div className={ADMIN_PAGE_WIDE}>
      <PageHeader
        // Only from a page that ARRIVED, and the MATCHING total rather than the rows on
        // screen: a count is the most trusted thing on a directory and the cheapest to get
        // wrong. Nothing while loading or after a failed read — "0 accounts" is a claim.
        description={
          page
            ? `${formatCount(page.total)} ${page.total === 1 ? "account" : "accounts"}${narrowed ? " match" : ""}.`
            : undefined
        }
        actions={
          // Gated on `admin:tenants` from the identity read (see `createAccess`): a dead
          // control rather than a link to a form that will refuse the submission.
          create.allowed ? (
            <Link href="/admin/new" className={PRIMARY_BUTTON}>
              <Plus aria-hidden className="h-4 w-4" />
              New client
            </Link>
          ) : (
            <span aria-disabled className={`${PRIMARY_BUTTON} cursor-not-allowed opacity-50`}>
              <Plus aria-hidden className="h-4 w-4" />
              New client
            </span>
          )
        }
      />

      <RestrictionNote reason={create.reason} />

      <NoOwnerAccounts />

      {/* THE SEARCH AND THE FILTERS ARE THE SERVER'S: the roster is paged, so a filter over
          the loaded page would narrow 25 accounts and claim to have searched the platform. */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative min-w-0 flex-1 basis-60">
            <span className="sr-only">Search clients by name or slug</span>
            <Search
              aria-hidden
              className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
            />
            <input
              type="search"
              value={q}
              onChange={(event) => narrow(() => setQ(event.target.value))}
              placeholder="Search by name or slug"
              className={`${FIELD_INLINE_ICON} w-full`}
            />
          </label>
          <label className="min-w-0">
            <span className="sr-only">Sort</span>
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
        {/* State and billing as chips in one row, a hairline between the two groups: each
            group is one choice (or none), and both are the server's own filters. */}
        <ScrollRegion label="Filter clients" className="-mx-1 px-1 [scrollbar-width:none]">
          <div className="flex w-max items-center gap-1.5">
            <FilterChip label="Any state" active={!status} onClick={() => narrow(() => setStatus(""))} />
            {STATUS_FILTERS.map((value) => (
              <FilterChip
                key={value}
                label={sentenceCase(value)}
                active={status === value}
                onClick={() => narrow(() => setStatus(status === value ? "" : value))}
              />
            ))}
            <span aria-hidden className="mx-1.5 h-5 w-px bg-line" />
            <FilterChip label="Any billing" active={!planTier} onClick={() => narrow(() => setPlanTier(""))} />
            {PLAN_FILTERS.map((value) => (
              <FilterChip
                key={value}
                label={sentenceCase(value)}
                active={planTier === value}
                onClick={() => narrow(() => setPlanTier(planTier === value ? "" : value))}
              />
            ))}
          </div>
        </ScrollRegion>
      </div>

      {tenants.error && <ProblemNotice error={tenants.error} onRetry={() => void tenants.refetch()} />}

      <div>
        {tenants.isLoading ? (
          <Skeleton rows={5} />
        ) : tenants.error || !rows ? (
          /* Deliberately NOT the empty state: "there are no clients" is a claim about the
             world that a failed (or parked) read is not evidence for. */
          <p className="border-y border-line py-6 text-body text-ink-muted">
            The client directory could not be read, so this is not a list of your clients.
          </p>
        ) : rows.length === 0 ? (
          /* Two empty states, two facts: "nothing matched" is about the search; "no
             clients yet" is about the platform. */
          narrowed ? (
            <EmptyState message="No account matches this search. Clear the search or the filters." />
          ) : (
            <EmptyState
              message="No clients yet."
              hint="Each business you create appears here with its plan, state and credit."
              illustration={
                <EmptySketch kind="leads" />
              }
            />
          )
        ) : (
          // A TABLE ON EVERY WIDTH (founder, 10 Oct 2026): on a phone it scrolls sideways
          // with a shadow at the clipped edge rather than stacking each client into a card,
          // so an operator compares the same columns on any screen.
          <ScrollRegion label="Clients" className="scroll-shadow-x relative">
            <div className="min-w-[760px]">
            {/* Column labels for a sighted reader. Each cell below names itself to a screen
                reader, so this row is decoration and is hidden from assistive technology. */}
            <div aria-hidden className={`grid gap-4 px-2 pb-2 ${ROW_GRID} ${LIST_HEAD}`}>
              <span>Client</span>
              <span>Plan</span>
              <span>Status</span>
              <span>Credit left</span>
              <span>Last call</span>
              <span />
            </div>
            <ul aria-label="Clients" className={HAIRLINE_LIST}>
              {rows.map((tenant) => (
                <ClientRow key={tenant.id} tenant={tenant} />
              ))}
            </ul>
            </div>
          </ScrollRegion>
        )}
      </div>

      {/* Says WHICH rows are on screen: "26-50 of 312" is what an operator reads back on a
          support call, and it cannot be off by one the way a derived page index can. */}
      {page && page.total > page.rows.length && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-meta text-ink-muted">
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
              <ChevronLeft aria-hidden className="h-3.5 w-3.5" />
              Previous
            </button>
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={page.offset + page.rows.length >= page.total}
              onClick={() => setOffset(page.offset + DIRECTORY_PAGE_SIZE)}
            >
              Next
              <ChevronRight aria-hidden className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Client · plan · status and flags · credit left · last call · menu. */
const ROW_GRID =
  "grid-cols-[minmax(0,1.3fr)_6.5rem_minmax(0,1.2fr)_minmax(0,1.1fr)_7.5rem_2.75rem]";

/**
 * One client, one row (founder, 10 Oct 2026): name, plan, status with its flags, credit left
 * (minutes first, rupees second), last call. Hard rule 6: a cross-tenant screen carries
 * accounts only — a name, a slug, figures and the gates holding them; nothing that
 * identifies a person.
 */
function ClientRow({ tenant }: { tenant: TenantSummary }) {
  return (
    <li
      className={`grid items-center gap-x-4 px-2 py-3 ${ROW_GRID} ${ROW_HOVER}`}
    >
      <div className="min-w-0">
        <Link
          href={`/admin/tenants/${tenant.id}`}
          className="block truncate rounded-sm text-body font-medium text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
        >
          {tenant.name}
        </Link>
        <div className="truncate text-meta text-ink-muted">
          /c/{tenant.slug}
          {tenant.vertical_template ? ` · ${tenant.vertical_template.replace(/_/g, " ")}` : ""}
        </div>
      </div>
      <div className="col-start-6 row-start-1">
        <RowMenu
          label={tenant.name}
          items={[
            { id: "open", label: "Open", href: `/admin/tenants/${tenant.id}` },
            {
              // The marker selects the impersonating credential and grants nothing
              // (lib/api/session.tsx); everything viewed and changed is logged.
              id: "view-as",
              label: "View as client (logged)",
              href: viewAsHref(tenant.slug),
            },
          ]}
        />
      </div>
      <div className="col-start-2 row-start-1 text-body text-ink">
        <span className="sr-only">Plan: </span>
        {sentenceCase(tenant.plan_tier)}
      </div>
      <div className="col-start-3 row-start-1 flex flex-wrap items-center gap-1">
        <StatusPill tone={lookup(TENANT_STATUS_TONES, tenant.status) ?? "neutral"}>
          {sentenceCase(tenant.status)}
        </StatusPill>
        {/* Outbound is refused pre-dispatch at the ceiling (TRD §9). */}
        {tenant.capped && <StatusPill tone="stop">Capped</StatusPill>}
        {/* The R-11 gates from `read_tenant_holds` — the same list the hold queue is built
            from — linking to that queue, where the remedy lives. */}
        {tenant.holds.map((rule) => (
          <Link
            key={rule}
            href="/admin/holds"
            title="Held for a human decision — see the work list"
            className="rounded-full hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          >
            <StatusPill tone="warn">{holdRule(rule)?.label ?? rule}</StatusPill>
          </Link>
        ))}
      </div>
      <div className="col-start-4 row-start-1 text-body">
        <span className="sr-only">Credit left: </span>
        <CreditLeft credit={tenant} />
      </div>
      <div className="col-start-5 row-start-1 text-meta text-ink-muted">
        <span className="sr-only">Last call </span>
        {formatIST(tenant.last_call_at)}
      </div>
    </li>
  );
}
