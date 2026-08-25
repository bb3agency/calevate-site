"use client";

/**
 * THE STRUCTURED SECTIONS — opening line, steps, Q&A, end-call rules, and the raw escape.
 *
 * Split out of `ScriptBuilder.tsx` (UX-DOCTRINE §6): the builder was 737 lines carrying
 * the data plumbing, the save/apply/undo ladder, the AI assist AND five field editors. The
 * five editors are one subject — "what the author types" — and none of them reads the
 * network: each takes a value and hands back the next one, which is what lets the builder
 * shell own every write in one place.
 *
 * Every control takes `trackFocus`, which records the last text field the author touched
 * so the "insert a merge field" buttons drop the token at their cursor rather than into a
 * fixed box. That is why these are not self-contained.
 */

import { useRef } from "react";
import { GripVertical, Plus, Trash2, X } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import type { FaqEntry, ScriptStep } from "@/lib/api/script";

/** The two text controls a merge field can be inserted into. */
export type Focusable = HTMLInputElement | HTMLTextAreaElement;

export function VariableBar({
  standard,
  custom,
  onInsert,
}: {
  standard: { key: string; label: string }[];
  custom: { key: string; label: string }[];
  onInsert: (key: string) => void;
}) {
  const all = [...standard, ...custom.filter((c) => !standard.some((s) => s.key === c.key))];
  return (
    <div>
      <span className={FIELD_LABEL}>Insert a merge field</span>
      <span className={FIELD_HINT}>
        Click a field to drop it where your cursor is. It is filled in from the lead when the
        call is placed; if there is no value, it simply disappears.
      </span>
      <div className="mt-2 flex flex-wrap gap-2">
        {all.map((v) => (
          <button
            key={v.key}
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => onInsert(v.key)}
          >
            <Plus aria-hidden className="h-3 w-3" />
            {v.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function OpeningSection({
  value,
  onChange,
  trackFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  trackFocus: (el: Focusable | null) => void;
}) {
  return (
    <section>
      <label className={FIELD_LABEL} htmlFor="opening-line">
        Opening line
      </label>
      <span className={FIELD_HINT}>
        What the agent says after it introduces itself. The AI/recording notice is spoken
        first automatically — this follows it.
      </span>
      <textarea
        id="opening-line"
        className={FIELD}
        rows={2}
        value={value}
        onFocus={(e) => trackFocus(e.currentTarget)}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Namaste! How can I help you today?"
      />
    </section>
  );
}

export function StepsSection({
  steps,
  onChange,
  trackFocus,
}: {
  steps: ScriptStep[];
  onChange: (steps: ScriptStep[]) => void;
  trackFocus: (el: Focusable | null) => void;
}) {
  const dragFrom = useRef<number | null>(null);

  const move = (from: number, to: number) => {
    if (to < 0 || to >= steps.length) return;
    const next = [...steps];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    onChange(next);
  };
  const update = (i: number, instruction: string) =>
    onChange(steps.map((s, idx) => (idx === i ? { instruction } : s)));
  const remove = (i: number) => onChange(steps.filter((_, idx) => idx !== i));
  const add = () => onChange([...steps, { instruction: "" }]);

  return (
    <section>
      <span className={FIELD_LABEL}>Steps</span>
      <span className={FIELD_HINT}>
        A loose outline the agent follows, one thing at a time. Drag the handle to reorder,
        or use the up/down buttons.
      </span>
      <ol className="mt-3 space-y-3">
        {steps.map((step, i) => (
          <li
            key={i}
            className="flex items-start gap-2 rounded-md border border-line bg-surface p-2"
            draggable
            onDragStart={() => (dragFrom.current = i)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => {
              if (dragFrom.current !== null) move(dragFrom.current, i);
              dragFrom.current = null;
            }}
          >
            <span
              aria-hidden
              className="mt-2 cursor-grab text-ink-faint"
              title="Drag to reorder"
            >
              <GripVertical className="h-4 w-4" />
            </span>
            <span className="mt-2 w-5 shrink-0 text-center text-xs font-semibold text-ink-muted">
              {i + 1}
            </span>
            <textarea
              className={`${FIELD} mt-0`}
              rows={2}
              value={step.instruction}
              aria-label={`Step ${i + 1}`}
              onFocus={(e) => trackFocus(e.currentTarget)}
              onChange={(e) => update(i, e.target.value)}
              placeholder="Ask what the caller needs and confirm it back."
            />
            <div className="mt-1 flex flex-col gap-1">
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                aria-label={`Move step ${i + 1} up`}
                disabled={i === 0}
                onClick={() => move(i, i - 1)}
              >
                ↑
              </button>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                aria-label={`Move step ${i + 1} down`}
                disabled={i === steps.length - 1}
                onClick={() => move(i, i + 1)}
              >
                ↓
              </button>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                aria-label={`Remove step ${i + 1}`}
                onClick={() => remove(i)}
              >
                <Trash2 aria-hidden className="h-3.5 w-3.5" />
              </button>
            </div>
          </li>
        ))}
      </ol>
      <button type="button" className={`${SECONDARY_BUTTON_SM} mt-3`} onClick={add}>
        <Plus aria-hidden className="h-3.5 w-3.5" />
        Add step
      </button>
    </section>
  );
}

export function FaqSection({
  faqs,
  fallback,
  onFaqs,
  onFallback,
  trackFocus,
}: {
  faqs: FaqEntry[];
  fallback: string;
  onFaqs: (faqs: FaqEntry[]) => void;
  onFallback: (v: string) => void;
  trackFocus: (el: Focusable | null) => void;
}) {
  const update = (i: number, patch: Partial<FaqEntry>) =>
    onFaqs(faqs.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  const remove = (i: number) => onFaqs(faqs.filter((_, idx) => idx !== i));
  const add = () => onFaqs([...faqs, { question: "", answer: "" }]);

  return (
    <section>
      <span className={FIELD_LABEL}>Questions &amp; answers</span>
      <span className={FIELD_HINT}>
        The agent answers these ONLY from what you write here. For anything else it uses the
        don&apos;t-know reply below rather than guessing.
      </span>
      <div className="mt-3 space-y-3">
        {faqs.map((faq, i) => (
          <div key={i} className="rounded-md border border-line bg-surface p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-ink-muted">Q&amp;A {i + 1}</span>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                aria-label={`Remove question ${i + 1}`}
                onClick={() => remove(i)}
              >
                <X aria-hidden className="h-3.5 w-3.5" />
              </button>
            </div>
            <input
              className={FIELD}
              value={faq.question}
              aria-label={`Question ${i + 1}`}
              onFocus={(e) => trackFocus(e.currentTarget)}
              onChange={(e) => update(i, { question: e.target.value })}
              placeholder="What are your opening hours?"
            />
            <textarea
              className={FIELD}
              rows={2}
              value={faq.answer}
              aria-label={`Answer ${i + 1}`}
              onFocus={(e) => trackFocus(e.currentTarget)}
              onChange={(e) => update(i, { answer: e.target.value })}
              placeholder="We are open 9 to 6, Monday to Saturday."
            />
          </div>
        ))}
      </div>
      <button type="button" className={`${SECONDARY_BUTTON_SM} mt-3`} onClick={add}>
        <Plus aria-hidden className="h-3.5 w-3.5" />
        Add question
      </button>
      <div className="mt-4">
        <label className={FIELD_LABEL} htmlFor="faq-fallback">
          When the agent does not know
        </label>
        <textarea
          id="faq-fallback"
          className={FIELD}
          rows={2}
          value={fallback}
          onFocus={(e) => trackFocus(e.currentTarget)}
          onChange={(e) => onFallback(e.target.value)}
        />
      </div>
    </section>
  );
}

export function EndCallSection({
  rules,
  onChange,
  trackFocus,
}: {
  rules: string[];
  onChange: (rules: string[]) => void;
  trackFocus: (el: Focusable | null) => void;
}) {
  return (
    <section>
      <span className={FIELD_LABEL}>Ending a call</span>
      <span className={FIELD_HINT}>
        The agent always ends politely once the caller&apos;s need is handled. Add any extra
        rules of your own, one per line.
      </span>
      <textarea
        className={FIELD}
        rows={3}
        value={rules.join("\n")}
        aria-label="Extra end-call rules, one per line"
        onFocus={(e) => trackFocus(e.currentTarget)}
        onChange={(e) => onChange(e.target.value.split("\n"))}
        placeholder={"Never promise a same-day appointment.\nAlways offer a callback if unsure."}
      />
    </section>
  );
}

export function RawEditor({
  value,
  onChange,
  trackFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  trackFocus: (el: Focusable | null) => void;
}) {
  return (
    <section>
      <NoticeBox tone="neutral" title="Raw editing" className="mb-3">
        You are editing the script as plain text. The platform still adds the AI/recording
        answer underneath — you cannot remove it. Switch back to the structured builder any
        time.
      </NoticeBox>
      <textarea
        className={`${FIELD} font-mono`}
        rows={16}
        value={value}
        aria-label="Raw script text"
        onFocus={(e) => trackFocus(e.currentTarget)}
        onChange={(e) => onChange(e.target.value)}
      />
    </section>
  );
}
