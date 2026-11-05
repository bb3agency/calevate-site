"use client";

import { AskAssistant } from "@/components/copilot/AskAssistant";
import { NoticeBox } from "@/components/ui";
import { Why } from "@/components/why";
import { type Session } from "@/lib/api/client";
import { useAgentPromoCheck } from "@/lib/api/compliancePack";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { rewritePrompt } from "../../../campaigns/blockerCopy";

/** How many lines the warning quotes; the rest are counted. */
const SHOWN = 3;

/**
 * THE PROMO CHECK AT PUT-LIVE (D-943). A warning, never a block: an agent's script also
 * answers inbound calls, which the caller started, and the campaign launch is where an
 * offer actually stops a call (`script_promotional`). Nothing renders while the check
 * loads, fails or comes back clear — it is advice beside the button, not a gate on it.
 */
export function PromoWarning({
  session,
  agentId,
  agentName,
}: {
  session: Session;
  agentId: string;
  agentName: string;
}) {
  const check = useAgentPromoCheck(session, agentId);
  const report = check.data?.report;
  if (!report || report.verdict === "clear") return null;
  const promotional = report.verdict === "promotional";
  const shown = report.findings.slice(0, SHOWN);
  const more = report.findings.length - shown.length;
  // Wording in a language the check cannot read is named, never passed as clear.
  const unread = report.not_checked_in ?? [];
  const title = promotional
    ? "This script talks about offers"
    : shown.length > 0
      ? "Check these lines"
      : "Read these lines yourself";
  return (
    <NoticeBox
      tone={promotional ? "warn" : "neutral"}
      title={title}
      action={
        <AskAssistant label={`Ask ${ASSISTANT_NAME} to rewrite it`} prompt={rewritePrompt(agentName)} />
      }
    >
      <ul className="space-y-1">
        {shown.map((finding) => (
          <li key={`${finding.where}-${finding.phrase}`} className="text-meta">
            <span className="font-medium">{finding.where}:</span> “{finding.quote}”
          </li>
        ))}
      </ul>
      {more > 0 && <p className="text-meta text-ink-muted">and {more} more</p>}
      {unread.length > 0 && <p className="text-meta">Not checked in {unread.join(", ")}</p>}
      <Why inline>
        {promotional
          ? "One offer or sales line makes a call you place promotional. Campaigns using this script cannot launch until it is out."
          : shown.length > 0
            ? "These lines are sometimes promotional. They do not stop a campaign."
            : "The offer check cannot read these languages. Make sure the script makes no offer."}
      </Why>
    </NoticeBox>
  );
}
