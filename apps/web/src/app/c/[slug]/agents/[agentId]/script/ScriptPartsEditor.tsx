"use client";

/**
 * A SAVED SCRIPT, EDITED ONE PART AT A TIME (founder, 27 Nov 2026: "I seriously don't want
 * the user to be overwhelmed").
 *
 * The script is a short list of its parts' names, each with a one-line preview. Tapping one
 * opens that part alone with the builder's own editor (`PartEditor`, `SectionFields`); opening
 * another closes it. Save writes the whole saved script with only that part changed, through
 * the caller's own save, and is held by the builder's `validate` on that part alone.
 *
 * The open state is ours rather than a native `<details>` (`Disclosure`, `Accordion`): an open
 * part holds unsaved words, and a `<details>` closes itself on a tap before anything can ask
 * the owner to save or cancel them first.
 *
 * `leaveOut` is what another surface edits: on a campaign the canvas owns the steps and both
 * opening lines, so the campaign passes them here and `steps={false}`.
 */

import { ChevronRight, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ActionButton } from "@/components/arc/feedback";
import type { CallScript } from "@/lib/api/script";
import { scrollToFirstFinding } from "@/lib/api/scriptChecks";
import { keepInView } from "@/lib/keepInView";
import { useUnsavedGuard } from "@/lib/useUnsavedGuard";

import { placed } from "../../../campaigns/scenarioModel";
import { PART_OF_FIELD, PartEditor, SectionFields, partShows, sectionShows, unshownIssues } from "./ProposalEditors";
import { WarningLines } from "./StepExamplesEditor";
import { partWarnings, stageWarnings, type LineWarning } from "./stepExamples";
import { GeneratePart, type GeneratePartProps } from "./GeneratePart";
import { PARTS, partText, type PartKey } from "./scriptDiff";
import { DEFAULT_LIMITS, sectionsOf, validate, type Issue, type Limits, type Section } from "./scriptModel";

/** Parts whose editor has no way to add an entry: listed only while they hold something. */
const FILLED_ONLY: ReadonlySet<PartKey> = new Set(["step_outcomes", "example_exchange"]);
const NONE: readonly PartKey[] = [];

type Row =
  | { id: string; kind: "part"; part: PartKey; label: string; asks?: string; preview: string }
  | { id: string; kind: "step"; stageId: string; label: string; preview: string };

function firstLine(text: string): string {
  return text.trim().split("\n")[0]?.trim() ?? "";
}

function rowsOf(script: CallScript, leaveOut: readonly PartKey[], steps: boolean): Row[] {
  const parts: Row[] = PARTS.filter(({ key }) => !leaveOut.includes(key))
    .map(({ key, label, asks }) => ({ id: `part:${key}`, kind: "part" as const, part: key, label, asks, preview: partText(script, key) }))
    .filter((row) => !FILLED_ONLY.has(row.part) || row.preview !== "");
  if (!steps) return parts;
  return [
    ...parts,
    ...sectionsOf(script).map((s, i) => ({
      id: `stage:${s.id}`,
      kind: "step" as const,
      stageId: s.id,
      label: s.name.trim() || `Step ${i + 1}`,
      preview: s.instruction,
    })),
  ];
}

function warningsOn(row: Row, warnings: readonly LineWarning[]): LineWarning[] {
  if (row.kind === "part") return partWarnings(warnings, row.part);
  const prefix = `stages.${row.stageId}`;
  return warnings.filter((w) => w.path === prefix || w.path.startsWith(`${prefix}.`));
}

function issuesOn(row: Row, issues: readonly Issue[]): Issue[] {
  return issues.filter((issue) =>
    row.kind === "step"
      ? issue.section === row.stageId
      : issue.section === null && PART_OF_FIELD.find((p) => p.test.test(issue.field))?.part === row.part,
  );
}

function domId(row: Row): string {
  return `script-part-${row.id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

export function ScriptPartsEditor({
  script,
  onSave,
  onClose,
  saving = false,
  leaveOut = NONE,
  steps = true,
  generatePart,
  languages = [],
  warnings = [],
  limits = DEFAULT_LIMITS,
  language = "your callers' language",
  show = null,
}: {
  /** The saved script: every Save starts from it and changes one part. */
  script: CallScript;
  onSave: (next: CallScript) => void;
  onClose: () => void;
  saving?: boolean;
  /** Parts another surface edits, not listed here. */
  leaveOut?: readonly PartKey[];
  /** List each step as a part of its own. */
  steps?: boolean;
  /** Pip rewrites the open part in a chosen language. */
  generatePart?: GeneratePartProps;
  /** The call's languages, main first: a step's examples are per language. */
  languages?: { tag: string; name: string }[];
  /** The saved script's checks, each shown on the part it is about. */
  warnings?: readonly LineWarning[];
  limits?: Limits;
  /** The call language in words, for the hints on lines the agent says. */
  language?: string;
  /** "Show me" from a refusal: opens that step, or the first part with a finding. Each new
   *  object opens it again. */
  show?: { stageId: string | null } | null;
}) {
  const rows = useMemo(() => rowsOf(script, leaveOut, steps), [script, leaveOut, steps]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState<CallScript>(script);
  const [tried, setTried] = useState(false);
  const [nudged, setNudged] = useState(false);
  const dirty = openId !== null && JSON.stringify(draft) !== JSON.stringify(script);
  useUnsavedGuard(dirty);

  const open = rows.find((r) => r.id === openId) ?? null;
  const issues = useMemo(() => (open ? issuesOn(open, validate(draft, limits)) : []), [open, draft, limits]);

  const button = (row: Row) => document.getElementById(`${domId(row)}-toggle`);
  const focusFirstField = (row: Row) =>
    window.requestAnimationFrame(() =>
      document
        .getElementById(`${domId(row)}-panel`)
        ?.querySelector<HTMLElement>("textarea, input:not([type=hidden]), select")
        ?.focus({ preventScroll: true }),
    );

  const openRow = (row: Row) => {
    setDraft(script);
    setTried(false);
    setNudged(false);
    setOpenId(row.id);
    focusFirstField(row);
  };

  const closeRow = (row: Row) => {
    keepInView(button(row));
    setOpenId(null);
    setTried(false);
    setNudged(false);
    window.requestAnimationFrame(() => button(row)?.focus({ preventScroll: true }));
  };

  const toggle = (row: Row) => {
    keepInView(button(row));
    if (row.id === openId) {
      // Closing by the row itself drops nothing silently: unsaved words ask for Save or Cancel.
      if (dirty) setNudged(true);
      else closeRow(row);
      return;
    }
    if (dirty) {
      setNudged(true);
      return;
    }
    openRow(row);
  };

  // "Show me": open the flagged step, or the first part a finding is on.
  useEffect(() => {
    if (!show) return;
    const target =
      (show.stageId ? rows.find((r) => r.kind === "step" && r.stageId === show.stageId) : undefined) ??
      rows.find((r) => warningsOn(r, warnings).length > 0);
    if (target && !dirty) {
      setDraft(script);
      setOpenId(target.id);
    }
    scrollToFirstFinding();
    // Only a new request opens a part; the rows and script it reads are the current ones.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show]);

  const save = (row: Row) => {
    if (issues.length > 0) {
      setTried(true);
      window.requestAnimationFrame(() =>
        document
          .getElementById(`${domId(row)}-panel`)
          ?.querySelector<HTMLElement>("[aria-invalid='true']")
          ?.focus(),
      );
      return;
    }
    onSave(draft);
  };

  const editStep = (id: string, patch: Partial<Section>) =>
    setDraft((d) => ({ ...d, stages: sectionsOf(d).map((s) => (s.id === id ? { ...s, ...patch, id } : s)) }));

  return (
    <section aria-labelledby="script-parts-heading" className="space-y-3">
      <div>
        <h3 id="script-parts-heading" className="text-heading text-ink">
          Edit your script
        </h3>
        <p className="mt-1 text-meta text-ink-muted">Tap a part to change it.</p>
      </div>
      <ul className="divide-y divide-line border-y border-line">
        {rows.map((row) => {
          const isOpen = row.id === openId;
          const id = domId(row);
          const flagged = warningsOn(row, warnings);
          return (
            <li key={row.id} data-editing={isOpen || undefined}>
              <button
                id={`${id}-toggle`}
                type="button"
                aria-expanded={isOpen}
                aria-controls={isOpen ? `${id}-panel` : undefined}
                className="group flex w-full items-start gap-3 rounded-sm py-3 text-left touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand"
                onClick={() => toggle(row)}
              >
                <ChevronRight
                  aria-hidden
                  className={`mt-0.5 h-4 w-4 shrink-0 text-ink-muted transition-transform duration-150 ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none group-hover:text-ink ${
                    isOpen ? "rotate-90" : ""
                  }`}
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-body font-medium text-ink">{row.label}</span>
                  {!isOpen && (
                    <span className="block truncate text-meta text-ink-muted">
                      {firstLine(row.preview) || "Not set"}
                    </span>
                  )}
                </span>
                {!isOpen && flagged.length > 0 && (
                  <span className="mt-0.5 inline-flex shrink-0 items-center gap-1 text-meta text-warn">
                    <TriangleAlert aria-hidden className="h-3.5 w-3.5" />
                    {flagged.length === 1 ? "1 to check" : `${flagged.length} to check`}
                  </span>
                )}
              </button>
              {isOpen && (
                <div
                  id={`${id}-panel`}
                  role="region"
                  aria-labelledby={`${id}-toggle`}
                  className="space-y-3 pb-4 pl-7"
                >
                  {generatePart && (
                    <GeneratePart
                      {...generatePart}
                      what={row.label}
                      sendAs={row.kind === "part" ? row.asks : undefined}
                      held={dirty ? "Save or cancel your edits first." : undefined}
                    />
                  )}
                  {row.kind === "part" ? (
                    <PartBody
                      part={row.part}
                      idBase={id}
                      draft={draft}
                      issues={tried ? issues : []}
                      language={language}
                      warnings={flagged}
                      onChange={setDraft}
                    />
                  ) : (
                    <StepBody
                      stageId={row.stageId}
                      idBase={id}
                      draft={draft}
                      issues={tried ? issues : []}
                      limits={limits}
                      language={language}
                      languages={languages}
                      warnings={warnings}
                      generate={generatePart}
                      onChange={(patch) => editStep(row.stageId, patch)}
                    />
                  )}
                  <div className="flex flex-wrap items-center gap-2">
                    <ActionButton
                      variant="primary-sm"
                      status={saving ? "pending" : "idle"}
                      pendingLabel="Saving…"
                      disabled={!dirty}
                      aria-label={`Save ${row.label}`}
                      onClick={() => save(row)}
                    >
                      Save
                    </ActionButton>
                    <ActionButton
                      variant="secondary-sm"
                      disabled={saving}
                      aria-label={`Cancel ${row.label}`}
                      onClick={() => closeRow(row)}
                    >
                      Cancel
                    </ActionButton>
                  </div>
                  {nudged && dirty && (
                    <p role="status" className="text-meta text-warn">
                      Save or cancel this part first.
                    </p>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        <ActionButton variant="secondary-sm" disabled={saving} onClick={onClose}>
          Close
        </ActionButton>
      </div>
    </section>
  );
}

function RowErrors({ issues }: { issues: Issue[] }) {
  if (issues.length === 0) return null;
  return <p className="text-meta text-danger">{issues.map((i) => i.message).join(" ")}</p>;
}

function PartBody({
  part,
  idBase,
  draft,
  issues,
  language,
  warnings,
  onChange,
}: {
  part: PartKey;
  idBase: string;
  draft: CallScript;
  issues: Issue[];
  language: string;
  warnings: readonly LineWarning[];
  onChange: (next: CallScript) => void;
}) {
  return (
    <div className="space-y-1.5">
      <PartEditor part={part} script={draft} idBase={idBase} issues={issues} language={language} onChange={onChange} />
      <RowErrors issues={unshownIssues(issues, partShows)} />
      <WarningLines warnings={warnings} idBase={`${idBase}-warn`} />
    </div>
  );
}

function StepBody({
  stageId,
  idBase,
  draft,
  issues,
  limits,
  language,
  languages,
  warnings,
  generate,
  onChange,
}: {
  stageId: string;
  idBase: string;
  draft: CallScript;
  issues: Issue[];
  limits: Limits;
  language: string;
  languages: { tag: string; name: string }[];
  warnings: readonly LineWarning[];
  generate?: GeneratePartProps;
  onChange: (patch: Partial<Section>) => void;
}) {
  const sections = sectionsOf(draft);
  const section = sections.find((s) => s.id === stageId);
  if (!section) return null;
  const first = placed(sections).find((p) => p.section.id === stageId)?.step === 1;
  return (
    <div className="space-y-1.5">
      <SectionFields
        section={section}
        idBase={idBase}
        issues={issues}
        limits={limits}
        language={language}
        languages={languages}
        first={first}
        warnings={warnings}
        generate={generate}
        onChange={onChange}
      />
      <RowErrors issues={unshownIssues(issues, sectionShows)} />
      <WarningLines warnings={stageWarnings(warnings, stageId, null)} idBase={`${idBase}-warn`} />
    </div>
  );
}
