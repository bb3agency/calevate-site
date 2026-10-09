"use client";

import { use, useState } from "react";

import { Providers } from "@/app/providers";
import { ToastProvider } from "@/components/interior/toaster";
import { MaintenanceBanner, MaintenanceGate } from "@/components/maintenance";
import { OfflineBanner } from "@/components/offline";
import { MAIN_CONTENT_ID, SHELL_RAIL_CLASS, Skeleton, SkipLink } from "@/components/ui";
import { ClientRealmProvider } from "@/lib/api/session";

import { ClientSidebar } from "./ClientSidebar";
import { ClientTopHeader } from "./ClientTopHeader";
import { TrialBanner } from "./TrialBanner";
import { ViewAsBanner } from "./ViewAsBanner";

/**
 * The client console's app shell.
 *
 * Every route under `/c/<slug>` renders inside it, so the things it gets wrong, it
 * gets wrong twenty times. Two of those are worth naming here because they are easy
 * to reintroduce: the nav is ONE list that both the sidebar and the page title read
 * (a second copy is how a renamed screen keeps its old title in the header), and
 * every destination in it is a route that exists — a nav entry pointing at a 404 is
 * the frontend's version of the half-wired feature `scripts/check_wiring.py` refuses
 * on the backend.
 *
 * The pieces live beside it by subject: the sidebar (`ClientSidebar.tsx`), the top bar
 * with its counters and the assistant (`ClientTopHeader.tsx`) and the operator banner
 * (`ViewAsBanner.tsx`). A layout module may export only Next's conventions, so they
 * cannot live in this file as exports.
 */

export default function ClientRealmLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  return (
    <Providers>
      {/* `ToastProvider` app-wide for this realm, so `useToast()` works on any screen the
          shell renders. Its notifications region is `fixed` bottom-right, renders AFTER the
          shell subtree and is `pointer-events-none` with an empty `aria-live` polite region
          until a toast is fired — so it adds no landmark the a11y sweep flags, no focusable
          element ahead of `SkipLink`, and nothing to the DOM the "you are here" checks read.
          It wraps the shell (rather than sitting inside the scrolling `<main>`) so a toast
          survives navigation between screens and is not clipped by the shell's overflow. */}
      <ToastProvider>
        {/* `data-app-shell` is what `globals.css` scopes its `overflow: hidden` pin to.
            The document scrolls by default; a shell that clips its own content is the only
            thing that needs the document to stop. */}
        <div data-app-shell className="fixed inset-0 flex overflow-hidden bg-app font-sans">
          {/* FIRST focusable thing in the shell, and outside `ClientRealmProvider` on
              purpose: the sidebar is 21 links, and a reader must be able to bypass them
              even while the session is still resolving and the fallback skeleton is what
              is on screen (WCAG 2.4.1, Level A). */}
          <SkipLink />
          <ClientRealmProvider
            slug={slug}
            fallback={
              // A `<main>` here too, carrying the same id: `SkipLink` above is rendered in
              // EVERY state of this shell, so its target has to exist in every state or the
              // control is dead exactly when the page is slowest. The gate branches get
              // theirs from `SessionGate`'s `landmark` prop; this is the Suspense arm, which
              // no gate reaches. Measured by axe in a real browser — `skip-link`, "the
              // skip-link target should exist and be focusable".
              <main
                id={MAIN_CONTENT_ID}
                tabIndex={-1}
                className="flex h-full w-full items-center justify-center"
              >
                <div className="w-full max-w-96 px-4">
                  <Skeleton rows={8} />
                </div>
              </main>
            }
          >
            <ClientSidebar slug={slug} isMobileOpen={isMobileOpen} onClose={() => setIsMobileOpen(false)} />
            <div className="flex flex-1 flex-col overflow-hidden">
              {/* ABOVE the view-as banner and the header, because it is a statement about
                  the whole window rather than about this screen — and it renders nothing at
                  all while online, so a connected user pays no DOM for it. */}
              <OfflineBanner />
              {/* BELOW the offline strip and above everything else, for the same reason
                  that one is where it is: it is a statement about the whole window rather
                  than about this screen. It renders nothing at all when no window is
                  scheduled, which is every ordinary day. */}
              <MaintenanceBanner />
              <ViewAsBanner slug={slug} />
              {/* A statement about the ACCOUNT on every screen, below the two about the
                  window: while a trial runs every money sentence in the console means
                  something different, and a client must not have to open billing to learn
                  it. Renders nothing when no trial is running. */}
              <TrialBanner />
              <ClientTopHeader slug={slug} onMenuToggle={() => setIsMobileOpen(true)} />
              {/* `tabIndex={-1}` is what makes `SkipLink` actually skip: following a
                  fragment scrolls to the target but only MOVES FOCUS if the target is
                  focusable, so without it the next Tab resumes inside the navigation the
                  reader just asked to leave. */}
              <main
                id={MAIN_CONTENT_ID}
                tabIndex={-1}
                className="relative flex-1 overflow-y-auto bg-surface px-4 py-4 lg:px-8 lg:py-8"
              >
                {/* THE DOOR. Inside the shell, so a locked-out client sees their own
                    console with a message in it rather than a bare error page — and
                    wrapping `children` rather than the layout, so the sidebar, the header
                    and the skip link all survive the window. It renders `children`
                    untouched unless the platform has actually refused us with a
                    maintenance 503. */}
                <div className={SHELL_RAIL_CLASS}>
                  <MaintenanceGate>{children}</MaintenanceGate>
                </div>
              </main>
            </div>
          </ClientRealmProvider>
        </div>
      </ToastProvider>
    </Providers>
  );
}
