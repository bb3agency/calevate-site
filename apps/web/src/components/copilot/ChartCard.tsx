"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, Copy, Pin } from "lucide-react";

import { ActionButton, problemToast, useActionFeedback } from "@/components/arc/feedback";
import { useToast } from "@/components/arc/toast";
import { copyText } from "@/components/interior/copy-button";
import { SECONDARY_BUTTON_SM } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useAddPin, useRemovePin } from "@/lib/api/pins";
import { openHref, specCsv, type ChartRealm, type ChartSpec } from "@/lib/copilot/charts";

import { ChartView } from "./ChartView";

/**
 * A chart Pip drew in the panel (D-934), with its three buttons: keep it on the home screen
 * (at once, with Undo in the toast), open the screen that shows the same set, and copy it
 * as CSV. The chart itself carries "Show as table" for anyone who cannot read the marks.
 */
export function ChartCard({
  spec,
  session,
  realm,
}: {
  spec: ChartSpec;
  session: Session;
  realm: ChartRealm;
}) {
  const add = useAddPin(session, realm);
  const remove = useRemovePin(session, realm);
  const { toast } = useToast();
  const pinFeedback = useActionFeedback(add, {
    errorTitle: "Could not pin this chart",
    successToast: "Pinned to your home screen",
    undo: (made) => remove.mutate(made.id, { onError: (error) => toast(problemToast(error, "Could not take it off")) }),
  });
  const [copied, setCopied] = useState<"idle" | "copied" | "error">("idle");
  const href = openHref(spec, realm, session.orgSlug);

  const pin = () => pinFeedback.run({ chart: spec.chart, args: spec.args, title: spec.title });

  const copy = async () => {
    setCopied((await copyText(specCsv(spec))) ? "copied" : "error");
    setTimeout(() => setCopied("idle"), 2000);
  };

  return (
    <div className="rounded-card border border-line bg-surface p-3">
      <ChartView spec={spec} />
      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton
          variant="secondary"
          status={pinFeedback.status}
          onClick={pin}
          successLabel="Pinned"
          aria-label={`Pin “${spec.title}” to the home screen`}
        >
          <Pin aria-hidden className="h-3.5 w-3.5" />
          Pin to home
        </ActionButton>
        {href && spec.open ? (
          <Link href={href} className={SECONDARY_BUTTON_SM}>
            <ArrowUpRight aria-hidden className="h-3.5 w-3.5" />
            Open in {spec.open.screen}
          </Link>
        ) : null}
        <button type="button" onClick={() => void copy()} className={SECONDARY_BUTTON_SM}>
          <Copy aria-hidden className="h-3.5 w-3.5" />
          {copied === "copied" ? "Copied" : copied === "error" ? "Could not copy" : "Copy as CSV"}
        </button>
      </div>
      <p aria-live="polite" className="sr-only">
        {copied === "copied" ? "Copied as CSV." : ""}
      </p>
    </div>
  );
}
