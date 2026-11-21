"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { Eye } from "lucide-react";

import { CreditLeft } from "@/components/admin/credit";
import { StatusPill, sentenceCase } from "@/components/admin/kit";
import {
  ProblemNotice,
  SECONDARY_BUTTON,
  ScrollRegion,
  Skeleton,
  type NoticeTone,
} from "@/components/ui";
import { planLabel, useTenant, type TenantSummary } from "@/lib/api/admin";
import { ApiProblem } from "@/lib/api/client";
import { useClosure } from "@/lib/api/closure";
import { useAdminBusinessProfile } from "@/lib/api/businessProfile";
import { useOwnerStatus } from "@/lib/api/onboarding";
import { viewAsHref } from "@/lib/api/session";
import { useBusinessTypeLabel } from "@/lib/businessTypes";
import { lookup } from "@/lib/lookup";

import {
  TENANT_SECTION_GROUPS,
  currentTenantSection,
  tenantSectionHref,
} from "./tenantSections";
import { onboardingRemaining } from "./accountFacts";

/** `organizations.status` is a bare string on the wire; an unknown one keeps a neutral pill. */
const STATUS_TONES: Record<string, NoticeTone> = {
  active: "ok",
  suspended: "warn",
  churned: "stop",
};

/**
 * EVERY PAGE OF ONE CLIENT (D-661): the client's name, its state and the one action, then a
 * grouped section menu beside the page.
 *
 * The layout owns the tenant read and its three non-answers. While the client is loading,
 * unreadable or missing, no sub-page mounts — so a sub-page never renders a body over a
 * client nobody has confirmed exists, and none of them repeats the guard. The read shares
 * `useTenant`'s query key, so a sub-page that also needs the record gets it from cache.
 *
 * Headings: the client's name is the document's `h1`. A sub-page starts at `h2`.
 */
export function TenantShell({ tenantId, children }: { tenantId: string; children: ReactNode }) {
  const tenantQuery = useTenant(tenantId);
  const tenant = tenantQuery.data;
  const pathname = usePathname() ?? "";

  if (tenantQuery.error) {
    if (isErasedClosureRead(tenantQuery.error, tenantId, pathname)) {
      return <ErasedClientShell tenantId={tenantId}>{children}</ErasedClientShell>;
    }
    return <ProblemNotice error={tenantQuery.error} onRetry={() => void tenantQuery.refetch()} />;
  }
  // Loading, and also a read the browser has parked while offline (the shell's offline
  // strip says why): neither is "no such client", so neither says it.
  if (!tenant) return <Skeleton rows={6} />;

  return (
    <div className="space-y-8 pb-12">
      <TenantHeader tenant={tenant} />
      <div className="space-y-6">
        <TenantSectionNav tenantId={tenantId} />
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}

/**
 * The one exception to "no sub-page without a live tenant": an ERASED client's Closing page.
 *
 * Erasure marks the organisation deleted, and the directory read filters deleted
 * organisations, so it answers 404 — which would leave the erasure certificate (the DPDP
 * record of what was destroyed and when) unreachable. The closure and erasure reads are
 * deliberately answerable after erasure, so this route alone is mounted on a 404. Every
 * other route, and every other error on this one, keeps the refusal above.
 */
function isErasedClosureRead(error: unknown, tenantId: string, pathname: string): boolean {
  const onClosure = pathname.replace(/\/$/, "") === `/admin/tenants/${tenantId}/closure`;
  return onClosure && error instanceof ApiProblem && error.status === 404;
}

/**
 * A minimal header and no section menu: every other section 404s for an erased client.
 * The heading says "Erased client" only once the closure read (shared with the page, so a
 * cache hit) confirms `erased_at`; a 404 for an id that never existed must not be told it
 * was erased, and the page shows that read's own refusal.
 */
function ErasedClientShell({ tenantId, children }: { tenantId: string; children: ReactNode }) {
  const closure = useClosure(tenantId);
  const erased = closure.data?.erased_at != null;
  return (
    <div className="space-y-6 pb-12">
      <header>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <h1 className="text-title text-ink">
            {erased ? "Erased client" : "Client not available"}
          </h1>
          {erased && <StatusPill tone="stop">Erased</StatusPill>}
        </div>
        {erased && (
          <p className="mt-1 text-body text-ink-muted">
            This client&apos;s records were erased. Only the closing record and its erasure
            certificate remain.
          </p>
        )}
      </header>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
function TenantHeader({ tenant }: { tenant: TenantSummary }) {
  const labelOf = useBusinessTypeLabel();
  const typeLabel = tenant.vertical_template ? labelOf(tenant.vertical_template) : "";
  return (
    <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0 flex-1 basis-64">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <h1 className="min-w-0 break-words text-title text-ink">{tenant.name}</h1>
          <StatusPill tone={lookup(STATUS_TONES, tenant.status) ?? "neutral"}>
            {sentenceCase(tenant.status)}
          </StatusPill>
          {/* Outbound is refused pre-dispatch at the ceiling (TRD §9). */}
          {tenant.capped && <StatusPill tone="stop">Capped</StatusPill>}
        </div>
        <p className="mt-1 text-meta text-ink-muted">
          /c/{tenant.slug} · {planLabel(tenant.plan_tier)}
          {typeLabel ? ` · ${typeLabel}` : ""}
        </p>
        {tenant.status === "onboarding" && <OnboardingNote tenantId={tenant.id} />}
        {/* Credit left on every page of the client, minutes first (founder, 10 Oct 2026):
            "why did their calls stop" is asked from every section, not only from Credits. */}
        {tenant.credit_inr !== undefined && tenant.plan_tier !== "managed" && (
          <p className="mt-0.5 text-meta">
            <span className="text-ink-muted">Credit left </span>
            <CreditLeft credit={tenant} compact />
          </p>
        )}
      </div>
      {/* `?view=admin` selects the impersonating credential (admin token +
          X-Impersonate-Org) in the client shell and grants nothing; the API verifies the
          admin identity regardless (lib/api/session.tsx). The label never says
          "read-only": since D-587 a view-as session can change the account. */}
      <Link
        href={viewAsHref(tenant.slug)}
        // Bordered, not filled: every section below owns its own one primary action, and
        // a green button in the header of every page would be a second one on each.
        className={`${SECONDARY_BUTTON} max-sm:w-full max-sm:justify-center`}
      >
        <Eye aria-hidden className="h-4 w-4" />
        View as client
      </Link>
    </header>
  );
}

/**
 * The section menu (founder, 12 Nov 2026: the twenty pages wrapped into four unlabeled rows).
 * Two levels, the way a settings area with many pages is usually navigated: one row of the
 * nine groups, underlined like the console's tabs, and under it the pages of the open group
 * when it has more than one. A group's tab opens the page already open in it, else its
 * first. Every page is two clicks away at most, and the command palette still lists all.
 *
 * The rows sit above the page at every width, so the page keeps its full width: a side
 * column took 240px beside the open sidebar and tables under it scrolled sideways.
 *
 * `aria-current="true"` marks the open page only, rather than `"page"`: the sidebar's
 * Clients entry already carries `"page"` for every client route, and a document with two
 * "current page" claims answers "where am I" twice.
 */
export function TenantSectionNav({ tenantId }: { tenantId: string }) {
  const pathname = usePathname() ?? "";
  const current = currentTenantSection(tenantId, pathname);
  const openGroup = TENANT_SECTION_GROUPS.find((group) =>
    group.items.some((item) => item === current),
  );
  const activeRef = useRef<HTMLAnchorElement>(null);

  // On a phone the open group can sit off the end of the row; scroll the ROW to it. Not
  // `scrollIntoView`: with `block: "nearest"` it also scrolls the page whenever the item is
  // below the fold. No smooth scroll: it runs on every navigation.
  useEffect(() => {
    const link = activeRef.current;
    let row = link?.parentElement ?? null;
    while (row && !(row.scrollWidth > row.clientWidth && /auto|scroll/.test(getComputedStyle(row).overflowX))) {
      row = row.parentElement;
    }
    if (!link || !row) return;
    const item = link.getBoundingClientRect();
    const box = row.getBoundingClientRect();
    if (item.left < box.left) row.scrollLeft += item.left - box.left - 8;
    else if (item.right > box.right) row.scrollLeft += item.right - box.right + 8;
  }, [current]);

  return (
    <nav aria-label="Client sections" className="space-y-3">
      <ScrollRegion
        label="Client sections"
        className="border-b border-line [scrollbar-width:none] [&::-webkit-scrollbar]:hidden max-sm:scroll-shadow-x"
      >
        <ul className="flex w-max gap-6">
          {TENANT_SECTION_GROUPS.map((group) => {
            const open = group === openGroup;
            const target = open && current ? current : group.items[0];
            const single = group.items.length === 1;
            return (
              <li key={group.label}>
                <Link
                  ref={open ? activeRef : undefined}
                  href={tenantSectionHref(tenantId, target)}
                  aria-current={open && single ? "true" : undefined}
                  className={`-mb-px flex h-10 items-center whitespace-nowrap border-b-2 text-body outline-none transition-colors duration-(--duration-fast) focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-brand touch:h-11 ${
                    open
                      ? "border-brand-strong font-medium text-ink"
                      : "border-transparent text-ink-muted hover:text-ink"
                  }`}
                >
                  {group.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </ScrollRegion>
      {openGroup && openGroup.items.length > 1 && (
        <ul aria-label={openGroup.label} className="flex flex-wrap gap-1">
          {openGroup.items.map((section) => {
            const on = section === current;
            return (
              <li key={section.path}>
                <Link
                  href={tenantSectionHref(tenantId, section)}
                  aria-current={on ? "true" : undefined}
                  className={`press flex h-8 items-center whitespace-nowrap rounded-full px-3 text-meta font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 ${
                    on ? "bg-ink/[0.06] text-ink" : "text-ink-muted hover:bg-ink/[0.05] hover:text-ink"
                  }`}
                >
                  {section.label}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}

/**
 * WHAT "ONBOARDING" IS WAITING FOR. The pill alone read as a verdict on the whole account
 * while it measures one thing: whether an owner has joined and the business profile has what
 * an agent needs to go live (`tenancy/onboarding.onboarding_finished`). KYC, the pledge and
 * payment are separate axes with their own sections, so they are not listed here.
 */
function OnboardingNote({ tenantId }: { tenantId: string }) {
  const owner = useOwnerStatus(tenantId);
  const profile = useAdminBusinessProfile(tenantId);
  const left = onboardingRemaining(owner, profile);
  if (left === null) return null;
  return (
    <p className="mt-0.5 text-meta text-ink-muted">
      {left.length === 0
        ? "Setup is finished. The account moves to Active on its next business profile save, or set it on Account state."
        : `Onboarding until: ${left.join("; ")}.`}
    </p>
  );
}
