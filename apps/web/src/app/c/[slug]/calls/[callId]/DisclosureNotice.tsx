"use client";


import { NoticeBox, SECONDARY_BUTTON_SM } from "@/components/ui";
import { resolvePlaceholders } from "@/lib/legal/placeholders";

/**
 * Was the disclosure line played? — the one compliance fact this screen can prove.
 *
 * Every agent must carry a non-null disclosure line (hard rule 5), and this column is
 * the per-call evidence that it reached the caller. Three states, not two: `null` means
 * the pipeline never recorded an answer, which is NOT the same as "no" and must not be
 * rendered as one — an owner told their call was non-compliant when we simply do not
 * know would go and change something that was never broken.
 */
export function DisclosureNotice({
  played,
  callId,
}: {
  played: boolean | null | undefined;
  callId: string;
}) {
  if (played === true) return null;
  if (played === false) {
    // The subject carries the call's id (not the caller's number) so support can open it.
    const subject = encodeURIComponent(`AI notice did not play, call ${callId}`);
    return (
      <NoticeBox
        tone="stop"
        title="The AI notice did not play"
        info="Callers must be told they are speaking to an AI. Tell us and we check the agent."
        infoLabel="why this matters"
        action={
          <a
            className={SECONDARY_BUTTON_SM}
            href={`mailto:${resolvePlaceholders("{{SUPPORT_EMAIL}}")}?subject=${subject}`}
          >
            Tell us
          </a>
        }
      />
    );
  }
  return null;
}
