"use client";

/**
 * AN AI PROPOSAL, REVIEWED BEFORE IT TOUCHES ANYTHING.
 *
 * Every change is its own row with its own "Keep" box, all kept to start with; the owner
 * unticks what they do not want and only the rest is applied to their draft (`applyChanges`).
 * Nothing goes live from here: the draft still waits for "Put it live".
 */

import { useMemo, useState, type ReactNode } from "react";

import { PRIMARY_BUTTON_SM, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { CallScript } from "@/lib/api/script";

import { applyChanges, diffScripts, type Change } from "./scriptDiff";
import { sectionDetail } from "./scriptModel";

export function ProposalReview({
  current,
  proposal,
  onApply,
  onDiscard,
  gate,
  children,
}: {
  current: CallScript;
  proposal: CallScript;
  onApply: (next: CallScript) => void;
  onDiscard: () => void;
  /** A reason "Keep" must wait (the owner has not confirmed the unplaced lines yet). */
  gate?: string | null;
  /** Shown above the changes: the server's account of how it was written, unplaced lines. */
  children?: ReactNode;
}) {
  const changes = useMemo(() => diffScripts(current, proposal), [current, proposal]);
  const [kept, setKept] = useState<Set<string>>(() => new Set(changes.map((c) => c.id)));
  const keptCount = changes.filter((c) => kept.has(c.id)).length;

  const toggle = (id: string, on: boolean) =>
    setKept((k) => {
      const next = new Set(k);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  return (
    <section aria-labelledby="proposal-heading" className="space-y-4">
      <div>
        <h3 id="proposal-heading" className="text-heading text-ink">
          {changes.length === 1 ? "1 suggested change" : `${changes.length} suggested changes`}
        </h3>
        <p className="mt-1 text-meta text-ink-muted">
          Untick what you do not want. What you keep goes into your draft, not live.
        </p>
      </div>
      {children}
      {changes.length === 0 ? (
        <p className="text-body text-ink-muted">The suggestion is the same as your script. Nothing to change.</p>
      ) : (
        <ul className="divide-y divide-line border-y border-line">
          {changes.map((change) => {
            const on = kept.has(change.id);
            return (
              <li key={change.id}>
                {/* An unticked change fades, so what will be applied is visible at a glance. */}
                <label
                  className={`flex cursor-pointer items-start gap-3 py-3 transition-opacity duration-150 ${
                    on ? "" : "opacity-55"
                  }`}
                >
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 shrink-0 accent-[var(--brand-strong)]"
                    checked={on}
                    onChange={(e) => toggle(change.id, e.target.checked)}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-baseline gap-x-2">
                      <span className="text-body font-medium text-ink">{headline(change)}</span>
                      <span className="text-meta text-ink-muted">{kindLabel(change)}</span>
                    </span>
                    <ChangeBody change={change} />
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {/* The one primary action stays in reach however long the list is. */}
      <div className="sticky bottom-0 -mx-1 space-y-2 border-t border-line bg-surface px-1 pb-1 pt-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className={PRIMARY_BUTTON_SM}
            disabled={keptCount === 0 || Boolean(gate)}
            title={gate ?? undefined}
            onClick={() => onApply(applyChanges(current, proposal, kept))}
          >
            {keptCount === changes.length
              ? changes.length === 1
                ? "Add it to my draft"
                : `Add all ${changes.length} to my draft`
              : `Add ${keptCount} of ${changes.length} to my draft`}
          </button>
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDiscard}>
            Discard
          </button>
        </div>
        {gate && <p className="text-meta text-ink-muted">{gate}</p>}
      </div>
    </section>
  );
}

export function headline(change: Change): string {
  return change.label;
}

/** What kind of change a row is, said quietly beside its name rather than in it. */
export function kindLabel(change: Change): string {
  switch (change.kind) {
    case "part":
      return change.before ? "Changed" : "Added";
    case "section-added":
      return "New step";
    case "section-removed":
      return "Step removed";
    case "section-changed":
      return "Step changed";
  }
}

export function ChangeBody({ change }: { change: Change }) {
  if (change.kind === "part") return <BeforeAfter before={change.before} after={change.after} />;
  if (change.kind === "section-added") return <Quote tone="after" text={sectionDetail(change.after)} />;
  if (change.kind === "section-removed") return <Quote tone="before" text={sectionDetail(change.before)} />;
  const before = [change.before.name !== change.after.name && `Name: ${change.before.name}`, sectionDetail(change.before)]
    .filter(Boolean)
    .join("\n");
  const after = [change.before.name !== change.after.name && `Name: ${change.after.name}`, sectionDetail(change.after)]
    .filter(Boolean)
    .join("\n");
  return <BeforeAfter before={before} after={after} />;
}

function BeforeAfter({ before, after }: { before: string; after: string }) {
  return (
    <span className="mt-1.5 block space-y-1.5">
      {before && <Quote tone="before" text={before} />}
      <Quote tone="after" text={after || "(left empty)"} />
    </span>
  );
}

/** Long texts open in full on request; four lines is enough to judge most changes. */
const CLAMP_AT = 220;

/**
 * One side of a change. A rule down the left marks the side, rather than two filled boxes
 * that made every row equally loud: the suggestion carries the brand rule and full ink, what
 * is there now stays muted.
 */
function Quote({ tone, text }: { tone: "before" | "after"; text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > CLAMP_AT;
  const after = tone === "after";
  return (
    <span
      className={`block border-l-2 pl-3 text-meta ${
        after ? "border-brand text-ink" : "border-line text-ink-muted"
      }`}
    >
      <span className="block text-[11px] font-medium uppercase tracking-wide text-ink-muted">
        {after ? "Suggested" : "Now"}
      </span>
      <span className={`block whitespace-pre-wrap ${long && !open ? "line-clamp-4" : ""}`}>{text}</span>
      {long && (
        <button
          type="button"
          className="mt-0.5 text-[11px] font-medium text-brand-strong hover:underline"
          onClick={(e) => {
            // Inside the row's label: a click here must not tick or untick the change.
            e.preventDefault();
            setOpen((o) => !o);
          }}
        >
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </span>
  );
}
