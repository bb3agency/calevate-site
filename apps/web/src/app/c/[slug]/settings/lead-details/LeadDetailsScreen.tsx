"use client";

import { LeadDetailsView } from "@/components/leadFields/LeadDetailsView";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  useDraftLeadFields,
  useLeadFields,
  useReplaceLeadFields,
  useSaveAgentLeadFields,
} from "@/lib/api/leadFields";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

/**
 * Lead details: what every call of this business writes down (founder decision 15).
 * Readable by everyone on the account; changed by the owner, and by an operator in a
 * view-as session.
 */
export function LeadDetailsScreen() {
  const { session } = useClientRealm();
  const fields = useLeadFields(session);
  const write = useWriteAccess(session, "org:manage", "change the lead details");
  const eg = useVerticalExamples();
  const writes = {
    save: useSaveAgentLeadFields(session),
    draft: useDraftLeadFields(session),
    replace: useReplaceLeadFields(session),
  };

  useCopilotSurface({
    route: "/c/{slug}/settings/lead-details",
    title: "Lead details",
    realm: "client",
    fields: [],
    facts: fields.data
      ? [
          { key: "business_type", label: "Business type", value: fields.data.business_type_label },
          {
            key: "always_captured",
            label: "Captured on every call, fixed",
            value: fields.data.core_fields.map((f) => f.label).join(", "),
          },
          ...fields.data.agents.map((agent) => ({
            key: `agent_${agent.id}`,
            label: `Business details ${agent.name} writes down (names only)`,
            value: agent.business_fields.map((f) => f.label).join(", ") || "none yet",
          })),
          {
            key: "draft",
            label: "Drafted once from the business details",
            value: fields.data.draft?.status ?? (fields.data.can_draft ? "not yet" : "not needed"),
          },
        ]
      : [{ key: "state", label: "What is on screen", value: fields.error ? "failed to load" : "still loading" }],
    apply: noFill,
  });

  if (fields.isPending) return <Skeleton rows={8} label="Loading the lead details" />;
  if (fields.isError)
    return <ProblemNotice error={fields.error} onRetry={() => void fields.refetch()} />;
  return (
    <LeadDetailsView
      data={fields.data}
      audience="client"
      canWrite={write.allowed}
      writeReason={write.reason}
      writes={writes}
      eg={eg}
    />
  );
}
