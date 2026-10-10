"use client";

/**
 * ONE ACTION, ONE ROW, and every action the same row (founder, REDESIGN-2): its icon, its
 * name, one line of how it is set up, its own switch, a chip only when something is wrong,
 * and Manage. Booking is not special here; it opens into its own view like the rest.
 *
 * `ActionHeader` is the top of every action's own view, so a set-up row and the page it
 * opens read as the same thing.
 */

import type { ComponentType, SVGProps } from "react";
import { ChevronRight } from "lucide-react";

import { IconTile } from "@/components/console/iconTile";
import { TEXT_ACTION } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { ToggleSwitch } from "@/components/ui";

type Icon = ComponentType<SVGProps<SVGSVGElement>>;

export function ActionRow({
  title,
  summary,
  logo,
  icon,
  problem,
  enabled,
  switchDisabled,
  onToggle,
  onOpen,
}: {
  title: string;
  summary: string;
  logo: string | null;
  icon: Icon;
  problem: string | null;
  enabled: boolean;
  switchDisabled?: boolean;
  onToggle: (next: boolean) => void;
  onOpen: () => void;
}) {
  return (
    <li className="flex items-center gap-4 py-4">
      <IconTile service={logo} icon={icon} />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-body font-medium text-ink">
          <span className="[overflow-wrap:anywhere]">{title}</span>
          {problem ? (
            <StatusPill tone="warn">{problem}</StatusPill>
          ) : null}
        </p>
        {summary ? <p className="text-meta text-ink-muted [overflow-wrap:anywhere]">{summary}</p> : null}
      </div>
      <ToggleSwitch
        label={<span className="sr-only">{title}</span>}
        checked={enabled}
        disabled={switchDisabled}
        onChange={onToggle}
      />
      <button
        type="button"
        className={`${TEXT_ACTION} inline-flex items-center gap-0.5`}
        aria-label={`Manage ${title}`}
        onClick={onOpen}
      >
        <span className="max-sm:sr-only">Manage</span>
        <ChevronRight aria-hidden className="h-4 w-4" />
      </button>
    </li>
  );
}

/** The top of an action's own view: its icon, its name and what it does. */
export function ActionHeader({
  title,
  line,
  logo,
  icon,
}: {
  title: string;
  line: string;
  logo: string | null;
  icon: Icon;
}) {
  return (
    <div className="flex items-start gap-4">
      <IconTile service={logo} icon={icon} />
      <div className="min-w-0">
        <h3 className="text-heading text-ink">{title}</h3>
        <p className="mt-0.5 text-meta text-ink-muted">{line}</p>
      </div>
    </div>
  );
}
