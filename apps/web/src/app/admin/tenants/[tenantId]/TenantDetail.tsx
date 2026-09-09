"use client";

import Link from "next/link";
import { ArrowLeft, Bot, PhoneCall, Sparkles, Users } from "lucide-react";

import {
  EmptyState,
  ProblemNotice,
  Skeleton,
  StatTile,
  formatCount,
  formatIST,
} from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import { useTenant, useTenantKbQueue } from "@/lib/api/admin";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { holdRule } from "@/lib/api/holds";

import { AgentsPanel } from "./AgentsPanel";
import { CampaignSetup } from "./CampaignSetup";
import { HoldsBanner } from "./HoldsBanner";
import { KnowledgeQueue, unpublishedSources } from "./KnowledgeQueue";
import { MarginPanel } from "./MarginPanel";
import { SpendCapPanel } from "./SpendCapPanel";
import { TenantNav } from "./TenantNav";
import { WhatsAppAlertsPanel } from "./WhatsAppAlertsPanel";

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
 *
 * ## Why the panels are eight files and not one
 *
 * This module was 1,844 lines — UX-DOCTRINE §6's smell with its named remedy, extract by
 * SUBJECT. Every panel below is a subject with its own permission, its own reads and its
 * own refusals, and each is now its own file beside this one. Nothing any of them does
 * changed; what changed is that the screen's shape is readable from the directory.
 */

export function TenantDetail({ tenantId }: { tenantId: string }) {
  // One request for one client — the list endpoint is N+1 by design (it counts calls
  // and leads per tenant under each tenant's own RLS), so fetching all of it to find
  // one row made a detail page cost the whole directory.
  const tenantQuery = useTenant(tenantId);
  const tenant = tenantQuery.data;
  const slug = tenant?.slug ?? "";

  /*
   * READ HERE ONLY SO THE ASSISTANT CAN BE TOLD THE TWO QUEUE SIZES. `KnowledgeQueue`
   * runs the same two reads and owns every control over them; these share its query keys,
   * so this is a second verdict on one request rather than a second request — the same
   * arrangement `/admin/ops` uses for its two readings of `useAdminAccess`. The
   * declaration cannot be moved into the panel: `registry.ts` keeps a stack and the
   * innermost registration wins, so a surface declared down there would shadow this one.
   */
  const queue = useTenantKbQueue(slug);
  const publishQueue = useTenantKbQueue(slug, "approved");
  const kbWrite = useAdminAccess("admin:tenants", "decide on this client's knowledge");

  /*
   * ONE CLIENT, DECLARED TO THE SCREEN ASSISTANT.
   *
   * THE CROSS-TENANT QUESTION IS ANSWERED BY THE ROUTE HERE, and this is the one admin
   * shape where per-client detail is the right answer rather than the leak: the URL names
   * a single tenant, every figure below was read under that tenant's own RLS session, and
   * an operator asking "why can this client not dial" is asking about the client whose
   * name is in the heading. The boards that list many tenants (`/admin`, `/admin/health`,
   * `/admin/holds`, `/admin/spend`) send counts precisely so that the detail lives here,
   * scoped, once.
   *
   * The KB queue is declared as COUNTS and not as titles. A source name is client-authored
   * text — the rename-your-price-list kind — and the module that guards this seam exists
   * partly because attacker-authored titles carry invisible characters
   * (`copilot/sanitize.py`); the document PREVIEW, which is the client's own content, is
   * further still from anything worth volunteering.
   *
   * The reject-reason box is not declared. It is free text an operator writes onto a
   * client's permanent `rejection_reason`, and a machine-drafted rejection is not a thing
   * this console should offer at the point the operator is deciding.
   *
   * Declared before the three early returns, because a hook cannot sit behind one — and
   * the loading and not-found renders want the launcher too.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}",
    title: "Client",
    realm: "admin",
    fields: [],
    facts: tenant
      ? [
          { key: "tenant_id", label: "Tenant id", value: tenantId },
          { key: "client", label: "Client", value: tenant.name },
          { key: "slug", label: "Slug", value: tenant.slug },
          { key: "status", label: "Account status", value: tenant.status },
          {
            key: "vertical_template",
            label: "Vertical template",
            value: tenant.vertical_template ?? "none",
          },
          { key: "live_agents", label: "Live agents", value: String(tenant.live_agents) },
          { key: "calls_7d", label: "Calls in the last 7 days", value: String(tenant.calls_7d) },
          { key: "leads", label: "Leads", value: String(tenant.leads) },
          { key: "last_call_at", label: "Last call", value: tenant.last_call_at ?? "never" },
          {
            key: "capped",
            label: "At the spend ceiling (outbound refused pre-dispatch)",
            value: tenant.capped ? "yes" : "no",
          },
          {
            key: "holds",
            label: "Gates holding this account",
            value:
              tenant.holds.map((rule) => holdRule(rule)?.label ?? rule).join(", ") || "none",
          },
          {
            key: "kb_awaiting_approval",
            label: "Knowledge documents awaiting approval (titles are not sent)",
            value: queue.data ? String(queue.data.length) : "could not be read",
          },
          {
            key: "kb_awaiting_publish",
            label: "Approved knowledge documents not yet live",
            value: publishQueue.data
              ? String(unpublishedSources(publishQueue.data).length)
              : "could not be read",
          },
          {
            key: "may_decide_kb",
            label: "May this operator approve or reject knowledge",
            value: kbWrite.allowed ? "yes" : "no",
          },
        ]
      : [
          {
            key: "client",
            label: "This client",
            // A 403, a 500 or a dropped connection is not "no such client", and the
            // assistant must not be the surface that says it is.
            value: tenantQuery.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

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
        <TenantNav tenantId={tenantId} slug={tenant.slug} />
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

      <KnowledgeQueue tenantId={tenantId} slug={slug} />

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
