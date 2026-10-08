import type { ReactNode } from "react";

import { loadShedModeCopy } from "@/app/admin/ops/opsLanguage";
import { formatCount } from "@/components/ui";
import type { PlatformState } from "@/lib/api/admin";

import type { DeadLetterState, EngineDriftState } from "./opsSurfaceState";

type Tone = "ok" | "warn" | "danger" | "unknown";

const TONE_TEXT: Record<Tone, string> = {
  ok: "text-ink",
  warn: "text-warn",
  danger: "text-danger",
  unknown: "text-ink-muted",
};

const TONE_DOT: Record<Tone, string> = {
  ok: "bg-brand",
  warn: "bg-warn",
  danger: "bg-danger",
  unknown: "bg-ink-faint",
};

/**
 * The platform at a glance, above the switches: five facts, each the SERVER's value and
 * each a link to the panel that owns it.
 *
 * There is no default state here either: a platform row that did not arrive renders every
 * fact as "Unknown", never as "Running" — the one line this screen must not get wrong is
 * whether outbound calling is stopped.
 */
export function OpsStatusStrip({
  platform,
  deadLetters,
  engineDrift,
}: {
  platform: PlatformState | undefined;
  deadLetters: DeadLetterState;
  engineDrift: EngineDriftState;
}) {
  const unknown = { value: "Unknown", tone: "unknown" as const };
  const outbound = platform
    ? platform.outbound_halted
      ? { value: "Halted", tone: "danger" as const }
      : { value: "Running", tone: "ok" as const }
    : unknown;
  const slowdown = platform
    ? {
        value: loadShedModeCopy(platform.load_shed_mode).label,
        tone: platform.load_shed_mode === "normal" ? ("ok" as const) : ("warn" as const),
      }
    : unknown;
  // D-692: Calevate does not register as a telemarketer and no outbound gate asks for it,
  // so an absent registration is the expected state rather than an alarm.
  const registration = platform
    ? platform.tm_registration.is_live
      ? { value: "Live", tone: "ok" as const }
      : { value: "Not required", tone: "unknown" as const }
    : unknown;
  const stuck =
    deadLetters.status === "read"
      ? {
          value: formatCount(deadLetters.queue.depth),
          tone: deadLetters.queue.depth > 0 ? ("warn" as const) : ("ok" as const),
        }
      : unknown;
  const drift =
    engineDrift.status === "read"
      ? {
          value: `${formatCount(engineDrift.drift.out_of_sync)} drifted`,
          tone: engineDrift.drift.out_of_sync > 0 ? ("warn" as const) : ("ok" as const),
        }
      : unknown;

  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-card border border-line bg-surface p-4 sm:grid-cols-3 lg:grid-cols-5">
      <Fact href="#outbound" label="Outbound calling" {...outbound} />
      <Fact href="#slowdown" label="Protective slowdown" {...slowdown} />
      <Fact href="#registration" label="Telemarketer registration" {...registration} />
      <Fact href="#stuck" label="Stuck messages" {...stuck} />
      <Fact href="#drift" label="Live agents" {...drift} />
    </dl>
  );
}

function Fact({
  href,
  label,
  value,
  tone,
}: {
  href: string;
  label: string;
  value: ReactNode;
  tone: Tone;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[12px] font-medium text-ink-muted">{label}</dt>
      <dd className="mt-0.5">
        <a
          href={href}
          className={`inline-flex items-center gap-1.5 rounded-sm text-[15px] font-semibold hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11 ${TONE_TEXT[tone]}`}
        >
          <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${TONE_DOT[tone]}`} />
          {value}
        </a>
      </dd>
    </div>
  );
}
