"use client";

/**
 * One configured action, and the panel that fires it for real.
 *
 * Split out of `Actions.tsx` (UX-DOCTRINE §6). The test panel is deliberately DISCLOSED
 * rather than always open — it is rare, and it has a consequence a reader must be warned
 * about before they can reach the button ("a WhatsApp test really sends").
 */

import { useState } from "react";
import { FlaskConical, Trash2 } from "lucide-react";

import { ConfirmDialog } from "@/components/confirmDialog";
import {
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  ScrollRegion,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import {
  ACTION_KIND_LABELS,
  PROVIDER_LABELS,
  useDeleteAction,
  useSetActionEnabled,
  useTestAction,
  type ActionTool,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

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
  // A boolean is enough here — the row IS the action, so there is only one thing this
  // dialog can be about.
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);
  const kindLabel = lookup(ACTION_KIND_LABELS, tool.kind) ?? tool.kind;
  const label =
    tool.kind === "whatsapp" && tool.provider
      ? `${kindLabel} · ${lookup(PROVIDER_LABELS, tool.provider) ?? tool.provider}`
      : kindLabel;

  return (
    <li className="rounded-card border border-line bg-app p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p title={tool.name} className="truncate text-sm font-medium text-ink">
            {tool.name}
          </p>
          <p className="truncate text-xs text-ink-muted">
            {label} · {tool.trigger === "after_call" ? "After the call" : "During the call"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => setTesting((v) => !v)}
          >
            <FlaskConical className="mr-1 inline h-3.5 w-3.5" />
            Test
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
      {testing ? <TestPanel tool={tool} agentId={agentId} session={session} /> : null}
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
  const aiParams = tool.params.filter((p) => p.source !== "static");
  const [values, setValues] = useState<Record<string, string>>({});

  return (
    <div className="mt-3 rounded-card border border-line bg-surface p-3">
      <p className="text-xs font-medium text-ink">Test with sample values</p>
      <p className={FIELD_HINT}>
        This runs the real call — a WhatsApp test really sends, a booking really books.
      </p>
      <div className="mt-2 space-y-2">
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
        onClick={() => test.mutate({ toolId: tool.id, values })}
      >
        {test.isPending ? "Running…" : "Run test"}
      </button>
      {test.isError ? <ProblemNotice error={test.error} /> : null}
      {test.data ? (
        <NoticeBox tone={test.data.ok ? "ok" : "warn"} title={`Result: ${test.data.status}`}>
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
