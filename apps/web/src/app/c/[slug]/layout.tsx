"use client";

/**
 * Client realm shell — `app.calevate.tech/c/<slug>` (D-10: slug-based client URLs).
 *
 * The admin realm is a SEPARATE route group with a separate Clerk application; they
 * never share session logic (TRD §11). What they DO share, deliberately and in exactly
 * one place, is the D-22 "view as client" handoff: an operator can arrive at this URL
 * carrying an admin credential, and the shell has to build the impersonating session
 * rather than a client one. That decision lives in `ClientRealmProvider`
 * (lib/api/session.tsx), which documents why the URL marker grants no authority — the
 * admin token does, and the banner below renders from the server's answer, not the URL.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { use } from "react";

import { Providers } from "@/app/providers";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { ClientRealmProvider, useClientRealm } from "@/lib/api/session";

function Nav({ slug }: { slug: string }) {
  const pathname = usePathname();
  // `href()` carries the view-as marker across in-realm navigation. Without it, an
  // operator's second click drops back to a client token — a 401 two pages in, which
  // is a far more confusing failure than one at the front door.
  const { href } = useClientRealm();
  const items = [
    { href: `/c/${slug}`, label: "Dashboard" },
    { href: `/c/${slug}/agents`, label: "Agents" },
    { href: `/c/${slug}/calls`, label: "Calls" },
    { href: `/c/${slug}/leads`, label: "Leads" },
    { href: `/c/${slug}/campaigns`, label: "Campaigns" },
    { href: `/c/${slug}/do-not-call`, label: "Do not call" },
    { href: `/c/${slug}/knowledge`, label: "Knowledge" },
    { href: `/c/${slug}/integrations`, label: "Integrations" },
    { href: `/c/${slug}/lead-sources`, label: "Lead sources" },
    { href: `/c/${slug}/performance`, label: "Performance" },
    { href: `/c/${slug}/attention`, label: "Needs attention" },
    { href: `/c/${slug}/usage`, label: "Usage" },
  ];
  return (
    <nav className="flex flex-wrap gap-1">
      {items.map((item) => {
        // `usePathname()` excludes the query string, so the marker never breaks the
        // active-tab match.
        const active = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={href(item.href)}
            className={
              active
                ? "rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-slate-100 dark:text-slate-900"
                : "rounded-md px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            }
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

function Header({ slug }: { slug: string }) {
  const { session, viewAsRequested } = useClientRealm();
  const me = useMe(session);
  return (
    <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      {/* D-22: an admin viewing a client dashboard is READ-ONLY, and it must never
          look like the client's own session. The banner is the whole point.

          It keys off `me.impersonating`, which the API sets only after it has verified
          an admin identity and the `admin:impersonate` permission — never off the URL
          marker, so a client-realm user cannot make this appear. */}
      {me.data?.impersonating && (
        <div className="bg-amber-500 px-4 py-1.5 text-center text-xs font-semibold text-amber-950">
          Viewing as {me.data.organization?.name ?? slug} — read only. Every page view is
          logged, and anything that would change this account is refused.
        </div>
      )}
      {/* The handoff failed: this tab asked for the operator session and the API would
          not grant it (no admin session, no `admin:impersonate`, wrong realm). Saying
          so beats letting every panel below render its own 401. */}
      {viewAsRequested && !me.data?.impersonating && me.error != null && (
        <div className="border-b border-rose-200 bg-rose-50 px-4 py-2 dark:border-rose-900 dark:bg-rose-950">
          <ProblemNotice error={me.error} />
          <p className="mt-2 text-xs text-rose-800 dark:text-rose-300">
            This page was opened as an operator. Open it from the admin console, or{" "}
            <Link href={`/c/${slug}`} className="underline">
              continue as a normal user
            </Link>
            .
          </p>
        </div>
      )}
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {me.data?.organization?.name ?? "Calevate"}
          </p>
          <p className="text-xs text-slate-500">
            {me.data?.impersonating
              ? "Operator view"
              : me.data?.role
                ? `Signed in as ${me.data.role}`
                : " "}
          </p>
        </div>
        <Nav slug={slug} />
      </div>
    </header>
  );
}

export default function ClientRealmLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  return (
    <Providers>
      <div className="min-h-full bg-slate-50 dark:bg-slate-950">
        <ClientRealmProvider
          slug={slug}
          fallback={
            <main className="mx-auto max-w-6xl px-4 py-6">
              <Skeleton rows={8} />
            </main>
          }
        >
          <Header slug={slug} />
          <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
        </ClientRealmProvider>
      </div>
    </Providers>
  );
}
