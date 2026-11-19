"use client";

/**
 * CALLING SETUPS: how many engine agents this client's own ThinnestAI workspace may hold.
 *
 * ThinnestAI allows 2 per workspace on pay-as-you-go and raises it per workspace on request.
 * The console setting is the default for every client; when ThinnestAI confirms a raise for
 * this client, the operator records it here, so only this client goes past 2. Recording more
 * than ThinnestAI really allows does not get more: the platform refuses each setup past its cap.
 * A failed read offers no control, so an operator never saves over a value they could not see.
 */

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { NumberField } from "@/components/arc/number-field";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useAgentAllowance, useSetAgentAllowance, type AgentAllowance } from "@/lib/api/engineWorkspaces";
import { resetIfSettled } from "@/app/admin/resetIfSettled";

/** "2 setups", "1 setup". */
export function setups(count: number): string {
  return `${count} ${count === 1 ? "setup" : "setups"}`;
}

/** The limit row's value: the cap, and how many are held when the workspace is active. */
export function allowanceLine(data: AgentAllowance): string {
  return data.in_use === null ? setups(data.limit) : `${setups(data.limit)}, ${data.in_use} in use`;
}

export function AgentAllowancePanel({ tenantId, canWrite }: { tenantId: string; canWrite: boolean }) {
  const state = useAgentAllowance(tenantId);
  const save = useSetAgentAllowance(tenantId);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const [editing, setEditing] = useState(false);
  // `null` is "no cap of this client's own", sent as null so the console default applies.
  const [value, setValue] = useState<number | null>(null);
  const data = state.data;

  return (
    <Section title="Calling setups">
      {state.error ? (
        <ProblemNotice error={state.error} onRetry={() => void state.refetch()} />
      ) : state.isLoading || !data ? (
        <Skeleton rows={1} />
      ) : (
        <div className="space-y-3">
          <SettingRows className="border-y border-line">
            <SettingRow
              label="Limit"
              hint={
                data.agent_allowance === null
                  ? `Console default (${data.default})`
                  : "Raised by ThinnestAI for this client"
              }
              info={
                <p>
                  How many agents, inbound lines, campaigns and test calls can hold a setup in this
                  client&apos;s workspace at once. ThinnestAI allows {data.default} unless they raise
                  it for this workspace. Record a raise only once they confirm it.
                </p>
              }
              value={allowanceLine(data)}
              action={
                editing || !canWrite || !data.settable ? undefined : (
                  <button
                    type="button"
                    className={TEXT_ACTION}
                    onClick={() => {
                      setValue(data.agent_allowance);
                      resetIfSettled(save);
                      setEditing(true);
                    }}
                  >
                    Change
                  </button>
                )
              }
            />
          </SettingRows>
          {!data.settable && (
            <p className="text-body text-ink-muted">
              No workspace yet. A raise can be recorded once it exists.
            </p>
          )}
          {save.error && <ProblemNotice error={save.error} />}
          {editing && (
            <form
              className="space-y-2"
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                if (save.isPending) return;
                save.mutate({ agent_allowance: value }, { onSuccess: () => setEditing(false) });
              }}
            >
              <NumberField
                label="Calling setups"
                hint={`${data.min_allowance} to ${data.max_allowance}, as ThinnestAI confirmed. Leave empty for the console default.`}
                value={value}
                onChange={setValue}
                min={data.min_allowance}
                max={data.max_allowance}
                optional
              />
              <div className="flex items-center gap-3">
                <ActionButton type="submit" status={saveFeedback.status} successLabel="Saved">
                  Save
                </ActionButton>
                <button
                  type="button"
                  className={TEXT_ACTION}
                  onClick={() => {
                    // A refusal belongs to the attempt it answered, not to the next one.
                    resetIfSettled(save);
                    setEditing(false);
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      )}
    </Section>
  );
}
