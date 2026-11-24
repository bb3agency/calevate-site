"use client";

/**
 * TEST A SECOND OPENING, honestly (D-992 item 8). The opening is said after someone picks
 * up, so the test measures who STAYS past the first seconds, with reaching the goal shown
 * beside it. It reports a chance, never a verdict, and decides on its own only with enough
 * people on both sides (`campaigns/learning.opening_verdict`): the stronger opening then
 * becomes the campaign's opening through the ordinary script save, the AI and recording
 * notices still said, and the owner can undo it. Before it starts, the card says whether the
 * list is large enough; a list too small gets the practice comparison instead.
 */

import { useEffect, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProgressBar } from "@/components/interior/progress-bar";
import { FIELD } from "@/components/ui";
import {
  useOpeningPractice,
  useSaveOpeningB,
  useUndoOpening,
  type CampaignInsights,
} from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";

import { ImproveCard, MoveError, percent } from "./ImproveCard";

type OpeningTest = CampaignInsights["opening"];

/** What the list can tell, before the test starts. */
export function listSizeWords(test: OpeningTest): string {
  const size = test.list_size;
  const need = test.min_answered_per_opening.toLocaleString("en-IN");
  if (size.large_enough === true) return `Large enough: each opening needs ${need} people who pick up.`;
  if (size.large_enough === false)
    return `Too small to tell two openings apart on calls: each needs ${need} people who pick up, and this list has ${size.people.toLocaleString("en-IN")} people.`;
  return `Each opening needs ${need} people who pick up. How many will is known once some calls are made.`;
}

export function OpeningTestCard({
  campaignId,
  data,
  canWrite,
  refusal,
}: {
  campaignId: string;
  data: OpeningTest;
  canWrite: boolean;
  refusal?: string;
}) {
  const { session } = useClientRealm();
  const save = useSaveOpeningB(session, campaignId);
  useActionFeedback(save, { errorDisplay: "inline" });
  const undo = useUndoOpening(session, campaignId);
  useActionFeedback(undo, { errorDisplay: "inline", successToast: "The old opening is back" });
  const practice = useOpeningPractice(session, campaignId);
  useActionFeedback(practice, { errorDisplay: "inline" });
  const [text, setText] = useState("");
  useEffect(() => setText(data.opening_b ?? ""), [data.opening_b]);
  const running = data.opening_b != null;
  const typed = text.trim();
  const small = data.list_size.large_enough === false;
  const decision = data.decision;
  return (
    <ImproveCard
      title="Test a second opening"
      hint="Half hear this opening, half the script's own."
      info={`It counts who stays past the first ${data.stayed_seconds} seconds, because the opening is said after they pick up. It wins on its own once the chance reaches ${percent(data.win_chance)} with ${data.min_answered_per_opening} people who picked up on each side. The AI and recording notices are still said.`}
    >
      {!running && decision && !decision.undone && (
        <div className="mb-3">
          <p className="text-body text-ink">
            {decision.winner === "b"
              ? decision.applied
                ? "The second opening won. It is now this campaign's opening."
                : "The second opening won. Put it in the script to use it."
              : "The script's own opening won. The test has ended."}
          </p>
          <p className="text-meta text-ink-muted">
            Chance the second opening keeps more people: {percent(decision.chance_b_better)}.
          </p>
          {decision.can_undo && (
            <ActionButton
              variant="secondary-sm"
              className="mt-2"
              status={undo.isPending ? "pending" : "idle"}
              pendingLabel="Putting back…"
              disabled={!canWrite}
              title={refusal}
              onClick={() => undo.mutate()}
            >
              Undo
            </ActionButton>
          )}
          <MoveError error={undo.error} fallback="The old opening was not put back" />
        </div>
      )}
      <label className="block text-meta font-medium text-ink" htmlFor={`${campaignId}-opening-b`}>
        Second opening
      </label>
      <textarea
        id={`${campaignId}-opening-b`}
        className={`${FIELD} mt-1 min-h-20 w-full resize-y`}
        maxLength={200}
        value={text}
        placeholder="A different first sentence, to see which keeps more people talking."
        onChange={(e) => setText(e.target.value)}
      />
      {!running && <p className="mt-1 text-meta text-ink-muted">{listSizeWords(data)}</p>}
      <div className="mt-2 flex flex-wrap gap-2">
        {small && !running ? (
          <ActionButton
            variant="primary-sm"
            status={practice.isPending ? "pending" : "idle"}
            pendingLabel="Comparing…"
            disabled={!typed}
            onClick={() => practice.mutate(typed)}
          >
            Compare in practice
          </ActionButton>
        ) : (
          <ActionButton
            variant="primary-sm"
            status={save.isPending && save.variables !== null ? "pending" : "idle"}
            pendingLabel="Saving…"
            disabled={
              !canWrite ||
              !typed ||
              typed === (data.opening_b ?? "") ||
              (save.isPending && save.variables === null)
            }
            title={refusal}
            onClick={() => save.mutate(typed)}
          >
            {running ? "Save opening" : "Start the test"}
          </ActionButton>
        )}
        {running && (
          <ActionButton
            variant="secondary-sm"
            status={save.isPending && save.variables === null ? "pending" : "idle"}
            pendingLabel="Stopping…"
            disabled={!canWrite || (save.isPending && save.variables !== null)}
            onClick={() => save.mutate(null)}
          >
            Stop the test
          </ActionButton>
        )}
      </div>
      <MoveError error={save.error} fallback="That did not save" />
      <MoveError error={practice.error} fallback="The comparison did not run" />
      {practice.data && !running && <PracticeResult result={practice.data} />}
      {running && <Measuring data={data} />}
    </ImproveCard>
  );
}

function Measuring({ data }: { data: OpeningTest }) {
  const [a, b] = data.openings;
  if (!a || !b) return null;
  const fewest = Math.min(a.answered, b.answered);
  return (
    <div className="mt-3 space-y-2">
      {data.state === "too_few" ? (
        <ProgressBar
          value={fewest}
          max={data.min_answered_per_opening}
          label={`People who picked up, on the side with fewer: ${fewest} of ${data.min_answered_per_opening}`}
          pendingLabel="Measuring"
          completeLabel="Enough to decide"
        />
      ) : (
        data.chance_b_better != null && (
          <p className="text-meta text-ink">
            Chance the second opening keeps more people: {percent(data.chance_b_better)}. It wins on
            its own at {percent(data.win_chance)}.
          </p>
        )
      )}
      <table className="w-full text-meta">
        <caption className="sr-only">The two openings so far</caption>
        <thead className="text-ink-muted">
          <tr>
            <th scope="col" className="text-left font-medium">Opening</th>
            <th scope="col" className="text-right font-medium">Picked up</th>
            <th scope="col" className="text-right font-medium">Stayed</th>
            <th scope="col" className="text-right font-medium">Goal reached</th>
          </tr>
        </thead>
        <tbody className="text-ink">
          {[
            { label: "Script's own", o: a },
            { label: "Second", o: b },
          ].map(({ label, o }) => (
            <tr key={o.variant}>
              <th scope="row" className="text-left font-normal">{label}</th>
              <td className="text-right tabular-nums">{o.answered.toLocaleString("en-IN")}</td>
              <td className="text-right tabular-nums">
                {o.stayed.toLocaleString("en-IN")}
                {o.stayed_rate != null && ` (${percent(o.stayed_rate)})`}
              </td>
              <td className="text-right tabular-nums">
                {o.goal_reached.toLocaleString("en-IN")}
                {o.goal_rate != null && ` (${percent(o.goal_rate)})`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PracticeResult({ result }: { result: NonNullable<ReturnType<typeof useOpeningPractice>["data"]> }) {
  const verdict =
    result.fewer === "b"
      ? "The second opening has fewer mistakes."
      : result.fewer === "a"
        ? "The script's own opening has fewer mistakes."
        : "Both have as many mistakes.";
  return (
    <div className="mt-3 space-y-2" role="status">
      <p className="text-body text-ink">{verdict}</p>
      {[
        { label: "Script's own", side: result.own },
        { label: "Second", side: result.second },
      ].map(({ label, side }) => (
        <div key={label}>
          <p className="text-meta font-medium text-ink">
            {label}: {side.mistakes.length === 0 ? "no mistakes" : `${side.mistakes.length} to fix`}
          </p>
          {side.mistakes.length > 0 && (
            <ul className="list-disc pl-5 text-meta text-ink-muted">
              {side.mistakes.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}
