"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Mic, Square } from "lucide-react";

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
import { FileDrop } from "@/components/fileDrop";
import { useFormValidation } from "@/components/formValidation";
import { useToast } from "@/components/interior/toaster";
import { useAgents } from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import {
  isTeachingBusy,
  useConfirmWords,
  useDiscardTeaching,
  useSaveTeaching,
  useStartTeaching,
  useTeaching,
  type TeachItem,
  type Teaching,
} from "@/lib/api/teach";

import { useKnowledgeCopilot } from "./copilot";

/** The voice note stops itself here: the speech-to-text step takes clips under 30 s. */
const MAX_RECORDING_S = 30;

/** A photo is read by the reading step, whose ceiling this is. */
const MAX_PHOTO_MB = 12;

const FAILURE: Record<string, string> = {
  voice_unreadable: "We could not hear that recording. Try again somewhere quieter, or type it.",
  nothing_heard: "We did not hear any words. Try recording again, or type it.",
  photo_reading_unavailable: "Reading photos is switched off at the moment. Type it instead.",
  unreadable: "We could not read that file. Try a clearer photo, or type it.",
  nothing_read: "We found no words in that. Try a clearer photo, or type it.",
  upload_missing: "That upload went missing. Send it again.",
};

/** One row of the review, with what the owner decided about it. */
type ReviewItem = TeachItem & { key: number; keep: boolean };

/**
 * THE TEACH BOX: one place to tell the agents something, by typing, a photo or a file, or
 * a voice note (founder decision 9).
 *
 * Whatever is given comes back sorted into facts (what is true about the business; every
 * agent gets them) and rules (how one agent should behave; they wait in its script). The
 * owner reviews each before anything is saved. A voice note shows its words first, so a
 * misheard price is caught before it is sorted.
 */
export function TeachBox({
  allowed,
  reason,
  answering,
}: {
  allowed: boolean;
  reason: string | null;
  /** Set by "Add the answer" on a struggle: what the caller asked, and its question id. */
  answering?: { gapId: string | null; question: string; key: number } | null;
}) {
  const session = useClientSession();
  const start = useStartTeaching(session);
  const [words, setWords] = useState("");
  const [teachingId, setTeachingId] = useState<string | null>(null);
  const [linkedGap, setLinkedGap] = useState<string | null>(null);
  const [asked, setAsked] = useState<string | null>(null);
  const teaching = useTeaching(session, teachingId);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const inputId = useId();
  const valid = useFormValidation();
  const teachField = valid.field("teach", "Write what your agents should know.");

  useKnowledgeCopilot({ body: words, setBody: setWords });

  useEffect(() => {
    if (!answering) return;
    setWords("");
    setAsked(answering.question);
    setLinkedGap(answering.gapId);
    setTeachingId(null);
    boxRef.current?.scrollIntoView?.({ block: "center" });
    boxRef.current?.focus();
  }, [answering]);

  const reset = () => {
    setTeachingId(null);
    setWords("");
    setLinkedGap(null);
    setAsked(null);
    start.reset();
  };

  const begin = (
    input:
      | { kind: "text"; words: string }
      | { kind: "photo" | "file" | "voice"; file: Blob; filename: string },
  ) =>
    start.mutate(
      { ...input, gapId: linkedGap },
      { onSuccess: (created) => setTeachingId(created.id) },
    );

  const current = teaching.data;
  const working = start.isPending || (teachingId !== null && (!current || isTeachingBusy(current.status)));

  return (
    <Section
      title="Teach your agents"
      info={
        <p>
          Type it, send a photo of a price list, or say it. We sort what you give into facts,
          which every agent gets, and rules for how one agent should behave. You check each
          one before it is saved.
        </p>
      }
    >
      {teachingId === null ? (
        <form
          className="space-y-3"
          noValidate
          onSubmit={valid.onSubmit(() => begin({ kind: "text", words: words.trim() }))}
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
            disabled={!allowed || start.isPending}
            placeholder={
              "For example: Red chilli powder is ₹120 for 250 g. We deliver in Kukatpally " +
              "and Miyapur. Never promise same-day delivery."
            }
            className={`${FIELD} mt-0`}
          />
          {valid.error("teach")}
          {start.error ? <ProblemNotice error={start.error} /> : null}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="submit"
              className={PRIMARY_BUTTON}
              disabled={!allowed || start.isPending}
              title={reason ?? undefined}
            >
              {start.isPending ? "Sending…" : "Sort it"}
            </button>
            <VoiceButton
              disabled={!allowed || start.isPending}
              onRecorded={(blob) => begin({ kind: "voice", file: blob, filename: "voice-note.webm" })}
            />
          </div>
          <FileDrop
            label="Or send a photo or a file"
            hint={`A photo of a price list or menu, up to ${MAX_PHOTO_MB} MB, or a Word, text, CSV or Excel file.`}
            accept={TEACH_ACCEPT}
            validate={teachFileProblem}
            disabled={!allowed || start.isPending}
            onFiles={([file]) => {
              if (!file) return;
              begin({
                kind: file.type.startsWith("image/") ? "photo" : "file",
                file,
                filename: file.name,
              });
            }}
          />
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
      ) : teaching.error ? (
        <ProblemNotice error={teaching.error} onRetry={() => void teaching.refetch()} />
      ) : working || !current ? (
        <Working teaching={current} />
      ) : current.status === "heard" ? (
        <CheckWords teaching={current} onCancel={reset} />
      ) : current.status === "ready" ? (
        <Review teaching={current} onDone={reset} />
      ) : current.status === "failed" ? (
        <div className="space-y-3">
          <p role="alert" className="text-sm text-ink">
            {lookup(FAILURE, current.error_code) ?? "Something went wrong. Try again, or type it."}
          </p>
          <button type="button" className={SECONDARY_BUTTON} onClick={reset}>
            Start again
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-ink-muted">That one is finished.</p>
          <button type="button" className={SECONDARY_BUTTON} onClick={reset}>
            Teach something else
          </button>
        </div>
      )}
    </Section>
  );
}

function Working({ teaching }: { teaching: Teaching | undefined }) {
  const label =
    teaching?.status === "reading"
      ? teaching.input_kind === "voice"
        ? "Listening to your voice note…"
        : "Reading what you sent…"
      : teaching?.status === "sorting" || teaching?.status === "queued"
        ? "Sorting into facts and rules…"
        : "Sending…";
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-muted" aria-hidden>
        {label}
      </p>
      <Skeleton rows={3} label={label} />
    </div>
  );
}

/** What the reading step takes. A dropped file bypasses `accept`, so this is checked too. */
const TEACH_ACCEPT = "image/*,.docx,.txt,.csv,.xlsx";
const TEACH_DOCUMENT_EXTENSIONS = [".docx", ".txt", ".csv", ".xlsx"];

function teachFileProblem(file: File): string | null {
  const isPhoto = file.type.startsWith("image/");
  const name = file.name.toLowerCase();
  if (!isPhoto && !TEACH_DOCUMENT_EXTENSIONS.some((extension) => name.endsWith(extension))) {
    return "Send a photo, or a Word, text, CSV or Excel file.";
  }
  if (file.size === 0) return "That file is empty.";
  if (isPhoto && file.size > MAX_PHOTO_MB * 1024 * 1024) {
    return `That photo is over ${MAX_PHOTO_MB} MB. Send a smaller one.`;
  }
  return null;
}

function VoiceButton({
  disabled,
  onRecorded,
}: {
  disabled: boolean;
  onRecorded: (blob: Blob) => void;
}) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stop = () => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    recorder.current?.stop();
    setRecording(false);
  };

  useEffect(() => () => stop(), []);

  const record = async () => {
    setError(null);
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setError("This browser cannot record. Type it instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
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
    } catch {
      setError("We could not use your microphone. Allow it in your browser, or type it.");
    }
  };

  return (
    <>
      {recording ? (
        <button type="button" className={SECONDARY_BUTTON} onClick={stop}>
          <Square aria-hidden className="h-3.5 w-3.5 fill-current text-danger" />
          Stop · <span className="tabular-nums">0:{String(seconds).padStart(2, "0")}</span>
        </button>
      ) : (
        <button type="button" className={SECONDARY_BUTTON} onClick={() => void record()} disabled={disabled}>
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
    </>
  );
}

function CheckWords({ teaching, onCancel }: { teaching: Teaching; onCancel: () => void }) {
  const session = useClientSession();
  const confirm = useConfirmWords(session);
  const discard = useDiscardTeaching(session);
  const [words, setWords] = useState(teaching.words ?? "");
  const id = useId();
  return (
    <form
      className="space-y-3"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (words.trim()) confirm.mutate({ id: teaching.id, words: words.trim() });
      }}
    >
      <label htmlFor={id} className={FIELD_LABEL}>
        This is what we heard. Fix anything we got wrong.
      </label>
      <textarea
        id={id}
        rows={4}
        value={words}
        onChange={(event) => setWords(event.target.value)}
        className={`${FIELD} mt-0`}
      />
      {confirm.error ? <ProblemNotice error={confirm.error} /> : null}
      {discard.error ? <ProblemNotice error={discard.error} /> : null}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={PRIMARY_BUTTON} disabled={confirm.isPending || !words.trim()}>
          {confirm.isPending ? "Sending…" : "Sort it"}
        </button>
        <button
          type="button"
          className={SECONDARY_BUTTON}
          onClick={() => discard.mutate(teaching.id, { onSuccess: onCancel })}
        >
          Start again
        </button>
      </div>
    </form>
  );
}

function Review({ teaching, onDone }: { teaching: Teaching; onDone: () => void }) {
  const session = useClientSession();
  const agents = useAgents(session);
  const save = useSaveTeaching(session);
  const discard = useDiscardTeaching(session);
  const { toast } = useToast();
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
                onSuccess: (saved) => {
                  toast({
                    tone: "success",
                    title: "Saved",
                    description:
                      saved.rules_added > 0
                        ? "Facts reach your agents in a minute or two. The rules wait in the agent's script until you put it live."
                        : "Your agents will know this in a minute or two.",
                  });
                  onDone();
                },
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
          onClick={() => discard.mutate(teaching.id, { onSuccess: onDone })}
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
