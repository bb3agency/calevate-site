"use client";

/**
 * WHAT AN AGENT CAN DO ON A CALL — the agent's Actions section (REDESIGN-2).
 *
 * The overview is three parts and every action is a peer in them (founder, 10 Oct 2026):
 * the one switch for actions on calls; "On this agent", one row per job that is set up
 * (booking is one row, though two calendar tools sit behind it); and "Add an action", the
 * catalogue of jobs not yet set up, in the same row style. Opening any of them goes to that
 * job's own view inside the section, under "← All actions", with the same header.
 *
 * This file is the ORCHESTRATION only: which reads happen, what the master switch does, and
 * which view is showing. The views are `BookingJob` / `BookingSetup` (the booking job),
 * `ToolDetail` / `ActionForm` (every other job), drawn with `ActionRow` / `ActionHeader`;
 * the vocabulary is in `jobs.ts`. Accounts are connected for the whole business (D-700).
 */

import { useState } from "react";
import {
  CalendarCheck,
  Code2,
  CreditCard,
  Database,
  MessageCircle,
  Sheet,
  UserSearch,
} from "lucide-react";

import { Chooser, ChooserItem } from "@/components/console/chooser";
import { EmptyState } from "@/components/console/emptyState";
import { EmptySketch } from "@/components/console/emptySketch";
import { IconTile } from "@/components/console/iconTile";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { ProblemNotice, RestrictionNote, Skeleton, ToggleSwitch } from "@/components/ui";
import {
  useAgentActions,
  useCredentials,
  useSetActionEnabled,
  useSetMasterSwitch,
  type ActionTool,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import { useVerticalExamples } from "@/lib/useVerticalExamples";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { ActionForm } from "./ActionForm";
import { ActionHeader, ActionRow } from "./ActionRow";
import { BookingJob } from "./BookingJob";
import { BookingSetup } from "./BookingSetup";
import { ToolDetail } from "./ToolDetail";
import {
  BOOKING_JOB,
  JOBS,
  bookingParts,
  daysLabel,
  hourLabel,
  jobFor,
  jobLine,
  jobLogo,
  jobTitle,
  keptHours,
  readBooking,
  toolLogo,
  toolProblem,
  toolSummary,
  toolTitle,
  REPEATABLE_JOBS,
  type Job,
  type JobId,
} from "./jobs";

const ICONS: Record<JobId, typeof CalendarCheck> = {
  booking: CalendarCheck,
  caller_lookup: UserSearch,
  whatsapp: MessageCircle,
  payment_link: CreditCard,
  crm: Database,
  sheets: Sheet,
  custom_api: Code2,
};

type View =
  | { at: "list" }
  | { at: "booking" }
  | { at: "change-booking" }
  | { at: "tool"; toolId: string }
  | { at: "setup"; job: JobId };

/** The job a set-up tool belongs to; a kind this build does not know reads as a custom API. */
function jobOf(tool: ActionTool): Job {
  return jobFor(tool.kind) ?? JOBS.find((j) => j.id === "custom_api")!;
}

export function Actions({ agentId, session }: { agentId: string; session: Session }) {
  const actions = useAgentActions(session, agentId);
  const creds = useCredentials(session);
  const setMaster = useSetMasterSwitch(session, agentId);
  const setEnabled = useSetActionEnabled(session, agentId);
  const [requested, setView] = useState<View>({ at: "list" });
  const eg = useVerticalExamples();
  // Reading actions and credentials is `org:read`; every write here — the master switch,
  // a tool, a credential, a test run — is `org:manage`, which staff do not hold.
  const write = useWriteAccess(session, "org:manage", "change what this agent can do mid-call");

  // THIS SECTION, DECLARED TO THE ASSISTANT. Before the loading/failure branches, because a
  // hook cannot be conditional. Facts only: the overview's controls are switches the
  // assistant should not flip by "filling"; the setup forms declare their own fields.
  const data = actions.data;
  useCopilotSurface({
    route: "/c/{slug}/agents/{id}",
    title: "Agent: what it can do on a call",
    realm: "client",
    fields: [],
    facts: [
      { key: "agent_id", label: "Agent id", value: agentId },
      {
        key: "state",
        label: "What is on screen",
        value: data ? "the agent's actions have loaded" : actions.error ? "the actions failed to load" : "still loading",
      },
      ...(data
        ? [
            { key: "actions_on", label: "Actions switched on for this agent", value: data.api_actions_enabled ? "yes" : "no" },
            {
              key: "set_up",
              label: "Actions set up on this agent",
              value:
                [
                  ...(bookingParts(data.tools).check || bookingParts(data.tools).book ? [jobTitle(BOOKING_JOB, eg)] : []),
                  ...data.tools
                    .filter((t) => t.kind !== "calendar")
                    .map((t) => `${toolTitle(t)} (${t.enabled ? "on" : "off"}${toolProblem(t, creds.data) ? `, ${toolProblem(t, creds.data)}` : ""})`),
                ].join("; ") || "none",
            },
          ]
        : []),
    ],
    apply: noFill,
  });

  if (actions.isPending) return <Skeleton rows={4} label="Loading actions…" />;
  if (actions.isError)
    return <ProblemNotice error={actions.error} onRetry={() => void actions.refetch()} />;

  const settings = actions.data;
  const { check, book } = bookingParts(settings.tools);
  const hasBooking = check !== undefined || book !== undefined;
  const others = settings.tools.filter((t) => t.kind !== "calendar");
  const back = () => setView({ at: "list" });
  // A tool removed (here or in another tab) while its view was open falls back to the overview.
  const view: View =
    requested.at === "tool" && !settings.tools.some((t) => t.id === requested.toolId)
      ? { at: "list" }
      : requested;
  const switchOn = () => {
    if (!settings.api_actions_enabled) setMaster.mutate(true);
  };

  if (view.at !== "list") {
    const tool = view.at === "tool" ? settings.tools.find((t) => t.id === view.toolId) : undefined;
    const job =
      view.at === "tool" && tool
        ? jobOf(tool)
        : view.at === "setup"
          ? (JOBS.find((j) => j.id === view.job) ?? BOOKING_JOB)
          : BOOKING_JOB;
    const toBooking = view.at === "change-booking" && hasBooking;
    return (
      <fieldset disabled={!write.allowed} className="min-w-0 max-w-2xl space-y-8">
        <button
          type="button"
          className={TEXT_ACTION}
          onClick={() => (toBooking ? setView({ at: "booking" }) : back())}
        >
          {toBooking ? `← ${jobTitle(BOOKING_JOB, eg)}` : "← All actions"}
        </button>
        <ActionHeader
          title={tool ? toolTitle(tool) : jobTitle(job, eg)}
          line={jobLine(job, eg)}
          logo={tool ? toolLogo(tool) : jobLogo(job)}
          icon={ICONS[job.id]}
        />
        {view.at === "booking" ? (
          <BookingJob
            agentId={agentId}
            session={session}
            check={check}
            book={book}
            onChange={() => setView({ at: "change-booking" })}
          />
        ) : view.at === "change-booking" || (view.at === "setup" && view.job === "booking") ? (
          <BookingSetup
            agentId={agentId}
            session={session}
            tools={settings.tools}
            masterOn={settings.api_actions_enabled}
            check={check}
            book={book}
            onDone={() => setView(hasBooking ? { at: "booking" } : { at: "list" })}
          />
        ) : view.at === "tool" && tool ? (
          <ToolDetail
            tool={tool}
            agentId={agentId}
            session={session}
            takenNames={settings.tools.map((t) => t.name)}
            onRemoved={back}
            onAddAnother={() => setView({ at: "setup", job: jobOf(tool).id })}
          />
        ) : view.at === "setup" ? (
          <ActionForm
            kind={job.kind}
            agentId={agentId}
            session={session}
            takenNames={settings.tools.map((t) => t.name)}
            onSaved={switchOn}
            onDone={back}
          />
        ) : null}
        {setMaster.isError ? <ProblemNotice error={setMaster.error} /> : null}
      </fieldset>
    );
  }

  // Booking is one row though two tools sit behind it: on only when both halves are.
  const bookingOn = check !== undefined && book !== undefined && check.enabled && book.enabled;
  const bookingSettings = readBooking(check, book);
  const kept = keptHours(check, book);
  const bookingAccount = creds.data?.find((c) => c.id === bookingSettings.credentialId);
  const bookingProblem =
    check === undefined || book === undefined
      ? "Not finished"
      : !bookingAccount && creds.data !== undefined
        ? "Not connected"
        : null;
  const bookingSummary = [
    bookingAccount ? `Google · ${bookingAccount.label}` : null,
    kept ? `${hourLabel(kept.from)} – ${hourLabel(kept.to)}` : "Any time",
    daysLabel(bookingSettings.days),
  ]
    .filter(Boolean)
    .join(" · ");

  const setUpKinds = new Set(others.map((t) => t.kind));
  const catalogue = JOBS.filter((j) =>
    j.id === "booking" ? !hasBooking : REPEATABLE_JOBS.includes(j.id) || !setUpKinds.has(j.kind),
  );

  return (
    <div className="max-w-2xl space-y-10">
      <p className="max-w-prose text-body text-ink-muted">
        Your agent can book, look up and send things while it talks. Changes reach live calls
        straight away.
      </p>

      <RestrictionNote reason={write.reason} />

      {/* A disabled <fieldset> disables every control inside it natively, including the
          ones the child components own, so no write can be reached without the grant. */}
      <fieldset disabled={!write.allowed} className="min-w-0 space-y-10">
        <div>
          <ToggleSwitch
            label="Use actions on calls"
            hint="One switch for every action on this agent."
            checked={settings.api_actions_enabled}
            disabled={setMaster.isPending}
            onChange={(next) => setMaster.mutate(next)}
          />
          {setMaster.isError ? <ProblemNotice error={setMaster.error} /> : null}
        </div>

        <Section headingLevel={3} title="On this agent">
          {hasBooking || others.length > 0 ? (
            <ul className="divide-y divide-line border-y border-line">
              {hasBooking ? (
                <ActionRow
                  title={jobTitle(BOOKING_JOB, eg)}
                  summary={bookingSummary}
                  logo="google_calendar"
                  icon={CalendarCheck}
                  problem={bookingProblem}
                  enabled={bookingOn}
                  switchDisabled={setEnabled.isPending || check === undefined || book === undefined}
                  onToggle={(next) => {
                    for (const t of [check, book]) if (t) setEnabled.mutate({ toolId: t.id, enabled: next });
                  }}
                  onOpen={() => setView({ at: "booking" })}
                />
              ) : null}
              {others.map((tool) => {
                const job = jobOf(tool);
                return (
                  <ActionRow
                    key={tool.id}
                    title={toolTitle(tool)}
                    summary={toolSummary(tool)}
                    logo={toolLogo(tool)}
                    icon={ICONS[job.id]}
                    problem={toolProblem(tool, creds.data)}
                    enabled={tool.enabled}
                    switchDisabled={setEnabled.isPending}
                    onToggle={(next) => setEnabled.mutate({ toolId: tool.id, enabled: next })}
                    onOpen={() => setView({ at: "tool", toolId: tool.id })}
                  />
                );
              })}
            </ul>
          ) : (
            <EmptyState
              align="start"
              illustration={<EmptySketch kind="actions" />}
              message="Nothing is set up on this agent yet."
              hint="Pick something for it to do from the list below."
            />
          )}
          {setEnabled.error ? <ProblemNotice error={setEnabled.error} /> : null}
        </Section>

        {catalogue.length > 0 ? (
          <Section headingLevel={3} title="Add an action">
            <Chooser label="Things your agent can do">
              {catalogue.map((job) => {
                const unavailable = job.id === "booking" && !settings.calendar_available;
                return (
                  <ChooserItem
                    key={job.id}
                    title={jobTitle(job, eg)}
                    description={
                      unavailable
                        ? "Google Calendar is not available on your account yet — ask your Calevate team."
                        : jobLine(job, eg)
                    }
                    icon={<IconTile service={jobLogo(job)} icon={ICONS[job.id]} />}
                    disabled={unavailable}
                    onSelect={() => setView({ at: "setup", job: job.id })}
                  />
                );
              })}
            </Chooser>
          </Section>
        ) : null}
      </fieldset>
    </div>
  );
}

