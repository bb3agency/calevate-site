"use client";

import { useMemo, useState } from "react";
import { CircleAlert } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { WriteFailure } from "@/app/admin/writeFailure";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import {
  GROUP_LABELS,
  textToValue,
  useCallWord,
  useCallWords,
  useChangeCallWord,
  valueToText,
  type CallWord,
} from "@/lib/api/callWords";
import { lookup } from "@/lib/lookup";

type Show = "asked" | "edited" | "all";

const SHAPE_HINTS: Record<CallWord["shape"], string> = {
  pattern: "One pattern. Separate alternatives with |.",
  list: "One word or phrase per line.",
  table: "A table by language, written as JSON. Keep the shape of the shipped one.",
};

/** The name of a list without its group: "detection.topic.pricing" → "topic pricing". */
export function entryName(key: string): string {
  const rest = key.includes(".") ? key.slice(key.indexOf(".") + 1) : key;
  return rest.replace(/^_+/, "").replace(/[._]+/g, " ").trim().toLowerCase();
}

function groupLabel(group: string): string {
  return lookup(GROUP_LABELS, group) ?? group.replace(/_/g, " ");
}

/** The first line or so of what is in force, for the list. */
function preview(entry: CallWord): string {
  const text = valueToText(entry.shape, entry.value).replace(/\s+/g, " ").trim();
  if (!text || text === "[]" || text === "{}") return "(empty: this check is off)";
  return text.length > 140 ? `${text.slice(0, 140)}…` : text;
}

function EntryEditor({ entry, onClose }: { entry: CallWord; onClose: () => void }) {
  const detail = useCallWord(entry.key);
  const change = useChangeCallWord();
  const feedback = useActionFeedback(change, {
    errorDisplay: "inline",
    successToast: (_data, vars) => (vars.value === null ? "Shipped words back in use" : "Saved"),
  });
  const [text, setText] = useState(() => valueToText(entry.shape, entry.value));
  const [note, setNote] = useState("");
  const parsed = textToValue(entry.shape, text);
  const id = `words-${entry.key.replace(/[^A-Za-z0-9]/g, "-")}`;
  const pressedReset = change.variables?.value === null;

  const send = (value: CallWord["value"] | null) =>
    change.mutate(
      { key: entry.key, value, note, confirmation: entry.confirmation },
      { onSuccess: onClose },
    );

  return (
    <form
      className="space-y-3 border-t border-line pt-3"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (parsed.ok) send(parsed.value);
      }}
    >
      <label className="block" htmlFor={`${id}-value`}>
        <span className={FIELD_LABEL}>Words</span>
        <span className={FIELD_HINT}>{SHAPE_HINTS[entry.shape]}</span>
        <textarea
          id={`${id}-value`}
          rows={entry.shape === "pattern" ? 4 : 10}
          value={text}
          spellCheck={false}
          onChange={(e) => setText(e.target.value)}
          aria-invalid={!parsed.ok}
          aria-describedby={parsed.ok ? undefined : `${id}-parse`}
          className={`${FIELD} font-mono text-meta`}
        />
      </label>
      {!parsed.ok ? (
        <p id={`${id}-parse`} className="text-body text-danger">
          {parsed.reason}
        </p>
      ) : null}
      <label className="block max-w-xl" htmlFor={`${id}-note`}>
        <span className={FIELD_LABEL}>Why (optional)</span>
        <input
          id={`${id}-note`}
          maxLength={300}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className={FIELD}
        />
      </label>
      {change.error ? <WriteFailure error={change.error} actionLabel="Save" /> : null}
      <div className="flex flex-wrap gap-2">
        <ActionButton
          type="submit"
          status={pressedReset ? "idle" : feedback.status}
          disabled={!parsed.ok || (change.isPending && pressedReset)}
          pendingLabel="Saving…"
        >
          Save
        </ActionButton>
        {entry.edited ? (
          <ActionButton
            variant="secondary"
            status={pressedReset ? feedback.status : "idle"}
            disabled={change.isPending && !pressedReset}
            pendingLabel="Putting back…"
            onClick={() => send(null)}
          >
            Use the shipped words
          </ActionButton>
        ) : null}
        <button type="button" disabled={change.isPending} onClick={onClose} className={SECONDARY_BUTTON}>
          Cancel
        </button>
      </div>
      {detail.data && detail.data.history.length > 0 ? (
        <div className="space-y-1">
          <p className={FIELD_LABEL}>Changed before</p>
          <ul className="space-y-1 text-meta text-ink-muted">
            {detail.data.history.map((item) => (
              <li key={item.changed_at}>
                {new Date(item.changed_at).toLocaleString("en-IN", {
                  day: "numeric",
                  month: "short",
                  hour: "numeric",
                  minute: "2-digit",
                  timeZone: "Asia/Kolkata",
                })}
                {" · "}
                {item.value === null ? "shipped words put back" : "saved"}
                {item.note ? ` · ${item.note}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </form>
  );
}

function EntryRow({
  entry,
  editing,
  onEdit,
  onClose,
}: {
  entry: CallWord;
  editing: boolean;
  onEdit: () => void;
  onClose: () => void;
}) {
  const name = entryName(entry.key);
  return (
    <li className="space-y-2 px-3 py-2.5">
      <div className="flex flex-wrap items-start gap-3">
        {/* Full width on a phone, so the pills wrap under the words instead of squeezing them. */}
        <div className="min-w-0 basis-full space-y-1 sm:basis-0 sm:flex-1">
          <p className="text-body font-medium text-ink">{name}</p>
          <p className="break-words font-mono text-meta text-ink-muted">{preview(entry)}</p>
        </div>
        {entry.asked_for ? <StatusPill tone="warn">Needs your words</StatusPill> : null}
        <StatusPill tone={entry.edited ? "ok" : "neutral"}>{entry.edited ? "Edited" : "As shipped"}</StatusPill>
        {!editing ? (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={onEdit}
            aria-label={`Edit: ${name}`}
          >
            Edit
          </button>
        ) : null}
      </div>
      {entry.asked_for ? <p className="text-body text-ink">{entry.asked_for}</p> : null}
      {entry.note && editing ? <p className="text-meta text-ink-muted">{entry.note}</p> : null}
      {editing ? <EntryEditor entry={entry} onClose={onClose} /> : null}
    </li>
  );
}

/**
 * Ops > Call words (G-C2): the words the call checks listen for, in every language, which
 * the founder writes and corrects. The shipped file is the default; a save is used by every
 * check within a minute, without a release.
 */
export function CallWordsScreen() {
  const access = useAdminAccess("ops:manage", "change the words the call checks listen for");
  const list = useCallWords(!access.refused);
  const [show, setShow] = useState<Show>("asked");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<string | null>(null);

  const entries = useMemo(() => list.data?.entries ?? [], [list.data]);
  const asked = entries.filter((entry) => entry.asked_for).length;
  const groups = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const shown = entries.filter(
      (entry) =>
        (show === "all" || (show === "asked" ? Boolean(entry.asked_for) : entry.edited)) &&
        (!needle || entry.key.toLowerCase().includes(needle) || entryName(entry.key).includes(needle)),
    );
    const byGroup = new Map<string, CallWord[]>();
    for (const entry of shown) byGroup.set(entry.group, [...(byGroup.get(entry.group) ?? []), entry]);
    return [...byGroup.entries()];
  }, [entries, show, search]);

  return (
    <div className="max-w-4xl space-y-8 pb-12">
      <PageHeader description="The words each call check listens for, in every language. A save is used on calls within a minute." />
      {access.refused ? (
        <RestrictionNote reason={access.reason} />
      ) : list.error != null ? (
        <ProblemNotice error={list.error} onRetry={() => void list.refetch()} />
      ) : !list.data ? (
        <Skeleton rows={6} label="Loading the word lists" />
      ) : (
        <>
          {asked > 0 ? (
            <NoticeBox
              tone="warn"
              icon={<CircleAlert aria-hidden className="h-5 w-5" />}
              title={`${asked} list${asked === 1 ? "" : "s"} need${asked === 1 ? "s" : ""} your words`}
            >
              <p className="mt-1">Each says what to add. Until then those checks miss what is not listed.</p>
            </NoticeBox>
          ) : null}
          <div className="flex flex-wrap items-end gap-3">
            <label className="block w-full sm:w-56" htmlFor="words-show">
              <span className={FIELD_LABEL}>Show</span>
              <select
                id="words-show"
                value={show}
                onChange={(e) => setShow(e.target.value as Show)}
                className={FIELD}
              >
                <option value="asked">Needs your words ({asked})</option>
                <option value="edited">Edited</option>
                <option value="all">All lists ({entries.length})</option>
              </select>
            </label>
            <label className="block w-full sm:w-72" htmlFor="words-search">
              <span className={FIELD_LABEL}>Find a list</span>
              <input
                id="words-search"
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className={FIELD}
              />
            </label>
          </div>
          {groups.length === 0 ? (
            <p className="text-body text-ink-muted">
              {show === "edited" ? "Nothing edited yet: every list is as shipped." : "No list matches."}
            </p>
          ) : (
            groups.map(([group, rows]) => (
              <Section key={group} title={groupLabel(group)}>
                <ul className="divide-y divide-line border-y border-line">
                  {rows.map((entry) => (
                    <EntryRow
                      key={entry.key}
                      entry={entry}
                      editing={editing === entry.key}
                      onEdit={() => setEditing(entry.key)}
                      onClose={() => setEditing(null)}
                    />
                  ))}
                </ul>
              </Section>
            ))
          )}
          <details className="text-body text-ink-muted">
            <summary className="cursor-pointer text-ink">About these lists</summary>
            <p className="mt-2 whitespace-pre-line">{list.data.about}</p>
          </details>
        </>
      )}
    </div>
  );
}
