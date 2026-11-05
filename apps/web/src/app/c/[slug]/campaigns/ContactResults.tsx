"use client";

import Link from "next/link";
import { useState } from "react";
import { PhoneCall, UserMinus } from "lucide-react";

import { ChipGroup } from "@/components/arc/chip-group";
import { useActionFeedback } from "@/components/arc/feedback";
import { FilterToolbar } from "@/components/arc/filter-toolbar";
import { RowMenu } from "@/components/arc/menu";
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
  useRemoveContacts,
  type ContactOutcome,
  type ContactResult,
} from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";
import { GOAL_WORDS } from "@/lib/callReview";

import { OUTCOME_ORDER, OUTCOME_WORDS } from "./CampaignResults";

const PAGE_SIZE = 50;

const CELL = "px-3 py-2.5 first:pl-4 last:pr-3 sm:first:pl-5";

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
 * A real table, kept to three columns so nothing scrolls sideways at 375px: the person
 * (with the number under the name), what happened (the outcome as a status mark, the tries
 * and the next one), and the row's one action. Before launch the second column is the
 * phone number, shown under the name on a phone instead, and the action is a ⋯ menu that
 * takes a person not yet tried off the list.
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
        className={TEXT_ACTION_SM}
        aria-label={`Open the call with ${who}`}
      >
        <PhoneCall aria-hidden className="h-3.5 w-3.5" />
        <span className="max-sm:sr-only">Open call</span>
      </Link>
    ) : editable && row.outcome === "not_called" ? (
      // One quiet ⋯ per row rather than a bordered button on every line: taking someone
      // off is occasional, and a column of identical buttons outweighs the names.
      <RowMenu
        label={who}
        items={[
          {
            id: "remove",
            label: "Take off this campaign",
            tone: "danger",
            icon: <UserMinus aria-hidden className="h-3.5 w-3.5" />,
            disabled: !canWrite,
            hint: refusal,
            ariaLabel: `Take ${who} off this campaign`,
            onSelect: () => removeFeedback.run([row.id]),
          },
        ]}
      />
    ) : null;
  const removing = (row: ContactResult) => remove.isPending && remove.variables?.[0] === row.id;

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
          <div className="overflow-hidden rounded-card border border-line">
            <table aria-label="People on this campaign" className="w-full table-fixed border-collapse text-left">
              <thead className="bg-surface-muted">
                <tr className="text-meta text-ink-muted">
                  <th scope="col" className={`${CELL} font-medium`}>
                    Person
                  </th>
                  {editable ? (
                    <th scope="col" className={`${CELL} hidden font-medium sm:table-cell`}>
                      Phone
                    </th>
                  ) : (
                    <th scope="col" className={`${CELL} font-medium`}>
                      What happened
                    </th>
                  )}
                  {/* `touch:w-17`: the ⋯ menu is 44px on a finger, and with the cell's 24px of padding a
                      56px column pushed it past the card's clipped edge. */}
                  <th scope="col" className={`${CELL} ${editable ? "w-14 touch:w-17" : "w-14 sm:w-32"}`}>
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.items.map((row) => {
                  const named = row.name?.trim();
                  const who = named || formatPhone(row.phone_e164);
                  return (
                    <tr
                      key={row.id}
                      aria-busy={removing(row) || undefined}
                      className={`align-middle transition-opacity duration-(--duration-fast) ${removing(row) ? "opacity-50" : ""}`}
                    >
                      <td className={CELL}>
                        <p className="text-body font-medium text-ink [overflow-wrap:anywhere]">{who}</p>
                        {named ? (
                          <p className={`text-meta tabular-nums text-ink-muted ${editable ? "sm:hidden" : ""}`}>
                            {formatPhone(row.phone_e164)}
                          </p>
                        ) : null}
                        {/* Before launch the only state worth a mark is one that stops a call. */}
                        {editable && row.outcome !== "not_called" ? (
                          <StatusPill tone={OUTCOME_TONE[row.outcome]} className="mt-1">
                            {OUTCOME_WORDS[row.outcome]}
                          </StatusPill>
                        ) : null}
                      </td>
                      {editable ? (
                        <td className={`${CELL} hidden text-body tabular-nums text-ink-muted sm:table-cell`}>
                          {named ? formatPhone(row.phone_e164) : ""}
                        </td>
                      ) : (
                        <td className={CELL}>
                          <PersonOutcome row={row} maxAttempts={maxAttempts} />
                        </td>
                      )}
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
      {/* The goal's why, so "Goal unclear" beside one person says what was missing. */}
      {row.goal_reached && row.goal_reason ? (
        <p className="max-w-prose text-meta text-ink-muted [text-wrap:pretty]">{row.goal_reason}</p>
      ) : null}
    </div>
  );
}
