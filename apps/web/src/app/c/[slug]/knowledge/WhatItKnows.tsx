"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, Pin } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { SearchField } from "@/components/arc/search-field";
import { EmptyState } from "@/components/console/emptyState";
import { Section } from "@/components/console/section";
import {
  FIELD,
  FIELD_LABEL,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import type { useKbSources } from "@/lib/api/kb";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { useVerticalExamples } from "@/lib/useVerticalExamples";
import { lookup } from "@/lib/lookup";
import {
  useAddFact,
  useEditFact,
  useKnows,
  useRemoveFact,
  useReorderPinned,
  type Fact,
  type KnownItem,
  type PinnedNotYetOn,
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
  const clearQuery = () => setQuery("");

  const pinned = useMemo(() => knows.data?.facts.filter((f) => f.pinned) ?? [], [knows.data]);
  const other = useMemo(() => knows.data?.facts.filter((f) => !f.pinned) ?? [], [knows.data]);

  if (knows.isLoading) return <Skeleton rows={5} label="Loading what your agents know" />;
  if (knows.error || !knows.data) {
    return (
      <EmptyState
        variant="error"
        message="We could not load what your agents know."
        error={knows.error}
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
        <SearchField
          label="Search what your agents know"
          hideLabel
          value={query}
          onValueChange={setQuery}
          placeholder="Search"
          className="max-w-sm"
        />
      ) : null}

      <PinnedFacts
        facts={shownPinned}
        all={pinned}
        canWrite={canWrite}
        filtered={query.trim() !== ""}
        onClearFilter={clearQuery}
        notYetOn={knows.data.pinned_not_yet_on}
      />

      <Section
        title="Facts"
        headingLevel={3}
        info={<p>Found and used when a caller asks about them.</p>}
        action={
          knows.data.facts_state === "publishing" && other.length ? (
            <span className="text-shimmer text-meta text-ink-muted">Reaching your agents…</span>
          ) : knows.data.facts_state === "in_review" ? (
            <span className="text-meta text-ink-muted">Waiting for review</span>
          ) : undefined
        }
      >
        {shownOther.length === 0 ? (
          other.length ? (
            <NoMatch message="No facts match your search." onClear={clearQuery} />
          ) : (
            <p className="text-meta text-ink-muted">Facts you teach above appear here.</p>
          )
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
          knows.data.items.length ? (
            <NoMatch message="No documents, photos or pages match your search." onClear={clearQuery} />
          ) : (
            <p className="text-meta text-ink-muted">Add these under Files and pages.</p>
          )
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

/** A list the search emptied: says so, and offers the way back. */
function NoMatch({ message, onClear }: { message: string; onClear: () => void }) {
  return (
    <EmptyState
      variant="filtered"
      align="start"
      className="py-4"
      message={message}
      onClear={onClear}
      clearLabel="Clear the search"
    />
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
  onClearFilter,
  notYetOn,
}: {
  facts: Fact[];
  all: Fact[];
  canWrite: boolean;
  filtered: boolean;
  onClearFilter: () => void;
  /** Agents whose live instructions do not carry these facts yet, with the server's reason. */
  notYetOn: PinnedNotYetOn[];
}) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const [adding, setAdding] = useState(false);
  const reorder = useReorderPinned(session);
  // The refusal is drawn above the list; the new order is the success.
  const reorderFeedback = useActionFeedback(reorder, { errorDisplay: "inline" });
  /** Which arrow was pressed, so only that one shows the move's state. */
  const [pressed, setPressed] = useState<string | null>(null);

  const move = (index: number, by: -1 | 1) => {
    const ids = all.map((f) => f.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + by, 0, moved!);
    setPressed(`${moved}:${by}`);
    reorderFeedback.run(ids);
  };
  const arrowStatus = (id: string, by: -1 | 1) =>
    pressed === `${id}:${by}` ? reorderFeedback.status : "idle";

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
      {notYetOn.length > 0 ? (
        <ul className="space-y-1" aria-label="Agents that do not have these facts yet">
          {notYetOn.map((entry) => (
            <li
              key={entry.agent_id}
              className={`text-meta ${entry.reason === "on_the_way" ? "text-ink-muted" : "text-warn"}`}
            >
              {entry.sentence}
              {entry.reason !== "on_the_way" ? (
                <>
                  {" "}
                  <Link
                    href={href(`/c/${session.orgSlug}/agents/${entry.agent_id}?section=script`)}
                    className="underline underline-offset-2"
                  >
                    Open {entry.agent_name}&rsquo;s script
                  </Link>
                </>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {facts.length === 0 && !adding ? (
        all.length && filtered ? (
          <NoMatch message="No pinned facts match your search." onClear={onClearFilter} />
        ) : (
          <p className="text-meta text-ink-muted">Nothing pinned yet. Pin a fact when you teach it.</p>
        )
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
                      {/* Icon-only faces (null labels) keep each arrow its own width. */}
                      <ActionButton
                        variant="secondary-sm"
                        aria-label="Move up"
                        status={arrowStatus(fact.id, -1)}
                        pendingLabel={null}
                        successLabel={null}
                        errorLabel={null}
                        disabled={index === 0 || (reorder.isPending && arrowStatus(fact.id, -1) !== "pending")}
                        onClick={() => move(index, -1)}
                      >
                        <ArrowUp aria-hidden className="h-3.5 w-3.5" />
                      </ActionButton>
                      <ActionButton
                        variant="secondary-sm"
                        aria-label="Move down"
                        status={arrowStatus(fact.id, 1)}
                        pendingLabel={null}
                        successLabel={null}
                        errorLabel={null}
                        disabled={
                          index === all.length - 1 || (reorder.isPending && arrowStatus(fact.id, 1) !== "pending")
                        }
                        onClick={() => move(index, 1)}
                      >
                        <ArrowDown aria-hidden className="h-3.5 w-3.5" />
                      </ActionButton>
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
  // The form closes on success and the fact appears in the list; a refusal stays here.
  const addFeedback = useActionFeedback(add, { errorDisplay: "inline" });
  // A question and its answer written as one pair (D-827), so the answer always fits the
  // question shown above it.
  const eg = useVerticalExamples();
  return (
    <form
      className="mb-4 max-w-2xl space-y-3"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (answer.trim() && !add.isPending)
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
          placeholder={eg.factQuestion}
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
          placeholder={eg.factAnswer}
          className={FIELD}
        />
      </div>
      {add.error ? <ProblemNotice error={add.error} /> : null}
      <div className="flex gap-2">
        <ActionButton
          type="submit"
          variant="primary-sm"
          status={addFeedback.status}
          pendingLabel="Adding…"
          successLabel="Added"
          disabled={!answer.trim()}
        >
          Add
        </ActionButton>
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
  const editFeedback = useActionFeedback(edit, { errorDisplay: "inline" });
  // The row leaves the list on success, so the toast is where that is said.
  const removeFeedback = useActionFeedback(remove, {
    errorDisplay: "inline",
    successToast: "Fact removed",
  });
  /** `edit` both saves the text and pins; only the control that started it shows its state. */
  const [editKind, setEditKind] = useState<"text" | "pin">("text");
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
            if (!text.trim() || busy) return;
            setEditKind("text");
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
            <ActionButton
              type="submit"
              variant="primary-sm"
              status={editKind === "text" ? editFeedback.status : "idle"}
              pendingLabel="Saving…"
              successLabel="Saved"
              disabled={!text.trim() || remove.isPending}
            >
              Save
            </ActionButton>
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
            // Wraps within itself on a phone: the kit buttons are as wide as their widest face.
            <div className="flex min-w-0 flex-wrap gap-1.5">
              {ordering}
              <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setEditing(true)} disabled={busy}>
                Edit
              </button>
              <ActionButton
                variant="secondary-sm"
                status={editKind === "pin" ? editFeedback.status : "idle"}
                successLabel={fact.pinned ? "Pinned" : "Unpinned"}
                disabled={remove.isPending || (edit.isPending && editKind !== "pin")}
                onClick={() => {
                  setEditKind("pin");
                  editFeedback.run({ id: fact.id, pinned: !fact.pinned });
                }}
              >
                {fact.pinned ? "Unpin" : "Pin"}
              </ActionButton>
              <ActionButton
                variant="secondary-sm"
                status={removeFeedback.status}
                successLabel="Removed"
                disabled={edit.isPending}
                onClick={() => removeFeedback.run(fact.id)}
              >
                Remove
              </ActionButton>
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
