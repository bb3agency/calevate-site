"use client";

import Link from "next/link";
import { useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { PageHeader } from "@/components/console/pageHeader";
import { StatusPill } from "@/components/console/statusPill";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { Tabs } from "@/components/interior/tabs";
import {
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useFollowUp, useMoveFollowUp, type FollowUpOut } from "@/lib/api/followUps";
import { useMe, useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { lookup } from "@/lib/lookup";

import { STATUS_TONES, STATUS_WORDS, triggerWords } from "../followUpCopy";
import { isFollowUpConflict, useConflictToast } from "./conflict";
import { PublishPanel } from "./PublishPanel";
import { ResultsTab } from "./ResultsTab";
import { RunsTab } from "./RunsTab";
import { StepsTab, focusStep } from "./StepsTab";

const TABS = [
  { value: "steps", label: "Steps" },
  { value: "runs", label: "Leads" },
  { value: "results", label: "Results" },
];

/**
 * ONE FOLLOW-UP (D-940).
 *
 * PRIMARY JOB: see what happens to a lead, step by step, and make a small change to it.
 *
 * - Small edits go to the draft (founder decision 4); "Publish" is the one large button
 *   and appears only when the draft differs from what runs. Its problems are buttons that
 *   open the step they are about.
 * - Anything bigger is "Ask Pip to change it", which prefills and never sends.
 * - Steps / Leads / Results are peer views of one Follow-up (D-655): each is complete
 *   on its own and a reader picks one.
 */
export function FollowUpScreen({ followUpId }: { followUpId: string }) {
  const { session, href } = useClientRealm();
  const slug = session.orgSlug;
  const me = useMe(session);
  const query = useFollowUp(session, followUpId);
  const write = useWriteAccess(session, "leads:dispatch", "change this Follow-up");
  const [tab, setTab] = useState("steps");
  const data = query.data;

  useCopilotSurface(
    data
      ? {
          route: `/c/${slug}/follow-ups/${followUpId}`,
          title: data.name,
          realm: "client",
          fields: [],
          facts: [
            { key: "status", label: "Status", value: lookup(STATUS_WORDS, data.status) ?? data.status },
            { key: "starts", label: "What starts it", value: triggerWords(data.trigger) },
            { key: "steps", label: "Steps", value: data.steps.map((step) => step.summary).join(" → ") },
            {
              key: "unpublished",
              label: "Changes not published",
              value: data.has_unpublished_changes ? "yes" : "no",
            },
          ],
          apply: () => {},
        }
      : null,
  );

  const refused = me.data !== undefined && !me.data.permissions.includes("leads:read");
  if (refused) {
    return <RestrictionNote reason="Only people who can see leads can see Follow-ups." />;
  }

  const back = { href: href(`/c/${slug}/follow-ups`), label: "All Follow-ups" };
  if (query.isLoading) {
    return (
      <div className="max-w-4xl space-y-6 pb-12">
        <PageHeader back={back} />
        <Skeleton rows={6} label="Loading this Follow-up" />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="max-w-4xl space-y-6 pb-12">
        <PageHeader back={back} />
        <ProblemNotice error={query.error} onRetry={() => void query.refetch()} />
      </div>
    );
  }

  const openStep = (stepId: string) => {
    setTab("steps");
    // After the Steps panel has rendered.
    window.requestAnimationFrame(() => focusStep(stepId));
  };

  return (
    <div className="max-w-4xl space-y-6 pb-12">
      <PageHeader
        back={back}
        headingLevel={1}
        title={data.name}
        status={
          <StatusPill tone={lookup(STATUS_TONES, data.status) ?? "neutral"}>
            {lookup(STATUS_WORDS, data.status) ?? data.status}
          </StatusPill>
        }
        description={`Starts when: ${triggerWords(data.trigger)}`}
        meta={
          data.live_version ? (
            <span className="text-meta text-ink-muted">Published {formatIST(data.live_version.published_at)}</span>
          ) : undefined
        }
        actions={write.allowed ? <StatusActions followUp={data} /> : undefined}
      />

      <RestrictionNote reason={write.reason} />

      {write.allowed && (data.has_unpublished_changes || data.status === "draft") && (
        <PublishPanel followUp={data} onOpenStep={openStep} />
      )}

      {write.allowed && (
        <div className="flex flex-wrap items-center gap-2">
          <AskAssistant
            label={`Ask ${ASSISTANT_NAME} to change it`}
            prompt={`Change my Follow-up “${data.name}”: `}
          />
          {data.trigger.kind === "manual" && data.status === "live" && (
            <Link
              href={href(`/c/${slug}/leads?follow_up=${data.id}`)}
              className={SECONDARY_BUTTON_SM}
            >
              Start for leads
            </Link>
          )}
        </div>
      )}

      <Tabs
        label="This Follow-up"
        items={TABS}
        value={tab}
        onValueChange={setTab}
        panelClassName="pt-5"
        renderPanel={(value) =>
          value === "runs" ? (
            <RunsTab followUp={data} canStop={write.allowed} />
          ) : value === "results" ? (
            <ResultsTab followUp={data} />
          ) : (
            <StepsTab followUp={data} canEdit={write.allowed} />
          )
        }
      />
    </div>
  );
}

/** Pause, resume and turn off. Turning off stops every lead in it, so it is confirmed. */
function StatusActions({ followUp }: { followUp: FollowUpOut }) {
  const { session } = useClientRealm();
  const move = useMoveFollowUp(session, followUp.id);
  const conflict = useConflictToast();
  const feedback = useActionFeedback(move, {
    errorDisplay: "inline",
    successToast: (_data, vars) =>
      vars.move === "pause" ? "Paused" : vars.move === "resume" ? "Turned on" : vars.move === "turn-off" ? "Turned off" : null,
  });
  const [confirmOff, setConfirmOff] = useState(false);
  const pending = feedback.status === "pending";
  const run = (which: "pause" | "resume") =>
    move.mutate({ move: which }, { onError: (error) => conflict(error) });

  return (
    <div className="flex flex-wrap gap-2">
      {followUp.status === "live" && (
        <button type="button" className={SECONDARY_BUTTON_SM} disabled={pending} onClick={() => run("pause")}>
          Pause
        </button>
      )}
      {(followUp.status === "paused" || followUp.status === "off") && followUp.live_version && (
        <button type="button" className={SECONDARY_BUTTON_SM} disabled={pending} onClick={() => run("resume")}>
          {followUp.status === "paused" ? "Resume" : "Turn back on"}
        </button>
      )}
      {(followUp.status === "live" || followUp.status === "paused") && (
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={pending}
          onClick={() => {
            move.reset();
            setConfirmOff(true);
          }}
        >
          Turn off
        </button>
      )}
      {move.error && !confirmOff && !isFollowUpConflict(move.error) ? <ProblemNotice error={move.error} /> : null}

      {confirmOff && (
        <ConfirmDialog
          title={`Turn off “${followUp.name}”?`}
          confirmLabel="Turn it off"
          pendingLabel="Turning off…"
          cancelLabel="Keep it on"
          status={feedback.status}
          error={move.error}
          onCancel={() => {
            move.reset();
            setConfirmOff(false);
          }}
          onConfirm={() =>
            move.mutate(
              { move: "turn-off" },
              {
                onSuccess: () => setConfirmOff(false),
                onError: (error) => {
                  if (conflict(error)) setConfirmOff(false);
                },
              },
            )
          }
        >
          <p>
            <strong className="font-semibold text-ink">Every lead in it now stops.</strong>
          </p>
          <p>
            {followUp.starter === "call_new_leads"
              ? "New leads are still saved, but nobody calls them."
              : "No new lead starts it."}
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
