"use client";

/**
 * THE CALL AS A FLOWCHART, in the campaign's Script section (founder, 16 Nov 2026: "call ->
 * user recognises, user doesn't remember Rytu Khata etc as first layer and so on").
 *
 * It is the script's own sections drawn as steps (columns) of scenarios, not a second copy of
 * the call (`ScenarioFlow`, founder 17 Nov 2026), so what is drawn is what the agent follows. Changes stay here until Save, which writes the script the
 * same way Edit script does. "Let Pip map the scenarios" asks for the steps rewritten as the
 * likely ways the call goes, each with its way out; that comes back as a draft to review
 * above, like any script Pip writes.
 */

import {
  ChevronDown,
  History,
  Maximize2,
  Plus,
  Redo2,
  Undo2,
  Workflow,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { ConfirmDialog } from "@/components/confirmDialog";
import type { ActionFeedback } from "@/components/arc/feedback";
import {
  PRIMARY_BUTTON_SM,
  SECONDARY_BUTTON_SM,
  ScrollRegion,
  formatIST,
} from "@/components/ui";
import { useFocusTrap } from "@/lib/focusTrap";
import { keepInView } from "@/lib/keepInView";
import type { CallScript } from "@/lib/api/script";
import { useScript } from "@/lib/api/script";
import { useClientRealm } from "@/lib/api/session";

import {
  limitsFrom,
  sectionsOf,
  validate,
} from "../agents/[agentId]/script/scriptModel";
import { DESKTOP, useMedia } from "../agents/[agentId]/script/useMedia";
import { ScenarioFlow } from "./ScenarioFlow";
import { FlowAgentBar, useFlowAgent } from "./FlowAgentBar";
import { addScenario, placed } from "./scenarioModel";

const FOLD_KEY = "calevate:fold:call-flow";
/** How many changes Undo can step back through. */
const HISTORY = 100;
/** Changes closer together than this (typing a sentence) undo as one. */
const MERGE_MS = 800;

/** The part name the server recognises for "map the call's scenarios as steps". */
export const FLOW_PART = "flow";
/** The part name the server reads as "translate the English lines" (`campaign_script_ask`). */
export const TRANSLATE_PART = "translate";

export function CampaignFlow({
  agentId,
  script,
  canWrite,
  refusal,
  saving,
  onSave,
  onMapScenarios,
  mapping,
  languages,
  campaignId,
  beforePipAt,
  restore,
  onRestore,
  onTranslate,
  translating = false,
  translateNote = null,
  onDismissTranslate,
}: {
  translateNote?: string | null;
  onDismissTranslate?: () => void;
  /** Ask Pip to fill the campaign language's empty boxes from the English. */
  onTranslate?: () => void;
  translating?: boolean;
  /** When the flow from before Pip's last draft was kept aside; null: nothing to put back. */
  beforePipAt: string | null;
  restore: ActionFeedback<void>;
  onRestore: () => Promise<unknown>;
  campaignId: string;
  agentId: string;
  /** The campaign's languages, main first: each scenario has a script line in each. */
  languages: string[];
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
    if (now - lastChange.current > MERGE_MS || past.length === 0)
      setPast((p) => [...p, draft].slice(-HISTORY));
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
    if (
      !(e.ctrlKey || e.metaKey) ||
      t.closest("input, textarea, select, [contenteditable]")
    )
      return;
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

  const addStep = () => {
    const steps = Math.max(0, ...placed(sections).map((p) => p.step));
    const made = addScenario(draft, steps + 1);
    commit(made.script);
    setSelected(made.id);
  };

  const [confirmRestore, setConfirmRestore] = useState(false);
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
      {beforePipAt && (
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={readOnly || dirty}
          title={
            dirty
              ? "Save or discard your changes first."
              : `The flow as it was on ${formatIST(beforePipAt)}, before Pip wrote.`
          }
          onClick={() => setConfirmRestore(true)}
        >
          <History aria-hidden className="h-3.5 w-3.5" />
          Put back the flow from before Pip
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

  // The agent whose voice "Hear it" speaks in, with its picker and voice settings.
  const flowAgent = useFlowAgent(agentId, (agent) => (
    <FlowAgentBar
      campaignId={campaignId}
      agentId={agentId}
      agent={agent}
      canWrite={canWrite}
      refusal={refusal}
    />
  ));

  // The steps and the chosen scenario's editor; on a phone the steps stack.
  const body = () => (
    <ScenarioFlow
      agent={flowAgent}
      onTranslate={onTranslate}
      translating={translating}
      translateNote={translateNote}
      onDismissTranslate={onDismissTranslate}
      translateBlocked={dirty ? "Save or discard your changes first." : null}
      script={draft}
      limits={limits}
      issues={issues}
      languages={languages}
      selected={selected}
      readOnly={readOnly}
      wide={desktop}
      onSelect={setSelected}
      onChange={commit}
    />
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
            {issues.length > 0 && (
              <span className="text-meta text-danger">{issues[0].message}</span>
            )}
          </>
        )}
        {always && (
          <button
            type="button"
            className={`${SECONDARY_BUTTON_SM} ml-auto`}
            onClick={() => setFull(false)}
          >
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
              className="inline-flex items-center gap-1.5 touch:min-h-11"
            >
              <ChevronDown
                aria-hidden
                className={`h-4 w-4 transition-transform ${folded ? "-rotate-90" : ""}`}
              />
              <Workflow aria-hidden className="h-4 w-4 text-series-2" />
              <span>
                Call flow{" "}
                <span className="text-meta font-normal text-ink-muted">
                  {flowCount(sections)}
                </span>
              </span>
            </button>
          </h3>
          {!folded && (
            <p className="mt-0.5 text-meta text-ink-muted">
              Each column is a step of the call; each box a way it can go (a
              scenario). Click a box to edit it, right-click for more, and drag
              its green dot to a scenario in a later step to link them.
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!folded && toolbar}
          {desktop && (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => setFull(true)}
            >
              <Maximize2 aria-hidden className="h-3.5 w-3.5" />
              Open full screen
            </button>
          )}
        </div>
      </div>

      {!folded && !full && (
        <>
          {body()}
          {saveBar(false)}
        </>
      )}

      {confirmRestore && beforePipAt && (
        <ConfirmDialog
          title="Put back the flow from before Pip?"
          confirmLabel="Put it back"
          pendingLabel="Putting it back"
          cancelLabel="Keep this one"
          status={restore.status}
          error={restore.error ?? null}
          onCancel={() => {
            restore.reset();
            setConfirmRestore(false);
          }}
          onConfirm={() =>
            void onRestore().then(
              () => setConfirmRestore(false),
              () => undefined,
            )
          }
        >
          <span className="block">
            The steps and scenarios go back to how they were on{" "}
            {formatIST(beforePipAt)}, before Pip wrote. The flow you have now is
            kept, so you can switch back to it the same way.
          </span>
        </ConfirmDialog>
      )}

      {full && (
        <FullScreen title="Call flow" onClose={() => setFull(false)}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <p className="text-meta text-ink-muted">
              Click a box to edit it on the right, right-click for more, and
              drag its green dot to a scenario in a later step to link them.
              Save keeps the changes.
            </p>
            {toolbar}
          </div>
          {body()}
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
function FullScreen({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
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
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={onClose}
            aria-label="Close full screen"
          >
            <X aria-hidden className="h-3.5 w-3.5" />
            Close
          </button>
        </div>
        <ScrollRegion
          label={title}
          edgeCue={false}
          className="min-h-0 flex-1 overflow-y-auto"
        >
          {children}
        </ScrollRegion>
      </div>
    </div>,
    document.body,
  );
}

function flowCount(sections: ReturnType<typeof sectionsOf>): string {
  const items = placed(sections);
  const steps = new Set(items.map((p) => p.step)).size;
  return `${steps} ${steps === 1 ? "step" : "steps"} · ${items.length} ${items.length === 1 ? "scenario" : "scenarios"}`;
}
