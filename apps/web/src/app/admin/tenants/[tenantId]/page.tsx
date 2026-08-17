"use client";

import Link from "next/link";
import { use, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  BellOff,
  BellRing,
  BookOpenCheck,
  Bot,
  Eye,
  FileCheck2,
  Flag,
  Hash,
  IndianRupee,
  PhoneCall,
  Power,
  ReceiptIndianRupee,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Users,
  Wallet,
} from "lucide-react";

import {
  Card,
  EmptyState,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  StatTile,
  formatCount,
  formatINR,
  formatIST,
} from "@/components/ui";
import {
  useKbDecision,
  useKbPreview,
  useMargin,
  useProvisionNumber,
  useRecomputeSpendCap,
  useRecordDltRegistration,
  useRegisterTemplate,
  useSetNumberDltStatus,
  useSetTemplateStatus,
  useTenant,
  useTenantAgents,
  useTenantKbQueue,
  useTenantNumbers,
  useTenantTemplates,
  viewAsSession,
  type Margin,
  type PeStatus,
  type TmLinkStatus,
} from "@/lib/api/admin";
import { useCaps } from "@/lib/api/caps";
import { holdRule } from "@/lib/api/holds";
import { VIEW_AS_ADMIN, VIEW_AS_PARAM } from "@/lib/api/session";
import { useRecordTenantAlertOptIn, useTenantAlertOptIn } from "@/lib/api/whatsappAlerts";

import { useAdminAccess } from "@/app/admin/access";

/**
 * One client: health, the read-only view-as link, and the KB approval queue.
 *
 * The queue is READ through impersonation and DECIDED through the admin surface —
 * that split is D-22 ("no acting-as: mutations still go through admin surfaces"), and
 * it is why the buttons here post to `/v1/admin/tenants/.../kb/...` rather than to the
 * client-realm KB routes the queue was read from.
 *
 * ## What the design pass changed here beyond colour
 *
 * Every panel on this screen read its list as `data ?? []` and rendered the empty case
 * when the request FAILED, which on an operator console is the expensive direction: a
 * failed read of `/v1/campaigns/numbers` printed "No numbers provisioned", and the next
 * thing an operator does with that sentence is buy a second number for a client who
 * already has one. Loading is a `Skeleton`, a failure is a `ProblemNotice`, and "there
 * are none" is now a claim this screen only makes when the server made it.
 *
 * Every control that WRITES is gated on the permission its route requires
 * (`admin:tenants`, `apps/api/admin/routes.py`) and disabled with the reason beside it —
 * see `@/app/admin/access` for why the client realm's `useWriteAccess` cannot be used
 * here, and where the permission set is read from (`GET /v1/admin/me`).
 *
 * The `<h1>` stays: unlike the client shell, `admin/layout.tsx` prints no page title, so
 * removing it would leave the screen unnamed. If a title lands in the shell, this is the
 * copy to delete.
 */
export default function TenantDetailPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  // One request for one client — the list endpoint is N+1 by design (it counts calls
  // and leads per tenant under each tenant's own RLS), so fetching all of it to find
  // one row made a detail page cost the whole directory.
  const tenantQuery = useTenant(tenantId);
  const tenant = tenantQuery.data;
  const slug = tenant?.slug ?? "";

  const queue = useTenantKbQueue(slug);
  // Approved-but-unpublished is its own queue: approving does NOT push to the engine
  // (kb_service.approve_source only moves the status), so without this list the
  // publish endpoint has no caller and the client's Knowledge screen sits on
  // "Approved, not live yet" forever.
  const publishQueue = useTenantKbQueue(slug, "approved");
  // Publishing leaves `status` at 'approved' and flips `is_active`, so the live ones
  // stay in this list — filter them out rather than offer a second Publish button.
  const awaitingPublish = (publishQueue.data ?? []).filter((source) => !source.is_active);
  const [selected, setSelected] = useState<string | null>(null);
  const preview = useKbPreview(slug, selected);
  const decide = useKbDecision(tenantId);
  const kbWrite = useAdminAccess("admin:tenants", "decide on this client's knowledge");

  if (tenantQuery.isLoading) return <Skeleton rows={6} />;
  // A 403, a 500 or a dropped connection is not "no such client" — saying so sends
  // an operator hunting for a deleted tenant that is sitting right there.
  if (tenantQuery.error)
    return <ProblemNotice error={tenantQuery.error} onRetry={() => tenantQuery.refetch()} />;
  if (!tenant) return <EmptyState title="Client not found" />;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link
            href="/admin"
            className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Clients
          </Link>
          <h1 className="mt-1 text-xl font-semibold text-ink">{tenant.name}</h1>
          <p className="text-sm text-ink-muted">
            /c/{tenant.slug} · {tenant.status} · {tenant.vertical_template ?? "no template"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {/* The telecom gate in front of everything below: no verification, no number
              on any tier, and no outbound dialling at all on a self-serve account. It
              gets its own screen rather than a panel here because it is an audited
              write with four fields an auditor will ask about, and because the current
              record has to be read from the tenant's own view of it. */}
          <NavLink href={`/admin/tenants/${tenantId}/kyc`} icon={<ShieldCheck className="h-4 w-4" />}>
            Identity (KYC)
          </NavLink>
          {/* The other human-decision gate, and the only one that had no screen at all:
              `POST .../first-campaign-review` was reachable by curl and nothing else. It
              is a sibling of KYC rather than a panel here for the same reasons — an
              audited compliance decision with a note an auditor will read, over a state
              that has to be read from the tenant's own view of it. */}
          <NavLink
            href={`/admin/tenants/${tenantId}/first-campaign-review`}
            icon={<FileCheck2 className="h-4 w-4" />}
          >
            Campaign review
          </NavLink>
          <NavLink
            href={`/admin/tenants/${tenantId}/invoice`}
            icon={<ReceiptIndianRupee className="h-4 w-4" />}
          >
            Invoice
          </NavLink>
          {/* What the invoice above is DERIVED FROM. `plans` had no writer at all until
              this screen landed, so every number on the invoice rested on a row somebody
              had inserted by hand. Its own screen because a plan change is an audited,
              dated agreement with a history an operator has to be able to read. */}
          <NavLink
            href={`/admin/tenants/${tenantId}/commercials`}
            icon={<IndianRupee className="h-4 w-4" />}
          >
            Commercials
          </NavLink>
          {/* The wallet the commercial terms are drawn down against, and the ONLY path
              money takes INTO an account. Its own screen because the ledger has to be
              visible before the write — a blind form over an append-only ledger is how a
              double credit happens — and because nothing on it can be undone. */}
          <NavLink
            href={`/admin/tenants/${tenantId}/credits`}
            icon={<Wallet className="h-4 w-4" />}
          >
            Credits
          </NavLink>
          {/* Beta features and debug views, per client (SURFACES §1). Its own screen
              rather than a panel here because each flag needs three facts beside it — the
              platform default, this client's override, and the resolved answer — and a
              row that showed only the last one would read as a switch nobody set. */}
          <NavLink
            href={`/admin/tenants/${tenantId}/feature-flags`}
            icon={<Flag className="h-4 w-4" />}
          >
            Feature flags
          </NavLink>
          {/* Suspend / reactivate / close. Separate from everything above because it is
              the one control here that stops a client's outbound dialling outright. */}
          <NavLink
            href={`/admin/tenants/${tenantId}/lifecycle`}
            icon={<Power className="h-4 w-4" />}
          >
            Account state
          </NavLink>
          {/* `?view=admin` tells the client-realm shell to build the IMPERSONATING
              session (admin token + X-Impersonate-Org) instead of a client one — see
              lib/api/session.tsx. Without it the link handed over a client token the
              operator does not have, so `me.impersonating` was always false and the
              read-only banner never appeared. The marker selects a credential; it
              grants nothing, and the API verifies the admin identity regardless.

              "read-only" is now IN THE LABEL rather than only in a `title` a mouse has
              to find and a keyboard never will. D-22 is the promise this link makes, and
              a promise that only appears on hover is not one the operator has read. */}
          <NavLink
            href={`/c/${tenant.slug}?${VIEW_AS_PARAM}=${VIEW_AS_ADMIN}`}
            icon={<Eye className="h-4 w-4" />}
            title="Read-only (D-22). Every page view is audit-logged."
          >
            View as client (read-only)
          </NavLink>
        </div>
      </div>

      <HoldsBanner tenantId={tenantId} holds={tenant.holds} />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Live agents"
          value={formatCount(tenant.live_agents)}
          icon={<Bot className="h-5 w-5" />}
        />
        <StatTile
          label="Calls (7d)"
          value={formatCount(tenant.calls_7d)}
          icon={<PhoneCall className="h-5 w-5" />}
        />
        <StatTile label="Leads" value={formatCount(tenant.leads)} icon={<Users className="h-5 w-5" />} />
        <StatTile
          label="Last call"
          value={formatIST(tenant.last_call_at)}
          icon={<Sparkles className="h-5 w-5" />}
        />
      </div>

      {decide.error && <ProblemNotice error={decide.error} />}

      <Card title="Knowledge awaiting approval">
        <RestrictionNote reason={kbWrite.reason} />
        {queue.error ? (
          /* Never an empty queue on a failed read: "nothing is waiting" is a claim about
             this client's work, and an expired token is not evidence for it. */
          <ProblemNotice error={queue.error} onRetry={() => queue.refetch()} />
        ) : queue.isLoading ? (
          <Skeleton rows={3} />
        ) : queue.data?.length ? (
          <ul className="space-y-2">
            {queue.data.map((source) => (
              <li key={source.id} className="rounded-card border border-line p-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-ink">
                      {source.name} <span className="text-xs text-ink-faint">v{source.version}</span>
                    </p>
                    <p className="text-xs text-ink-muted">
                      {source.chunks} chunks · {source.kind}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {/* Preview is a READ and stays available to anyone who reached this
                        screen — refusing to show what is queued would make an operator
                        without the decision permission unable to even brief the one who
                        has it. */}
                    <SecondaryButton
                      onClick={() => setSelected(selected === source.id ? null : source.id)}
                    >
                      {selected === source.id ? "Hide" : "Preview"}
                    </SecondaryButton>
                    <PrimaryButton
                      disabled={decide.isPending || !kbWrite.allowed}
                      onClick={() => decide.mutate({ sourceId: source.id, decision: "approve" })}
                    >
                      Approve
                    </PrimaryButton>
                    <DangerButton
                      disabled={decide.isPending || !kbWrite.allowed}
                      onClick={() =>
                        decide.mutate({
                          sourceId: source.id,
                          decision: "reject",
                          reason: "Not suitable for the agent",
                        })
                      }
                    >
                      Reject
                    </DangerButton>
                  </div>
                </div>
                {selected === source.id && (
                  <div className="mt-3 space-y-2">
                    {preview.error ? (
                      <ProblemNotice error={preview.error} onRetry={() => preview.refetch()} />
                    ) : preview.isLoading ? (
                      <Skeleton rows={2} />
                    ) : !preview.data ? (
                      /* A paused query (offline) is neither loading nor failed, and
                         `?? []` below would have shown an operator an EMPTY source and
                         invited them to approve it on that evidence. */
                      <ProblemNotice
                        error={new Error("The preview did not load.")}
                        onRetry={() => preview.refetch()}
                      />
                    ) : (
                      /* Chunk-by-chunk is how it is reviewed because chunk-by-chunk is
                         how it will be retrieved and read aloud. */
                      preview.data.map((chunk) => (
                        <div key={chunk.idx} className="rounded-md bg-app p-2 text-xs text-ink-muted">
                          <span className="mr-2 text-ink-faint">#{chunk.idx}</span>
                          {chunk.content}
                          <span className="ml-2 text-ink-faint">({chunk.chars} chars)</span>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="Nothing awaiting approval"
            hint="Approved sources still need publishing before the agent knows them."
          />
        )}
      </Card>

      {/* Approve moves a source to `approved`; publishing is the separate step that
          pushes it to the engine and makes it the live version (FLOWS §7). Both are
          ours, so both need a button — an approved source with nowhere to press is
          work that silently stops halfway.
          The whole panel used to vanish on a failed read of the approved list, which is
          the same silence as an empty one: a source stuck at "Approved, not live yet"
          on the client's screen and nothing here to explain why.
          §52's OTHER clause was still open here, and it is the same sentence drawn a
          third way: while the approved list is IN FLIGHT, `awaitingPublish` is `[]` — the
          `?? []` above cannot tell "not answered yet" from "the server says none" — so
          the panel rendered `null` and an operator's first paint of this screen said
          "nothing is waiting to be published" about a request that had not come back.
          The §52 guard (apps/web/tests/surfaceStatesGuard.test.ts) deliberately does not
          scan a `?? []` outside a JSX child, because whether it reaches a pixel is a
          question about branch dominance; this was the branch that let it through.
          Loading is a skeleton. An empty list, once the server has said so, is still
          nothing — the approval card above already carries the sentence that explains
          what publishing is for. */}
      {publishQueue.isLoading ? (
        <Card title="Approved, awaiting publish">
          <Skeleton rows={2} />
        </Card>
      ) : publishQueue.error || !publishQueue.data ? (
        /* `|| !publishQueue.data` closes the same hole one state further out. The comment
           above names "in flight" and "failed"; a query TanStack has PAUSED because the
           browser is offline is neither — `isLoading === false`, `error === null` — so
           `awaitingPublish` was `[]` and the panel rendered `null`, which on this screen
           reads as "nothing is waiting to be published". */
        <Card title="Approved, awaiting publish">
          <ProblemNotice
            error={publishQueue.error ?? new Error("The publish queue did not load.")}
            onRetry={() => publishQueue.refetch()}
          />
        </Card>
      ) : awaitingPublish.length > 0 ? (
        <Card title="Approved, awaiting publish" bodyClassName="px-4 pb-4 sm:px-6">
          <p className="pt-2 text-xs text-ink-muted">
            The agent does not know these until they are published.
          </p>
          <RestrictionNote reason={kbWrite.reason} />
          <ul className="divide-y divide-line">
            {awaitingPublish.map((source) => (
              <li key={source.id} className="flex flex-wrap items-center gap-2 py-2.5 text-sm">
                <span className="font-medium text-ink">{source.name}</span>
                <span className="text-xs text-ink-muted">
                  v{source.version} · {source.chunks} chunks
                </span>
                <span className="ml-auto">
                  <PrimaryButton
                    disabled={decide.isPending || !kbWrite.allowed}
                    onClick={() => decide.mutate({ sourceId: source.id, decision: "publish" })}
                  >
                    Publish
                  </PrimaryButton>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <AgentsPanel tenantId={tenantId} slug={slug} />

      <MarginPanel tenantId={tenantId} />

      {/* Beside the margin because both are this client's money, and on THIS screen
          rather than on /admin/ops because the route names a tenant in its path and binds
          its step-up confirmation to that tenant id — see the panel. */}
      <SpendCapPanel tenantId={tenantId} slug={slug} directoryCapped={tenant.capped} />

      <CampaignSetup tenantId={tenantId} slug={slug} />

      {/* On THIS screen for `SpendCapPanel`'s reason: the route names a tenant in its
          path and the subject is that tenant's owner. The client's own version of this
          control is `/c/[slug]/settings/alerts` — this one exists for the opt-in that was
          given on an onboarding call rather than on a screen. */}
      <WhatsAppAlertsPanel tenantId={tenantId} />
    </div>
  );
}

/** The screen-to-screen affordances in the header, in one shape rather than four. */
function NavLink({
  href,
  icon,
  title,
  children,
}: {
  href: string;
  icon: React.ReactNode;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      title={title}
      className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink hover:bg-black/5 dark:hover:bg-white/5"
    >
      {icon}
      {children}
    </Link>
  );
}

const BUTTON_BASE =
  "rounded-md px-2.5 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50";

function PrimaryButton({
  children,
  disabled,
  onClick,
  type = "button",
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type === "submit" ? "submit" : "button"}
      disabled={disabled}
      onClick={onClick}
      className={`${BUTTON_BASE} bg-brand-strong text-white hover:bg-brand`}
    >
      {children}
    </button>
  );
}

function SecondaryButton({
  children,
  disabled,
  onClick,
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`${BUTTON_BASE} border border-line bg-surface text-ink hover:bg-black/5 dark:hover:bg-white/5`}
    >
      {children}
    </button>
  );
}

function DangerButton({
  children,
  disabled,
  onClick,
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`${BUTTON_BASE} border border-rose-300 text-rose-700 hover:bg-rose-50 dark:border-rose-900 dark:text-rose-300 dark:hover:bg-rose-950`}
    >
      {children}
    </button>
  );
}

/*
 * `min-w-0` because every one of these sits in a `flex flex-wrap` row. A flex item
 * defaults to `min-width: auto` and so refuses to shrink below its own min-content, and a
 * `<select>` s min-content is its LONGEST OPTION — "not_started — no application filed"
 * here, which is wider than a 320px phone. Wrapping does not save it: once wrapped the
 * item is alone on its line and still will not shrink. Measured at 320px this row reached
 * x=395 in a 320px viewport, inside the shell s `overflow-hidden`, so the control was
 * clipped off-screen rather than scrollable.
 */
const FIELD =
  "min-w-0 rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink placeholder:text-ink-faint disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11";

/**
 * What is holding this account, at the top of its own page.
 *
 * `TenantSummary.holds` is `read_tenant_holds` — the blockers themselves — so this says
 * the same thing as the work list and as the client's refusal, in the same vocabulary. It
 * is here because the panels below (numbers, templates, registrations) all read as "this
 * client is nearly ready", and an account whose dialling is refused outright should not
 * have to be inferred from a screen full of green.
 *
 * Renders nothing when nothing holds them: an operator opening a healthy account should
 * not be shown a box saying so.
 */
function HoldsBanner({ tenantId, holds }: { tenantId: string; holds: string[] }) {
  if (holds.length === 0) return null;
  return (
    <NoticeBox
      tone="warn"
      icon={<AlertTriangle className="h-5 w-5" />}
      title="This account is waiting on us."
    >
      <ul className="mt-2 space-y-2 text-xs">
        {holds.map((rule) => {
          const copy = holdRule(rule);
          return (
            <li key={rule} className="flex flex-wrap items-baseline gap-2">
              <span className="font-medium">{copy?.label ?? rule}</span>
              <span className="opacity-80">
                {copy?.blocks ??
                  "This console does not recognise this rule; the gate that emitted it does."}
              </span>
              {copy && (
                <Link href={copy.screen(tenantId)} className="font-medium underline">
                  {copy.cta}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </NoticeBox>
  );
}

/** The tenant's agents, each linking to its prompt history, the Apply/Undo controls
 * and the call cap — the entry point those screens need, since a prompt belongs to an
 * agent, not to the tenant.
 *
 * It used to `return null` on anything but a populated list, so a failed read and a
 * client with no agents were the same blank space — and "this client has no agents" is
 * the more alarming of the two to be wrong about. */
function AgentsPanel({ tenantId, slug }: { tenantId: string; slug: string }) {
  const agents = useTenantAgents(slug);
  return (
    <Card title="Agents" bodyClassName="px-4 pb-4 pt-2 sm:px-6">
      {agents.error ? (
        <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />
      ) : agents.isLoading || !agents.data ? (
        <Skeleton rows={2} />
      ) : agents.data.length === 0 ? (
        <EmptyState
          title="No agents yet"
          hint="Nothing answers or dials for this client until one is built."
        />
      ) : (
        <ul className="divide-y divide-line">
          {agents.data.map((agent) => (
            <li key={agent.id} className="flex flex-wrap items-center gap-2 py-2.5 text-sm">
              <span className="font-medium text-ink">{agent.name}</span>
              <span className="rounded bg-brand-soft px-1.5 py-0.5 text-xs font-medium text-brand-strong">
                {agent.status}
              </span>
              <span className="text-xs text-ink-muted">{agent.direction}</span>
              <Link
                href={`/admin/tenants/${tenantId}/agents/${agent.id}/prompt`}
                className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-0.5 text-xs font-medium text-ink hover:bg-black/5 dark:hover:bg-white/5"
              >
                <ScrollText className="h-3.5 w-3.5" />
                Prompt &amp; publishing
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/**
 * Per-client margin (D-12), the number gate G2 turns on.
 *
 * It lives in the ADMIN console and nowhere else: `unit_cost_paid` is our supplier
 * pricing, and a client who can see it is a client negotiating against it. Their own
 * usage panel shows what they used and what it costs them, which is the half that is
 * theirs.
 *
 * MONEY: `revenue_inr` / `cost_inr` / `margin_inr` are exact decimal STRINGS and go
 * through `formatINR`, which formats the digits and never parses them. They used to be
 * interpolated raw as `₹{string}`, which printed `₹1015900.00` — ungrouped, and a
 * server-sent `1015900.0` would have printed a single paise digit. These are TOTALS, so
 * two decimals is what they mean; the rate on the invoice is the one figure that must
 * NOT be rounded like a rupee, and it is not shown here.
 */
function MarginPanel({ tenantId }: { tenantId: string }) {
  const margin = useMargin(tenantId);
  if (margin.error) return <ProblemNotice error={margin.error} onRetry={() => margin.refetch()} />;
  if (!margin.data)
    return (
      <Card title="Margin">
        <Skeleton rows={2} />
      </Card>
    );
  const data = margin.data;
  const negative = data.margin_inr.trim().startsWith("-");

  return (
    <Card title={`Margin · ${data.month}`}>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Revenue" value={formatINR(data.revenue_inr)} />
        <StatTile label="Our cost" value={formatINR(data.cost_inr)} />
        <div className="rounded-card border border-line bg-surface p-5">
          <p className="text-[13px] font-medium text-ink-muted">Margin</p>
          <p
            className={
              negative
                ? "mt-1 text-2xl font-bold tracking-tight tabular-nums text-rose-600 dark:text-rose-400"
                : "mt-1 text-2xl font-bold tracking-tight tabular-nums text-brand-strong dark:text-brand-bright"
            }
          >
            {formatINR(data.margin_inr)}
          </p>
        </div>
        {/* null, not 0%: "nothing billed yet" and "we made nothing" are different
            facts, and an operator acts differently on each. */}
        <StatTile
          label="Margin %"
          value={data.margin_pct === null ? "not billed yet" : `${data.margin_pct}%`}
        />
      </div>
      <p className="mt-3 text-xs text-ink-muted">
        {data.minutes_used} minutes across {formatCount(data.calls)} calls. Cost is what we
        actually paid, stamped per usage row at capture time with the fx rate used.
      </p>
      <TierSplit tiers={data.tiers} />
    </Card>
  );
}

/**
 * What the margin's cost side is MADE of, by TTS rung (D-36).
 *
 * A thin margin is not actionable on its own — the operator's next move differs
 * completely depending on whether the cost is premium voice (move the client to the
 * value rung, or reprice) or the value rung already (the plan is underpriced). The
 * server nests these under `tiers` on the same read, so this costs no round trip.
 *
 * The three costs are a PARTITION of `cost_inr` above and add up to it exactly — both
 * come from `_tier_totals`. Nothing is recomputed here: adding the strings client-side
 * would be float arithmetic on money (hard rule 7), and the total is already on the card.
 *
 * `unattributed` is shown even at zero. It is the count of minutes we could not prove a
 * rung for, and hiding it when empty would make its later appearance look like a new
 * feature rather than a metering gap — an operator who has never seen the row will not
 * know to ask what it means.
 */
function TierSplit({ tiers }: { tiers: Margin["tiers"] }) {
  const rungs = [
    { label: "Premium (v3)", minutes: tiers.minutes_premium, cost: tiers.cost_premium_inr },
    { label: "Value (v2)", minutes: tiers.minutes_value, cost: tiers.cost_value_inr },
    {
      label: "Unattributed",
      minutes: tiers.minutes_unattributed,
      cost: tiers.cost_unattributed_inr,
    },
  ];
  return (
    <div className="mt-4 border-t border-line pt-3">
      {/* h3, not h4: this panel sits inside a `Card`, whose title is an <h2>, so an h4
          skips a level. Pre-existing and previously invisible to the axe sweep — jsdom
          implements no `matchMedia`, and without it axe cannot resolve media-query
          visibility, so it was not evaluating this heading at all. The stub added in
          tests/setup.ts for the marketing page's reduced-motion check made the sweep
          able to see it. Size is carried by the class, so nothing moves on screen. */}
      <h3 className="text-[13px] font-medium text-ink-muted">Cost by TTS rung</h3>
      <dl className="mt-2 grid gap-3 sm:grid-cols-3">
        {rungs.map((rung) => (
          <div key={rung.label} className="rounded-card border border-line bg-surface px-4 py-3">
            <dt className="text-xs text-ink-muted">{rung.label}</dt>
            <dd className="mt-0.5 text-sm font-semibold tabular-nums">{formatINR(rung.cost)}</dd>
            <dd className="text-xs tabular-nums text-ink-muted">{rung.minutes} min</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/**
 * The spend cap that is stopping this client's outbound dialling, and the one control
 * that clears it — `POST /v1/ops/tenants/{id}/spend-cap/recompute`.
 *
 * ## Why this lives here and not on /admin/ops
 *
 * It was the fourth operator endpoint with no path in the console, and the only one on
 * that list that names a TENANT: the route puts the tenant in its path and binds its
 * step-up confirmation to that tenant id, precisely so a header captured for one client
 * cannot be replayed against another (`spend_cap_confirmation`, `ops/routes.py`). Putting
 * it on the platform screen would mean a picker — a uuid or a dropdown, with no client's
 * name, no ceiling and no counters beside it, which is `runbooks/calls-stopped.md` §2's
 * curl in a nicer font and with the same failure available: the right button pressed for
 * the wrong client. Here, the operator is already looking at the account they mean, at
 * the ceilings that decide the answer, having arrived from the directory row badged
 * "capped" or from the runbook, which now names this screen.
 *
 * ## Where the flag is read from, which is not the obvious place
 *
 * `TenantSummary.capped` is already in hand on this screen and is NOT the state this
 * control moves. It is `SELECT capped FROM spend_state LIMIT 1` with no month predicate
 * (`admin/service.py`), while the compliance gate asks `spend_capped()`, which treats a
 * row stamped with a CLOSED month as no cap at all. So a tenant capped in July shows
 * `capped: true` on the directory in August while nothing is actually refusing their
 * dials. `CapsOut.capped` comes from `read_spend_counters`, which applies the same month
 * test as the gate — so that is the flag rendered here, and the directory's is reported
 * as the disagreement it is when the two differ.
 *
 * Read through impersonation (`billing:read`, non-mutating, so D-22 allows it and there
 * is no admin-realm twin of this read), WRITTEN through the admin surface with the tenant
 * in the path — the same split as KYC and the first-campaign hold.
 *
 * ## No cap state, no control
 *
 * A failed caps read renders the failure and NOTHING ELSE. The ops screen's rule, applied
 * where it belongs: this button's whole subject is a flag, and a screen that offered it
 * over an unreadable one would let an operator "release" a client who was never capped
 * and report success to them.
 */
function SpendCapPanel({
  tenantId,
  slug,
  directoryCapped,
}: {
  tenantId: string;
  slug: string;
  directoryCapped: boolean;
}) {
  const caps = useCaps(viewAsSession(slug));
  const recompute = useRecomputeSpendCap(tenantId);
  // `ops:manage`, not `admin:tenants` — this is the one control on this screen whose route
  // lives under `/v1/ops`, and only `superadmin` holds it (core/rbac.py). Gating it with
  // the panel's neighbours would offer an `operator` a button whose only outcome is a 403.
  const write = useAdminAccess("ops:manage", "recompute a client's spend cap");
  const [confirm, setConfirm] = useState("");

  const data = caps.data;
  const ready = confirm === "RECOMPUTE";

  return (
    <Card title="Spend cap">
      {caps.error ? (
        <>
          <p className="mb-3 text-sm text-ink-muted">
            The cap state could not be read, so nothing is offered here. Recomputing a flag
            whose current value we do not know could report a client released who was never
            capped.
          </p>
          <ProblemNotice error={caps.error} onRetry={() => caps.refetch()} />
        </>
      ) : caps.isLoading || !data ? (
        <Skeleton rows={3} />
      ) : (
        <div className="space-y-4">
          <NoticeBox
            tone={data.capped ? "stop" : "ok"}
            icon={
              data.capped ? (
                <AlertTriangle className="h-5 w-5" />
              ) : (
                <ShieldCheck className="h-5 w-5" />
              )
            }
            title={
              data.capped
                ? "Outbound calling is STOPPED for this client by the spend cap"
                : "Not capped — the spend cap is not stopping this client"
            }
          >
            <p className="mt-1 text-xs">
              {data.capped
                ? "Every outbound dial is refused with rule spend_cap. Inbound calls are unaffected — their receptionist keeps answering."
                : "Their dialling is not refused on this rule. Any other blocker on this account is listed above."}
            </p>
            {/* The two flags come from different predicates and CAN disagree; when they
                do, the reason is almost always a row still stamped with a closed billing
                month. Saying so turns a confusing screen into a diagnosis. */}
            {directoryCapped !== data.capped && (
              <p className="mt-2 text-xs">
                The client directory shows this account as{" "}
                {directoryCapped ? "capped" : "not capped"}, which disagrees. That badge
                reads the flag without checking its billing month; this one applies the
                same month test the compliance gate does. A row left over from a closed
                month is the usual cause, and the recompute below writes nothing for it.
              </p>
            )}
          </NoticeBox>

          {/* MONEY AS STRINGS. Every rupee field here is an exact decimal the API sent as
              text (hard rule 7); `formatINR` groups the digits and never parses them. */}
          <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <CapFact
              label={`Spent · ${data.month}`}
              value={formatINR(data.spend_used_inr)}
              note={`${data.minutes_used} minutes`}
            />
            <CapFact
              label="Ceiling in force"
              value={formatINR(data.effective_cap_spend_inr)}
              note={
                data.effective_cap_minutes === null
                  ? "no minute ceiling"
                  : `${formatCount(data.effective_cap_minutes)} minutes`
              }
            />
            <CapFact
              label="Our ceiling (the plan's)"
              value={formatINR(data.plan_cap_spend_inr)}
              note={
                data.plan_cap_minutes === null
                  ? "no minute ceiling"
                  : `${formatCount(data.plan_cap_minutes)} minutes`
              }
            />
            {/* Theirs, and only they can move it — the one line that decides whether this
                button can help at all. */}
            <CapFact
              label="Their own ceiling"
              value={formatINR(data.client_cap_spend_inr)}
              note={
                data.client_cap_minutes === null
                  ? "no minute ceiling"
                  : `${formatCount(data.client_cap_minutes)} minutes`
              }
            />
          </dl>

          {recompute.error && <ProblemNotice error={recompute.error} />}

          {/* The SERVER's before/after and the numbers that decided it. `capped: true`
              after a recompute is the route working, so it is rendered as an explanation
              rather than as a failure. */}
          {recompute.data && (
            <NoticeBox
              tone={recompute.data.capped ? "warn" : "ok"}
              icon={<ReceiptIndianRupee className="h-5 w-5" />}
              title={
                recompute.data.capped
                  ? "Recomputed — this client is still capped"
                  : recompute.data.capped_before
                    ? "Recomputed — the cap is released"
                    : "Recomputed — this client was not capped and still is not"
              }
            >
              <p className="mt-1 text-xs">
                {recompute.data.capped
                  ? `They have spent ${formatINR(recompute.data.spend_used_inr)} of ${formatINR(
                      recompute.data.effective_cap_spend_inr,
                    )} this month, so the ceiling in force is still the smaller number. Raise it (or ask them to raise theirs, if the effective ceiling is the client's) and run this again.`
                  : "Their next dial is allowed. Campaigns pick up at the next dispatch tick."}
              </p>
            </NoticeBox>
          )}

          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              recompute.mutate(undefined, { onSuccess: () => setConfirm("") });
            }}
          >
            {/* WHAT IT DOES AND WHAT IT CANNOT DO, before the click. The second half is
                what stops this being read as an "un-cap" button. */}
            <div className="flex gap-3 rounded-card border border-line bg-app p-4 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
              <div className="min-w-0">
                <p className="font-semibold text-ink">
                  This client only — it re-derives the flag, it does not lift the cap
                </p>
                <p className="mt-1 text-ink-muted">
                  It compares the minutes and spend ALREADY metered this month against the
                  ceiling in force now. A client still over that ceiling stays stopped, so
                  raise the ceiling first if that is the fix — this is the second half of
                  that job, not a substitute for it. It never moves a counter, never
                  touches another client, and never affects inbound calls.
                </p>
                <p className="mt-1 text-xs text-ink-faint">
                  Recorded in the audit log as ops.recompute_spend_cap against your admin
                  account, and confirmed with a header bound to this client&apos;s id.
                </p>
              </div>
            </div>

            <label className="block">
              <span className={FIELD_LABEL}>Type RECOMPUTE to confirm</span>
              <input
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                disabled={!write.allowed}
                placeholder="RECOMPUTE"
                className={`${FIELD} mt-1 block w-full font-mono`}
              />
            </label>

            <PrimaryButton
              type="submit"
              disabled={!write.allowed || !ready || recompute.isPending}
            >
              {recompute.isPending ? "Recomputing…" : "Recompute this client's spend cap"}
            </PrimaryButton>

            <RestrictionNote reason={write.reason} />
          </form>
        </div>
      )}
    </Card>
  );
}

/** One cap figure with the minute ceiling that goes with it — rupees and minutes are two
 * ceilings, and `LEAST` is taken over each independently. */
function CapFact({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-card border border-line bg-surface p-4">
      <dt className="text-xs uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className="mt-0.5 text-lg font-semibold tabular-nums text-ink">{value}</dd>
      <dd className="mt-0.5 text-xs text-ink-muted">{note}</dd>
    </div>
  );
}

const PE_STATUSES: { value: PeStatus; label: string }[] = [
  { value: "not_started", label: "not_started — no application filed" },
  { value: "submitted", label: "submitted — filed, awaiting the registrar" },
  { value: "active", label: "active — granted and in force" },
  { value: "suspended", label: "suspended — registrar action" },
  { value: "rejected", label: "rejected — refused by the registrar" },
];

const TM_LINK_STATUSES: { value: TmLinkStatus; label: string }[] = [
  { value: "not_linked", label: "not_linked — client has not authorised us" },
  { value: "pending", label: "pending — authorisation requested" },
  { value: "active", label: "active — we may call on their behalf" },
  { value: "revoked", label: "revoked — authorisation withdrawn" },
];

/**
 * The client's DLT Principal Entity registration, and its link to us (SEC-COMP §3).
 *
 * The symptom: three launch blockers (`pe_registration_missing`,
 * `pe_registration_not_active`, `tm_link_not_active`) tell the client "we handle this,
 * ask your account manager" — and the account manager had nowhere to record the answer
 * when the registrar gave it. Every one of those campaigns stayed blocked with no
 * control anywhere in the product to clear it.
 *
 * OPERATOR-ONLY, and that is the mechanism's integrity rather than a missing feature:
 * the launch gate reads these two statuses, so a client who could set them would be
 * clearing their own compliance blocker by choosing a value from a dropdown. There is
 * no client-realm route for this and there must not be one.
 *
 * Two statuses, not one "ready" flag, because they fail separately and the next action
 * differs — an unregistered entity is a registration we execute for them; a missing TM
 * link is an authorisation only they can grant on the registrar's portal.
 */
function DltRegistrationPanel({ tenantId, write }: { tenantId: string; write: ReturnType<typeof useAdminAccess> }) {
  const record = useRecordDltRegistration(tenantId);
  const [status, setStatus] = useState<PeStatus>("not_started");
  const [tmLink, setTmLink] = useState<TmLinkStatus>("not_linked");
  const [peId, setPeId] = useState("");
  const [entityName, setEntityName] = useState("");
  const [registeredAt, setRegisteredAt] = useState("");

  return (
    <div className="min-w-0 space-y-3 lg:col-span-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
        DLT entity registration (Principal Entity)
      </h3>
      <p className="text-xs text-ink-muted">
        The registrar issues three separate registrations and none implies another: this
        one is the client&apos;s ENTITY, the number header is its own, the voice template
        is a third. The launch gate asks for all three by name.
      </p>

      {record.error && <ProblemNotice error={record.error} />}
      {record.data && (
        /* The API has no GET for this, so the panel can only show what THIS screen just
           wrote — never the stored state on load. Saying "recorded" and echoing the
           values back is the honest version; claiming to display current state we did
           not read would be worse than showing nothing. */
        <NoticeBox tone="ok" icon={<BookOpenCheck className="h-4 w-4" />}>
          <p className="text-xs">
            Recorded: entity <span className="font-medium">{record.data.status}</span>, TM link{" "}
            <span className="font-medium">{record.data.tm_link_status}</span>
            {record.data.pe_id && (
              <>
                , PE id <span className="font-mono">{record.data.pe_id}</span>
              </>
            )}
            . The client&apos;s launch check reflects this on its next refresh.
          </p>
        </NoticeBox>
      )}

      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          record.mutate({
            status,
            tm_link_status: tmLink,
            pe_id: peId.trim() || null,
            entity_name: entityName.trim() || null,
            // `<input type="date">` parsed as LOCAL midnight, not UTC: at +05:30 the
            // UTC reading of "today" is a moment that has not happened yet, and the
            // server refuses a future registration date.
            registered_at: registeredAt ? new Date(`${registeredAt}T00:00:00`).toISOString() : null,
          });
        }}
      >
        <div className="flex flex-wrap gap-2">
          <select
            aria-label="Entity registration status"
            value={status}
            disabled={!write.allowed}
            onChange={(e) => setStatus(e.target.value as PeStatus)}
            className={FIELD}
          >
            {PE_STATUSES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            aria-label="Telemarketer link status"
            value={tmLink}
            disabled={!write.allowed}
            onChange={(e) => setTmLink(e.target.value as TmLinkStatus)}
            className={FIELD}
          >
            {TM_LINK_STATUSES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            value={peId}
            disabled={!write.allowed}
            onChange={(e) => setPeId(e.target.value)}
            placeholder="PE id from the registrar (optional)"
            className={`flex-1 font-mono ${FIELD}`}
          />
          <input
            value={entityName}
            disabled={!write.allowed}
            onChange={(e) => setEntityName(e.target.value)}
            placeholder="Registered entity name (optional)"
            className={`flex-1 ${FIELD}`}
          />
          <input
            type="date"
            aria-label="Registered on"
            value={registeredAt}
            disabled={!write.allowed}
            onChange={(e) => setRegisteredAt(e.target.value)}
            className={FIELD}
          />
        </div>
        <p className="text-xs text-ink-muted">
          Re-recording is normal — this upserts, and it is what happens every time we
          re-verify with the registrar.
        </p>
        <PrimaryButton type="submit" disabled={record.isPending || !write.allowed}>
          {record.isPending ? "Recording…" : "Record registration"}
        </PrimaryButton>
      </form>
    </div>
  );
}

/**
 * The prerequisites every client campaign stalls on (SEC-COMP §3).
 *
 * They live in the ADMIN console because they are our operational work: we buy the
 * number, we file the template with the registrar under the client's PE, we record
 * what the registrar says about their entity. A client who could mark their own
 * template "approved" would be launching under a registration that does not exist —
 * so the client realm reads these and never writes them.
 */
function CampaignSetup({ tenantId, slug }: { tenantId: string; slug: string }) {
  const numbers = useTenantNumbers(slug);
  const templates = useTenantTemplates(slug);
  const provision = useProvisionNumber(tenantId);
  const setDlt = useSetNumberDltStatus(tenantId);
  const register = useRegisterTemplate(tenantId);
  const setStatus = useSetTemplateStatus(tenantId);
  // Every write in this panel is `admin:tenants` on `/v1/admin/tenants/{id}/...`.
  const write = useAdminAccess("admin:tenants", "change this client's telecom setup");

  const [e164, setE164] = useState("");
  const [series, setSeries] = useState<"140" | "160" | "standard">("160");
  const [classification, setClassification] = useState<
    "promotional" | "transactional" | "service"
  >("service");
  const [body, setBody] = useState("");
  const [dltRef, setDltRef] = useState("");

  return (
    <Card title="Campaign setup">
      <p className="-mt-2 text-xs text-ink-muted">
        Until a number, an approved template and an active entity registration exist,
        every campaign this client creates is blocked at launch.
      </p>
      <div className="mt-4">
        <RestrictionNote reason={write.reason} />
      </div>
      {/* `min-w-0` on the columns: a grid item defaults to `min-width: auto`, so it
          refuses to shrink below its own min-content and pushes the grid past the
          viewport instead of wrapping. Measured at 320px this column's min-content was
          288px inside a 238px box — the compliance forms below (a `flex-1` input, a
          `<select>` sized by its longest option) are what set it. */}
      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <div className="min-w-0 space-y-3">
          <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-ink-muted">
            <Hash className="h-3.5 w-3.5" />
            Numbers
          </h3>
          {provision.error && <ProblemNotice error={provision.error} />}
          {setDlt.error && <ProblemNotice error={setDlt.error} />}
          {/* A failed read printed "No numbers provisioned" — the sentence an operator
              acts on by buying a second number for a client who already has one. */}
          {numbers.error ? (
            <ProblemNotice error={numbers.error} onRetry={() => numbers.refetch()} />
          ) : numbers.isLoading || !numbers.data ? (
            <Skeleton rows={2} />
          ) : numbers.data.length === 0 ? (
            <p className="text-xs text-ink-muted">No numbers provisioned.</p>
          ) : (
            <ul className="space-y-1.5">
              {numbers.data.map((number) => (
                <li
                  key={number.id}
                  className="flex flex-wrap items-center gap-2 rounded-card border border-line p-2 text-xs"
                >
                  {/* The client's OWN published business number, which is the whole
                      point of the panel — not a called party's, which is the number
                      hard rule 6 is about. */}
                  <span className="font-mono text-ink">{number.e164}</span>
                  <span className="rounded bg-brand-soft px-1.5 py-0.5 font-medium text-brand-strong">
                    {number.series}
                  </span>
                  <span className="text-ink-muted">{number.dlt_status}</span>
                  {number.dlt_status !== "registered" && (
                    <span className="ml-auto">
                      <SecondaryButton
                        disabled={setDlt.isPending || !write.allowed}
                        onClick={() => setDlt.mutate({ numberId: number.id, dltStatus: "registered" })}
                      >
                        Mark registered
                      </SecondaryButton>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <form
            className="flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              provision.mutate({ e164, series }, { onSuccess: () => setE164("") });
            }}
          >
            <input
              required
              aria-label="Number to provision"
              value={e164}
              disabled={!write.allowed}
              onChange={(ev) => setE164(ev.target.value)}
              placeholder="+918041234567"
              className={`flex-1 font-mono ${FIELD}`}
            />
            {/* The series is what the launch gate matches against the campaign's
                classification — wrong here is a DLT violation later, not a typo. */}
            <select
              aria-label="Number series"
              value={series}
              disabled={!write.allowed}
              onChange={(ev) => setSeries(ev.target.value as typeof series)}
              className={FIELD}
            >
              <option value="140">140 — promotional</option>
              <option value="160">160 — service</option>
              <option value="standard">standard</option>
            </select>
            <PrimaryButton
              type="submit"
              disabled={provision.isPending || e164.length < 8 || !write.allowed}
            >
              Add
            </PrimaryButton>
          </form>
        </div>

        <div className="min-w-0 space-y-3">
          <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-ink-muted">
            <ScrollText className="h-3.5 w-3.5" />
            DLT voice templates
          </h3>
          {register.error && <ProblemNotice error={register.error} />}
          {setStatus.error && <ProblemNotice error={setStatus.error} />}
          {templates.error ? (
            <ProblemNotice error={templates.error} onRetry={() => templates.refetch()} />
          ) : templates.isLoading || !templates.data ? (
            <Skeleton rows={2} />
          ) : templates.data.length === 0 ? (
            <p className="text-xs text-ink-muted">No templates registered.</p>
          ) : (
            <ul className="space-y-1.5">
              {templates.data.map((template) => (
                <li key={template.id} className="rounded-card border border-line p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-brand-soft px-1.5 py-0.5 font-medium text-brand-strong">
                      {template.classification}
                    </span>
                    <span className="text-ink-muted">{template.status}</span>
                    {template.status !== "approved" && (
                      <span className="ml-auto">
                        <PrimaryButton
                          disabled={setStatus.isPending || !write.allowed}
                          onClick={() =>
                            setStatus.mutate({ templateId: template.id, status: "approved" })
                          }
                        >
                          Registrar approved
                        </PrimaryButton>
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-ink-muted">{template.body}</p>
                </li>
              ))}
            </ul>
          )}
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              register.mutate(
                { classification, body, dlt_ref: dltRef || null },
                {
                  onSuccess: () => {
                    setBody("");
                    setDltRef("");
                  },
                },
              );
            }}
          >
            <div className="flex gap-2">
              <select
                aria-label="Template classification"
                value={classification}
                disabled={!write.allowed}
                onChange={(ev) => setClassification(ev.target.value as typeof classification)}
                className={FIELD}
              >
                <option value="promotional">promotional</option>
                <option value="service">service</option>
                <option value="transactional">transactional</option>
              </select>
              <input
                aria-label="Registrar template id"
                value={dltRef}
                disabled={!write.allowed}
                onChange={(ev) => setDltRef(ev.target.value)}
                placeholder="registrar template id (optional)"
                className={`flex-1 ${FIELD}`}
              />
            </div>
            <textarea
              required
              aria-label="Template wording"
              minLength={10}
              rows={3}
              value={body}
              disabled={!write.allowed}
              onChange={(ev) => setBody(ev.target.value)}
              placeholder="The exact wording registered with the DLT registrar."
              className={`w-full ${FIELD}`}
            />
            <PrimaryButton
              type="submit"
              disabled={register.isPending || body.length < 10 || !write.allowed}
            >
              Register template
            </PrimaryButton>
          </form>
        </div>

        {/* Beside the numbers and the templates, because they are the same family of
            registrar paperwork and an operator working one is usually working all
            three — not on a separate screen a launch blocker has to send them to. */}
        <DltRegistrationPanel tenantId={tenantId} write={write} />
      </div>
    </Card>
  );
}

/**
 * WhatsApp hot-lead alerts for this client's owner — the opt-in given OFF the screen.
 *
 * ## Why an operator surface exists at all
 *
 * The client's own control is `/c/[slug]/settings/alerts`, and it is the better path:
 * the person agreeing is the person clicking, which is what makes a self-serve grant
 * self-evidencing (a CHECK constraint requires the subject and the recorder to be the
 * same user). This panel is for the other case, which is most of them at our size — the
 * owner agreed on the onboarding call, or on a signed form, and somebody has to write
 * that down. So a grant here MUST carry the reference of the document it rests on, and
 * the row names the operator rather than the owner as its recorder.
 *
 * ## The read is the part that makes the write safe to offer
 *
 * `GET .../whatsapp-alerts` (admin realm) exists so this panel can show the owner's
 * CURRENT state before an operator records a month-old form over a withdrawal made last
 * week. The ledger is append-only, so that mistake is not editable — it is another row,
 * and the alerts went out in between. The client-realm read cannot answer here: a view-as
 * session has no `users` row of its own and deliberately reports no subject state.
 *
 * ## What it does not do
 *
 * No step-up header, unlike the ops console's global do-not-call writes. This names ONE
 * tenant and one owner and demands a document reference; the typed-confirmation
 * discipline is spent where a single POST binds every tenant at once.
 */
function WhatsAppAlertsPanel({ tenantId }: { tenantId: string }) {
  const state = useTenantAlertOptIn(tenantId);
  const record = useRecordTenantAlertOptIn(tenantId);
  const write = useAdminAccess("admin:tenants", "record this client's WhatsApp opt-in");
  const [reference, setReference] = useState("");

  const current = state.data;
  // The document reference is what makes an operator's claim evidence rather than an
  // assertion — the service and a CHECK both refuse a grant without one, so the button
  // is dead until it is typed rather than sending a request that cannot succeed.
  const ready = write.allowed && reference.trim().length > 0 && !record.isPending;

  return (
    <Card title="WhatsApp alerts to the owner">
      <p className="-mt-2 text-xs text-ink-muted">
        Hot-lead alerts go to the owner&apos;s mobile only if they have agreed to receive
        them. Record an agreement given during onboarding here; the client can turn it on
        or off themselves on their own Alerts screen.
      </p>

      <div className="mt-4">
        <RestrictionNote reason={write.reason} />
      </div>

      {/* Loading is a skeleton and a failure is a refusal — never "not opted in", which
          is the sentence an operator answers by recording one they have no document for. */}
      {state.isLoading ? (
        <div className="mt-4">
          <Skeleton rows={2} />
        </div>
      ) : state.error ? (
        <div className="mt-4">
          <ProblemNotice error={state.error} onRetry={() => state.refetch()} />
        </div>
      ) : !current ? null : (
        <div className="mt-4 space-y-4">
          <NoticeBox
            tone={current.messageable ? "ok" : "neutral"}
            icon={
              current.messageable ? (
                <BellRing aria-hidden className="h-5 w-5" />
              ) : (
                <BellOff aria-hidden className="h-5 w-5" />
              )
            }
            title={
              current.messageable
                ? "The owner receives WhatsApp hot-lead alerts"
                : current.status === "withdrawn"
                  ? "The owner has WITHDRAWN — do not record an older agreement over this"
                  : "Nobody on this account has agreed to WhatsApp alerts"
            }
          >
            <p className="mt-1">
              {current.captured_at
                ? `Recorded ${formatIST(current.captured_at)} · ${current.channel ?? "unknown channel"}`
                : "No entry on the opt-in ledger for this owner and this number."}
              {!current.delivery_available && (
                <>
                  {" "}
                  This deployment cannot deliver WhatsApp yet
                  {current.delivery_unavailable_reason
                    ? ` (${current.delivery_unavailable_reason})`
                    : ""}
                  , so nothing is sent whatever is recorded here.
                </>
              )}
            </p>
          </NoticeBox>

          {record.error && <ProblemNotice error={record.error} />}

          <label className="block">
            <span className={FIELD_LABEL}>Where the agreement is filed</span>
            <input
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              disabled={!write.allowed}
              placeholder="e.g. ONB-2026-0042, or a ticket id"
              className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint"
            />
            <span className="mt-1 block text-xs text-ink-faint">
              A reference, never the document itself. It is what answers &ldquo;who agreed,
              and where is it written down&rdquo; a year later — a grant without one is
              refused by the service and by the database.
            </span>
          </label>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!ready}
              title={write.reason ?? undefined}
              onClick={() =>
                record.mutate(
                  { status: "granted", evidence: { reference: reference.trim() } },
                  { onSuccess: () => setReference("") },
                )
              }
              className="inline-flex items-center gap-2 rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-strong disabled:cursor-not-allowed disabled:opacity-50"
            >
              <BellRing aria-hidden className="h-4 w-4" />
              Record that the owner agreed
            </button>
            {/* Withdrawing needs no document — nobody has to prove that somebody asked to
                stop, and requiring evidence for it would be a reason to delay stopping. */}
            <button
              type="button"
              disabled={!write.allowed || record.isPending}
              title={write.reason ?? undefined}
              onClick={() => record.mutate({ status: "withdrawn", evidence: null })}
              className="inline-flex items-center gap-2 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-white/5"
            >
              <BellOff aria-hidden className="h-4 w-4" />
              Record a withdrawal
            </button>
          </div>
        </div>
      )}
    </Card>
  );
}
