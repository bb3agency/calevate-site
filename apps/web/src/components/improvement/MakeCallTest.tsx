"use client";

import { useEffect, useId, useState } from "react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { useToast } from "@/components/interior/toaster";
import { useClientSession } from "@/lib/api/session";
import { useCaseDraft, useDiscardPreparedTest, useMakeCallATest } from "@/lib/api/teach";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

/** What Pip is asked, in the words the person sees in its ask box. */
export const MAKE_TEST_REQUEST = "Make this call a test for its agent.";

/**
 * "MAKE THIS CALL A TEST" (founder decision 11), asked of Pip (D-822).
 *
 * The button opens Pip with the request written. Pip (`call_test_prepare`) saves nothing: it
 * leaves what the agent should do for this call, and this form opens filled in with it and
 * with what the caller said (redacted, editable). The person checks it and saves it here, or
 * discards it. Saved, it joins that agent's tests, which re-run against the live agent
 * whenever the owner runs them after a change.
 *
 * Nothing renders for a person who cannot change agents (`agents:write`, the save's own
 * permission).
 */
export function MakeCallTest({ callId, canWrite = true }: { callId: string; canWrite?: boolean }) {
  const session = useClientSession();
  const eg = useVerticalExamples();
  const draft = useCaseDraft(session, callId, canWrite);
  const make = useMakeCallATest(session, callId);
  const discard = useDiscardPreparedTest(session, callId);
  const { toast } = useToast();
  const [lines, setLines] = useState<string[]>([]);
  const [expected, setExpected] = useState("");
  const [title, setTitle] = useState("");
  const expectedId = useId();
  const pending = draft.data?.pending ?? null;

  useEffect(() => {
    if (!draft.data?.pending) return;
    setLines(draft.data.caller_lines.length ? draft.data.caller_lines : [""]);
    setTitle(draft.data.pending.title ?? draft.data.title);
    setExpected(draft.data.pending.expected ?? "");
  }, [draft.data]);

  if (!canWrite) return null;
  if (draft.isLoading) return <Skeleton rows={1} label="Loading the test form" />;
  if (draft.error) return <ProblemNotice error={draft.error} onRetry={() => void draft.refetch()} />;
  if (!pending) {
    return (
      <AskAssistant label={`Let ${ASSISTANT_NAME} make this call a test`} prompt={MAKE_TEST_REQUEST} />
    );
  }

  const kept = lines.map((line) => line.trim()).filter(Boolean);
  const busy = make.isPending || discard.isPending;

  return (
    <section aria-label="Make this call a test" className="space-y-3 border-t border-line pt-4">
      <h3 className="text-sm font-semibold text-ink">Make this call a test</h3>
      <p className="text-meta text-ink-muted">
        {ASSISTANT_NAME} filled this in. Check it, change anything, and save it.
      </p>
      <form
        className="space-y-3"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (!kept.length || !expected.trim()) return;
          make.mutate(
            { title, caller_lines: kept, expected: expected.trim() },
            {
              onSuccess: () =>
                toast({
                  tone: "success",
                  title: "Test saved",
                  description: draft.data?.agent_name
                    ? `It runs with ${draft.data.agent_name}'s other tests.`
                    : "It runs with the agent's other tests.",
                }),
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
            placeholder={eg.testExpectation}
            className={FIELD}
          />
        </div>
        {make.error ? <ProblemNotice error={make.error} /> : null}
        {discard.error ? <ProblemNotice error={discard.error} /> : null}
        <div className="flex gap-2">
          <button
            type="submit"
            className={PRIMARY_BUTTON_SM}
            disabled={!kept.length || !expected.trim() || busy}
          >
            {make.isPending ? "Saving…" : "Save test"}
          </button>
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={busy}
            onClick={() => discard.mutate()}
          >
            {discard.isPending ? "Discarding…" : "Discard"}
          </button>
        </div>
      </form>
    </section>
  );
}
