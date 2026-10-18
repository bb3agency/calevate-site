"use client";

import { AskAssistant } from "@/components/copilot/AskAssistant";
import { Disclosure, RestrictionNote } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useActAccess } from "@/lib/api/hooks";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

/** What Pip is asked, in the words the owner sees in its ask box. */
export const SECOND_READING_REQUEST = "Summarise this call again from its transcript.";

/**
 * "A second reading of this call", asked of Pip (D-821; it was a panel of its own, D-127).
 *
 * Pip proposes `call_summarise_again`; once the owner confirms, it reads the REDACTED
 * transcript and shows the fresh summary in its panel, beside a disclosure when another
 * model answered and a note when nothing was charged. Nothing here is stored or replaced,
 * and the ceiling's wallet dialog is Pip's own (`CopilotPanel`). Pip knows which call from
 * this page's `call_id` fact.
 *
 * The access is the action's own: `org:manage`, and never from a view-as session, because
 * it spends the client's AI allowance (`billing.ai_assist`).
 */
export function AssistCard({ session }: { session: Session }) {
  const write = useActAccess(session, "org:manage", "billing.ai_assist", "use AI help on this call");
  return (
    // Behind a disclosure (UX-DOCTRINE §3): rarely used, and it spends the allowance.
    <Disclosure variant="inline" title="A second reading of this call" className="border-t border-line">
      <div className="space-y-3 pb-3">
        <p className="text-meta text-ink-muted">
          {ASSISTANT_NAME} reads the transcript again with numbers hidden and writes a fresh
          summary for you. It uses your AI allowance and changes nothing saved here.
        </p>
        <RestrictionNote reason={write.reason} />
        <AskAssistant
          label={`Let ${ASSISTANT_NAME} write a second reading`}
          prompt={SECOND_READING_REQUEST}
          size="md"
          disabled={!write.allowed}
        />
      </div>
    </Disclosure>
  );
}
