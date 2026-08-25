"use client";

/**
 * The structured call-script builder (client realm). Primary authoring model with a raw
 * escape hatch, plus the AI writing assist.
 *
 * WHAT A CLIENT DOES HERE, and where each write goes: edit the opening line, the ordered
 * steps (drag to reorder, keyboard up/down as the accessible equivalent), the FAQ and its
 * don't-know fallback, and the end-call rules; insert `{{ }}` merge fields; ask the AI to
 * draft the whole thing from a business description; view the exact compiled engine prompt;
 * Save (which STAGES on a live agent), then Apply to live or Undo. Every save routes through
 * `PUT /v1/agents/{id}/script` and stages — nothing reaches a live call until Apply, which
 * is how this honours D-21's regression concern while being the client-owned surface the
 * approved decision calls for.
 *
 * The one guarantee this screen cannot touch: the truthful-answer floor. "View compiled
 * prompt" shows it appended last by the server, so an author can watch the platform rules
 * ride underneath their own script and see that no field here removes them.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import {
  Bot,
  Eye,
  GripVertical,
  Plus,
  Trash2,
  Undo2,
  Wand2,
  X,
} from "lucide-react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { useClientSession } from "@/lib/api/session";
import {
  EMPTY_SCRIPT,
  useApplyScript,
  useAssistScript,
  usePreviewScript,
  useSaveScript,
  useScript,
  useUndoScript,
  type CallScript,
  type FaqEntry,
  type ScriptStep,
} from "@/lib/api/script";

// Soft budget from PROMPT-GUIDE §1: ~2,500 tokens total. We count characters (the client
// has no tokenizer) and warn past a conservative character equivalent — this is guidance,
// not a hard stop, exactly as the guide frames it.
const CHAR_BUDGET = 9000;

export function ScriptBuilder({ agentId }: { agentId: string }) {
  const session = useClientSession();
  const loaded = useScript(session, agentId);

  return (
    <div className="space-y-5 pb-16">
      {loaded.error && <ProblemNotice error={loaded.error} onRetry={() => void loaded.refetch()} />}
      {loaded.isLoading ? (
        <Card bodyClassName="p-4">
          <Skeleton rows={10} />
        </Card>
      ) : loaded.data ? (
        <Editor
          agentId={agentId}
          initial={loaded.data.script}
          version={loaded.data.version}
          isFreeform={loaded.data.is_freeform}
          hasPending={loaded.data.has_pending}
          standardVariables={loaded.data.standard_variables}
        />
      ) : null}
    </div>
  );
}

type Focusable = HTMLInputElement | HTMLTextAreaElement;

function Editor({
  agentId,
  initial,
  version,
  isFreeform,
  hasPending,
  standardVariables,
}: {
  agentId: string;
  initial: CallScript;
  version: number | null;
  isFreeform: boolean;
  hasPending: boolean;
  standardVariables: { key: string; label: string }[];
}) {
  const session = useClientSession();
  const [script, setScript] = useState<CallScript>(initial);
  const [raw, setRaw] = useState<boolean>(initial.raw_override !== null);
  const [preview, setPreview] = useState<string | null>(null);

  const save = useSaveScript(session, agentId);
  const previewMut = usePreviewScript(session, agentId);
  const apply = useApplyScript(session, agentId);
  const undo = useUndoScript(session, agentId);

  // The field the "insert variable" buttons target: the last text control the author
  // touched, so a variable lands where their cursor is rather than in a fixed field.
  const lastFocused = useRef<Focusable | null>(null);
  const trackFocus = useCallback((el: Focusable | null) => {
    if (el) lastFocused.current = el;
  }, []);

  const insertVariable = useCallback((key: string) => {
    const el = lastFocused.current;
    if (!el) return;
    const token = `{{${key}}}`;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    // Native value setter + input event so React's controlled onChange fires and state
    // updates — the standard way to inject text into a controlled field programmatically.
    const proto =
      el instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    setter?.call(el, el.value.slice(0, start) + token + el.value.slice(end));
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.focus();
    const caret = start + token.length;
    el.setSelectionRange(caret, caret);
  }, []);

  const setField = useCallback(<K extends keyof CallScript>(key: K, value: CallScript[K]) => {
    setScript((s) => ({ ...s, [key]: value }));
  }, []);

  const compiledChars = useMemo(() => (preview ? preview.length : null), [preview]);

  const toStructured = () => {
    setRaw(false);
    setScript((s) => ({ ...s, raw_override: null }));
  };
  const toRaw = () => {
    setRaw(true);
    // Seed raw mode with a blank body; the author can paste. Structured fields are cleared
    // because the server refuses both modes at once.
    setScript({ ...EMPTY_SCRIPT, raw_override: "" });
  };

  const onSave = () => {
    save.mutate({ script });
  };

  const onPreview = () => {
    previewMut.mutate(script, { onSuccess: (r) => setPreview(r.compiled) });
  };

  return (
    <div className="space-y-5">
      {isFreeform && (
        <NoticeBox tone="neutral" title="This script was written as free text">
          It is shown in the raw editor below so nothing is lost. Switch to the structured
          builder when you are ready to rebuild it as steps and FAQs.
        </NoticeBox>
      )}

      {hasPending && (
        <NoticeBox tone="warn" title="You have changes waiting to go live">
          <div className="space-y-3">
            <p>
              A newer version of this script is saved but not yet applied to live calls.
              Apply it when you are ready, or undo to go back to what callers hear now.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={PRIMARY_BUTTON_SM}
                disabled={apply.isPending}
                onClick={() => apply.mutate({ expected_version: version })}
              >
                Apply to live calls
              </button>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={undo.isPending}
                onClick={() => undo.mutate()}
              >
                <Undo2 aria-hidden className="h-3.5 w-3.5" />
                Undo changes
              </button>
            </div>
            {apply.error && <ProblemNotice error={apply.error} />}
            {undo.error && <ProblemNotice error={undo.error} />}
          </div>
        </NoticeBox>
      )}

      <AssistPanel agentId={agentId} onDraft={(s) => setScript(s)} disabled={raw} />

      <Card title="Its script" action={<ModeToggle raw={raw} onStructured={toStructured} onRaw={toRaw} />}>
        {raw ? (
          <RawEditor
            value={script.raw_override ?? ""}
            onChange={(v) => setField("raw_override", v)}
            trackFocus={trackFocus}
          />
        ) : (
          <div className="space-y-8">
            <VariableBar
              standard={standardVariables}
              custom={script.variables}
              onInsert={insertVariable}
            />
            <OpeningSection
              value={script.opening_line}
              onChange={(v) => setField("opening_line", v)}
              trackFocus={trackFocus}
            />
            <StepsSection
              steps={script.steps}
              onChange={(steps) => setField("steps", steps)}
              trackFocus={trackFocus}
            />
            <FaqSection
              faqs={script.faqs}
              fallback={script.faq_fallback}
              onFaqs={(faqs) => setField("faqs", faqs)}
              onFallback={(v) => setField("faq_fallback", v)}
              trackFocus={trackFocus}
            />
            <EndCallSection
              rules={script.end_call_extra_rules}
              onChange={(v) => setField("end_call_extra_rules", v)}
              trackFocus={trackFocus}
            />
          </div>
        )}
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className={PRIMARY_BUTTON} disabled={save.isPending} onClick={onSave}>
          Save script
        </button>
        <button
          type="button"
          className={SECONDARY_BUTTON}
          disabled={previewMut.isPending}
          onClick={onPreview}
        >
          <Eye aria-hidden className="h-4 w-4" />
          View compiled prompt
        </button>
        {save.data && (
          <span className="text-sm text-ink-muted">
            {save.data.staged
              ? `Saved as v${save.data.version} — waiting to apply to live calls.`
              : `Saved as v${save.data.version}.`}
          </span>
        )}
        {compiledChars !== null && (
          <span
            className={`text-xs ${compiledChars > CHAR_BUDGET ? "text-rose-600" : "text-ink-faint"}`}
          >
            Compiled length {compiledChars.toLocaleString()} characters
            {compiledChars > CHAR_BUDGET ? " — over the recommended budget" : ""}
          </span>
        )}
      </div>

      {save.error && <ProblemNotice error={save.error} />}
      {previewMut.error && <ProblemNotice error={previewMut.error} />}

      {preview !== null && <CompiledPrompt text={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}

function ModeToggle({
  raw,
  onStructured,
  onRaw,
}: {
  raw: boolean;
  onStructured: () => void;
  onRaw: () => void;
}) {
  return (
    <div className="inline-flex rounded-md border border-line text-xs" role="group" aria-label="Editing mode">
      <button
        type="button"
        aria-pressed={!raw}
        onClick={onStructured}
        className={`rounded-l-md px-3 py-1.5 font-medium ${!raw ? "bg-brand-strong text-white" : "text-ink-muted"}`}
      >
        Structured
      </button>
      <button
        type="button"
        aria-pressed={raw}
        onClick={onRaw}
        className={`rounded-r-md px-3 py-1.5 font-medium ${raw ? "bg-brand-strong text-white" : "text-ink-muted"}`}
      >
        Raw text
      </button>
    </div>
  );
}

function VariableBar({
  standard,
  custom,
  onInsert,
}: {
  standard: { key: string; label: string }[];
  custom: { key: string; label: string }[];
  onInsert: (key: string) => void;
}) {
  const all = [...standard, ...custom.filter((c) => !standard.some((s) => s.key === c.key))];
  return (
    <div>
      <span className={FIELD_LABEL}>Insert a merge field</span>
      <span className={FIELD_HINT}>
        Click a field to drop it where your cursor is. It is filled in from the lead when the
        call is placed; if there is no value, it simply disappears.
      </span>
      <div className="mt-2 flex flex-wrap gap-2">
        {all.map((v) => (
          <button
            key={v.key}
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => onInsert(v.key)}
          >
            <Plus aria-hidden className="h-3 w-3" />
            {v.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function OpeningSection({
  value,
  onChange,
  trackFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  trackFocus: (el: Focusable | null) => void;
}) {
  return (
    <section>
      <label className={FIELD_LABEL} htmlFor="opening-line">
        Opening line
      </label>
      <span className={FIELD_HINT}>
        What the agent says after it introduces itself. The AI/recording notice is spoken
        first automatically — this follows it.
      </span>
      <textarea
        id="opening-line"
        className={FIELD}
        rows={2}
        value={value}
        onFocus={(e) => trackFocus(e.currentTarget)}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Namaste! How can I help you today?"
      />
    </section>
  );
}

function StepsSection({
  steps,
  onChange,
  trackFocus,
}: {
  steps: ScriptStep[];
  onChange: (steps: ScriptStep[]) => void;
  trackFocus: (el: Focusable | null) => void;
}) {
  const dragFrom = useRef<number | null>(null);

  const move = (from: number, to: number) => {
    if (to < 0 || to >= steps.length) return;
    const next = [...steps];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    onChange(next);
  };
  const update = (i: number, instruction: string) =>
    onChange(steps.map((s, idx) => (idx === i ? { instruction } : s)));
  const remove = (i: number) => onChange(steps.filter((_, idx) => idx !== i));
  const add = () => onChange([...steps, { instruction: "" }]);

  return (
    <section>
      <span className={FIELD_LABEL}>Steps</span>
      <span className={FIELD_HINT}>
        A loose outline the agent follows, one thing at a time. Drag the handle to reorder,
        or use the up/down buttons.
      </span>
      <ol className="mt-3 space-y-3">
        {steps.map((step, i) => (
          <li
            key={i}
            className="flex items-start gap-2 rounded-md border border-line bg-surface p-2"
            draggable
            onDragStart={() => (dragFrom.current = i)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => {
              if (dragFrom.current !== null) move(dragFrom.current, i);
              dragFrom.current = null;
            }}
          >
            <span
              aria-hidden
              className="mt-2 cursor-grab text-ink-faint"
              title="Drag to reorder"
            >
              <GripVertical className="h-4 w-4" />
            </span>
            <span className="mt-2 w-5 shrink-0 text-center text-xs font-semibold text-ink-muted">
              {i + 1}
            </span>
            <textarea
              className={`${FIELD} mt-0`}
              rows={2}
              value={step.instruction}
              aria-label={`Step ${i + 1}`}
              onFocus={(e) => trackFocus(e.currentTarget)}
              onChange={(e) => update(i, e.target.value)}
              placeholder="Ask what the caller needs and confirm it back."
            />
            <div className="mt-1 flex flex-col gap-1">
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                aria-label={`Move step ${i + 1} up`}
                disabled={i === 0}
                onClick={() => move(i, i - 1)}
              >
                ↑
              </button>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                aria-label={`Move step ${i + 1} down`}
                disabled={i === steps.length - 1}
                onClick={() => move(i, i + 1)}
              >
                ↓
              </button>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                aria-label={`Remove step ${i + 1}`}
                onClick={() => remove(i)}
              >
                <Trash2 aria-hidden className="h-3.5 w-3.5" />
              </button>
            </div>
          </li>
        ))}
      </ol>
      <button type="button" className={`${SECONDARY_BUTTON_SM} mt-3`} onClick={add}>
        <Plus aria-hidden className="h-3.5 w-3.5" />
        Add step
      </button>
    </section>
  );
}

function FaqSection({
  faqs,
  fallback,
  onFaqs,
  onFallback,
  trackFocus,
}: {
  faqs: FaqEntry[];
  fallback: string;
  onFaqs: (faqs: FaqEntry[]) => void;
  onFallback: (v: string) => void;
  trackFocus: (el: Focusable | null) => void;
}) {
  const update = (i: number, patch: Partial<FaqEntry>) =>
    onFaqs(faqs.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  const remove = (i: number) => onFaqs(faqs.filter((_, idx) => idx !== i));
  const add = () => onFaqs([...faqs, { question: "", answer: "" }]);

  return (
    <section>
      <span className={FIELD_LABEL}>Questions &amp; answers</span>
      <span className={FIELD_HINT}>
        The agent answers these ONLY from what you write here. For anything else it uses the
        don&apos;t-know reply below rather than guessing.
      </span>
      <div className="mt-3 space-y-3">
        {faqs.map((faq, i) => (
          <div key={i} className="rounded-md border border-line bg-surface p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-ink-muted">Q&amp;A {i + 1}</span>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                aria-label={`Remove question ${i + 1}`}
                onClick={() => remove(i)}
              >
                <X aria-hidden className="h-3.5 w-3.5" />
              </button>
            </div>
            <input
              className={FIELD}
              value={faq.question}
              aria-label={`Question ${i + 1}`}
              onFocus={(e) => trackFocus(e.currentTarget)}
              onChange={(e) => update(i, { question: e.target.value })}
              placeholder="What are your opening hours?"
            />
            <textarea
              className={FIELD}
              rows={2}
              value={faq.answer}
              aria-label={`Answer ${i + 1}`}
              onFocus={(e) => trackFocus(e.currentTarget)}
              onChange={(e) => update(i, { answer: e.target.value })}
              placeholder="We are open 9 to 6, Monday to Saturday."
            />
          </div>
        ))}
      </div>
      <button type="button" className={`${SECONDARY_BUTTON_SM} mt-3`} onClick={add}>
        <Plus aria-hidden className="h-3.5 w-3.5" />
        Add question
      </button>
      <div className="mt-4">
        <label className={FIELD_LABEL} htmlFor="faq-fallback">
          When the agent does not know
        </label>
        <textarea
          id="faq-fallback"
          className={FIELD}
          rows={2}
          value={fallback}
          onFocus={(e) => trackFocus(e.currentTarget)}
          onChange={(e) => onFallback(e.target.value)}
        />
      </div>
    </section>
  );
}

function EndCallSection({
  rules,
  onChange,
  trackFocus,
}: {
  rules: string[];
  onChange: (rules: string[]) => void;
  trackFocus: (el: Focusable | null) => void;
}) {
  return (
    <section>
      <span className={FIELD_LABEL}>Ending a call</span>
      <span className={FIELD_HINT}>
        The agent always ends politely once the caller&apos;s need is handled. Add any extra
        rules of your own, one per line.
      </span>
      <textarea
        className={FIELD}
        rows={3}
        value={rules.join("\n")}
        aria-label="Extra end-call rules, one per line"
        onFocus={(e) => trackFocus(e.currentTarget)}
        onChange={(e) => onChange(e.target.value.split("\n"))}
        placeholder={"Never promise a same-day appointment.\nAlways offer a callback if unsure."}
      />
    </section>
  );
}

function RawEditor({
  value,
  onChange,
  trackFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  trackFocus: (el: Focusable | null) => void;
}) {
  return (
    <section>
      <NoticeBox tone="neutral" title="Raw editing" className="mb-3">
        You are editing the script as plain text. The platform still adds the AI/recording
        answer underneath — you cannot remove it. Switch back to the structured builder any
        time.
      </NoticeBox>
      <textarea
        className={`${FIELD} font-mono`}
        rows={16}
        value={value}
        aria-label="Raw script text"
        onFocus={(e) => trackFocus(e.currentTarget)}
        onChange={(e) => onChange(e.target.value)}
      />
    </section>
  );
}

function CompiledPrompt({ text, onClose }: { text: string; onClose: () => void }) {
  return (
    <Card
      title="Compiled prompt"
      action={
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onClose}>
          <X aria-hidden className="h-3.5 w-3.5" />
          Close
        </button>
      }
    >
      <p className="mb-3 text-sm text-ink-muted">
        This is exactly what the calling system runs — your opening, your script, and the
        platform rules the agent must always follow, which you cannot remove.
      </p>
      {/* Focusable for the same reason every `ScrollRegion` is, on the other axis:
          `max-h-[28rem]` makes this a VERTICALLY scrolling container, and no key scrolls a
          non-focusable element, so a keyboard reader could see the first 28rem of the
          compiled prompt and no more. Not `ScrollRegion` itself — that component is the
          sideways case and hardcodes `overflow-x-auto` (its waiver's argument is written
          there); this matches the integrations screen's delivered-payload `<pre>`. */}
      <pre
        role="region"
        aria-label="Compiled prompt"
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- see above
        tabIndex={0}
        className="max-h-[28rem] overflow-auto whitespace-pre-wrap rounded-md border border-line bg-black/[0.03] p-3 text-xs text-ink dark:bg-white/[0.03]"
      >
        {text}
      </pre>
    </Card>
  );
}

function AssistPanel({
  agentId,
  onDraft,
  disabled,
}: {
  agentId: string;
  onDraft: (script: CallScript) => void;
  disabled: boolean;
}) {
  const session = useClientSession();
  const [description, setDescription] = useState("");
  const [open, setOpen] = useState(false);
  const assist = useAssistScript(session, agentId);

  const run = () => {
    assist.mutate(
      { description },
      {
        onSuccess: (r) => onDraft(r.script),
      },
    );
  };

  return (
    <Card
      title="Draft with AI"
      action={
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen((o) => !o)}>
          {open ? "Hide" : "Open"}
        </button>
      }
    >
      {open && (
        <div className="space-y-3">
          <p className="text-sm text-ink-muted">
            Describe your business and how you want calls handled. We will draft an opening
            line, steps and questions for you to review and edit — nothing goes live until you
            save and apply.
          </p>
          <textarea
            className={FIELD}
            rows={4}
            value={description}
            aria-label="Business description"
            onChange={(e) => setDescription(e.target.value)}
            placeholder="We are a dental clinic in Hyderabad. Callers usually want to book a check-up or ask about teeth cleaning prices. Book appointments and take a callback number."
          />
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className={PRIMARY_BUTTON_SM}
              disabled={assist.isPending || disabled || description.trim().length < 10}
              onClick={run}
            >
              <Wand2 aria-hidden className="h-3.5 w-3.5" />
              {assist.isPending ? "Drafting…" : "Draft my script"}
            </button>
            {disabled && (
              <span className="text-xs text-ink-faint">
                Switch to the structured builder to use AI drafting.
              </span>
            )}
            {assist.data && (
              <span className="inline-flex items-center gap-1.5 text-xs text-ink-muted">
                <Bot aria-hidden className="h-3.5 w-3.5" />
                Draft loaded — review and edit below, then Save.
              </span>
            )}
          </div>
          {assist.data?.disclosure && (
            <NoticeBox tone="neutral" title="How this draft was written">
              {assist.data.disclosure}
            </NoticeBox>
          )}
          {assist.error && <ProblemNotice error={assist.error} />}
        </div>
      )}
    </Card>
  );
}
