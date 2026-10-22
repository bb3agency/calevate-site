"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Mic, Square } from "lucide-react";

import { AskAssistant } from "@/components/copilot/AskAssistant";
import { PipMark } from "@/components/illustration/pip";
import { SavedTick } from "@/components/console/savedTick";
import { Section } from "@/components/console/section";
import {
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { ModalDialog } from "@/components/modalDialog";
import { useFormValidation } from "@/components/formValidation";
import { useAgents } from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { openAssistant } from "@/lib/copilot/launcher";
import { lookup } from "@/lib/lookup";
import { useVerticalExamples } from "@/lib/useVerticalExamples";
import {
  isTeachingBusy,
  useDiscardTeaching,
  useHearVoiceNote,
  useOpenTeaching,
  useSaveTeaching,
  useTeaching,
  type TeachItem,
  type Teaching,
} from "@/lib/api/teach";

import { useKnowledgeCopilot } from "./copilot";

/** The voice note stops itself here: the speech-to-text step takes clips under 30 s. */
const MAX_RECORDING_S = 30;

const FAILURE: Record<string, string> = {
  voice_unreadable: "We could not hear that recording. Try again somewhere quieter, or type it.",
  nothing_heard: "We did not hear any words. Try recording again, or type it.",
  upload_missing: "That recording went missing. Record it again.",
};

/** What Pip is asked, in the words the owner sees in its ask box. */
export function teachRequest(words: string, question: string | null): string {
  return question
    ? `Teach my agents the answer to a caller who asked “${question}”: ${words}`
    : `Teach my agents this: ${words}`;
}
export const READ_FILE_REQUEST = "Read the photo or file I attach and teach my agents what it says.";

/** One row of the review, with what the owner decided about it. */
type ReviewItem = TeachItem & { key: number; keep: boolean };

/**
 * THE TEACH BOX: one place to tell the agents something (founder decision 9), asked of Pip
 * since D-821.
 *
 * The owner types it or says it here, and "Let Pip teach it" prefills Pip with the words; a
 * photo of a price list or a file is attached in Pip itself, which reads it. Pip sends the
 * words to be sorted into facts (every agent gets them) and rules (how one agent should
 * behave), and they come back HERE for review: nothing is saved until the owner keeps it.
 * A voice note is heard first and its words land in the box, so a misheard price is caught
 * before anything is sorted.
 */
export function TeachBox({
  allowed,
  reason,
  answering,
  headingLevel = 2,
}: {
  allowed: boolean;
  reason: string | null;
  /** Set by "Add the answer" on a struggle: what the caller asked, and its question id. */
  answering?: { gapId: string | null; question: string; key: number } | null;
  /** 3 inside an agent's Training tab, whose tab label is the h2. */
  headingLevel?: 2 | 3;
}) {
  const session = useClientSession();
  const eg = useVerticalExamples();
  const hear = useHearVoiceNote(session);
  const discardHeard = useDiscardTeaching(session);
  const open = useOpenTeaching(session);
  const [words, setWords] = useState("");
  const [linkedGap, setLinkedGap] = useState<string | null>(null);
  const [asked, setAsked] = useState<string | null>(null);
  const [heardId, setHeardId] = useState<string | null>(null);
  const [voiceFailure, setVoiceFailure] = useState<string | null>(null);
  const heard = useTeaching(session, heardId);
  // What the last save did, said beside the box it came back to (REDESIGN-2: saves are
  // confirmed where the person is looking, never by a toast).
  const [saved, setSaved] = useState<{ note: string; at: number } | null>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const inputId = useId();
  const valid = useFormValidation();
  const teachField = valid.field("teach", "Write what your agents should know.");

  useKnowledgeCopilot({
    body: words,
    setBody: setWords,
    answering: asked ? { gapId: linkedGap, question: asked } : null,
  });

  useEffect(() => {
    if (!answering) return;
    setWords("");
    setAsked(answering.question);
    setLinkedGap(answering.gapId);
    boxRef.current?.scrollIntoView?.({ block: "center" });
    boxRef.current?.focus();
  }, [answering]);

  // A voice note's words go into the box for the owner to check; the heard teaching has
  // done its job and is discarded.
  const note = heard.data;
  const discardNote = discardHeard.mutate;
  useEffect(() => {
    if (!note || note.id !== heardId) return;
    if (note.status === "heard") {
      setWords((current) => [current.trim(), note.words ?? ""].filter(Boolean).join("\n"));
      setHeardId(null);
      discardNote(note.id);
      boxRef.current?.focus();
    } else if (note.status === "failed") {
      setVoiceFailure(note.error_code ?? "voice_unreadable");
      setHeardId(null);
    }
  }, [note, heardId, discardNote]);

  const listening = hear.isPending || (heardId !== null && note?.status !== "heard" && note?.status !== "failed");
  const current = open.data ?? null;

  return (
    <Section
      headingLevel={headingLevel}
      title="Teach your agents"
      info={
        <p>
          Type it or say it, or attach a photo of a price list or a file in {ASSISTANT_NAME}.{" "}
          {ASSISTANT_NAME} sorts it into facts, which every agent gets, and rules for how one agent
          should behave. You check each one here before it is saved.
        </p>
      }
    >
      {current && current.status === "ready" ? (
        <Review
          teaching={current}
          onSaved={(saveNote) => {
            setSaved({ note: saveNote, at: Date.now() });
            setWords("");
            setAsked(null);
            setLinkedGap(null);
          }}
        />
      ) : current && isTeachingBusy(current.status) ? (
        <Working />
      ) : (
        <form
          className="space-y-3"
          noValidate
          onSubmit={valid.onSubmit(() => openAssistant({ prompt: teachRequest(words.trim(), asked) }))}
        >
          <label htmlFor={inputId} className="sr-only">
            What should your agents know?
          </label>
          <textarea
            {...teachField}
            required
            minLength={3}
            id={inputId}
            ref={(node) => {
              teachField.ref(node);
              boxRef.current = node;
            }}
            rows={4}
            value={words}
            onChange={(event) => setWords(event.target.value)}
            disabled={!allowed || listening}
            placeholder={`For example: ${eg.teachNote}`}
            className={`${FIELD} mt-0`}
          />
          {valid.error("teach")}
          {hear.error ? <ProblemNotice error={hear.error} /> : null}
          {discardHeard.error ? <ProblemNotice error={discardHeard.error} /> : null}
          {voiceFailure ? (
            <p role="alert" className="text-sm text-ink">
              {lookup(FAILURE, voiceFailure) ?? "We could not hear that recording. Type it instead."}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <button type="submit" className={PRIMARY_BUTTON} disabled={!allowed || listening} title={reason ?? undefined}>
              Let {ASSISTANT_NAME} teach it
            </button>
            <VoiceButton
              disabled={!allowed || listening}
              onRecorded={(blob) => {
                setSaved(null);
                setVoiceFailure(null);
                hear.mutate({ file: blob }, { onSuccess: (started) => setHeardId(started.id) });
              }}
              onTypeInstead={() => boxRef.current?.focus()}
            />
            {listening ? (
              <span role="status" className="text-meta text-ink-muted">
                <span className="text-shimmer">Listening to your voice note…</span>
              </span>
            ) : null}
            {saved ? <SavedTick at={saved.at} /> : null}
          </div>
          {saved ? <p className="text-meta text-ink-muted">{saved.note}</p> : null}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line pt-3">
            <p className="text-meta text-ink-muted">
              A photo of a price list or menu, or a Word, text, CSV or Excel file: attach it in{" "}
              {ASSISTANT_NAME}.
            </p>
            <AskAssistant label={`Let ${ASSISTANT_NAME} read a photo or file`} prompt={READ_FILE_REQUEST} disabled={!allowed} />
          </div>
          {asked ? (
            <p className="text-meta text-ink-muted">
              Answering a caller who asked &ldquo;{asked}&rdquo;.{" "}
              <button
                type="button"
                className="underline"
                onClick={() => {
                  setAsked(null);
                  setLinkedGap(null);
                }}
              >
                Not that
              </button>
            </p>
          ) : null}
        </form>
      )}
      {open.error ? <ProblemNotice error={open.error} onRetry={() => void open.refetch()} /> : null}
    </Section>
  );
}

function Working() {
  const label = `${ASSISTANT_NAME} is sorting it into facts and rules…`;
  return (
    <div className="space-y-3">
      <p className="flex items-center gap-2 text-sm text-ink-muted" aria-hidden>
        <PipMark size={16} thinking className="shrink-0" />
        {label}
      </p>
      <Skeleton rows={3} label={label} />
    </div>
  );
}

/** What the browser says about the microphone before we ask for it. */
async function microphonePermission(): Promise<PermissionState | "unknown"> {
  try {
    const status = await navigator.permissions?.query({ name: "microphone" as PermissionName });
    return status?.state ?? "unknown";
  } catch {
    // Safari and Firefox may not know the "microphone" name, or the API at all.
    return "unknown";
  }
}

function errorName(error: unknown): string {
  return error instanceof Error || error instanceof DOMException ? error.name : "";
}

/**
 * "Say it". The browser's own microphone prompt is easy to miss or dismiss, and once
 * refused it never shows again, so we explain before it appears: already allowed records
 * straight away; not yet asked opens our dialog, whose button triggers the browser's
 * prompt; blocked opens the same dialog saying how to unblock it.
 */
export function VoiceButton({
  disabled,
  onRecorded,
  onTypeInstead,
}: {
  disabled: boolean;
  onRecorded: (blob: Blob) => void;
  /** Close the question and put the cursor in the text box. */
  onTypeInstead: () => void;
}) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState<"ask" | "blocked" | null>(null);
  const [starting, setStarting] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stop = () => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    recorder.current?.stop();
    setRecording(false);
  };

  useEffect(() => () => stop(), []);

  const start = async () => {
    setStarting(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setAsking(null);
      const type = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      const media = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      const chunks: Blob[] = [];
      media.ondataavailable = (event) => chunks.push(event.data);
      media.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunks, { type: media.mimeType.split(";")[0] || "audio/webm" });
        if (blob.size > 0) onRecorded(blob);
      };
      recorder.current = media;
      media.start();
      setSeconds(0);
      setRecording(true);
      timer.current = setInterval(() => {
        setSeconds((s) => {
          if (s + 1 >= MAX_RECORDING_S) stop();
          return s + 1;
        });
      }, 1000);
    } catch (caught) {
      const name = errorName(caught);
      if (name === "NotAllowedError") {
        setAsking("blocked");
      } else {
        setAsking(null);
        setError(
          name === "NotFoundError"
            ? "No microphone found on this device."
            : "We could not use your microphone. Allow it in your browser, or type it.",
        );
      }
    } finally {
      setStarting(false);
    }
  };

  const press = async () => {
    setError(null);
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setError("This browser cannot record. Type it instead.");
      return;
    }
    const state = await microphonePermission();
    if (state === "granted") {
      await start();
      return;
    }
    setAsking(state === "denied" ? "blocked" : "ask");
  };

  const typeInstead = () => {
    setAsking(null);
    // After the dialog has handed focus back to "Say it", so the text box keeps it.
    setTimeout(onTypeInstead, 0);
  };

  return (
    <>
      {recording ? (
        <button type="button" className={SECONDARY_BUTTON} onClick={stop}>
          <Square aria-hidden className="h-3.5 w-3.5 fill-current text-danger" />
          Stop · <span className="tabular-nums">0:{String(seconds).padStart(2, "0")}</span>
        </button>
      ) : (
        <button
          type="button"
          className={SECONDARY_BUTTON}
          onClick={() => void press()}
          disabled={disabled || starting}
        >
          <Mic aria-hidden className="h-4 w-4" />
          Say it
        </button>
      )}
      {recording ? (
        <span className="text-meta text-ink-muted" aria-live="polite">
          Recording, up to {MAX_RECORDING_S} seconds
        </span>
      ) : null}
      {error ? (
        <p role="alert" className="basis-full text-meta text-danger">
          {error}
        </p>
      ) : null}
      {asking ? (
        <ModalDialog
          title={asking === "blocked" ? "Your microphone is blocked" : "Allow your microphone"}
          description={
            <p>
              {asking === "blocked"
                ? "Turn it on for this site: click the icon at the left of the address bar, set Microphone to Allow, then press Try again."
                : "Say what your agents should know. Your browser will ask to use the microphone; choose Allow."}
            </p>
          }
          onClose={() => setAsking(null)}
          actions={
            <>
              <button type="button" className={SECONDARY_BUTTON} onClick={typeInstead}>
                Type it instead
              </button>
              <button type="button" className={PRIMARY_BUTTON} onClick={() => void start()} disabled={starting}>
                {asking === "blocked" ? "Try again" : "Allow microphone"}
              </button>
            </>
          }
        />
      ) : null}
    </>
  );
}

function Review({
  teaching,
  onSaved,
}: {
  teaching: Teaching;
  /** Called with what the save means for the agents, in one sentence. */
  onSaved: (note: string) => void;
}) {
  const session = useClientSession();
  const agents = useAgents(session);
  const save = useSaveTeaching(session);
  const discard = useDiscardTeaching(session);
  const [items, setItems] = useState<ReviewItem[]>(() =>
    teaching.items.map((item, key) => ({ ...item, key, keep: true })),
  );
  const [agentId, setAgentId] = useState<string>("");
  // Undefined until the agents are read; a failed read is shown beside the agent choice.
  const agentList = agents.data;
  const onlyAgent = agentList?.length === 1 ? agentList[0]!.id : "";
  const chosenAgent = agentId || onlyAgent;
  const kept = items.filter((item) => item.keep && item.text.trim());
  const facts = kept.filter((item) => item.kind === "fact").length;
  const rules = kept.length - facts;
  const needsAgent = rules > 0 && !chosenAgent;

  const update = (key: number, patch: Partial<ReviewItem>) =>
    setItems((all) => all.map((item) => (item.key === key ? { ...item, ...patch } : item)));

  const summary = [
    facts ? `${facts} fact${facts === 1 ? "" : "s"}` : null,
    rules ? `${rules} rule${rules === 1 ? "" : "s"}` : null,
  ]
    .filter(Boolean)
    .join(" and ");

  return (
    <div className="space-y-4">
      {teaching.note ? <p className="text-meta text-ink-muted">{teaching.note}</p> : null}
      {items.length === 0 ? (
        <p className="text-sm text-ink-muted">We found nothing to keep in that.</p>
      ) : (
        <ul className="divide-y divide-line border-y border-line" aria-label="Check what we found">
          {items.map((item) => (
            <ReviewRow key={item.key} item={item} onChange={(patch) => update(item.key, patch)} />
          ))}
        </ul>
      )}

      {rules > 0 && agents.isError ? (
        <ProblemNotice error={agents.error} onRetry={() => void agents.refetch()} />
      ) : null}
      {rules > 0 && agentList && agentList.length > 1 ? (
        <div>
          <label htmlFor="teach-agent" className={FIELD_LABEL}>
            Which agent are the rules for?
          </label>
          <select
            id="teach-agent"
            value={agentId}
            onChange={(event) => setAgentId(event.target.value)}
            className={`${FIELD} max-w-sm`}
          >
            <option value="">Choose an agent</option>
            {agentList.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {rules > 0 && agentList && agentList.length === 0 ? (
        <p className="text-meta text-ink-muted">
          Rules belong to an agent, and you have none yet. Keep them as facts, or add an agent
          first.
        </p>
      ) : null}

      {save.error ? <ProblemNotice error={save.error} /> : null}
      {discard.error ? <ProblemNotice error={discard.error} /> : null}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={PRIMARY_BUTTON}
          disabled={kept.length === 0 || needsAgent || save.isPending}
          onClick={() =>
            save.mutate(
              {
                id: teaching.id,
                items: kept.map(({ kind, text, pinned }) => ({
                  kind,
                  text: text.trim(),
                  pinned: kind === "fact" && Boolean(pinned),
                })),
                agentId: rules > 0 ? chosenAgent : null,
              },
              {
                onSuccess: (saved) =>
                  onSaved(
                    saved.rules_added > 0
                      ? "Facts reach your agents in a minute or two. The rules wait in the agent's script until you put it live."
                      : "Your agents will know this in a minute or two.",
                  ),
              },
            )
          }
        >
          {save.isPending ? "Saving…" : kept.length ? `Save ${summary}` : "Save"}
        </button>
        <button
          type="button"
          className={SECONDARY_BUTTON}
          disabled={save.isPending}
          onClick={() => discard.mutate(teaching.id)}
        >
          Discard
        </button>
      </div>
    </div>
  );
}

function ReviewRow({
  item,
  onChange,
}: {
  item: ReviewItem;
  onChange: (patch: Partial<ReviewItem>) => void;
}) {
  const [editing, setEditing] = useState(false);
  const id = useId();
  return (
    <li className={`py-3 ${item.keep ? "" : "opacity-60"}`}>
      <div className="flex items-start gap-3">
        <input
          id={`${id}-keep`}
          type="checkbox"
          checked={item.keep}
          onChange={(event) => onChange({ keep: event.target.checked })}
          className="mt-1 h-4 w-4 shrink-0 accent-brand-strong"
          aria-label={`Keep: ${item.text}`}
        />
        <div className="min-w-0 flex-1 space-y-2">
          <p className="text-meta font-medium text-ink-muted">
            {item.kind === "fact" ? (item.pinned ? "Fact, pinned" : "Fact") : "Rule"}
          </p>
          {editing ? (
            <textarea
              aria-label="Edit"
              rows={2}
              value={item.text}
              onChange={(event) => onChange({ text: event.target.value })}
              onBlur={() => setEditing(false)}
              className={`${FIELD} mt-0`}
            />
          ) : (
            <p className="text-sm text-ink [overflow-wrap:anywhere]">{item.text}</p>
          )}
          {item.keep ? (
            <div className="flex flex-wrap gap-2">
              <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setEditing(!editing)}>
                {editing ? "Done" : "Edit"}
              </button>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                onClick={() =>
                  onChange({ kind: item.kind === "fact" ? "rule" : "fact", pinned: false })
                }
              >
                {item.kind === "fact" ? "It's a rule" : "It's a fact"}
              </button>
              {item.kind === "fact" ? (
                <button
                  type="button"
                  aria-pressed={Boolean(item.pinned)}
                  className={SECONDARY_BUTTON_SM}
                  onClick={() => onChange({ pinned: !item.pinned })}
                >
                  {item.pinned ? "Unpin" : "Pin"}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </li>
  );
}
