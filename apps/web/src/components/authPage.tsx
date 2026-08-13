"use client";

/**
 * The frame the three sign-in surfaces sit in. Presentation only — no session, no realm.
 *
 * `/sign-in`, `/sign-up` and `/admin/sign-in` are outside both app shells: `/c` and
 * `/admin` each own a `fixed inset-0` layout and an auth page has neither. `globals.css`
 * sets `html, body { overflow: hidden }` for those shells, so a page that simply grows
 * is silently clipped at the fold — and on a sign-in page the clipped part is the
 * password field. Hence `flex-1 min-h-0 overflow-y-auto`, the same shape `/signup` and
 * the landing page already use and for the same reason.
 *
 * It carries no `Providers` (TanStack Query) because none of these screens calls the
 * API: signing in is a conversation between the browser and Clerk.
 */

import type { ReactNode } from "react";

import Link from "next/link";
import { Lock } from "lucide-react";

export function AuthPageFrame({
  /** Names the realm in the header, so an operator can see which door they are at. */
  realmLabel,
  children,
}: {
  realmLabel: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-app">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-md items-center justify-between gap-4 px-6 py-4">
          <Link href="/" className="text-base font-semibold tracking-tight text-ink">
            Calevate
          </Link>
          <span className="flex items-center gap-1.5 text-xs text-ink-faint">
            <Lock aria-hidden className="h-3.5 w-3.5" />
            {realmLabel}
          </span>
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-6 py-10">
        {children}
      </main>
    </div>
  );
}
