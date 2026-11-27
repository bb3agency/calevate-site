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
import { ConfirmDialog } from "@/components/confirmDialog";
import { TEXT_ACTION } from "@/components/console/section";
import { BestHoursCard } from "@/components/improve/BestHoursCard";
import { CallAgainCard } from "@/components/improve/CallAgainCard";
import { DiagnoseCards } from "@/components/improve/DiagnoseCards";
import { GiveCallersTimeCard } from "@/components/improve/GiveCallersTimeCard";
import { ImproveCard as Card } from "@/components/improve/ImproveCard";
import { OpeningTestCard } from "@/components/improve/OpeningTestCard";
import { RetrySpreadCard } from "@/components/improve/RetrySpreadCard";
import { TestCallsPausedNote, useTestCallsPaused } from "@/components/phoneService";
import {
  FIELD,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  ToggleSwitch,
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
import {
  useCampaignWhatsApp,
  useSetUpCampaignWhatsApp,
  useSwitchCampaignWhatsApp,
  type CampaignWhatsAppMade,
} from "@/lib/api/followUps";
import { useActAccess } from "@/lib/api/hooks";
import { TEST_CALLS_PAUSED } from "@/lib/api/phoneService";
import { useClientRealm } from "@/lib/api/session";
import { useTestRingsFrom } from "@/lib/api/trialCalls";

import { FirstWordsPlayer } from "../agents/first/FirstWordsPlayer";
import { FallbackNote, RingsFromNote } from "../TestCallStatus";
import { FoldSection } from "./FoldSection";
import { SlotsFullProblem, isSlotsFull } from "./SlotHolders";
import { agentSectionId } from "./campaignSections";
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
      <DiagnoseCards {...props} holder={{ kind: "campaign", id: props.campaignId }} />
      <BestHoursCard {...props} data={insights.data.best_hours} />
      <OpeningTestCard {...props} data={insights.data.opening} />
      <RetrySpreadCard {...props} data={insights.data.retry} />
      <GiveCallersTimeCard
        slug={props.slug}
        holder={{ kind: "campaign", id: props.campaignId }}
        canWrite={props.canWrite}
        refusal={props.refusal}
      />
      <CallAgainCard {...props} />
      <WhatsAppFollowUp
        slug={props.slug}
        campaignId={props.campaignId}
        canWrite={props.canWrite}
        refusal={props.refusal}
      />
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
  const { paused, errorIsPause } = useTestCallsPaused(call.error);
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
  const hearWork = ringsFrom?.lineId
    ? { kind: "line" as const, id: ringsFrom.lineId }
    : ringsFrom?.campaignId
      ? { kind: "campaign" as const, id: ringsFrom.campaignId }
      : null;
  return (
    <div>
      {ringsFrom?.agentId && hearWork ? (
        <div className="mb-3">
          <FirstWordsPlayer session={session} agentId={ringsFrom.agentId} work={hearWork} version={null} />
        </div>
      ) : null}
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
          // A press the server would refuse whatever is typed (no line to ring from) is not
          // offered; the note under the box says why, in the server's words (W1.7).
          disabled={!canWrite || !typed || Boolean(from.data?.unavailable)}
          title={refusal}
          waitingFor={paused ? TEST_CALLS_PAUSED : null}
          onClick={() => call.mutate({ number, numberIsMine: mine })}
        >
          Call me
        </ActionButton>
      </div>
      {errorIsPause && !paused && <TestCallsPausedNote />}
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
        !errorIsPause &&
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

function waitWords(minutes: number): string {
  if (minutes <= 0) return "as soon as the call ends";
  if (minutes % 60 === 0) {
    const hours = minutes / 60;
    return `${hours === 1 ? "an hour" : `${hours} hours`} after the call`;
  }
  return `${minutes === 1 ? "a minute" : `${minutes} minutes`} after the call`;
}

/**
 * D-1041 (founder, 24 Nov 2026: "make the whatsapp card set it up directly"). One press has
 * Pip write the message from this campaign and pick which of its outcomes it is for; the
 * follow-up is saved off, and nothing is sent until the owner turns the switch on. Turning
 * on is one press, as Publish is on the Follow-ups screen; turning off stops the people
 * waiting in it, so it is confirmed, as there.
 */
export function WhatsAppFollowUp({ slug, campaignId, canWrite, refusal }: Omit<Common, "agentId">) {
  const { session, href } = useClientRealm();
  const card = useCampaignWhatsApp(session, campaignId);
  const setUp = useSetUpCampaignWhatsApp(session, campaignId);
  const setUpFeedback = useActionFeedback(setUp, { errorDisplay: "inline" });
  const connectHref = href(`/c/${slug}/integrations/whatsapp`);
  // Writing the message sends a WhatsApp template for review, which the WhatsApp screen keeps
  // to the owner (founder, 25 Nov 2026); turning a made one on or off stays with `canWrite`.
  const templates = useActAccess(
    session,
    "org:manage",
    "billing.ai_assist",
    "set up a WhatsApp follow-up",
  );
  const setUpReason = !templates.allowed ? templates.reason : null;

  const setUpButton = (label: string) => (
    <div className="space-y-1">
      <ActionButton
        variant="secondary-sm"
        status={setUpFeedback.status}
        pendingLabel="Asking Pip…"
        disabled={!templates.allowed}
        title={setUpReason ?? undefined}
        onClick={() => setUp.mutate()}
      >
        {label}
      </ActionButton>
      {setUpReason && <p className="text-meta text-ink-muted">{setUpReason}</p>}
    </div>
  );

  return (
    <Card
      title="Follow up on WhatsApp"
      hint="A message after a call that did not finish, or where they asked for details."
      info={
        <p>
          Pip writes the message from what this campaign is for and its
          knowledge, and WhatsApp checks it before it can be sent. Nothing is
          sent until you turn it on.
        </p>
      }
    >
      {card.isLoading ? (
        <Skeleton rows={2} label="Reading the WhatsApp follow-up" />
      ) : !card.data ? (
        <ProblemNotice error={card.error} onRetry={() => card.refetch()} />
      ) : card.data.phase === "not_connected" ? (
        <div className="space-y-2">
          <p className="text-meta text-ink-muted">Connect WhatsApp to send messages after calls.</p>
          <Link href={connectHref} className={`${SECONDARY_BUTTON_SM} inline-flex`}>
            Connect WhatsApp
          </Link>
        </div>
      ) : card.data.phase === "writing" ? (
        <div className="flex items-center gap-3">
          <span
            className="h-3 w-3 shrink-0 animate-pulse rounded-full bg-brand motion-reduce:animate-none"
            aria-hidden
          />
          <p role="status" className="text-body text-ink">
            Pip is writing the message.
          </p>
        </div>
      ) : card.data.made ? (
        <MadeFollowUp
          slug={slug}
          campaignId={campaignId}
          made={card.data.made}
          connected={card.data.connected}
          connectHref={connectHref}
          canWrite={canWrite}
          refusal={refusal}
          writeAgain={setUpButton("Write it again")}
        />
      ) : (
        <div className="space-y-2">
          {card.data.phase === "failed" && card.data.failure && (
            <p className="text-meta text-ink-muted">{card.data.failure}</p>
          )}
          {setUpButton(card.data.phase === "failed" ? "Try again" : "Set up WhatsApp follow-up")}
        </div>
      )}
      {setUp.error != null && <ProblemNotice error={setUp.error} />}
    </Card>
  );
}

function MadeFollowUp({
  slug,
  campaignId,
  made,
  connected,
  connectHref,
  canWrite,
  refusal,
  writeAgain,
}: {
  slug: string;
  campaignId: string;
  made: CampaignWhatsAppMade;
  connected: boolean;
  connectHref: string;
  canWrite: boolean;
  refusal?: string;
  writeAgain: React.ReactNode;
}) {
  const { session, href } = useClientRealm();
  const flip = useSwitchCampaignWhatsApp(session, campaignId);
  const flipFeedback = useActionFeedback(flip, {
    errorDisplay: "inline",
    successToast: (_card, on) => (on ? "Turned on" : "Turned off"),
  });
  const [confirmOff, setConfirmOff] = useState(false);
  const on = made.status === "live";
  const approved = made.message_status === "approved";
  const reviewing = made.message_status === "pending";
  const pending = flipFeedback.status === "pending";
  const messageId = `wa-message-${campaignId}`;
  const outcomes = made.outcomes.map((o) => o.label).join(", ");

  return (
    <div className="space-y-3">
      {made.message ? (
        <blockquote
          id={messageId}
          lang={made.message_language ?? undefined}
          className="whitespace-pre-line break-words rounded-card border-l-2 border-line bg-surface-muted px-3 py-2 text-body text-ink"
        >
          {made.message}
        </blockquote>
      ) : (
        <p className="text-meta text-ink-muted">This follow-up has no message yet.</p>
      )}
      <p className="text-meta text-ink-muted">
        {outcomes ? `For calls that ended as: ${outcomes}. ` : ""}
        Sent {waitWords(made.wait_minutes)}.
      </p>

      {reviewing && (
        <p className="text-meta text-ink-muted">
          WhatsApp is checking the message. This can take up to a day.
        </p>
      )}
      {!approved && !reviewing && (
        <div className="space-y-2">
          <p className="text-meta text-ink-muted">WhatsApp turned this message down.</p>
          {writeAgain}
        </div>
      )}
      {!connected && (
        <p className="text-meta text-ink-muted">
          WhatsApp is not connected.{" "}
          <Link href={connectHref} className={TEXT_ACTION}>
            Connect WhatsApp
          </Link>
        </p>
      )}

      <ToggleSwitch
        label="On"
        hint={
          pending
            ? on
              ? "Turning off…"
              : "Turning on…"
            : approved
              ? "Sends this message after this campaign's calls."
              : "Can be turned on once WhatsApp approves the message."
        }
        checked={on}
        disabled={!canWrite || pending || (!on && !approved)}
        describedBy={made.message ? messageId : undefined}
        onChange={(next) => {
          flip.reset();
          if (next) flip.mutate(true);
          else setConfirmOff(true);
        }}
      />
      {!canWrite && refusal && <p className="text-meta text-ink-muted">{refusal}</p>}
      {flip.error != null && !confirmOff && <ProblemNotice error={flip.error} />}

      {made.status !== "draft" && (
        <p className="text-meta text-ink-muted tabular-nums">
          {made.sent} sent · {made.replied} replied
        </p>
      )}
      <Link href={href(`/c/${slug}/follow-ups/${made.follow_up_id}`)} className={TEXT_ACTION}>
        Edit
      </Link>

      {confirmOff && (
        <ConfirmDialog
          title="Turn off the WhatsApp follow-up?"
          confirmLabel="Turn it off"
          pendingLabel="Turning off…"
          cancelLabel="Keep it on"
          status={flipFeedback.status}
          error={flip.error}
          onCancel={() => {
            flip.reset();
            setConfirmOff(false);
          }}
          onConfirm={() => flip.mutate(false, { onSuccess: () => setConfirmOff(false) })}
        >
          <p>No more messages are sent, including to people waiting for theirs.</p>
        </ConfirmDialog>
      )}
    </div>
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
