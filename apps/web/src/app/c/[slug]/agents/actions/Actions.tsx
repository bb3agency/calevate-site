"use client";

/**
 * WHAT AN AGENT CAN DO ON A CALL — the agent's Actions section, as a guided flow
 * (REDESIGN-2): pick a job → connect an account if it needs one → two or three plain
 * settings → turn it on, with a safe "Try it" for booking.
 *
 * This file is the ORCHESTRATION only: which reads happen, what the master switch does,
 * and which view is showing — the list of what is on, or one job being set up. The
 * children are one subject each: `BookingSetup`/`BookingJob` (the two calendar tools
 * behind "Book appointments"), `ActionForm` (every other job), `ToolRow`, `AccountRow`, and
 * the React-free vocabulary in `jobs.ts` and `params.ts`. Accounts are connected for the
 * whole business (D-700); a job can connect a sign-in account in place.
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
import { Section, TEXT_ACTION } from "@/components/console/section";
import { ProblemNotice, RestrictionNote, Skeleton, ToggleSwitch } from "@/components/ui";
import { useAgentActions, useSetMasterSwitch } from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";

import { ActionForm } from "./ActionForm";
import { BookingJob } from "./BookingJob";
import { BookingSetup } from "./BookingSetup";
import { JOBS, bookingParts, type JobId } from "./jobs";
import { ToolRow } from "./ToolRow";

const ICONS: Record<JobId, typeof CalendarCheck> = {
  booking: CalendarCheck,
  caller_lookup: UserSearch,
  whatsapp: MessageCircle,
  payment_link: CreditCard,
  crm: Database,
  sheets: Sheet,
  custom_api: Code2,
};

type View = { at: "list" } | { at: "setup"; job: JobId } | { at: "change-booking" };

export function Actions({ agentId, session }: { agentId: string; session: Session }) {
  const actions = useAgentActions(session, agentId);
  const setMaster = useSetMasterSwitch(session, agentId);
  const [view, setView] = useState<View>({ at: "list" });
  // Reading actions and credentials is `org:read`; every write here — the master switch,
  // a tool, a credential, a test run — is `org:manage`, which staff do not hold.
  const write = useWriteAccess(session, "org:manage", "change what this agent can do mid-call");

  if (actions.isPending) return <Skeleton rows={4} label="Loading actions…" />;
  if (actions.isError)
    return <ProblemNotice error={actions.error} onRetry={() => void actions.refetch()} />;

  const settings = actions.data;
  const { check, book } = bookingParts(settings.tools);
  const hasBooking = check !== undefined || book !== undefined;
  const others = settings.tools.filter((t) => t.kind !== "calendar");
  const back = () => setView({ at: "list" });
  const switchOn = () => {
    if (!settings.api_actions_enabled) setMaster.mutate(true);
  };

  if (view.at !== "list") {
    return (
      <fieldset disabled={!write.allowed} className="min-w-0 max-w-2xl">
        <button type="button" className={`${TEXT_ACTION} mb-4`} onClick={back}>
          ← All actions
        </button>
        {view.at === "change-booking" || (view.at === "setup" && view.job === "booking") ? (
          <BookingSetup
            agentId={agentId}
            session={session}
            tools={settings.tools}
            masterOn={settings.api_actions_enabled}
            check={check}
            book={book}
            onDone={back}
          />
        ) : (
          <ActionForm
            kind={JOBS.find((j) => j.id === view.job)?.kind ?? "custom_api"}
            agentId={agentId}
            session={session}
            takenNames={settings.tools.map((t) => t.name)}
            onSaved={switchOn}
            onDone={back}
          />
        )}
        {setMaster.isError ? <ProblemNotice error={setMaster.error} /> : null}
      </fieldset>
    );
  }

  const offered = JOBS.filter((j) => j.id !== "booking" || !hasBooking);

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

        {hasBooking ? (
          <BookingJob
            agentId={agentId}
            session={session}
            check={check}
            book={book}
            onChange={() => setView({ at: "change-booking" })}
          />
        ) : null}

        {others.length > 0 ? (
          <Section headingLevel={3} title={hasBooking ? "Other actions" : "What it does now"}>
            <ul className="divide-y divide-line border-y border-line">
              {others.map((tool) => (
                <ToolRow key={tool.id} tool={tool} agentId={agentId} session={session} />
              ))}
            </ul>
          </Section>
        ) : null}

        <Section
          headingLevel={3}
          title={settings.tools.length === 0 ? "What should your agent do on calls?" : "Add something else"}
          description={settings.tools.length === 0 ? "Pick one. You can add more later." : undefined}
        >
          <Chooser label="Things your agent can do">
            {offered.map((job) => {
              const Icon = ICONS[job.id];
              const unavailable = job.id === "booking" && !settings.calendar_available;
              return (
                <ChooserItem
                  key={job.id}
                  title={job.title}
                  description={
                    unavailable
                      ? "Google Calendar is not available on your account yet — ask your Calevate team."
                      : job.line
                  }
                  icon={<Icon className="h-5 w-5" />}
                  disabled={unavailable}
                  onSelect={() => setView({ at: "setup", job: job.id })}
                />
              );
            })}
          </Chooser>
        </Section>
      </fieldset>
    </div>
  );
}
