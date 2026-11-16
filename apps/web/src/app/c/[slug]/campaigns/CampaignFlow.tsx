"use client";

/**
 * THE CALL AS A FLOWCHART, in the campaign's Script section (founder, 16 Nov 2026: "call ->
 * user recognises, user doesn't remember Rytu Khata etc as first layer and so on").
 *
 * It is the script's own steps and their ways out drawn as a picture, not a second copy of
 * the call: the same `FlowCanvas` and step editor the agent Script page uses, so what is
 * drawn is what the agent follows. Changes stay here until Save, which writes the script the
 * same way Edit script does. "Let Pip map the scenarios" asks for the steps rewritten as the
 * likely ways the call goes, each with its way out; that comes back as a draft to review
 * above, like any script Pip writes.
 */

import { ChevronDown, GitBranch, Maximize2, Plus, Redo2, Undo2, Workflow, X } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { PRIMARY_BUTTON_SM, SECONDARY_BUTTON_SM, ScrollRegion } from "@/components/ui";
import { useFocusTrap } from "@/lib/focusTrap";
import { keepInView } from "@/lib/keepInView";
import type { CallScript } from "@/lib/api/script";
import { useScript } from "@/lib/api/script";
import { useClientRealm } from "@/lib/api/session";

import { SectionEditor } from "../agents/[agentId]/script/SectionEditor";
import { SectionList } from "../agents/[agentId]/script/SectionList";
import {
  END,
  addSection,
  connect,
  limitsFrom,
  moveSection,
  relabel,
  removeSection,
  sectionsOf,
  setBend,
  setEndPosition,
  setPosition,
  updateSection,
  validate,
} from "../agents/[agentId]/script/scriptModel";
import { DESKTOP, useMedia } from "../agents/[agentId]/script/useMedia";

const FlowCanvas = dynamic(() => import("../agents/[agentId]/script/FlowCanvas").then((m) => m.FlowCanvas), {
  ssr: false,
});

const FOLD_KEY = "calevate:fold:call-flow";
/** How many changes Undo can step back through. */
const HISTORY = 100;
/** Changes closer together than this (typing a sentence) undo as one. */
const MERGE_MS = 800;

/** The part name the server recognises for "map the call's scenarios as steps". */
export const FLOW_PART = "flow";

export function CampaignFlow({
  agentId,
  script,
  canWrite,
  refusal,
  saving,
  onSave,
  onMapScenarios,
  mapping,
}: {
  agentId: string;
  script: CallScript;
  canWrite: boolean;
  refusal?: string;
  saving: boolean;
  onSave: (next: CallScript) => Promise<void> | void;
  /** Ask Pip to map the scenarios; absent while it cannot (a draft to review first). */
  onMapScenarios?: () => void;
  mapping: boolean;
}) {
  const { session } = useClientRealm();
  const context = useScript(session, agentId).data?.context ?? null;
  const limits = limitsFrom(context);
  const desktop = useMedia(DESKTOP);
  const [draft, setDraft] = useState<CallScript>(script);
  const [selected, setSelected] = useState<string | null>(null);
  // Folded or open is remembered per browser, like the Set up sections; full screen is not.
  const [folded, setFoldedState] = useState(false);
  const [full, setFull] = useState(false);
  useEffect(() => {
    try {
      setFoldedState(window.localStorage.getItem(FOLD_KEY) === "closed");
    } catch {
      // No storage: it starts open.
    }
  }, []);
  const setFolded = (next: boolean) => {
    setFoldedState(next);
    try {
      window.localStorage.setItem(FOLD_KEY, next ? "closed" : "open");
    } catch {
      // Not remembered without storage.
    }
  };
  // Undo and Redo (founder, 16 Nov 2026): the drafts before and after this one, until Save.
  const [past, setPast] = useState<CallScript[]>([]);
  const [future, setFuture] = useState<CallScript[]>([]);
  const lastChange = useRef(0);
  // A save, or a script Pip wrote and the owner kept, replaces what is drawn and its history.
  useEffect(() => {
    setDraft(script);
    setPast([]);
    setFuture([]);
  }, [script]);
  const commit = (next: CallScript) => {
    if (next === draft) return;
    const now = Date.now();
    if (now - lastChange.current > MERGE_MS || past.length === 0) setPast((p) => [...p, draft].slice(-HISTORY));
    lastChange.current = now;
    setFuture([]);
    setDraft(next);
  };
  const undo = () => {
    const before = past[past.length - 1];
    if (!before) return;
    lastChange.current = 0;
    setPast((p) => p.slice(0, -1));
    setFuture((f) => [draft, ...f]);
    setDraft(before);
  };
  const redo = () => {
    const after = future[0];
    if (!after) return;
    lastChange.current = 0;
    setFuture((f) => f.slice(1));
    setPast((p) => [...p, draft]);
    setDraft(after);
  };
  // Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y over the flow; a text box keeps its own undo.
  const onKeys = (e: React.KeyboardEvent) => {
    const t = e.target as HTMLElement;
    if (!(e.ctrlKey || e.metaKey) || t.closest("input, textarea, select, [contenteditable]")) return;
    const key = e.key.toLowerCase();
    if (key === "z" && !e.shiftKey) {
      e.preventDefault();
      undo();
    } else if (key === "y" || (key === "z" && e.shiftKey)) {
      e.preventDefault();
      redo();
    }
  };

  const sections = sectionsOf(draft);
  const issues = useMemo(() => validate(draft, limits), [draft, limits]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(script);
  const readOnly = !canWrite;
  const edit = (change: (s: CallScript) => CallScript) => commit(change(draft));

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
      readOnly={readOnly}
      onChange={(patch) => edit((s) => updateSection(s, selectedSection.id, patch))}
      onMove={(to) => edit((s) => moveSection(s, selectedIndex, to))}
      onDelete={() => {
        edit((s) => removeSection(s, selectedSection.id));
        setSelected(null);
      }}
      optionsOpenAtFirst
    />
  );
  // The chosen step's quick moves (founder, 16 Nov 2026: change the step number, insert steps
  // in between, and "if yes, do this; if no, do this").
  const insertAfter = () => {
    const made = addSection(draft, {}, selectedIndex + 1);
    commit(made.script);
    setSelected(made.id);
  };
  const addYesNo = () => {
    if (!selectedSection) return;
    const next = sections[selectedIndex + 1]?.id ?? END;
    edit((s) =>
      updateSection(s, selectedSection.id, {
        branches: [
          ...selectedSection.branches,
          { when: "They say yes", target: next },
          { when: "They say no", target: END },
        ].slice(0, limits.maxBranches),
      }),
    );
  };
  const stepTools = selectedSection && !readOnly && (
    <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
      <label className="flex items-center gap-1.5 text-meta font-medium text-ink">
        Step
        <select
          aria-label="Step number"
          className="rounded border border-line bg-surface px-1.5 py-0.5 text-meta text-ink"
          value={selectedIndex}
          onChange={(e) => edit((s) => moveSection(s, selectedIndex, Number(e.target.value)))}
        >
          {sections.map((_, i) => (
            <option key={i} value={i}>
              {i + 1}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={sections.length >= limits.maxSections}
        title={sections.length >= limits.maxSections ? `Up to ${limits.maxSections} steps.` : undefined}
        onClick={insertAfter}
      >
        <Plus aria-hidden className="h-3.5 w-3.5" />
        Insert a step after
      </button>
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={selectedSection.branches.length + 2 > limits.maxBranches}
        title="Adds two ways out: yes goes to the next step, no ends the call. Change either below."
        onClick={addYesNo}
      >
        <GitBranch aria-hidden className="h-3.5 w-3.5" />
        Add Yes / No
      </button>
    </div>
  );
  const addStep = () => {
    const made = addSection(draft);
    commit(made.script);
    setSelected(made.id);
  };

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      {!readOnly && (
        <>
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={past.length === 0}
            title="Undo (Ctrl+Z)"
            onClick={undo}
          >
            <Undo2 aria-hidden className="h-3.5 w-3.5" />
            Undo
          </button>
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={future.length === 0}
            title="Redo (Ctrl+Y)"
            onClick={redo}
          >
            <Redo2 aria-hidden className="h-3.5 w-3.5" />
            Redo
          </button>
        </>
      )}
      {onMapScenarios && (
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={readOnly || mapping || dirty}
          title={dirty ? "Save or discard your changes first." : refusal}
          onClick={onMapScenarios}
        >
          {mapping ? "Pip is mapping…" : "Let Pip map the scenarios"}
        </button>
      )}
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={readOnly || sections.length >= limits.maxSections}
        title={refusal}
        onClick={addStep}
      >
        <Plus aria-hidden className="h-3.5 w-3.5" />
        Add a step
      </button>
    </div>
  );

  // The picture and the chosen step's editor; `wide` is the full-screen window, where the
  // editor always sits beside the picture.
  const body = (wide: boolean) =>
    sections.length === 0 ? (
      <p className="mt-4 rounded-card border border-dashed border-line px-4 py-6 text-center text-meta text-ink-muted">
        No steps yet. Add one, or let Pip map the scenarios.
      </p>
    ) : desktop ? (
      <div
        className={`mt-4 grid grid-cols-1 gap-6 ${wide ? "lg:grid-cols-[minmax(0,1fr)_400px]" : "2xl:grid-cols-[minmax(0,1fr)_380px]"}`}
      >
        <div className="min-w-0">
          <FlowCanvas
            sections={sections}
            context={context}
            issues={issues}
            selected={selected}
            readOnly={readOnly}
            onSelect={setSelected}
            onPosition={(id, at) => edit((s) => setPosition(s, id, at))}
            onConnect={(from, to) => {
              edit((s) => connect(s, from, to, limits.maxBranches).script);
              setSelected(from);
            }}
            endPositions={draft.end_positions ?? undefined}
            onEndPosition={(target, at) => edit((s) => setEndPosition(s, target, at))}
            onBend={(from, branch, via) => edit((s) => setBend(s, from, branch, via))}
            onRelabel={(from, branch, when) => edit((s) => relabel(s, from, branch, when))}
          />
        </div>
        <aside aria-label="Edit the chosen step" className="min-w-0 self-start rounded-card border border-line bg-surface">
          {selectedSection ? (
            <>
              <p className="border-b border-line px-4 py-3 text-body font-semibold text-ink">
                Step {selectedIndex + 1}: {selectedSection.name}
              </p>
              {stepTools}
              <div className="p-4">{editor}</div>
            </>
          ) : (
            <p className="px-4 py-8 text-center text-meta text-ink-muted">Choose a step to edit it here.</p>
          )}
        </aside>
      </div>
    ) : (
      <div className="mt-4">
        <SectionList
          sections={sections}
          context={context}
          issues={issues}
          selected={selected}
          readOnly={readOnly}
          onOpen={(id) => setSelected((open) => (open === id ? null : id))}
          onMove={(from, to) => edit((s) => moveSection(s, from, to))}
          onDelete={readOnly ? undefined : (id) => edit((s) => removeSection(s, id))}
          editor={editor}
        />
      </div>
    );

  const saveBar = (always: boolean) =>
    dirty || always ? (
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {dirty && (
          <>
            <button
              type="button"
              className={PRIMARY_BUTTON_SM}
              disabled={saving || issues.length > 0}
              title={issues[0]?.message}
              onClick={() => void onSave(draft)}
            >
              {saving ? "Saving…" : "Save flow"}
            </button>
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => {
                setDraft(script);
                setPast([]);
                setFuture([]);
              }}
            >
              Discard changes
            </button>
            {issues.length > 0 && <span className="text-meta text-danger">{issues[0].message}</span>}
          </>
        )}
        {always && (
          <button type="button" className={`${SECONDARY_BUTTON_SM} ml-auto`} onClick={() => setFull(false)}>
            Close
          </button>
        )}
      </div>
    ) : null;

  return (
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- Ctrl+Z / Ctrl+Y for the buttons in it
    <div className="mt-6 border-t border-line pt-5" onKeyDown={onKeys}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-body font-semibold text-ink">
            <button
              type="button"
              aria-expanded={!folded}
              onClick={(e) => {
                keepInView(e.currentTarget);
                setFolded(!folded);
              }}
              className="inline-flex items-center gap-1.5"
            >
              <ChevronDown aria-hidden className={`h-4 w-4 transition-transform ${folded ? "-rotate-90" : ""}`} />
              <Workflow aria-hidden className="h-4 w-4 text-series-2" />
              <span>
                Call flow{" "}
                <span className="text-meta font-normal text-ink-muted">
                  {sections.length === 1 ? "1 step" : `${sections.length} steps`}
                </span>
              </span>
            </button>
          </h3>
          {!folded && (
            <p className="mt-0.5 text-meta text-ink-muted">
              Each step and where the call goes next, by what the person says. Click a step to edit it; drag
              its dot to another step to add a way out. Click an arrow&apos;s words to change them; drag them, or an
              end point, to move it.
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!folded && toolbar}
          {desktop && (
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setFull(true)}>
              <Maximize2 aria-hidden className="h-3.5 w-3.5" />
              Open full screen
            </button>
          )}
        </div>
      </div>

      {!folded && !full && (
        <>
          {body(false)}
          {saveBar(false)}
        </>
      )}

      {full && (
        <FullScreen title="Call flow" onClose={() => setFull(false)}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <p className="text-meta text-ink-muted">
              Click a step to edit it on the right; drag its dot to another step to add a way out. Click an
              arrow&apos;s words to change them; drag them, or an end point, to move it. Save keeps the changes.
            </p>
            {toolbar}
          </div>
          {body(true)}
          {saveBar(true)}
        </FullScreen>
      )}
    </div>
  );
}

/**
 * The flow on nearly the whole window, over the page; Escape or Close returns. The dialog
 * focus contract is `useFocusTrap`'s, as in `ModalDialog`: focus moves in, Tab stays inside,
 * Escape closes and focus goes back to "Open full screen".
 */
function FullScreen({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  useFocusTrap(panel, true, onClose, "container");
  useEffect(() => {
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = overflow;
    };
  }, []);
  return createPortal(
    <div className="fixed inset-0 z-modal bg-ink/50 p-4">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="flex h-full flex-col rounded-card bg-app p-5 shadow-card"
      >
        <div className="mb-3 flex shrink-0 items-center justify-between gap-3">
          <h2 className="flex items-center gap-1.5 text-heading text-ink">
            <Workflow aria-hidden className="h-5 w-5 text-series-2" />
            {title}
          </h2>
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={onClose} aria-label="Close full screen">
            <X aria-hidden className="h-3.5 w-3.5" />
            Close
          </button>
        </div>
        <ScrollRegion label={title} edgeCue={false} className="min-h-0 flex-1 overflow-y-auto">
          {children}
        </ScrollRegion>
      </div>
    </div>,
    document.body,
  );
}
