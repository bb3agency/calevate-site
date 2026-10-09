"use client";

/**
 * THIS CLIENT'S OWN THINNESTAI CUSTOMER WORKSPACE (D-693).
 *
 * Every client gets its own workspace, and its numbers are rented there in the client's
 * business name once its KYC is verified and its business details are approved. This panel
 * is where an operator sees why a client cannot buy yet and pulls the levers only an
 * operator has: retry provisioning (after a plan upgrade or a fix), send or re-read the
 * business details, offboard a closed account, and buy on the client's behalf.
 *
 * Renders nothing on a deployment whose engine has no per-client workspaces.
 */

import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import {
  FIELD_INLINE,
  FIELD_LABEL,
  MonoValue,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
  formatINR,
  formatPhone,
} from "@/components/ui";
import {
  useOffboardWorkspace,
  useProvisionWorkspace,
  useRefreshWorkspaceBusinessDetails,
  useSendWorkspaceBusinessDetails,
  useTenantWorkspace,
  useWorkspaceAvailableNumbers,
  useWorkspaceCities,
  useWorkspacePurchase,
  type AdminAvailableNumber,
  type AdminPurchased,
  type TenantWorkspace,
} from "@/lib/api/engineWorkspaces";
import { SEARCH_DIGITS_MAX, newRequestKey, searchDigits } from "@/lib/api/ownNumbers";
import type { components } from "@/lib/api/schema";
import { lookup } from "@/lib/lookup";

import { firstPeriodPhrase } from "./firstPeriod";

type EngineAgent = components["schemas"]["EngineAgentOut"];

const WORKSPACE_STATUS: Record<string, string> = {
  not_provisioned: "Not provisioned",
  pending: "Being provisioned",
  active: "Active",
  plan_limit: "Plan's customer limit reached",
  failed: "Provisioning failed",
  offboarding: "Being offboarded",
  deleted: "Deleted",
};

const DETAILS_STATUS: Record<string, string> = {
  none: "Nothing sent yet",
  draft: "Started, never sent",
  submitted: "Being checked",
  accepted: "Approved",
  rejected: "Rejected — correct it and send again",
  suspended: "Approval withdrawn — ThinnestAI documents no resend for this; raise it with them",
  expired: "Lapsed — send again",
  unknown: "A status we do not recognise",
};

const STEP_COPY: Record<string, string> = {
  workspace: "Waiting on the workspace",
  verify_business: "Waiting on KYC",
  business_details: "Waiting on business-details approval",
  price: "Waiting on an attested number price",
  ready: "Ready to buy",
};

const BLOCKER_COPY: Record<string, string> = {
  engine_workspace_not_provisioned: "The client's workspace is not active.",
  kyc_not_verified: "The client's KYC is not verified.",
  business_details_not_approved: "The business details are not approved by ThinnestAI.",
  number_price_not_attested: "No attested monthly number price in the ops console.",
};

export function WorkspacePanel({
  tenantId,
  canWrite,
  agents,
}: {
  tenantId: string;
  canWrite: boolean;
  /** This client's agents ThinnestAI knows, for the purchase's optional agent. */
  agents: EngineAgent[] | undefined;
}) {
  const workspace = useTenantWorkspace(tenantId);

  if (workspace.isLoading) return <Skeleton rows={3} label="Loading the voice workspace" />;
  if (workspace.error || !workspace.data) {
    return <ProblemNotice error={workspace.error} onRetry={() => void workspace.refetch()} />;
  }
  if (!workspace.data.available) return null;
  return <WorkspaceBody tenantId={tenantId} data={workspace.data} canWrite={canWrite} agents={agents} />;
}

function WorkspaceBody({
  tenantId,
  data,
  canWrite,
  agents,
}: {
  tenantId: string;
  data: TenantWorkspace;
  canWrite: boolean;
  agents: EngineAgent[] | undefined;
}) {
  const provision = useProvisionWorkspace(tenantId);
  const offboard = useOffboardWorkspace(tenantId);
  const send = useSendWorkspaceBusinessDetails(tenantId);
  const refresh = useRefreshWorkspaceBusinessDetails(tenantId);
  const [offboarding, setOffboarding] = useState(false);

  const status = data.status ?? "not_provisioned";
  const details = data.business_details;
  const retryable = status === "not_provisioned" || status === "failed" || status === "plan_limit" || status === "pending";

  return (
    <section
      aria-labelledby="voice-workspace-heading"
      className="space-y-4 rounded-card border border-line bg-surface p-4 sm:p-6"
    >
      <div>
        <h2 id="voice-workspace-heading" className="text-base font-semibold text-ink">
          Voice workspace
        </h2>
        <p className="mt-1 text-sm text-ink-muted">
          This client&apos;s own ThinnestAI customer workspace. Its numbers are rented there, in
          the client&apos;s business name.
        </p>
      </div>

      {status === "plan_limit" && (
        <NoticeBox tone="stop" title="Plan's customer limit reached">
          <p className="mt-1">Upgrade the ThinnestAI plan, then Retry provisioning.</p>
        </NoticeBox>
      )}
      {status === "failed" && (
        <NoticeBox tone="stop" title="Provisioning failed">
          <p className="mt-1">
            {data.last_error_code ? `Last error: ${data.last_error_code}. ` : ""}Fix the cause, then
            Retry provisioning.
          </p>
        </NoticeBox>
      )}

      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[max-content_1fr]">
        <dt className="text-ink-muted">Status</dt>
        <dd className="font-medium text-ink">{lookup(WORKSPACE_STATUS, status) ?? status}</dd>
        <dt className="text-ink-muted">Workspace id</dt>
        <dd className="text-ink">
          {data.workspace_id ? <MonoValue>{data.workspace_id}</MonoValue> : "None yet"}
        </dd>
        <dt className="text-ink-muted">Attempts</dt>
        <dd className="text-ink">{data.attempts}</dd>
        {data.last_error_code && (
          <>
            <dt className="text-ink-muted">Last error</dt>
            <dd className="font-mono text-ink">{data.last_error_code}</dd>
          </>
        )}
        {data.provisioned_at && (
          <>
            <dt className="text-ink-muted">Provisioned</dt>
            <dd className="text-ink">{formatIST(data.provisioned_at)}</dd>
          </>
        )}
        <dt className="text-ink-muted">Numbers</dt>
        <dd className="text-ink">
          {data.numbers
            ? `${data.numbers.own_workspace} in the client's workspace, ${data.numbers.platform_held} held in the platform account`
            : "Not read"}
        </dd>
        <dt className="text-ink-muted">Client pays</dt>
        <dd className="text-ink">
          {data.client_inr_per_month ? `${formatINR(data.client_inr_per_month)} a month per number` : "No attested price"}
        </dd>
      </dl>

      {data.agents_in_platform_account > 0 && (
        <NoticeBox tone="warn">
          {data.agents_in_platform_account === 1
            ? "One agent is still in the platform account. It is recreated in the client's workspace on its next publish."
            : `${data.agents_in_platform_account} agents are still in the platform account. They are recreated in the client's workspace on their next publish.`}
        </NoticeBox>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={!canWrite || !retryable || provision.isPending}
          onClick={() => provision.mutate()}
        >
          {provision.isPending ? "Retrying…" : "Retry provisioning"}
        </button>
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={!canWrite || offboard.isPending}
          onClick={() => {
            offboard.reset();
            setOffboarding(true);
          }}
        >
          Offboard
        </button>
      </div>
      <ProblemNotice error={provision.error} />

      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-ink">Business details</h3>
        {details ? (
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[max-content_1fr]">
            <dt className="text-ink-muted">Status</dt>
            <dd className="font-medium text-ink">
              {lookup(DETAILS_STATUS, details.status ?? "none") ?? DETAILS_STATUS.unknown}
            </dd>
            <dt className="text-ink-muted">Can rent a number</dt>
            <dd className="text-ink">{details.can_rent ? "Yes" : "No"}</dd>
            {details.submitted_at && (
              <>
                <dt className="text-ink-muted">Last sent</dt>
                <dd className="text-ink">{formatIST(details.submitted_at)}</dd>
              </>
            )}
            {details.checked_at && (
              <>
                <dt className="text-ink-muted">Last checked</dt>
                <dd className="text-ink">{formatIST(details.checked_at)}</dd>
              </>
            )}
          </dl>
        ) : (
          <p className="text-sm text-ink-muted">Not read yet.</p>
        )}
        {details?.review_note && (
          <NoticeBox tone="warn" title="Review note">
            <p className="mt-1">{details.review_note}</p>
          </NoticeBox>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={!canWrite || send.isPending}
            onClick={() => send.mutate()}
          >
            {send.isPending ? "Sending…" : "Send business details"}
          </button>
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={!canWrite || refresh.isPending}
            onClick={() => refresh.mutate()}
          >
            {refresh.isPending ? "Reading…" : "Refresh status"}
          </button>
        </div>
        <ProblemNotice error={send.error ?? refresh.error} />
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-ink">Buying a number</h3>
        <p className="text-sm text-ink">
          {lookup(STEP_COPY, data.purchase_step) ?? "Not known"}
        </p>
        {data.purchase_blockers.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-muted">
            {data.purchase_blockers.map((blocker) => (
              <li key={blocker}>
                {lookup(BLOCKER_COPY, blocker) ?? blocker}{" "}
                <span className="font-mono text-xs text-ink-faint">{blocker}</span>
              </li>
            ))}
          </ul>
        )}
        {data.purchase_step === "ready" && (
          <AdminBuyNumber tenantId={tenantId} canWrite={canWrite} agents={agents} />
        )}
      </div>

      {offboarding && (
        <ConfirmDialog
          title="Offboard this client's workspace"
          confirmLabel="Offboard"
          pendingLabel="Offboarding…"
          pending={offboard.isPending}
          error={offboard.error}
          onCancel={() => setOffboarding(false)}
          onConfirm={() => offboard.mutate(undefined, { onSuccess: () => setOffboarding(false) })}
        >
          <p>
            Releases every number in the workspace (permanent, the month is not refunded), deletes
            its agents and deletes the ThinnestAI customer. Refused unless the account is closed.
          </p>
        </ConfirmDialog>
      )}
    </section>
  );
}

const NO_AGENT = "";

/** The client's own purchase, run by an operator: client price and our cost side by side. */
function AdminBuyNumber({
  tenantId,
  canWrite,
  agents,
}: {
  tenantId: string;
  canWrite: boolean;
  agents: EngineAgent[] | undefined;
}) {
  const cities = useWorkspaceCities(tenantId, true);
  const purchase = useWorkspacePurchase(tenantId);
  const [city, setCity] = useState("");
  const [pattern, setPattern] = useState("");
  const [search, setSearch] = useState<{ city: string; pattern: string } | null>(null);
  const available = useWorkspaceAvailableNumbers(tenantId, search);
  const [chosen, setChosen] = useState<AdminAvailableNumber | null>(null);
  const [agentId, setAgentId] = useState(NO_AGENT);
  const [requestKey, setRequestKey] = useState("");
  const [bought, setBought] = useState<AdminPurchased | null>(null);

  if (cities.isLoading) return <Skeleton rows={2} label="Loading cities" />;
  if (cities.error || !cities.data) {
    return <ProblemNotice error={cities.error} onRetry={() => void cities.refetch()} />;
  }
  const pages = available.data?.pages;
  const numbers = pages === undefined ? undefined : pages.flatMap((page) => page.numbers);

  return (
    <div className="space-y-3">
      {bought && (
        <NoticeBox tone="ok" title={`${formatPhone(bought.e164)} bought for the client`}>
          <p className="mt-1">
            {bought.replayed
              ? "An earlier request already bought this number for the client. Nothing more was charged."
              : bought.client_inr_per_month
                ? firstPeriodPhrase(bought.first_period, bought.client_inr_per_month)
                : "No client price recorded."}
          </p>
        </NoticeBox>
      )}
      <form
        noValidate
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (city) setSearch({ city, pattern: searchDigits(pattern) });
        }}
      >
        <label className="flex flex-col gap-1">
          <span className={FIELD_LABEL}>City</span>
          <select className={FIELD_INLINE} value={city} onChange={(event) => setCity(event.target.value)}>
            <option value="">Choose…</option>
            {cities.data.map((option) => (
              <option key={option.name} value={option.name}>
                {option.name} ({option.available})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={FIELD_LABEL}>Contains (optional)</span>
          <input
            className={FIELD_INLINE}
            value={pattern}
            inputMode="numeric"
            maxLength={SEARCH_DIGITS_MAX}
            onChange={(event) => setPattern(searchDigits(event.target.value))}
          />
        </label>
        <button type="submit" className={SECONDARY_BUTTON_SM} disabled={!city || available.isFetching}>
          Find numbers
        </button>
      </form>
      {available.error && <ProblemNotice error={available.error} />}
      {search !== null &&
        !available.error &&
        (numbers === undefined ? (
          <Skeleton rows={2} />
        ) : numbers.length === 0 ? (
          <p className="text-sm text-ink-muted">Nothing free in {search.city} right now.</p>
        ) : (
          <>
            <ul className="divide-y divide-line rounded-card border border-line">
              {numbers.map((offer) => (
                <li key={offer.number} className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm">
                  <span className="font-mono text-ink">{formatPhone(offer.e164)}</span>
                  {offer.city && <span className="text-xs text-ink-muted">{offer.city}</span>}
                  <span className="ml-auto text-ink-muted">
                    Client pays {offer.client_inr_per_month ? formatINR(offer.client_inr_per_month) : "—"}
                    {" · "}our cost {offer.vendor_inr_per_month ? formatINR(offer.vendor_inr_per_month) : "—"} a month
                  </span>
                  <button
                    type="button"
                    className={PRIMARY_BUTTON_SM}
                    disabled={!canWrite}
                    aria-label={`Buy ${formatPhone(offer.e164)}`}
                    onClick={() => {
                      purchase.reset();
                      setAgentId(NO_AGENT);
                      setRequestKey(newRequestKey());
                      setChosen(offer);
                    }}
                  >
                    Buy
                  </button>
                </li>
              ))}
            </ul>
            {available.hasNextPage && (
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={available.isFetchingNextPage}
                onClick={() => void available.fetchNextPage()}
              >
                {available.isFetchingNextPage ? "Loading…" : "Load more"}
              </button>
            )}
          </>
        ))}

      {chosen && (
        <ConfirmDialog
          title={`Buy ${formatPhone(chosen.e164)} for this client`}
          confirmLabel="Buy for the client"
          pendingLabel="Buying…"
          pending={purchase.isPending}
          error={purchase.error}
          onCancel={() => setChosen(null)}
          onConfirm={() =>
            purchase.mutate(
              {
                number: chosen.number,
                agent_id: agentId === NO_AGENT ? null : agentId,
                direction: "both",
                request_key: requestKey,
              },
              {
                onSuccess: (result) => {
                  setBought(result);
                  setChosen(null);
                },
              },
            )
          }
        >
          <p>
            Rented in the client&apos;s workspace, in its business name. The client pays{" "}
            {chosen.client_inr_per_month ? formatINR(chosen.client_inr_per_month) : "no attested price"} a
            month; our cost is {chosen.vendor_inr_per_month ? formatINR(chosen.vendor_inr_per_month) : "not stated"}.
          </p>
          <label className="flex flex-col gap-1">
            <span className={FIELD_LABEL}>Agent (optional)</span>
            <select
              className={FIELD_INLINE}
              value={agentId}
              onChange={(event) => {
                setAgentId(event.target.value);
                setRequestKey(newRequestKey());
              }}
            >
              <option value={NO_AGENT}>None yet</option>
              {agents?.map((agent) => (
                <option key={agent.agent_id} value={agent.agent_id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>
        </ConfirmDialog>
      )}
    </div>
  );
}
