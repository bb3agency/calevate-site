"use client";

/**
 * START CAMPAIGN, in the page header on every tab and under the checks (redesign plan §3). A
 * campaign starts and stops any time: Start resumes a stopped (paused) one, and launches a
 * draft or a campaign stopped before Stop became a pause, through the same gate.
 *
 * Every press asks first (founder, 16 Nov 2026: "ask the user again, if he is sure"). The box
 * says who will be called; when something stands in the way it lists each thing instead,
 * holds the start, and outlines the sections that need fixing, opening the tab of the first.
 * A refusal from the server (its compliance gate runs again on every start, hard rule 5)
 * shows in the same box.
 *
 * The button stays pressable while something is in the way, rather than disabled: the box it
 * opens is what lists every blocker and takes the owner to each. The line beside it says
 * what is left before anyone presses.
 */

import { PhoneOutgoing } from "lucide-react";
import { useEffect, useState } from "react";

import { type ActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { PRIMARY_BUTTON_SM, formatCount } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import type { useCampaignProgress, useLaunchCheck } from "@/lib/api/campaigns";

import { blockerNote } from "./blockerCopy";
import { useChecksLeft } from "./LaunchGate";
import {
  SCRIPT_SECTION,
  agentSectionId,
  complianceCardId,
  peopleSectionId,
  useOpenCampaignSection,
} from "./campaignSections";
import { reviewHoldsResume } from "./resumeHold";
import { SlotsFullProblem, isSlotsFull } from "./SlotHolders";

/** The section a launch rule is fixed in. */
export function sectionFor(rule: string, campaignId: string): string {
  if (rule === "no_contacts" || rule === "all_contacts_dnc") return peopleSectionId(campaignId);
  if (rule.startsWith("agent_") || rule === "disclosure_missing") return agentSectionId(campaignId);
  if (rule.startsWith("script_") || rule === "truthful_answer_drift") return SCRIPT_SECTION;
  return complianceCardId(campaignId);
}

type Problem = { rule: string; text: string };

/**
 * The one line beside Start: the checks left (the same count as the Checks tab and the
 * card), else the first other thing in the way, each opening the section that fixes it.
 */
function LeftLine({
  problems,
  check,
  campaignId,
}: {
  problems: readonly Problem[];
  check: ReturnType<typeof useLaunchCheck>;
  campaignId: string;
}) {
  const openSection = useOpenCampaignSection();
  const checksLeft = useChecksLeft(check);
  const left =
    checksLeft != null && checksLeft > 0
      ? {
          text: checksLeft === 1 ? "1 check left. Open Checks" : `${formatCount(checksLeft)} checks left. Open Checks`,
          section: complianceCardId(campaignId),
        }
      : problems[0]
        ? { text: problems[0].text, section: sectionFor(problems[0].rule, campaignId) }
        : null;
  if (!left) return null;
  return (
    <button
      type="button"
      className="text-meta text-ink-muted underline decoration-line underline-offset-4 hover:text-ink touch:min-h-11"
      onClick={() => openSection(left.section)}
    >
      {left.text}
    </button>
  );
}

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
  showLeft = false,
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
  /** Say beside the button what is left before it can start, as a link to it. */
  showLeft?: boolean;
}) {
  const openSection = useOpenCampaignSection();
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
    if (refused.length > 0) openSection(refused.map((p) => sectionFor(p.rule, campaignId)), "problem");
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

  // What stands in the way, before the press: the launch check, or an opt-out review still
  // owed (`reviewHoldsResume`, the rule the list row's Resume follows too). Anything else
  // that still stops a resume is the server's refusal, shown in this box.
  const problems: Problem[] = [];
  if (resuming) {
    if (reviewHoldsResume(data)) problems.push({ rule: "complaint_review", text: "Review the opt-outs first." });
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
    if (problems.length > 0) openSection(problems.map((p) => sectionFor(p.rule, campaignId)), "problem");
  };

  // What is left, in words beside the button, so no tab has to be opened to learn why it
  // would not start. Only once the check has answered: a guess would be wrong half the time.
  const showsLeft = showLeft && !resuming && check.data != null && !check.data.ready;

  return (
    <>
      {showsLeft && <LeftLine problems={problems} check={check} campaignId={campaignId} />}
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
