"use client";

/**
 * WRITING THE SCRIPT BY HAND, and asking Pip to turn it into steps when the owner is ready.
 *
 * The conversion is Pip's (D-820): the button prefills Pip's ask box, Pip writes the steps,
 * and they come back to this page as a suggestion (`PipProposal`) that lists every line of
 * the hand-written text that appears nowhere in them. Nothing is replaced until the owner
 * keeps it.
 */

import { AskAssistant } from "@/components/copilot/AskAssistant";
import { FIELD, FIELD_HINT, FIELD_LABEL, formatCount } from "@/components/ui";
import { InfoTip } from "@/components/console/infoTip";
import { useActAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import type { CallScript } from "@/lib/api/script";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { STEPS_REQUEST } from "./PipAsk";

const RAW_MAX = 20000;

export function HandWritten({
  script,
  readOnly,
  onChange,
}: {
  script: CallScript;
  readOnly: boolean;
  onChange: (text: string) => void;
}) {
  const session = useClientSession();
  const write = useActAccess(session, "org:manage", "billing.ai_assist", `ask ${ASSISTANT_NAME} to turn this into steps`);
  const text = script.raw_override ?? "";

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-1">
          <label className={FIELD_LABEL} htmlFor="raw-script">
            Your script
          </label>
          <InfoTip label="writing it by hand" align="start">
            The rules every agent follows, like always answering truthfully whether it is an AI
            and whether the call is recorded, are added for you.
          </InfoTip>
        </div>
        <span className={FIELD_HINT}>Brief it like new staff. Greeting goes under [OPENING].</span>
        <textarea
          id="raw-script"
          className={`${FIELD} min-h-[40dvh] font-mono`}
          rows={16}
          value={text}
          readOnly={readOnly}
          maxLength={RAW_MAX}
          onChange={(e) => onChange(e.target.value)}
        />
        <p className="mt-1 text-meta tabular-nums text-ink-faint">
          {formatCount(text.length)} of {formatCount(RAW_MAX)} letters
        </p>
      </div>

      <div className="space-y-2">
        <AskAssistant
          label={`Let ${ASSISTANT_NAME} turn it into steps`}
          prompt={STEPS_REQUEST}
          size="md"
          disabled={!write.allowed || readOnly || text.trim().length < 10}
        />
        <p className="text-meta text-ink-muted">
          You check each step first. Uses your AI allowance.
        </p>
      </div>
    </div>
  );
}
