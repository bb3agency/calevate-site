"use client";

import { useMemo, useState } from "react";
import { ListPlus, Search } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { MonoValue, dncSourceCopy } from "@/app/admin/ops/opsLanguage";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { Drawer } from "@/components/console/drawer";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { RowMenu } from "@/components/console/rowMenu";
import { CopyButton } from "@/components/interior/copy-button";
import {
  Card,
  FIELD_INLINE_ICON,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatIST,
  formatPhone,
} from "@/components/ui";
import { DNC_LIST_LIMIT } from "@/lib/api/dnc";
import {
  useGlobalDncList,
  useReleaseGlobally,
  useSuppressGlobally,
  type GlobalDncEntry,
} from "@/lib/api/opsDnc";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { ReleaseConfirm, SuppressForm } from "./dncDrawers";

/**
 * The platform-wide do-not-call list: `dnc_list.scope='global'` rows (D-107), an absolute
 * suppression true for every tenant at once and removable by no client.
 *
 * The two directions are not symmetrical. Suppressing costs calls that would have been
 * placed; releasing re-permits dialling somebody who asked not to be dialled, for every
 * client, at the next dispatch tick. So:
 *
 * 1. There is no default state. The list stays `GlobalDncEntry[] | undefined`: a failed
 *    read is a refusal and no rows, never "nothing is suppressed" (§52).
 * 2. Each write carries its own typed word and its own `X-Confirm-Action` header, which the
 *    API binds separately — the release header names the row.
 * 3. Release is confirmed per row, in a drawer mounted for that one entry.
 * 4. The list shows numbers in full (D-436): releasing means reading the number back to the
 *    regulator or telecom operator who asked. Display is grouped (`formatPhone`); copying
 *    and searching use E.164.
 *
 * The preference-register scrub (`POST …/campaigns/{id}/preference-scrub`) is a different
 * fact — per campaign, on an access provider's DLT platform, expiring that day — and needs
 * the Registered Telemarketer relationship (R-01) this company does not hold yet;
 * `runbooks/dnc-complaint.md` §8 carries the procedure meanwhile.
 */
export function DncScreen() {
  const entries = useGlobalDncList();
  const suppress = useSuppressGlobally();
  const release = useReleaseGlobally();
  /*
   * `ops:manage` (superadmin only), asked of `GET /v1/admin/me` so the controls disable
   * themselves with the reason. Gated on the permission alone, not on the list read:
   * suppressing a number the list could not be shown for is still right when a regulator
   * is on the phone.
   */
  const write = useAdminAccess("ops:manage", "change the platform-wide do-not-call list");
  const [adding, setAdding] = useState(false);
  const [releasingId, setReleasingId] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  // `entries.data`, never `?? []`: "the server said none" and "the server did not answer"
  // are opposite facts about our compliance posture.
  const rows = entries.data;
  // At the endpoint's ceiling the count stops being a total (it clamps, with no offset).
  const truncated = rows !== undefined && rows.length >= DNC_LIST_LIMIT;
  const digits = query.replace(/\D/g, "");
  const shown = useMemo(
    () => (rows && digits ? rows.filter((entry) => entry.phone_e164.replace(/\D/g, "").includes(digits)) : rows),
    [rows, digits],
  );
  const releasingEntry = rows?.find((entry) => entry.id === releasingId);

  /*
   * Every row is a phone number, so this declaration carries none of them and no field.
   * The two controls a field would cover are the paste box — a bulk write against every
   * client's dialler, behind a typed confirmation whose purpose is that a human read the
   * numbers — and the reason, free text where a complainant's name lands. Neither should
   * be reachable from a sentence. The counts identify nobody.
   */
  useCopilotSurface({
    route: "/admin/ops/dnc",
    title: "Do-not-call, platform-wide",
    realm: "admin",
    fields: [],
    facts: rows
      ? [
          {
            key: "entries",
            label: truncated
              ? `Entries listed (clamped at the endpoint's ceiling of ${DNC_LIST_LIMIT}, so this is not the total)`
              : "Numbers suppressed for every client",
            value: String(rows.length),
          },
          {
            key: "sources",
            label: "Where the listed entries came from",
            value:
              [...new Set(rows.map((entry) => entry.source ?? "unrecorded"))].sort().join(", ") ||
              "none",
          },
          {
            key: "removable",
            label: "Listed entries an operator may release",
            value: String(rows.filter((entry) => entry.removable).length),
          },
          {
            key: "may_write",
            label: "May this operator suppress or release a number",
            value: write.allowed ? "yes" : "no",
          },
          {
            key: "numbers_withheld",
            label: "The numbers themselves",
            value: "not sent to the assistant — see the comment above this declaration",
          },
        ]
      : [
          {
            key: "list",
            label: "The platform-wide list",
            value: entries.error ? "could not be read" : "still loading",
          },
        ],
    apply: noFill,
  });

  const openRelease = (id: string) => {
    // The mutation is shared by every row; a refusal for one number must not greet the next.
    release.reset();
    setReleasingId(id);
  };
  const columns = useMemo(
    () => buildColumns(write.allowed, openRelease),
    // `openRelease` only closes over stable setters and the mutation's `reset`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [write.allowed],
  );

  return (
    <div className="max-w-3xl space-y-5">
      <PageHeader
        description={
          <>
            These are the numbers Calevate will not dial for anyone. A number here overrides
            every client&apos;s own do-not-call list, is checked before every single call, and
            no client can add or remove it.{" "}
            <InfoTip label="Who changed what">
              Every change you make is recorded in the audit log under your admin account.
            </InfoTip>
          </>
        }
        actions={
          <button
            type="button"
            onClick={() => setAdding(true)}
            disabled={!write.allowed}
            title={write.reason ?? undefined}
            className={PRIMARY_BUTTON}
          >
            <ListPlus aria-hidden className="h-4 w-4" />
            Suppress numbers
          </button>
        }
      />

      <RestrictionNote reason={write.allowed ? null : write.reason} />

      <Card
        title="Suppressed for every client"
        action={
          // No count until the server has sent one: "0" while the first request is in
          // flight is a statement about what this platform refuses to dial.
          rows ? (
            <span className="text-xs text-ink-muted">
              {truncated
                ? `Showing the ${formatCount(DNC_LIST_LIMIT)} most recently added`
                : `${formatCount(rows.length)} ${rows.length === 1 ? "entry" : "entries"}`}
            </span>
          ) : undefined
        }
        bodyClassName="p-0"
      >
        {entries.error != null && (
          <div className="space-y-2 px-4 pb-4 pt-2">
            <ProblemNotice error={entries.error} onRetry={() => entries.refetch()} />
            {/* An operator who cannot see the list is the one most likely to assume it is
                empty, so the refusal says so in this screen's own words. */}
            <p className="text-sm text-ink-muted">
              This screen will not tell you what is suppressed, and it will not tell you
              nothing is. The suppressions are unaffected — the check runs against them
              directly before every call, not from this screen.
            </p>
          </div>
        )}

        {entries.isLoading ? (
          <div className="p-4">
            <Skeleton rows={5} label="Loading the platform-wide list" />
          </div>
        ) : !rows || !shown ? null : rows.length === 0 ? (
          <EmptyState
            message={
              <>
                No number is suppressed platform-wide.
                <span className="mt-1 block text-[13px] text-ink-faint">
                  Clients&apos; own do-not-call lists are separate and are not shown here.
                </span>
              </>
            }
          />
        ) : (
          <>
            <div className="border-b border-line px-4 pb-3 pt-1">
              <label className="relative block max-w-xs">
                <span className="sr-only">Find a number</span>
                <Search
                  aria-hidden
                  className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
                />
                <input
                  type="search"
                  inputMode="tel"
                  autoComplete="off"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Find a number"
                  className={`${FIELD_INLINE_ICON} w-full`}
                />
              </label>
            </div>
            {shown.length === 0 ? (
              <EmptyState
                message="No suppressed number matches that."
                action={
                  <button type="button" onClick={() => setQuery("")} className={SECONDARY_BUTTON_SM}>
                    Clear search
                  </button>
                }
              />
            ) : (
              <DataTable
                rows={shown}
                columns={columns}
                getRowId={entryId}
                label="Numbers suppressed for every client"
                partialNote={truncated ? "Sorted within the most recently added only." : undefined}
              />
            )}
          </>
        )}
      </Card>

      <Drawer
        open={adding}
        onClose={() => setAdding(false)}
        title="Suppress numbers for every client"
        width="lg"
      >
        <SuppressForm access={write} mutation={suppress} />
      </Drawer>

      <Drawer
        open={releasingEntry !== undefined}
        onClose={() => setReleasingId(null)}
        title={releasingEntry ? `Release ${formatPhone(releasingEntry.phone_e164)}` : ""}
      >
        {releasingEntry && (
          <ReleaseConfirm
            key={releasingEntry.id}
            entry={releasingEntry}
            mutation={release}
            onDone={() => setReleasingId(null)}
          />
        )}
      </Drawer>
    </div>
  );
}

function entryId(entry: GlobalDncEntry): string {
  return entry.id;
}

/** A source this build cannot name still shows its raw value: a suppression an operator cannot explain is one they will be asked to. */
function sourceLabel(entry: GlobalDncEntry): string {
  return entry.source ? dncSourceCopy(entry.source).label : "No source recorded";
}

/*
 * `entry.removable` does NOT gate Release. It is `is_removable()`'s answer about CLIENTS
 * and is false on every row this endpoint returns; global suppressions are removed by
 * operations, through this router. A session without `ops:manage` is not offered the
 * menu at all — a Release that 403s teaches an operator our compliance rules are a bug.
 */
function buildColumns(
  mayRelease: boolean,
  onRelease: (id: string) => void,
): DataColumn<GlobalDncEntry>[] {
  const columns: DataColumn<GlobalDncEntry>[] = [
    {
      id: "number",
      header: "Number",
      cell: (entry) => (
        <div className="min-w-0">
          <span className="inline-flex items-center gap-1.5">
            <MonoValue className="whitespace-nowrap tabular-nums text-ink">
              {formatPhone(entry.phone_e164)}
            </MonoValue>
            <CopyButton value={entry.phone_e164} label={`Copy ${formatPhone(entry.phone_e164)}`} />
          </span>
          <p className="mt-0.5 text-xs text-ink-muted sm:hidden">
            {sourceLabel(entry)} · {formatIST(entry.added_at)}
          </p>
        </div>
      ),
    },
    {
      id: "source",
      header: "Source",
      hideBelow: "sm",
      cell: (entry) => <span className="text-xs text-ink-muted">{sourceLabel(entry)}</span>,
    },
    {
      id: "added",
      header: "Added",
      hideBelow: "sm",
      sort: { value: (entry) => entry.added_at, kind: "time", first: "desc" },
      cell: (entry) => (
        <span className="whitespace-nowrap text-xs text-ink-muted">{formatIST(entry.added_at)}</span>
      ),
    },
  ];
  if (!mayRelease) return columns;
  return [
    ...columns,
    {
      id: "actions",
      header: "Actions",
      renderHeader: () => null,
      align: "right",
      cell: (entry) => (
        <RowMenu
          label={formatPhone(entry.phone_e164)}
          items={[{ id: "release", label: "Release…", tone: "danger", onSelect: () => onRelease(entry.id) }]}
        />
      ),
    },
  ];
}
