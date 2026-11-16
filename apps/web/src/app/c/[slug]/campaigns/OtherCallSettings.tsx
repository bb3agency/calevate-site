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
 * - Calls at once, held to the account's call lines; the number it calls from (a draft's
 *   choice, since the compliance gate passed on it at launch); and the kind of call the
 *   campaign's own choices make it (D-943), said rather than chosen.
 */

import { useEffect, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { FIELD, ProblemNotice, formatPhone } from "@/components/ui";
import { Why } from "@/components/why";
import { useMyCallLines } from "@/lib/api/callLines";
import { useCampaignNumbers, useUpdateCampaign, type CampaignProgress } from "@/lib/api/campaigns";
import { useCampaignPurpose } from "@/lib/api/compliancePack";
import { useClientRealm } from "@/lib/api/session";

import { AtOnceHint } from "./CampaignSettings";
import { campaignNumbers } from "./NewCampaignSteps";
import { clampConcurrency, concurrencyCap } from "./campaignForm";

import { FoldSection } from "./FoldSection";

import { PLATFORM_WINDOW, windowRefusal } from "./callingWindow";

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
  progress,
  numberEditable,
}: {
  campaignId: string;
  /** Calls at once and the calling number as they stand. */
  progress: CampaignProgress;
  /** The number changes only on a draft. */
  numberEditable: boolean;
  /** Hours and retries change until the campaign stops. */
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
  const callLines = useMyCallLines(session);
  const cap = concurrencyCap(callLines.data?.call_lines);
  const numbers = useCampaignNumbers(session);
  const purpose = useCampaignPurpose(session, campaignId).data?.purpose;
  const [atOnce, setAtOnce] = useState(progress.concurrency);
  const [numberId, setNumberId] = useState(progress.number_id ?? "");
  useEffect(() => setAtOnce(progress.concurrency), [progress.concurrency]);
  useEffect(() => setNumberId(progress.number_id ?? ""), [progress.number_id]);
  const callingNumbers = campaignNumbers(numbers.data);

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
      concurrency: clampConcurrency(atOnce, cap),
      ...(numberEditable ? { number_id: numberId || null } : {}),
    });
  };

  const disabled = !canWrite || !editable;
  return (
    <FoldSection title="Other call settings" tone="settings">
      {!editable && (
        <p className="mb-3 text-meta text-ink-muted">It has stopped, so these no longer change anything.</p>
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

      <div className="mt-6 grid grid-cols-1 gap-6 border-t border-line pt-5 md:grid-cols-2">
        <div>
          <h3 className="text-body font-semibold text-ink">Calls at once</h3>
          <p className="mt-0.5 text-meta text-ink-muted">How many people it calls at the same time.</p>
          <label className="mt-2 block text-meta font-medium text-ink">
            Up to
            <select
              className={`${FIELD} mt-1 block`}
              value={clampConcurrency(atOnce, cap)}
              disabled={disabled}
              onChange={(e) => setAtOnce(Number(e.target.value))}
            >
              {Array.from({ length: cap ?? progress.concurrency }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {n === 1 ? "1 call" : `${n} calls`}
                </option>
              ))}
            </select>
          </label>
          <AtOnceHint progress={progress} className="mt-1 block text-meta text-ink-muted" />
        </div>

        <div>
          <h3 className="text-body font-semibold text-ink">Calling from</h3>
          <p className="mt-0.5 text-meta text-ink-muted">The number people see when it rings.</p>
          <label className="mt-2 block text-meta font-medium text-ink">
            Number
            <select
              className={`${FIELD} mt-1 block`}
              value={numberId}
              disabled={disabled || !numberEditable}
              onChange={(e) => setNumberId(e.target.value)}
            >
              <option value="">Your agent&rsquo;s number</option>
              {callingNumbers.map((n) => (
                <option key={n.id} value={n.id}>
                  {formatPhone(n.e164)}
                </option>
              ))}
            </select>
          </label>
          {!numberEditable && (
            <p className="mt-1 text-meta text-ink-faint">Set before it started; the checks passed on this number.</p>
          )}
        </div>

        {purpose && purpose.purpose !== "unclear" && (
          <div className="md:col-span-2">
            <h3 className="text-body font-semibold text-ink">Kind of call</h3>
            <p className="mt-0.5 text-body text-ink">{purpose.label}</p>
            {/* The window is the regulation's, stated rather than enforced: a list carries one
                declared date, so the gate cannot check each person's (D-943). */}
            {purpose.window ? (
              <p className="text-meta text-ink-muted">Permission lasts {purpose.window}.</p>
            ) : null}
            <p className="text-meta text-ink-muted">
              <Why inline>
                {purpose.explanation}
                {purpose.window ? " We don't check each person's date for you." : ""}
              </Why>
            </p>
          </div>
        )}
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
