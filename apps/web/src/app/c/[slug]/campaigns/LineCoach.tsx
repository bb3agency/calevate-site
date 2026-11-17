"use client";

/**
 * HEAR A SCENARIO'S LINE AND SAY HOW IT SHOULD SOUND (founder, 17 Nov 2026: "let the user
 * listen to how it speaks and give comments for the agent to adjust its voice").
 *
 * "Hear it" speaks the line in the campaign agent's Studio voice with its saved speed,
 * loudness and emotion (`POST /v1/agents/{id}/voice-tuning/preview-line`, the start of the
 * line, one of the account's samples for the day). A Clear voice has no sample at all, so
 * the owner is pointed at the Test call instead. Each note ("slower", "say Rytu Khata as
 * ...") is kept on the scenario for that language and reaches the agent's instructions on
 * the next save; the voice's own settings, which change the agent everywhere, are in the
 * agent bar above.
 */

import { Play, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { problemToast, useActionFeedback } from "@/components/arc/feedback";
import { useTeachVoiceNote, useVoiceNotes } from "@/lib/api/voiceNotes";
import { FIELD, SECONDARY_BUTTON_SM } from "@/components/ui";
import { useClientRealm } from "@/lib/api/session";
import { useClientVoiceTuning, useHearLine } from "@/lib/api/voiceTuning";

export type FlowAgent = {
  id: string;
  name: string;
  voiceId: string | null;
  /** The agent's name, its picker and its voice settings, drawn at the top of Script. */
  bar: ReactNode;
};

export function LineCoach({
  agent,
  language,
  line,
  notes,
  readOnly,
  onNotes,
  source,
}: {
  /** Where a note taught to the agent came from, e.g. "Call flow, scenario 2.1". */
  source: string;
  agent: FlowAgent | null;
  language: string;
  line: string;
  notes: string[];
  readOnly: boolean;
  onNotes: (notes: string[]) => void;
}) {
  const [typed, setTyped] = useState("");
  const { session } = useClientRealm();
  const agentId = agent?.id ?? "";
  const taught = useVoiceNotes(session, agentId);
  const teach = useTeachVoiceNote(session, agentId);
  useActionFeedback(teach, { errorDisplay: "inline", successToast: agent ? `Taught to ${agent.name}` : undefined });
  // On by default: each small lesson also becomes how the agent sounds on all its calls.
  const [toAgent, setToAgent] = useState(true);
  const isTaught = (note: string) =>
    (taught.data?.items ?? []).some((n) => n.language === language && n.note.toLowerCase() === note.toLowerCase());
  const add = () => {
    const note = typed.trim();
    if (!note) return;
    onNotes([...notes, note].slice(0, 10));
    if (toAgent && agentId) teach.mutate({ language, note, source });
    setTyped("");
  };
  return (
    <div className="mt-1.5 space-y-1.5">
      {agent ? <Hear agent={agent} language={language} line={line} /> : null}
      {notes.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="How it should sound">
          {notes.map((note, i) => (
            <li
              key={`${i}-${note}`}
              className="inline-flex items-center gap-1 rounded-full border border-series-4/40 bg-series-4/10 px-2 py-0.5 text-[12px] text-ink"
            >
              {note}
              {isTaught(note) && <span className="text-[10px] font-medium text-series-4">· {agent?.name}</span>}
              {!readOnly && agentId && !isTaught(note) && (
                <button
                  type="button"
                  className="text-[10px] font-medium text-brand-strong hover:underline"
                  onClick={() => teach.mutate({ language, note, source })}
                >
                  Teach {agent?.name}
                </button>
              )}
              {!readOnly && (
                <button
                  type="button"
                  aria-label={`Remove "${note}"`}
                  className="rounded-full text-ink-muted hover:text-ink"
                  onClick={() => onNotes(notes.filter((_, j) => j !== i))}
                >
                  <X aria-hidden className="h-3 w-3" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {!readOnly && (
        <div className="flex gap-1.5">
          <input
            aria-label="How should it sound?"
            className={`${FIELD} h-8 text-meta`}
            placeholder="How should it sound? e.g. slower, warmer, say Rytu Khata as రైతు ఖాతా"
            value={typed}
            maxLength={300}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
          />
          <button type="button" className={SECONDARY_BUTTON_SM} disabled={!typed.trim() || notes.length >= 10} onClick={add}>
            Add
          </button>
        </div>
      )}
      {!readOnly && agentId && (
        <label className="flex items-center gap-1.5 text-[11px] text-ink-muted">
          <input type="checkbox" className="h-3.5 w-3.5 accent-brand-strong" checked={toAgent} onChange={(e) => setToAgent(e.target.checked)} />
          Also teach {agent?.name}, so it sounds this way on all its calls
        </label>
      )}
      {teach.error != null && (
        <p role="alert" className="text-[12px] text-danger">
          {problemToast(teach.error, "It could not be taught").description ?? "It could not be taught"}
        </p>
      )}
    </div>
  );
}

function Hear({ agent, language, line }: { agent: FlowAgent; language: string; line: string }) {
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
      <p className="text-[12px] text-ink-muted">
        {agent.name}&apos;s voice is a Clear voice, which has no sample. Use Test call to hear this line on a call.
      </p>
    );
  }
  const left = tuning.data.previews_left_today;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={!line.trim() || hear.isPending || left === 0}
        title={left === 0 ? "No samples left today." : "Speaks the start of this line in the agent's voice."}
        onClick={() =>
          hear.mutate(
            { text: line, language },
            {
              onSuccess: (blob) => {
                setSrc((old) => {
                  if (old) URL.revokeObjectURL(old);
                  return URL.createObjectURL(blob);
                });
              },
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
