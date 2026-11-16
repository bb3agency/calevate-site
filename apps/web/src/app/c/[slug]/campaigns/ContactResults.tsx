"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { PhoneCall } from "lucide-react";

import { ChipGroup } from "@/components/arc/chip-group";
import { useActionFeedback } from "@/components/arc/feedback";
import { FilterToolbar } from "@/components/arc/filter-toolbar";
import { SearchField } from "@/components/arc/search-field";
import { EmptyState } from "@/components/console/emptyState";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { STATE_DOT, StatusPill } from "@/components/console/statusPill";
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
  useIncludeContacts,
  type ContactOutcome,
  type ContactResult,
} from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";
import { GOAL_WORDS } from "@/lib/callReview";

import { OUTCOME_ORDER, OUTCOME_WORDS } from "./CampaignResults";

const PAGE_SIZE = 10;

const CELL = "px-3 py-3 first:pl-0 last:pr-0";

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
 * Columns: the include box, the person, their number (under the name on a phone), the
 * status (what happened, the tries and the next one), and the row's one action. The box
 * only decides whether a person may be dialled; who is actually rung still follows each
 * person's own status, so "include everyone" never re-calls people already reached
 * (founder, 16 Nov 2026).
 */
export function ContactResults({
  slug,
  campaignId,
  maxAttempts,
  live,
  canWrite,
  refusal,
}: {
  slug: string;
  campaignId: string;
  maxAttempts: number;
  live: boolean;
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
  const include = useIncludeContacts(session, campaignId);
  useActionFeedback(include, { errorTitle: "Could not change who is included" });
  const data = people.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  // A page that lost its rows (the last person taken off, everyone under "Calling" moving
  // on) steps back to the last page that has some, rather than saying nobody matches. Only
  // on the server's answer for THIS page, never on the previous page's placeholder.
  const settledPages = data && !people.isPlaceholderData ? pages : undefined;
  useEffect(() => {
    if (settledPages !== undefined && page > settledPages) setPage(settledPages);
  }, [page, settledPages]);
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
        className={TEXT_ACTION_SM}
        aria-label={`Open the call with ${who}`}
      >
        <PhoneCall aria-hidden className="h-3.5 w-3.5" />
        <span className="max-sm:sr-only">Open call</span>
      </Link>
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
          shown.length > 1 ? (
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
          <div className="border-y border-line">
            <table aria-label="People on this campaign" className="w-full table-fixed border-collapse text-left">
              <thead className="border-b border-line">
                <tr className="text-meta text-ink-muted">
                  <th scope="col" className={`${CELL} w-10`}>
                    <IncludeAll
                      included={data.included ?? 0}
                      everyone={data.everyone ?? 0}
                      disabled={!canWrite || include.isPending}
                      refusal={refusal}
                      onChange={(on) => include.mutate({ all: true, included: on })}
                    />
                  </th>
                  <th scope="col" className={`${CELL} font-medium sm:w-44 lg:w-56`}>
                    Person
                  </th>
                  <th scope="col" className={`${CELL} hidden w-40 font-medium sm:table-cell`}>
                    Phone
                  </th>
                  <th scope="col" className={`${CELL} font-medium`}>
                    Status
                  </th>
                  <th scope="col" className={`${CELL} w-14 sm:w-32`}>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.items.map((row) => {
                  const named = row.name?.trim();
                  const who = named || formatPhone(row.phone_e164);
                  return (
                    <tr key={row.id} className="align-middle">
                      <td className={CELL}>
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-brand-strong touch:h-5 touch:w-5"
                          checked={row.included ?? true}
                          disabled={!canWrite || include.isPending}
                          title={refusal}
                          aria-label={`Include ${who} in this campaign`}
                          onChange={(e) => include.mutate({ all: false, contact_ids: [row.id], included: e.target.checked })}
                        />
                      </td>
                      <td className={CELL}>
                        <p
                          className={`text-body font-medium [overflow-wrap:anywhere] ${row.included === false ? "text-ink-muted" : "text-ink"}`}
                        >
                          {who}
                        </p>
                        {named ? (
                          <p className="text-meta tabular-nums text-ink-muted sm:hidden">{formatPhone(row.phone_e164)}</p>
                        ) : null}
                      </td>
                      <td className={`${CELL} hidden text-body tabular-nums text-ink-muted sm:table-cell`}>
                        {named ? formatPhone(row.phone_e164) : ""}
                      </td>
                      <td className={CELL}>
                        <PersonOutcome row={row} maxAttempts={maxAttempts} />
                      </td>
                      <td className={`${CELL} text-right`}>{action(row, who)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {pages > 1 && <Pagination count={pages} page={page} onPageChange={setPage} label="People pages" />}
        </>
      )}
    </div>
  );
}

/**
 * The header box: ticked when everyone is included, a dash when some are. Pressing it
 * includes everyone (or, when all are in, leaves everyone out); each person is still
 * dialled by their own status.
 */
function IncludeAll({
  included,
  everyone,
  disabled,
  refusal,
  onChange,
}: {
  included: number;
  everyone: number;
  disabled: boolean;
  refusal: string | undefined;
  onChange: (on: boolean) => void;
}) {
  const box = useRef<HTMLInputElement>(null);
  const all = everyone > 0 && included === everyone;
  const some = included > 0 && !all;
  useEffect(() => {
    if (box.current) box.current.indeterminate = some;
  }, [some]);
  return (
    <input
      ref={box}
      type="checkbox"
      className="h-4 w-4 accent-brand-strong touch:h-5 touch:w-5"
      checked={all}
      disabled={disabled}
      title={refusal ?? `${formatCount(included)} of ${formatCount(everyone)} included`}
      aria-label={all ? "Leave everyone out of this campaign" : "Include everyone in this campaign"}
      onChange={() => onChange(!all)}
    />
  );
}

/** What happened to one person: the outcome, the tries used, and what comes next. */
function PersonOutcome({ row, maxAttempts }: { row: ContactResult; maxAttempts: number }) {
  if (row.included === false && row.attempts === 0) {
    return <p className="text-meta text-ink-muted">Not included, so not called</p>;
  }
  const details = [
    row.business_outcome_label ?? null,
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
      {row.included === false ? <p className="text-meta text-ink-muted">Not included: no more calls</p> : null}
      {/* The goal's why, so "Goal unclear" beside one person says what was missing. */}
      {row.goal_reached && row.goal_reason ? (
        <p className="max-w-prose text-meta text-ink-muted [text-wrap:pretty]">{row.goal_reason}</p>
      ) : null}
    </div>
  );
}
