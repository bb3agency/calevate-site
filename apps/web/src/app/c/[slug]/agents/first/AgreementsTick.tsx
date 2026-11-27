"use client";

import { useId, useState } from "react";
import { Check, ChevronDown, ExternalLink } from "lucide-react";

import type { LegalDocumentState } from "@/lib/api/agreements";

/** The tick's key among Hear it's ticks. */
export const AGREEMENTS_TICK = "agreements";

/** "the Privacy Policy, the Terms and the Data Processing Addendum": the titles as one phrase. */
export function titlesPhrase(titles: readonly string[]): string {
  const named = titles.map((title) => `the ${title}`);
  if (named.length <= 1) return named.join("");
  return `${named.slice(0, -1).join(", ")} and ${named.at(-1)}`;
}

/**
 * THE AGREEMENTS AS ONE TICK (W1.5): one sentence naming every document still to accept, and
 * under it each document's name opening in place to say what it is, with the whole text a tap
 * further. One tick is one decision for the owner; the record is unchanged: the press still
 * accepts each document on its own, at its version, against the statement the server sent
 * (`HearItStep.ring`). The pledge and "this number is mine" are different promises and keep
 * their own ticks.
 *
 * The disclosures sit outside the `<label>`, because a button inside a label is a second
 * control in the checkbox's name and a tap on it would tick the box.
 */
export function AgreementsTick({
  docs,
  checked,
  onChange,
}: {
  docs: readonly LegalDocumentState[];
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const base = useId();
  const [open, setOpen] = useState<string | null>(null);
  return (
    <li className="px-4 py-3">
      <label className="flex min-w-0 cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          name="agree"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
          className="peer sr-only"
        />
        <span
          aria-hidden
          className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-[5px] border-[1.5px] transition-colors duration-(--duration-fast) peer-focus-visible:ring-2 peer-focus-visible:ring-brand peer-focus-visible:ring-offset-2 ${
            checked ? "border-brand-strong bg-brand-strong text-white" : "border-ink/30 bg-surface"
          }`}
        >
          {checked ? <Check className="h-3 w-3" strokeWidth={3} /> : null}
        </span>
        <span className="min-w-0 text-body text-ink">
          I accept {titlesPhrase(docs.map((doc) => doc.title))}
        </span>
      </label>
      <ul className="mt-1.5 flex flex-wrap gap-x-1 gap-y-1 pl-8">
        {docs.map((doc) => {
          const expanded = open === doc.slug;
          return (
            <li key={doc.slug}>
              <button
                type="button"
                aria-expanded={expanded}
                aria-controls={`${base}-${doc.slug}`}
                onClick={() => setOpen(expanded ? null : doc.slug)}
                className="press inline-flex min-h-8 items-center gap-1 rounded-md px-2 text-meta font-medium text-brand-strong hover:bg-brand/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
              >
                {doc.title}
                <ChevronDown
                  aria-hidden
                  className={`h-3.5 w-3.5 transition-transform duration-(--duration-fast) ${expanded ? "rotate-180" : ""}`}
                />
              </button>
            </li>
          );
        })}
      </ul>
      {docs.map((doc) =>
        open === doc.slug ? (
          <div
            key={doc.slug}
            id={`${base}-${doc.slug}`}
            className="mt-2 ml-8 rounded-md border border-line bg-surface-muted/60 px-3 py-2.5"
          >
            <p className="text-meta text-ink">{doc.headline}</p>
            <a
              href={doc.href}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-flex min-h-8 items-center gap-1 text-meta font-medium text-brand-strong underline underline-offset-2 touch:min-h-11"
            >
              <span>
                Read the {doc.title} in full<span className="sr-only"> (opens in a new tab)</span>
              </span>
              <ExternalLink aria-hidden className="h-3 w-3" />
            </a>
          </div>
        ) : null,
      )}
    </li>
  );
}
