import { IndustryTabs } from "@/components/marketing/industryTabs";
import { Reveal } from "@/components/marketing/motion";
import { Band, Chapter, HOME } from "./band";

/**
 * CHAPTER 4 — your language, your trade. BANDS 07 AND 08, ON THE ONE GROUND THEY SHARE.
 *
 * These were the furthest-apart bands on the old page (verticals at 07, Telugu at 08, with
 * a rule and a colour flip between them) and they are the same argument: *this is built for
 * YOUR context, not for a generic buyer*. A clinic in Guntur is being asked to believe two
 * things — that the agent will speak to their callers in Telugu, and that it will ask the
 * questions a clinic actually asks — and those two beliefs reinforce each other.
 *
 * ## Why this chapter is the one with a tinted ground
 *
 * Telugu-first is the positioning, and on the old page it was the least visible band on the
 * page: an unremarkable two-column at band 08, indistinguishable from "Before and after" at
 * 04. The brand tint is the cheapest way to say "this is the part that is ours" without
 * inventing a claim, and it is the only brand-coloured ground on the page apart from the
 * dark chapter, so it cannot become another alternating stripe.
 *
 * ## What is deliberately NOT said here
 *
 * No score for how well any language is understood. D-36 records Telugu extraction quality
 * as UNMEASURED until task #87 scores it, and `TESTED_SCENARIOS` publishes the LIST of test
 * calls with no rating of any kind. The paragraph that says so is kept verbatim.
 *
 * The vertical field lists are read from `scripts/seed.py`'s `VERTICAL_TEMPLATES` by
 * `industryTabs.tsx`, and `publicLanding.test.tsx` matches the rendered chips against the
 * seed's own labels — so a page advertising a column the product stopped shipping fails
 * rather than ships.
 */

/** The same question, in the three languages the product offers. */
const SAME_QUESTION: readonly { lang: string; label: string; text: string }[] = [
  { lang: "te", label: "తెలుగు", text: "రేపు డాక్టర్ గారు ఉంటారా?" },
  { lang: "hi", label: "हिन्दी", text: "क्या कल डॉक्टर उपलब्ध हैं?" },
  { lang: "en", label: "English", text: "Is the doctor available tomorrow?" },
];

export function LanguageAndTrade() {
  return (
    <Chapter tone="brand">
      <Band
        id="languages"
        eyebrow="Telugu-first"
        weight="standard"
        title="Your customers shouldn’t have to change language to reach you"
      >
        <div className={`${HOME.contentGap} grid gap-12 lg:grid-cols-2 lg:items-start lg:gap-16`}>
          <Reveal>
            <p className={`max-w-xl text-pretty text-ink-muted ${HOME.body}`}>
              Your callers do not switch to English for your convenience, and a
              receptionist who makes them is one they hang up on. A new agent is a Telugu
              agent until somebody changes it — that is the default in the database, not a
              suggestion in a guide — and the opening line, the script and the answers all
              move with the language it speaks.
            </p>
            {/* `-muted`, not `-faint`, and the GROUND is why. `--text-faint` is held to
                4.5:1 against `--surface` and `--app` only (`tests/contrastTokens.test.ts`
                computes exactly those two); on this chapter's brand tint it measures
                4.43:1 — axe in a real Chromium, 9 Sep 2026. The tier moves up rather than
                the tint being washed out to the ~25% that would rescue it, which would
                leave the chapter with no visible ground at all. */}
            <p className={`mt-8 max-w-xl text-ink-muted ${HOME.bodySm}`}>
              Three languages are offered, and only three, because those are the ones we
              are willing to put a client’s callers in front of. We publish no score for
              how well it understands any of them: a number we cannot show you the working
              for is worth nothing.
            </p>
          </Reveal>
          <Reveal delay={0.08} as="section" className={HOME.panel}>
            <h3 className={`${HOME.itemTitle} font-semibold text-balance text-ink`}>
              The same question, asked three ways
            </h3>
            <p className={`mt-2 text-ink-muted ${HOME.bodySm}`}>
              Your agent answers all three on the same number.
            </p>
            <ul className="mt-7 space-y-4">
              {SAME_QUESTION.map(({ lang, label, text }) => (
                <li key={lang} className="rounded-xl border border-line bg-app/60 px-5 py-4">
                  <p className="text-xs font-semibold tracking-wide text-ink-faint uppercase">
                    {label}
                  </p>
                  <p lang={lang} className="mt-1.5 text-xl text-ink sm:text-2xl">
                    {text}
                  </p>
                </li>
              ))}
            </ul>
            <p className={`mt-7 border-t border-line pt-5 text-ink-muted ${HOME.bodySm}`}>
              Each of them comes back to you as the same row: who rang, what they wanted,
              and when they can come in.
            </p>
          </Reveal>
        </div>
      </Band>

      <Band
        id="industries"
        eyebrow="Your line of work"
        weight="quiet"
        className={HOME.bandGap}
        title="It asks the questions your trade actually asks"
        lede="A clinic needs to know what hurts and how soon. A property office needs a budget and an area. These are the field lists a new agent starts from — and then you change them, because the columns are yours rather than ours."
      >
        <IndustryTabs />
        <Reveal delay={0.12}>
          <p className={`mt-10 max-w-2xl text-ink-muted ${HOME.bodySm}`}>
            Nothing is locked to a line of work. If yours is not one of these, you write the
            list of things the agent has to find out, and that is the whole setup — the same
            as it is for the four above.
          </p>
        </Reveal>
      </Band>
    </Chapter>
  );
}
