"use client";

/**
 * Client realm shell — `app.calevate.tech/c/<slug>` (D-10: slug-based client URLs).
 *
 * The admin realm is a SEPARATE route group with a separate Clerk application; they
 * never share session logic (TRD §11), which is why this layout builds its own session
 * from the slug rather than reading a global one.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { use } from "react";

import { Providers } from "@/app/providers";
import { devSession } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";

function Nav({ slug }: { slug: string }) {
  const pathname = usePathname();
  const items = [
    { href: `/c/${slug}`, label: "Dashboard" },
    { href: `/c/${slug}/calls`, label: "Calls" },
    { href: `/c/${slug}/leads`, label: "Leads" },
    { href: `/c/${slug}/knowledge`, label: "Knowledge" },
  ];
  return (
    <nav className="flex gap-1">
      {items.map((item) => {
        const active = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
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
  const session = devSession(slug);
  const { data: me } = useMe(session);
  return (
    <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      {/* D-22: an admin viewing a client dashboard is READ-ONLY, and it must never
          look like the client's own session. The banner is the whole point. */}
      {me?.impersonating && (
        <div className="bg-amber-500 px-4 py-1.5 text-center text-xs font-semibold text-amber-950">
          Viewing as {me.organization?.name ?? slug} — read only. Every page view is logged.
        </div>
      )}
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-slate-900 dark:text-slate-50">
            {me?.organization?.name ?? "Calevate"}
          </p>
          <p className="text-xs text-slate-500">{me?.role ? `Signed in as ${me.role}` : " "}</p>
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
        <Header slug={slug} />
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </div>
    </Providers>
  );
}
