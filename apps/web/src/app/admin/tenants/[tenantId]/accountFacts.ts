/**
 * The facts an operator asks the assistant about one client, from reads the admin console
 * already makes.
 *
 * "Are they KYC verified?", "have they taken the pledge?", "are they still on the trial?",
 * "why can they not dial?", "is their workspace ready?" — every one of those has an answer
 * on another section of this client's pages, and the overview's assistant could see none of
 * them, so it said it could not tell. Each read here is the one that section already makes
 * (same query key, so a page that has it loaded sends nothing new), and a read that failed
 * or is still loading is said to be so rather than reported as "no".
 *
 * NOTHING PERSONAL GOES OUT (hard rule 6): no owner name, no masked ID, no contact phone,
 * no business address. Status words, counts, rupee balances and the gates' own refusal
 * sentences only.
 */

import { useQuery } from "@tanstack/react-query";

import { formatINR } from "@/components/ui";
import { lookup } from "@/lib/lookup";

import { adminSession, viewAsSession, type TenantSummary } from "@/lib/api/admin";
import { useTenantReadiness, type TenantReadiness } from "@/lib/api/adminAccount";
import { apiRequest } from "@/lib/api/client";
import { useAdminBusinessProfile, type AdminBusinessProfile } from "@/lib/api/businessProfile";
import { useTenantWorkspace, type TenantWorkspace } from "@/lib/api/engineWorkspaces";
import { useAdminTenantKyc, type AdminKyc } from "@/lib/api/kycReview";
import { useOwnerStatus, type OwnerStatus } from "@/lib/api/onboarding";
import { trialKey, trialPath, type TrialStatus } from "@/lib/api/trials";
import { walletKey, type Wallet } from "@/lib/api/wallet";
import type { CopilotFact } from "@/lib/copilot/types";

/** One read's outcome: its data, or why there is none. */
type Read<T> = { data?: T; isError?: boolean };

export interface AccountReads {
  kyc: Read<AdminKyc>;
  readiness: Read<TenantReadiness>;
  workspace: Read<TenantWorkspace>;
  /** `null` data: the client has never had a trial. */
  trial: Read<TrialStatus | null>;
  wallet: Read<Wallet>;
  owner: Read<OwnerStatus>;
  profile: Read<AdminBusinessProfile>;
}

function unread(read: Read<unknown>): string {
  return read.isError ? "could not be read" : "still loading";
}

const KYC_WORDS: Record<string, string> = {
  verified: "verified",
  submitted: "submitted, waiting for review",
  in_review: "in review",
  rejected: "rejected",
  not_started: "not started",
};

export function kycFact(kyc: Read<AdminKyc>): string {
  const record = kyc.data;
  if (record === undefined) return unread(kyc);
  if (!record.recorded) return "not started";
  const status = lookup(KYC_WORDS, record.status) ?? record.status ?? "unknown";
  const path =
    record.kyc_path === "digilocker"
      ? "DigiLocker"
      : record.kyc_path === "manual"
        ? "document review"
        : null;
  const parts = [status];
  if (path) parts.push(`path: ${path}`);
  if (record.is_verified && record.verified_at) parts.push(`verified on ${record.verified_at.slice(0, 10)}`);
  if (record.digilocker_outstanding) parts.push("a DigiLocker check is still required");
  return parts.join("; ");
}

export function pledgeFact(kyc: Read<AdminKyc>): string {
  const record = kyc.data;
  if (record === undefined) return unread(kyc);
  if (record.pledge_accepted_version === null) return "not accepted";
  if (record.pledge_accepted_version !== record.pledge_current_version) {
    return "accepted an older version; the current one is not accepted yet";
  }
  return `accepted${record.pledge_accepted_at ? ` on ${record.pledge_accepted_at.slice(0, 10)}` : ""}`;
}

export function trialFact(trial: Read<TrialStatus | null>, wallet: Read<Wallet>): string {
  if (trial.data === undefined) return unread(trial);
  const paidIn = wallet.data === undefined ? null : Number(wallet.data.paid_inr) > 0;
  const paid = paidIn === null ? "" : paidIn ? "; has paid in" : "; no payment yet";
  if (trial.data === null) return `never had a trial${paid}`;
  const t = trial.data;
  if (t.active) {
    const left = t.days_remaining === null ? "" : `, ${t.days_remaining} ${t.days_remaining === 1 ? "day" : "days"} left`;
    const minutes =
      t.free_minutes === null ? "" : `, ${t.minutes_used} of ${t.free_minutes} free minutes used`;
    return `trial running${left}${minutes}${paid}`;
  }
  return `trial ${t.status}${t.ended_at ? ` on ${t.ended_at.slice(0, 10)}` : ""}${paid}`;
}

export function creditFact(tenant: TenantSummary, wallet: Read<Wallet>): string {
  if (tenant.plan_tier === "managed") return "invoiced account, no wallet";
  const w = wallet.data;
  if (w === undefined) return unread(wallet);
  const parts = [`balance ${formatINR(w.balance_inr)}`];
  if (w.trial?.test_calls_only) parts.push("trial: test calls only until the first payment");
  if (w.outbound_stopped) parts.push("outbound stopped for lack of credit");
  else if (w.is_low) parts.push("running low");
  return parts.join("; ");
}

export function workspaceFact(workspace: Read<TenantWorkspace>): string {
  const w = workspace.data;
  if (w === undefined) return unread(workspace);
  const status = w.status ?? "not provisioned";
  const parts = [status.replaceAll("_", " ")];
  if (w.last_error_code) parts.push(`last error: ${w.last_error_code}`);
  if (w.purchase_step && w.purchase_step !== "ready") {
    parts.push(`next step before buying a number: ${w.purchase_step.replaceAll("_", " ")}`);
  }
  return parts.join("; ");
}

export function numbersFact(workspace: Read<TenantWorkspace>): string {
  const counts = workspace.data?.numbers;
  if (workspace.data === undefined) return unread(workspace);
  if (!counts) return "none recorded";
  return `${counts.own_workspace} in their own workspace, ${counts.platform_held} held by Calevate`;
}

export function outboundFact(readiness: Read<TenantReadiness>): string {
  const r = readiness.data;
  if (r === undefined) return unread(readiness);
  if (r.may_operate) return "nothing at account level is blocking outbound calls";
  return r.rows
    .map((row) => `${row.title} (${row.rule}, ${row.actor}'s move): ${row.reason}`)
    .join(" | ");
}

/** The profile's go-live gaps in an operator's words (the server's copy is the client's). */
const PROFILE_GAPS: Record<string, string> = {
  business_hours_missing: "business profile has no opening hours",
  branch_missing: "business profile has no address",
  service_missing: "business profile has no services",
  escalation_contact_missing: "business profile has nobody to take handed-over calls",
};

/**
 * What still stands between this account and the end of onboarding, in the terms the
 * server uses to move it to `active` (`tenancy/onboarding.onboarding_finished`): an owner
 * has joined and the business profile has what an agent needs to go live. `[]` once both
 * hold; `null` while either read is missing.
 */
export function onboardingRemaining(
  owner: Read<OwnerStatus>,
  profile: Read<AdminBusinessProfile>,
): string[] | null {
  if (owner.data === undefined || profile.data === undefined) return null;
  const left: string[] = [];
  if (!owner.data.owner_present) {
    left.push(owner.data.invite_pending ? "owner has not accepted the invite" : "no owner invited");
  }
  for (const blocker of profile.data.blockers) {
    left.push(lookup(PROFILE_GAPS, blocker.code) ?? blocker.message.replace(/\.$/, ""));
  }
  return left;
}


export function lifecycleFact(tenant: TenantSummary, reads: AccountReads): string {
  if (tenant.status !== "onboarding") return tenant.status;
  const left = onboardingRemaining(reads.owner, reads.profile);
  if (left === null) return "onboarding";
  if (left.length === 0) {
    return "onboarding; setup is finished — it moves to active on the next business profile save, or an operator can set it active on the Account state page";
  }
  return `onboarding; still to do: ${left.join("; ")}`;
}

export function accountFacts(tenant: TenantSummary, reads: AccountReads): CopilotFact[] {
  return [
    { key: "lifecycle", label: "Account lifecycle", value: lifecycleFact(tenant, reads) },
    { key: "kyc", label: "Business verification (KYC)", value: kycFact(reads.kyc) },
    { key: "pledge", label: "No-cold-calls pledge", value: pledgeFact(reads.kyc) },
    { key: "trial", label: "Trial and payment", value: trialFact(reads.trial, reads.wallet) },
    { key: "credit", label: "Credit", value: creditFact(tenant, reads.wallet) },
    { key: "workspace", label: "Voice workspace", value: workspaceFact(reads.workspace) },
    { key: "numbers", label: "Phone numbers", value: numbersFact(reads.workspace) },
    {
      key: "outbound_blockers",
      label: "What blocks outbound calls (gate, whose move, reason)",
      value: outboundFact(reads.readiness),
    },
    {
      key: "inbound",
      label: "Inbound answering needs a live agent on a number; inbound is never gated by KYC",
      value: `${tenant.live_agents} live ${tenant.live_agents === 1 ? "agent" : "agents"}; numbers: ${numbersFact(reads.workspace)}`,
    },
  ];
}

/**
 * Every read `accountFacts` needs, each under the query key its own section uses. The
 * trial read is the credits page's (`TrialPanel`), asked on the admin session.
 */
export function useAccountReads(tenant: TenantSummary | undefined): AccountReads {
  const tenantId = tenant?.id ?? "";
  const slug = tenant?.slug ?? "";
  const kyc = useAdminTenantKyc(tenantId);
  const readiness = useTenantReadiness(tenantId);
  const workspace = useTenantWorkspace(tenantId);
  const trial = useQuery({
    queryKey: trialKey(tenantId),
    queryFn: () => apiRequest<TrialStatus | null>(adminSession(), trialPath(tenantId)),
    enabled: tenantId !== "",
  });
  const wallet = useQuery({
    queryKey: walletKey(slug),
    queryFn: () => apiRequest<Wallet>(viewAsSession(slug), "/v1/billing/wallet"),
    enabled: slug !== "",
  });
  const owner = useOwnerStatus(tenantId);
  const profile = useAdminBusinessProfile(tenantId);
  return { kyc, readiness, workspace, trial, wallet, owner, profile };
}
