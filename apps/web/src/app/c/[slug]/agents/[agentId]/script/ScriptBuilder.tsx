"use client";

/**
 * THE SCRIPT BUILDER (client realm).
 *
 * WHAT AN OWNER DOES HERE: lay out the call as numbered sections joined by "when … go to"
 * ways out, write what the agent does in each, set the opening line, how it talks and how
 * it ends, and put the result live. On a desktop the sections are a flow picture or a list;
 * on a phone they are a list. Both are views of `script.stages` (`scriptModel.ts`).
 *
 * HOW SAVING WORKS (founder decision, 10 Oct 2026): the working copy autosaves a moment
 * after typing stops (`PUT .../script/draft`, carrying the `saved_at` it started from so a
 * second window cannot be silently overwritten), and ONE "Put it live" turns the draft into
 * a history entry and applies it. Nothing typed here reaches a caller before that. A draft
 * the server would refuse (an empty section name, a branch to nowhere) is not sent; the
 * save line says what to finish instead.
 *
 * The truthful-answer rules are not on this screen and nothing here can remove them; "What
 * the agent reads" shows them added after the owner's script.
 */

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { LayoutList, Plus, Waypoints } from "lucide-react";

import {
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Drawer } from "@/components/console/drawer";
import { TEXT_ACTION } from "@/components/console/section";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { applyByPaths } from "@/lib/copilot/paths";
import { ApiProblem } from "@/lib/api/client";
import { useClientSession } from "@/lib/api/session";
import { isDeleted } from "@/lib/agentState";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useAgent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { usePendingChanges } from "@/lib/api/publishing";
import {
  EMPTY_SCRIPT,
  scriptKeys,
  usePreviewScript,
  useSaveDraft,
  useScript,
  withDraft,
  type CallScript,
  type ScriptOut,
} from "@/lib/api/script";

import {
  EndingSection,
  ExampleSection,
  GoalSection,
  IdentitySection,
  ObjectionsSection,
  OpeningSection,
  PoliciesSection,
  StrictnessSection,
  StyleSection,
  VariableBar,
  type Focusable,
} from "./ScriptSections";
import { TestConversationsPanel } from "./TestConversationsPanel";
import { AssistPanel } from "./AssistPanel";
import { CompiledPrompt, ScriptToolbar } from "./ScriptToolbar";
import { scriptCopilotFields } from "./scriptSurface";
import {
  AUTOSAVE_DELAY_MS,
  hasUnpublished,
  reconcileDraft,
  sameScript,
  saveState,
  workingCopy,
  type SavedCopy,
} from "./scriptDraft";
import {
  addSection,
  connect,
  limitsFrom,
  moveSection,
  pointersTo,
  removeSection,
  scriptAsText,
  sectionsOf,
  setPosition,
  tidy,
  updateSection,
  validate,
} from "./scriptModel";
import { FlowCanvas } from "./FlowCanvas";
import { SectionList } from "./SectionList";
import { SectionEditor } from "./SectionEditor";
import { HandWritten } from "./HandWritten";
import { ScriptHistory } from "./ScriptHistory";
import { PutLiveDialog, usePutLive } from "./PutLive";
import { DESKTOP, useMedia } from "./useMedia";
import { TaughtRules } from "./TaughtRules";
import { voiceTierLine } from "../../panels/publishing";

const PREVIEW_DELAY_MS = 1500;

export function ScriptBuilder({
  agentId,
  backHref,
  knowledgeHref,
}: {
  agentId: string;
  backHref: string;
  knowledgeHref: string;
}) {
  const session = useClientSession();
  const startAssist = useSearchParams().get("assist") === "1";
  const loaded = useScript(session, agentId);
  // This route is bookmarkable and every write on a deleted agent is refused
  // (`agent_archived`), so a deleted agent gets no editor.
  const agent = useAgent(session, agentId);
  const deleted = agent.data !== undefined && isDeleted(agent.data);

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
      <NoticeBox tone="warn" title="This agent is deleted">
        <p className="mt-1">
          Its script is kept exactly as it was and cannot be edited while the agent is deleted.
          Bring the agent back from its own screen; it returns switched off, and the builder
          opens again.
        </p>
      </NoticeBox>
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
          out={loaded.data}
          backHref={backHref}
          knowledgeHref={knowledgeHref}
          agentName={agent.data?.name ?? "This agent"}
          agentOn={agent.data ? agent.data.published && agent.data.status === "live" : false}
          startAssist={startAssist}
        />
      ) : null}
    </div>
  );
}

function Editor({
  agentId,
  out,
  backHref,
  knowledgeHref,
  agentName,
  agentOn,
  startAssist,
}: {
  agentId: string;
  out: ScriptOut;
  backHref: string;
  knowledgeHref: string;
  agentName: string;
  agentOn: boolean;
  startAssist: boolean;
}) {
  const session = useClientSession();
  const queryClient = useQueryClient();
  const desktop = useMedia(DESKTOP);
  const context = out.context ?? null;
  const limits = limitsFrom(context);

  const incoming = useMemo(() => workingCopy(out), [out]);
  const [script, setScript] = useState<CallScript>(incoming.script);
  const [base, setBase] = useState<SavedCopy>(incoming);
  const [seen, setSeen] = useState<SavedCopy>(incoming);
  const [lastSave, setLastSave] = useState<SavedCopy | null>(null);
  const [conflict, setConflict] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<"flow" | "list">("flow");
  const [helperOpen, setHelperOpen] = useState(startAssist);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [published, setPublished] = useState<{ live: boolean } | null>(null);
  const [compiled, setCompiled] = useState<string | null>(null);
  const [room, setRoom] = useState<{ used: number; limit: number } | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [toText, setToText] = useState(false);
  const [undoTo, setUndoTo] = useState<CallScript | null>(null);

  const adopt = (copy: SavedCopy) => {
    setScript(copy.script);
    setBase(copy);
    setConflict(false);
  };

  // Follow every new read (adjusting state during render: react.dev, "You Might Not Need
  // an Effect"), so the screen never shows or autosaves a copy that has been superseded.
  if (seen !== incoming) {
    setSeen(incoming);
    const next = reconcileDraft(script, base, incoming, lastSave);
    if (next.kind === "adopt") adopt(incoming);
    else if (next.kind === "rebase") setBase(incoming);
    else if (next.kind === "conflict") setConflict(true);
  }

  const write = useWriteAccess(session, "org:manage", "change this script");
  const saveDraft = useSaveDraft(session, agentId);
  const previewMut = usePreviewScript(session, agentId);
  const putLive = usePutLive(session, agentId);
  // Read for the voice tier the Put it live step names; the same cached read the agent page uses.
  const pending = usePendingChanges(session, agentId);

  const raw = script.raw_override !== null;
  const dirty = !sameScript(script, base.script);
  const issues = useMemo(() => validate(script, limits), [script, limits]);
  const sections = sectionsOf(script);
  const unpublished = hasUnpublished(out, script);
  useUnsavedGuard(dirty);

  const edit = useCallback((next: CallScript | ((s: CallScript) => CallScript)) => {
    setScript(next);
    setSaveFailed(false);
    setPublished(null);
  }, []);

  /** Store the draft. Without `base`, the save is unconditional ("Keep mine"). */
  const store = useCallback(
    (sent: CallScript, checked: boolean) => {
      setLastSave({ script: sent, stamp: null, savedAt: null });
      saveDraft.mutate(checked ? { script: sent, base_saved_at: base.savedAt } : { script: sent }, {
        onSuccess: (r) => {
          setLastSave({ script: sent, stamp: `d:${r.saved_at}`, savedAt: r.saved_at });
          setConflict(false);
          queryClient.setQueryData<ScriptOut>(scriptKeys.one(session.orgSlug, agentId), (old) =>
            old ? withDraft(old, { script: sent, saved_at: r.saved_at }) : old,
          );
        },
        onError: (error) => {
          setLastSave(null);
          if (error instanceof ApiProblem && error.code === "script_changed_elsewhere") setConflict(true);
          else setSaveFailed(true);
        },
      });
    },
    [saveDraft, base.savedAt, queryClient, session.orgSlug, agentId],
  );

  // The autosave: a moment after the last change, when there is something the server
  // will accept and nobody else's copy is in the way.
  const pendingSave = saveDraft.isPending;
  useEffect(() => {
    if (!dirty || !write.allowed || conflict || saveFailed || issues.length > 0 || pendingSave || publishing) return;
    const timer = setTimeout(() => store(script, true), AUTOSAVE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [script, dirty, write.allowed, conflict, saveFailed, issues.length, pendingSave, publishing, store]);

  // The room-left meter, from the server's own count of the instructions it would send.
  const previewMutate = previewMut.mutate;
  useEffect(() => {
    if (issues.length > 0) return;
    const timer = setTimeout(
      () =>
        previewMutate(script, {
          onSuccess: (r) =>
            setRoom(
              r.instructions_limit && r.instructions_chars !== undefined
                ? { used: r.instructions_chars, limit: r.instructions_limit }
                : null,
            ),
        }),
      PREVIEW_DELAY_MS,
    );
    return () => clearTimeout(timer);
  }, [script, issues.length, previewMutate]);

  // The merge-field buttons drop a field at the caret of the last text box the owner used.
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
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(el, el.value.slice(0, start) + token + el.value.slice(end));
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.focus();
    el.setSelectionRange(start + token.length, start + token.length);
  }, []);

  const setField = useCallback(
    <K extends keyof CallScript>(key: K, value: CallScript[K]) => edit((s) => ({ ...s, [key]: value })),
    [edit],
  );

  useCopilotSurface({
    route: "/c/{slug}/agents/{id}/script",
    title: raw ? "Call script (hand-written)" : "Call script",
    realm: "client",
    fields: scriptCopilotFields(script, raw),
    facts: script.variables.map((variable) => ({
      key: variable.key,
      label: `Variable {{${variable.key}}}`,
      value: variable.label,
    })),
    apply: (items) =>
      edit((current) =>
        applyByPaths(current, items, (id) =>
          id.startsWith("script-") ? id.slice("script-".length).replace(/-/g, ".") : null,
        ),
      ),
  });

  const addOne = () => {
    const made = addSection(script);
    edit(made.script);
    setSelected(made.id);
  };
  const keep = (next: CallScript) => {
    setUndoTo(script);
    edit(next);
    setHelperOpen(false);
  };

  const save = saveState({
    dirty,
    saving: pendingSave,
    canWrite: write.allowed,
    conflict,
    failed: saveFailed,
    issueCount: issues.length,
    savedAt: base.savedAt,
  });

  const selectedIndex = sections.findIndex((s) => s.id === selected);
  const selectedSection = selectedIndex >= 0 ? sections[selectedIndex] : null;
  const editor = selectedSection && (
    <SectionEditor
      key={selectedSection.id}
      section={selectedSection}
      index={selectedIndex}
      sections={sections}
      context={context}
      limits={limits}
      issues={issues}
      readOnly={!write.allowed}
      onChange={(patch) => edit((s) => updateSection(s, selectedSection.id, patch))}
      onMove={(to) => edit((s) => moveSection(s, selectedIndex, to))}
      onDelete={() => setDeleting(selectedSection.id)}
    />
  );
  const showCanvas = desktop && view === "flow";

  return (
    <div className="space-y-6">
      <ScriptToolbar
        backHref={backHref}
        agentName={agentName}
        save={save}
        room={raw ? null : room}
        unpublished={unpublished}
        canWrite={write.allowed}
        writeReason={write.reason}
        publishing={putLive.pending}
        helperOpen={helperOpen}
        onPublish={() => setPublishing(true)}
        onHistory={() => setHistoryOpen(true)}
        onHelper={() => setHelperOpen((o) => !o)}
        menu={[
          {
            id: "compiled",
            label: "See what the agent reads",
            onSelect: () => previewMut.mutate(script, { onSuccess: (r) => setCompiled(r.compiled) }),
            disabled: issues.length > 0,
            hint: issues.length > 0 ? "Finish the marked parts first." : undefined,
          },
          raw
            ? { id: "sections", label: "Use sections instead", onSelect: () => setToText(true), disabled: !write.allowed }
            : { id: "text", label: "Write it by hand instead", onSelect: () => setToText(true), disabled: !write.allowed },
        ]}
      />

      <RestrictionNote reason={write.reason} />
      {conflict && (
        <NoticeBox tone="warn" title="This draft was changed somewhere else">
          <p className="mt-1 text-meta">
            Another window or another person saved a newer draft while you were editing. Your
            edits are still on screen and have not been saved.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => adopt(incoming)}>
              Load the newer draft
            </button>
            <button type="button" className={SECONDARY_BUTTON_SM} disabled={!write.allowed} onClick={() => store(script, false)}>
              Keep mine
            </button>
          </div>
        </NoticeBox>
      )}
      {saveFailed && (
        <NoticeBox tone="warn" title="Your draft could not be saved">
          <p className="mt-1 text-meta">Your edits are still on screen.</p>
          <button type="button" className={`${SECONDARY_BUTTON_SM} mt-2`} onClick={() => store(script, true)}>
            Try again
          </button>
        </NoticeBox>
      )}
      {saveDraft.error && !conflict && saveFailed && <ProblemNotice error={saveDraft.error} />}
      {previewMut.error && <ProblemNotice error={previewMut.error} />}
      {published && (
        <NoticeBox tone="ok" title={published.live ? "It is live" : "Saved as the agent's script"}>
          <p className="mt-1 text-meta">
            {published.live
              ? "Callers hear it from their next call."
              : "Callers hear it once the agent is switched on."}
          </p>
        </NoticeBox>
      )}
      {undoTo && (
        <NoticeBox tone="neutral">
          <span className="text-meta">The changes are in your draft. </span>
          <button
            type="button"
            className={TEXT_ACTION}
            onClick={() => {
              edit(undoTo);
              setUndoTo(null);
            }}
          >
            Undo
          </button>
        </NoticeBox>
      )}
      {out.stored_schema_version === 1 && !raw && (
        <p className="text-meta text-ink-muted">
          This script was written in the older format and is shown in sections here. Callers
          keep hearing the old one until you put it live.
        </p>
      )}

      {raw ? (
        <section aria-labelledby="hand-heading" className="max-w-3xl space-y-3">
          <h3 id="hand-heading" className="text-heading text-ink">
            Written by hand
          </h3>
          <HandWritten
            agentId={agentId}
            script={script}
            readOnly={!write.allowed}
            onChange={(text) => setField("raw_override", text)}
            onConverted={keep}
          />
        </section>
      ) : (
        <>
          <div className="max-w-3xl">
            <TaughtRules agentId={agentId} script={script} canWrite={write.allowed} onChange={(next) => edit(next)} />
          </div>
          <fieldset disabled={!write.allowed} className="min-w-0 max-w-3xl space-y-3">
            <legend className="sr-only">Opening line</legend>
            <OpeningSection value={script.opening_line} onChange={(v) => setField("opening_line", v)} trackFocus={trackFocus} />
            <VariableBar standard={out.standard_variables} custom={script.variables} onInsert={insertVariable} />
          </fieldset>

          <section id="stages" aria-labelledby="call-heading" className="scroll-mt-24 space-y-4 border-t border-line pt-6">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h3 id="call-heading" className="text-sm font-semibold text-ink">
                  How the call goes
                </h3>
                <p className="mt-1 text-sm text-ink-muted">
                  {sections.length} of {limits.maxSections} sections. Number 1 starts the call; each
                  one says where the call goes next.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {desktop && (
                  <div className="inline-flex rounded-md border border-line" role="group" aria-label="Show the sections as">
                    <ViewButton on={view === "flow"} onClick={() => setView("flow")} icon={<Waypoints aria-hidden className="h-4 w-4" />} label="Flow" />
                    <ViewButton on={view === "list"} onClick={() => setView("list")} icon={<LayoutList aria-hidden className="h-4 w-4" />} label="List" />
                  </div>
                )}
                {showCanvas && sections.some((s) => s.position) && write.allowed && (
                  <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => edit(tidy)}>
                    Tidy up
                  </button>
                )}
                {write.allowed && sections.length > 0 && sections.length < limits.maxSections && (
                  <button type="button" className={SECONDARY_BUTTON_SM} onClick={addOne}>
                    <Plus aria-hidden className="h-3.5 w-3.5" />
                    Add a section
                  </button>
                )}
              </div>
            </div>
            {issues.some((i) => i.field === "sections") && (
              <p className="text-meta text-danger">{issues.find((i) => i.field === "sections")?.message}</p>
            )}

            {sections.length === 0 ? (
              <div className="rounded-card border border-dashed border-line px-4 py-8 text-center">
                <p className="text-body text-ink">No sections yet.</p>
                <p className="mx-auto mt-1 max-w-md text-meta text-ink-muted">
                  Most calls go: greet, find out what they need, answer or take the details, agree
                  what happens next. Add a section for each, or let the AI helper draft them.
                </p>
                {write.allowed && (
                  <div className="mt-4 flex flex-wrap justify-center gap-2">
                    <button type="button" className={SECONDARY_BUTTON} onClick={addOne}>
                      <Plus aria-hidden className="h-4 w-4" />
                      Add a section
                    </button>
                    <button type="button" className={SECONDARY_BUTTON} onClick={() => setHelperOpen(true)}>
                      Ask the AI helper
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className={desktop ? "grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(320px,380px)]" : ""}>
                <div className="min-w-0">
                  {showCanvas ? (
                    <FlowCanvas
                      sections={sections}
                      context={context}
                      issues={issues}
                      selected={selected}
                      readOnly={!write.allowed}
                      onSelect={setSelected}
                      onPosition={(id, at) => edit((s) => setPosition(s, id, at))}
                      onConnect={(from, to) => {
                        edit((s) => connect(s, from, to, limits.maxBranches).script);
                        setSelected(from);
                      }}
                    />
                  ) : (
                    <SectionList
                      sections={sections}
                      context={context}
                      issues={issues}
                      selected={selected}
                      readOnly={!write.allowed}
                      onOpen={setSelected}
                      onMove={(from, to) => edit((s) => moveSection(s, from, to))}
                    />
                  )}
                </div>
                {desktop && (
                  <aside aria-label="Edit the chosen section" className="min-w-0">
                    {editor ?? (
                      <p className="rounded-card border border-dashed border-line px-4 py-6 text-meta text-ink-muted">
                        Choose a section to edit it here.
                      </p>
                    )}
                  </aside>
                )}
              </div>
            )}
            {!desktop && selectedSection && (
              <Drawer
                open
                onClose={() => setSelected(null)}
                title={`${selectedIndex + 1}. ${selectedSection.name.trim() || "Untitled section"}`}
                description="Changes save by themselves."
              >
                {editor}
              </Drawer>
            )}
            <fieldset disabled={!write.allowed} className="min-w-0 max-w-3xl pt-2">
              <StrictnessSection value={script.adherence ?? "flexible"} onChange={(v) => setField("adherence", v)} />
            </fieldset>
          </section>

          <fieldset disabled={!write.allowed} className="min-w-0 max-w-3xl space-y-6 border-t border-line pt-6">
            <legend className="sr-only">About the agent and the call</legend>
            <IdentitySection script={script} set={setField} trackFocus={trackFocus} />
            <GoalSection script={script} set={setField} direction={context?.direction ?? "inbound"} trackFocus={trackFocus} />
            <StyleSection style={script.style} onChange={(v) => setField("style", v)} context={context} trackFocus={trackFocus} />
            <ObjectionsSection objections={script.objections} onChange={(v) => setField("objections", v)} trackFocus={trackFocus} />
            <PoliciesSection policies={script.policies} onChange={(v) => setField("policies", v)} context={context} />
            <EndingSection value={script.ending} onChange={(v) => setField("ending", v)} trackFocus={trackFocus} />
            <p className="text-sm text-ink-muted">
              Quick facts, like prices and timings, live in{" "}
              <Link href={knowledgeHref} className="font-medium text-ink underline underline-offset-2">
                Knowledge
              </Link>
              , where all your agents share them.
            </p>
            <ExampleSection
              lines={script.example_exchange}
              needsReview={script.example_needs_review}
              onChange={(lines, stillNeedsReview) =>
                edit((s) => ({ ...s, example_exchange: lines, example_needs_review: stillNeedsReview }))
              }
              trackFocus={trackFocus}
            />
          </fieldset>
        </>
      )}

      <div className="max-w-3xl border-t border-line pt-6">
        <TestConversationsPanel agentId={agentId} />
      </div>

      <Drawer
        open={helperOpen}
        onClose={() => setHelperOpen(false)}
        title="AI helper"
        description="Drafts or changes your script. You review every change."
        width="md"
      >
        <AssistPanel agentId={agentId} script={script} onKeep={keep} />
      </Drawer>

      <Drawer open={historyOpen} onClose={() => setHistoryOpen(false)} title="History" description="Every time the script was put live.">
        <ScriptHistory
          agentId={agentId}
          onRestored={(draft) => {
            const copy = { script: draft.script, stamp: `d:${draft.saved_at}`, savedAt: draft.saved_at };
            queryClient.setQueryData<ScriptOut>(scriptKeys.one(session.orgSlug, agentId), (old) =>
              old ? withDraft(old, draft) : old,
            );
            adopt(copy);
            setHistoryOpen(false);
          }}
        />
      </Drawer>

      {compiled !== null && <CompiledPrompt text={compiled} onClose={() => setCompiled(null)} />}

      {publishing && (
        <PutLiveDialog
          live={out.script}
          draft={script}
          agentOn={agentOn}
          voiceLine={voiceTierLine(pending.data)}
          pending={putLive.pending}
          error={putLive.error}
          onCancel={() => {
            setPublishing(false);
            putLive.reset();
          }}
          onConfirm={(summary) =>
            putLive.run(out, script, summary, (result) => {
              setPublishing(false);
              setPublished(result);
              setLastSave(null);
            })
          }
        />
      )}

      {deleting && (
        <ConfirmDialog
          title={`Delete ${sections.find((s) => s.id === deleting)?.name.trim() || "this section"}?`}
          confirmLabel="Delete section"
          pendingLabel="Deleting…"
          cancelLabel="Keep it"
          pending={false}
          error={null}
          onCancel={() => setDeleting(null)}
          onConfirm={() => {
            const id = deleting;
            setDeleting(null);
            setSelected(null);
            edit((s) => removeSection(s, id));
          }}
        >
          <p>It comes out of your draft. Callers keep hearing the live script until you put it live.</p>
          {pointersTo(sections, deleting).length > 0 && (
            <p>
              {pointersTo(sections, deleting).join(", ")} {pointersTo(sections, deleting).length === 1 ? "goes" : "go"} to
              it now. Those ways out are removed too.
            </p>
          )}
        </ConfirmDialog>
      )}

      {toText && (
        <ConfirmDialog
          title={raw ? "Start again with sections?" : "Write the script by hand?"}
          confirmLabel={raw ? "Start with sections" : "Write it by hand"}
          pendingLabel="Switching…"
          cancelLabel="Stay as it is"
          pending={false}
          error={null}
          onCancel={() => setToText(false)}
          onConfirm={() => {
            setToText(false);
            setUndoTo(script);
            edit(raw ? { ...EMPTY_SCRIPT } : { ...EMPTY_SCRIPT, raw_override: scriptAsText(script) });
          }}
        >
          <p>
            {raw
              ? "The text box is cleared from your draft and you start with empty sections. To keep your text, use “Turn this into sections” instead."
              : "Everything you built is copied into one text box, so nothing is lost. The sections are cleared from your draft. Callers keep hearing the live script until you put it live."}
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}

function ViewButton({
  on,
  onClick,
  icon,
  label,
}: {
  on: boolean;
  onClick: () => void;
  icon: ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium first:rounded-l-md last:rounded-r-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand touch:min-h-11 ${
        on ? "bg-ink/[0.07] text-ink" : "text-ink-muted hover:bg-ink/[0.04]"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}
