"use client";

/**
 * ONE ACTION'S OWN VIEW (every job except booking, which has `BookingJob`): its switch,
 * how it is set up as plain rows with Change, a real test, and the rare things — recent
 * runs, the technical name, removal — closed below. Change swaps the rows for the
 * `ActionForm`, whose Cancel / Save sit at its foot, so the view never shows both.
 */

import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import { TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import { ServiceLogo } from "@/components/console/serviceLogo";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { Disclosure, ProblemNotice, ToggleSwitch } from "@/components/ui";
import {
  useCredentials,
  useDeleteAction,
  useSetActionEnabled,
  type ActionTool,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";

import { ActionForm } from "./ActionForm";
import { toolLogo, toolProblem, toolSummary } from "./jobs";
import { KINDS } from "./params";
import { RunsPanel, TestPanel } from "./ToolRow";

export function ToolDetail({
  tool,
  agentId,
  session,
  takenNames,
  onRemoved,
  onAddAnother,
}: {
  tool: ActionTool;
  agentId: string;
  session: Session;
  takenNames: readonly string[];
  onRemoved: () => void;
  onAddAnother: () => void;
}) {
  const creds = useCredentials(session);
  const setEnabled = useSetActionEnabled(session, agentId);
  const remove = useDeleteAction(session, agentId);
  const [changing, setChanging] = useState(false);
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);
  // A kind this build has no form for is listed and removable, never offered for editing.
  const editableKind = KINDS.find((k) => k === tool.kind);
  const problem = toolProblem(tool, creds.data);
  const account = creds.data?.find((c) => c.id === tool.credential_id);
  const logo = toolLogo(tool);

  if (changing && editableKind) {
    return (
      <ActionForm
        kind={editableKind}
        agentId={agentId}
        session={session}
        existing={tool}
        takenNames={takenNames}
        onDone={() => setChanging(false)}
      />
    );
  }

  const change = editableKind ? (
    <button type="button" className={TEXT_ACTION} aria-label={`Change ${tool.name}`} onClick={() => setChanging(true)}>
      Change
    </button>
  ) : undefined;

  return (
    <div className="space-y-8">
      <div>
        <ToggleSwitch
          label="Use it on calls"
          hint={tool.enabled ? "Your agent can do this on calls." : "Your agent will not do this."}
          checked={tool.enabled}
          disabled={setEnabled.isPending}
          onChange={(next) => setEnabled.mutate({ toolId: tool.id, enabled: next })}
        />
        {setEnabled.error ? <ProblemNotice error={setEnabled.error} /> : null}
      </div>

      <div>
        <SettingRows className="border-y border-line">
          <SettingRow label="Set up" value={toolSummary(tool) || "Nothing yet"} action={change} />
          {tool.kind !== "custom_api" ? (
            <SettingRow
              label="Account"
              value={
                account ? (
                  <span className="inline-flex items-center gap-2">
                    {logo ? <ServiceLogo service={logo} className="h-5 w-5" /> : null}
                    {account.label}
                  </span>
                ) : (
                  <span className="text-warn">Not connected</span>
                )
              }
              action={change}
            />
          ) : null}
          <SettingRow
            label="When"
            value={tool.trigger === "after_call" ? "After the call ends" : "During the call"}
            action={change}
          />
          <SettingRow label="What your agent is told" value={tool.description} action={change} />
        </SettingRows>
        {problem ? (
          <p className="mt-3 text-meta text-warn">
            {problem}. Your agent cannot do this until it is fixed. Use Change to finish it.
          </p>
        ) : null}
      </div>

      <div>
        <h4 className="text-body font-medium text-ink">Try it</h4>
        <div className="mt-2">
          <TestPanel tool={tool} agentId={agentId} session={session} />
        </div>
      </div>

      <div className="border-t border-line">
        <Disclosure variant="inline" headingLevel={4} title="Recent runs">
          <RunsPanel tool={tool} agentId={agentId} session={session} />
        </Disclosure>
        <Disclosure variant="inline" headingLevel={4} title="Advanced">
          <p>
            Its name on calls: <span className="font-mono text-ink">{tool.name}</span>
          </p>
        </Disclosure>
      </div>

      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <button type="button" className={TEXT_ACTION} onClick={onAddAnother}>
          Add another like this
        </button>
        <button
          type="button"
          className={TEXT_ACTION_DANGER}
          aria-label={`Remove ${tool.name}`}
          onClick={() => setConfirmingRemoval(true)}
        >
          Remove this action
        </button>
      </div>
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
            remove.mutate(tool.id, {
              onSuccess: () => {
                setConfirmingRemoval(false);
                onRemoved();
              },
            })
          }
        >
          <p>
            Your agent stops being able to do this on calls straight away. Anything it has
            already sent stays sent.
          </p>
          <p>You can set it up again later, with the same credential.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
