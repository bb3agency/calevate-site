"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { PRIMARY_BUTTON } from "@/components/ui";
import { useGoLive, type GoLive } from "@/lib/api/goLive";
import type { Session } from "@/lib/api/client";

import { HOME } from "./setup/_ui/copy";

const STEP_WORDS: Record<GoLive["current"], string> = HOME.goLiveStep;
/** The guide's four steps in order, for the "2 of 4" chip (the guide's own list is not
 *  imported: it would pull the whole guide into the dashboard's bundle). */
const ORDER: readonly GoLive["current"][] = ["move", "verify", "number", "switch_on"];

/** Is the guide still worth offering: owed (the account has paid), not finished, not done. */
export function goLiveOffered(guide: GoLive | undefined): boolean {
  return (
    guide !== undefined &&
    guide.owed_at !== null &&
    (guide.finished_at ?? null) === null &&
    guide.current !== "done"
  );
}

/**
 * THE WAY BACK INTO "GO LIVE" (D-859), on the dashboard from the first payment until the owner
 * finishes the guide; putting it aside keeps this card. Renders nothing otherwise, and a failed
 * read says nothing here (the guide itself says it).
 */
export function GoLiveInvite({ session, href }: { session: Session; href: (path: string) => string }) {
  const guide = useGoLive(session);
  if (!goLiveOffered(guide.data)) return null;
  const current = guide.data!.current;
  const at = ORDER.indexOf(current);
  return (
    <section
      aria-labelledby="go-live-invite"
      className="flex flex-col gap-4 rounded-card border border-brand/40 bg-surface p-5 shadow-card sm:flex-row sm:items-center"
    >
      <div className="min-w-0 flex-1">
        <h2 id="go-live-invite" className="flex items-center gap-2 text-heading text-ink">
          {HOME.goLiveTitle}
          {at >= 0 ? (
            <span className="rounded-full bg-brand-soft px-2 py-0.5 text-meta font-medium tabular-nums text-brand-strong">
              {at + 1} of {ORDER.length}
            </span>
          ) : null}
        </h2>
        <p className="mt-0.5 text-body text-ink-muted">{STEP_WORDS[current]}</p>
      </div>
      <Link href={href("/go-live")} className={`${PRIMARY_BUTTON} justify-center`}>
        {HOME.goLiveContinue}
        <ArrowRight aria-hidden className="h-4 w-4" />
      </Link>
    </section>
  );
}
