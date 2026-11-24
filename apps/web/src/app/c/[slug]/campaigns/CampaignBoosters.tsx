"use client";

/**
 * WHAT MAKES A CAMPAIGN WORK BETTER (D-992, item 8): hear the script on your own phone before
 * Start, test a second opening line, call at the hours people answer, call the unanswered
 * again, and follow up on WhatsApp. Each card has its own colour so the eye keeps them apart;
 * status colours stay reserved for status.
 */

import {
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ActionButton, problemToast, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { BestHoursCard } from "@/components/improve/BestHoursCard";
import { CallAgainCard } from "@/components/improve/CallAgainCard";
import { ImproveCard as Card } from "@/components/improve/ImproveCard";
import { OpeningTestCard } from "@/components/improve/OpeningTestCard";
import { RetrySpreadCard } from "@/components/improve/RetrySpreadCard";
import {
  FIELD,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { isAssignable } from "@/lib/agentState";
import { CAMPAIGN_TEST_ANCHOR } from "@/lib/api/agentJobs";
import { useAgents } from "@/lib/api/agents";
import { useUpdateCampaign } from "@/lib/api/campaigns";
import {
  useCampaignInsights,
  useCampaignTestCall,
  useSaveTestNumbers,
  useTestNumbers,
  workspaceKey,
} from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";
import { useTestRingsFrom } from "@/lib/api/trialCalls";

import { FallbackNote, RingsFromNote } from "../TestCallStatus";
import { FoldSection } from "./FoldSection";
import { SlotsFullProblem, isSlotsFull } from "./SlotHolders";
import { agentSectionId } from "./StartCampaign";
import { AgentChoice } from "./NewCampaignSteps";
import { TestCallList } from "./TestCallList";

type Common = {
  slug: string;
  campaignId: string;
  canWrite: boolean;
  refusal?: string;
  agentId?: string;
};

function errorText(error: unknown, fallback: string): string {
  return problemToast(error, fallback).description ?? fallback;
}

/** After Start: what the calls teach, and the next moves. */
export function ImproveTab(props: Common & { status?: string | null }) {
  const { session } = useClientRealm();
  const insights = useCampaignInsights(session, props.campaignId);
  if (insights.isLoading)
    return <Skeleton rows={4} label="Reading what the calls teach" />;
  if (!insights.data)
    return (
      <ProblemNotice
        error={insights.error}
        onRetry={() => insights.refetch()}
      />
    );
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <BestHoursCard {...props} data={insights.data.best_hours} />
      <OpeningTestCard {...props} data={insights.data.opening} />
      <RetrySpreadCard {...props} data={insights.data.retry} />
      <CallAgainCard {...props} />
      <WhatsAppFollowUp slug={props.slug} />
      <HearItFirst {...props} />
    </div>
  );
}

function HearItFirst({ slug, campaignId, canWrite, refusal, agentId }: Common) {
  const { session } = useClientRealm();
  const call = useCampaignTestCall(session, campaignId);
  useActionFeedback(call, { errorDisplay: "inline" });
  const saved = useTestNumbers(session, campaignId);
  const saveNumbers = useSaveTestNumbers(session, campaignId);
  useActionFeedback(saveNumbers, { errorDisplay: "inline" });
  return (
    <TestCallForm
      slug={slug}
      call={call}
      saved={saved}
      saveNumbers={saveNumbers}
      canWrite={canWrite}
      refusal={refusal}
      ringsFrom={{ agentId, campaignId }}
    />
  );
}

/** The account's saved test numbers as read: a failed read is shown, never taken as none. */
type SavedTestNumbers = Pick<
  UseQueryResult<{ numbers: string[] }>,
  "data" | "error" | "refetch"
>;

/** What a test call answers, from a campaign's route or a line's. */
type TestCallAnswer = {
  status: "queued" | "blocked";
  blocked_reason?: string | null;
  call_id?: string | null;
  shared_fallback?: boolean;
};

/**
 * THE TEST CALL FORM, shared by a campaign and an inbound line: the saved numbers to pick
 * from, the number box, "This number is mine", and Call me. The account's saved numbers are
 * one list; only a screen that can change it passes `saveNumbers`. The screen that makes
 * `call` gives it its feedback (`useActionFeedback`), as it does every mutation it starts.
 */
export function TestCallForm({
  slug,
  call,
  saved,
  saveNumbers,
  canWrite,
  refusal,
  ringsFrom,
}: {
  slug: string;
  call: UseMutationResult<
    TestCallAnswer,
    Error,
    { number: string; numberIsMine: boolean }
  >;
  saved: SavedTestNumbers;
  saveNumbers?: UseMutationResult<unknown, Error, string[]>;
  canWrite: boolean;
  refusal?: string;
  /** What the call rings through, so the form can say which number it rings from. */
  ringsFrom?: { agentId?: string; lineId?: string; campaignId?: string };
}) {
  const { href, session } = useClientRealm();
  const from = useTestRingsFrom(session, ringsFrom ?? {});
  // Saving replaces the whole list, so nothing is saved or removed until the list is read:
  // a Save over a pending or failed read would drop every number already saved.
  const loaded = saved.data !== undefined;
  const numbers = saved.data?.numbers ?? [];
  const [number, setNumber] = useState("");
  // The owner's own tick, never assumed (D-855): it lifts the calling-hours limit for this
  // number and is recorded as their word, so it starts off and clears when the number changes.
  const [mine, setMine] = useState(false);
  const choose = (value: string) => {
    setNumber(value);
    setMine(false);
  };
  const result = call.data;
  const digits = number.replace(/\D/g, "");
  const typed = digits.length >= 10;
  const isSaved = numbers.some(
    (n) => n.replace(/\D/g, "").endsWith(digits.slice(-10)) && typed,
  );
  // The first saved number is ready to call, so a test is one press.
  useEffect(() => {
    if (number === "" && numbers.length > 0) setNumber(numbers[0]);
    // Only when the list first arrives; a cleared box stays cleared.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved.data]);
  return (
    <div>
      {saved.error != null && !loaded && (
        <div className="mb-3">
          <ProblemNotice
            error={saved.error}
            onRetry={() => void saved.refetch()}
          />
        </div>
      )}
      {numbers.length > 0 && (
        <div className="mb-3">
          <p className="text-meta font-medium text-ink">Saved numbers</p>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {numbers.map((n) => {
              const chosen =
                n.replace(/\D/g, "").endsWith(digits.slice(-10)) && typed;
              return (
                <span
                  key={n}
                  className={`inline-flex items-center rounded-full border text-meta ${
                    chosen
                      ? "border-series-6 bg-series-6 text-white"
                      : "border-line bg-surface text-ink"
                  }`}
                >
                  <button
                    type="button"
                    aria-pressed={chosen}
                    className="py-1 pl-3 pr-2 font-medium tabular-nums touch:min-h-11"
                    onClick={() => choose(n)}
                  >
                    {formatPhone(n)}
                  </button>
                  {saveNumbers ? (
                    <ActionButton
                      variant="text"
                      aria-label={`Remove ${formatPhone(n)} from saved numbers`}
                      title="Remove"
                      status={
                        saveNumbers.isPending &&
                        saveNumbers.variables !== undefined &&
                        numbers.includes(n) &&
                        !saveNumbers.variables.includes(n)
                          ? "pending"
                          : "idle"
                      }
                      pendingLabel={<></>}
                      disabled={!canWrite || !loaded || (saveNumbers.isPending && saveNumbers.variables?.includes(n) !== false)}
                      className="mx-0! min-h-0! rounded-full! py-1! pl-1! pr-2.5! text-inherit! opacity-70 hover:bg-transparent! hover:opacity-100 touch:min-h-11 touch:min-w-11"
                      onClick={() =>
                        saveNumbers.mutate(numbers.filter((x) => x !== n))
                      }
                    >
                      <X aria-hidden className="h-3.5 w-3.5" />
                    </ActionButton>
                  ) : null}
                </span>
              );
            })}
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-48 flex-1 text-meta font-medium text-ink">
          {numbers.length > 0 ? "Number to call" : "Your number"}
          <input
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            className={`${FIELD} mt-1 w-full`}
            placeholder="98765 43210"
            value={number}
            onChange={(e) => choose(e.target.value)}
          />
        </label>
        {saveNumbers ? (
          <ActionButton
            variant="secondary-sm"
            status={
              saveNumbers.isPending && (saveNumbers.variables?.length ?? 0) > numbers.length ? "pending" : "idle"
            }
            pendingLabel="Saving…"
            disabled={
              !canWrite ||
              !loaded ||
              !typed ||
              isSaved ||
              numbers.length >= 10 ||
              (saveNumbers.isPending && (saveNumbers.variables?.length ?? 0) <= numbers.length)
            }
            title={
              isSaved
                ? "Already saved"
                : numbers.length >= 10
                  ? "Up to 10 saved numbers"
                  : refusal
            }
            onClick={() => saveNumbers.mutate([...numbers, number])}
          >
            {isSaved ? "Saved" : "Save"}
          </ActionButton>
        ) : null}
        <ActionButton
          variant="secondary-sm"
          status={call.isPending ? "pending" : "idle"}
          pendingLabel="Calling…"
          disabled={!canWrite || !typed}
          title={refusal}
          onClick={() => call.mutate({ number, numberIsMine: mine })}
        >
          Call me
        </ActionButton>
      </div>
      <p className="mt-1 text-meta text-ink-muted">
        A number you call is saved for next time. Up to 10.
      </p>
      <RingsFromNote from={from.data} />
      <label className="mt-2 flex w-fit items-center gap-2 text-meta text-ink-muted touch:min-h-11">
        <input
          type="checkbox"
          className="h-4 w-4 accent-brand-strong touch:h-5 touch:w-5"
          checked={mine}
          onChange={(e) => setMine(e.target.checked)}
        />
        This number is my own. Test calls to it can ring at any hour.
      </label>
      {saveNumbers?.error != null && (
        <p role="alert" className="mt-2 text-meta text-danger">
          {errorText(saveNumbers.error, "The number did not save")}
        </p>
      )}
      {call.error != null &&
        (isSlotsFull(call.error) ? (
          <SlotsFullProblem slug={slug} error={call.error} />
        ) : (
          <p role="alert" className="mt-2 text-meta text-danger">
            {errorText(call.error, "The test call did not start")}
          </p>
        ))}
      {result?.status === "queued" && (
        <p role="status" className="mt-2 text-meta text-ink">
          Calling you now.{" "}
          {result.call_id && (
            <Link
              className="inline-flex items-center text-brand-strong underline touch:min-h-11"
              href={href(`/c/${slug}/calls/${result.call_id}`)}
            >
              Open the call
            </Link>
          )}
        </p>
      )}
      {result?.status === "queued" && (
        <FallbackNote shown={result.shared_fallback} />
      )}
      {result?.status === "blocked" && (
        <p role="alert" className="mt-2 text-meta text-warn">
          {result.blocked_reason ??
            "The test call could not be placed right now."}
        </p>
      )}
    </div>
  );
}

/** +919876543210 as +91 98765 43210; anything else as stored. */
function formatPhone(e164: string): string {
  const m = /^\+91(\d{5})(\d{5})$/.exec(e164);
  return m ? `+91 ${m[1]} ${m[2]}` : e164;
}

function WhatsAppFollowUp({ slug }: { slug: string }) {
  const { href } = useClientRealm();
  return (
    <Card
      title="Follow up on WhatsApp"
      hint="Send a WhatsApp message after a call."
      info={
        <>
          <p>
            For example the install steps or a link, to the people who asked for
            it or did not finish.
          </p>
          <p>
            Make a follow-up that starts when a call ends, choose this
            campaign&apos;s agent and the outcomes it is for, then add a
            WhatsApp step.
          </p>
        </>
      }
    >
      <Link
        href={href(`/c/${slug}/follow-ups`)}
        className={`${SECONDARY_BUTTON_SM} inline-flex`}
      >
        Set up a follow-up
      </Link>
    </Card>
  );
}

/**
 * STEP 4, KEPT SIMPLE (founder, 15 Nov 2026): the agents to choose from, then a test call with
 * the chosen one speaking this campaign's script. What the call says (its opening included)
 * belongs in the script, not here. The agent can be changed while the campaign is a draft.
 */
export function AgentSection({
  campaignId,
  agentId,
  editable,
  canWrite,
}: Omit<Common, "slug"> & {
  agentId: string;
  editable: boolean;
  status?: string | null;
}) {
  const { session, href } = useClientRealm();
  const agents = useAgents(session);
  const update = useUpdateCampaign(session, campaignId);
  useActionFeedback(update, { errorDisplay: "inline" });
  const client = useQueryClient();
  const options = (agents.data ?? []).filter(isAssignable);

  const choose = (id: string) => {
    if (id === agentId || !editable || !canWrite) return;
    update.mutate(
      { agent_id: id },
      {
        onSuccess: () =>
          void client.invalidateQueries({
            queryKey: workspaceKey(session.orgSlug, campaignId),
          }),
      },
    );
  };

  return (
    <FoldSection
      id={agentSectionId(campaignId)}
      title="Agent"
      tone="agent"
      hint="Who makes these calls."
    >
      <div className="space-y-4">
        {!agents.data && !agents.error && (
          <Skeleton rows={2} label="Loading your agents" />
        )}
        {agents.error != null && (
          <ProblemNotice
            error={agents.error}
            onRetry={() => agents.refetch()}
          />
        )}
        {options.length > 0 && (
          <AgentChoice
            onChange={choose}
            agentOptions={options}
            selectedAgentId={agentId}
            selectedAgent={options.find((agent) => agent.id === agentId)}
            disabled={!canWrite || !editable || update.isPending}
          />
        )}
        {!editable && (
          <p className="text-meta text-ink-muted">
            It is archived. Restore it to change the agent.
          </p>
        )}
        {update.error != null && <ProblemNotice error={update.error} />}
        <Link
          href={href(`/c/${session.orgSlug}/agents/${agentId}?section=settings`)}
          className={TEXT_ACTION}
        >
          Voice and call settings
        </Link>
      </div>
    </FoldSection>
  );
}

/**
 * The chosen agent rings the owner's phone with this campaign's script, from the campaign's
 * calling number once the account has paid and holds one, else from our test number
 * (D-1020); the form says which before the call.
 */
export function TestCallSection(props: Common) {
  return (
    <FoldSection
      id={CAMPAIGN_TEST_ANCHOR}
      title="Test call"
      tone="test"
      hint="The chosen agent rings your phone."
      info="It rings with this campaign's own script and settings, so you hear exactly what people will hear. The agent's own script is not changed."
    >
      <HearItFirst {...props} />
      <TestCallList {...props} />
    </FoldSection>
  );
}
