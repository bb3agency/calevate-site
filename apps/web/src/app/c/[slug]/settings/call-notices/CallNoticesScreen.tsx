"use client";

import Link from "next/link";
import { TriangleAlert } from "lucide-react";
import { useId, useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import {
  Disclosure,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  ToggleSwitch,
} from "@/components/ui";
import { useAgent, useCallNotices, useSetCallNotices, type DisclosureIn } from "@/lib/api/agents";
import { problemOf } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { Term } from "@/lib/glossary";

import {
  IntroducedOpeningFix,
  NOTICE_NEEDS_ROOM,
  OPENING_INTRODUCES,
  OpeningLineFix,
} from "../../agents/panels/openingLineFix";

/**
 * The server's truthful-answer promise split at its first sentence: the guarantee, shown
 * above the switches, and the rest (the exact answers), shown in full in the disclosure.
 * The words are the server's either way (`compliance/disclosure.truthful_answer_promise`).
 */
export function splitPromise(rule: string): { lead: string; rest: string } {
  const match = /^(.+?[.!?])\s+(\S[\s\S]*)$/.exec(rule.trim());
  return match ? { lead: match[1], rest: match[2] } : { lead: rule.trim(), rest: "" };
}

/**
 * THE CALL NOTICES — one AI switch and one recording switch for every call (D-1021).
 *
 * Founder, 19 Nov 2026: every call made from or to the client's numbers, inbound and
 * outbound, has a single AI switch and a single recording switch; the words follow the
 * call's direction. So the switches are the account's, set here, and each agent's page only
 * shows them. Two switches, not one: "this is an AI" and "this call is recorded" are
 * separate obligations under separate regimes (D-163).
 *
 * `org:manage` is the owner's; an operator in "view as client" can flip them too (D-587),
 * and every flip is audited. With a switch on, each opening says the notice in its own words
 * (D-971), so no sentence is quoted. "Off" never makes the agent lie: the server's
 * truthful-answer promise is drawn above the switches in its own words.
 *
 * A refusal names the one agent, Inbound line or campaign whose opening cannot take the
 * notice, with a button to it, so the owner has one thing to fix rather than a paragraph to
 * read.
 */
export function CallNoticesScreen() {
  const { session, href } = useClientRealm();
  const notices = useCallNotices(session);
  const save = useSetCallNotices(session);
  const feedback = useActionFeedback(save, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "change the call notices");
  const locked = save.isPending || !write.allowed;
  // The switch last turned on, so a refusal naming an agent can be fixed in place and the
  // same switch turned on again once that agent's opening line is changed.
  const [lastOn, setLastOn] = useState<DisclosureIn | null>(null);
  const flip = (payload: DisclosureIn, next: boolean) => {
    setLastOn(next ? payload : null);
    save.mutate(payload);
  };
  const roomRefusal = problemOf<"NoticeNeedsRoomOnAgent">(save.error, NOTICE_NEEDS_ROOM);
  const introRefusal = problemOf<"OpeningIntroducesOnAgent">(save.error, OPENING_INTRODUCES);
  const blocked = roomRefusal ?? introRefusal;
  const agentId = typeof blocked?.agent_id === "string" ? blocked.agent_id : "";
  const agentName = typeof blocked?.agent_name === "string" ? blocked.agent_name : "";
  // A line's or a campaign's own opening has no room: that line or campaign is the one to fix.
  const holder = holderOf(roomRefusal, session.orgSlug);

  return (
    <div className="max-w-2xl space-y-6 pb-12">
      <PageHeader description="What every call says first, answered or placed." />
      <RestrictionNote reason={write.reason} />
      <Section
        title="Call notices"
        description="One setting for all your agents, lines and campaigns."
      >
        {notices.error ? (
          <ProblemNotice error={notices.error} onRetry={() => void notices.refetch()} />
        ) : !notices.data ? (
          <Skeleton rows={2} label="Checking your call notices" />
        ) : (
          <>
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              {/* Above the switches, so two "off" positions are never read as "it may pass
                  for human". Quiet on purpose: a guarantee, not an alert. */}
              <p className="text-meta text-ink-muted">
                {splitPromise(notices.data.truthful_answer_rule).lead}
              </p>
              <p role="status" className="text-meta text-ink-muted">
                {feedback.status === "pending"
                  ? "Saving…"
                  : feedback.status === "success"
                    ? "Saved. The next call uses this."
                    : ""}
              </p>
            </div>
            {save.error != null && holder ? (
              <div className="mt-3 space-y-2">
                <ProblemNotice error={save.error} />
                <Link href={href(holder.path)} className={`inline-flex ${SECONDARY_BUTTON_SM}`}>
                  {holder.name ? `Open ${holder.name}` : holder.fallback}
                </Link>
              </div>
            ) : save.error != null && agentId && lastOn ? (
              <BlockedAgent
                agentId={agentId}
                agentName={agentName}
                needsRoom={roomRefusal !== undefined}
                turnedOn={lastOn}
                error={save.error}
                retrying={save.isPending}
                retry={() => save.mutate(lastOn)}
                agentHref={href(`/c/${session.orgSlug}/agents/${agentId}`)}
              />
            ) : (
              save.error != null && (
                <div className="mt-3">
                  <ProblemNotice error={save.error} />
                </div>
              )
            )}
            <div className="mt-3 divide-y divide-line border-y border-line">
              <NoticeToggle
                label="Say it is an AI assistant"
                checked={notices.data.ai_disclosure_enabled}
                pending={locked}
                onLine="Every call says so when it starts."
                offLine="Calls won't bring it up, but always say so if asked."
                onChange={(next) => flip({ ai_disclosure_enabled: next }, next)}
              />
              <NoticeToggle
                label="Say the call is being recorded"
                checked={notices.data.recording_notice_enabled}
                pending={locked}
                onLine={
                  notices.data.calls_recorded
                    ? "Every call says so when it starts."
                    : "Calls are not recorded now, so nothing is said."
                }
                offLine="Calls are still recorded. Tell callers another way."
                offIsWarning={notices.data.calls_recorded}
                onChange={(next) => flip({ recording_notice_enabled: next }, next)}
              />
            </div>
            <Disclosure variant="inline" headingLevel={3} title="How these work" className="mt-2">
              {/* The reasoning, behind a tap; never a control. */}
              <div className="space-y-2 pb-3 text-sm text-ink-muted">
                {splitPromise(notices.data.truthful_answer_rule).rest && (
                  <p>{splitPromise(notices.data.truthful_answer_rule).rest}</p>
                )}
                <p>
                  Each call says a notice that is on in its opening, in its own words: a call
                  your agent answers and a call it makes each say it their own way. When you
                  switch one, Pip rewrites the openings. Until then a short set sentence is said
                  with the opening, so no call goes out without it.
                </p>
                <p>
                  Calls are still recorded — the recording switch only stops the announcement.
                  Telling callers is still your duty under the{" "}
                  <Term id="dpdp" term="DPDP Act" />; with this off, your own privacy notice has
                  to cover it.
                </p>
                <p>Changes take effect on the next call.</p>
              </div>
            </Disclosure>
          </>
        )}
      </Section>
    </div>
  );
}

/**
 * The Inbound line or campaign a room refusal names, with the page to open it on; undefined
 * when the refusal names an agent's own opening.
 */
export function holderOf(
  refusal: { [member: string]: unknown } | undefined,
  slug: string,
): { path: string; name: string; fallback: string } | undefined {
  const text = (member: string) => (typeof refusal?.[member] === "string" ? (refusal[member] as string) : "");
  if (text("line_id")) {
    return {
      path: `/c/${slug}/inbound/${text("line_id")}`,
      name: text("line_name"),
      fallback: "Open the line",
    };
  }
  if (text("campaign_id")) {
    return {
      path: `/c/${slug}/campaigns/${text("campaign_id")}`,
      name: text("campaign_name"),
      fallback: "Open the campaign",
    };
  }
  return undefined;
}

/**
 * A switch refused because one agent's opening line cannot take the notice: that agent's
 * opening line, fixed in place with the agent's own fix (`openingLineFix`), which saves the
 * line and turns the switch on again; and a button to the agent for anything more.
 */
function BlockedAgent({
  agentId,
  agentName,
  needsRoom,
  turnedOn,
  error,
  retrying,
  retry,
  agentHref,
}: {
  agentId: string;
  agentName: string;
  needsRoom: boolean;
  turnedOn: DisclosureIn;
  error: unknown;
  retrying: boolean;
  retry: () => void;
  agentHref: string;
}) {
  const { session } = useClientRealm();
  const agent = useAgent(session, agentId);
  const budget = agent.data?.greeting_budget;
  const room = budget
    ? turnedOn.ai_disclosure_enabled
      ? budget.opening_room_with_ai_disclosure
      : budget.opening_room_with_recording_notice
    : undefined;
  return (
    <div className="mt-3 space-y-2">
      {!agent.data ? (
        <ProblemNotice error={error} />
      ) : needsRoom && room !== undefined ? (
        <OpeningLineFix agent={agent.data} error={error} room={room} retry={retry} retrying={retrying} />
      ) : (
        <IntroducedOpeningFix agent={agent.data} error={error} retry={retry} retrying={retrying} />
      )}
      <Link href={agentHref} className={`inline-flex ${SECONDARY_BUTTON_SM}`}>
        {agentName ? `Open ${agentName}` : "Open the agent"}
      </Link>
    </div>
  );
}

/**
 * One notice, as a switch and one line saying what its current position does.
 *
 * `pending` disables BOTH switches while either is in flight: the two write one row, and a
 * second click before the first response would race it.
 */
function NoticeToggle({
  label,
  checked,
  pending,
  onLine,
  offLine,
  offIsWarning = false,
  onChange,
}: {
  label: string;
  checked: boolean;
  pending: boolean;
  onLine: string;
  offLine: string;
  /** Off leaves a duty the owner must meet elsewhere, so the off line is a warning. */
  offIsWarning?: boolean;
  onChange: (next: boolean) => void;
}) {
  const lineId = useId();
  const warn = !checked && offIsWarning;
  return (
    <ToggleSwitch
      label={label}
      checked={checked}
      disabled={pending}
      onChange={onChange}
      describedBy={lineId}
      className="py-3"
    >
      {/* `pl-12`: the switch (w-9) and its gap (gap-3), so the line sits under the label. */}
      <p
        id={lineId}
        data-notice={warn ? "warn" : undefined}
        className={`mt-0.5 flex items-start gap-1.5 pl-12 text-meta ${warn ? "text-ink" : "text-ink-muted"}`}
      >
        {warn && <TriangleAlert aria-hidden className="mt-[3px] h-3.5 w-3.5 shrink-0 text-warn" />}
        <span>{checked ? onLine : offLine}</span>
      </p>
    </ToggleSwitch>
  );
}
