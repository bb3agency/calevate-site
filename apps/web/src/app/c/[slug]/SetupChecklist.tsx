"use client";

import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { STEPS, setupHref, stepStates, useBusinessProfile } from "@/lib/api/businessProfile";
import { useClientRealm } from "@/lib/api/session";

/**
 * What is answered of the business profile (D-695), on Business profile: each row opens its
 * question one at a time. Always shown there, so a finished list, or one hidden from the
 * dashboard's next steps, is never lost.
 *
 * Renders nothing while loading or on a failed read: the checklist is help, and a guess
 * about what is left would be worse than no list (§52).
 */
export function SetupChecklist() {
  const { session, href: realmHref } = useClientRealm();
  const href = (path: string) => realmHref(`/c/${session.orgSlug}${path}`);
  const profile = useBusinessProfile(session);

  const data = profile.data;
  if (!data) return null;
  const finished = data.setup.complete && data.blockers.length === 0;
  const states = stepStates(data);
  const blocking = new Set(data.blockers.map((b) => b.step));
  // A blocker's own sentence first: this is the one list of what stops calls on Business
  // profile (e2e audit OB-25 removed the second list that repeated it).
  const blockerSaid = new Map(data.blockers.map((b) => [b.step, b.message]));
  const why = new Map(data.setup.nudges.map((n) => [n.step, n.message]));
  const items: ChecklistItem[] = STEPS.map((step) => {
    const state = states[step.id];
    return {
      id: step.id,
      label: step.short,
      state: state === "done" ? "done" : "todo",
      detail:
        blockerSaid.get(step.id) ??
        why.get(step.id) ??
        (state === "skipped"
          ? blocking.has(step.id)
            ? "Skipped — your agents need this to take calls"
            : "Skipped"
          : blocking.has(step.id)
            ? "Your agents need this to take calls"
            : undefined),
      link: state === "done" ? undefined : { href: setupHref(href, step.id), label: "Open" },
    };
  });

  return (
    <Checklist
      label={finished ? "Your setup is complete" : "Your setup"}
      items={items}
      headingLevel={2}
      emphasizeNext
      foldDone
    />
  );
}
