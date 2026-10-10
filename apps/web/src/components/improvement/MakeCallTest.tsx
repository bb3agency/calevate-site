"use client";

import { useEffect, useId, useState } from "react";
import { FlaskConical } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { useToast } from "@/components/interior/toaster";
import { useClientSession } from "@/lib/api/session";
import { useCaseDraft, useMakeCallATest } from "@/lib/api/teach";

/**
 * "MAKE THIS CALL A TEST" (founder decision 11): a small action for the call detail page.
 *
 * Opens a short form holding what the caller said on this call (redacted, editable) and asks
 * what the agent should have done. Saved, it joins that agent's tests, which re-run against
 * the live agent whenever the owner runs them after a change.
 *
 * Mount it on the call detail screen: `<MakeCallTest callId={call.id} />`. It renders a
 * single secondary button until opened, and nothing for a person who cannot change agents.
 */
export function MakeCallTest({ callId, canWrite = true }: { callId: string; canWrite?: boolean }) {
  const session = useClientSession();
  const [open, setOpen] = useState(false);
  const draft = useCaseDraft(session, callId, open);
  const make = useMakeCallATest(session, callId);
  const { toast } = useToast();
  const [lines, setLines] = useState<string[]>([]);
  const [expected, setExpected] = useState("");
  const [title, setTitle] = useState("");
  const expectedId = useId();

  useEffect(() => {
    if (!draft.data) return;
    setLines(draft.data.caller_lines.length ? draft.data.caller_lines : [""]);
    setTitle(draft.data.title);
  }, [draft.data]);

  if (!canWrite) return null;
  if (!open) {
    return (
      <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen(true)}>
        <FlaskConical aria-hidden className="h-3.5 w-3.5" />
        Make this call a test
      </button>
    );
  }

  const kept = lines.map((line) => line.trim()).filter(Boolean);

  return (
    <section aria-label="Make this call a test" className="space-y-3 border-t border-line pt-4">
      <h3 className="text-sm font-semibold text-ink">Make this call a test</h3>
      {draft.isLoading ? (
        <Skeleton rows={3} label="Loading what the caller said" />
      ) : draft.error ? (
        <ProblemNotice error={draft.error} onRetry={() => void draft.refetch()} />
      ) : (
        <form
          className="space-y-3"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (!kept.length || !expected.trim()) return;
            make.mutate(
              { title, caller_lines: kept, expected: expected.trim() },
              {
                onSuccess: () => {
                  toast({
                    tone: "success",
                    title: "Test saved",
                    description: draft.data?.agent_name
                      ? `It runs with ${draft.data.agent_name}'s other tests.`
                      : "It runs with the agent's other tests.",
                  });
                  setOpen(false);
                },
              },
            );
          }}
        >
          <fieldset className="space-y-2">
            <legend className={FIELD_LABEL}>What the caller says</legend>
            {lines.map((line, index) => (
              <div key={index} className="flex gap-2">
                <input
                  aria-label={`Caller line ${index + 1}`}
                  value={line}
                  onChange={(event) =>
                    setLines((all) => all.map((l, i) => (i === index ? event.target.value : l)))
                  }
                  className={`${FIELD} mt-0`}
                />
                {lines.length > 1 ? (
                  <button
                    type="button"
                    className={SECONDARY_BUTTON_SM}
                    aria-label={`Remove caller line ${index + 1}`}
                    onClick={() => setLines((all) => all.filter((_, i) => i !== index))}
                  >
                    Remove
                  </button>
                ) : null}
              </div>
            ))}
            <span className={FIELD_HINT}>
              Phone numbers and names are already hidden. Keep the lines where it went wrong.
            </span>
          </fieldset>
          <div>
            <label htmlFor={expectedId} className={FIELD_LABEL}>
              What should the agent do?
            </label>
            <textarea
              id={expectedId}
              rows={2}
              value={expected}
              onChange={(event) => setExpected(event.target.value)}
              placeholder="Look up chilli in our knowledge and give the price."
              className={FIELD}
            />
          </div>
          {make.error ? <ProblemNotice error={make.error} /> : null}
          <div className="flex gap-2">
            <button
              type="submit"
              className={PRIMARY_BUTTON_SM}
              disabled={!kept.length || !expected.trim() || make.isPending}
            >
              {make.isPending ? "Saving…" : "Save test"}
            </button>
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen(false)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
