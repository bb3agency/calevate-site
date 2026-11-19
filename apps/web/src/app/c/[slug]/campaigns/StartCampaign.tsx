"use client";

/**
 * START CAMPAIGN, at the top and the bottom of the set-up and on Progress (founder, 15-16 Nov
 * 2026). A campaign starts and stops any time: Start resumes a stopped (paused) one, and
 * launches a draft or a campaign stopped before Stop became a pause, through the same gate.
 *
 * Every press asks first (founder, 16 Nov 2026: "ask the user again, if he is sure"). The box
 * says who will be called; when something stands in the way it lists each thing instead,
 * holds the start, and outlines the sections that need fixing. A refusal from the server
 * (its compliance gate runs again on every start, hard rule 5) shows in the same box.
 */

import { PhoneOutgoing } from "lucide-react";
import { useEffect, useState } from "react";

import { type ActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { PRIMARY_BUTTON_SM, formatCount } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import type { useCampaignProgress, useLaunchCheck } from "@/lib/api/campaigns";

import { blockerNote } from "./blockerCopy";
import { peopleSectionId } from "./DraftPeople";
import { SlotsFullProblem, isSlotsFull } from "./SlotHolders";

/** A pause whose cause must be cleared first; the notice above the page says how. */
const HELD_PAUSES = ["complaint_spike", "out_of_credit", "spend_cap"];

/** The compliance card's element id, so Start can take the owner to what is left. */
export function complianceCardId(campaignId: string): string {
  return `compliance-${campaignId}`;
}

export function agentSectionId(campaignId: string): string {
  return `agent-${campaignId}`;
}

/** The set-up section a launch rule is fixed in. */
function sectionFor(rule: string, campaignId: string): string {
  if (rule === "no_contacts" || rule === "all_contacts_dnc") return peopleSectionId(campaignId);
  if (rule.startsWith("agent_") || rule === "disclosure_missing") return agentSectionId(campaignId);
  if (rule.startsWith("script_") || rule === "truthful_answer_drift") return "campaign-script";
  return complianceCardId(campaignId);
}

/** Outlines the sections that need attention, scrolls to the first, and clears the outline
 * after a while so the page does not stay shouting once the owner is there. */
function highlight(ids: string[]): void {
  const found = [...new Set(ids)].map((id) => document.getElementById(id)).filter((el): el is HTMLElement => el != null);
  for (const el of found) {
    el.style.outline = "3px solid var(--danger, #b91c1c)";
    el.style.outlineOffset = "6px";
    el.style.borderRadius = "16px";
    window.setTimeout(() => {
      el.style.outline = "";
      el.style.outlineOffset = "";
    }, 12_000);
  }
  found[0]?.scrollIntoView?.({ block: "start", behavior: "smooth" });
}

type Problem = { rule: string; text: string };

export function StartCampaign({
  slug,
  campaignId,
  status,
  check,
  progress,
  launch,
  resume,
  canWrite,
  refusal,
}: {
  slug: string;
  campaignId: string;
  status: string | null;
  check: ReturnType<typeof useLaunchCheck>;
  progress: ReturnType<typeof useCampaignProgress>;
  launch: ActionFeedback<void>;
  /** Resumes a stopped (paused) campaign. */
  resume: ActionFeedback<"pause" | "resume">;
  canWrite: boolean;
  refusal: string | undefined;
}) {
  const [asking, setAsking] = useState(false);
  const data = progress.data;
  const resuming = status === "paused";
  // A paused campaign, or one stopped before Stop became a pause, picks up where it stopped.
  const carryOn = resuming || status === "cancelled" || status === "completed";
  const action = resuming ? resume : launch;

  // The server's own refusal, rule by rule, when the start was refused after all.
  const refused: Problem[] =
    action.error instanceof ApiProblem && action.error.fields?.length
      ? action.error.fields.map((f) => ({ rule: f.rule, text: blockerNote(f.rule, { promotionalOpen: null })?.text ?? f.message }))
      : [];
  // No free calling setup: name what holds each one, with a way to free it, as the line and
  // test-call screens do, rather than the refusal's sentence alone.
  const slotsFull = isSlotsFull(action.error);
  useEffect(() => {
    if (refused.length > 0) highlight(refused.map((p) => sectionFor(p.rule, campaignId)));
    // Once per refusal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [action.error]);

  // Closes on success; a failure stays in the box, where it is read.
  useEffect(() => {
    if (asking && action.status === "success") setAsking(false);
  }, [asking, action.status]);

  if (status === "running") {
    const why = "It is calling now. Use Stop campaign to stop it.";
    return (
      <button type="button" className={PRIMARY_BUTTON_SM} disabled title={why} aria-label={`Start campaign: ${why}`}>
        <PhoneOutgoing aria-hidden className="h-3.5 w-3.5" />
        Start campaign
      </button>
    );
  }

  // What stands in the way, before the press: the launch check, or the cause of a held pause.
  const problems: Problem[] = [];
  if (resuming) {
    if (data?.complaint_review_required === true) problems.push({ rule: "complaint_review", text: "Review the opt-outs first." });
    else if (HELD_PAUSES.includes(data?.pause_reason ?? ""))
      problems.push({ rule: data?.pause_reason ?? "", text: "Fix the reason shown at the top of the page first." });
  } else {
    for (const b of check.data?.blockers ?? []) {
      problems.push({ rule: b.rule, text: blockerNote(b.rule, { promotionalOpen: null })?.text ?? b.reason });
    }
    // `ready` is the gate's verdict, not an empty list: a check still loading, failed, or
    // not ready without naming why holds the start rather than offering a press it refuses.
    if (problems.length === 0 && check.data?.ready !== true) {
      problems.push({
        rule: "launch_check",
        text: check.data
          ? "It isn't ready to start yet."
          : check.error
            ? "The checks did not load. Close this and try again."
            : "Still checking the campaign.",
      });
    }
    if ((data?.total ?? 0) === 0 && !problems.some((p) => p.rule === "no_contacts"))
      problems.push({ rule: "no_contacts", text: "Add the people to call." });
  }
  const shown = refused.length > 0 ? refused : problems;
  const waiting = data?.contacts.pending ?? 0;

  const open = () => {
    action.reset();
    setAsking(true);
    if (problems.length > 0) highlight(problems.map((p) => sectionFor(p.rule, campaignId)));
  };

  return (
    <>
      <button type="button" className={PRIMARY_BUTTON_SM} title={refusal} disabled={!canWrite} onClick={open}>
        <PhoneOutgoing aria-hidden className="h-3.5 w-3.5" />
        Start campaign
      </button>
      {asking && (
        <ConfirmDialog
          title={shown.length > 0 ? "This campaign can't start yet" : "Start this campaign?"}
          confirmLabel="Start campaign"
          pendingLabel="Starting"
          cancelLabel={shown.length > 0 ? "Close" : "Not now"}
          status={action.status}
          confirmDisabled={problems.length > 0 || check.isRefetching}
          error={refused.length > 0 || slotsFull ? null : action.error}
          onCancel={() => {
            action.reset();
            setAsking(false);
          }}
          onConfirm={() => (resuming ? resume.run("resume") : launch.run())}
        >
          {slotsFull ? <SlotsFullProblem slug={slug} error={action.error} /> : null}
          {shown.length > 0 ? (
            <>
              <span className="block">Fix these first. The sections are outlined in red on the page.</span>
              <span className="mt-2 block">
                {shown.map((p) => (
                  <span key={p.rule + p.text} className="block text-danger">
                    • {p.text}
                  </span>
                ))}
              </span>
            </>
          ) : (
            <>
              <span className="block">
                {carryOn
                  ? "It carries on from where it stopped."
                  : `It calls the ${formatCount(data?.total ?? 0)} people on the list.`}
              </span>
              {carryOn && (
                <span className="block">
                  {waiting === 1 ? "1 person is" : `${formatCount(waiting)} people are`} still to be called.
                </span>
              )}
              <span className="block">You can stop it at any time.</span>
            </>
          )}
        </ConfirmDialog>
      )}
    </>
  );
}
