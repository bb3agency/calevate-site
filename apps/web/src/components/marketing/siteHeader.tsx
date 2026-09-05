/**
 * The marketing header: a wordmark, a way around the page, "Sign in", and one door.
 *
 * ## What changed and why
 *
 * It used to be three things in a row — mark, "Sign in", and a button reading "Create a
 * workspace". Two defects, both of them about the person the header is actually for:
 *
 * 1. **"Create a workspace" is product vocabulary aimed at somebody who already knows what
 *    we are.** A clinic owner who has been on this page for four seconds does not want a
 *    workspace; they do not yet know what one is. It is now "Get started", the same label
 *    every other link to `/signup` carries — see `HEADER_CTA` for the decision, which was
 *    made twice on 5 Sep 2026 and landed there.
 * 2. **There was no way around the page.** A landing page with fourteen bands and no
 *    navigation asks every reader to scroll for the one thing they came for.
 *
 * ## Why the mobile menu is `<details>` and not a button with `aria-expanded`
 *
 * Same argument the FAQ records, and the same one that keeps this file a SERVER component.
 * `<details>`/`<summary>` is the platform's own disclosure widget: it is keyboard-operable
 * (Enter and Space on the summary), announced as expandable by every screen reader, and
 * correct with no JavaScript at all — which matters here more than anywhere, because a
 * menu that needs a bundle is a page a reader on a bad connection cannot navigate. A
 * hand-built version would be a second answer to a question this repo has already
 * answered (CLAUDE.md, "one way per problem"), plus its own focus handling to get wrong.
 *
 * It is a DISCLOSURE, not a modal: it does not trap focus and does not close on Escape,
 * which is correct for a menu that pushes the page rather than covering it.
 *
 * ## Why the links are anchors on this page rather than routes
 *
 * Because those routes do not exist. A nav item pointing at `/solutions` would be the
 * "route nobody mounted" defect CLAUDE.md names — a promise in the one place a visitor
 * trusts most. Every item here scrolls to a section that is really on the page.
 */

import Link from "next/link";
import { Menu } from "lucide-react";

import { MarketingAccountNav } from "@/components/authn/marketingAccountNav";
import { BrandHeaderMark } from "@/components/brand";

/**
 * The page's own sections, in reading order. Each `href` is an id this page really
 * renders — `publicLanding.test.tsx` pins that, because a nav item that scrolls nowhere
 * is indistinguishable from a broken page to the reader and invisible to everyone else.
 */
export const NAV_SECTIONS: readonly { href: string; label: string }[] = [
  { href: "#how", label: "How it works" },
  { href: "#capabilities", label: "What it does" },
  { href: "#industries", label: "Industries" },
  { href: "#why", label: "Why Calevate" },
  { href: "#cost", label: "What it costs" },
];

/**
 * The header's call to action.
 *
 * ⚠ THIS WAS "See how it works" FOR HALF OF 5 SEP 2026 AND THE FOUNDER REVERSED IT THE
 * SAME DAY. The header carries Sign in + the signup door; "See how it works" survives as
 * the hero's lower-intent SECONDARY button, which is where a cold visitor who is not ready
 * to start an account still has somewhere to go. What both decisions agree on, and what
 * must not come back, is "Create a workspace": it is product vocabulary aimed at a reader
 * who does not yet know what we are.
 *
 * The label is the same string every other link to `/signup` on this page carries — one
 * door, one name for it (`app/page.tsx::CTA_LABEL`, pinned by `publicLanding.test.tsx`).
 */
export const HEADER_CTA = { href: "/signup", label: "Get started" } as const;

const NAV_LINK =
  "rounded-md px-2.5 py-1.5 text-sm font-medium whitespace-nowrap text-ink-muted transition-colors hover:bg-black/5 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong dark:hover:bg-white/5";

/** The same link, sized for a thumb inside the menu panel. */
const MENU_LINK =
  "block rounded-lg px-3 py-3 text-base font-medium text-ink transition-colors hover:bg-brand-soft/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/85 backdrop-blur-md">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-5 py-3 sm:gap-4 sm:px-6 xl:max-w-7xl 2xl:max-w-[90rem]">
        {/* Square mark on a phone, wordmark from `sm` — one element, one request. The row
            does not fit at 320px otherwise; `BrandHeaderMark` carries the measurement. */}
        <BrandHeaderMark />

        {/* The desktop nav. Hidden below `lg` by CSS, which is why the menu below exists —
            the two are the same five destinations, never two different site maps. */}
        <nav aria-label="Sections" className="hidden lg:flex lg:items-center lg:gap-1">
          {NAV_SECTIONS.map((item) => (
            <Link key={item.href} href={item.href} className={NAV_LINK}>
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-1.5 sm:gap-2">
          <MarketingAccountNav ctaHref={HEADER_CTA.href} ctaLabel={HEADER_CTA.label} />

          {/* The menu, below `lg`. `relative` on the wrapper so the panel hangs off the
              header rather than off the page. */}
          <details className="group relative lg:hidden">
            <summary
              className="flex h-9 w-9 cursor-pointer list-none items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-black/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong [&::-webkit-details-marker]:hidden dark:hover:bg-white/5"
              aria-label="Menu"
            >
              <Menu aria-hidden className="h-5 w-5" />
            </summary>
            {/* `right-0` and a fixed width: anchored to the button, never wider than the
                narrowest phone this page is designed for. */}
            <nav
              aria-label="Sections menu"
              className="absolute right-0 z-40 mt-2 w-60 rounded-xl border border-line bg-surface p-2 shadow-lg"
            >
              <ul>
                {NAV_SECTIONS.map((item) => (
                  <li key={item.href}>
                    <Link href={item.href} className={MENU_LINK}>
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          </details>
        </div>
      </div>
    </header>
  );
}
