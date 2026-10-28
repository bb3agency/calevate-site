"use client";

import { Eraser } from "lucide-react";

import { Checklist } from "@/components/console/checklist";
import { SECONDARY_BUTTON_SM } from "@/components/ui";
import type { CallerNotice } from "@/lib/api/callerNotice";
import { useMediaQuery } from "@/lib/useMediaQuery";

import { blankLabel, valueOf, type BlankValues } from "@/lib/noticeDraft/blanks";

import { WhyTip } from "../agreements/_ui/WhyTip";
import { CALLER_NOTICE_COPY as COPY, CALLER_NOTICE_KEPT as KEPT } from "./copy";

// Below `lg` the panel sits ABOVE the sheet, so it starts closed there: its summary still
// says "N of M done", and an open list of five rows would push the document off the screen.
const STACKED = "(max-width: 1023px)";

function useStacked(): boolean {
  return useMediaQuery(STACKED);
}

/**
 * Beside the sheet: how many blanks are filled, a jump to each, and the two facts about
 * this account the owner must see before publishing.
 */
export function FillPanel({
  notice,
  keys,
  values,
  onClear,
}: {
  notice: CallerNotice;
  keys: string[];
  values: BlankValues;
  onClear: () => void;
}) {
  const jump = (key: string) => {
    const field = Array.from(document.querySelectorAll<HTMLElement>("[data-blank-field]")).find(
      (element) => element.dataset.blankField === key,
    );
    field?.scrollIntoView({ block: "center", behavior: "smooth" });
    field?.focus({ preventScroll: true });
  };
  const stacked = useStacked();
  const anyFilled = keys.some((key) => valueOf(values, key) !== null);

  return (
    <div className="space-y-6">
      {keys.length > 0 && (
        <div>
          <Checklist
            label={COPY.fillHeading}
            headingLevel={2}
            collapsible
            defaultOpen={!stacked}
            items={keys.map((key) => ({
              id: key,
              label: blankLabel(key),
              state: valueOf(values, key) !== null ? "done" : "todo",
              action: (
                <button
                  type="button"
                  onClick={() => jump(key)}
                  aria-label={`Go to the blank: ${blankLabel(key)}`}
                  className="press rounded-md px-2 py-1 text-meta font-medium text-brand-strong hover:bg-brand-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
                >
                  {valueOf(values, key) !== null ? COPY.edit : COPY.fill}
                </button>
              ),
            }))}
          />
          <p className="mt-3 text-meta leading-snug text-ink-faint">{COPY.localOnly}</p>
          {anyFilled && (
            <button type="button" onClick={onClear} className={`${SECONDARY_BUTTON_SM} mt-2`}>
              <Eraser aria-hidden className="h-3.5 w-3.5" />
              {COPY.clear}
            </button>
          )}
        </div>
      )}

      {notice.collected.length === 0 && (
        <p className="flex flex-wrap items-center gap-x-1 text-meta font-medium text-ink">
          {COPY.nothingListed}
          <WhyTip about="caller details in the notice" label="Why?">
            <p>{COPY.nothingListedWhy}</p>
          </WhyTip>
        </p>
      )}

      <AnnouncementsOff notice={notice} />
    </div>
  );
}

/**
 * The agents whose opening announcements are switched off (D-163). With one off, the
 * obligation moves onto this notice, so the agents are NAMED. The truthful-answer sentence
 * comes first, because "announcement off" read alone describes a product that conceals.
 */
function AnnouncementsOff({ notice }: { notice: CallerNotice }) {
  const groups = [
    { key: "ai", label: COPY.offAi, agents: notice.ai_disclosure_off },
    { key: "recording", label: COPY.offRecording, agents: notice.recording_notice_off },
  ].filter((group) => group.agents.length > 0);

  if (groups.length === 0) return null;

  return (
    <section aria-labelledby="announcements-off" className="border-t border-line pt-5">
      <h2 id="announcements-off" className="text-heading text-ink">
        {COPY.offHeading}
      </h2>
      {/* The guarantee first and on screen (UX-DOCTRINE §8.7): "announcement off" read alone
          describes a product that conceals. Both sentences keep their words; only the
          explanation of what the switches cover sits behind the tap. */}
      <div className="mt-1.5 space-y-1.5 text-meta leading-relaxed text-ink-muted">
        <p>{KEPT.guarantee}</p>
        <p className="flex flex-wrap items-center gap-x-1">
          {KEPT.obligation}
          <WhyTip about="what these settings cover" label="Why?">
            <p>{COPY.offWhy}</p>
          </WhyTip>
        </p>
      </div>
      <div className="mt-3 space-y-3">
        {groups.map((group) => (
          <div key={group.key}>
            <p className="text-meta font-medium text-ink-muted">{group.label}</p>
            <ul className="mt-1 flex flex-wrap gap-1.5">
              {group.agents.map((name) => (
                <li key={name} className="rounded-md bg-surface-muted px-2 py-0.5 text-meta text-ink">
                  {name}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
