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
 * ⚠ THE HOMEPAGE HAD NO `metadata` EXPORT AT ALL until 9 Sep 2026, which meant it
 * inherited the root layout's fallback — so `/` and `/signup` both went to search engines
 * titled "Calevate" with the description "AI phone agents for Indian businesses". Two
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
 * This rule predates every redesign and survives this one unchanged: name a behaviour that
 * is enforced in code today, or leave it out. The 9 Sep 2026 redesign re-RANKED the page
 * and re-GROUPED it, and the density pass that followed the same day re-SCALED it; between
 * them they did not add a single claim, and they did not delete one — the rendered text of
 * `<main>` is byte-identical across both. Each chapter
 * component below carries, in its own header, the shipped surface behind every sentence in
 * it. What is still deliberately ABSENT, because the absences are the load-bearing part and
 * a rewrite is exactly when they get quietly reinstated:
 *
 * - **No prices, with ONE deliberate exception.** D-11's managed pricing is negotiated per
 *   client, so no plan price appears. The exception is the ROI calculator: it shows the
 *   published self-serve rates as the INPUT to a comparison the buyer drives with their own
 *   numbers — a tool, not a tag. Those rates are FETCHED, never typed: this module awaits
 *   `GET /v1/public/rate-card` and hands the card to `Cost`, which refuses to run the
 *   comparison at all if the card cannot be loaded (D-545, reshaped by D-547).
 *   `publicLanding.test.tsx` scopes its price/percent bans off that one section and keeps
 *   them everywhere else, and `homepageStructure` bans a typed rupee figure from every
 *   source file this page is built from.
 * - **No customer counts, logos, testimonials or case studies.** There is no client #1 in
 *   production (ROADMAP M2). The founder's decision of 5 Sep 2026 is that the proof section
 *   is OMITTED rather than filled with placeholders.
 * - **No uptime, latency, accuracy or quality figures.** The testing band is a LIST of the
 *   scenarios an agent is run against and carries no score of any kind; D-36 records Telugu
 *   extraction quality as UNMEASURED until task #87 scores it.
 * - **No turnaround promise, and no integration logos.**
 * - **No data-residency, storage-location or certification claim.** The trust chapter names
 *   which leg is Indian and which is not (Azure OpenAI in East US 2 since D-449) and says
 *   the region is confirmed by a person, not proved by a build. Those sentences are REUSED
 *   VERBATIM from `lib/marketing/compliance.ts` rather than rewritten.
 *
 * ## THE SHAPE OF THE PAGE, AND WHAT THE REDESIGN CHANGED
 *
 * It was THIRTEEN numbered bands of identical visual weight — same eyebrow with a running
 * index, same `text-3xl sm:text-4xl` heading, same hairline, two backgrounds alternating.
 * A running number tells a reader this is a DOCUMENT to be read in order; a landing page is
 * scanned. Nothing was emphasised, so nothing landed, and the page measured 12,841px on a
 * desktop with no band louder than any other anywhere down it.
 *
 * It is now EIGHT chapters. A chapter is a tonal ground and a subject; two of them carry a
 * second, visibly quieter band where the second is a supporting move on the same subject
 * rather than a new topic. Three bands are `anchor`-weight and they are the argument —
 * **what changes**, **what your team receives**, **what it costs**; everything else is
 * `standard` or `quiet`. Four grounds instead of two, including one dark chapter around the
 * only place the product itself is on screen. `components/marketing/home/band.tsx` is where
 * that model is written down, and the numbering is gone.
 *
 *   the problem → what changes · how it works · what it does ·
 *   your language and your trade · what your team receives · what it costs ·
 *   trust · questions
 *
 * ## AND THEN THE DENSITY PASS, WHICH IS THE HALF THE RANKING DID NOT FIX
 *
 * Ranking the bands did not change what a reader meets INSIDE one, and the founder said so
 * after comparing the result against a competitor's landing page. Measured on the ranked
 * page at 1440×900: 12,263px over 13.6 screenfuls, with body copy at 14px in 58 paragraphs
 * and 12px in 51 — the console's density, on the page a stranger reads once. So: a named
 * type and space scale in `home/band.tsx` (`HOME`), body copy at 18–20px, chapter padding
 * at 96/128/160px, and every dense grid decided one at a time — the three problems and the
 * three steps became full-width rows, the six capabilities went three-up to two-up, the
 * three qualification cards became one panel of three rows, the trust cards stacked, and
 * the lead inbox stopped being 1.35fr of a shell so the product is drawn at the size it is
 * meant to be read at. The page is 18,526px now and that is the intended direction: length
 * is not the defect, a screenful you cannot parse is.
 *
 * NOTHING TRUE WAS DROPPED. Six bands became three chapters by joining pairs that were
 * always one argument — the problem and its answer; the three steps and the before/after
 * they illustrate; the leads screen and what a shortlist does to a sales day; the headcount
 * comparison and the part it cannot see; the language argument and the trade field lists.
 *
 * ## Why this file is eleven imports and a fetch
 *
 * UX-DOCTRINE §6: a route module's budget is 150 lines, it may export only `default`
 * (D-196), and so it cannot be split by extraction — the screen moves out and the route
 * keeps the chrome. This file was 1,258 lines, which is §6's stated smell exactly: "a big
 * file is a hierarchy nobody could see", and thirteen equal bands is what accumulates in
 * one. Each chapter is now a module named for its SUBJECT, with the evidence for its claims
 * in its own header where the next editor of that chapter will read it.
 *
 * ## Motion
 *
 * `SmoothScroll` installs Lenis and the shared GSAP ticker (D-161). All of it is an
 * enhancement: content renders visible and is animated FROM a displaced state, so a failed
 * bundle or a reader who asked for reduced motion gets the same page, immediately. The hero
 * figure is CSS-only for the same reason and one more (`heroCallSim.tsx`).
 * `data-marketing-root` is what lets `globals.css` hand the document its scrollbar back and
 * paint the marketing-only visual tokens without either rule reaching the fixed app shells
 * under /c and /admin.
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
