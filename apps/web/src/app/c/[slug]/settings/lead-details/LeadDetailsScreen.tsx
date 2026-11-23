"use client";

import { useActionFeedback } from "@/components/arc/feedback";
import { CallOutcomesView } from "@/components/leadFields/CallOutcomesView";
import { LeadDetailsView, type JobLinks } from "@/components/leadFields/LeadDetailsView";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useCallOutcomes, useDraftCallOutcomes, useSaveCallOutcomes } from "@/lib/api/callOutcomes";
import { useWriteAccess } from "@/lib/api/hooks";
import { useLeadNouns } from "@/lib/businessCapabilities";
import {
  useReviewLeadFieldsDraft,
  useLeadFields,
  useNameCoreDetails,
  useReplaceLeadFields,
} from "@/lib/api/leadFields";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { useVerticalExamples } from "@/lib/useVerticalExamples";

import { CLIENT_JOB_NOTES } from "../../campaigns/CampaignNotes";

/**
 * Lead details: what every call of this business writes down (founder decision 15), one card
 * per campaign and Inbound line (D-1029). Readable by everyone on the account; changed by the
 * owner, and by an operator in a view-as session.
 */
export function LeadDetailsScreen() {
  const { session, href } = useClientRealm();
  const slug = session.orgSlug;
  const fields = useLeadFields(session);
  const write = useWriteAccess(session, "org:manage", "change the lead details");
  const eg = useVerticalExamples();
  const nouns = useLeadNouns();
  const outcomes = useCallOutcomes(session);
  const saveOutcomes = useSaveCallOutcomes(session);
  const draftOutcomes = useDraftCallOutcomes(session);
  const reviewDraft = useReviewLeadFieldsDraft(session);
  const replaceFields = useReplaceLeadFields(session);
  const nameCore = useNameCoreDetails(session);
  // The views draw each write's busy face, saved tick and refusal beside its own button, so a
  // failure stays inline rather than being said twice in a toast.
  useActionFeedback(saveOutcomes, { errorDisplay: "inline" });
  useActionFeedback(draftOutcomes, { errorDisplay: "inline" });
  useActionFeedback(reviewDraft, { errorDisplay: "inline" });
  useActionFeedback(replaceFields, { errorDisplay: "inline" });
  useActionFeedback(nameCore, { errorDisplay: "inline" });
  const writes = { review: reviewDraft, replace: replaceFields, nameCore };
  const links: JobLinks = {
    open: (kind, id) => href(kind === "campaign" ? `/c/${slug}/campaigns/${id}` : `/c/${slug}/inbound/${id}`),
    create: (kind) => href(kind === "campaign" ? `/c/${slug}/campaigns/new` : `/c/${slug}/inbound`),
  };

  useCopilotSurface({
    route: "/c/{slug}/settings/lead-details",
    title: nouns.LeadDetails,
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
          {
            key: "starting_set",
            label: "What a new campaign or line starts with (names only)",
            value: fields.data.starting_fields.map((f) => f.label).join(", ") || "only the fixed details",
          },
          ...fields.data.jobs.map((job) => ({
            key: `${job.kind}_${job.id}`,
            label: `What the ${job.kind === "campaign" ? "campaign" : "line"} ${job.name} notes (names only; ${job.kind} id ${job.id})`,
            value: job.fields.map((f) => f.label).join(", ") || "only the fixed details",
          })),
          {
            key: "draft",
            label: "Drafted once from the business details",
            value:
              fields.data.draft?.status === "done" && !fields.data.draft.reviewed
                ? "drafted; waiting for the owner to keep the ones that fit, on this screen"
                : (fields.data.draft?.status ?? (fields.data.can_draft ? "not yet" : "not needed")),
          },
          ...(outcomes.data
            ? outcomes.data.agents.map((agent) => ({
                key: `outcomes_${agent.id}`,
                label: `How ${agent.name}'s calls can end for the business (names only)`,
                value: agent.outcomes.map((o) => o.label).join(", ") || "none",
              }))
            : [
                {
                  key: "outcomes",
                  label: "How calls end",
                  value: outcomes.error ? "failed to load" : "still loading",
                },
              ]),
        ]
      : [{ key: "state", label: "What is on screen", value: fields.error ? "failed to load" : "still loading" }],
    apply: noFill,
  });

  if (fields.isPending) return <Skeleton rows={8} label={`Loading the ${nouns.lead} details`} />;
  if (fields.isError)
    return <ProblemNotice error={fields.error} onRetry={() => void fields.refetch()} />;
  return (
    <div className="space-y-10">
      <LeadDetailsView
        data={fields.data}
        audience="client"
        canWrite={write.allowed}
        writeReason={write.reason}
        writes={writes}
        source={CLIENT_JOB_NOTES}
        links={links}
      />
      <div className="max-w-3xl">
        {outcomes.isPending ? (
          <Skeleton rows={4} label="Loading how calls end" />
        ) : outcomes.isError ? (
          <ProblemNotice error={outcomes.error} onRetry={() => void outcomes.refetch()} />
        ) : (
          <CallOutcomesView
            data={outcomes.data}
            canWrite={write.allowed}
            save={saveOutcomes}
            draft={draftOutcomes}
            examples={eg}
          />
        )}
      </div>
    </div>
  );
}
