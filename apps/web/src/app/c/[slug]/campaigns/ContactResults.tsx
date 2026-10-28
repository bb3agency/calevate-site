"use client";

import Link from "next/link";
import { useState } from "react";

import { ChipGroup } from "@/components/arc/chip-group";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { FilterToolbar } from "@/components/arc/filter-toolbar";
import { SearchField } from "@/components/arc/search-field";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { Pagination } from "@/components/interior/pagination";
import {
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
  // What is typed, and the settled query the server is asked for (`SearchField.onSearch`).
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const people = useContactResults(session, campaignId, { page, pageSize: PAGE_SIZE, outcome, search }, live);
  const remove = useRemoveContacts(session, campaignId);
  // The row leaves the list on success, so the toast is where the result is said.
  const removeFeedback = useActionFeedback(remove, {
    errorTitle: "Could not take this person off",
    successToast: "Taken off this campaign",
  });
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
          <Link href={href(`/c/${slug}/calls/${row.call_id}`)} className={`${TEXT_ACTION_SM} -mr-2 whitespace-nowrap`}>
            Open call
          </Link>
        ) : editable && row.outcome === "not_called" ? (
          <ActionButton
            variant="secondary-sm"
            title={refusal}
            disabled={!canWrite}
            status={remove.variables?.[0] === row.id ? removeFeedback.status : "idle"}
            pendingLabel="Removing"
            successLabel="Removed"
            onClick={() => removeFeedback.run([row.id])}
            aria-label={`Take ${row.name?.trim() || formatPhone(row.phone_e164)} off this campaign`}
          >
            Remove
          </ActionButton>
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

  const runSearch = (query: string) => {
    setSearch(query);
    setPage(1);
  };
  const clearAll = () => {
    setTyped("");
    runSearch("");
    choose(undefined);
  };
  const active = [
    ...(outcome ? [{ id: "outcome", label: `Outcome: ${OUTCOME_WORDS[outcome]}`, onRemove: () => choose(undefined) }] : []),
    ...(search ? [{ id: "search", label: `Search: ${search}`, onRemove: () => {
      setTyped("");
      runSearch("");
    } }] : []),
  ];

  return (
    <div className="space-y-4">
      <FilterToolbar
        search={
          <SearchField
            label="Search people by name or the end of their number"
            hideLabel
            placeholder="Name or last digits"
            value={typed}
            onValueChange={setTyped}
            onSearch={runSearch}
            className="w-full sm:w-56"
          />
        }
        filters={
          !editable && shown.length > 0 ? (
            <ChipGroup
              mode="single"
              label="Show people by outcome"
              value={outcome ?? null}
              onChange={(next) => choose((next ?? undefined) as ContactOutcome | undefined)}
              allLabel={data ? `Everyone ${formatCount(all)}` : "Everyone"}
              chips={shown.map((o) => ({ value: o, label: `${OUTCOME_WORDS[o]} ${formatCount(data?.counts[o] ?? 0)}` }))}
            />
          ) : undefined
        }
        active={active}
        onClearAll={clearAll}
        count={data ? { shown: data.total, total: all, noun: "person", nounPlural: "people" } : undefined}
      />
      {people.isLoading ? (
        <Skeleton rows={4} />
      ) : !data ? (
        <EmptyState
          variant="error"
          message="The people on this campaign did not load."
          error={people.error}
          onRetry={() => void people.refetch()}
        />
      ) : data.items.length === 0 ? (
        all === 0 ? (
          <EmptyState message="Nobody is on this campaign yet." />
        ) : (
          <EmptyState variant="filtered" message="Nobody matches." onClear={clearAll} clearLabel="Show everyone" />
        )
      ) : (
        <>
          <DataTable label="People on this campaign" rows={data.items} columns={columns} getRowId={(row) => row.id} />
          {pages > 1 && <Pagination count={pages} page={page} onPageChange={setPage} label="People pages" />}
        </>
      )}
    </div>
  );
}
