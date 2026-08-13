"use client";

import Link from "next/link";
import { use, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  BookOpenCheck,
  Bot,
  Eye,
  FileCheck2,
  Hash,
  PhoneCall,
  ReceiptIndianRupee,
  ScrollText,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";

import {
  Card,
  EmptyState,
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
  useRecordDltRegistration,
  useRegisterTemplate,
  useSetNumberDltStatus,
  useSetTemplateStatus,
  useTenant,
  useTenantAgents,
  useTenantKbQueue,
  useTenantNumbers,
  useTenantTemplates,
  type PeStatus,
  type TmLinkStatus,
} from "@/lib/api/admin";
import { holdRule } from "@/lib/api/holds";
import { VIEW_AS_ADMIN, VIEW_AS_PARAM } from "@/lib/api/session";

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
                    ) : (
                      /* Chunk-by-chunk is how it is reviewed because chunk-by-chunk is
                         how it will be retrieved and read aloud. */
                      (preview.data ?? []).map((chunk) => (
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
          on the client's screen and nothing here to explain why. */}
      {publishQueue.error ? (
        <Card title="Approved, awaiting publish">
          <ProblemNotice error={publishQueue.error} onRetry={() => publishQueue.refetch()} />
        </Card>
      ) : awaitingPublish.length > 0 ? (
        <Card title="Approved, awaiting publish" bodyClassName="px-6 pb-4">
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

      <CampaignSetup tenantId={tenantId} slug={slug} />
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

const FIELD =
  "rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink placeholder:text-ink-faint disabled:cursor-not-allowed disabled:opacity-50";

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
    <Card title="Agents" bodyClassName="px-6 pb-4 pt-2">
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
    </Card>
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
    <div className="space-y-3 lg:col-span-2">
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
      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <div className="space-y-3">
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

        <div className="space-y-3">
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
