"use client";

/**
 * WHAT A PIP DRAFT LEFT OUT, shown beside the review of an Inbound line's or a campaign's
 * draft (`ProposalReview`). An agent has no script of its own (D-997, D-1000), so the agent's
 * own suggestion this file once reviewed is retired (D-1005); the notice is all that stays.
 */

import { NoticeBox } from "@/components/ui";
import type { components } from "@/lib/api/schema";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

type LeftOutPart = components["schemas"]["CampaignLeftOutOut"];

/**
 * The parts Pip left as the owner had them because its words for them broke a call rule:
 * the rest of the draft is still offered, and these are named rather than dropped.
 */
export function LeftOutNotice({ parts }: { parts: LeftOutPart[] }) {
  // A warning Pip's repairs could not clear is in the draft itself, not a part kept as the
  // owner had it, so it is named apart (D-989).
  const unfixed = parts.filter((part) => part.unfixed);
  const kept = parts.filter((part) => !part.unfixed);
  const one = kept.length === 1;
  return (
    <>
      {kept.length > 0 && (
        <NoticeBox tone="neutral" title={`${kept.length} ${one ? "part" : "parts"} kept as you had ${one ? "it" : "them"}`}>
          <PartList parts={kept} />
          <p className="mt-2 text-meta">Edit {one ? "it" : "them"} yourself, or ask {ASSISTANT_NAME} for one at a time.</p>
        </NoticeBox>
      )}
      {unfixed.length > 0 && (
        <NoticeBox tone="neutral" title={`${ASSISTANT_NAME} could not fix everything`}>
          <PartList parts={unfixed} />
          <p className="mt-2 text-meta">Edit {unfixed.length === 1 ? "it" : "them"} after you keep this, or keep your lines.</p>
        </NoticeBox>
      )}
    </>
  );
}

function PartList({ parts }: { parts: LeftOutPart[] }) {
  return (
    <ul className="mt-2 space-y-1 text-meta">
      {parts.map((part, i) => (
        <li key={`${part.part}-${i}`} className="break-words [overflow-wrap:anywhere]">
          <span className="font-semibold">{part.label}</span>
          {part.added ? " (not added)" : ""}: {part.rule}
        </li>
      ))}
    </ul>
  );
}
