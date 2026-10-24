"use client";

/**
 * ONE CLIENT'S CALL HANDLING DEFAULTS, the operator's half of `/c/[slug]/settings/call-handling`.
 *
 * Same rows, same values, written through `PUT /v1/admin/organizations/{id}/call-handling`
 * (`admin:tenants`) rather than through a view-as session, so the change is audited under the
 * operator's own name. An agent's own values stay on its page (Agents, then the agent's
 * Call handling section); this is what every agent without one follows.
 */

import { use } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { CallHandlingDefaultsRows } from "@/components/callHandlingDefaults";
import { PageHeader } from "@/components/console/pageHeader";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { useTenant } from "@/lib/api/admin";
import {
  agentOverridesSummary,
  ambienceSummary,
  fillerSummary,
  pauseLabel,
  silenceSummary,
  useAdminOrganizationCallHandling,
  useAdminSetOrganizationCallHandling,
} from "@/lib/api/callHandling";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { useAdminAccess } from "@/app/admin/access";

export default function TenantCallHandlingPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenant = useTenant(tenantId).data;
  const state = useAdminOrganizationCallHandling(tenantId);
  const save = useAdminSetOrganizationCallHandling(tenantId, tenant?.slug);
  // The row that saved shows pending and the error face on its save bar, with the refusal
  // beside it; the bar closes on success, so the success is a toast.
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Call settings saved" });
  const write = useAdminAccess("admin:tenants", "change a client's call handling defaults");
  const data = state.data;

  useCopilotSurface({
    route: "/admin/tenants/{id}/call-handling",
    title: "Call handling defaults",
    realm: "admin",
    fields: [],
    facts: [
      { key: "tenant_id", label: "Tenant id", value: tenantId },
      { key: "client", label: "Client", value: tenant?.name ?? "not read yet" },
      ...(data
        ? [
            {
              key: "pause_before_reply",
              label: "Pause before agents reply, unless an agent has its own",
              value: `${pauseLabel(data.turn_silence_ms_effective)}${data.turn_silence_ms === null ? ", the Calevate default" : ""}`,
            },
            {
              key: "hang_up_when_finished",
              label: "Agents hang up when the conversation ends, unless an agent has its own",
              value: `${data.end_call_on_finish_effective ? "yes" : "no"}${data.end_call_on_finish === null ? ", the Calevate default" : ""}`,
            },
            {
              key: "if_the_caller_goes_quiet",
              label: "What agents do when the caller goes quiet",
              value: silenceSummary(
                data.nudge_after_seconds_effective,
                data.nudge_count_effective,
                data.end_after_silence_seconds_effective,
              ),
            },
            {
              key: "lines_while_looking_up",
              label: "Lines agents say while they look something up",
              value: fillerSummary(data.filler_lines_effective),
            },
            {
              key: "background_sound",
              label: "Background sound on calls",
              value: ambienceSummary(data.ambience_effective, data.ambience_volume_pct_effective),
            },
            {
              key: "agents_with_own",
              label: "Agents that do not follow these defaults, and what they use instead",
              value: agentOverridesSummary(data),
            },
          ]
        : [
            {
              key: "state",
              label: "What is on screen",
              value: state.error ? "the settings failed to load" : "still loading",
            },
          ]),
    ],
    apply: noFill,
  });

  return (
    <div className="max-w-2xl space-y-5 pb-12">
      <PageHeader
        title="Call handling"
        description="How this client's agents wait for callers and end their calls, unless an agent has its own. A change reaches live agents from their next call."
      />
      {state.error != null && (
        <ProblemNotice error={state.error} onRetry={() => void state.refetch()} />
      )}
      {state.isLoading ? (
        <Skeleton rows={2} label="Loading this client's call handling defaults" />
      ) : !data ? null : (
        <>
          <RestrictionNote reason={write.allowed ? null : write.reason} />
          <CallHandlingDefaultsRows
            data={data}
            save={save}
            status={feedback.status}
            canChange={write.allowed}
            idPrefix={`tenant-${tenantId}`}
            ownLabel="This client's default"
            agentHref={(agentId) => `/admin/tenants/${tenantId}/agents/${agentId}/prompt?section=limits`}
          />
        </>
      )}
    </div>
  );
}
