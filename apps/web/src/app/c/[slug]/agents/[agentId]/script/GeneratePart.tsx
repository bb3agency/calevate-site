"use client";

import { useEffect, useRef, useState } from "react";

import { TEXT_ACTION } from "@/components/console/section";
import { PRIMARY_BUTTON_SM, SECONDARY_BUTTON_SM } from "@/components/ui";
import { INSTRUCTION_MAX } from "@/lib/api/campaignWorkspace";

export type GeneratePartProps = {
  /** The languages Pip may write in, the first chosen to start. */
  languages: { tag: string; name: string }[];
  initial: string;
  /** `instruction`: what the owner asked Pip to change in it, when they typed one. */
  onGenerate: (part: string, language: string, instruction?: string) => void;
  /** Why Generate waits (a draft being written), or nothing. */
  reason?: string;
};

/**
 * "Write it in [language]" beside a part's Edit: Pip rewrites that part only, for review.
 * "Ask Pip to change it" opens one short box for what to change ("make it warmer"), sent
 * with the same rewrite (D-1004).
 */
export function GeneratePart({
  languages,
  initial,
  onGenerate,
  reason,
  what,
  sendAs,
  held,
}: GeneratePartProps & {
  /** The part's name on screen. */
  what: string;
  /** The name Pip is asked for the part by, when it is not the one on screen (`PARTS.asks`). */
  sendAs?: string;
  held?: string;
}) {
  const part = sendAs ?? what;
  const [language, setLanguage] = useState(initial);
  const [asking, setAsking] = useState(false);
  const [instruction, setInstruction] = useState("");
  // The box takes the focus when it opens, so the owner types straight away.
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (asking) box.current?.focus();
  }, [asking]);
  const waits = held ?? reason;
  const languageName = languages.find((l) => l.tag === language)?.name ?? language;
  const boxId = `change-${what.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-4 gap-y-2 text-meta">
      <span className="inline-flex items-center gap-1.5">
        <button
          type="button"
          className={`${TEXT_ACTION} text-meta disabled:opacity-50`}
          disabled={Boolean(waits)}
          title={waits}
          aria-label={`Write ${what} in ${languageName}`}
          onClick={() => onGenerate(part, language)}
        >
          Write it in
        </button>
        <select
          aria-label={`Language for ${what}`}
          className="rounded border border-line bg-surface px-1.5 py-0.5 text-meta text-ink"
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
        >
          {languages.map((l) => (
            <option key={l.tag} value={l.tag}>
              {l.name}
            </option>
          ))}
        </select>
      </span>
      {!asking ? (
        <button
          type="button"
          className={`${TEXT_ACTION} text-meta disabled:opacity-50`}
          disabled={Boolean(waits)}
          title={waits}
          aria-label={`Ask Pip to change ${what}`}
          onClick={() => setAsking(true)}
        >
          Ask Pip to change it
        </button>
      ) : (
        <span className="flex w-full flex-wrap items-center gap-2">
          <label htmlFor={boxId} className="sr-only">
            What should Pip change in {what}?
          </label>
          <input
            id={boxId}
            ref={box}
            type="text"
            maxLength={INSTRUCTION_MAX}
            placeholder="For example: make it warmer"
            className="min-w-0 flex-1 basis-full rounded border border-line bg-surface px-2 py-1 text-meta text-ink sm:basis-0"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && instruction.trim() && !waits) onGenerate(part, language, instruction.trim());
              if (e.key === "Escape") setAsking(false);
            }}
          />
          <button
            type="button"
            className={PRIMARY_BUTTON_SM}
            disabled={Boolean(waits) || !instruction.trim()}
            title={waits}
            onClick={() => onGenerate(part, language, instruction.trim())}
          >
            Rewrite
          </button>
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setAsking(false)}>
            Cancel
          </button>
        </span>
      )}
    </span>
  );
}
