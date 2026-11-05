"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, Pin } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { SearchField } from "@/components/arc/search-field";
import { EmptyState } from "@/components/console/emptyState";
import { EmptySketch } from "@/components/console/emptySketch";
import { Section } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import {
  FIELD,
  FIELD_LABEL,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatCountOf,
  type NoticeTone,
} from "@/components/ui";
import { useBusinessProfile, type BusinessProfile } from "@/lib/api/businessProfile";
import { useKbUploads, type KbUpload, type useKbNotes } from "@/lib/api/kb";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { PRICES_QUESTION } from "@/lib/api/teachQuestions";
import { useVerticalExamples } from "@/lib/useVerticalExamples";
import {
  useAddFact,
  useEditFact,
  useKnows,
  useRemoveFact,
  useReorderPinned,
  type Fact,
  type PinnedNotYetOn,
} from "@/lib/api/teach";

import { AgentScripts } from "./AgentScripts";
import { BusinessBasics, basicsCount, profileBasics } from "./BusinessBasics";
import { Group, NoMatch } from "./KnowledgeGroup";
import { NotesList, noteTone } from "./NotesList";
import { ProfileKnowledge, profileMatchCount } from "./ProfileKnowledge";
import { UploadRow } from "./UploadList";
import { uploadState } from "./uploadCopy";


function matches(query: string, ...values: (string | null | undefined)[]): boolean {
  const q = query.trim().toLocaleLowerCase();
  return !q || values.some((value) => value?.toLocaleLowerCase().includes(q));
}

/**
 * EVERYTHING THE AGENTS HAVE BEEN GIVEN, in one searchable list grouped by what it is:
 * pinned facts (in every agent's instructions, winning over anything else), the other facts
 * and answers, files, links, and notes typed before the teach box. Every row is shared by
 * all the agents (D-689), so no row names one.
 *
 * Files and links are read from the uploads list rather than `/v1/kb/knows`' items: only
 * an upload row carries its kind (`source_kind`), and the kind decides whether its words
 * reach the agents at all (`uploadCopy.reachesAgents`). Each read keeps its own honesty
 * (§52): one that failed gets its refusal, never an "empty" claim about what was sent.
 */
export function WhatItKnows({
  canWrite,
  notes: notesRead,
  onAnswerQuestions,
}: {
  canWrite: boolean;
  notes: ReturnType<typeof useKbNotes>;
  /** Opens the Questions to answer view, on one question when it names one. */
  onAnswerQuestions?: (key: string) => void;
}) {
  const session = useClientSession();
  const knows = useKnows(session);
  const uploads = useKbUploads(session);
  const profile = useBusinessProfile(session);
  const [query, setQuery] = useState("");
  const clearQuery = () => setQuery("");

  const pinned = useMemo(() => knows.data?.facts.filter((f) => f.pinned) ?? [], [knows.data]);
  const other = useMemo(() => knows.data?.facts.filter((f) => !f.pinned) ?? [], [knows.data]);
  // A replaced version is history: the version that took its place is the row.
  const current = useMemo(
    () => uploads.data?.filter((u) => u.review_state !== "archived") ?? [],
    [uploads.data],
  );
  const files = current.filter((u) => u.source_kind !== "url");
  const links = current.filter((u) => u.source_kind === "url");
  // Every typed note, removed ones included so the page can put them back; only the
  // others are knowledge and count toward what the agents were given.
  const allNotes = notesRead.data?.notes ?? [];
  const notes = allNotes.filter((n) => n.state !== "removed");

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

  const filtered = query.trim() !== "";
  const shownPinned = pinned.filter((f) => matches(query, f.text, f.question));
  const shownOther = other.filter((f) => matches(query, f.text));
  const uploadMatches = (u: KbUpload) => matches(query, u.name, u.filename, u.source_url);
  const shownFiles = files.filter(uploadMatches);
  const shownLinks = links.filter(uploadMatches);
  const shownAnyNote = allNotes.some((n) => matches(query, n.name));
  const tally = knowledgeTally({
    pinned: pinned.length,
    facts: knows.data.facts_state === "live" ? other.length : 0,
    profile: profile.data,
    files,
    links,
    notes: notes.filter((n) => n.state === "in_use").length,
  });
  const anything =
    pinned.length + other.length + files.length + links.length + notes.length + tally.business > 0;
  // "Nothing yet" is said only when every read answered; a read still out is not empty.
  const empty =
    !anything && allNotes.length === 0 && Boolean(uploads.data) && Boolean(notesRead.data) && Boolean(profile.data);
  const shown =
    shownPinned.length +
    shownOther.length +
    shownFiles.length +
    shownLinks.length +
    (shownAnyNote ? 1 : 0) +
    profileMatchCount(profile.data, query) +
    (profile.data ? profileBasics(profile.data).filter((b) => matches(query, b.label, b.value)).length : 0);

  if (empty) {
    // The Add area above is the one way in, so the empty list offers no second form.
    return (
      <div>
        <EmptyState
          align="start"
          illustration={<EmptySketch kind="knowledge" />}
          message={
            <>
              {/* Its own script may already state facts (A-20): only this page is empty. */}
              <span className="block font-medium text-ink">Nothing added to Knowledge yet</span>
              <span className="mt-1 block">Start with what callers ask most.</span>
            </>
          }
          action={
            onAnswerQuestions && canWrite ? (
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                onClick={() => onAnswerQuestions(PRICES_QUESTION)}
              >
                Answer the first questions
              </button>
            ) : undefined
          }
        />
      </div>
    );
  }

  const uploadsFailed = uploads.error || (!uploads.isLoading && !uploads.data);

  return (
    <div className="space-y-10">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <p className="text-body font-medium text-ink">
              {formatCount(tally.total)} {tally.total === 1 ? "thing" : "things"} your agents know
            </p>
            <NeedsYouTally tones={[...current.map((u) => uploadState(u).tone), ...notes.map((n) => noteTone(n.state))]} />
          </div>
          <TallyList tally={tally} />
        </div>
        <SearchField
          label="Search what your agents know"
          hideLabel
          value={query}
          onValueChange={setQuery}
          placeholder="Search"
          className="w-full lg:max-w-xs"
        />
      </div>

      {filtered && shown === 0 ? (
        <NoMatch message="Nothing matches your search." onClear={clearQuery} />
      ) : null}

      <div id={ANCHORS.pinned} className="scroll-mt-24">
        <PinnedFacts
          facts={shownPinned}
          all={pinned}
          canWrite={canWrite}
          filtered={filtered}
          onClearFilter={clearQuery}
          notYetOn={knows.data.pinned_not_yet_on}
        />
      </div>

      {/* Everything the business details tell every agent, together (D-968). */}
      <div id={ANCHORS.business} className="scroll-mt-24 space-y-10">
        {profile.data ? <BusinessBasics profile={profile.data} query={query} /> : null}
        <ProfileKnowledge query={query} />
      </div>

      <div id={ANCHORS.facts} className="scroll-mt-24">
      <Group
        title="Facts and answers"
        count={other.length}
        hidden={filtered && shownOther.length === 0}
        info={<p>Your agents look these up when a caller asks about them.</p>}
        status={<FactsStatus state={knows.data.facts_state} any={other.length > 0} />}
      >
        {other.length === 0 ? (
          <p className="text-meta text-ink-muted">Facts you write show here.</p>
        ) : (
          <ul className="divide-y divide-line border-y border-line">
            {shownOther.map((fact) => (
              <FactRow key={fact.id} fact={fact} canWrite={canWrite} />
            ))}
          </ul>
        )}
      </Group>
      </div>

      {uploadsFailed ? (
        <ProblemNotice
          error={uploads.error ?? new Error("We could not load the files and links you sent.")}
          onRetry={() => void uploads.refetch()}
        />
      ) : uploads.isLoading ? (
        <Skeleton rows={3} label="Loading your files and links" />
      ) : (
        <>
          <div id={ANCHORS.files} className="scroll-mt-24">
          <Group
            title="Files"
            count={files.length}
            hidden={filtered && shownFiles.length === 0}
            info={<p>Open a file to see what your agents learned from it.</p>}
          >
            {files.length === 0 ? (
              <p className="text-meta text-ink-muted">Files and photos you send show here.</p>
            ) : (
              <ul className="divide-y divide-line border-y border-line">
                {shownFiles.map((upload) => (
                  <UploadRow key={upload.id} upload={upload} />
                ))}
              </ul>
            )}
          </Group>
          </div>

          {/* Links only once there is one: an empty "Links" group would invite a kind of
              item whose words do not reach the agents yet (D-868). */}
          {links.length > 0 ? (
            <div id={ANCHORS.links} className="scroll-mt-24">
            <Group title="Links" count={links.length} hidden={filtered && shownLinks.length === 0}>
              <ul className="divide-y divide-line border-y border-line">
                {shownLinks.map((upload) => (
                  <UploadRow key={upload.id} upload={upload} />
                ))}
              </ul>
            </Group>
            </div>
          ) : null}
        </>
      )}

      {notesRead.isLoading ? (
        <Skeleton rows={2} label="Loading your notes" />
      ) : allNotes.length > 0 ? (
        <div id={ANCHORS.notes} className="scroll-mt-24">
        <Group
          title="Notes you wrote earlier"
          count={notes.length}
          hidden={filtered && !shownAnyNote}
          info={<p>Longer notes added before you could write facts one by one.</p>}
        >
          <NotesList
            notes={allNotes}
            canWrite={canWrite}
            query={(name) => matches(query, name)}
          />
        </Group>
        </div>
      ) : null}

      <AgentScripts query={query} />
    </div>
  );
}

/**
 * The rows that are not reaching the agents, counted by kind beside the total, so an owner
 * sees there is something to open without scrolling every group. Only waiting and broken
 * rows are counted, and only when there are some: a row of "0" chips would say nothing.
 */
export function NeedsYouTally({ tones }: { tones: NoticeTone[] }) {
  const waiting = tones.filter((tone) => tone === "warn").length;
  const broken = tones.filter((tone) => tone === "stop").length;
  if (waiting === 0 && broken === 0) return null;
  return (
    <ul aria-label="Not in use yet" className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {broken > 0 && (
        <li>
          <StatusPill tone="stop">{formatCount(broken)} not working</StatusPill>
        </li>
      )}
      {waiting > 0 && (
        <li>
          <StatusPill tone="warn">{formatCount(waiting)} waiting</StatusPill>
        </li>
      )}
    </ul>
  );
}

/**
 * Where the newest facts are, from `/v1/kb/knows`' `facts_state`. It is ONE state for the
 * whole set (the facts are published together), so it is said once beside the heading
 * rather than repeated on every row.
 */
function FactsStatus({ state, any }: { state: string; any: boolean }) {
  if (!any) return null;
  if (state === "publishing") {
    return <span className="text-shimmer text-meta text-ink-muted">Reaching your agents…</span>;
  }
  if (state === "in_review") return <StatusPill tone="warn">Waiting for review</StatusPill>;
  if (state === "live") return <StatusPill tone="ok">In use</StatusPill>;
  return null;
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
                    className="underline underline-offset-2 touch:inline-flex touch:min-h-11 touch:items-center"
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
          <p className="text-meta text-ink-muted">Nothing pinned yet.</p>
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
        // Stacked on a phone: beside three buttons the fact was squeezed to a word a line.
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
          <div className="min-w-0 sm:flex-1">
            {fact.question ? <p className="text-meta text-ink-muted">{fact.question}</p> : null}
            <p className="text-sm text-ink [overflow-wrap:anywhere]">
              {fact.pinned ? <Pin aria-label="Pinned" className="mr-1.5 inline h-3.5 w-3.5 text-brand-strong" /> : null}
              {fact.text}
            </p>
          </div>
          {canWrite ? (
            // Wraps within itself on a phone: the kit buttons are as wide as their widest face.
            <div className="flex min-w-0 flex-wrap gap-1.5 sm:shrink-0">
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

/** Where each group sits on the page, for the tally's jump links. */
export const ANCHORS = {
  pinned: "knows-pinned",
  business: "knows-business",
  facts: "knows-facts",
  files: "knows-files",
  links: "knows-links",
  notes: "knows-notes",
} as const;

export interface KnowledgeTally {
  total: number;
  pinned: number;
  business: number;
  facts: number;
  /** Files in use, and how many things were read out of them. */
  files: number;
  learned: number;
  links: number;
  notes: number;
}

/**
 * HOW MUCH THE AGENTS KNOW, counted where it came from. Only what reaches them counts: a
 * file, link or note that is waiting, refused or still being read is not known yet (the
 * tally beside it says so), and facts still on their way are not either. A file counts the
 * things read out of it (`UploadOut.facts_count`), the same number its row shows; a link
 * counts once, as its agents read the page itself.
 */
export function knowledgeTally({
  pinned,
  facts,
  profile,
  files,
  links,
  notes,
}: {
  pinned: number;
  facts: number;
  profile: BusinessProfile | undefined;
  files: KbUpload[];
  links: KbUpload[];
  notes: number;
}): KnowledgeTally {
  const inUse = (u: KbUpload) => uploadState(u).tone === "ok";
  const usedFiles = files.filter(inUse);
  const learned = usedFiles.reduce((sum, u) => sum + u.facts_count, 0);
  const business = profileMatchCount(profile, "") + basicsCount(profile);
  const usedLinks = links.filter(inUse).length;
  return {
    total: pinned + business + facts + learned + usedLinks + notes,
    pinned,
    business,
    facts,
    files: usedFiles.length,
    learned,
    links: usedLinks,
    notes,
  };
}

/** The tally as jump links, one per source that holds something. */
function TallyList({ tally }: { tally: KnowledgeTally }) {
  const entries: { anchor: string; label: string }[] = [];
  if (tally.business > 0) {
    entries.push({ anchor: ANCHORS.business, label: `${formatCount(tally.business)} from business details` });
  }
  if (tally.pinned > 0) entries.push({ anchor: ANCHORS.pinned, label: `${formatCount(tally.pinned)} pinned` });
  if (tally.facts > 0) {
    entries.push({ anchor: ANCHORS.facts, label: formatCountOf(tally.facts, "fact you wrote", "facts you wrote") });
  }
  if (tally.files > 0) {
    entries.push({ anchor: ANCHORS.files, label: `${formatCount(tally.learned)} from ${formatCountOf(tally.files, "file")}` });
  }
  if (tally.links > 0) entries.push({ anchor: ANCHORS.links, label: formatCountOf(tally.links, "web page") });
  if (tally.notes > 0) entries.push({ anchor: ANCHORS.notes, label: formatCountOf(tally.notes, "note") });
  if (entries.length === 0) return null;
  return (
    <ul aria-label="Where it came from" className="flex flex-wrap gap-x-4 gap-y-1">
      {entries.map((entry) => (
        <li key={entry.anchor}>
          <a
            href={`#${entry.anchor}`}
            className="text-meta tabular-nums text-ink-muted underline-offset-2 hover:text-ink hover:underline touch:inline-flex touch:min-h-11 touch:items-center"
          >
            {entry.label}
          </a>
        </li>
      ))}
    </ul>
  );
}
