"use client";

import { useAdminAccess } from "@/app/admin/access";
import { formatISTStamp } from "@/components/ui";
import { useTenant, useTenantKbQueue } from "@/lib/api/admin";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { holdRule } from "@/lib/api/holds";

import { AccountStateBanner } from "./AccountStateBanner";
import { HoldsBanner } from "./HoldsBanner";
import { NoOwnerBanner } from "./NoOwnerBanner";
import { accountFacts, useAccountReads } from "./accountFacts";
import { KnowledgeDeliveryPanel } from "./KnowledgeDeliveryPanel";
import { KnowledgeQueue, unpublishedSources } from "./KnowledgeQueue";
import { HealthSummary } from "./HealthSummary";
import { MarginPanel } from "./MarginPanel";
import { UsagePanel, useUsageFacts } from "./UsagePanel";

/**
 * One client's overview: is it working, and what is waiting on us.
 *
 * Primary job: *tell the operator where to go next.* Stops first (account state, then the
 * gates holding it), then this week's activity and this month's margin, then the knowledge
 * an operator still has to decide or publish and whether it reached the phone. Everything
 * else is a section of the client layout (D-661) and is reached from its menu.
 *
 * The queue is READ through impersonation and DECIDED through the admin surface. That
 * split was D-22's ("no acting-as: mutations still go through admin surfaces") and it
 * OUTLIVES D-587, which reversed the read-only rule: approving a client's knowledge is
 * OUR act and the record should say so, on a path that names the tenant rather than
 * borrowing their session. So the buttons here still post to
 * `/v1/admin/tenants/.../kb/...` rather than to the client-realm KB routes the queue was
 * read from.
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
 * The client's name, state and section menu are the tenant layout's (`TenantShell.tsx`),
 * which prints the page's `h1`; this screen starts at `h2`.
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
  const accountReads = useAccountReads(tenant);
  const usage = useUsageFacts(tenantId);

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
    tenantId,
    fields: [],
    facts: tenant
      ? [
          { key: "tenant_id", label: "Tenant id", value: tenantId },
          { key: "client", label: "Client", value: tenant.name },
          { key: "slug", label: "Slug", value: tenant.slug },
          { key: "status", label: "Account status (stored)", value: tenant.status },
          ...accountFacts(tenant, accountReads),
          ...usage,
          {
            // WHICH WAY THE MONEY MOVES, which decides what half this screen's other
            // figures mean: a `managed` client has no wallet to be empty, so "why have
            // their calls stopped" has different answers either side of it.
            key: "plan_tier",
            label: "Account type (every client pays from prepaid credit)",
            value: tenant.plan_tier,
          },
          {
            key: "vertical_template",
            label: "Vertical template",
            value: tenant.vertical_template ?? "none",
          },
          { key: "live_agents", label: "Live agents", value: String(tenant.live_agents) },
          { key: "calls_7d", label: "Calls in the last 7 days", value: String(tenant.calls_7d) },
          { key: "leads", label: "Leads", value: String(tenant.leads) },
          { key: "last_call_at", label: "Last call", value: formatISTStamp(tenant.last_call_at, "never") },
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

  // The layout resolves the tenant before this page mounts; a render without it (a test
  // that mounts the page alone, before its stub answers) paints nothing rather than a guess.
  if (!tenant) return null;

  return (
    <div className="max-w-4xl space-y-10">
      {/* ABOVE the holds, because it outranks them: `check_dispatch` asks the account
          state before it asks any gate, so a suspended account is refused whether or not
          a hold is also open, and an operator told only about the hold would clear it and
          watch nothing change. */}
      <AccountStateBanner tenantId={tenantId} status={tenant.status} />

      <NoOwnerBanner tenantId={tenantId} slug={tenant.slug} />

      <HoldsBanner tenantId={tenantId} holds={tenant.holds} />

      {/* Status, what is wrong now, credit and runway, the last calls and the quick
          actions (founder, 10 Oct 2026), above the money and the knowledge queue. */}
      <HealthSummary tenant={tenant} />

      <UsagePanel tenantId={tenantId} />

      <MarginPanel tenantId={tenantId} />

      <KnowledgeQueue tenantId={tenantId} slug={slug} />

      {/* Directly under the queue, because it is the other end of the same job: the queue
          ends at Publish, and a publish whose pack failed to store leaves every screen
          showing the new words while the phone quotes the old ones
          (`kb/pack.refresh_published_pack` survives that failure by design). */}
      <KnowledgeDeliveryPanel slug={slug} />

    </div>
  );
}
