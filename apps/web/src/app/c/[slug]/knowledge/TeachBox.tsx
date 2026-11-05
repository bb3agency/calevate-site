"use client";

import { useCallback, useId, useRef, useState } from "react";
import { Plus } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { PipMark } from "@/components/illustration/pip";
import { SavedTick } from "@/components/console/savedTick";
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
import { useBusinessCopy } from "@/lib/api/businessCopy";
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

/** Sentence starters offered before the account's own example has been written: they name
 *  what is worth teaching without putting a made-up price in the owner's box. */
const STARTERS = ["Our prices: ", "We are open ", "We serve ", "Never promise "] as const;

/** The account's own example, one tappable sentence each; at most three, so the row stays one glance. */
export function exampleSentences(note: string | null | undefined): string[] {
  return (note ?? "")
    .split(/(?<=[.!?।])\s+/u)
    .map((sentence) => sentence.trim())
    .filter(Boolean)
    .slice(0, 3);
}

/**
 * THE TEACH BOX: the "Type or say it" way of the teach card (`AddArea`), asked of Pip since
 * D-821 (founder decision 9).
 *
 * The owner types it or says it, and "Teach this" prefills Pip with the words. Pip sorts
 * them into facts (every agent gets them) and rules (how one agent should behave), and they
 * come back HERE for review: nothing is saved until the owner keeps it. A voice note is heard
 * first and its words land in the box, so a misheard price is caught before anything is
 * sorted. The examples are buttons that write into the box rather than placeholder text,
 * because a long grey sentence reads as something already filled in and vanishes on the
 * first keystroke.
 */
export function TeachBox({ allowed, reason }: { allowed: boolean; reason: string | null }) {
  const session = useClientSession();
  const eg = useVerticalExamples();
  const copy = useBusinessCopy(session);
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
  const locked = !allowed || listening;
  // Only the account's own written example is offered as sentences; the per-trade fallback
  // carries a sample price that would read as this business's own.
  const ownExample = copy.data?.placeholders?.teach_note?.trim() ? eg.teachNote : null;
  const examples = ownExample ? exampleSentences(ownExample) : [...STARTERS];
  const addExample = (text: string) => {
    setWords((now) => {
      const before = now.trimEnd();
      return before ? `${before}${ownExample ? " " : "\n"}${text}` : text;
    });
    const box = boxRef.current;
    if (box) {
      box.focus();
      // After React writes the value, so the caret lands at the end of the new words.
      requestAnimationFrame(() => box.setSelectionRange(box.value.length, box.value.length));
    }
  };

  return (
    <div className="space-y-3">
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
          {/* One well holding the words and both ways of putting them there (form-design: the
              mic belongs to the field it fills, not to the row of actions under it). The
              well, not the bare textarea, carries the focus and invalid states. */}
          <div
            className={`rounded-card border bg-surface transition-[border-color,box-shadow] duration-(--duration-fast) ease-out focus-within:border-brand focus-within:ring-2 focus-within:ring-brand/20 ${
              locked ? "border-line bg-surface-muted" : "border-line"
            } has-[textarea[aria-invalid=true]]:border-danger`}
          >
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
              disabled={locked}
              placeholder="Prices, timings, where you deliver, what never to promise…"
              className="block min-h-28 max-h-72 w-full resize-none rounded-t-card [field-sizing:content] bg-transparent px-4 pt-3 pb-2 text-body text-ink placeholder:text-ink-faint focus:outline-none disabled:cursor-not-allowed"
            />
            <div className="flex flex-wrap items-center gap-2 px-3 pb-3">
              <VoiceButton
                disabled={locked}
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
              <button
                type="submit"
                className={`${PRIMARY_BUTTON} ml-auto`}
                disabled={locked}
                title={reason ?? undefined}
              >
                Teach this
              </button>
            </div>
          </div>
          {valid.error("teach")}
          {voice.error ? <ProblemNotice error={voice.error} /> : null}
          {voice.failure ? (
            <p role="alert" className="text-sm text-ink">
              {voice.failure}
            </p>
          ) : null}
          {saved ? (
            <p className="text-meta text-ink-muted">{saved.note}</p>
          ) : (
            <p className="text-meta text-ink-muted">
              {ASSISTANT_NAME} sorts it into facts and rules. You check each one before it is saved.
            </p>
          )}
          {examples.length ? (
            <div className="space-y-2">
              <p id={`${inputId}-ideas`} className="text-meta font-medium text-ink-muted">
                {ownExample ? "Tap an example to start" : "Start with"}
              </p>
              <ul aria-labelledby={`${inputId}-ideas`} className="flex flex-wrap gap-2">
                {examples.map((text) => (
                  <li key={text} className="min-w-0 max-w-full">
                    <button
                      type="button"
                      disabled={locked}
                      onClick={() => addExample(text)}
                      className="press inline-flex max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-left text-meta text-ink [&:not(:disabled)]:hover:border-brand/40 [&:not(:disabled)]:hover:bg-brand-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:text-ink-faint touch:min-h-11"
                    >
                      <Plus aria-hidden className="h-3.5 w-3.5 shrink-0 text-brand-strong" />
                      <span className="min-w-0 [overflow-wrap:anywhere]">{text.trim()}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </form>
      )}
      {open.error ? <ProblemNotice error={open.error} onRetry={() => void open.refetch()} /> : null}
    </div>
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
      <p className="flex items-start gap-2 text-body text-ink">
        <PipMark size={16} className="mt-0.5 shrink-0" />
        Check what {ASSISTANT_NAME} found. Nothing is saved until you press Save.
      </p>
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
          disabled={discard.isPending}
          waitingFor={
            kept.length === 0 ? "Keep at least one item." : needsAgent ? "Choose which agent takes the rules." : null
          }
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
