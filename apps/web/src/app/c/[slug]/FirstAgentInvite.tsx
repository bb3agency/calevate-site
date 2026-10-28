"use client";

import Link from "next/link";
import { ArrowRight, MessageSquareText, PhoneIncoming, Sparkles } from "lucide-react";

import { PRIMARY_BUTTON } from "@/components/ui";

import { HOME } from "./setup/_ui/copy";

const STEPS = [
  { icon: Sparkles, label: HOME.meetSteps[0] },
  { icon: MessageSquareText, label: HOME.meetSteps[1] },
  { icon: PhoneIncoming, label: HOME.meetSteps[2] },
] as const;

/**
 * THE WAY IN TO THE FIRST AGENT (D-854, D-855), on the dashboard while the account has none.
 *
 * New accounts are not given a ready agent (D-853), so the dashboard's first job is to send
 * the owner to "Meet your agent". Rendered by the caller only when the agents list answered
 * empty and this person may create an agent; a failed read says nothing here. It names the
 * three things that will happen, so the click is not a leap.
 */
export function FirstAgentInvite({ href, started = false }: { href: (path: string) => string; started?: boolean }) {
  return (
    <section
      aria-labelledby="first-agent-invite"
      className="overflow-hidden rounded-card border border-brand/30 bg-surface shadow-card"
    >
      <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:gap-6">
        <div className="min-w-0 flex-1">
          <h2 id="first-agent-invite" className="text-title text-ink">
            {HOME.meetTitle}
          </h2>
          <ol className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-2">
            {STEPS.map(({ icon: Icon, label }, index) => (
              <li key={label} className="flex items-center gap-1.5">
                {index > 0 ? <span aria-hidden className="h-px w-3 bg-line" /> : null}
                <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-2.5 py-1 text-meta text-brand-strong">
                  <Icon aria-hidden className="h-3.5 w-3.5" />
                  {label}
                </span>
              </li>
            ))}
          </ol>
        </div>
        <Link href={href("/agents/first")} className={`${PRIMARY_BUTTON} shrink-0 justify-center`}>
          {started ? HOME.meetContinue : HOME.meetStart}
          <ArrowRight aria-hidden className="h-4 w-4" />
        </Link>
      </div>
    </section>
  );
}
