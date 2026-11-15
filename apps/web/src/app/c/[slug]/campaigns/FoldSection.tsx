"use client";

/**
 * A FOLDABLE SECTION with its name outside the card (founder, 15 Nov 2026): a coloured pill
 * sits on the card's top edge, and pressing it folds the card to a thin bar. Each section has
 * its own colour so the eye finds it again; the pill keeps the name, so colour is never the
 * only signal.
 *
 * `FoldGroup` adds Collapse all / Expand all for every section inside it. A command is a
 * counter rather than a boolean so pressing the same one twice still reaches sections a
 * person has opened or closed by hand since.
 */

import { ChevronDown } from "lucide-react";
import { createContext, useContext, useEffect, useId, useState, type ReactNode } from "react";

type Command = { open: boolean; seq: number };
const FoldCommand = createContext<Command | null>(null);

export type FoldTone = "voice" | "compliance" | "add" | "people" | "settings";

const TONE: Record<FoldTone, { pill: string; card: string }> = {
  voice: { pill: "bg-info text-surface", card: "border-info-line border-l-info bg-info-soft/40" },
  compliance: { pill: "bg-warn text-surface", card: "border-warn-line border-l-warn bg-warn-soft/40" },
  add: { pill: "bg-brand-strong text-surface", card: "border-success-line border-l-brand-strong bg-brand-soft/40" },
  people: { pill: "bg-series-4 text-surface", card: "border-series-4/30 border-l-series-4 bg-series-4/5" },
  settings: { pill: "bg-ink text-surface", card: "border-line border-l-ink bg-surface-muted/60" },
};

export function FoldGroup({
  header,
  children,
  className = "",
}: {
  /** Shown left of the two buttons, such as the step's own heading. */
  header?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const [command, setCommand] = useState<Command | null>(null);
  const press = (open: boolean) => setCommand((c) => ({ open, seq: (c?.seq ?? 0) + 1 }));
  return (
    <FoldCommand.Provider value={command}>
      <div className={className}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">{header}</div>
          <div className="flex gap-2">
          <button
            type="button"
            className="rounded-full border border-line bg-surface px-3 py-1.5 text-meta font-medium text-ink hover:bg-surface-muted"
            onClick={() => press(false)}
          >
            Collapse all
          </button>
          <button
            type="button"
            className="rounded-full border border-line bg-surface px-3 py-1.5 text-meta font-medium text-ink hover:bg-surface-muted"
            onClick={() => press(true)}
          >
            Expand all
          </button>
          </div>
        </div>
        {children}
      </div>
    </FoldCommand.Provider>
  );
}

export function FoldSection({
  title,
  tone,
  aside,
  defaultOpen = true,
  id,
  children,
}: {
  title: string;
  tone: FoldTone;
  /** A short status beside the name, such as "2 checks to answer". */
  aside?: ReactNode;
  defaultOpen?: boolean;
  /** The card's element id, for a link or a scroll to land on. */
  id?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const command = useContext(FoldCommand);
  const bodyId = useId();
  useEffect(() => {
    if (command) setOpen(command.open);
  }, [command]);
  const look = TONE[tone];
  return (
    <section id={id} className="relative scroll-mt-24 pt-4">
      <div className="absolute left-4 top-0 z-10 flex items-center gap-3">
        <h2 className="text-body font-semibold">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen(!open)}
            className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1 shadow-card ${look.pill}`}
          >
            <ChevronDown aria-hidden className={`h-4 w-4 transition-transform ${open ? "" : "-rotate-90"}`} />
            {title}
          </button>
        </h2>
        {aside ? <span className="rounded-full bg-surface px-2 py-0.5 text-meta">{aside}</span> : null}
      </div>
      <div
        id={bodyId}
        className={`rounded-card border border-l-4 ${look.card} ${open ? "px-4 pb-5 pt-7 sm:px-6" : "h-5"}`}
      >
        {/* Hidden rather than unmounted, so a half-filled form survives a fold. */}
        <div hidden={!open}>{children}</div>
      </div>
    </section>
  );
}
