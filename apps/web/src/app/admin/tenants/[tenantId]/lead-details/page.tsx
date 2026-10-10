"use client";

import { use, useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import { ConfirmDialog } from "@/components/confirmDialog";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { LeadDetailsView } from "@/components/leadFields/LeadDetailsView";
import { FIELD, FIELD_LABEL, ProblemNotice, SECONDARY_BUTTON, Skeleton } from "@/components/ui";
import { BUSINESS_TYPES, businessTypeLabel, type BusinessType } from "@/lib/businessTypes";
import {
  useAdminDraftLeadFields,
  useAdminLeadFields,
  useAdminReplaceLeadFields,
  useAdminSaveAgentLeadFields,
  type LeadFields,
} from "@/lib/api/leadFields";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { examplesFor } from "@/lib/verticalExamples";

/**
 * One client's lead details, for an operator (founder decision 15): the same screen the
 * client sees, plus the one operator tool — replacing every agent's business details with
 * a business type's standard set, which is how an account set up on the wrong type (a shop
 * seated on clinic details) is moved. Replacing is a new version per agent; answers
 * already captured stay readable under their old names.
 */
export default function TenantLeadDetailsPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const fields = useAdminLeadFields(tenantId);
  const write = useAdminAccess("admin:tenants", "change a client's lead details");
  const writes = {
    save: useAdminSaveAgentLeadFields(tenantId),
    draft: useAdminDraftLeadFields(tenantId),
    replace: useAdminReplaceLeadFields(tenantId),
  };

  useCopilotSurface({
    route: "/admin/tenants/{id}/lead-details",
    title: "Lead details",
    realm: "admin",
    fields: [],
    facts: fields.data
      ? [
          { key: "tenant_id", label: "Tenant id", value: tenantId },
          { key: "business_type", label: "Business type", value: fields.data.business_type_label },
          {
            key: "agents",
            label: "Business details per agent (names only)",
            value:
              fields.data.agents
                .map((a) => `${a.name}: ${a.business_fields.map((f) => f.label).join(", ") || "none"}`)
                .join("; ") || "no agents",
          },
          { key: "draft", label: "AI draft", value: fields.data.draft?.status ?? "none" },
        ]
      : [{ key: "state", label: "This client", value: fields.error ? "could not be read" : "still loading" }],
    apply: noFill,
  });

  return (
    <div className="space-y-10">
      <PageHeader
        title="Lead details"
        description="What every call of this client writes down. Every change is a new version; nothing already captured is rewritten."
      />
      {fields.isPending ? (
        <Skeleton rows={8} label="Loading the lead details" />
      ) : fields.isError ? (
        <ProblemNotice error={fields.error} onRetry={() => void fields.refetch()} />
      ) : (
        <>
          <LeadDetailsView
            data={fields.data}
            audience="operator"
            canWrite={write.allowed}
            writeReason={write.reason}
            writes={writes}
            eg={examplesFor(fields.data.business_type)}
          />
          {write.allowed && fields.data.agents.length > 0 && (
            <ReplaceAll data={fields.data} replace={writes.replace} />
          )}
        </>
      )}
    </div>
  );
}

function ReplaceAll({
  data,
  replace,
}: {
  data: LeadFields;
  replace: ReturnType<typeof useAdminReplaceLeadFields>;
}) {
  const offered = BUSINESS_TYPES.filter((option) => option.value !== "custom");
  const current = offered.find((option) => option.value === data.business_type)?.value;
  const [type, setType] = useState<BusinessType>(current ?? offered[0].value);
  const [confirming, setConfirming] = useState(false);
  return (
    <Section
      className="max-w-3xl"
      title="Move every agent to a standard set"
      description="For an account set up on the wrong business type. Change the type under Business details first; this replaces each agent's business details and keeps every answer already captured readable."
    >
      <div className="flex flex-wrap items-end gap-3">
        <label className="block min-w-0">
          <span className={FIELD_LABEL}>Standard details for</span>
          <select
            className={`${FIELD} w-full sm:w-72`}
            value={type}
            onChange={(event) => {
              const next = BUSINESS_TYPES.find((option) => option.value === event.target.value);
              if (next) setType(next.value);
              replace.reset();
            }}
          >
            {offered.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className={SECONDARY_BUTTON}
          disabled={replace.isPending}
          onClick={() => setConfirming(true)}
        >
          Replace on every agent
        </button>
      </div>
      {replace.data && !confirming && (
        <p role="status" className="mt-3 text-sm text-ink-muted">
          {replace.data.agents_changed} agent{replace.data.agents_changed === 1 ? "" : "s"} moved
          {replace.data.agents_unchanged > 0
            ? `; ${replace.data.agents_unchanged} already had these details`
            : ""}
          .
        </p>
      )}
      {confirming && (
        <ConfirmDialog
          title={`Replace every agent's details with the ${businessTypeLabel(type).toLowerCase()} set?`}
          confirmLabel="Replace details"
          pendingLabel="Replacing…"
          pending={replace.isPending}
          error={replace.error}
          onCancel={() => setConfirming(false)}
          onConfirm={() =>
            replace.mutate(
              { business_type: type, agent_ids: null },
              { onSuccess: () => setConfirming(false) },
            )
          }
        >
          <p>
            {data.agents.length} agent{data.agents.length === 1 ? "" : "s"} will write down the
            standard {businessTypeLabel(type).toLowerCase()} details from the next call. The
            client is not told; their Lead details screen shows the new list.
          </p>
          <p>Answers already captured stay on their leads and calls, under their old names.</p>
        </ConfirmDialog>
      )}
    </Section>
  );
}
