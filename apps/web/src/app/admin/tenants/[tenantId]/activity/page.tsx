"use client";

import Link from "next/link";
import { use, useState } from "react";
import { ArrowLeft, ChevronLeft, ChevronRight, Eye, ShieldCheck } from "lucide-react";

import {
  Card,
  EmptyState,
  FilterChip,
  NOTICE_TONES,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  ScrollRegion,
  Skeleton,
  formatCount,
  formatIST,
} from "@/components/ui";
import { useTenant } from "@/lib/api/admin";
import {
  ACTIVITY_PAGE_SIZE,
  ACTOR_LABELS,
  useTenantActivity,
  type ActivityEntry,
  type ActorType,
} from "@/lib/api/adminAccount";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

/**
 * What has been done to this account, and by whom.
 *
 * Read from `audit_log` — the existing hash-chained, append-only ledger — and NOT from a
 * new store. That is the whole design: every mutation in either realm already writes a row
 * there, so the question "who changed this client's plan, and when" has had an answer
 * since the first migration; what it has never had is a screen. Building a second history
 * table to render would have been two records of one fact, and the one on screen would be
 * the one nobody could verify.
 *
 * ## WHAT AN OPERATOR CAN DO WITH THIS AND WHAT THEY CANNOT
 *
 * It answers WHO, WHAT and WHEN. It does not answer WHAT CHANGED: `audit_log` has no
 * summary column — `write_audit`'s summary goes to the log stream — and that is deliberate
 * rather than a gap, because a hashed ledger row carrying free-form payloads is a ledger
 * carrying whatever a caller put in it, up to and including a phone number. So this screen
 * is a trail, and the before-and-after of any one act lives on the screen that performed
 * it.
 *
 * ## THE VIEW-AS MARK IS THE ROW WORTH READING (D-587)
 *
 * A view-as session can change a client's account now, and every such change carries the
 * grant it came through. An act done while wearing the client's face is marked here, so
 * "the client did this" and "one of us did this as the client" are never the same row. It
 * is painted in the warn tone for that reason and not because it is suspicious.
 *
 * ## THE ACTION NAME IS PRINTED AS ITSELF
 *
 * No translation table. The vocabulary is open — every module adds to it — and a console
 * that only knew some of the names would either drop rows it could not label or print
 * "Unknown action" over a real one. `admin.plan_tier_changed` is legible to the operator
 * who needs it and searchable by the one who does not.
 */

const ACTOR_FILTERS: readonly (ActorType | "all")[] = ["all", "admin", "user", "system"];

const ACTOR_FILTER_LABELS: Record<string, string> = {
  all: "everyone",
  admin: "us",
  user: "the client",
  system: "automatic",
};

function EntryRow({ entry }: { entry: ActivityEntry }) {
  return (
    <tr className="align-top">
      <td className="whitespace-nowrap px-5 py-3 text-xs text-ink-muted">{formatIST(entry.at)}</td>
      <td className="px-5 py-3">
        <span className="font-mono text-xs text-ink">{entry.action}</span>
        {entry.via_grant_id && (
          <span
            className={`ml-2 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${NOTICE_TONES.warn}`}
            title="Done from a view-as session: one of us, acting inside the client's console"
          >
            <Eye className="h-3 w-3" />
            as the client
          </span>
        )}
      </td>
      <td className="px-5 py-3 text-xs text-ink-muted">
        {/* The operator's NAME when we have one, and the actor class when we do not. An
            uuid on its own is not an answer a support call can use, and an unrecorded
            name is a fact about our own older rows rather than about this client. */}
        {entry.actor_label ?? lookup(ACTOR_LABELS, entry.actor_type) ?? entry.actor_type}
      </td>
      <td className="px-5 py-3 text-xs text-ink-faint">
        {entry.object_type ? (
          <>
            {entry.object_type}
            {entry.object_id && <span className="ml-1 font-mono">{entry.object_id}</span>}
          </>
        ) : (
          "—"
        )}
      </td>
    </tr>
  );
}

export default function TenantActivityPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const [actorType, setActorType] = useState<ActorType | "all">("all");
  const [offset, setOffset] = useState(0);
  const tenantQuery = useTenant(tenantId);
  const activity = useTenantActivity(tenantId, { offset, actorType });

  const page = activity.data;
  const entries = page?.entries ?? [];

  /*
   * THE TRAIL, DECLARED TO THE SCREEN ASSISTANT.
   *
   * COUNTS AND ACTION NAMES, NOT ROWS. The action vocabulary is what an operator asks
   * about ("what is admin.tenant_read?"), and the shape of the page is what they can see.
   * The actor labels are NOT declared: they name Calevate staff, and a colleague's name
   * has no business in a model conversation about a client's history.
   *
   * NO FIELDS: nothing on this screen is writable, and by construction nothing can be —
   * the ledger is INSERT-only.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/activity",
    title: "Account activity",
    realm: "admin",
    fields: [],
    facts: [
      { key: "tenant_id", label: "Tenant id", value: tenantId },
      { key: "client", label: "Client", value: tenantQuery.data?.name ?? "could not be read" },
      {
        key: "total",
        label: "Audited acts recorded against this account, matching the current filter",
        value: page
          ? String(page.total)
          : activity.error
            ? "could not be read"
            : "still loading",
      },
      {
        key: "actions",
        label: "The action names on the page being read",
        value: entries.length
          ? Array.from(new Set(entries.map((entry) => entry.action))).join(", ")
          : "none",
      },
      {
        key: "view_as",
        label: "How many acts on this page were done from a view-as session",
        value: String(entries.filter((entry) => entry.via_grant_id).length),
      },
    ],
    apply: noFill,
  });

  const name = tenantQuery.data?.name ?? "this client";

  function refilter(next: ActorType | "all") {
    setActorType(next);
    // The offsets of one filtered set mean nothing in another: staying on page three
    // while narrowing to "the client" asks for rows 50-75 of a set that may have four.
    setOffset(0);
  }

  return (
    <div className="max-w-4xl space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {name}
        </Link>
        <h1 className="mt-1 text-xl font-semibold text-ink">Activity</h1>
        <p className="text-sm text-ink-muted">
          Every audited act recorded against this account, newest first — ours and theirs.
          This is a view of the tamper-evident audit ledger itself, so nothing on it can be
          edited or removed. It says who acted and what they did; what a change contained
          lives on the screen that made it.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-ink-faint">Acts by</span>
        {ACTOR_FILTERS.map((value) => (
          <FilterChip
            key={value}
            label={lookup(ACTOR_FILTER_LABELS, value) ?? value}
            active={actorType === value}
            onClick={() => refilter(value)}
          />
        ))}
      </div>

      <Card bodyClassName="p-0">
        {activity.isLoading ? (
          <div className="p-6">
            <Skeleton rows={5} />
          </div>
        ) : activity.error ? (
          /* Not an empty table: "nothing has been done to this account" is a claim about
             the record, and a failed read is not evidence for it. */
          <div className="p-6">
            <ProblemNotice error={activity.error} onRetry={() => void activity.refetch()} />
          </div>
        ) : entries.length === 0 ? (
          <EmptyState
            title={
              actorType === "all"
                ? "Nothing has been recorded against this account yet"
                : "Nothing matches this filter"
            }
            hint={
              actorType === "all"
                ? "Every audited act — a plan change, a verification, a campaign release — appears here as it happens."
                : "Try 'everyone' to see the whole trail."
            }
          />
        ) : (
          <ScrollRegion label="Account activity">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th className="px-5 py-3 font-semibold">When (IST)</th>
                  <th className="px-5 py-3 font-semibold">Action</th>
                  <th className="px-5 py-3 font-semibold">Who</th>
                  <th className="px-5 py-3 font-semibold">On</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {entries.map((entry) => (
                  <EntryRow key={entry.id} entry={entry} />
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
      </Card>

      {page && page.total > entries.length && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-ink-muted">
          <span aria-live="polite">
            Showing {formatCount(page.offset + 1)}–{formatCount(page.offset + entries.length)} of{" "}
            {formatCount(page.total)}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={page.offset === 0}
              onClick={() => setOffset(Math.max(0, page.offset - ACTIVITY_PAGE_SIZE))}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              Newer
            </button>
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={page.offset + entries.length >= page.total}
              onClick={() => setOffset(page.offset + ACTIVITY_PAGE_SIZE)}
            >
              Older
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      <p className="flex items-start gap-2 text-xs text-ink-faint">
        <ShieldCheck aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        Each row is a link in a hash chain. The chain itself is verified from the ops
        switchboard, which reports any entry that has been altered since it was written.
      </p>
    </div>
  );
}
