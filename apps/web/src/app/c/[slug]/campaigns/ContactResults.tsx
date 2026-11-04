"use client";

import Link from "next/link";
import { useState } from "react";
import { PhoneCall } from "lucide-react";

import { ChipGroup } from "@/components/arc/chip-group";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { FilterToolbar } from "@/components/arc/filter-toolbar";
import { SearchField } from "@/components/arc/search-field";
import { EmptyState } from "@/components/console/emptyState";
import { STATE_DOT, StatusPill } from "@/components/console/statusPill";
import { Pagination } from "@/components/interior/pagination";
import {
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

/** Whether the person's latest answered call reached the campaign's goal. */
const GOAL_WORDS: Record<NonNullable<ContactResult["goal_reached"]>, string> = {
  yes: "Goal reached",
  no: "Goal not reached",
  unclear: "Goal unclear",
};

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
 * EVERY PERSON ON THE CAMPAIGN, with what happened (D-773): the heart of a launched
 * campaign's page. One row per person: who, what happened with the tries and the next
 * one, and the call itself as a button, because opening a call is what an owner does
 * here most. One page of the server's list at a time, filtered by outcome and searched by
 * name or the last digits of the number, so a list of five thousand stays a page.
 *
 * A row rather than a table: on a phone the three things a person row says have to stay
 * together, and a table hides its columns there; the row stacks them instead. Before
 * launch the same list names who will be called, and a person not yet tried can be taken
 * off.
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
    ...(search
      ? [
          {
            id: "search",
            label: `Search: ${search}`,
            onRemove: () => {
              setTyped("");
              runSearch("");
            },
          },
        ]
      : []),
  ];

  const action = (row: ContactResult, who: string) =>
    row.call_id ? (
      <Link
        href={href(`/c/${slug}/calls/${row.call_id}`)}
        className={SECONDARY_BUTTON_SM}
        aria-label={`Open the call with ${who}`}
      >
        <PhoneCall aria-hidden className="h-3.5 w-3.5" />
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
        aria-label={`Take ${who} off this campaign`}
      >
        Remove
      </ActionButton>
    ) : null;

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
          <ul aria-label="People on this campaign" className="divide-y divide-line border-y border-line">
            {data.items.map((row) => {
              const who = row.name?.trim() || formatPhone(row.phone_e164);
              return (
                <li
                  key={row.id}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_6.5rem] sm:gap-x-6"
                >
                  <div className="col-start-1 row-start-1 min-w-0">
                    <p className="truncate text-body font-medium text-ink">{who}</p>
                    {row.name?.trim() ? (
                      <p className="text-meta tabular-nums text-ink-muted">{formatPhone(row.phone_e164)}</p>
                    ) : null}
                  </div>
                  {editable ? null : (
                    <div className="col-start-1 row-start-2 min-w-0 sm:col-start-2 sm:row-start-1">
                      <PersonOutcome row={row} maxAttempts={maxAttempts} />
                    </div>
                  )}
                  <div className="col-start-2 row-span-2 row-start-1 self-center justify-self-end sm:col-start-3 sm:row-span-1">
                    {action(row, who)}
                  </div>
                </li>
              );
            })}
          </ul>
          {pages > 1 && <Pagination count={pages} page={page} onPageChange={setPage} label="People pages" />}
        </>
      )}
    </div>
  );
}

/** What happened to one person: the outcome, the tries used, and what comes next. */
function PersonOutcome({ row, maxAttempts }: { row: ContactResult; maxAttempts: number }) {
  const details = [
    row.goal_reached ? GOAL_WORDS[row.goal_reached] : null,
    row.attempts > 0 ? `Try ${formatCount(row.attempts)} of ${formatCount(maxAttempts)}` : null,
    row.will_retry && row.next_attempt_at
      ? `Next try ${formatIST(row.next_attempt_at)}`
      : row.last_attempt_at && row.outcome !== "calling"
        ? `Last ${formatIST(row.last_attempt_at)}`
        : null,
  ].filter((part): part is string => part !== null);
  return (
    <div className="min-w-0 space-y-0.5">
      <StatusPill tone={OUTCOME_TONE[row.outcome]} dot={row.outcome === "not_called" ? STATE_DOT.draft : undefined}>
        {OUTCOME_WORDS[row.outcome]}
      </StatusPill>
      {details.length > 0 ? <p className="text-meta text-ink-muted">{details.join(" · ")}</p> : null}
    </div>
  );
}
