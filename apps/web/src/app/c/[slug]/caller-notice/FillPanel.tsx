"use client";

import { useSyncExternalStore } from "react";

import { Checklist } from "@/components/console/checklist";
import type { CallerNotice } from "@/lib/api/callerNotice";

import { blankLabel, valueOf, type BlankValues } from "@/lib/noticeDraft/blanks";

// Below `lg` the panel sits ABOVE the sheet, so it starts closed there: its summary still
// says "N of M done", and an open list of five rows would push the document off the screen.
const STACKED = "(max-width: 1023px)";

function subscribe(onChange: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const query = window.matchMedia(STACKED);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function useStacked(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(STACKED).matches : false),
    () => false,
  );
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
            label="Fill the blanks"
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
                  {valueOf(values, key) !== null ? "Edit" : "Fill in"}
                </button>
              ),
            }))}
          />
          <p className="mt-3 text-meta leading-snug text-ink-faint">
            What you type stays in this browser. Nothing is sent to Calevate.
            {anyFilled && (
              <>
                {" "}
                <button
                  type="button"
                  onClick={onClear}
                  className="rounded-sm font-medium text-ink-muted underline underline-offset-2 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                >
                  Clear what I typed
                </button>
              </>
            )}
          </p>
        </div>
      )}

      {notice.collected.length === 0 && (
        <p className="text-meta text-ink-muted">
          <span className="font-medium text-ink">Nothing itemised yet</span>: once an agent is
          live and set up to collect details from calls, every detail it captures appears in
          the notice.
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
    { key: "ai", label: "These agents do not announce that they are AI", agents: notice.ai_disclosure_off },
    {
      key: "recording",
      label: "These agents do not announce that the call is recorded",
      agents: notice.recording_notice_off,
    },
  ].filter((group) => group.agents.length > 0);

  if (groups.length === 0) return null;

  return (
    <section aria-labelledby="announcements-off" className="border-t border-line pt-5">
      <h2 id="announcements-off" className="text-heading text-ink">
        Announcements your agents do not make
      </h2>
      <p className="mt-1.5 text-meta leading-relaxed text-ink-muted">
        Every agent still answers truthfully whenever a caller asks whether they are
        speaking to an AI or whether the call is recorded — that cannot be switched off.
        These settings govern only what is said unprompted at the start of a call, so where
        one is off, your written notice is where the obligation lands.
      </p>
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
