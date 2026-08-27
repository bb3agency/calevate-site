import type { Metadata } from "next";
import Link from "next/link";

import { LEGAL_DOCUMENTS } from "@/lib/legal";
import { PendingReviewBanner } from "@/lib/legal/document";

/**
 * The index of the published legal documents.
 *
 * One of a small number of screens a stranger can reach, and the one a payment gateway's
 * onboarding reviewer, a client's procurement team and a regulator all land on. It is
 * deliberately a list and nothing else: the documents say what they say, and a summary
 * page that paraphrases them would be a ninth document nobody maintains.
 */
export const metadata: Metadata = {
  title: "Legal — Calevate",
  description:
    "Calevate's privacy policy, terms of service, acceptable use policy, data " +
    "processing addendum, sub-processor list, refund policy, grievance redressal and " +
    "cookie notice.",
};

export default function LegalIndexPage() {
  return (
    <div className="bg-app">
      <header className="border-b border-line bg-surface/85">
        <div className="mx-auto w-full max-w-3xl px-4 sm:px-6 lg:max-w-5xl xl:max-w-6xl 2xl:max-w-[88rem] flex items-center justify-between gap-4 py-4">
          <Link href="/" className="text-sm font-semibold text-ink">
            Calevate
          </Link>
        </div>
      </header>

      {/* The same shell as the document reader (`lib/legal/document.tsx`), spelled the
          same way, so the index and the pages it links to do not step sideways as a
          reader moves between them. */}
      <main className="mx-auto w-full max-w-3xl px-4 sm:px-6 lg:max-w-5xl xl:max-w-6xl 2xl:max-w-[88rem] py-10">
        <PendingReviewBanner />

        <h1 className="mt-8 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
          Legal
        </h1>
        <p className="mt-3 text-[15px] leading-7 text-ink-muted">
          Calevate supplies AI telephone agents to businesses in India. Which of these
          documents applies to you depends on whether you buy Calevate, work for a
          business that does, or received a call from one — each page says so at the top.
        </p>

        <ul className="mt-8 space-y-3">
          {LEGAL_DOCUMENTS.map((doc) => (
            <li key={doc.slug}>
              <Link
                href={`/legal/${doc.slug}`}
                className="block rounded-card border border-line bg-surface p-5 hover:border-brand"
              >
                <span className="text-[17px] font-semibold text-ink">{doc.shortTitle}</span>
                <span className="mt-1 block text-sm leading-6 text-ink-muted">
                  {doc.summary}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </main>

      <footer className="border-t border-line px-4 py-8 sm:px-6">
        <p className="mx-auto w-full max-w-3xl px-4 sm:px-6 lg:max-w-5xl xl:max-w-6xl 2xl:max-w-[88rem] text-xs text-ink-faint">
          Calevate — AI phone agents for Indian businesses.
        </p>
      </footer>
    </div>
  );
}
