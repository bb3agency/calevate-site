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

import { Plus, Workflow } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { PRIMARY_BUTTON_SM, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { CallScript } from "@/lib/api/script";
import { useScript } from "@/lib/api/script";
import { useClientRealm } from "@/lib/api/session";

import { SectionEditor } from "../agents/[agentId]/script/SectionEditor";
import { SectionList } from "../agents/[agentId]/script/SectionList";
import {
  addSection,
  connect,
  limitsFrom,
  moveSection,
  removeSection,
  sectionsOf,
  setPosition,
  updateSection,
  validate,
} from "../agents/[agentId]/script/scriptModel";
import { DESKTOP, useMedia } from "../agents/[agentId]/script/useMedia";

const FlowCanvas = dynamic(() => import("../agents/[agentId]/script/FlowCanvas").then((m) => m.FlowCanvas), {
  ssr: false,
});

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
  // A save, or a script Pip wrote and the owner kept, replaces what is drawn.
  useEffect(() => setDraft(script), [script]);

  const sections = sectionsOf(draft);
  const issues = useMemo(() => validate(draft, limits), [draft, limits]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(script);
  const readOnly = !canWrite;
  const edit = (change: (s: CallScript) => CallScript) => setDraft((s) => change(s));

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
    />
  );
  const addStep = () => {
    const made = addSection(draft);
    setDraft(made.script);
    setSelected(made.id);
  };

  return (
    <div className="mt-6 border-t border-line pt-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-1.5 text-body font-semibold text-ink">
            <Workflow aria-hidden className="h-4 w-4 text-series-2" />
            Call flow
          </h3>
          <p className="mt-0.5 text-meta text-ink-muted">
            Each step and where the call goes next, by what the person says. Click a step to edit it; drag
            its dot to another step to add a way out.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
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
      </div>

      {sections.length === 0 ? (
        <p className="mt-4 rounded-card border border-dashed border-line px-4 py-6 text-center text-meta text-ink-muted">
          No steps yet. Add one, or let Pip map the scenarios.
        </p>
      ) : desktop ? (
        <div className="mt-4 grid grid-cols-1 gap-6 2xl:grid-cols-[minmax(0,1fr)_380px]">
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
            />
          </div>
          <aside aria-label="Edit the chosen step" className="min-w-0 self-start rounded-card border border-line bg-surface">
            {selectedSection ? (
              <>
                <p className="border-b border-line px-4 py-3 text-body font-semibold text-ink">Step {selectedIndex + 1}</p>
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
      )}

      {dirty && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            className={PRIMARY_BUTTON_SM}
            disabled={saving || issues.length > 0}
            title={issues[0]?.message}
            onClick={() => void onSave(draft)}
          >
            {saving ? "Saving…" : "Save flow"}
          </button>
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setDraft(script)}>
            Discard changes
          </button>
          {issues.length > 0 && <span className="text-meta text-danger">{issues[0].message}</span>}
        </div>
      )}
    </div>
  );
}
