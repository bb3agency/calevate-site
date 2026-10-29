"use client";

import { useId, useState } from "react";
import { ArrowRight, Check, ChevronDown, CircleAlert, CircleHelp } from "lucide-react";

import { NOTICE_BAR, SECONDARY_BUTTON_SM } from "@/components/ui";

import type { CopilotCheck, CopilotCheckFix, CopilotDiagnosis } from "@/lib/copilot/types";

/**
 * WHY SOMETHING DID NOT WORK, AS A CHECKLIST — the troubleshoot card (D-935).
 *
 * The server ran an ordered list of checks and the first one that found a problem is the
 * cause. So the card leads with that one, open, with its one button; everything that passed
 * folds into a single line that opens to the list (progressive disclosure: the cause is the
 * content, the passed checks are the receipt). Buttons, not paragraphs.
 *
 * A check that could not be made says "Not checked", never a tick: an unknown read as a pass
 * is exactly the guess this mode exists to avoid.
 *
 * The fix is one of two things the server chose from its own inventory: a screen of this
 * console (handed to `onNavigate`, whose resolver checks it against the sidebar's own list),
 * or a sentence the button asks Pip, which then proposes the change under its usual
 * confirmation. Nothing here builds a route or changes anything by itself.
 */
export function DiagnosisCard({
  diagnosis,
  onAsk,
  asking = false,
  onNavigate,
}: {
  diagnosis: CopilotDiagnosis;
  onAsk?: (question: string) => void;
  asking?: boolean;
  onNavigate?: (destination: { route: string; screen: string; where: string }) => void;
}) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const cause = diagnosis.checks.find((check) => check.status === "problem") ?? null;
  const rest = diagnosis.checks.filter((check) => check !== cause);
  const passed = rest.filter((check) => check.status === "ok").length;
  const tone = cause ? "warn" : rest.some((check) => check.status === "unknown") ? "neutral" : "ok";

  return (
    <section
      aria-label={diagnosis.subject}
      className={`border-l-2 ${NOTICE_BAR[tone]} py-1 pl-3`}
    >
      <p className="text-xs font-medium text-ink">{diagnosis.subject}</p>
      {cause ? (
        <div className="mt-1">
          <p className="flex items-start gap-1.5 text-xs text-ink">
            <CircleAlert aria-hidden className="mt-px h-3.5 w-3.5 shrink-0 text-chart-warn" />
            <span>
              <span className="sr-only">Problem: </span>
              {cause.detail}
            </span>
          </p>
          {cause.fix ? (
            <FixButton
              fix={cause.fix}
              onAsk={onAsk}
              asking={asking}
              onNavigate={onNavigate}
            />
          ) : null}
        </div>
      ) : (
        <p className="mt-1 text-xs text-ink-muted">{diagnosis.verdict}</p>
      )}
      {rest.length > 0 ? (
        <div className="mt-1.5 text-meta text-ink-muted">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={listId}
            onClick={() => setOpen((value) => !value)}
            className="press inline-flex items-center gap-1.5 rounded-sm hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
          >
            {summary(rest.length, passed)}
            <ChevronDown
              aria-hidden
              className={`h-3.5 w-3.5 transition-transform duration-(--duration-fast) ${open ? "rotate-180" : ""}`}
            />
          </button>
          {open ? (
            <ul id={listId} className="mt-1.5 space-y-1.5 border-l border-line pl-3">
              {rest.map((check) => (
                <CheckRow key={check.key} check={check} />
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function summary(total: number, passed: number): string {
  if (passed === total) return total === 1 ? "1 other check passed" : `${total} other checks passed`;
  return `${passed} of ${total} other checks passed`;
}

const STATUS_WORDS: Record<CopilotCheck["status"], string> = {
  ok: "Passed",
  problem: "Problem",
  unknown: "Not checked",
};

function CheckRow({ check }: { check: CopilotCheck }) {
  const Icon = check.status === "ok" ? Check : check.status === "problem" ? CircleAlert : CircleHelp;
  return (
    <li>
      <span className="flex items-center gap-1.5 text-ink">
        <Icon
          aria-hidden
          className={`h-3.5 w-3.5 shrink-0 ${check.status === "problem" ? "text-chart-warn" : "text-ink-faint"}`}
        />
        <span className="sr-only">{STATUS_WORDS[check.status]}: </span>
        {check.label}
      </span>
      <span className="block break-words">
        {check.status === "unknown" ? `Not checked: ${check.detail}` : check.detail}
      </span>
    </li>
  );
}

function FixButton({
  fix,
  onAsk,
  asking,
  onNavigate,
}: {
  fix: CopilotCheckFix;
  onAsk?: (question: string) => void;
  asking: boolean;
  onNavigate?: (destination: { route: string; screen: string; where: string }) => void;
}) {
  const ask = fix.ask ?? null;
  if (ask !== null && onAsk) {
    return (
      <button
        type="button"
        disabled={asking}
        onClick={() => onAsk(ask)}
        className={`${SECONDARY_BUTTON_SM} mt-2`}
      >
        {fix.label}
      </button>
    );
  }
  const { route, screen, where } = fix;
  if (route && screen && where && onNavigate) {
    return (
      <button
        type="button"
        onClick={() => onNavigate({ route, screen, where })}
        className={`${SECONDARY_BUTTON_SM} mt-2`}
      >
        {fix.label}
        <ArrowRight aria-hidden className="h-3.5 w-3.5" />
      </button>
    );
  }
  // No way to act from here (the admin console opens no client screen and makes no client
  // change): say what the fix is, in words.
  const words = where ? `${fix.label}: ${where}.` : ask ? `Next step: ${ask}.` : null;
  return words ? <p className="mt-1 text-xs text-ink-muted">{words}</p> : null;
}
