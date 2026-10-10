"use client";

import { Checklist, type ChecklistItem } from "@/components/console/checklist";
import { TEXT_ACTION } from "@/components/console/section";
import { ProblemNotice } from "@/components/ui";
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
 * The setup checklist (D-695): what is left of the business setup, each row resuming its
 * step. On the DASHBOARD until the account is live (founder, REDESIGN-2): it folds away once
 * every step is answered or skipped and nothing still stops an agent going live, and it
 * goes when the client hides it. Under SETTINGS (Business profile) it always shows, so a
 * finished or hidden list is never lost, and a hidden one can be put back on the dashboard.
 *
 * Renders nothing while loading or on a failed read: the checklist is help, and a guess
 * about what is left would be worse than no list (§52).
 */
export function SetupChecklist({ placement = "dashboard" }: { placement?: "dashboard" | "settings" }) {
  const { session, href: realmHref } = useClientRealm();
  // Paths below are relative to this account: "/setup" is /c/<slug>/setup.
  const href = (path: string) => realmHref(`/c/${session.orgSlug}${path}`);
  const profile = useBusinessProfile(session);
  const write = useWriteAccess(session, "org:manage", "hide the setup checklist");
  const dismiss = useSetupAction(session);

  const data = profile.data;
  if (!data) return null;
  const finished = data.setup.complete && data.blockers.length === 0;
  const onDashboard = placement === "dashboard";
  if (onDashboard && (data.setup.dismissed || finished)) return null;

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
    <div className={onDashboard ? "border-y border-line py-4" : ""}>
      <Checklist
        label={onDashboard ? "Set up your business" : finished ? "Your setup is complete" : "Your setup"}
        items={items}
        collapsible={onDashboard}
        headingLevel={2}
      />
      {dismiss.error && <ProblemNotice error={dismiss.error} />}
      {write.allowed && onDashboard && (
        <button
          type="button"
          onClick={() => dismiss.mutate({ action: "dismiss" })}
          disabled={dismiss.isPending}
          className="press mt-3 rounded-sm text-meta font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          Hide this list
        </button>
      )}
      {write.allowed && !onDashboard && data.setup.dismissed && !finished && (
        <button
          type="button"
          onClick={() => dismiss.mutate({ action: "reopen" })}
          disabled={dismiss.isPending}
          className={`${TEXT_ACTION} mt-3`}
        >
          Show it on the dashboard again
        </button>
      )}
    </div>
  );
}
