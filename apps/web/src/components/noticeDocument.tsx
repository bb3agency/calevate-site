"use client";

import { forwardRef, type ReactNode } from "react";

import { lookup } from "@/lib/lookup";

import { blankLabel, valueOf, type BlankValues } from "@/lib/noticeDraft/blanks";
import type { Block, Inline } from "@/lib/noticeDraft/blocks";

/**
 * The draft as a document: a sheet of paper, the server's words, and the blanks as fields.
 *
 * The paper is white with slate ink rather than theme tokens, for `invoiceDocument.tsx`'s
 * reason: the same sheet is printed, and a themed sheet prints blank in dark mode. It lives
 * here beside that file, rather than in the caller-notice route, because it is the same
 * exception: paper that must look the same on every screen and on the printer.
 *
 * Each blank is a real field named by its own wording. Every occurrence of a blank is
 * bound to the same value, so the business name typed in the title also fills "Who is
 * responsible". `data-blank` marks the field's wrapper so the print copy can swap each
 * field for its filled text (`printableClone`): a cloned input does not carry its value.
 */
export const NoticeDocument = forwardRef<
  HTMLElement,
  { blocks: Block[]; values: BlankValues; onChange: (key: string, value: string) => void }
>(function NoticeDocument({ blocks, values, onChange }, ref) {
  const render = (parts: Inline[]): ReactNode[] =>
    parts.map((part, i) => {
      if (part.kind === "text") return part.text;
      if (part.kind === "strong") return <strong key={i} className="font-semibold">{render(part.parts)}</strong>;
      return <BlankField key={i} blankKey={part.key} raw={part.raw} values={values} onChange={onChange} />;
    });

  return (
    <article
      ref={ref}
      aria-label="Draft privacy notice"
      className="mx-auto w-full max-w-[46rem] rounded-sm border border-slate-200 bg-white px-5 py-8 font-serif text-[16px] leading-[1.7] text-slate-900 shadow-raised sm:px-12 sm:py-14 print:max-w-none print:border-0 print:p-0 print:shadow-none"
    >
      <div aria-hidden className="mb-6 flex justify-end">
        <p className="rotate-[-3deg] rounded-sm border-2 border-danger/70 px-2 py-0.5 font-sans text-[11px] font-semibold tracking-wide text-danger sm:text-[12px]">
          Draft for your advocate&rsquo;s review
        </p>
      </div>
      <div className="space-y-4">
        {blocks.map((block, i) => {
          switch (block.kind) {
            case "heading":
              return block.level === 1 ? (
                <h2 key={i} className="pt-4 font-serif text-[26px] font-semibold leading-tight tracking-tight text-slate-900 sm:text-[30px]">
                  {render(block.parts)}
                </h2>
              ) : (
                <h3 key={i} className="pt-4 font-serif text-[19px] font-semibold leading-snug text-slate-900">
                  {render(block.parts)}
                </h3>
              );
            case "quote":
              return (
                <blockquote key={i} className="border-l-2 border-slate-300 pl-4 font-sans text-[13px] leading-relaxed text-slate-600">
                  <p>{render(block.parts)}</p>
                </blockquote>
              );
            case "list":
              return (
                <ul key={i} className="list-disc space-y-1.5 pl-6 marker:text-slate-400">
                  {block.items.map((item, j) => (
                    <li key={j}>{render(item)}</li>
                  ))}
                </ul>
              );
            default:
              return <p key={i}>{render(block.parts)}</p>;
          }
        })}
      </div>
    </article>
  );
});

/** A blank of more than this many characters is a sentence to write, not a name to type. */
const LONG_BLANK = 60;

function BlankField({
  blankKey,
  raw,
  values,
  onChange,
}: {
  blankKey: string;
  raw: string;
  values: BlankValues;
  onChange: (key: string, value: string) => void;
}) {
  const value = lookup(values, blankKey) ?? "";
  const filled = valueOf(values, blankKey) !== null;
  const tone = filled
    ? "border-slate-400 border-dotted bg-transparent"
    : "border-warn-line bg-warn-soft placeholder:text-warn";
  const common = `rounded-sm border-0 border-b-2 px-1 font-sans text-[15px] text-slate-900 transition-colors duration-(--duration-fast) focus:outline-none focus-visible:ring-2 focus-visible:ring-brand motion-reduce:transition-none ${tone}`;

  return (
    <span data-blank={blankKey} data-raw={raw} className={blankKey.length > LONG_BLANK ? "my-1 block" : "inline"}>
      {blankKey.length > LONG_BLANK ? (
        <textarea
          aria-label={blankLabel(blankKey)}
          data-blank-field={blankKey}
          value={value}
          placeholder={blankKey}
          rows={3}
          onChange={(event) => onChange(blankKey, event.target.value)}
          className={`${common} block w-full resize-y py-1 leading-snug field-sizing-content touch:text-base`}
        />
      ) : (
        <input
          aria-label={blankLabel(blankKey)}
          data-blank-field={blankKey}
          value={value}
          placeholder={blankKey}
          size={Math.max(6, Math.min(LONG_BLANK, (value || blankKey).length + 1))}
          onChange={(event) => onChange(blankKey, event.target.value)}
          className={`${common} inline max-w-full py-0 align-baseline field-sizing-content touch:min-h-11 touch:text-base`}
        />
      )}
    </span>
  );
}

/**
 * A copy of the sheet for printing, with every field replaced by what it holds: the typed
 * value as plain text, or the blank exactly as the server wrote it, highlighted.
 */
export function printableClone(sheet: HTMLElement, values: BlankValues): HTMLElement {
  const clone = sheet.cloneNode(true) as HTMLElement;
  for (const holder of Array.from(clone.querySelectorAll<HTMLElement>("[data-blank]"))) {
    const key = holder.dataset.blank ?? "";
    const filled = valueOf(values, key);
    const out = document.createElement(filled ? "span" : "mark");
    out.textContent = filled ?? holder.dataset.raw ?? "";
    out.className = filled ? "whitespace-pre-wrap" : "bg-warn-soft px-0.5 font-sans text-[0.9em]";
    holder.replaceWith(out);
  }
  return clone;
}
