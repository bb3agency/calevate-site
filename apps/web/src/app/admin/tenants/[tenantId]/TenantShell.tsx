"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";
import { Eye } from "lucide-react";

import {
  NOTICE_TONES,
  PRIMARY_BUTTON,
  ProblemNotice,
  ScrollRegion,
  Skeleton,
} from "@/components/ui";
import { useTenant, type TenantSummary } from "@/lib/api/admin";
import { ApiProblem } from "@/lib/api/client";
import { useClosure } from "@/lib/api/closure";
import { viewAsHref } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import {
  TENANT_SECTION_GROUPS,
  currentTenantSection,
  tenantSectionHref,
} from "./tenantSections";

/** `organizations.status` is a bare string on the wire; an unknown one keeps a neutral pill. */
const STATUS_TONES: Record<string, string> = {
  active: "border-brand/30 bg-brand-soft text-brand-strong dark:bg-brand-strong/20",
  suspended: NOTICE_TONES.warn,
  churned: NOTICE_TONES.stop,
};

const PILL = "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium";

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
    <div className="space-y-6 pb-12">
      <TenantHeader tenant={tenant} />
      <div className="gap-8 lg:grid lg:grid-cols-[208px_minmax(0,1fr)]">
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
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            {erased ? "Erased client" : "Client not available"}
          </h1>
          {erased && <span className={`${PILL} ${NOTICE_TONES.stop}`}>erased</span>}
        </div>
        {erased && (
          <p className="mt-1 text-[14px] text-ink-muted">
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
  return (
    <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0 flex-1 basis-64">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <h1 className="min-w-0 break-words text-2xl font-semibold tracking-tight text-ink">
            {tenant.name}
          </h1>
          <span
            className={`${PILL} capitalize ${lookup(STATUS_TONES, tenant.status) ?? NOTICE_TONES.neutral}`}
          >
            {tenant.status}
          </span>
          {/* Outbound is refused pre-dispatch at the ceiling (TRD §9). */}
          {tenant.capped && <span className={`${PILL} ${NOTICE_TONES.stop}`}>capped</span>}
        </div>
        <p className="mt-1 text-[14px] text-ink-muted">
          /c/{tenant.slug} · {tenant.plan_tier.replace(/_/g, " ")}
          {tenant.vertical_template ? ` · ${tenant.vertical_template.replace(/_/g, " ")}` : ""}
        </p>
      </div>
      {/* `?view=admin` selects the impersonating credential (admin token +
          X-Impersonate-Org) in the client shell and grants nothing; the API verifies the
          admin identity regardless (lib/api/session.tsx). The label says "(logged)" and
          never "read-only": since D-587 a view-as session can change the account, and what
          stays true is that everything viewed and changed is recorded against the operator.
          It is in the label, where a keyboard user reads it, not only in the title. */}
      <Link
        href={viewAsHref(tenant.slug)}
        title="Everything you view and everything you change is recorded against you in the audit log."
        className={`${PRIMARY_BUTTON} max-sm:w-full max-sm:justify-center`}
      >
        <Eye aria-hidden className="h-4 w-4" />
        View as client (logged)
      </Link>
    </header>
  );
}

/**
 * The section menu: a sticky grouped column from `lg`, one scrolling row on a phone. ONE
 * list in both shapes, so each page has exactly one link in the document. Single-page
 * groups show only their item; the group heading would repeat it.
 *
 * `aria-current="true"` rather than `"page"`: the sidebar's Clients entry already carries
 * `"page"` for every client route, and a document with two "current page" claims answers
 * "where am I" twice.
 */
export function TenantSectionNav({ tenantId }: { tenantId: string }) {
  const pathname = usePathname() ?? "";
  const current = currentTenantSection(tenantId, pathname);
  const activeRef = useRef<HTMLAnchorElement>(null);

  // On a phone the active item can sit off the end of the row; bring it into view without
  // moving the page vertically. No smooth scroll: it runs on every navigation.
  useEffect(() => {
    activeRef.current?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [current]);

  return (
    <nav aria-label="Client sections" className="mb-6 lg:sticky lg:top-2 lg:mb-0 lg:self-start">
      <ScrollRegion
        label="Client sections"
        className="-mx-1 px-1 pb-1 lg:mx-0 lg:overflow-visible lg:p-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        <ul className="flex w-max items-center gap-1 lg:w-auto lg:flex-col lg:items-stretch lg:gap-0.5">
          {TENANT_SECTION_GROUPS.map((group, index) => (
            <li
              key={group.label}
              className={`flex items-center gap-1 lg:block ${
                index > 0 ? "border-l border-line pl-1 lg:border-l-0 lg:pl-0" : ""
              } ${group.items.length > 1 ? "lg:py-2" : ""}`}
            >
              {group.items.length > 1 && (
                <p
                  id={`tenant-group-${index}`}
                  className="mb-1 hidden px-3 text-[12px] font-medium text-ink-faint lg:block"
                >
                  {group.label}
                </p>
              )}
              <ul
                aria-labelledby={group.items.length > 1 ? `tenant-group-${index}` : undefined}
                className="flex items-center gap-1 lg:flex-col lg:items-stretch lg:gap-0.5"
              >
                {group.items.map((section) => {
                  const on = section === current;
                  return (
                    <li key={section.path}>
                      <Link
                        ref={on ? activeRef : undefined}
                        href={tenantSectionHref(tenantId, section)}
                        aria-current={on ? "true" : undefined}
                        className={`press flex h-9 items-center whitespace-nowrap rounded-full px-3.5 text-[13px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 lg:rounded-md lg:px-3 lg:text-[14px] ${
                          on
                            ? "bg-ink text-surface lg:bg-ink/[0.06] lg:text-ink"
                            : "text-ink-muted hover:bg-ink/[0.05] hover:text-ink lg:font-normal"
                        }`}
                      >
                        {section.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      </ScrollRegion>
    </nav>
  );
}
