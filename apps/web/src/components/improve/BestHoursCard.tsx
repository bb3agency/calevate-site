"use client";

/**
 * BEST TIME TO CALL, as one press (D-992 item 8). The calls are counted by PEOPLE: someone
 * rung three times at 10am is one person tried at 10am. A block of the day is offered only
 * once it, and the rest of the day, each have enough people tried and its answer rate is
 * clearly higher (`campaigns/learning.best_block`). "Call only …" narrows this campaign's
 * hours inside the platform's; Undo puts them back. Pip may do it on its own when the owner
 * turns that on.
 */

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ToggleSwitch } from "@/components/ui";
import {
  useBestHoursAuto,
  useBestHoursMove,
  type CampaignInsights,
} from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";
import { clockRange, hourWords } from "@/lib/clock";

import { ImproveCard, MoveError, percent } from "./ImproveCard";

type BestHours = CampaignInsights["best_hours"];

export function BestHoursCard({
  campaignId,
  data,
  canWrite,
  refusal,
}: {
  campaignId: string;
  data: BestHours;
  canWrite: boolean;
  refusal?: string;
}) {
  const { session } = useClientRealm();
  const move = useBestHoursMove(session, campaignId);
  useActionFeedback(move, {
    errorDisplay: "inline",
    successToast: (_, vars) => (vars === "apply" ? "Calling hours narrowed" : "Calling hours put back"),
  });
  const auto = useBestHoursAuto(session, campaignId);
  useActionFeedback(auto, { errorDisplay: "inline" });
  const best = data.best;
  const applied = data.applied;
  const busy = move.isPending || auto.isPending;
  return (
    <ImproveCard
      title="Best time to call"
      hint="When people pick up, by hour (IST)."
      info={`Each person counts once an hour, however many times they were rung. A block of the day is suggested once it and the rest of the day each have ${data.min_people_per_block} people tried, and the chance it really is better reaches ${percent(data.chance_needed)}.`}
    >
      {applied ? (
        <div className="mb-3">
          <p className="text-body text-ink">
            Calls only {clockRange(applied.block.start, applied.block.end)}.
          </p>
          <p className="text-meta text-ink-muted">
            {applied.by === "pip" ? "Pip narrowed the hours. " : ""}
            {applied.before
              ? `Before: ${clockRange(applied.before.start, applied.before.end)}.`
              : "Before: all day, within the allowed hours."}
          </p>
          <ActionButton
            variant="secondary-sm"
            className="mt-2"
            status={move.isPending && move.variables === "undo" ? "pending" : "idle"}
            pendingLabel="Putting back…"
            disabled={!canWrite || busy}
            title={refusal}
            onClick={() => move.mutate("undo")}
          >
            Undo
          </ActionButton>
        </div>
      ) : data.state === "actionable" && best ? (
        <div className="mb-3">
          <p className="text-body text-ink">
            Most people pick up {clockRange(best.start, best.end)}: {percent(best.rate)} of{" "}
            {best.people.toLocaleString("en-IN")} people.
          </p>
          <ActionButton
            variant="primary-sm"
            className="mt-2"
            status={move.isPending && move.variables === "apply" ? "pending" : "idle"}
            pendingLabel="Narrowing…"
            disabled={!canWrite || busy}
            title={refusal}
            onClick={() => move.mutate("apply")}
          >
            Call only {clockRange(best.start, best.end)}
          </ActionButton>
        </div>
      ) : (
        <p className="mb-3 text-meta text-ink-muted">
          {data.state === "empty"
            ? "No calls yet. This fills in as people are called."
            : data.state === "too_few"
              ? `Too few people so far. Each block needs ${data.min_people_per_block} people tried.`
              : "Measuring. No block of the day stands out yet."}
        </p>
      )}
      <MoveError error={move.error} fallback="That did not change the hours" />
      {data.hours.length > 0 && <HourBars hours={data.hours} best={best} />}
      <ToggleSwitch
        className="mt-3"
        label="Let Pip do this once it is clear"
        hint="Off until you turn it on. You can undo what Pip changes."
        checked={data.auto}
        disabled={!canWrite || busy}
        onChange={(on) => auto.mutate(on)}
      />
      <MoveError error={auto.error} fallback="That did not save" />
    </ImproveCard>
  );
}

/** Per hour, people tried (the track) and people who picked up (the fill), labelled in
 * words so the numbers never rest on the bar or its colour alone. */
function HourBars({
  hours,
  best,
}: {
  hours: BestHours["hours"];
  best: BestHours["best"];
}) {
  const max = Math.max(1, ...hours.map((h) => h.people));
  const inBest = (hour: number) =>
    best != null && hour >= Number(best.start.slice(0, 2)) && hour < Number(best.end.slice(0, 2));
  return (
    <ul className="space-y-1" aria-label="People tried and reached by hour">
      {hours.map((h) => (
        <li key={h.hour} className="flex items-center gap-2 text-meta">
          <span className="w-12 shrink-0 text-ink-muted tabular-nums">{hourWords(h.hour)}</span>
          <span className="relative h-3 flex-1 overflow-hidden rounded-sm bg-surface-muted" aria-hidden>
            <span className="absolute inset-y-0 left-0 bg-line" style={{ width: `${(h.people / max) * 100}%` }} />
            <span
              className={`absolute inset-y-0 left-0 ${inBest(h.hour) ? "bg-brand" : "bg-brand/50"}`}
              style={{ width: `${(h.reached / max) * 100}%` }}
            />
          </span>
          <span className="w-32 shrink-0 text-right text-ink tabular-nums">
            {h.reached}/{h.people} people
          </span>
        </li>
      ))}
    </ul>
  );
}
