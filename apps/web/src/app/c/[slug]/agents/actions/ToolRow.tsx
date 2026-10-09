"use client";

/**
 * One configured action, and the panel that fires it for real.
 *
 * Split out of `Actions.tsx` (UX-DOCTRINE §6). The test panel is deliberately DISCLOSED
 * rather than always open — it is rare, and it has a consequence a reader must be warned
 * about before they can reach the button ("a WhatsApp test really sends").
 */

import { useState } from "react";
import { FlaskConical, History, Pencil, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirmDialog";
import {
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  formatIST,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  ScrollRegion,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import {
  ACTION_KIND_LABELS,
  PROVIDER_LABELS,
  RUN_SOURCE_LABELS,
  RUN_STATUS_LABELS,
  useActionLog,
  useDeleteAction,
  useSetActionEnabled,
  useTestAction,
  type ActionTool,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

import { ActionForm } from "./ActionForm";
import { KINDS } from "./params";

// The kinds whose test needs a number to stand in for the caller's: one of the business's
// own (the server refuses any other for a WhatsApp or payment-link test).
const NEEDS_TEST_PHONE: readonly string[] = ["whatsapp", "payment_link", "crm", "caller_lookup"];

export function ToolRow({
  tool,
  agentId,
  session,
}: {
  tool: ActionTool;
  agentId: string;
  session: Session;
}) {
  const setEnabled = useSetActionEnabled(session, agentId);
  const remove = useDeleteAction(session, agentId);
  const [testing, setTesting] = useState(false);
  const [showingRuns, setShowingRuns] = useState(false);
  const [editing, setEditing] = useState(false);
  // A kind this build has no form for is listed and removable, never offered for editing.
  const editableKind = KINDS.find((k) => k === tool.kind);
  // A boolean is enough here — the row IS the action, so there is only one thing this
  // dialog can be about.
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);
  const kindLabel = lookup(ACTION_KIND_LABELS, tool.kind) ?? tool.kind;
  const label =
    tool.provider && tool.kind !== "calendar"
      ? `${kindLabel} · ${lookup(PROVIDER_LABELS, tool.provider) ?? tool.provider}`
      : kindLabel;

  return (
    <li className="rounded-card border border-line bg-app p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p title={tool.name} className="truncate text-sm font-medium text-ink">
            {tool.name}
          </p>
          <p className="truncate text-xs text-ink-muted">
            {label} · {tool.trigger === "after_call" ? "After the call" : "During the call"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {editableKind ? (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => setEditing((v) => !v)}
              aria-expanded={editing}
              aria-label={`Edit ${tool.name}`}
            >
              <Pencil className="mr-1 inline h-3.5 w-3.5" />
              Edit
            </button>
          ) : null}
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => setTesting((v) => !v)}
            aria-expanded={testing}
          >
            <FlaskConical className="mr-1 inline h-3.5 w-3.5" />
            Test
          </button>
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => setShowingRuns((v) => !v)}
            aria-expanded={showingRuns}
            aria-label={`Recent runs of ${tool.name}`}
          >
            <History className="mr-1 inline h-3.5 w-3.5" />
            Runs
          </button>
          <label className="flex items-center gap-1 text-xs text-ink-muted">
            <input
              type="checkbox"
              checked={tool.enabled}
              disabled={setEnabled.isPending}
              onChange={(e) => setEnabled.mutate({ toolId: tool.id, enabled: e.target.checked })}
            />
            On
          </label>
          <button
            type="button"
            className={DANGER_BUTTON}
            onClick={() => setConfirmingRemoval(true)}
            aria-label={`Remove ${tool.name}`}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <p className="mt-2 text-xs text-ink-muted">{tool.description}</p>
      {setEnabled.error ? <ProblemNotice error={setEnabled.error} /> : null}
      {/* While the dialog is open the refusal renders inside it, so it is not printed twice. */}
      {remove.error && !confirmingRemoval ? <ProblemNotice error={remove.error} /> : null}
      {confirmingRemoval && (
        <ConfirmDialog
          title={`Remove the action “${tool.name}”?`}
          confirmLabel="Remove it"
          pendingLabel="Removing…"
          pending={remove.isPending}
          error={remove.error}
          onCancel={() => setConfirmingRemoval(false)}
          onConfirm={() =>
            remove.mutate(tool.id, { onSuccess: () => setConfirmingRemoval(false) })
          }
        >
          <p>
            Your agent stops being able to do this on calls straight away. Anything it has
            already sent stays sent.
          </p>
          <p>You can set it up again later, with the same credential.</p>
        </ConfirmDialog>
      )}
      {editing && editableKind ? (
        <div className="mt-3">
          <ActionForm
            kind={editableKind}
            agentId={agentId}
            session={session}
            existing={tool}
            onDone={() => setEditing(false)}
          />
        </div>
      ) : null}
      {testing ? <TestPanel tool={tool} agentId={agentId} session={session} /> : null}
      {showingRuns ? <RunsPanel tool={tool} agentId={agentId} session={session} /> : null}
    </li>
  );
}

function TestPanel({
  tool,
  agentId,
  session,
}: {
  tool: ActionTool;
  agentId: string;
  session: Session;
}) {
  const test = useTestAction(session, agentId);
  // `tool.params` is a list of open dicts on the wire; read fields defensively (String())
  // rather than asserting onto a generated type (the wire-fixture guard bans that).
  const aiParams = tool.params.filter((p) => p.source === "ai");
  const [values, setValues] = useState<Record<string, string>>({});
  const [testPhone, setTestPhone] = useState("");
  const needsPhone = NEEDS_TEST_PHONE.includes(tool.kind);

  return (
    <div className="mt-3 rounded-card border border-line bg-surface p-3">
      <p className="text-xs font-medium text-ink">Test with sample values</p>
      <p className={FIELD_HINT}>
        This runs it for real — a WhatsApp test really sends, a booking really books, a CRM
        record is really saved.
      </p>
      <div className="mt-2 space-y-2">
        {needsPhone ? (
          <div>
            <label className="block">
              <span className={FIELD_LABEL}>Your number (stands in for the caller)</span>
              <input
                className={FIELD}
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                value={testPhone}
                onChange={(e) => setTestPhone(e.target.value)}
                placeholder="+91 98765 43210"
              />
            </label>
            <span className={FIELD_HINT}>
              WhatsApp and payment-link tests go only to one of your business&rsquo;s own
              contact numbers.
            </span>
          </div>
        ) : null}
        {aiParams.map((p) => {
          const nm = String(p.name);
          return (
            <div key={nm}>
              <label className="block">
                <span className={FIELD_LABEL}>{nm}</span>
                <input
                  className={FIELD}
                  value={values[nm] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [nm]: e.target.value }))}
                />
              </label>
            </div>
          );
        })}
      </div>
      <button
        type="button"
        className={`${PRIMARY_BUTTON_SM} mt-2`}
        disabled={test.isPending}
        onClick={() =>
          test.mutate({ toolId: tool.id, values, testPhone: testPhone.trim() || null })
        }
      >
        {test.isPending ? "Running…" : "Run test"}
      </button>
      {test.isError ? <ProblemNotice error={test.error} /> : null}
      {test.data ? (
        <NoticeBox
          tone={test.data.ok ? "ok" : "warn"}
          title={lookup(RUN_STATUS_LABELS, test.data.status) ?? `Result: ${test.data.status}`}
        >
          <ScrollRegion className="max-h-64" label="Test result">
            <pre className="whitespace-pre-wrap break-words text-xs">
              {JSON.stringify(test.data.payload, null, 2)}
            </pre>
          </ScrollRegion>
        </NoticeBox>
      ) : null}
    </div>
  );
}

/** The action's recent runs — on calls, in the background and from tests — newest first. */
function RunsPanel({
  tool,
  agentId,
  session,
}: {
  tool: ActionTool;
  agentId: string;
  session: Session;
}) {
  const runs = useActionLog(session, agentId, tool.id, true);
  return (
    <div className="mt-3 rounded-card border border-line bg-surface p-3">
      <p className="text-xs font-medium text-ink">Recent runs</p>
      {runs.isPending ? (
        <p className={FIELD_HINT}>Loading…</p>
      ) : runs.isError ? (
        <ProblemNotice error={runs.error} onRetry={() => void runs.refetch()} />
      ) : runs.data.length === 0 ? (
        <p className={FIELD_HINT}>It has not run yet.</p>
      ) : (
        <ul className="mt-1 divide-y divide-line text-xs">
          {runs.data.map((run) => (
            <li key={`${run.at}-${run.status}`} className="flex flex-wrap justify-between gap-2 py-1.5">
              <span className="text-ink">
                {lookup(RUN_STATUS_LABELS, run.status) ?? run.status.replace(/_/g, " ")}
              </span>
              <span className="text-ink-muted">
                {lookup(RUN_SOURCE_LABELS, run.source) ?? run.source} · {formatIST(run.at)}
                {run.duration_ms !== null ? ` · ${(run.duration_ms / 1000).toFixed(1)} s` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
