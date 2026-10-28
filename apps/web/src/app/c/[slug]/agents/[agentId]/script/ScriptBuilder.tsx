"use client";

/**
 * THE SCRIPT BUILDER (client realm), the agent page's Script tab since D-825.
 *
 * WHAT AN OWNER DOES HERE: write the opening line (with the caller details it may name),
 * lay out the call as numbered steps, each with what the agent does there and an example
 * line, set how it talks and how it ends, and put the result live. The steps are a list at
 * every width, each opening in place; a desktop can show them as a flow picture instead,
 * from More options. Both are views of `script.stages` (`scriptModel.ts`). Asking Pip for a
 * change is a panel beside the steps ("Tell Pip what to change", D-820).
 *
 * HOW SAVING WORKS (founder decision, 10 Oct 2026): the working copy autosaves a moment
 * after typing stops (`PUT .../script/draft`, carrying the `saved_at` it started from so a
 * second window cannot be silently overwritten), and ONE "Put it live" turns the draft into
 * a history entry and applies it. Nothing typed here reaches a caller before that. A draft
 * the server would refuse (an empty section name, a branch to nowhere) is not sent; the
 * save line says what to finish instead.
 *
 * HOW THE PAGE IS ORDERED (founder, 11 Oct 2026: "all of it is too much to read"; 19 Oct
 * 2026: simpler than Outpero's): by how often an owner needs each thing. The opening line
 * and the steps are on the page, because they are what gets edited; a step's rarer options
 * are under its own More options (`SectionEditor`); the parts set once (role, goal, speech,
 * push-backs, what it may do, ending, example) are a summary list whose rows open in place
 * (`ScriptParts`); History, the full instructions, the flow picture and hand-writing are in
 * the bar's ⋯ menu. Help is one line, with the reason behind an ⓘ. The bar's one filled
 * button is "Put it live". The flow picture loads only when asked for (`next/dynamic`).
 *
 * The truthful-answer rules are not on this screen and nothing here can remove them; "What
 * the agent reads" shows them added after the owner's script.
 */

import { useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus } from "lucide-react";

import {
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { Drawer } from "@/components/console/drawer";
import { InfoTip } from "@/components/console/infoTip";
import { BELOW_PAGE_BAR_STICKY } from "@/components/console/stickyPageBar";
import { TEXT_ACTION } from "@/components/console/section";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { applyByPaths } from "@/lib/copilot/paths";
import { ApiProblem } from "@/lib/api/client";
import { useClientSession } from "@/lib/api/session";
import { isDeleted } from "@/lib/agentState";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";
import { useVerticalExamples } from "@/lib/useVerticalExamples";
import { useAgent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { usePendingChanges } from "@/lib/api/publishing";
import {
  EMPTY_SCRIPT,
  scriptKeys,
  usePreviewScript,
  useSaveDraft,
  useScript,
  useScriptProposal,
  withDraft,
  type CallScript,
  type ScriptOut,
} from "@/lib/api/script";

import { OpeningEditor, StrictnessSection } from "./ScriptSections";
import { ScriptParts } from "./ScriptParts";
import { PipAsk, WHOLE_REQUEST } from "./PipAsk";
import { PipProposal } from "./PipProposal";
import { CompiledPrompt, ScriptToolbar, roomFrom, type Room } from "./ScriptToolbar";
import { HeldBackNotice, TooLongNotice } from "@/components/heldBackNotice";
import { PUT_LIVE, scriptCopilotFacts, scriptCopilotFields } from "./scriptSurface";
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
import { SectionList } from "./SectionList";
import { SectionEditor } from "./SectionEditor";
import { HandWritten } from "./HandWritten";
import { ScriptHistory } from "./ScriptHistory";
import { PutLiveDialog, usePutLive } from "./PutLive";
import { DESKTOP, SIDE_PANEL, useMedia } from "./useMedia";
import { TaughtRules } from "./TaughtRules";
import { voiceTierLine } from "../../panels/publishing";

const PREVIEW_DELAY_MS = 1500;

/** Most owners never open the flow picture, so its code is fetched only when they do. */
const FlowCanvas = dynamic(() => import("./FlowCanvas").then((m) => m.FlowCanvas), {
  ssr: false,
  loading: () => <Skeleton rows={6} label="Drawing the call" />,
});

export function ScriptBuilder({
  agentId,
  knowledgeHref,
  trainingHref,
}: {
  agentId: string;
  knowledgeHref: string;
  /** The agent's Training tab, where the chat, the practice call and the tests are. */
  trainingHref: string;
}) {
  const session = useClientSession();
  const loaded = useScript(session, agentId);
  // This route is bookmarkable and every write on a deleted agent is refused
  // (`agent_archived`), so a deleted agent gets no editor.
  const agent = useAgent(session, agentId);
  const deleted = agent.data !== undefined && isDeleted(agent.data);

  useCopilotSurface(
    loaded.data && !deleted
      ? null
      : {
          route: "/c/{slug}/agents/{id}",
          title: "Agent: script",
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
        <p className="mt-1">Read-only. Bring the agent back to edit it.</p>
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
          knowledgeHref={knowledgeHref}
          trainingHref={trainingHref}
          agentName={agent.data?.name ?? "This agent"}
          agentOn={agent.data ? agent.data.published && agent.data.status === "live" : false}
          openingRoom={agent.data?.greeting_budget?.opening_room}
        />
      ) : null}
    </div>
  );
}

function Editor({
  agentId,
  out,
  knowledgeHref,
  trainingHref,
  agentName,
  agentOn,
  openingRoom,
}: {
  agentId: string;
  out: ScriptOut;
  knowledgeHref: string;
  trainingHref: string;
  agentName: string;
  agentOn: boolean;
  /** Characters the opening line may have after the notices switched on (D-846). */
  openingRoom?: number;
}) {
  const session = useClientSession();
  const queryClient = useQueryClient();
  const desktop = useMedia(DESKTOP);
  const sidePanel = useMedia(SIDE_PANEL);
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
  const [view, setView] = useState<"flow" | "list">("list");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [published, setPublished] = useState<{ live: boolean } | null>(null);
  const [compiled, setCompiled] = useState<string | null>(null);
  const [room, setRoom] = useState<Room | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [toText, setToText] = useState(false);
  const [undoTo, setUndoTo] = useState<CallScript | null>(null);
  // A link may name a part (`#policies`, from Knowledge's "Fix in script"). The page drew
  // nothing while the script loaded, so the browser's own jump found no target: open that
  // part and scroll to it once the editor is on screen.
  const [arrivedAt] = useState(() => (typeof window === "undefined" ? null : window.location.hash.slice(1) || null));
  useEffect(() => {
    const target = arrivedAt ? document.getElementById(arrivedAt) : null;
    (target?.closest("details") ?? target)?.scrollIntoView?.({ block: "start" });
  }, [arrivedAt]);

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
  // The autosave and the room count run on their own; their outcome is the save line in
  // the bar and the notices above the editor (conflict, could not save), never a toast.
  useActionFeedback(saveDraft, { errorDisplay: "inline" });
  const previewMut = usePreviewScript(session, agentId);
  useActionFeedback(previewMut, { errorDisplay: "inline" });
  const eg = useVerticalExamples();
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

  // The room-left meter, from the server's own count of everything the calling system
  // receives: Calevate's rules as well as the script, hand-written or in steps.
  const previewMutate = previewMut.mutate;
  useEffect(() => {
    if (issues.length > 0) return;
    const timer = setTimeout(
      () =>
        previewMutate(script, {
          onSuccess: (r) => setRoom(roomFrom(r)),
        }),
      PREVIEW_DELAY_MS,
    );
    return () => clearTimeout(timer);
  }, [script, issues.length, previewMutate]);

  const setField = useCallback(
    <K extends keyof CallScript>(key: K, value: CallScript[K]) => edit((s) => ({ ...s, [key]: value })),
    [edit],
  );

  const save = saveState({
    dirty,
    saving: pendingSave,
    canWrite: write.allowed,
    conflict,
    failed: saveFailed,
    issueCount: issues.length,
    savedAt: base.savedAt,
  });

  // The suggestion's state for Pip: the same cached read `PipProposal` shows.
  const proposal = useScriptProposal(session, agentId).data;
  const [keptSuggestion, setKeptSuggestion] = useState(false);
  if (proposal && keptSuggestion) setKeptSuggestion(false);

  useCopilotSurface({
    route: "/c/{slug}/agents/{id}",
    title: raw ? "Agent: script (hand-written)" : "Agent: script",
    realm: "client",
    saves: "autosave",
    liveStep: PUT_LIVE,
    fields: scriptCopilotFields(script, raw, context?.language),
    // The agent's id and name first: a request to change this script names the agent by them.
    facts: [
      { key: "agent_id", label: "Agent id", value: agentId },
      { key: "agent_name", label: "Agent", value: agentName },
      ...scriptCopilotFacts({ proposal, keptSuggestion, save, unpublished, liveStep: PUT_LIVE }),
      ...script.variables.map((variable) => ({
        key: variable.key,
        label: `Variable {{${variable.key}}}`,
        value: variable.label,
      })),
    ],
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
    setKeptSuggestion(true);
    edit(next);
  };

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
  // Whether callers hear this draft, in the same words the agent page uses.
  const live: { text: string; tone: "ok" | "warn" | "neutral" } =
    out.version === null
      ? { text: unpublished ? "Not live yet" : "Not written yet", tone: "neutral" }
      : unpublished
        ? { text: "Changes not live yet", tone: "warn" }
        : agentOn
          ? { text: "Live", tone: "ok" }
          : { text: "Ready · agent is off", tone: "neutral" };

  // Pip's panel sits beside the steps when the list leaves room for it; the flow picture
  // wants the full width, so with it, and on a narrow screen, the panel follows the steps.
  const twoColumns = sidePanel && !showCanvas;
  const pip = <PipAsk handWritten={raw} />;
  const steps = (
    <section id="stages" aria-labelledby="call-heading" className={`scroll-mt-24 space-y-4 ${showCanvas ? "" : "max-w-3xl"}`}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-1">
            <h3 id="call-heading" className="text-heading text-ink">
              How the call goes
            </h3>
            <InfoTip label="the steps" align="start">
              Step 1 starts the call and each step leads to the next. Open a step to change what
              the agent does there; where it goes instead is under More options.
            </InfoTip>
          </div>
          <p className="text-meta text-ink-muted">
            {sections.length} of {limits.maxSections} steps
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {showCanvas && sections.some((s) => s.position) && write.allowed && (
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => edit(tidy)}>
              Tidy up
            </button>
          )}
          {write.allowed && sections.length > 0 && sections.length < limits.maxSections && (
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={addOne}>
              <Plus aria-hidden className="h-3.5 w-3.5" />
              Add a step
            </button>
          )}
        </div>
      </div>
      {issues.some((i) => i.field === "sections") && (
        <p className="text-meta text-danger">{issues.find((i) => i.field === "sections")?.message}</p>
      )}

      {sections.length === 0 ? (
        <div className="rounded-card border border-dashed border-line px-4 py-8 text-center">
          <p className="text-body text-ink">No steps yet.</p>
          <p className="mx-auto mt-1 max-w-md text-meta text-ink-muted">
            Most calls: greet, ask the need, help, agree next steps.
          </p>
          {write.allowed && (
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              <button type="button" className={SECONDARY_BUTTON} onClick={addOne}>
                <Plus aria-hidden className="h-4 w-4" />
                Add a step
              </button>
              <AskAssistant label={`Let ${ASSISTANT_NAME} draft the whole script`} prompt={WHOLE_REQUEST} size="md" />
            </div>
          )}
        </div>
      ) : showCanvas ? (
        <div className={sidePanel ? "grid gap-6 2xl:grid-cols-[minmax(0,1fr)_380px]" : ""}>
          <div className="min-w-0">
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
          </div>
          {sidePanel && (
            <aside
              aria-label="Edit the chosen step"
              className={`min-w-0 self-start rounded-card border border-line bg-surface ${BELOW_PAGE_BAR_STICKY}`}
            >
              {selectedSection ? (
                <>
                  <p className="border-b border-line px-4 py-3 text-body font-semibold text-ink">
                    Step {selectedIndex + 1}
                  </p>
                  <div className="p-4">{editor}</div>
                </>
              ) : (
                <div className="px-4 py-8 text-center">
                  <p className="text-body text-ink">Choose a step to edit it here.</p>
                  <p className="mx-auto mt-1 max-w-64 text-meta text-ink-muted">
                    Drag a step to move it. Drag its dot to link steps.
                  </p>
                </div>
              )}
            </aside>
          )}
        </div>
      ) : (
        <SectionList
          sections={sections}
          context={context}
          issues={issues}
          selected={selected}
          readOnly={!write.allowed}
          onOpen={(id) => setSelected((open) => (open === id ? null : id))}
          onMove={(from, to) => edit((s) => moveSection(s, from, to))}
          editor={editor}
        />
      )}
      {showCanvas && !sidePanel && selectedSection && (
        <Drawer
          open
          onClose={() => setSelected(null)}
          title={`${selectedIndex + 1}. ${selectedSection.name.trim() || "Untitled step"}`}
          description="Changes save by themselves."
        >
          {editor}
        </Drawer>
      )}
      {sections.length > 0 && (
        <fieldset disabled={!write.allowed} className="min-w-0">
          <legend className="sr-only">How closely it follows the steps</legend>
          <StrictnessSection value={script.adherence ?? "flexible"} onChange={(v) => setField("adherence", v)} />
        </fieldset>
      )}
    </section>
  );

  return (
    <div className="space-y-6">
      <ScriptToolbar
        save={save}
        room={room}
        unpublished={unpublished}
        canWrite={write.allowed}
        writeReason={write.reason}
        publishing={putLive.pending}
        live={live}
        onPublish={() => setPublishing(true)}
        menu={[
          { id: "history", label: "History", onSelect: () => setHistoryOpen(true) },
          {
            id: "compiled",
            label: "See what the agent reads",
            onSelect: () => previewMut.mutate(script, { onSuccess: (r) => setCompiled(r.compiled) }),
            disabled: issues.length > 0,
            hint: issues.length > 0 ? "Finish the marked parts first." : undefined,
          },
          ...(desktop && !raw && sections.length > 0
            ? [
                showCanvas
                  ? { id: "list", label: "Show the steps as a list", onSelect: () => setView("list") }
                  : { id: "flow", label: "Show the call as a flow", onSelect: () => setView("flow") },
              ]
            : []),
          raw
            ? { id: "sections", label: "Use steps instead", onSelect: () => setToText(true), disabled: !write.allowed }
            : { id: "text", label: "Write it by hand instead", onSelect: () => setToText(true), disabled: !write.allowed },
        ]}
      />

      <RestrictionNote reason={write.reason} />
      {conflict && (
        <NoticeBox
          tone="warn"
          title="This draft was changed somewhere else"
          action={
            <>
              <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => adopt(incoming)}>
                Load the newer draft
              </button>
              <button type="button" className={SECONDARY_BUTTON_SM} disabled={!write.allowed} onClick={() => store(script, false)}>
                Keep mine
              </button>
            </>
          }
        >
          Your edits are still on screen and not saved.
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
      {pending.data?.held_back && <HeldBackNotice held={pending.data.held_back} />}
      {room?.tooLong && <TooLongNotice message={room.tooLong} longest={room.longest} />}
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
        <NoticeBox
          tone="neutral"
          title="Shown in steps from the older format"
          info="Callers keep hearing the old one until you put it live."
        />
      )}

      {/* The steps and the Pip panel side by side where there is room for both at a
          readable width; one column below that, with the panel under the opening line. */}
      <div className={twoColumns ? "grid gap-8 xl:grid-cols-[minmax(0,1fr)_340px]" : ""}>
        <div className="min-w-0 space-y-8">
          <div className="max-w-3xl space-y-8">
          <PipProposal
            agentId={agentId}
            script={script}
            canWrite={write.allowed}
            onKeep={keep}
            limits={limits}
            language={context?.language}
          />
          {raw ? (
            <section aria-labelledby="hand-heading" className="space-y-3">
              <h3 id="hand-heading" className="text-heading text-ink">
                Written by hand
              </h3>
              <HandWritten script={script} readOnly={!write.allowed} onChange={(text) => setField("raw_override", text)} />
            </section>
          ) : (
            <fieldset disabled={!write.allowed} className="min-w-0">
              <legend className="sr-only">How the call opens</legend>
              <OpeningEditor
                script={script}
                set={setField}
                direction={context?.direction}
                room={openingRoom}
                standardVariables={out.standard_variables}
                eg={eg}
                previewAction={
                  <Link href={trainingHref} className={TEXT_ACTION}>
                    Hear it in Training
                  </Link>
                }
              />
            </fieldset>
          )}
          {raw && !twoColumns && pip}
          </div>
          {!raw && (
            <div className="space-y-8">
              {steps}
              {!twoColumns && pip}
              <div className="max-w-3xl space-y-8">
              <TaughtRules agentId={agentId} script={script} canWrite={write.allowed} onChange={(next) => edit(next)} />
              <fieldset disabled={!write.allowed} className="min-w-0">
                <legend className="sr-only">About the agent and the call</legend>
                <ScriptParts
                  script={script}
                  context={context}
                  issues={issues}
                  openPart={arrivedAt}
                  knowledgeHref={knowledgeHref}
                  setField={setField}
                  edit={edit}
                />
              </fieldset>
              </div>
            </div>
          )}
        </div>
        {twoColumns && <aside className={`min-w-0 self-start ${BELOW_PAGE_BAR_STICKY}`}>{pip}</aside>}
      </div>

      <p className="max-w-3xl text-body text-ink-muted">
        Put your changes live, then{" "}
        <Link href={trainingHref} className="font-medium text-ink underline underline-offset-2">
          try it in Training
        </Link>{" "}
        to hear how callers are answered now.
      </p>

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
          status={putLive.status}
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
          title={`Delete ${sections.find((s) => s.id === deleting)?.name.trim() || "this step"}?`}
          confirmLabel="Delete step"
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
          <p>Removed from your draft only.</p>
          <p>Callers hear no change until you put it live.</p>
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
          title={raw ? "Start again with steps?" : "Write the script by hand?"}
          confirmLabel={raw ? "Start with steps" : "Write it by hand"}
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
          {raw ? (
            <>
              <p>Your text is cleared. You start with empty steps.</p>
              <p>To keep it, use “Turn this into steps” instead.</p>
            </>
          ) : (
            <>
              <p>Your steps are copied into one text box. Nothing is lost.</p>
              <p>Callers hear no change until you put it live.</p>
            </>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}
