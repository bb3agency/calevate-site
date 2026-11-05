"use client";

/**
 * WRITING THE SCRIPT BY HAND, and asking Pip to turn it into steps when the owner is ready.
 *
 * The conversion is Pip's (D-820): the button prefills Pip's ask box, Pip writes the steps,
 * and they come back to this page as a suggestion (`PipProposal`) that lists every line of
 * the hand-written text that appears nowhere in them. Nothing is replaced until the owner
 * keeps it.
 */

import { AskAssistant } from "@/components/copilot/AskAssistant";
import { FIELD, FIELD_HINT, FIELD_LABEL, formatCount } from "@/components/ui";
import { InfoTip } from "@/components/console/infoTip";
import { useActAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import type { CallScript } from "@/lib/api/script";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { STEPS_REQUEST } from "./PipAsk";

const RAW_MAX = 20000;

/** The header the compiler reads the opening line under (`call_script.OPENING_HEADER`). */
const OPENING_HEADER = "[OPENING]";

/**
 * A hand-written script as the owner edits it (A-22): its opening line in its own box and
 * the rest of the text, so no owner has to write a bracketed heading. The opening is the
 * text under `[OPENING]` up to the next line that starts with "[", as the server reads it
 * (`call_script.opening_line_of`).
 */
export function splitOpening(raw: string): { opening: string; rest: string } {
  const lines = raw.split("\n");
  const start = lines.findIndex((line) => line.trim() === OPENING_HEADER);
  if (start < 0) return { opening: "", rest: raw };
  let end = lines.findIndex((line, i) => i > start && line.startsWith("["));
  if (end < 0) end = lines.length;
  const opening = lines.slice(start + 1, end).join(" ").replace(/^\s+/, "");
  // `joinOpening` puts one blank line before the heading; it is not the owner's.
  const before = lines.slice(0, start).join("\n");
  const head = before.endsWith("\n") ? before.slice(0, -1) : before;
  const after = lines.slice(end).join("\n");
  return { opening, rest: [head, after].filter((part) => part !== "").join("\n") };
}

/**
 * The raw text with `opening` under `[OPENING]` LAST, or no such section when empty. Last,
 * because the server reads the section up to the next bracketed heading: placed first, the
 * owner's whole brief below it would be read as the opening line.
 */
export function joinOpening(opening: string, rest: string): string {
  const line = opening.replace(/\n/g, " ");
  if (!line.trim()) return rest;
  return `${rest === "" ? "" : `${rest}\n\n`}${OPENING_HEADER}\n${line}`;
}

export function HandWritten({
  script,
  readOnly,
  onChange,
  drafting = false,
}: {
  script: CallScript;
  readOnly: boolean;
  onChange: (text: string) => void;
  /** A suggestion is being written; the server refuses another until it is done. */
  drafting?: boolean;
}) {
  const session = useClientSession();
  const write = useActAccess(session, "org:manage", "billing.ai_assist", `ask ${ASSISTANT_NAME} to turn this into steps`);
  const text = script.raw_override ?? "";
  const { opening, rest } = splitOpening(text);

  return (
    <div className="space-y-4">
      <div>
        <label className={FIELD_LABEL} htmlFor="raw-opening">
          Opening line
        </label>
        <span className={FIELD_HINT}>Its first words on a call. Keep it short.</span>
        <textarea
          id="raw-opening"
          className={FIELD}
          rows={2}
          value={opening}
          readOnly={readOnly}
          maxLength={1000}
          onChange={(e) => onChange(joinOpening(e.target.value, rest))}
        />
      </div>
      <div>
        <div className="flex items-center gap-1">
          <label className={FIELD_LABEL} htmlFor="raw-script">
            Your script
          </label>
          <InfoTip label="writing it by hand" align="start">
            The rules every agent follows, like always answering truthfully whether it is an AI
            and whether the call is recorded, are added for you.
          </InfoTip>
        </div>
        <span className={FIELD_HINT}>Brief it like new staff.</span>
        <textarea
          id="raw-script"
          className={`${FIELD} min-h-[40dvh] font-mono`}
          rows={16}
          value={rest}
          readOnly={readOnly}
          maxLength={RAW_MAX}
          onChange={(e) => onChange(joinOpening(opening, e.target.value))}
        />
        <p className="mt-1 text-meta tabular-nums text-ink-faint">
          {formatCount(text.length)} of {formatCount(RAW_MAX)} letters
        </p>
      </div>

      <div className="space-y-2">
        <AskAssistant
          label={`Let ${ASSISTANT_NAME} turn it into steps`}
          prompt={STEPS_REQUEST}
          size="md"
          disabled={!write.allowed || readOnly || drafting || text.trim().length < 10}
        />
        <p className="text-meta text-ink-muted">
          {drafting
            ? `Wait for ${ASSISTANT_NAME} to finish this suggestion`
            : "You check each step first. Uses your AI allowance."}
        </p>
      </div>
    </div>
  );
}
