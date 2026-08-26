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
 * API: signing in was a conversation between the browser and a vendor. Since D-177 it
 * is a conversation with our own `/v1/auth/**`, and these pages are both halves of it.
 */

import type { ReactNode } from "react";

import Link from "next/link";
import { Lock } from "lucide-react";

import { BrandWordmark } from "@/components/brand";

import { OfflineBanner } from "@/components/offline";

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
      {/* Offline matters MORE here than inside the consoles: a sign-in that cannot reach
          the API fails with a message about the request, and a person who cannot see that
          their connection is gone reads it as "my password is wrong" and starts changing
          it. `OfflineBanner` needs no `Providers` — query-core's `onlineManager` is a
          module singleton, not a context — so the frame's deliberate lack of one (see the
          header comment) is untouched. */}
      <OfflineBanner />
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-md items-center justify-between gap-4 px-6 py-4">
          {/* The wordmark is the link's whole content, so its `alt` is the link's
              accessible name — "Calevate" — which is what it read as before. */}
          <Link href="/" className="flex items-center">
            <BrandWordmark height={44} />
          </Link>
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs text-ink-faint">
              <Lock aria-hidden className="h-3.5 w-3.5" />
              {realmLabel}
            </span>
          </div>
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-6 py-10">
        {children}
      </main>
    </div>
  );
}
