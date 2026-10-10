"use client";

import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { NoticeBox, ProblemNotice, Skeleton, formatIST, formatISTStamp } from "@/components/ui";
import { PageHeader } from "@/components/console/pageHeader";
import { useAdminAccess } from "@/app/admin/access";
import {
  useFirstCampaignDecision,
  useTenant,
  useTenantFirstCampaignHold,
} from "@/lib/api/admin";
import { firstCampaignState, type FirstCampaignHold } from "@/lib/api/firstCampaign";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { DecisionForm } from "./DecisionForm";
import { HoldPill, WhereItStands } from "./WhereItStands";

/** Content, not identity: an equal refetch must not wipe a half-written note. */
function holdStamp(hold: FirstCampaignHold): string {
  return [hold.held, hold.rule, hold.status, hold.decision_note, hold.reviewed_campaign_id].join("|");
}

/**
 * Releasing (or refusing) a self-serve account's campaign calling — R-11's last hold, as an
 * audited compliance decision rather than a toggle. A rejection is not a deletion: the note
 * goes to the client VERBATIM, the account stays held, and a reviewer looks again.
 *
 * Two sessions, deliberately: the state is READ through impersonation (`org:read`, the only
 * read of a tenant's review that exists) and the decision is WRITTEN through the admin
 * surface with the tenant in the path (`admin:tenants`, which a view-as session is refused,
 * D-587). The mutation lives here rather than in the form because a successful write
 * remounts the form by its key, and a mutation held inside it would take the confirmation
 * of the write down with it.
 */
export function ReviewScreen({ tenantId }: { tenantId: string }) {
  const tenantQuery = useTenant(tenantId);
  const tenant = tenantQuery.data;
  const slug = tenant?.slug ?? "";
  const decide = useFirstCampaignDecision(tenantId);
  const hold = useTenantFirstCampaignHold(slug);
  const write = useAdminAccess("admin:tenants", "record a review decision");

  /*
   * `decision_note` is not declared, in either direction: reading it out would forward an
   * operator's prose about a named client, and writing it would have the assistant compose
   * the justification an auditor will later read as a human's.
   */
  const state = hold.data ? firstCampaignState(hold.data) : null;
  useCopilotSurface({
    route: "/admin/tenants/{id}/first-campaign-review",
    title: "First campaign review",
    realm: "admin",
    fields: [],
    facts:
      hold.data && state
        ? [
            { key: "tenant_id", label: "Tenant id", value: tenantId },
            { key: "client", label: "Client", value: tenant?.name ?? "not read yet" },
            { key: "state", label: "Where this account stands", value: state },
            { key: "held", label: "Is outbound campaigning held", value: hold.data.held ? "yes" : "no" },
            { key: "rule", label: "Which gate is holding it", value: hold.data.rule ?? "none" },
            { key: "status", label: "Recorded decision", value: hold.data.status ?? "none yet" },
            { key: "decided_at", label: "When it was decided", value: formatISTStamp(hold.data.decided_at, "not decided") },
            {
              key: "note_recorded",
              label: "Is a decision note on file (the text itself is not sent)",
              value: hold.data.decision_note ? "yes" : "no",
            },
            {
              key: "may_decide",
              label: "May this operator record a decision",
              value: write.allowed ? "yes" : "no",
            },
          ]
        : [
            { key: "client", label: "Client", value: tenant?.name ?? "not read yet" },
            {
              key: "hold",
              label: "The current decision",
              // Deciding while the state is unreadable can reverse a colleague's refusal.
              value: hold.error ? "could not be read" : "still loading",
            },
          ],
    apply: noFill,
  });

  // The tenant layout resolves this before mounting the page.
  if (!tenant) return null;

  return (
    <div className="max-w-3xl space-y-10">
      <PageHeader
        title="First campaign review"
        status={hold.data ? <HoldPill hold={hold.data} /> : null}
        description="Release or refuse this account's campaign calling after reading its first campaign. Inbound answering is never held by it."
      />

      {hold.error && <ProblemNotice error={hold.error} onRetry={() => hold.refetch()} />}

      {hold.isLoading ? (
        <Skeleton rows={4} />
      ) : !hold.data ? (
        /* Withheld, not merely unpopulated: this write replaces the CURRENT decision, so
           deciding blind can reverse a colleague's refusal or re-release an account that was
           withdrawn because complaints arrived. A retry is the cheaper failure. */
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Cannot decide while the current state is unreadable"
        >
          <p className="mt-1 text-meta opacity-90">
            We could not read where this account stands. A decision replaces whatever is on
            file, so recording one now could reverse a colleague&apos;s without anyone seeing
            it happen. Retry the read above; the form comes back with it.
          </p>
        </NoticeBox>
      ) : (
        <>
          <WhereItStands hold={hold.data} tenantName={tenant.name} slug={slug} />
          {decide.data && (
            <NoticeBox tone="ok" icon={<CheckCircle2 className="h-5 w-5" />}>
              <p>
                Recorded as <span className="font-medium">{decide.data.status}</span> at{" "}
                {formatIST(decide.data.decided_at)} IST. The panel above has re-read the
                gate&apos;s own answer, and the client&apos;s campaign screen reflects it from
                their next request.
              </p>
            </NoticeBox>
          )}
          {decide.error != null && <ProblemNotice error={decide.error} />}
          <DecisionForm
            key={holdStamp(hold.data)}
            decide={decide}
            tenantName={tenant.name}
            slug={slug}
            write={write}
          />
        </>
      )}
    </div>
  );
}
