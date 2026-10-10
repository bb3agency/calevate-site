"use client";

/**
 * One configured action as one row: what it is in words, one switch, and "Manage".
 *
 * Split out of `Actions.tsx` (UX-DOCTRINE §6). Everything rare sits behind Manage — the
 * instructions the agent reads, a real test run, recent runs, changing it, removing it —
 * so a list of actions scans as a list rather than a toolbar per row (REDESIGN-2). The test
 * panel keeps its warning above the button, because a WhatsApp test really sends.
 */

import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  formatIST,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  ScrollRegion,
  ToggleSwitch,
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
import { humanName, jobFor } from "./jobs";
import { KINDS } from "./params";

// The kinds whose test needs a number to stand in for the caller's: one of the business's
// own (the server refuses any other for a WhatsApp or payment-link test).
const NEEDS_TEST_PHONE: readonly string[] = ["whatsapp", "payment_link", "crm", "caller_lookup"];

type Panel = "test" | "runs" | "edit" | null;

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
  const [managing, setManaging] = useState(false);
  const [panel, setPanel] = useState<Panel>(null);
  // A kind this build has no form for is listed and removable, never offered for editing.
  const editableKind = KINDS.find((k) => k === tool.kind);
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);
  const title = humanName(tool.name);
  const job = jobFor(tool.kind)?.title ?? lookup(ACTION_KIND_LABELS, tool.kind) ?? tool.kind;
  const provider =
    tool.provider && tool.kind !== "calendar"
      ? (lookup(PROVIDER_LABELS, tool.provider) ?? tool.provider)
      : null;
  const meta = [job, provider, tool.trigger === "after_call" ? "after the call" : null]
    .filter(Boolean)
    .join(" · ");
  const toggle = (next: Panel) => setPanel((p) => (p === next ? null : next));

  return (
    <li className="py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <div className="min-w-0 flex-1">
          <p className="text-body font-medium text-ink [overflow-wrap:anywhere]">{title}</p>
          <p className="text-meta text-ink-muted">{meta}</p>
        </div>
        <div className="flex items-center gap-5">
          <ToggleSwitch
            label={<span className="sr-only">{title}</span>}
            checked={tool.enabled}
            disabled={setEnabled.isPending}
            onChange={(next) => setEnabled.mutate({ toolId: tool.id, enabled: next })}
          />
          <button
            type="button"
            className={TEXT_ACTION}
            aria-expanded={managing}
            aria-label={`Manage ${tool.name}`}
            onClick={() => {
              setManaging((v) => !v);
              setPanel(null);
            }}
          >
            {managing ? "Done" : "Manage"}
          </button>
        </div>
      </div>
      {setEnabled.error ? <ProblemNotice error={setEnabled.error} /> : null}
      {/* While the dialog is open the refusal renders inside it, so it is not printed twice. */}
      {remove.error && !confirmingRemoval ? <ProblemNotice error={remove.error} /> : null}

      {managing ? (
        <div className="mt-3 space-y-3 border-l-2 border-line pl-4">
          <div>
            <p className="text-meta font-medium text-ink-muted">What your agent is told</p>
            <p className="text-body text-ink">{tool.description}</p>
          </div>
          <div className="flex flex-wrap gap-x-5">
            {editableKind ? (
              <button
                type="button"
                className={TEXT_ACTION}
                onClick={() => toggle("edit")}
                aria-expanded={panel === "edit"}
                aria-label={`Change ${tool.name}`}
              >
                Change
              </button>
            ) : null}
            <button
              type="button"
              className={TEXT_ACTION}
              onClick={() => toggle("test")}
              aria-expanded={panel === "test"}
            >
              Test it
            </button>
            <button
              type="button"
              className={TEXT_ACTION}
              onClick={() => toggle("runs")}
              aria-expanded={panel === "runs"}
              aria-label={`Recent runs of ${tool.name}`}
            >
              Recent runs
            </button>
            <button
              type="button"
              className={TEXT_ACTION_DANGER}
              onClick={() => setConfirmingRemoval(true)}
              aria-label={`Remove ${tool.name}`}
            >
              Remove
            </button>
          </div>
          {panel === "edit" && editableKind ? (
            <ActionForm
              kind={editableKind}
              agentId={agentId}
              session={session}
              existing={tool}
              onDone={() => setPanel(null)}
            />
          ) : null}
          {panel === "test" ? <TestPanel tool={tool} agentId={agentId} session={session} /> : null}
          {panel === "runs" ? <RunsPanel tool={tool} agentId={agentId} session={session} /> : null}
        </div>
      ) : null}

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
    </li>
  );
}

export function TestPanel({
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
  // A calendar action's times are read as YYYY-MM-DDTHH:MM (India time), which is exactly
  // what a datetime-local input produces; a free-text box let "tomorrow 5pm" through.
  const timeParams =
    tool.kind === "calendar"
      ? [tool.config.start_param, tool.config.end_param].filter((v) => typeof v === "string")
      : [];

  return (
    <div className="border-t border-line pt-3">
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
          const isTime = timeParams.includes(nm);
          return (
            <div key={nm}>
              <label className="block">
                <span className={FIELD_LABEL}>{isTime ? `${nm} (India time)` : nm}</span>
                <input
                  className={FIELD}
                  type={isTime ? "datetime-local" : "text"}
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
export function RunsPanel({
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
    <div className="border-t border-line pt-3">
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
