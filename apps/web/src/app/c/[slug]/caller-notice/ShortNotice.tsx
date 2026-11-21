"use client";

import { useEffect, useState } from "react";

import { CopyButton } from "@/components/interior/copy-button";
import { NOTICE_BAR, NOTICE_BASE, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { useShortNotice, type NoticeLanguage } from "@/lib/api/compliancePack";
import { type Session } from "@/lib/api/client";
import { endonym } from "@/lib/languageNames";
import { fill, toPlainText, type BlankValues } from "@/lib/noticeDraft/blanks";

import { downloadText } from "./download";
import { SHORT_NOTICE_COPY as COPY } from "./copy";

/** Before the first answer arrives only English is known to exist. */
const ENGLISH_ONLY = [{ code: "en", name: "English" }];

/**
 * The short notice (D-943) in English and each language the server has its lines in
 * (`ShortNoticeOut.languages`): the version a caller actually reads. Each language is named
 * in its own script where the founder's data has the name. The words are the server's; the
 * blanks are filled from the same values as the full draft above, so a business name typed
 * once fills both. Copy, download and a WhatsApp share carry the FILLED text; the
 * disclaimer stays on screen.
 */
export function ShortNotice({ session, values }: { session: Session; values: BlankValues }) {
  const [language, setLanguage] = useState<NoticeLanguage>("en");
  const notice = useShortNotice(session, language);
  // Kept across a language switch, so the choices stay on screen while the next one loads.
  const [offered, setOffered] = useState(ENGLISH_ONLY);
  const answered = notice.data?.languages;
  useEffect(() => {
    if (answered) setOffered(answered);
  }, [answered]);
  const languages = (answered ?? offered).map(({ code, name }) => ({
    value: code,
    label: endonym(code) ?? name,
  }));
  const filled = notice.data ? toPlainText(fill(notice.data.notice_markdown, values)) : "";

  return (
    <section aria-labelledby="short-notice-heading" className="space-y-3">
      <h2 id="short-notice-heading" className="text-heading text-ink">
        {COPY.heading}
      </h2>
      <div role="radiogroup" aria-label={COPY.languageLabel} className="flex flex-wrap gap-2">
        {languages.map((option) => (
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
