"use client";

import { useState } from "react";
import { CheckCircle2, CircleAlert } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { WriteFailure } from "@/app/admin/writeFailure";
import { PageHeader } from "@/components/console/pageHeader";
import { Section } from "@/components/console/section";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { lookup } from "@/lib/lookup";
import {
  ADDABLE_KINDS,
  KIND_LABELS,
  KIND_ORDER,
  entrySummary,
  reviewStamp,
  useChangeEntry,
  usePublishSpokenStyle,
  useSpokenStyle,
  useSpokenStyles,
  type EntryKind,
  type LanguageStyle,
  type StyleEntry,
  type StyleValue,
} from "@/lib/api/spokenStyle";

/** The language the screen opens on: Telugu is the product's first language. */
const FIRST_LANGUAGE = "te-IN";

const STATUS_LABELS: Record<StyleEntry["status"], string> = {
  approved: "Approved",
  needs_review: "Needs review",
  retired: "Retired",
};

const CHIP = "inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs font-medium";
const CHIP_TONE: Record<StyleEntry["status"], string> = {
  approved: "border-brand text-ink",
  needs_review: "border-warn text-ink",
  retired: "border-line text-ink-muted",
};

/** "Caller: ..." / "Agent: ..." lines, as an example is edited, to and from turns. */
export function turnsToText(turns: StyleValue["turns"]): string {
  return (turns ?? [])
    .map((turn) => `${turn.speaker === "agent" ? "Agent" : "Caller"}: ${turn.text}`)
    .join("\n");
}

export function textToTurns(text: string): NonNullable<StyleValue["turns"]> {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = /^(caller|agent)\s*:\s*(.*)$/i.exec(line);
      if (!match) return { speaker: "caller" as const, text: line };
      const speaker = match[1].toLowerCase() === "agent" ? ("agent" as const) : ("caller" as const);
      return { speaker, text: match[2].trim() };
    });
}

interface Draft {
  key: string;
  text: string;
  use: string;
  formal: string;
  spoken: string;
  inPrompt: boolean;
}

function draftOf(entry: StyleEntry | null): Draft {
  const value = entry?.value ?? null;
  return {
    key: entry?.key ?? "",
    text: entry?.kind === "example" ? turnsToText(value?.turns) : (value?.text ?? ""),
    use: value?.use ?? "",
    formal: value?.formal ?? "",
    spoken: value?.spoken ?? "",
    inPrompt: Boolean(value?.in_prompt),
  };
}

function valueOf(kind: EntryKind, draft: Draft): StyleValue {
  if (kind === "swap") {
    return { formal: draft.formal.trim(), spoken: draft.spoken.trim(), in_prompt: draft.inPrompt };
  }
  if (kind === "example") return { turns: textToTurns(draft.text) };
  if (kind === "filler") return { text: draft.text.trim(), use: draft.use.trim() };
  return { text: draft.text.trim() };
}

/** Whether the form holds what the server will need; the server checks it again. */
function complete(kind: EntryKind, adding: boolean, draft: Draft): boolean {
  if (kind === "swap") return Boolean(draft.formal.trim() && draft.spoken.trim());
  if (kind === "example") {
    return textToTurns(draft.text).length > 0 && (!adding || /^[a-z0-9_][a-z0-9_-]*$/.test(draft.key.trim()));
  }
  return Boolean(draft.text.trim());
}

/**
 * The entry form, for an edit (`entry` set) or an addition (`entry` null). The fields are
 * the kind's own; a swap's formal word is its key, so it is fixed once the swap exists.
 */
function EntryForm({
  kind,
  entry,
  busy,
  onSave,
  onCancel,
}: {
  kind: EntryKind;
  entry: StyleEntry | null;
  busy: boolean;
  onSave: (key: string | null, value: StyleValue) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(entry));
  const set = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));
  const id = `${kind}-${entry?.key ?? "new"}`;
  const adding = entry === null;
  return (
    <form
      className="space-y-3 border-t border-line pt-3"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        onSave(adding && kind === "example" ? draft.key.trim() : (entry?.key ?? null), valueOf(kind, draft));
      }}
    >
      {kind === "swap" ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block" htmlFor={`${id}-formal`}>
            <span className={FIELD_LABEL}>Formal word</span>
            <input
              id={`${id}-formal`}
              required
              maxLength={120}
              value={draft.formal}
              readOnly={!adding}
              onChange={(e) => set({ formal: e.target.value })}
              className={FIELD}
            />
          </label>
          <label className="block" htmlFor={`${id}-spoken`}>
            <span className={FIELD_LABEL}>What people say</span>
            <input
              id={`${id}-spoken`}
              required
              maxLength={120}
              value={draft.spoken}
              onChange={(e) => set({ spoken: e.target.value })}
              className={FIELD}
            />
            <span className={FIELD_HINT}>An instruction in brackets, like (leave it out), is fine.</span>
          </label>
          <label className="flex items-center gap-2 text-body text-ink sm:col-span-2">
            <input
              type="checkbox"
              checked={draft.inPrompt}
              onChange={(e) => set({ inPrompt: e.target.checked })}
            />
            Put this one in every agent&apos;s instructions
          </label>
        </div>
      ) : (
        <>
          {adding && kind === "example" && (
            <label className="block" htmlFor={`${id}-key`}>
              <span className={FIELD_LABEL}>Business type</span>
              <input
                id={`${id}-key`}
                required
                pattern="[a-z0-9_][a-z0-9_\-]*"
                maxLength={48}
                value={draft.key}
                onChange={(e) => set({ key: e.target.value })}
                className={FIELD}
              />
              <span className={FIELD_HINT}>Lowercase, like retail or local_services.</span>
            </label>
          )}
          <label className="block" htmlFor={`${id}-text`}>
            <span className={FIELD_LABEL}>
              {kind === "example" ? "Lines, one per row: Caller: … or Agent: …" : "Text"}
            </span>
            <textarea
              id={`${id}-text`}
              required
              rows={kind === "example" ? 6 : 2}
              maxLength={kind === "example" ? 3000 : 600}
              value={draft.text}
              onChange={(e) => set({ text: e.target.value })}
              className={FIELD}
            />
          </label>
          {kind === "filler" && (
            <label className="block" htmlFor={`${id}-use`}>
              <span className={FIELD_LABEL}>When it is used (English)</span>
              <input
                id={`${id}-use`}
                maxLength={300}
                value={draft.use}
                onChange={(e) => set({ use: e.target.value })}
                className={FIELD}
              />
            </label>
          )}
        </>
      )}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy || !complete(kind, adding, draft)} className={PRIMARY_BUTTON}>
          {adding ? "Add and approve" : "Save and approve"}
        </button>
        <button type="button" disabled={busy} onClick={onCancel} className={SECONDARY_BUTTON}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function EntryRow({
  entry,
  busy,
  editing,
  onEdit,
  onAction,
  onSave,
  onCancel,
}: {
  entry: StyleEntry;
  busy: boolean;
  editing: boolean;
  onEdit: () => void;
  onAction: (action: "approve" | "retire") => void;
  onSave: (key: string | null, value: StyleValue) => void;
  onCancel: () => void;
}) {
  const summary = entrySummary(entry.kind, entry.value ?? entry.published_value);
  return (
    <li className="space-y-2 px-3 py-2.5">
      <div className="flex flex-wrap items-start gap-3">
        <p className="min-w-0 flex-1 whitespace-pre-line text-body text-ink">
          {entry.kind === "example" ? (
            <span className="mb-1 block text-meta font-medium text-ink-muted">
              {entry.key === "_default" ? "Any business" : entry.key.replace(/_/g, " ")}
            </span>
          ) : null}
          {summary}
          {entry.kind === "swap" && entry.value?.in_prompt ? (
            <span className="ml-2 text-meta text-ink-muted">· in every agent&apos;s instructions</span>
          ) : null}
        </p>
        <span className={`${CHIP} ${lookup(CHIP_TONE, entry.status) ?? ""}`}>
          {lookup(STATUS_LABELS, entry.status) ?? entry.status}
        </span>
        {entry.unpublished ? <span className="text-meta text-ink-muted">Not published yet</span> : null}
      </div>
      {entry.status !== "retired" && !editing && (
        <div className="flex flex-wrap gap-2">
          {entry.status === "needs_review" && (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={busy}
              onClick={() => onAction("approve")}
              aria-label={`Approve: ${summary.slice(0, 60)}`}
            >
              Approve
            </button>
          )}
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={busy}
            onClick={onEdit}
            aria-label={`Edit: ${summary.slice(0, 60)}`}
          >
            Edit
          </button>
          {entry.kind !== "register" && (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              disabled={busy}
              onClick={() => onAction("retire")}
              aria-label={`Retire: ${summary.slice(0, 60)}`}
            >
              Retire
            </button>
          )}
        </div>
      )}
      {editing && (
        <EntryForm kind={entry.kind} entry={entry} busy={busy} onSave={onSave} onCancel={onCancel} />
      )}
    </li>
  );
}

function PublishForm({ view }: { view: LanguageStyle }) {
  const publish = usePublishSpokenStyle(view.language);
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const nothing = view.unpublished_changes === 0;
  return (
    <form
      className="space-y-3"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        publish.mutate({
          reviewerName: reviewer.trim(),
          note,
          confirmation: view.publish_confirmation,
        });
      }}
    >
      <p className="text-body text-ink-muted">
        {nothing
          ? "Nothing changed since the last publish."
          : `${view.unpublished_changes} change${view.unpublished_changes === 1 ? "" : "s"} not published yet. Publishing puts them in every live agent in this language, within minutes, without switching anything off.`}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block" htmlFor="style-reviewer">
          <span className={FIELD_LABEL}>Reviewed by</span>
          <input
            id="style-reviewer"
            required
            minLength={2}
            maxLength={80}
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            className={FIELD}
          />
          <span className={FIELD_HINT}>The native speaker who read it, as the stamp should show.</span>
        </label>
        <label className="block" htmlFor="style-note">
          <span className={FIELD_LABEL}>Note (optional)</span>
          <input
            id="style-note"
            maxLength={500}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className={FIELD}
          />
        </label>
      </div>
      <button
        type="submit"
        disabled={nothing || publish.isPending || reviewer.trim().length < 2}
        className={PRIMARY_BUTTON}
      >
        {publish.isPending ? "Publishing…" : "Publish to live agents"}
      </button>
      {publish.error ? <WriteFailure error={publish.error} actionLabel="Publish to live agents" /> : null}
      {publish.isSuccess ? (
        <p className="flex items-start gap-2 text-body text-ink-muted">
          <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
          <span>Published. Live agents are being updated with these words.</span>
        </p>
      ) : null}
    </form>
  );
}

function LanguageReview({ view }: { view: LanguageStyle }) {
  const change = useChangeEntry(view.language);
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState<EntryKind | null>(null);
  const busy = change.isPending;
  const stamp = reviewStamp(view);

  const send = (kind: EntryKind, action: "approve" | "edit" | "add" | "retire", key: string | null, value?: StyleValue) =>
    change.mutate(
      { kind, action, key, value: value ?? null },
      {
        onSuccess: () => {
          setEditing(null);
          setAdding(null);
        },
      },
    );

  return (
    <div className="space-y-8">
      <NoticeBox
        tone={view.review === "native_reviewed" ? "ok" : "warn"}
        icon={<CircleAlert aria-hidden className="h-5 w-5" />}
        title={
          view.review === "native_reviewed"
            ? `${view.name}: reviewed by a native speaker`
            : `${view.name}: awaiting native review`
        }
      >
        <p className="mt-1">
          {stamp ?? "Not reviewed yet."} {view.approved} of {view.total} entries approved.
        </p>
      </NoticeBox>

      <Section title="Publish">
        <PublishForm view={view} />
      </Section>

      {change.error ? <WriteFailure error={change.error} actionLabel="Save" /> : null}

      {KIND_ORDER.map((kind) => {
        const entries = view.entries.filter((entry) => entry.kind === kind);
        if (entries.length === 0 && !ADDABLE_KINDS.has(kind)) return null;
        const label = lookup(KIND_LABELS, kind);
        return (
          <Section
            key={kind}
            title={label?.title ?? kind}
            description={label?.hint}
            action={
              ADDABLE_KINDS.has(kind) ? (
                <button
                  type="button"
                  className={SECONDARY_BUTTON_SM}
                  disabled={busy}
                  onClick={() => {
                    setAdding(kind);
                    setEditing(null);
                  }}
                >
                  Add
                </button>
              ) : undefined
            }
          >
            {adding === kind && (
              <EntryForm
                kind={kind}
                entry={null}
                busy={busy}
                onSave={(key, value) => send(kind, "add", key, value)}
                onCancel={() => setAdding(null)}
              />
            )}
            <ul className="divide-y divide-line border-y border-line">
              {entries.map((entry) => {
                const id = `${entry.kind}:${entry.key}`;
                return (
                  <EntryRow
                    key={id}
                    entry={entry}
                    busy={busy}
                    editing={editing === id}
                    onEdit={() => {
                      setEditing(id);
                      setAdding(null);
                    }}
                    onAction={(action) => send(entry.kind, action, entry.key)}
                    onSave={(key, value) => send(entry.kind, "edit", key, value)}
                    onCancel={() => setEditing(null)}
                  />
                );
              })}
            </ul>
          </Section>
        );
      })}

      {view.history.length > 0 && (
        <Section title="Published before">
          <ul className="space-y-1 text-body text-ink-muted">
            {view.history.map((item) => (
              <li key={item.published_at}>
                {reviewStamp({ reviewed_by: item.reviewer_name, reviewed_on: item.reviewed_on })}
                {item.note ? ` · ${item.note}` : ""}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

/**
 * Ops > Spoken style (D-744): how agents speak each language, for the founder to review.
 * Every entry starts as AI-drafted and unreviewed; approving, editing, adding or retiring
 * changes the working copy, and publishing puts the reviewed words in every live agent.
 */
export function SpokenStyleScreen() {
  const access = useAdminAccess("ops:manage", "review how agents speak");
  const list = useSpokenStyles(!access.refused);
  const [language, setLanguage] = useState(FIRST_LANGUAGE);
  const view = useSpokenStyle(language, !access.refused);

  return (
    <div className="max-w-4xl space-y-8 pb-12">
      <PageHeader description="How agents speak each language: the everyday words, tags, numbers and example calls the instructions and the script writer use. Review them, then publish." />
      {access.refused ? (
        <RestrictionNote reason={access.reason} />
      ) : (
        <>
          {list.error != null && <ProblemNotice error={list.error} onRetry={() => void list.refetch()} />}
          {list.data ? (
            <label className="block max-w-sm" htmlFor="style-language">
              <span className={FIELD_LABEL}>Language</span>
              <select
                id="style-language"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className={FIELD}
              >
                {list.data.languages.map((row) => (
                  <option key={row.language} value={row.language}>
                    {row.name} · {row.review === "native_reviewed" ? "reviewed" : `${row.approved} of ${row.total} approved`}
                  </option>
                ))}
              </select>
            </label>
          ) : list.error ? null : (
            <Skeleton rows={1} label="Loading the languages" />
          )}
          {view.error != null && <ProblemNotice error={view.error} onRetry={() => void view.refetch()} />}
          {view.data ? (
            <LanguageReview key={view.data.language} view={view.data} />
          ) : view.error ? null : (
            <Skeleton rows={6} label="Loading the spoken style" />
          )}
        </>
      )}
    </div>
  );
}
