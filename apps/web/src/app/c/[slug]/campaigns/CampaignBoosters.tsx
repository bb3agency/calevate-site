"use client";

/**
 * WHAT MAKES A CAMPAIGN WORK BETTER (D-992, item 8): hear the script on your own phone before
 * Start, test a second opening line, call at the hours people answer, call the unanswered
 * again, and follow up on WhatsApp. Each card has its own colour so the eye keeps them apart;
 * status colours stay reserved for status.
 */

import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { problemToast, useActionFeedback } from "@/components/arc/feedback";
import { InfoTip } from "@/components/console/infoTip";
import { FIELD, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { isAssignable } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import { useDuplicateCampaign, useUpdateCampaign } from "@/lib/api/campaigns";
import {
  useCampaignInsights,
  useCampaignTestCall,
  useSaveOpeningB,
  useSaveTestNumbers,
  useTestNumbers,
  workspaceKey,
  type CampaignInsights,
} from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";
import { hourWords } from "@/lib/clock";

import { CampaignVoiceSettings } from "./CampaignVoiceSettings";
import { FoldSection } from "./FoldSection";
import { AgentChoice } from "./NewCampaignSteps";
import { TestCallList } from "./TestCallList";

type Common = { slug: string; campaignId: string; canWrite: boolean; refusal?: string };

function Card({
  title,
  hint,
  info,
  children,
}: {
  title: string;
  hint: string;
  info?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-card border border-line p-4 sm:p-5">
      <h3 className="text-body font-semibold text-ink">{title}</h3>
      <p className="mt-0.5 flex items-center gap-1 text-meta text-ink-muted">
        <span className="block">{hint}</span>
        {info && (
          <InfoTip label={title.toLowerCase()} align="start">
            {info}
          </InfoTip>
        )}
      </p>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function errorText(error: unknown, fallback: string): string {
  return problemToast(error, fallback).description ?? fallback;
}

/** After Start: what the calls teach, and the next moves. */
export function ImproveTab(props: Common) {
  const { session } = useClientRealm();
  const insights = useCampaignInsights(session, props.campaignId);
  if (insights.isLoading) return <Skeleton rows={4} label="Reading what the calls teach" />;
  if (!insights.data) return <ProblemNotice error={insights.error} onRetry={() => insights.refetch()} />;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <BestTime insights={insights.data} />
      <OpeningTest {...props} insights={insights.data} />
      <CallUnansweredAgain {...props} />
      <WhatsAppFollowUp slug={props.slug} />
      <HearItFirst {...props} />
    </div>
  );
}

function HearItFirst({ slug, campaignId, canWrite, refusal }: Common) {
  const { session, href } = useClientRealm();
  const call = useCampaignTestCall(session, campaignId);
  useActionFeedback(call, { errorDisplay: "inline" });
  const saved = useTestNumbers(session, campaignId);
  const saveNumbers = useSaveTestNumbers(session, campaignId);
  const numbers = saved.data?.numbers ?? [];
  const [number, setNumber] = useState("");
  const [mine, setMine] = useState(true);
  const result = call.data;
  const digits = number.replace(/\D/g, "");
  const typed = digits.length >= 10;
  const isSaved = numbers.some((n) => n.replace(/\D/g, "").endsWith(digits.slice(-10)) && typed);
  // The first saved number is ready to call, so a test is one press.
  useEffect(() => {
    if (number === "" && numbers.length > 0) setNumber(numbers[0]);
    // Only when the list first arrives; a cleared box stays cleared.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saved.data]);
  return (
    <div>
      {numbers.length > 0 && (
        <div className="mb-3">
          <p className="text-meta font-medium text-ink">Saved numbers</p>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {numbers.map((n) => {
              const chosen = n.replace(/\D/g, "").endsWith(digits.slice(-10)) && typed;
              return (
                <span
                  key={n}
                  className={`inline-flex items-center rounded-full border text-meta ${
                    chosen ? "border-series-6 bg-series-6 text-white" : "border-line bg-surface text-ink"
                  }`}
                >
                  <button
                    type="button"
                    aria-pressed={chosen}
                    className="py-1 pl-3 pr-2 font-medium tabular-nums"
                    onClick={() => setNumber(n)}
                  >
                    {formatPhone(n)}
                  </button>
                  <button
                    type="button"
                    aria-label={`Remove ${formatPhone(n)} from saved numbers`}
                    title="Remove"
                    disabled={!canWrite || saveNumbers.isPending}
                    className="rounded-full py-1 pl-1 pr-2.5 opacity-70 hover:opacity-100"
                    onClick={() => saveNumbers.mutate(numbers.filter((x) => x !== n))}
                  >
                    <X aria-hidden className="h-3.5 w-3.5" />
                  </button>
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
            onChange={(e) => setNumber(e.target.value)}
          />
        </label>
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={!canWrite || !typed || isSaved || numbers.length >= 10 || saveNumbers.isPending}
          title={isSaved ? "Already saved" : numbers.length >= 10 ? "Up to 10 saved numbers" : refusal}
          onClick={() => saveNumbers.mutate([...numbers, number])}
        >
          {isSaved ? "Saved" : saveNumbers.isPending ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={!canWrite || !typed || call.isPending}
          title={refusal}
          onClick={() => call.mutate({ number, numberIsMine: mine })}
        >
          {call.isPending ? "Calling…" : "Call me"}
        </button>
      </div>
      <p className="mt-1 text-meta text-ink-muted">A number you call is saved for next time. Up to 10.</p>
      <label className="mt-2 flex items-center gap-2 text-meta text-ink-muted">
        <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
        This number is mine
      </label>
      {saveNumbers.error != null && (
        <p role="alert" className="mt-2 text-meta text-danger">
          {errorText(saveNumbers.error, "The number did not save")}
        </p>
      )}
      {call.error != null && (
        <p role="alert" className="mt-2 text-meta text-danger">
          {errorText(call.error, "The test call did not start")}
        </p>
      )}
      {result?.status === "queued" && (
        <p role="status" className="mt-2 text-meta text-ink">
          Calling you now.{" "}
          {result.call_id && (
            <Link className="text-brand-strong underline" href={href(`/c/${slug}/calls/${result.call_id}`)}>
              Open the call
            </Link>
          )}
        </p>
      )}
      {result?.status === "blocked" && (
        <p role="alert" className="mt-2 text-meta text-warn">
          {result.blocked_reason ?? "The test call could not be placed right now."}
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

function OpeningTest({ campaignId, canWrite, refusal, insights }: Common & { insights?: CampaignInsights }) {
  const { session } = useClientRealm();
  const fallback = useCampaignInsights(session, campaignId);
  const data = insights ?? fallback.data;
  const save = useSaveOpeningB(session, campaignId);
  useActionFeedback(save, { errorDisplay: "inline" });
  const [text, setText] = useState("");
  useEffect(() => setText(data?.opening_b ?? ""), [data?.opening_b]);
  const running = Boolean(data?.opening_b);
  const [a, b] = data?.openings ?? [];
  return (
    <Card
      title="Test a second opening line"
      hint="Half hear this opening, half the script's own."
    >
      <p className="mb-2 text-meta text-ink-muted">The AI and recording notices are still said.</p>
      <label className="sr-only" htmlFor={`${campaignId}-opening-b`}>
        Second opening line
      </label>
      <textarea
        id={`${campaignId}-opening-b`}
        className={`${FIELD} min-h-20 w-full resize-y`}
        maxLength={200}
        value={text}
        placeholder="Namaskaram! This is Anjali from Rytu Khata. Do you have two minutes to set up the app?"
        onChange={(e) => setText(e.target.value)}
      />
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          className={PRIMARY_BUTTON_SM}
          disabled={!canWrite || !text.trim() || text.trim() === (data?.opening_b ?? "") || save.isPending}
          title={refusal}
          onClick={() => save.mutate(text.trim())}
        >
          {running ? "Save opening" : "Start the test"}
        </button>
        {running && (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={!canWrite || save.isPending}
            onClick={() => save.mutate(null)}
          >
            Stop the test
          </button>
        )}
      </div>
      {save.error != null && (
        <p role="alert" className="mt-2 text-meta text-danger">
          {errorText(save.error, "That did not save")}
        </p>
      )}
      {running && a && b && (
        <div className="mt-3 space-y-2">
          <table className="w-full text-meta">
            <thead className="text-ink-muted">
              <tr>
                <th className="text-left font-medium">Opening</th>
                <th className="text-right font-medium">People</th>
                <th className="text-right font-medium">Answered</th>
                <th className="text-right font-medium">Goal reached</th>
              </tr>
            </thead>
            <tbody className="text-ink">
              {[
                { label: "Script's own", o: a },
                { label: "Second", o: b },
              ].map(({ label, o }) => (
                <tr key={o.variant}>
                  <td>{label}</td>
                  <td className="text-right tabular-nums">{o.people.toLocaleString("en-IN")}</td>
                  <td className="text-right tabular-nums">{o.answered.toLocaleString("en-IN")}</td>
                  <td className="text-right tabular-nums">
                    {o.goal_reached.toLocaleString("en-IN")}
                    {o.goal_rate != null && ` (${Math.round(o.goal_rate * 100)}%)`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data?.opening_verdict && <p className="text-meta text-ink-muted">{data.opening_verdict}</p>}
        </div>
      )}
    </Card>
  );
}

function BestTime({ insights }: { insights: CampaignInsights }) {
  const max = Math.max(1, ...insights.hours.map((h) => h.calls));
  const best = new Set(insights.best_hours.map((h) => h.hour));
  return (
    <Card
      title="Best time to call"
      hint="When people answer, by hour (IST)."
      info={`An hour needs ${insights.min_calls_per_hour} calls before it can be judged.`}
    >
      {insights.hours.length === 0 ? (
        <p className="text-meta text-ink-muted">No calls yet.</p>
      ) : (
        <>
          {insights.best_hours.length > 0 ? (
            <p className="mb-3 text-body text-ink">
              Best:{" "}
              {insights.best_hours
                .map((h) => `${hourWords(h.hour)} (${Math.round(h.rate * 100)}% answer)`)
                .join(", ")}
            </p>
          ) : (
            <p className="mb-3 text-meta text-ink-muted">Not enough calls in any hour yet to say.</p>
          )}
          {insights.best_hours.length > 0 && (
            <p className="mb-3 text-meta text-ink-muted">Narrow the calling hours in How it calls.</p>
          )}
          <ul className="space-y-1" aria-label="Calls and answers by hour">
            {insights.hours.map((h) => (
              <li key={h.hour} className="flex items-center gap-2 text-meta">
                <span className="w-12 shrink-0 text-ink-muted tabular-nums">{hourWords(h.hour)}</span>
                <span className="relative h-3 flex-1 overflow-hidden rounded-sm bg-surface-muted">
                  <span
                    className="absolute inset-y-0 left-0 bg-line"
                    style={{ width: `${(h.calls / max) * 100}%` }}
                    aria-hidden
                  />
                  <span
                    className={`absolute inset-y-0 left-0 ${best.has(h.hour) ? "bg-brand" : "bg-brand/50"}`}
                    style={{ width: `${(h.answered / max) * 100}%` }}
                    aria-hidden
                  />
                </span>
                <span className="w-28 shrink-0 text-right text-ink tabular-nums">
                  {h.answered}/{h.calls} answered
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

function CallUnansweredAgain({ slug, campaignId, canWrite, refusal }: Common) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const duplicate = useDuplicateCampaign(session, campaignId);
  useActionFeedback(duplicate, { errorDisplay: "inline" });
  return (
    <Card
      title="Call the unanswered again"
      hint="A new draft of only the people it never reached."
      info="Same script and settings. You start it when you are ready."
    >
      <button
        type="button"
        className={PRIMARY_BUTTON_SM}
        disabled={!canWrite || duplicate.isPending}
        title={refusal}
        onClick={() =>
          duplicate.mutate(
            { with_unreached: true },
            { onSuccess: (made) => router.push(href(`/c/${slug}/campaigns/${made.id}`)) },
          )
        }
      >
        {duplicate.isPending ? "Making it…" : "Make a draft for the unanswered"}
      </button>
      {duplicate.error != null && (
        <p role="alert" className="mt-2 text-meta text-danger">
          {errorText(duplicate.error, "The draft was not made")}
        </p>
      )}
    </Card>
  );
}

function WhatsAppFollowUp({ slug }: { slug: string }) {
  const { href } = useClientRealm();
  return (
    <Card
      title="Follow up on WhatsApp"
      hint="Send a WhatsApp message after a call."
      info={
        <>
          <p>For example the install steps or a link, to the people who asked for it or did not finish.</p>
          <p>
            Make a follow-up that starts when a call ends, choose this campaign&apos;s agent and the outcomes it is for,
            then add a WhatsApp step.
          </p>
        </>
      }
    >
      <Link href={href(`/c/${slug}/follow-ups`)} className={`${SECONDARY_BUTTON_SM} inline-flex`}>
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
  refusal,
}: Omit<Common, "slug"> & { agentId: string; editable: boolean }) {
  const { session } = useClientRealm();
  const agents = useAgents(session);
  const update = useUpdateCampaign(session, campaignId);
  useActionFeedback(update, { errorDisplay: "inline" });
  const client = useQueryClient();
  const options = (agents.data ?? []).filter(isAssignable);

  const choose = (id: string) => {
    if (id === agentId || !editable || !canWrite) return;
    update.mutate(
      { agent_id: id },
      { onSuccess: () => void client.invalidateQueries({ queryKey: workspaceKey(session.orgSlug, campaignId) }) },
    );
  };

  return (
    <FoldSection
      title="Agent and its settings"
      tone="agent"
     
      hint="Who makes these calls, and its settings here."
    >
    <div className="space-y-4">
      {!agents.data && !agents.error && <Skeleton rows={2} label="Loading your agents" />}
      {agents.error != null && <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />}
      {options.length > 0 && (
        <AgentChoice
          onChange={choose}
          agentOptions={options}
          selectedAgentId={agentId}
          selectedAgent={options.find((agent) => agent.id === agentId)}
          disabled={!canWrite || !editable || update.isPending}
        />
      )}
      {!editable && <p className="text-meta text-ink-muted">The agent can change only while it is a draft.</p>}
      {update.error != null && <ProblemNotice error={update.error} />}
      <CampaignVoiceSettings campaignId={campaignId} agentId={agentId} canWrite={canWrite} refusal={refusal} />
    </div>
    </FoldSection>
  );
}

/** The chosen agent rings the owner's phone with this campaign's script. */
export function TestCallSection(props: Common) {
  return (
    <FoldSection
      title="Test call"
      tone="test"
      hint="The chosen agent rings your phone."
      info="It puts this campaign's script on the agent first, so you hear exactly what people will hear."
    >
      <HearItFirst {...props} />
      <TestCallList {...props} />
    </FoldSection>
  );
}
