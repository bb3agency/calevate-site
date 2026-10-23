"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { PRIMARY_BUTTON } from "@/components/ui";
import { useGoLive, type GoLive } from "@/lib/api/goLive";
import type { Session } from "@/lib/api/client";

const STEP_WORDS: Record<GoLive["current"], string> = {
  move: "Your agents are moving to your own account.",
  verify: "Next: verify your business.",
  number: "Next: choose your number.",
  switch_on: "Next: switch an agent on.",
  done: "",
};

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
  return (
    <section
      aria-labelledby="go-live-invite"
      className="flex flex-col gap-4 rounded-card border border-brand/40 bg-surface p-5 shadow-card sm:flex-row sm:items-center"
    >
      <div className="min-w-0 flex-1">
        <h2 id="go-live-invite" className="text-heading text-ink">
          Go live
        </h2>
        <p className="mt-0.5 text-body text-ink-muted">{STEP_WORDS[guide.data!.current]}</p>
      </div>
      <Link href={href("/go-live")} className={PRIMARY_BUTTON}>
        Continue
        <ArrowRight aria-hidden className="h-4 w-4" />
      </Link>
    </section>
  );
}
