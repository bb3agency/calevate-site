"use client";

/**
 * HOW THE OWNER WANTS PIP TO WRITE THE SCRIPT (D-1004): a tone beside Generate, a note
 * behind "Add a note for Pip" (up to 1,000 characters), and a pointer to Sources when none
 * are picked, since Pip then has only the main task to work from and leaves out what it
 * cannot back.
 *
 * The tone and note go with this one request; nothing is saved on the campaign.
 */

import { useEffect, useRef, useState } from "react";

import { TEXT_ACTION } from "@/components/console/section";
import { FIELD, SECONDARY_BUTTON_SM } from "@/components/ui";
import { INSTRUCTION_MAX, type ScriptAsk } from "@/lib/api/campaignWorkspace";

import { RoomCounter } from "../agents/panels/openingLineFix";

export type Tone = NonNullable<ScriptAsk["tone"]>;

/** The tones the server takes (`campaign_script_ask.TONES`), in the owner's words. */
export const TONE_CHOICES: { value: Tone | ""; label: string }[] = [
  { value: "", label: "Pip decides" },
  { value: "warm", label: "Warm" },
  { value: "respectful", label: "Respectful" },
  { value: "brief", label: "Short and direct" },
];

export function TonePick({
  value,
  onChange,
  disabled,
  title,
}: {
  value: Tone | "";
  onChange: (tone: Tone | "") => void;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <label className="flex shrink-0 items-center gap-2 text-meta font-medium text-ink">
      Tone
      <select
        className={`${FIELD} w-auto`}
        value={value}
        disabled={disabled}
        title={title}
        onChange={(e) => onChange(e.target.value as Tone | "")}
      >
        {TONE_CHOICES.map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** "Add a note for Pip": what the owner wants this script to follow, in their own words. */
export function PipNote({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (note: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(value !== "");
  const box = useRef<HTMLTextAreaElement>(null);
  // Focused when the owner opens it, never when the page loads with a note already there.
  const mounted = useRef(false);
  useEffect(() => {
    if (open && mounted.current) box.current?.focus();
    mounted.current = true;
  }, [open]);
  if (!open) {
    return (
      <button type="button" className={`${TEXT_ACTION} text-meta`} disabled={disabled} onClick={() => setOpen(true)}>
        Add a note for Pip
      </button>
    );
  }
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <label htmlFor="pip-script-note" className="text-meta font-medium text-ink">
          Note for Pip
        </label>
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          onClick={() => {
            onChange("");
            setOpen(false);
          }}
        >
          Remove
        </button>
      </div>
      {/* A real note runs several sentences (who the agent is, what it says first, which
          words stay in English), so the box grows with it where the browser can. */}
      <textarea
        id="pip-script-note"
        ref={box}
        rows={3}
        maxLength={INSTRUCTION_MAX}
        aria-describedby="pip-script-note-room"
        placeholder="For example: keep every line short"
        className={`${FIELD} mt-1 [field-sizing:content] min-h-16 max-h-72`}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
      <RoomCounter id="pip-script-note-room" text={value} room={INSTRUCTION_MAX} />
    </div>
  );
}

/** No sources picked: Pip writes from the main task alone; one button to pick some. */
export function NoSourcesHint() {
  const pick = () => {
    const section = document.getElementById("campaign-materials");
    section?.scrollIntoView({ block: "start" });
    section?.querySelector<HTMLElement>("input, button")?.focus({ preventScroll: true });
  };
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <p className="text-meta text-ink-muted">No sources picked. Pip uses only the main task.</p>
      <button type="button" className={`${TEXT_ACTION} text-meta`} onClick={pick}>
        Pick sources
      </button>
    </div>
  );
}
