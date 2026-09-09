"use client";

import { ShieldAlert } from "lucide-react";

import { NoticeBox } from "@/components/ui";

/**
 * Was the disclosure line played? — the one compliance fact this screen can prove.
 *
 * Every agent must carry a non-null disclosure line (hard rule 5), and this column is
 * the per-call evidence that it reached the caller. Three states, not two: `null` means
 * the pipeline never recorded an answer, which is NOT the same as "no" and must not be
 * rendered as one — an owner told their call was non-compliant when we simply do not
 * know would go and change something that was never broken.
 */
export function DisclosureNotice({ played }: { played: boolean | null | undefined }) {
  if (played === true) return null;
  if (played === false) {
    return (
      <NoticeBox
        tone="stop"
        icon={<ShieldAlert className="h-5 w-5" />}
        title="No disclosure was played on this call"
      >
        Callers must be told they are speaking to an automated agent. Tell us about this call
        so we can check how the agent is set up.
      </NoticeBox>
    );
  }
  return null;
}
