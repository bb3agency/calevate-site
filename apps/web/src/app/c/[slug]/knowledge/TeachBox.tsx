"use client";

import { useCallback, useId, useRef, useState } from "react";


import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { PipMark } from "@/components/illustration/pip";
import { SavedTick } from "@/components/console/savedTick";
import { Section } from "@/components/console/section";
import {
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { VoiceButton } from "@/components/voiceButton";
import { useFormValidation } from "@/components/formValidation";
import { useAgents } from "@/lib/api/agents";
import { useClientSession } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { openAssistant } from "@/lib/copilot/launcher";
import { useVerticalExamples } from "@/lib/useVerticalExamples";
import { useVoiceWords } from "@/components/improvement/useVoiceWords";
import {
  isTeachingBusy,
  useDiscardTeaching,
  useOpenTeaching,
  useSaveTeaching,
  type TeachItem,
  type Teaching,
} from "@/lib/api/teach";

import { useKnowledgeCopilot } from "./copilot";

/** What Pip is asked, in the words the owner sees in its ask box. */
export function teachRequest(words: string): string {
  return `Teach my agents this: ${words}`;
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
  headingLevel = 2,
  framed = true,
}: {
  allowed: boolean;
  reason: string | null;
  /** 3 inside an agent's Training tab, whose tab label is the h2. */
  headingLevel?: 2 | 3;
  /** False inside a container that already names the box (the knowledge page's Add area). */
  framed?: boolean;
}) {
  const session = useClientSession();
  const eg = useVerticalExamples();
  const open = useOpenTeaching(session);
  const [words, setWords] = useState("");
  // What the last save did, said beside the box it came back to (REDESIGN-2: saves are
  // confirmed where the person is looking, never by a toast).
  const [saved, setSaved] = useState<{ note: string; at: number } | null>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const inputId = useId();
  const valid = useFormValidation();
  const teachField = valid.field("teach", "Write what your agents should know.");

  useKnowledgeCopilot({ body: words, setBody: setWords });

  // A voice note's words go into the box for the owner to check.
  const voice = useVoiceWords(
    session,
    useCallback((heard: string) => {
      setWords((current) => [current.trim(), heard].filter(Boolean).join("\n"));
      boxRef.current?.focus();
    }, []),
  );
  const listening = voice.listening;
  const current = open.data ?? null;

  const body = (
    <>
      {current && current.status === "ready" ? (
        <Review
          teaching={current}
          onSaved={(saveNote) => {
            setSaved({ note: saveNote, at: Date.now() });
            setWords("");
          }}
        />
      ) : current && isTeachingBusy(current.status) ? (
        <Working />
      ) : (
        <form
          className="space-y-3"
          noValidate
          onSubmit={valid.onSubmit(() => openAssistant({ prompt: teachRequest(words.trim()) }))}
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
          {voice.error ? <ProblemNotice error={voice.error} /> : null}
          {voice.failure ? (
            <p role="alert" className="text-sm text-ink">
              {voice.failure}
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
                voice.record(blob);
              }}
              onTypeInstead={() => boxRef.current?.focus()}
            />
            {listening ? (
              <span role="status" className="text-meta text-ink-muted">
                <span className="text-shimmer">Listening…</span>
              </span>
            ) : null}
            {saved ? <SavedTick at={saved.at} /> : null}
          </div>
          {saved ? <p className="text-meta text-ink-muted">{saved.note}</p> : null}
          {/* Unframed, the Add area offers files in its own File view, Pip's reading included. */}
          {framed ? (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line pt-3">
              <p className="text-meta text-ink-muted">Have a photo or file?</p>
              <AskAssistant label={`Let ${ASSISTANT_NAME} read a photo or file`} prompt={READ_FILE_REQUEST} disabled={!allowed} />
            </div>
          ) : null}
        </form>
      )}
      {open.error ? <ProblemNotice error={open.error} onRetry={() => void open.refetch()} /> : null}
    </>
  );

  // Unframed inside the knowledge page's Add area, which carries its own heading.
  if (!framed) return <div className="space-y-3">{body}</div>;
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
      {body}
    </Section>
  );
}

function Working() {
  const label = `${ASSISTANT_NAME} is sorting it…`;
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
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const discardFeedback = useActionFeedback(discard, { errorDisplay: "inline" });
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
        <p className="text-sm text-ink-muted">Nothing to keep in that.</p>
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
        <p className="text-meta text-ink-muted">No agents yet. Keep these as facts.</p>
      ) : null}

      {save.error ? <ProblemNotice error={save.error} /> : null}
      {discard.error ? <ProblemNotice error={discard.error} /> : null}
      <div className="flex flex-wrap items-center gap-2">
        <ActionButton
          status={saveFeedback.status}
          pendingLabel="Saving…"
          successLabel="Saved"
          disabled={kept.length === 0 || needsAgent || discard.isPending}
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
                      ? "Facts arrive soon. Rules wait until the script is live."
                      : "Your agents know this in a minute or two.",
                  ),
              },
            )
          }
        >
          {kept.length ? `Save ${summary}` : "Save"}
        </ActionButton>
        <ActionButton
          variant="secondary"
          status={discardFeedback.status}
          successLabel="Discarded"
          disabled={save.isPending}
          onClick={() => discardFeedback.run(teaching.id)}
        >
          Discard
        </ActionButton>
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
