"use client";

/**
 * WRITING THE SCRIPT BY HAND, and turning it into sections when the owner is ready.
 *
 * The conversion is a proposal like any other: the AI returns sections, the server lists
 * every line of the hand-written text that appears nowhere in them (`unplaced`), and the
 * owner sees both before anything is replaced. When lines are unplaced, "Keep" waits until
 * the owner says they have read them, so a lost sentence is a decision and never a surprise.
 */

import { useState } from "react";
import { Wand2 } from "lucide-react";

import { FIELD, FIELD_HINT, FIELD_LABEL, NoticeBox, ProblemNotice, SECONDARY_BUTTON, formatCount } from "@/components/ui";
import { useActAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { EMPTY_SCRIPT, useConvertScript, type CallScript, type ConvertOut } from "@/lib/api/script";

import { ProposalReview } from "./ProposalReview";

const RAW_MAX = 20000;

export function HandWritten({
  agentId,
  script,
  readOnly,
  onChange,
  onConverted,
}: {
  agentId: string;
  script: CallScript;
  readOnly: boolean;
  onChange: (text: string) => void;
  onConverted: (next: CallScript) => void;
}) {
  const session = useClientSession();
  const convert = useConvertScript(session, agentId);
  const write = useActAccess(session, "org:manage", "billing.ai_assist", "turn this into sections");
  const [proposal, setProposal] = useState<ConvertOut | null>(null);
  const [checked, setChecked] = useState(false);
  const text = script.raw_override ?? "";

  // The sections start from an empty structured script that keeps the owner's own switches.
  const structuredBase: CallScript = {
    ...EMPTY_SCRIPT,
    policies: script.policies,
    variables: script.variables,
  };

  return (
    <div className="space-y-4">
      <div>
        <label className={FIELD_LABEL} htmlFor="raw-script">
          Your script
        </label>
        <span className={FIELD_HINT}>
          Write it the way you would brief a new member of staff. The rules every agent follows,
          like always answering truthfully whether it is an AI and whether the call is
          recorded, are added for you. Put the greeting on the line after one that reads
          [OPENING].
        </span>
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

      {!proposal && (
        <div className="space-y-2">
          <button
            type="button"
            className={SECONDARY_BUTTON}
            disabled={!write.allowed || readOnly || convert.isPending || text.trim().length < 10}
            title={write.reason ?? undefined}
            onClick={() => {
              setChecked(false);
              convert.mutate({ raw_text: text }, { onSuccess: setProposal });
            }}
          >
            <Wand2 aria-hidden className="h-4 w-4" />
            {convert.isPending ? "Reading your script…" : "Turn this into sections"}
          </button>
          <p className="text-meta text-ink-muted">
            The AI suggests sections from your text and shows you every one before anything is
            replaced. It uses your account&apos;s AI allowance.
          </p>
        </div>
      )}
      {convert.error && <ProblemNotice error={convert.error} />}

      {proposal && (
        <ProposalReview
          current={structuredBase}
          proposal={proposal.script}
          onApply={(next) => {
            onConverted(next);
            setProposal(null);
          }}
          onDiscard={() => setProposal(null)}
          gate={
            proposal.unplaced.length > 0 && !checked
              ? "Read the lines that did not fit anywhere first."
              : null
          }
        >
          {proposal.disclosure && <p className="text-meta text-ink-muted">{proposal.disclosure}</p>}
          {proposal.unplaced.length === 0 ? (
            <p className="text-meta text-ink">Every line of your script has a place in these sections.</p>
          ) : (
            <NoticeBox tone="warn" title={`${proposal.unplaced.length} ${proposal.unplaced.length === 1 ? "line does" : "lines do"} not appear in the sections`}>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-meta">
                {proposal.unplaced.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
              <p className="mt-2 text-meta">
                Add them to a section after you keep the changes, or discard and edit your text.
                Your hand-written script stays in History once it has been live.
              </p>
              <label className="mt-2 flex items-start gap-2 text-meta">
                <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
                <span>I have read these lines</span>
              </label>
            </NoticeBox>
          )}
        </ProposalReview>
      )}
    </div>
  );
}
