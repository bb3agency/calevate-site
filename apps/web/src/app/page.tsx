import type { Metadata } from "next";

import { MarketingPage } from "@/components/marketing/pageShell";
import { Closing } from "@/components/marketing/home/closing";
import { Cost } from "@/components/marketing/home/cost";
import { Hero } from "@/components/marketing/home/hero";
import { HowItWorks } from "@/components/marketing/home/howItWorks";
import { LanguageAndTrade } from "@/components/marketing/home/languageAndTrade";
import { ProblemAndPromise } from "@/components/marketing/home/problemAndPromise";
import { Questions } from "@/components/marketing/home/questions";
import { TeamReceives } from "@/components/marketing/home/teamReceives";
import { Trust } from "@/components/marketing/home/trust";
import { WhatItDoes } from "@/components/marketing/home/whatItDoes";
import { fetchPublicRateCard } from "@/lib/api/rateCard";
import { publicPageMetadata } from "@/lib/seo/metadata";
import { SITE_DESCRIPTION } from "@/lib/seo/structuredData";

/**
 * THE HOMEPAGE MUST EXPORT ITS OWN `metadata`. Without it the page inherits the root
 * layout's fallback, and `/` and `/signup` both reach search engines titled "Calevate" with
 * the description "AI phone agents for Indian businesses". Two
 * public pages sharing a title and a description is a duplicate-content signal on the two
 * pages that matter most, and it was invisible because nothing renders a `<title>` where a
 * person doing the work would see it.
 *
 * The description is `SITE_DESCRIPTION`, which is the hero's own sentence — not a second
 * description of the product written for robots. `publicLanding.test.tsx` already holds
 * that sentence to this company's claim rules; a separate one would be a claim nothing
 * checks.
 */
export const metadata: Metadata = publicPageMetadata({
  path: "/",
  title: "Calevate — AI phone agents for Indian businesses",
  description: SITE_DESCRIPTION,
});

/**
 * Root of `app.calevate.tech` — one of exactly two screens a stranger can reach.
 *
 * ## Every line here is a promise, so every line is one the product already keeps
 *
 * Name a behaviour that is enforced in code today, or leave it out. Each chapter component
 * carries, in its own header, the shipped surface behind every sentence in it. What is
 * deliberately ABSENT, because a redesign is exactly when absences get quietly reinstated:
 *
 * - **No prices, with ONE exception.** D-11's managed pricing is negotiated per client. The
 *   ROI calculator shows the published self-serve rates as the INPUT to a comparison the
 *   buyer drives — and those rates are FETCHED from `GET /v1/public/rate-card` below, never
 *   typed (D-545, D-547). `publicLanding.test.tsx` bans a price everywhere else.
 * - **No customer counts, logos, testimonials or case studies.** There is no client #1 in
 *   production (ROADMAP M2); the founder's decision of 5 Sep 2026 is that the proof section
 *   is OMITTED rather than filled with placeholders.
 * - **No uptime, latency, accuracy or quality figures** — including inside the product
 *   mockups, which are drawn in skeleton bars precisely so they show the SHAPE of a screen
 *   without stating a number about it (`home/mockups/kit.tsx`).
 * - **No data-residency, storage-location or certification claim.** The trust chapter
 *   reuses `lib/marketing/compliance.ts` verbatim.
 *
 * ## The shape of the page
 *
 * A product page: a centred promise with the product drawn full width under it, then
 * chapters that SHOW a screen beside the sentence it proves —
 *
 *   hero → the problem · what changes → how it works → what it does →
 *   language · trade → what your team receives · your sales team → what it costs →
 *   trust → questions → closing
 *
 * Three bands are `anchor` weight and carry the argument (what changes, what your team
 * receives, what it costs); `home/band.tsx` is where the ranking and the type scale live.
 *
 * ## Motion
 *
 * `SmoothScroll` installs Lenis and the shared GSAP ticker (D-161). All of it is an
 * enhancement: content renders visible and is animated FROM a displaced state, so a failed
 * bundle or a reader who asked for reduced motion gets the same page, immediately. Section
 * headings reveal once on scroll; each mockup enters as ONE staggered group
 * (`home/mockups/stage.tsx`) rather than every element animating on its own, and its
 * ambient loops pause while it is off screen. `data-marketing-root` is what lets
 * `globals.css` hand the document its scrollbar back without reaching the app shells.
 */
export default async function Home() {
  // THE CARD IS FETCHED HERE, ONCE, AND HANDED DOWN. The calculator is the only thing on
  // this page that prices anything, and it must price from the live rate rather than a
  // number typed into the bundle (D-545). `null` is a first-class answer: the calculator
  // renders "the comparison cannot run right now" rather than a stale figure.
  //
  // No `try` around it — `fetchPublicRateCard` never throws; it logs and returns null. A
  // `catch` here would be a second way to say the same thing, and the one that drifts.
  const rateCard = await fetchPublicRateCard();

  return (
    <MarketingPage>
      <Hero />
      <ProblemAndPromise />
      <HowItWorks />
      <WhatItDoes />
      <LanguageAndTrade />
      <TeamReceives />
      <Cost rateCard={rateCard} />
      <Trust />
      <Questions />
      <Closing devSlug={process.env.NEXT_PUBLIC_DEV_ORG_SLUG} />
    </MarketingPage>
  );
}
