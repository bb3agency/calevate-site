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
import { Eye, Undo2, X } from "lucide-react";

import {
  Card,
  NoticeBox,
  PRIMARY_BUTTON,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { applyByPaths } from "@/lib/copilot/paths";
import { useClientSession } from "@/lib/api/session";
import {
  EMPTY_SCRIPT,
  useApplyScript,
  usePreviewScript,
  useSaveScript,
  useScript,
  useUndoScript,
  type CallScript,
} from "@/lib/api/script";

import {
  EndCallSection,
  FaqSection,
  OpeningSection,
  RawEditor,
  StepsSection,
  VariableBar,
  type Focusable,
} from "./ScriptSections";
import { AssistPanel } from "./AssistPanel";
import { scriptCopilotFields } from "./scriptSurface";

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

  /*
   * THE CALL SCRIPT, DECLARED TO THE SCREEN ASSISTANT.
   *
   * One typed `CallScript`, so the fill is one immutable update through `setScript`
   * addressed by PATH (`lib/copilot/paths.ts`). Not the DOM — and this file is the one
   * that would be most tempting to drive that way, because the native-value-setter
   * technique in `insertVariable` above is right here. It is the wrong tool for this
   * job: `insertVariable` writes into whichever control the AUTHOR last focused, at their
   * caret, which is a DOM fact with no state equivalent. A fill names a field, which is a
   * state fact, and going through the DOM for it would depend on ids these sub-components
   * do not have.
   *
   * The list rows are addressed by index (`steps.2.instruction`) and `paths.ts` refuses
   * an index this script does not have rather than growing the array — a step 4 appearing
   * on a script with three is a step nobody wrote.
   *
   * RAW MODE DECLARES ONE FIELD, the body itself: the structured fields are ignored by the
   * server while `raw_override` is a string, so offering them would be offering to fill in
   * text that will not be used.
   */
  useCopilotSurface({
    route: "/c/{slug}/agents/{id}/script",
    title: raw ? "Call script (raw)" : "Call script",
    realm: "client",
    // The `<field>` list, with the system-prompt drafting steer on its `help` (why the steer
    // and why `help` is its channel: `scriptSurface.ts`). Pure and split out so the model's
    // whole view of this screen is testable without the editor's query hooks.
    fields: scriptCopilotFields(script, raw),
    facts: script.variables.map((variable) => ({
      key: variable.key,
      label: `Variable {{${variable.key}}}`,
      value: variable.label,
    })),
    apply: (items) =>
      setScript((current) =>
        applyByPaths(current, items, (id) =>
          // `script-steps-2-instruction` -> `steps.2.instruction`. The id is the path
          // with dots swapped for dashes, the same derivation `intakeFieldId` makes for
          // the intake sheet, so there is one idea in the codebase and not two.
          id.startsWith("script-") ? id.slice("script-".length).replace(/-/g, ".") : null,
        ),
      ),
  });

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
