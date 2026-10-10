"use client";

import { useId, useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, Pin, Search } from "lucide-react";

import { Section } from "@/components/console/section";
import {
  FIELD,
  FIELD_INLINE_ICON,
  FIELD_LABEL,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import type { useKbSources } from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";
import {
  useAddFact,
  useEditFact,
  useKnows,
  useRemoveFact,
  useReorderPinned,
  type Fact,
  type KnownItem,
} from "@/lib/api/teach";

import { SourcesList } from "./SourcesList";

const KIND_LABEL: Record<string, string> = {
  document: "Document",
  photo: "Photo",
  page: "Web page",
};

const STATE_LABEL: Record<string, string | null> = {
  live: null,
  getting_ready: "Getting ready",
  in_review: "Waiting for review",
  needs_attention: "Needs attention — see Files and pages",
};

function matches(query: string, ...values: (string | null | undefined)[]): boolean {
  const q = query.trim().toLocaleLowerCase();
  return !q || values.some((value) => value?.toLocaleLowerCase().includes(q));
}

/**
 * WHAT THE AGENTS KNOW, in one searchable list: pinned facts first (always in every
 * agent's instructions, and they win over anything else), then the other facts, then
 * documents, photos, web pages and older notes. Every row is shared by all the agents.
 */
export function WhatItKnows({
  canWrite,
  sources,
}: {
  canWrite: boolean;
  sources: ReturnType<typeof useKbSources>;
}) {
  const session = useClientSession();
  const knows = useKnows(session);
  const [query, setQuery] = useState("");
  const searchId = useId();

  const pinned = useMemo(() => knows.data?.facts.filter((f) => f.pinned) ?? [], [knows.data]);
  const other = useMemo(() => knows.data?.facts.filter((f) => !f.pinned) ?? [], [knows.data]);

  if (knows.isLoading) return <Skeleton rows={5} label="Loading what your agents know" />;
  if (knows.error || !knows.data) {
    return (
      <ProblemNotice
        error={knows.error ?? new Error("We could not load what your agents know.")}
        onRetry={() => void knows.refetch()}
      />
    );
  }

  const shownPinned = pinned.filter((f) => matches(query, f.text, f.question));
  const shownOther = other.filter((f) => matches(query, f.text));
  const shownItems = knows.data.items.filter((i) => matches(query, i.name, i.url));
  const empty = pinned.length + other.length + knows.data.items.length === 0;

  return (
    <div className="space-y-8">
      <p className="text-meta text-ink-muted">Every one of your agents knows all of this.</p>

      {!empty ? (
        <div className="relative max-w-sm">
          <label htmlFor={searchId} className="sr-only">
            Search what your agents know
          </label>
          <Search aria-hidden className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-ink-faint" />
          <input
            id={searchId}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search"
            className={`${FIELD_INLINE_ICON} w-full`}
          />
        </div>
      ) : null}

      <PinnedFacts facts={shownPinned} all={pinned} canWrite={canWrite} filtered={query.trim() !== ""} />

      <Section
        title="Facts"
        headingLevel={3}
        info={<p>Found and used when a caller asks about them.</p>}
        action={
          knows.data.facts_state === "publishing" && other.length ? (
            <span className="text-meta text-ink-muted">Reaching your agents…</span>
          ) : knows.data.facts_state === "in_review" ? (
            <span className="text-meta text-ink-muted">Waiting for review</span>
          ) : undefined
        }
      >
        {shownOther.length === 0 ? (
          <p className="text-meta text-ink-muted">
            {other.length ? "No facts match." : "Facts you teach above appear here."}
          </p>
        ) : (
          <ul className="divide-y divide-line border-y border-line">
            {shownOther.map((fact) => (
              <FactRow key={fact.id} fact={fact} canWrite={canWrite} />
            ))}
          </ul>
        )}
      </Section>

      <Section title="Documents, photos and pages" headingLevel={3}>
        {shownItems.length === 0 ? (
          <p className="text-meta text-ink-muted">
            {knows.data.items.length ? "Nothing matches." : "Add these under Files and pages."}
          </p>
        ) : (
          <ul className="divide-y divide-line border-y border-line">
            {shownItems.map((item) => (
              <ItemRow key={item.id} item={item} />
            ))}
          </ul>
        )}
      </Section>

      <SourcesList sources={sources} only="facts" />
    </div>
  );
}

function ItemRow({ item }: { item: KnownItem }) {
  const state = lookup(STATE_LABEL, item.state) ?? null;
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5">
      <div className="min-w-0">
        <p className="truncate text-sm text-ink" title={item.name}>
          {item.name}
        </p>
        {item.url ? (
          <p className="truncate text-meta text-ink-faint" title={item.url}>
            {item.url}
          </p>
        ) : null}
      </div>
      <p className="shrink-0 text-meta text-ink-muted">
        {lookup(KIND_LABEL, item.kind) ?? "Document"}
        {state ? <span className={item.state === "needs_attention" ? "text-warn" : ""}> · {state}</span> : null}
      </p>
    </li>
  );
}

function PinnedFacts({
  facts,
  all,
  canWrite,
  filtered,
}: {
  facts: Fact[];
  all: Fact[];
  canWrite: boolean;
  filtered: boolean;
}) {
  const session = useClientSession();
  const [adding, setAdding] = useState(false);
  const reorder = useReorderPinned(session);

  const move = (index: number, by: -1 | 1) => {
    const ids = all.map((f) => f.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + by, 0, moved!);
    reorder.mutate(ids);
  };

  return (
    <Section
      title="Pinned facts"
      headingLevel={3}
      info={
        <p>
          Read by every agent on every call, and they win over anything else it finds. Keep
          them short: prices, timings, delivery areas.
        </p>
      }
      action={
        canWrite && !adding ? (
          <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setAdding(true)}>
            Add a pinned fact
          </button>
        ) : undefined
      }
    >
      {adding ? <PinnedForm onDone={() => setAdding(false)} /> : null}
      {reorder.error ? <ProblemNotice error={reorder.error} /> : null}
      {facts.length === 0 && !adding ? (
        <p className="text-meta text-ink-muted">
          {all.length ? "No pinned facts match." : "Nothing pinned yet. Pin a fact when you teach it."}
        </p>
      ) : (
        <ul className="divide-y divide-line border-y border-line" aria-label="Pinned facts">
          {facts.map((fact) => {
            const index = all.findIndex((f) => f.id === fact.id);
            return (
              <FactRow
                key={fact.id}
                fact={fact}
                canWrite={canWrite}
                ordering={
                  canWrite && !filtered && all.length > 1 ? (
                    <span className="flex gap-1">
                      <button
                        type="button"
                        aria-label="Move up"
                        className={SECONDARY_BUTTON_SM}
                        disabled={index === 0 || reorder.isPending}
                        onClick={() => move(index, -1)}
                      >
                        <ArrowUp aria-hidden className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        aria-label="Move down"
                        className={SECONDARY_BUTTON_SM}
                        disabled={index === all.length - 1 || reorder.isPending}
                        onClick={() => move(index, 1)}
                      >
                        <ArrowDown aria-hidden className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  ) : null
                }
              />
            );
          })}
        </ul>
      )}
    </Section>
  );
}

function PinnedForm({ onDone }: { onDone: () => void }) {
  const session = useClientSession();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const add = useAddFact(session);
  return (
    <form
      className="mb-4 max-w-2xl space-y-3"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (answer.trim())
          add.mutate(
            { text: answer.trim(), question: question.trim() || null, pinned: true },
            { onSuccess: onDone },
          );
      }}
    >
      <div>
        <label htmlFor="pinned-question" className={FIELD_LABEL}>
          What callers ask (optional)
        </label>
        <input
          id="pinned-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Do you deliver on Sundays?"
          className={FIELD}
        />
      </div>
      <div>
        <label htmlFor="pinned-answer" className={FIELD_LABEL}>
          The fact
        </label>
        <textarea
          id="pinned-answer"
          rows={2}
          value={answer}
          onChange={(event) => setAnswer(event.target.value)}
          placeholder="No, we deliver Monday to Saturday."
          className={FIELD}
        />
      </div>
      {add.error ? <ProblemNotice error={add.error} /> : null}
      <div className="flex gap-2">
        <button type="submit" className={PRIMARY_BUTTON_SM} disabled={!answer.trim() || add.isPending}>
          {add.isPending ? "Adding…" : "Add"}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function FactRow({
  fact,
  canWrite,
  ordering,
}: {
  fact: Fact;
  canWrite: boolean;
  ordering?: ReactNode;
}) {
  const session = useClientSession();
  const edit = useEditFact(session);
  const remove = useRemoveFact(session);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(fact.text);
  const [question, setQuestion] = useState(fact.question ?? "");
  const busy = edit.isPending || remove.isPending;
  const error = edit.error ?? remove.error;

  return (
    <li className="py-3">
      {editing ? (
        <form
          className="space-y-2"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (!text.trim()) return;
            edit.mutate(
              {
                id: fact.id,
                text: text.trim(),
                ...(fact.pinned ? { question: question.trim() } : {}),
              },
              { onSuccess: () => setEditing(false) },
            );
          }}
        >
          {fact.pinned ? (
            <input
              aria-label="What callers ask"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="What callers ask (optional)"
              className={`${FIELD} mt-0`}
            />
          ) : null}
          <textarea
            aria-label="The fact"
            rows={2}
            value={text}
            onChange={(event) => setText(event.target.value)}
            className={`${FIELD} mt-0`}
          />
          <div className="flex gap-2">
            <button type="submit" className={PRIMARY_BUTTON_SM} disabled={busy || !text.trim()}>
              {edit.isPending ? "Saving…" : "Save"}
            </button>
            <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            {fact.question ? <p className="text-meta text-ink-muted">{fact.question}</p> : null}
            <p className="text-sm text-ink [overflow-wrap:anywhere]">
              {fact.pinned ? <Pin aria-label="Pinned" className="mr-1.5 inline h-3.5 w-3.5 text-brand-strong" /> : null}
              {fact.text}
            </p>
          </div>
          {canWrite ? (
            <div className="flex shrink-0 flex-wrap gap-1.5">
              {ordering}
              <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setEditing(true)} disabled={busy}>
                Edit
              </button>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={busy}
                onClick={() => edit.mutate({ id: fact.id, pinned: !fact.pinned })}
              >
                {fact.pinned ? "Unpin" : "Pin"}
              </button>
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={busy}
                onClick={() => remove.mutate(fact.id)}
              >
                {remove.isPending ? "Removing…" : "Remove"}
              </button>
            </div>
          ) : null}
        </div>
      )}
      {error ? (
        <div className="mt-2">
          <ProblemNotice error={error} />
        </div>
      ) : null}
    </li>
  );
}
