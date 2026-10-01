import type { Metadata } from "next";
import Link from "next/link";

import { ArrowRight } from "lucide-react";

import {
  CARD_LINK,
  MarketingPage,
  NUDGE_ARROW,
  SHELL,
} from "@/components/marketing/pageShell";
import { publicPageMetadata } from "@/lib/seo/metadata";

import { LEGAL_DOCUMENTS } from "@/lib/legal";
import { PendingReviewBanner, PRINT_WITHOUT_CHROME } from "@/lib/legal/document";
import { documentVersionLabel } from "@/lib/legal/versions";

/**
 * The index of the published legal documents.
 *
 * One of a small number of screens a stranger can reach, and the one a payment gateway's
 * onboarding reviewer, a client's procurement team and a regulator all land on. It is
 * deliberately a list and nothing else: the documents say what they say, and a summary
 * page that paraphrases them would be a ninth document nobody maintains. Each card shows
 * the document's own one-sentence summary and its current version, both read from the
 * document set rather than written here.
 */
export const metadata: Metadata = publicPageMetadata({
  path: "/legal",
  title: "Legal — Calevate",
  description:
    "Calevate's privacy policy, terms of service, acceptable use policy, data " +
    "processing addendum, sub-processor list, refund policy, grievance redressal and " +
    "cookie notice.",
});

export default function LegalIndexPage() {
  return (
    // The real site header, for `lib/legal/document.tsx`'s reason: this index is a public
    // page and a reader who lands on it should not lose the rest of the site.
    <MarketingPage>
      {/* A div: `MarketingPage` renders the page's one `<main>` landmark. The shell and
          the masthead match the document reader's, so moving between the index and a
          document does not step sideways. */}
      <div className={PRINT_WITHOUT_CHROME}>
        <div className="border-b border-line">
          <div className={`${SHELL} pt-10 pb-10 sm:pt-16 sm:pb-14`}>
            <PendingReviewBanner />

            <h1 className="text-[2.25rem] leading-[1.08] font-semibold tracking-tight text-balance text-ink sm:text-5xl sm:leading-[1.05]">
              Legal
            </h1>
            <p className="mt-5 max-w-[68ch] text-lg text-pretty text-ink-muted sm:text-xl">
              Calevate supplies AI telephone agents to businesses in India. Which of
              these documents applies to you depends on whether you buy Calevate,
              work for a business that does, or received a call from one — each page
              says so at the top.
            </p>
          </div>
        </div>

        <div className={`${SHELL} py-10 sm:py-14 lg:py-16`}>
          <ul className="grid gap-4 sm:grid-cols-2 sm:gap-5">
            {LEGAL_DOCUMENTS.map((doc) => {
              const version = documentVersionLabel(doc.slug);
              return (
                <li key={doc.slug}>
                  <Link href={`/legal/${doc.slug}`} className={CARD_LINK}>
                    <h2 className="flex items-start justify-between gap-3 text-lg font-semibold text-ink sm:text-xl">
                      {doc.shortTitle}
                      <ArrowRight
                        aria-hidden
                        className={`${NUDGE_ARROW} mt-1.5 text-ink-faint group-hover:text-brand-strong`}
                      />
                    </h2>
                    <p className="mt-2 flex-1 text-[15px] leading-6 text-pretty text-ink-muted sm:text-base sm:leading-7">
                      {doc.summary}
                    </p>
                    {version !== null && (
                      <p className="mt-4 text-sm text-ink-faint tabular-nums">
                        Version {version}
                      </p>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </MarketingPage>
  );
}
