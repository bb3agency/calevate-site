"use client";

/**
 * Admin realm shell — `admin.calevate.tech`.
 *
 * A SEPARATE route group from `/c/[slug]` on purpose (TRD §11): different Clerk
 * application, different session, different navigation. Nothing here imports the
 * client realm's session helpers, so an admin token and a client token cannot be
 * confused by a shared code path.
 *
 * The visual language differs deliberately too. An operator with cross-client reach
 * should never be one glance away from believing they are inside a client's own
 * dashboard — that is the same instinct behind D-22's impersonation banner.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Providers } from "@/app/providers";

const NAV = [
  { href: "/admin", label: "Clients" },
  { href: "/admin/new", label: "New client" },
  { href: "/admin/ops", label: "Operations" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <Providers>
      <div className="min-h-full bg-slate-950">
        <header className="border-b border-slate-800 bg-slate-900">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-slate-50">Calevate admin</p>
              <p className="text-xs text-slate-400">Cross-client operator console</p>
            </div>
            <nav className="flex gap-1">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={
                    pathname === item.href
                      ? "rounded-md bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-900"
                      : "rounded-md px-3 py-1.5 text-sm font-medium text-slate-300 hover:bg-slate-800"
                  }
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6 text-slate-100">{children}</main>
      </div>
    </Providers>
  );
}
