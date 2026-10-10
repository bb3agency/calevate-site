"use client";

import Link from "next/link";
import { use } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { NoticeBox, ProblemNotice } from "@/components/ui";
import { PageHeader } from "@/components/console/pageHeader";
import { adminSession, useTenant } from "@/lib/api/admin";
import { useClosure } from "@/lib/api/closure";
import { useSetTenantStatus } from "@/lib/api/commercials";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { useAdminAccess } from "@/app/admin/access";
import { MovePanel } from "./MovePanel";

const LINK =
  "rounded-sm font-medium text-brand-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2";

/**
 * Account state: suspend and reactivate (SURFACES §1).
 *
 * Suspending genuinely stops the campaigns because `compliance.check_dispatch` refuses a
 * suspended or closed account; this screen writes the status the gate reads. Closing left
 * this screen with D-546 and lives on Closing the account, together with the erasure.
 *
 * The header sentence below is read by `tests/credit_stop_copy_test.py` from THIS file: a
 * suspension leaves inbound answering alone, and saying so is load-bearing.
 */
export default function LifecyclePage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const move = useSetTenantStatus(adminSession(), tenantId);
  const write = useAdminAccess("admin:tenants", "change an account's state");

  /*
   * No fields: every control here stops a business dialling, and the assistant explaining
   * what that does is useful while the assistant putting a value near it is not.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/lifecycle",
    title: "Account state",
    realm: "admin",
    fields: [],
    facts: tenantQuery.data
      ? [
          { key: "tenant_id", label: "Tenant id", value: tenantId },
          { key: "client", label: "Client", value: tenantQuery.data.name },
          { key: "status", label: "Account status now", value: tenantQuery.data.status },
          {
            key: "closed",
            label: "Is this account closed (reopening is on the Closing screen, not here)",
            value: tenantQuery.data.status === "churned" ? "yes" : "no",
          },
          {
            key: "may_move",
            label: "May this operator suspend or reactivate",
            value: write.allowed ? "yes" : "no",
          },
        ]
      : [
          {
            key: "client",
            label: "This client",
            // "Active" printed over a 503 is how somebody suspends the wrong client.
            value: tenantQuery.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  // The tenant layout resolves this read before mounting the page; outside the layout
  // (tests) a page that could not read the state renders nothing rather than a guess.
  const tenant = tenantQuery.data;
  if (!tenant) return null;

  return (
    <div className="max-w-3xl space-y-10">
      <PageHeader
        title="Account state"
        description="Suspending stops outbound dialling at the next dial. Inbound answering is never affected: their own customers still get through."
      />

      {tenant.status === "churned" ? (
        <ClosedNotice tenantId={tenantId} />
      ) : (
        <>
          <MovePanel
            move={move}
            currentStatus={tenant.status}
            tenantName={tenant.name}
            write={write}
          />
          <p className="text-body text-ink-muted">
            Ending the relationship for good is on{" "}
            <Link href={`/admin/tenants/${tenantId}/closure`} className={LINK}>
              Closing the account
            </Link>
            , which tells the client, sets the date their records go, and can be undone.
          </p>
        </>
      )}

      {move.error != null && <ProblemNotice error={move.error} />}
      {move.data && (
        <NoticeBox
          tone={move.data.changed ? "ok" : "neutral"}
          icon={<CheckCircle2 className="h-5 w-5" />}
        >
          <p>
            {move.data.changed
              ? `This account is now ${move.data.status}. The dial gate reads it from the next request.`
              : `This account was already ${move.data.status} — nothing changed, and no audit row was written.`}
          </p>
        </NoticeBox>
      )}
    </div>
  );
}

/**
 * What a CLOSED account gets instead of a state control. Reopening is a real way back
 * (`DELETE .../closure`, for as long as nothing has been erased), so this names where it
 * is rather than saying it is impossible.
 *
 * The countdown is not repeated: `days_remaining` belongs beside the button that acts on
 * it, and a deadline printed on two screens will disagree with itself.
 */
function ClosedNotice({ tenantId }: { tenantId: string }) {
  const closure = useClosure(tenantId);

  return (
    <NoticeBox tone="stop" icon={<AlertTriangle className="h-5 w-5" />} title="This account is closed">
      <p className="mt-1 text-meta opacity-90">
        Its users have no access and its outbound dialling has stopped. This screen cannot
        reopen it — closing, reopening and erasing their data all live on{" "}
        <Link href={`/admin/tenants/${tenantId}/closure`} className="rounded-sm font-medium underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
        >
          Closing the account
        </Link>
        , together with the date their records are erased.
      </p>
      {/* Only ever an addition, never a replacement: a failed or in-flight closure read
          must not leave a closed account looking unclosed. */}
      {closure.data?.restorable && (
        <p className="mt-2 text-meta opacity-90">
          Nothing has been erased yet, so this close can still be undone.
        </p>
      )}
    </NoticeBox>
  );
}
