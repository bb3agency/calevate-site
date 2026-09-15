"use client";

import { AlertTriangle, CheckCircle2, Clock, FileQuestion } from "lucide-react";

import {
  Card,
  EmptyState,
  MonoValue,
  NOTICE_TONES,
  ProblemNotice,
  Skeleton,
  formatIST,
} from "@/components/ui";
import { useKbDelivery, type AgentDelivery, type DeliveryState } from "@/lib/api/kb";
import { useClientSession } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

/**
 * "Is what I published actually on the phone?" — the answer that did not exist.
 *
 * ## Why this is a separate card from the submitted list
 *
 * `SubmittedList` answers "did a human approve my document", which is a question about
 * OUR review queue and ends at "approved". This answers what happens AFTER that, and the
 * two are genuinely different objects on different clocks: an approved source is
 * projected into chunks, frozen into a content-addressed pack, and only then does the
 * agent start answering out of it (`apps/api/kb/delivery.py`). A client reading
 * "approved" reasonably believes their correction is live, and until this card existed
 * nothing on any screen could tell them it was not.
 *
 * ## Every state says what to DO, because three of the four are not "fine"
 *
 * The one rule this card follows is that no row is allowed to report a condition without
 * naming the action it implies — including `live`, whose action is "nothing, and here is
 * the date so you can tell whether it is the version you meant". `not_delivered` is the
 * reason the whole surface exists: the publish succeeded everywhere else and the agent is
 * still answering out of its previous knowledge, and until now that reached the client as
 * silence.
 *
 * ## No caller content, structurally
 *
 * Every number here is the client's own approved knowledge (`apps/api/kb/delivery.py`
 * states it in full). What a CALLER asked and could not be answered is a different card
 * with a different pipeline — `KnowledgeGaps`, which redacts server-side — and nothing on
 * this one is derived from a conversation.
 */
export function KnowledgeDelivery({ className }: { className?: string }) {
  const session = useClientSession();
  const delivery = useKbDelivery(session);

  if (delivery.isLoading) {
    return (
      <Card title="On the phone" className={className}>
        <Skeleton rows={3} />
      </Card>
    );
  }

  if (delivery.error || !delivery.data) {
    return (
      <Card title="On the phone" className={className}>
        <ProblemNotice
          error={
            delivery.error ??
            new Error("We could not check whether your knowledge has reached your agents.")
          }
          onRetry={() => void delivery.refetch()}
        />
      </Card>
    );
  }

  const { items, not_delivered_count } = delivery.data;

  return (
    <Card
      title="On the phone"
      className={className}
      action={
        not_delivered_count > 0 ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-3 py-1 text-xs font-semibold text-brand-strong">
            <AlertTriangle aria-hidden className="h-3.5 w-3.5" />
            {not_delivered_count} not live
          </span>
        ) : undefined
      }
      bodyClassName="p-2 sm:p-3"
    >
      <p className="px-2 pb-3 pt-1 text-[12px] text-ink-muted">
        Approving a document is not the same as your agent knowing it. This is what each
        agent is actually answering callers out of, right now.
      </p>
      {items.length === 0 ? (
        <EmptyState
          title="No agents yet"
          hint="Once you have an agent, this is where you will see whether the knowledge you published has reached it."
        />
      ) : (
        <ul className="space-y-2" aria-label="Whether each agent's knowledge is live">
          {items.map((row) => (
            <DeliveryRow key={row.agent_id} row={row} />
          ))}
        </ul>
      )}
    </Card>
  );
}

/**
 * The four states, as a reader of the screen meets them.
 *
 * `tone` maps onto `NOTICE_TONES` rather than inventing colours: `preparing` is
 * deliberately `neutral` and not `warn`, because it is the ORDINARY path — a client who
 * publishes at 11:05 is in it until the sweep runs, and painting the normal case amber
 * teaches people to ignore the colour by the second week.
 *
 * `no_knowledge` is `neutral` for the same reason from the other direction: an account
 * that has not written anything down yet is not in a fault condition, and a new client's
 * first view of this screen must not be a red badge about a system working correctly.
 */
const STATE_COPY: Record<
  DeliveryState,
  { label: string; tone: keyof typeof NOTICE_TONES; icon: typeof CheckCircle2 }
> = {
  live: { label: "Live", tone: "ok", icon: CheckCircle2 },
  preparing: { label: "Getting ready", tone: "neutral", icon: Clock },
  not_delivered: { label: "Not live", tone: "stop", icon: AlertTriangle },
  no_knowledge: { label: "Nothing taught yet", tone: "neutral", icon: FileQuestion },
};

/**
 * What the client should DO — one sentence per state, in their words, never ours.
 *
 * No internal vocabulary reaches this function's output: not "pack", not "digest", not
 * "gloss", not "sweep". A client cannot act on any of them, and a support conversation
 * that starts with a client repeating a word we invented is worse than one that starts
 * with the symptom. The one exact string offered is the id under `not_delivered`, which
 * is there precisely so support has something unambiguous to look up.
 */
function sentence(row: AgentDelivery): string {
  switch (row.state) {
    case "live":
      return row.last_reached_at
        ? `Everything you have published is on this agent. It has been answering from it since ${formatIST(row.last_reached_at)}.`
        : "Everything you have published is on this agent.";
    case "preparing":
      // BOTH numbers, because one on its own is a worse sentence than none: "2 facts are
      // being prepared" reads as an outage to a client with two facts and as a rounding
      // error to one with two hundred. "2 of your 5" says how much of their knowledge is
      // affected, which is the thing they are actually judging.
      return `We are preparing ${row.awaiting_translation} of your ${row.live_chunks} ${row.live_chunks === 1 ? "fact" : "facts"} so the agent can find ${row.awaiting_translation === 1 ? "it" : "them"} however a caller asks. This finishes on its own, usually within the hour — nothing for you to do.`;
    case "not_delivered":
      return "Your newest knowledge has not reached this agent, and it is still answering callers from the version before it. Publish any document on this agent again to retry — if it stays like this, send us the reference below.";
    case "no_knowledge":
      return "This agent has nothing published yet, so it tells callers it does not have that information. Add a fact or a document above to change it.";
  }
}

function DeliveryRow({ row }: { row: AgentDelivery }) {
  // `lookup`, not `STATE_COPY[row.state]`: the union comes from the generated schema, and
  // a state added to the API before this file is updated would otherwise read `undefined`
  // and crash the card rather than degrade. UX-DOCTRINE's rule for server-driven unions.
  const copy = lookup(STATE_COPY, row.state) ?? STATE_COPY.no_knowledge;
  const Icon = copy.icon;

  return (
    <li className="rounded-xl border border-line bg-surface p-3 sm:p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        {/* `h3`: this row sits inside a `Card`, whose title is the `h2`, so anything
            deeper skips a level — WCAG 2.2 1.3.1, and axe's `heading-order` reports it
            (the rule `KnowledgeGaps.GapRow` records for the same reason). */}
        <h3 className="min-w-0 truncate text-sm font-semibold text-ink" title={row.agent_name}>
          {row.agent_name}
        </h3>
        <span
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${NOTICE_TONES[copy.tone]}`}
        >
          <Icon aria-hidden className="h-3.5 w-3.5" />
          {copy.label}
        </span>
      </div>

      <p className="mt-2 text-[13px] text-ink-muted">{sentence(row)}</p>

      {row.state === "not_delivered" && row.pack_id ? (
        <p className="mt-2 text-[12px] text-ink-faint">
          Reference for support:{" "}
          {/* The first twelve characters identify the version unambiguously in practice
              and are what a person can actually read aloud; the full value is the
              `title`, for anyone who needs to quote it exactly. The tooltip is on the
              wrapping span because `MonoValue` takes only children and a class — passing
              it through would widen a shared component for one call site. */}
          <span title={row.pack_id}>
            <MonoValue className="text-ink-muted">{row.pack_id.slice(0, 12)}</MonoValue>
          </span>
        </p>
      ) : null}
    </li>
  );
}
