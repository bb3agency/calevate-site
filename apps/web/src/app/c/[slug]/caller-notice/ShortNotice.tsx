"use client";

import { useState } from "react";

import { CopyButton } from "@/components/interior/copy-button";
import { NOTICE_BAR, NOTICE_BASE, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { useShortNotice, type NoticeLanguage } from "@/lib/api/compliancePack";
import { type Session } from "@/lib/api/client";
import { fill, toPlainText, type BlankValues } from "@/lib/noticeDraft/blanks";

import { downloadText } from "./download";
import { SHORT_NOTICE_COPY as COPY } from "./copy";

const LANGUAGES: { value: NoticeLanguage; label: string }[] = [
  { value: "en", label: "English" },
  { value: "te", label: "తెలుగు" },
  { value: "hi", label: "हिन्दी" },
];

/**
 * The short notice (D-943) in English, Telugu or Hindi: the version a caller actually
 * reads. The words are the server's; the blanks are filled from the same values as the
 * full draft above, so a business name typed once fills both. Copy, download and a
 * WhatsApp share carry the FILLED text; the disclaimer stays on screen.
 */
export function ShortNotice({ session, values }: { session: Session; values: BlankValues }) {
  const [language, setLanguage] = useState<NoticeLanguage>("en");
  const notice = useShortNotice(session, language);
  const filled = notice.data ? toPlainText(fill(notice.data.notice_markdown, values)) : "";

  return (
    <section aria-labelledby="short-notice-heading" className="space-y-3">
      <h2 id="short-notice-heading" className="text-section font-semibold text-ink">
        {COPY.heading}
      </h2>
      <div role="radiogroup" aria-label={COPY.languageLabel} className="flex flex-wrap gap-2">
        {LANGUAGES.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={language === option.value}
            onClick={() => setLanguage(option.value)}
            className={`${SECONDARY_BUTTON_SM} ${language === option.value ? "border-ink text-ink" : ""}`}
          >
            {option.label}
          </button>
        ))}
      </div>
      {notice.error ? (
        <ProblemNotice error={notice.error} />
      ) : !notice.data ? (
        <Skeleton rows={6} label={COPY.loading} />
      ) : (
        <>
          <p role="note" className={`${NOTICE_BASE} ${NOTICE_BAR.warn} text-meta leading-snug`}>
            {notice.data.disclaimer}
          </p>
          <div className="flex flex-wrap gap-2">
            <CopyButton value={filled} label={COPY.copy} variant="text" />
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => downloadText(filled, `privacy-notice-short-${language}.txt`, "text/plain")}
            >
              {COPY.download}
            </button>
            <a
              className={SECONDARY_BUTTON_SM}
              href={`https://wa.me/?text=${encodeURIComponent(filled)}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              {COPY.share}
            </a>
          </div>
          <pre
            lang={language}
            className="whitespace-pre-wrap break-words rounded-sm border border-line bg-surface p-4 font-sans text-body text-ink"
          >
            {filled}
          </pre>
        </>
      )}
    </section>
  );
}
