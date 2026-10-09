"use client";

import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { Card, ProblemNotice } from "@/components/ui";
import {
  STEPS,
  setupHref,
  stepStates,
  useBusinessProfile,
  useSetupAction,
} from "@/lib/api/businessProfile";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

/**
 * The dashboard's setup checklist (D-695): what is left of the business setup, each row
 * resuming its step. It folds away once every step is answered or skipped and nothing
 * still stops an agent going live, and it goes when the client hides it.
 *
 * Renders nothing while loading or on a failed read: the checklist is help, and a guess
 * about what is left would be worse than no list (§52).
 */
export function SetupChecklist() {
  const { session, href: realmHref } = useClientRealm();
  // Paths below are relative to this account: "/setup" is /c/<slug>/setup.
  const href = (path: string) => realmHref(`/c/${session.orgSlug}${path}`);
  const profile = useBusinessProfile(session);
  const write = useWriteAccess(session, "org:manage", "hide the setup checklist");
  const dismiss = useSetupAction(session);

  const data = profile.data;
  if (!data || data.setup.dismissed) return null;
  const finished = data.setup.complete && data.blockers.length === 0;
  if (finished) return null;

  const states = stepStates(data);
  const blocking = new Set(data.blockers.map((b) => b.step));
  const items: ChecklistItem[] = STEPS.map((step) => {
    const state = states[step.id];
    return {
      id: step.id,
      label: step.short,
      state: state === "done" ? "done" : "todo",
      detail:
        state === "skipped"
          ? blocking.has(step.id)
            ? "Skipped — your agents need this to take calls"
            : "Skipped"
          : blocking.has(step.id)
            ? "Your agents need this to take calls"
            : undefined,
      link: state === "done" ? undefined : { href: setupHref(href, step.id), label: "Open" },
    };
  });

  return (
    <Card density="compact">
      <Checklist label="Set up your business" items={items} collapsible headingLevel={2} />
      {dismiss.error && <ProblemNotice error={dismiss.error} />}
      {write.allowed && (
        <button
          type="button"
          onClick={() => dismiss.mutate({ action: "dismiss" })}
          disabled={dismiss.isPending}
          className="press mt-3 rounded-sm text-[13px] font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          Hide this list
        </button>
      )}
    </Card>
  );
}
