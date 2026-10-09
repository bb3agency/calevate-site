"use client";

/**
 * The frame every authentication screen sits in. Presentation only — no session, no realm.
 *
 * One calm surface: the wordmark, the form in a card, and — on the client realm's screens
 * at desktop width — a panel showing the product the person is signing in to. The panel
 * is real console UI with illustrative data (`authShowcase.tsx`), never a stock picture,
 * and it is hidden below `lg` so a phone gets the form and nothing else.
 *
 * `/auth/**`, `/signup` and the admin door are outside both app shells: `/c` and `/admin`
 * each own a `fixed inset-0` layout and an auth page has neither. `globals.css` sets
 * `html, body { overflow: hidden }` for those shells, so a page that simply grows is
 * silently clipped at the fold — and on a sign-in page the clipped part is the password
 * field. Hence `flex-1 min-h-0 overflow-y-auto` on the outermost box.
 */

import type { ReactNode } from "react";

import Link from "next/link";

import { BrandWordmark } from "@/components/brand";
import { OfflineBanner } from "@/components/offline";

export function AuthPageFrame({
  /** Names the realm under the wordmark, so an operator can see which door they are at. */
  realmLabel,
  /** Shown beside the form from `lg` up; omitted, the form is centred on its own. */
  aside,
  /** `wide` for a form with more than a couple of fields (the workspace setup). */
  width = "narrow",
  children,
}: {
  realmLabel: string;
  aside?: ReactNode;
  width?: "narrow" | "wide";
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-app">
      {/* Offline matters MORE here than inside the consoles: a sign-in that cannot reach
          the API fails with a message about the request, and a person who cannot see that
          their connection is gone reads it as "my password is wrong". */}
      <OfflineBanner />
      <div
        className={`flex flex-1 flex-col ${
          aside ? "lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" : ""
        }`}
      >
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center justify-between gap-4 px-5 pt-5 sm:px-8 sm:pt-7">
            {/* The wordmark is the link's whole content, so its `alt` is the link's
                accessible name — "Calevate". */}
            <Link
              href="/"
              className="flex items-center rounded-md touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-app"
            >
              <BrandWordmark height={36} />
            </Link>
            <span className="text-xs font-medium text-ink-muted">{realmLabel}</span>
          </header>
          <main
            className={`mx-auto flex w-full flex-1 flex-col justify-center px-5 py-10 sm:px-8 ${
              width === "wide" ? "max-w-xl" : "max-w-[25rem]"
            }`}
          >
            {children}
          </main>
          <footer className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 px-5 pb-6 text-xs text-ink-muted">
            <Link href="/legal/privacy" className="inline-flex items-center py-1 underline-offset-2 hover:underline touch:min-h-11">
              Privacy
            </Link>
            <Link href="/legal/terms" className="inline-flex items-center py-1 underline-offset-2 hover:underline touch:min-h-11">
              Terms
            </Link>
          </footer>
        </div>
        {aside ? (
          <aside className="relative hidden min-w-0 overflow-hidden border-l border-line bg-surface lg:flex lg:flex-col lg:justify-center">
            {aside}
          </aside>
        ) : null}
      </div>
    </div>
  );
}

/** The card a form sits in: one hairline, one soft shadow, generous padding. */
export function AuthCard({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-5 shadow-card sm:p-7">
      {children}
    </div>
  );
}

/** The screen's one heading and the sentence under it. */
export function AuthHeading({ title, lead }: { title: string; lead?: ReactNode }) {
  return (
    <div className="mb-6 space-y-1.5">
      <h1 className="text-balance text-2xl font-semibold tracking-tight text-ink">{title}</h1>
      {lead ? <p className="text-sm text-ink-muted">{lead}</p> : null}
    </div>
  );
}
