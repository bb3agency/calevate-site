"use client";

/**
 * A FOLDABLE SECTION of a campaign's set-up (founder, 15 Nov 2026): its heading is the
 * button that folds it, and `FoldGroup` adds Collapse all / Expand all for every section
 * inside it.
 *
 * The look is the console's calm one (REDESIGN-2): a heading on white above a hairline, no
 * tinted card and no colour per section. The founder chose "keep folding, drop colours" on
 * 15 Nov 2026 after five coloured tabs read as a different product from the rest of the
 * site; a status beside the heading keeps its meaning colour (amber for checks to answer).
 *
 * A command is a counter rather than a boolean so pressing the same one twice still reaches
 * sections a person has opened or closed by hand since.
 */

import { ChevronDown } from "lucide-react";
import { createContext, useContext, useEffect, useId, useState, type ReactNode } from "react";

import { TEXT_ACTION_SM } from "@/components/console/section";

type Command = { open: boolean; seq: number };
const FoldCommand = createContext<Command | null>(null);

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
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
          <div className="min-w-0">{header}</div>
          <div className="flex gap-1">
            <button type="button" className={TEXT_ACTION_SM} onClick={() => press(false)}>
              Collapse all
            </button>
            <button type="button" className={TEXT_ACTION_SM} onClick={() => press(true)}>
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
  aside,
  defaultOpen = true,
  id,
  children,
}: {
  title: string;
  /** A short status beside the name, such as "2 checks to answer". */
  aside?: ReactNode;
  defaultOpen?: boolean;
  /** The section's element id, for a link or a scroll to land on. */
  id?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const command = useContext(FoldCommand);
  const bodyId = useId();
  useEffect(() => {
    if (command) setOpen(command.open);
  }, [command]);
  return (
    <section id={id} className="scroll-mt-24 border-t border-line pt-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-heading text-ink">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen(!open)}
            className="press -mx-2 inline-flex min-h-9 items-center gap-1.5 rounded-md px-2 text-left hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
          >
            <ChevronDown
              aria-hidden
              className={`h-4 w-4 shrink-0 text-ink-muted transition-transform duration-(--duration-fast) motion-reduce:transition-none ${open ? "" : "-rotate-90"}`}
            />
            {title}
          </button>
        </h2>
        {aside ? <span className="text-meta text-ink-muted">{aside}</span> : null}
      </div>
      {/* Hidden rather than unmounted, so a half-filled form survives a fold. */}
      <div id={bodyId} hidden={!open} className="pt-4 pb-2">
        {children}
      </div>
    </section>
  );
}
