"use client";

/**
 * OTHER CALL SETTINGS (founder, 15 Nov 2026: "the only important information is the timings
 * for calls, failed calls - repeat at the same time next day till successfully called"):
 *
 * - When to call: the hours of the day it may call (inside the platform's 09:00-21:00 IST), and
 *   optionally a day and time to start (the existing Start later).
 * - If nobody answers: try again at the same time the next day until they are reached, on up to
 *   five days. Five is the retry policy's ceiling (`RetryPolicyIn.max_attempts`), and a daily gap
 *   is one of its allowed gaps (`RETRY_GAP_CHOICES` 1440), so this is the existing policy
 *   `max_attempts = days, gaps = [1440] * (days - 1)`. Unending retries are not offered: calling
 *   someone who never answers every day forever is the repeated-call pattern TRAI's rules exist for.
 */

import { useEffect, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { FIELD, ProblemNotice } from "@/components/ui";
import { useUpdateCampaign } from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";

import { FoldSection } from "./FoldSection";

import { PLATFORM_WINDOW, windowRefusal } from "./NewCampaignFlow";

const DAY_MINUTES = 1440;
const MAX_DAYS = 5;

function retryDays(policy: { max_attempts: number; gaps_minutes?: number[] }): number {
  const daily = (policy.gaps_minutes ?? []).every((g) => g === DAY_MINUTES);
  return daily ? policy.max_attempts : 0;
}

export function OtherCallSettings({
  campaignId,
  editable,
  callingHours,
  retryPolicy,
  canWrite,
  refusal,
  startLater,
}: {
  campaignId: string;
  /** Hours and retries change while the campaign is a draft. */
  editable: boolean;
  callingHours: { start: string; end: string } | null | undefined;
  retryPolicy: { max_attempts: number; gaps_minutes?: number[] };
  canWrite: boolean;
  refusal?: string;
  /** The existing Start later card, passed in by the page. */
  startLater?: React.ReactNode;
}) {
  const { session } = useClientRealm();
  const update = useUpdateCampaign(session, campaignId);
  const feedback = useActionFeedback(update, { errorDisplay: "inline" });
  const [start, setStart] = useState(callingHours?.start ?? PLATFORM_WINDOW.start);
  const [end, setEnd] = useState(callingHours?.end ?? PLATFORM_WINDOW.end);
  const [days, setDays] = useState(retryDays(retryPolicy) || MAX_DAYS);

  useEffect(() => {
    setStart(callingHours?.start ?? PLATFORM_WINDOW.start);
    setEnd(callingHours?.end ?? PLATFORM_WINDOW.end);
  }, [callingHours?.start, callingHours?.end]);

  // Said before the save rather than learned from the server's refusal.
  const hoursProblem = windowRefusal(start, end);
  const save = () => {
    if (hoursProblem) return;
    const platform = start === PLATFORM_WINDOW.start && end === PLATFORM_WINDOW.end;
    feedback.run({
      calling_hours: platform ? null : { start, end },
      retry_policy: { max_attempts: days, gaps_minutes: Array(days - 1).fill(DAY_MINUTES) },
    });
  };

  const disabled = !canWrite || !editable;
  return (
    <FoldSection title="Other call settings" tone="settings">
      {!editable && (
        <p className="mb-3 text-meta text-ink-muted">These can be changed while the campaign is a draft.</p>
      )}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div>
          <h3 className="text-body font-semibold text-ink">When to call</h3>
          <p className="mt-0.5 text-meta text-ink-muted">Each day, in IST, from 9am to 9pm at most.</p>
          <div className="mt-2 flex items-end gap-2">
            <label className="text-meta font-medium text-ink">
              From
              <input
                type="time"
                min="09:00"
                max="21:00"
                className={`${FIELD} mt-1 block`}
                value={start}
                disabled={disabled}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label className="text-meta font-medium text-ink">
              To
              <input
                type="time"
                min="09:00"
                max="21:00"
                className={`${FIELD} mt-1 block`}
                value={end}
                disabled={disabled}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
          </div>
          {hoursProblem && (
            <p role="alert" className="mt-2 text-meta text-danger">
              {hoursProblem}
            </p>
          )}
        </div>

        <div>
          <h3 className="text-body font-semibold text-ink">If nobody answers</h3>
          <p className="mt-0.5 text-meta text-ink-muted">Try again at the same time the next day.</p>
          <label className="mt-2 block text-meta font-medium text-ink">
            Keep trying for
            <select
              className={`${FIELD} mt-1 block`}
              value={days}
              disabled={disabled}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              {Array.from({ length: MAX_DAYS }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {n === 1 ? "1 day (no retry)" : `${n} days`}
                </option>
              ))}
            </select>
          </label>
          <p className="mt-1 text-meta text-ink-faint">At most {MAX_DAYS} days, so no one is called every day.</p>
        </div>
      </div>

      {update.error != null && (
        <div className="mt-3">
          <ProblemNotice error={update.error} />
        </div>
      )}
      <div className="mt-4 flex items-center gap-3">
        <ActionButton
          type="button"
          variant="primary-sm"
          status={feedback.status}
          successLabel="Saved"
          disabled={disabled || hoursProblem !== null}
          title={refusal}
          onClick={save}
        >
          Save
        </ActionButton>
      </div>

      {startLater && <div className="mt-6 border-t border-line pt-5">{startLater}</div>}
    </FoldSection>
  );
}
