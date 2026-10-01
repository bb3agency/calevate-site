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

import { useSearchParams } from "next/navigation";
import { useCallback, useMemo, useRef, useState } from "react";

import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Drawer } from "@/components/console/drawer";
import { InfoTip } from "@/components/console/infoTip";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { applyByPaths } from "@/lib/copilot/paths";
import { useClientSession } from "@/lib/api/session";
import { isDeleted } from "@/lib/agentState";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useAgent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
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
import { CompiledPrompt, ModeToggle, ScriptToolbar } from "./ScriptToolbar";
import { scriptCopilotFields } from "./scriptSurface";


export function ScriptBuilder({ agentId, backHref }: { agentId: string; backHref: string }) {
  const session = useClientSession();
  const startAssist = useSearchParams().get("assist") === "1";
  const loaded = useScript(session, agentId);
  // Read for one question: is the agent deleted? This route is bookmarkable, and every
  // save on a deleted agent is refused (`agent_archived`), so the editor is not offered.
  const agent = useAgent(session, agentId);
  const deleted = agent.data !== undefined && isDeleted(agent.data);

  // The loading/failed/deleted screens, declared so the assistant stays present; `null`
  // while `Editor` is up, because the innermost registration wins and `Editor` declares
  // the script's own fields.
  useCopilotSurface(
    loaded.data && !deleted
      ? null
      : {
          route: "/c/{slug}/agents/{id}/script",
          title: "Call script",
          realm: "client",
          fields: [],
          facts: [
            { key: "agent_id", label: "Agent id", value: agentId },
            {
              key: "state",
              label: "What is on screen",
              value: deleted
                ? "this agent is deleted, so its script is read-only and no editor is on screen"
                : loaded.error
                  ? "the script failed to load, so nothing of it is on screen"
                  : "still loading",
            },
          ],
          apply: noFill,
        },
  );

  if (deleted) {
    return (
      <div className="rounded-card border border-warn-line bg-warn-soft p-4 text-sm text-ink">
        <p className="font-semibold">This agent is deleted</p>
        <p className="mt-1">
          Its script is kept exactly as it was, and it cannot be edited while the agent is
          deleted. Bring the agent back from its own screen — it returns switched off — and
          the builder opens again.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5 pb-16">
      {loaded.error && <ProblemNotice error={loaded.error} onRetry={() => void loaded.refetch()} />}
      {loaded.isLoading ? (
        <Skeleton rows={10} />
      ) : loaded.data ? (
        <Editor
          agentId={agentId}
          initial={loaded.data.script}
          version={loaded.data.version}
          isFreeform={loaded.data.is_freeform}
          hasPending={loaded.data.has_pending}
          standardVariables={loaded.data.standard_variables}
          backHref={backHref}
          agentName={agent.data?.name ?? "This agent"}
          startAssist={startAssist}
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
  backHref,
  agentName,
  startAssist,
}: {
  backHref: string;
  agentName: string;
  startAssist: boolean;
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
  const [assisting, setAssisting] = useState(startAssist);
  const [switching, setSwitching] = useState<"raw" | "structured" | null>(null);

  // Compared by VALUE: every keystroke replaces the object, so a reference check would keep
  // asking after an edit that was typed and undone.
  const unsaved = useMemo(
    () => JSON.stringify(script) !== JSON.stringify(initial),
    [script, initial],
  );
  useUnsavedGuard(unsaved);

  const save = useSaveScript(session, agentId);
  const previewMut = usePreviewScript(session, agentId);
  const apply = useApplyScript(session, agentId);
  const undo = useUndoScript(session, agentId);
  // Reading and previewing are `agents:read`, so staff may draft and look at the compiled
  // prompt; saving, applying and undoing are `org:manage`, which only the owner holds.
  const write = useWriteAccess(session, "org:manage", "save or apply this script");

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

  /* The script, declared to the assistant as one typed `CallScript` filled by PATH
     (`lib/copilot/paths.ts`), never through the DOM: `insertVariable` above writes at the
     author's caret, which is a DOM fact, while a fill names a field, which is a state fact.
     `paths.ts` refuses an index the script does not have rather than growing a list. Raw
     mode declares one field, because the server ignores the structured ones then. */
  useCopilotSurface({
    route: "/c/{slug}/agents/{id}/script",
    title: raw ? "Call script (raw)" : "Call script",
    realm: "client",
    // Pure and split out (`scriptSurface.ts`) so the model's view is testable alone.
    fields: scriptCopilotFields(script, raw),
    facts: script.variables.map((variable) => ({
      key: variable.key,
      label: `Variable {{${variable.key}}}`,
      value: variable.label,
    })),
    apply: (items) =>
      setScript((current) =>
        applyByPaths(current, items, (id) =>
          // `script-steps-2-instruction` -> `steps.2.instruction`, as `intakeFieldId` does.
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
  // Each switch empties the editor of the other mode's text, so it asks first whenever
  // there is text to lose. An empty editor switches straight away.
  const hasStructured =
    script.opening_line.trim() !== "" || script.steps.length > 0 || script.faqs.length > 0;
  const hasRaw = (script.raw_override ?? "").trim() !== "";
  const askRaw = () => (hasStructured ? setSwitching("raw") : toRaw());
  const askStructured = () => (hasRaw ? setSwitching("structured") : toStructured());

  const onSave = () => {
    save.mutate({ script });
  };

  const onPreview = () => {
    previewMut.mutate(script, { onSuccess: (r) => setPreview(r.compiled) });
  };

  return (
    <div className="space-y-5">
      <ScriptToolbar
        backHref={backHref}
        agentName={agentName}
        version={version}
        hasPending={hasPending}
        unsaved={unsaved}
        canWrite={write.allowed}
        writeReason={write.reason}
        saving={save.isPending}
        applying={apply.isPending}
        onSave={onSave}
        onApply={() => apply.mutate({ expected_version: version })}
        onUndo={() => undo.mutate()}
        onPreview={onPreview}
        onAssist={() => setAssisting(true)}
      />

      <RestrictionNote reason={write.reason} />
      {save.error && <ProblemNotice error={save.error} />}
      {apply.error && <ProblemNotice error={apply.error} />}
      {undo.error && <ProblemNotice error={undo.error} />}
      {previewMut.error && <ProblemNotice error={previewMut.error} />}

      {/* Both pointers as data, because "the version on screen is the one callers hear" is
          the one misreading the two-speed model must never allow. */}
      {hasPending && (
        <p className="text-sm text-ink">
          A newer version of this script is saved but not yet applied to live calls. Apply it
          when you are ready, or undo to go back to what callers hear now.
        </p>
      )}
      {save.data && (
        <p role="status" className="settings-enter text-sm text-ink-muted">
          {save.data.staged
            ? `Saved as v${save.data.version} — waiting to apply to live calls.`
            : `Saved as v${save.data.version}.`}
        </p>
      )}
      {isFreeform && (
        <p className="flex items-center gap-1 text-sm text-ink-muted">
          This script was written as free text.
          <InfoTip label="Free-text script">
            <p>
              It is shown in the raw editor below so nothing is lost. Switch to the structured
              builder when you are ready to rebuild it as steps and FAQs.
            </p>
          </InfoTip>
        </p>
      )}

      <section aria-labelledby="script-editor-heading" className="mx-auto max-w-3xl space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 id="script-editor-heading" className="text-[15px] font-semibold text-ink">
            Its script
          </h3>
          <ModeToggle raw={raw} onStructured={askStructured} onRaw={askRaw} />
        </div>
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
      </section>

      <Drawer
        open={assisting}
        onClose={() => setAssisting(false)}
        title="Draft with AI"
        description="Describe your business; review the draft before you save."
        width="md"
      >
        <AssistPanel agentId={agentId} onDraft={(s) => setScript(s)} disabled={raw} />
      </Drawer>

      {preview !== null && (
        <CompiledPrompt
          text={preview}
          chars={compiledChars}
          onClose={() => setPreview(null)}
        />
      )}

      {switching && (
        <ConfirmDialog
          title={switching === "raw" ? "Start a blank text script?" : "Go back to the structured builder?"}
          confirmLabel={switching === "raw" ? "Start blank text" : "Switch to structured"}
          pendingLabel="Switching…"
          cancelLabel="Keep editing"
          pending={false}
          error={null}
          onCancel={() => setSwitching(null)}
          onConfirm={() => {
            if (switching === "raw") toRaw();
            else toStructured();
            setSwitching(null);
          }}
        >
          <p>
            {switching === "raw"
              ? "The text editor starts empty. The steps and answers on screen are cleared from this draft; the saved version is not touched until you save."
              : "The structured builder does not read free text, so the text on screen is cleared from this draft; the saved version is not touched until you save."}
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
