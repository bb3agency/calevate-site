"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { HAIRLINE_LIST, MetricRow, StatusPill } from "@/components/admin/kit";
import { EmptyState } from "@/components/console/emptyState";
import { Metric } from "@/components/console/metric";
import { Section, TEXT_ACTION } from "@/components/console/section";
import {
  ProblemNotice,
  Skeleton,
  StatusBadge,
  formatCount,
  formatDuration,
  formatINR,
  formatIST,
} from "@/components/ui";
import { useTenantHealth, viewAsSession, type TenantSummary } from "@/lib/api/admin";
import {
  causeCta,
  causeHref,
  causeLabel,
  severityTone,
  signalCopy,
  signalCount,
  type HealthSignal,
} from "@/lib/api/clientHealth";
import { useLineIncidents } from "@/lib/api/healer";
import { useCalls } from "@/lib/api/hooks";
import { viewAsHref } from "@/lib/api/session";
import { useWallet } from "@/lib/api/wallet";

/** How many of the client's calls the summary lists. */
const RECENT_CALLS = 5;

/**
 * THE TOP OF A CLIENT'S PAGE (founder, 10 Oct 2026): is this account working, what is
 * wrong with it now, how long its credit lasts, its last few calls, and the three things an
 * operator most often does next.
 *
 * Every figure is the server's own:
 * - what is wrong is `GET /v1/admin/client-health/{id}` — the board's judgement for this
 *   one account, so the two screens cannot disagree — plus the open line incidents the
 *   auto-healer recorded (`/v1/healer/incidents`) and a low or empty wallet;
 * - credit is minutes first, rupees second, from the directory row and the client's own
 *   wallet read (its runway in days);
 * - the calls are the client's own call list, read through the view-as session like every
 *   other client-scoped read on this page (D-22).
 *
 * The holds and the account state keep their own banners above this block: their wording
 * is the gate's and is not repeated here.
 *
 * The quick actions are LINKS to the screens that act, so each keeps its own confirmation
 * and step-up: pausing goes to Account state, adding credit to Credits, viewing as the
 * client to the logged view-as session.
 */
export function HealthSummary({ tenant }: { tenant: TenantSummary }) {
  const health = useTenantHealth(tenant.id);
  const session = viewAsSession(tenant.slug);
  const wallet = useWallet(session);
  const incidents = useLineIncidents(session);
  const calls = useCalls(session, { limit: RECENT_CALLS });

  const prepaid = tenant.plan_tier !== "managed";
  const lowCredit = prepaid && wallet.data?.is_low === true;
  const outboundStopped = prepaid && wallet.data?.outbound_stopped === true;
  // Each count only from a read that ARRIVED (§52): an unanswered or failed read is not
  // "no incidents" and not "no failed calls", so it can never produce "nothing is wrong".
  const openIncidents = incidents.data === undefined ? null : incidents.data.open;
  const failedCalls =
    calls.data === undefined ? null : calls.data.filter((call) => call.status === "failed").length;
  const signals = health.data === undefined ? [] : health.data.signals;
  const nothingWrong =
    health.data !== undefined &&
    signals.length === 0 &&
    !lowCredit &&
    openIncidents === 0 &&
    failedCalls === 0;

  return (
    <div className="space-y-10">
      <Section
        title="What is wrong now"
        info="The same judgement as the Client health board, for this account only, plus line problems the auto-healer recorded and the state of the wallet."
      >
        {health.isLoading ? (
          <Skeleton rows={2} />
        ) : health.error || !health.data ? (
          /* Never "nothing is wrong" from a read that did not arrive. */
          <ProblemNotice
            error={health.error ?? new Error("This account's health could not be read.")}
            onRetry={() => void health.refetch()}
          />
        ) : nothingWrong ? (
          <p className="flex items-center gap-2 text-body text-ink">
            <span aria-hidden className="h-2 w-2 rounded-full bg-brand" />
            Nothing is wrong with this account right now.
          </p>
        ) : (
          <ul aria-label="What is wrong now" className={HAIRLINE_LIST}>
            {signals.map((signal) => (
              <SignalRow key={signal.rule} signal={signal} tenant={tenant} />
            ))}
            {lowCredit && (
              <ProblemRow
                tone={outboundStopped ? "stop" : "warn"}
                label={outboundStopped ? "Credit used up" : "Credit is low"}
                detail={
                  outboundStopped
                    ? "Outgoing calls are refused and incoming calls get an apology until credit is added."
                    : "Below the low-balance line. Calls stop when it reaches zero."
                }
                href={`/admin/tenants/${tenant.id}/credits`}
                cta="Record a payment"
              />
            )}
            {incidents.isError && (
              <ProblemRow
                tone="warn"
                label="Line problems could not be read"
                detail="So this summary cannot say whether the auto-healer has recorded any."
                href="/admin/ops/healer"
                cta="Open the auto-healer"
              />
            )}
            {openIncidents !== null && openIncidents > 0 && (
              <ProblemRow
                tone="warn"
                label={openIncidents === 1 ? "1 line problem open" : `${formatCount(openIncidents)} line problems open`}
                detail="Recorded by the auto-healer in the last 30 days."
                href="/admin/ops/healer"
                cta="Open the auto-healer"
              />
            )}
            {failedCalls !== null && failedCalls > 0 && (
              <ProblemRow
                tone="warn"
                label={`${failedCalls} of the last ${calls.data?.length ?? RECENT_CALLS} calls failed`}
                detail="See the calls below; open one as the client for its detail."
                href={viewAsHref(tenant.slug, "/calls")}
                cta="Open calls as the client (logged)"
              />
            )}
          </ul>
        )}
      </Section>

      <div className="space-y-4">
        <h2 className="sr-only">Credit and activity</h2>
        <MetricRow>
          {/* Minutes first, as a figure; the other quality, the rupees and the runway under
              it. The full pair at figure size wrapped into three lines. */}
          <Metric
            label="Credit left"
            value={creditFigure(tenant)}
            hint={creditHint(tenant, prepaid && wallet.data?.runway.days != null ? wallet.data.runway.days : null)}
          />
          <Metric label="Calls (7d)" value={formatCount(tenant.calls_7d)} />
          <Metric
            label="Live agents"
            value={formatCount(tenant.live_agents)}
            hint={
              <Link href={`/admin/tenants/${tenant.id}/agents`} className={TEXT_ACTION}>
                Open agents
              </Link>
            }
          />
          <Metric label="Last call" value={formatIST(tenant.last_call_at)} />
        </MetricRow>
      </div>

      <Section
        title="Last calls"
        action={
          <a href={viewAsHref(tenant.slug, "/calls")} className={TEXT_ACTION}>
            All calls (logged)
          </a>
        }
      >
        {calls.isLoading ? (
          <Skeleton rows={3} />
        ) : calls.error || !calls.data ? (
          <ProblemNotice
            error={calls.error ?? new Error("This client's calls could not be read.")}
            onRetry={() => void calls.refetch()}
          />
        ) : calls.data.length === 0 ? (
          <EmptyState message="No calls yet." />
        ) : (
          <ul aria-label="Last calls" className={HAIRLINE_LIST}>
            {calls.data.slice(0, RECENT_CALLS).map((call) => (
              // Hard rule 6 in spirit: the caller's number is not needed to judge whether
              // the account works, so it is not on this summary.
              <li
                key={call.id}
                className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 py-2.5 sm:px-2"
              >
                <span className="min-w-0 text-body text-ink">
                  {call.agent_name ?? "Agent"}{" "}
                  <span className="text-meta text-ink-muted">
                    · {call.direction === "inbound" ? "incoming" : "outgoing"} · {formatDuration(call.duration_s)}
                  </span>
                </span>
                <span className="flex items-center gap-3 text-meta text-ink-muted">
                  <StatusBadge value={call.status} kind="call" />
                  {formatIST(call.started_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Quick actions" description="Each opens the screen that does it, with its own confirmation.">
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <a href={viewAsHref(tenant.slug)} className={TEXT_ACTION}>
            View as client (logged)
            <ArrowRight aria-hidden className="h-3.5 w-3.5" />
          </a>
          {prepaid && (
            <Link href={`/admin/tenants/${tenant.id}/credits`} className={TEXT_ACTION}>
              Record a payment
              <ArrowRight aria-hidden className="h-3.5 w-3.5" />
            </Link>
          )}
          <Link href={`/admin/tenants/${tenant.id}/lifecycle`} className={TEXT_ACTION}>
            {tenant.status === "suspended" ? "Reactivate the account" : "Pause the account"}
            <ArrowRight aria-hidden className="h-3.5 w-3.5" />
          </Link>
        </div>
      </Section>
    </div>
  );
}

/** The figure: the first voice quality's whole minutes, or the word for why there are none. */
function creditFigure(tenant: TenantSummary): string {
  if (tenant.plan_tier === "managed") return "Invoiced";
  const first = tenant.minutes_left?.[0];
  if (first) return `${formatCount(first.minutes)} min`;
  return tenant.credit_inr == null ? "—" : "On trial";
}

/** Under the figure: which quality it was, the other one, the balance and the runway. */
function creditHint(tenant: TenantSummary, runwayDays: number | null): string | undefined {
  if (tenant.plan_tier === "managed") return undefined;
  const [first, ...rest] = tenant.minutes_left ?? [];
  const parts = [
    first ? `${first.label}${rest.map((tier) => ` · ${tier.label} ${formatCount(tier.minutes)} min`).join("")}` : null,
    tenant.credit_inr == null ? null : formatINR(tenant.credit_inr),
    runwayDays == null ? null : `about ${formatCount(runwayDays)} days at the recent rate`,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : undefined;
}

function SignalRow({ signal, tenant }: { signal: HealthSignal; tenant: TenantSummary }) {
  const copy = signalCopy(signal.rule);
  const count = signalCount(signal);
  const detail = [count, copy?.meaning].filter(Boolean).join(". ");
  return (
    <li className="py-3 sm:px-2">
      <ProblemLine
        tone={severityTone(signal.severity)}
        // A signal this build cannot name still shows, as itself.
        label={copy?.label ?? signal.rule}
        detail={detail || "This console does not know this signal. The account is flagged by it all the same."}
        href={copy ? copy.screen(tenant.id, tenant.slug) : `/admin/tenants/${tenant.id}`}
        cta={copy?.cta ?? "Open the account"}
      />
      {signal.causes.length > 0 && (
        <ul className="mt-1.5 space-y-1 pl-1">
          {signal.causes.map((cause) => (
            <li key={cause} className="flex flex-wrap items-baseline gap-x-3 text-meta text-ink-muted">
              <span>{causeLabel(cause)}</span>
              <Link href={causeHref(cause, tenant.id)} className={TEXT_ACTION}>
                {causeCta(cause)}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function ProblemRow(props: Parameters<typeof ProblemLine>[0]) {
  return (
    <li className="py-3 sm:px-2">
      <ProblemLine {...props} />
    </li>
  );
}

function ProblemLine({
  tone,
  label,
  detail,
  href,
  cta,
}: {
  tone: "stop" | "warn" | "ok" | "neutral";
  label: string;
  detail: string;
  href: string;
  cta: string;
}) {
  const external = href.startsWith("http");
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-1.5">
      <div className="min-w-0 flex-1 basis-72">
        <p className="flex flex-wrap items-center gap-2 text-body font-medium text-ink">
          <StatusPill tone={tone}>{tone === "stop" ? "Broken now" : "Needs attention"}</StatusPill>
          {label}
        </p>
        <p className="mt-0.5 text-meta text-ink-muted">{detail}</p>
      </div>
      {external ? (
        <a href={href} className={TEXT_ACTION}>
          {cta}
          <ArrowRight aria-hidden className="h-3.5 w-3.5" />
        </a>
      ) : (
        <Link href={href} className={TEXT_ACTION}>
          {cta}
          <ArrowRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      )}
    </div>
  );
}
