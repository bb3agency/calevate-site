"use client";

/**
 * CALLS AT ONCE (F7): how many calls this client may have in progress together.
 *
 * Calevate's default is two for a paying client and one on a free trial; an operator may set
 * another. A paying client's own voice workspace is capped at the value (sent on save and
 * repaired by the daily sweep); a free trial's calls are counted by our dial gate. A failed
 * read offers no control, so an operator never saves over a value they could not see.
 */

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { NumberField } from "@/components/arc/number-field";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { callsAtOnce, useCallLines, useSetCallLines } from "@/lib/api/callLines";

export function CallLinesPanel({ tenantId, canWrite }: { tenantId: string; canWrite: boolean }) {
  const state = useCallLines(tenantId);
  const save = useSetCallLines(tenantId);
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const [editing, setEditing] = useState(false);
  // `null` is "no choice of this client's own", sent as null so the default applies. The
  // field holds the value inside min..max itself, so there is no out-of-range draft to refuse.
  const [value, setValue] = useState<number | null>(null);

  const data = state.data;

  return (
    <Section title="Calls at once">
      {state.error ? (
        <ProblemNotice error={state.error} onRetry={() => void state.refetch()} />
      ) : state.isLoading || !data ? (
        <Skeleton rows={1} />
      ) : (
        <div className="space-y-3">
          <SettingRows className="border-y border-line">
            <SettingRow
              label="Calls at once"
              hint={
                data.source === "organization"
                  ? "Set for this client"
                  : `Calevate default (${data.on_trial ? "free trial" : "paying client"})`
              }
              info={
                <p>
                  How many calls this client can have in progress together. The default is{" "}
                  {data.paid_default} for a paying client and {data.trial_default} on a free trial.
                  A call over the limit is refused until one ends.
                </p>
              }
              value={callsAtOnce(data.call_lines)}
              action={
                editing || !canWrite ? undefined : (
                  <button
                    type="button"
                    className={TEXT_ACTION}
                    onClick={() => {
                      setValue(data.call_lines_chosen);
                      save.reset();
                      setEditing(true);
                    }}
                  >
                    Change
                  </button>
                )
              }
            />
          </SettingRows>
          {save.error && <ProblemNotice error={save.error} />}
          {editing && (
            <form
              className="space-y-2"
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                if (save.isPending) return;
                save.mutate({ call_lines: value }, { onSuccess: () => setEditing(false) });
              }}
            >
              <NumberField
                label="Calls at once"
                hint={`${data.min_lines} to ${data.max_lines}. Leave empty for the default.`}
                value={value}
                onChange={setValue}
                min={data.min_lines}
                max={data.max_lines}
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
                    save.reset();
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
