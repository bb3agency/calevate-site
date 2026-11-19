"use client";

/**
 * HEAR A SCENARIO'S LINE IN THE AGENT'S VOICE (founder, 17-18 Nov 2026: "only give the option
 * to hear in the agent's voice, how it says").
 *
 * Speaks the start of the line in the campaign agent's Studio voice with its saved speed,
 * loudness and emotion (`POST /v1/agents/{id}/voice-tuning/preview-line`, one of the
 * account's samples for the day). A Clear voice has no sample, so the owner is pointed at the
 * Test call instead.
 */

import { Play } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { problemToast, useActionFeedback } from "@/components/arc/feedback";
import { SECONDARY_BUTTON_SM } from "@/components/ui";
import type { WriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useClientVoiceTuning, useHearLine } from "@/lib/api/voiceTuning";

export type FlowAgent = {
  /** Empty while the campaign has no agent to speak. */
  id: string;
  name: string;
  voiceId: string | null;
  /** What the editor shows when there is no agent: the way to choose one. */
  missing: ReactNode;
};

type HearProps = {
  language: string;
  line: string;
  /** The sample route is the owner's (`org:manage`); anyone else sees why it is closed. */
  access: WriteAccess;
};

export function HearLine({ agent, ...rest }: HearProps & { agent: FlowAgent | null }) {
  if (!agent?.id) return null;
  return <Hear agent={agent} {...rest} />;
}

function Hear({ agent, language, line, access }: HearProps & { agent: FlowAgent }) {
  const { session } = useClientRealm();
  const tuning = useClientVoiceTuning(session, agent.id, agent.voiceId);
  const hear = useHearLine(session, agent.id, agent.voiceId);
  useActionFeedback(hear, { errorDisplay: "inline" });
  const [src, setSrc] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  useEffect(() => () => void (src && URL.revokeObjectURL(src)), [src]);
  useEffect(() => {
    if (src) void audio.current?.play().catch(() => undefined);
  }, [src]);

  if (!tuning.data) return null;
  if (!tuning.data.studio) {
    return (
      <p className="mt-1.5 text-[12px] text-ink-muted">
        {agent.name}&apos;s voice is a Clear voice, which has no sample. Use Test call to hear this line on a call.
      </p>
    );
  }
  const left = tuning.data.previews_left_today;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-2">
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={!access.allowed || !line.trim() || hear.isPending || left === 0}
        title={
          !access.allowed
            ? (access.reason ?? undefined)
            : left === 0
              ? "No samples left today."
              : "Speaks the start of this line in the agent's voice."
        }
        onClick={() =>
          hear.mutate(
            { text: line, language },
            {
              onSuccess: (blob) =>
                setSrc((old) => {
                  if (old) URL.revokeObjectURL(old);
                  return URL.createObjectURL(blob);
                }),
            },
          )
        }
      >
        <Play aria-hidden className="h-3.5 w-3.5" />
        {hear.isPending ? "Speaking…" : `Hear it in ${agent.name}'s voice`}
      </button>
      {left != null && <span className="text-[11px] text-ink-faint">{left} samples left today</span>}
      {src && (
        // eslint-disable-next-line jsx-a11y/media-has-caption -- a spoken sample of the line written just above it
        <audio ref={audio} src={src} controls className="h-8 max-w-full" />
      )}
      {hear.error != null && (
        <p role="alert" className="w-full text-[12px] text-danger">
          {problemToast(hear.error, "It could not be spoken").description ?? "It could not be spoken"}
        </p>
      )}
    </div>
  );
}
