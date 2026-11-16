"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice, SECONDARY_BUTTON_SM } from "@/components/ui";
import { goLiveKey } from "@/lib/api/goLive";
import { useWriteAccess } from "@/lib/api/hooks";
import { usePublishInboundLine, type InboundLine } from "@/lib/api/inboundLines";
import { useClientRealm } from "@/lib/api/session";

import { lineState } from "./lineStatus";

/**
 * A line that is not live, with its one way to fix that: callers of its numbers hear nothing
 * until it is put live (a draft drafted by the first run, or one whose last publish did not
 * finish). A line with no script yet opens on its page, where the script is written first.
 *
 * Used where an owner meets the line away from its own page: Go live, and a number just
 * bought. `onLive` refreshes whatever the caller shows about being live.
 */
export function PutLineLive({ line, onLive }: { line: InboundLine; onLive?: () => void }) {
  const { session, href } = useClientRealm();
  const write = useWriteAccess(session, "org:manage", "put a line live");
  const publish = usePublishInboundLine(session, line.id);
  const feedback = useActionFeedback(publish, { errorDisplay: "inline", successToast: "The line is live" });
  const client = useQueryClient();
  const state = lineState(line);
  const lineHref = href(`/c/${session.orgSlug}/inbound/${line.id}`);
  if (state === "live") return null;
  return (
    <div className="space-y-2">
      <p className="text-body text-ink">
        <span className="font-medium">{line.name}</span>{" "}
        {state === "draft" ? "has nothing to say yet." : "is a draft. Callers hear nothing until it is live."}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {state === "not_live" ? (
          <ActionButton
            variant="primary-sm"
            status={feedback.status}
            pendingLabel="Putting it live…"
            successLabel="Live"
            disabled={!write.allowed}
            title={write.reason ?? undefined}
            onClick={() =>
              publish.mutate(undefined, {
                onSuccess: () => {
                  void client.invalidateQueries({ queryKey: goLiveKey(session.orgSlug) });
                  onLive?.();
                },
              })
            }
          >
            Put it live
          </ActionButton>
        ) : null}
        <Link href={lineHref} className={SECONDARY_BUTTON_SM}>
          {state === "draft" ? "Write what it says" : "Open the line"}
          <ArrowRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      </div>
      {publish.error ? <ProblemNotice error={publish.error} /> : null}
    </div>
  );
}
