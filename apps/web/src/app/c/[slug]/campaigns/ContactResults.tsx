"use client";

import Link from "next/link";
import { useState } from "react";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { StatusPill } from "@/components/console/statusPill";
import { Pagination } from "@/components/interior/pagination";
import {
  FIELD,
  FilterChip,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatIST,
  formatPhone,
  type NoticeTone,
} from "@/components/ui";
import {
  useContactResults,
  useRemoveContacts,
  type ContactOutcome,
  type ContactResult,
} from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";

import { OUTCOME_ORDER, OUTCOME_WORDS } from "./CampaignResults";

const PAGE_SIZE = 50;

const OUTCOME_TONE: Record<ContactOutcome, NoticeTone> = {
  connected: "ok",
  no_answer: "neutral",
  busy: "neutral",
  voicemail: "neutral",
  failed: "warn",
  do_not_call: "stop",
  calling: "ok",
  not_called: "neutral",
};

/**
 * EVERY PERSON ON THE CAMPAIGN, with what happened (D-773): outcome, tries used, the next
 * try, and the call itself. One page of the server's list at a time, filtered by outcome
 * and searched by name or the last digits of the number, so a list of five thousand stays
 * a page. Before launch the same table lists who will be called, and a person not yet
 * tried can be taken off.
 */
export function ContactResults({
  slug,
  campaignId,
  maxAttempts,
  live,
  editable,
  canWrite,
  refusal,
}: {
  slug: string;
  campaignId: string;
  maxAttempts: number;
  live: boolean;
  /** A draft or scheduled campaign: people not yet tried can be removed. */
  editable: boolean;
  canWrite: boolean;
  refusal: string | undefined;
}) {
  const { session, href } = useClientRealm();
  const [outcome, setOutcome] = useState<ContactOutcome | undefined>();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const people = useContactResults(session, campaignId, { page, pageSize: PAGE_SIZE, outcome, search }, live);
  const remove = useRemoveContacts(session, campaignId);
  const data = people.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const all = data ? Object.values(data.counts).reduce((a, b) => a + b, 0) : 0;

  const allColumns: DataColumn<ContactResult>[] = [
    {
      id: "person",
      header: "Person",
      cell: (row) => (
        <div className="min-w-0">
          <p className="truncate text-body font-medium text-ink">{row.name?.trim() || formatPhone(row.phone_e164)}</p>
          {row.name?.trim() ? <p className="text-meta text-ink-muted">{formatPhone(row.phone_e164)}</p> : null}
        </div>
      ),
    },
    {
      id: "outcome",
      header: "Outcome",
      cell: (row) => (
        <div className="space-y-0.5">
          <StatusPill tone={OUTCOME_TONE[row.outcome]}>{OUTCOME_WORDS[row.outcome]}</StatusPill>
          {row.will_retry && row.next_attempt_at ? (
            <p className="text-meta text-ink-muted">Next try {formatIST(row.next_attempt_at)}</p>
          ) : null}
        </div>
      ),
      flash: (row) => row.outcome,
    },
    {
      id: "tries",
      header: "Tries",
      cell: (row) => (
        <span className="tabular-nums text-body text-ink-muted">
          {row.attempts} of {maxAttempts}
        </span>
      ),
      hideBelow: "sm",
    },
    {
      id: "last",
      header: "Last try",
      cell: (row) => (
        <span className="whitespace-nowrap text-meta text-ink-muted">
          {row.last_attempt_at ? formatIST(row.last_attempt_at) : "—"}
        </span>
      ),
      hideBelow: "md",
    },
    {
      id: "action",
      header: editable ? "Remove" : "Call",
      align: "right",
      cell: (row) =>
        row.call_id ? (
          <Link href={href(`/c/${slug}/calls/${row.call_id}`)} className="whitespace-nowrap text-meta font-medium text-ink underline underline-offset-2">
            Open call
          </Link>
        ) : editable && row.outcome === "not_called" ? (
          <button
            type="button"
            title={refusal}
            disabled={!canWrite || remove.isPending}
            onClick={() => remove.mutate([row.id])}
            aria-label={`Take ${row.name?.trim() || formatPhone(row.phone_e164)} off this campaign`}
            className={SECONDARY_BUTTON_SM}
          >
            Remove
          </button>
        ) : null,
    },
  ];
  // Before launch every row would read "Not called yet · 0 of 3 · —": the person and the
  // way to take them off are all a draft's list has to say.
  const columns = editable ? allColumns.filter((c) => c.id === "person" || c.id === "action") : allColumns;
  const shown = OUTCOME_ORDER.filter((o) => (data?.counts[o] ?? 0) > 0);
  const choose = (next: ContactOutcome | undefined) => {
    setOutcome(next);
    setPage(1);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        {!editable && (
          <>
            {/* Eight chips wrap to three rows on a phone; there it is one native picker. */}
            <label className="block w-full sm:hidden">
              <span className="sr-only">Show people by outcome</span>
              <select
                value={outcome ?? ""}
                onChange={(e) => choose((e.target.value || undefined) as ContactOutcome | undefined)}
                className={FIELD}
              >
                <option value="">{data ? `Everyone (${formatCount(all)})` : "Everyone"}</option>
                {shown.map((o) => (
                  <option key={o} value={o}>
                    {OUTCOME_WORDS[o]} ({formatCount(data?.counts[o] ?? 0)})
                  </option>
                ))}
              </select>
            </label>
            <div role="group" aria-label="Show people by outcome" className="hidden flex-wrap gap-1.5 sm:flex">
              <FilterChip
                label={data ? `Everyone ${formatCount(all)}` : "Everyone"}
                active={outcome === undefined}
                onClick={() => choose(undefined)}
              />
              {shown.map((o) => (
                <FilterChip
                  key={o}
                  label={`${OUTCOME_WORDS[o]} ${formatCount(data?.counts[o] ?? 0)}`}
                  active={outcome === o}
                  onClick={() => choose(o)}
                />
              ))}
            </div>
          </>
        )}
        <label className="block w-full sm:w-56">
          <span className="sr-only">Search people by name or the end of their number</span>
          <input
            type="search"
            value={search}
            placeholder="Name or last digits"
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className={FIELD}
          />
        </label>
      </div>
      {remove.error ? <ProblemNotice error={remove.error} /> : null}
      {people.isLoading ? (
        <Skeleton rows={4} />
      ) : !data ? (
        <ProblemNotice
          error={people.error ?? new Error("The people on this campaign did not load.")}
          onRetry={() => people.refetch()}
        />
      ) : data.items.length === 0 ? (
        <p className="text-body text-ink-muted">
          {all === 0 ? "Nobody is on this campaign yet." : "Nobody matches. Clear the search or choose Everyone."}
        </p>
      ) : (
        <>
          <DataTable label="People on this campaign" rows={data.items} columns={columns} getRowId={(row) => row.id} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-meta text-ink-muted">
              {formatCount(data.total)} {data.total === 1 ? "person" : "people"}
            </p>
            {pages > 1 && <Pagination count={pages} page={page} onPageChange={setPage} label="People pages" />}
          </div>
        </>
      )}
    </div>
  );
}
