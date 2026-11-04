"use client";

import { useId, useMemo, useState, type DragEvent, type KeyboardEvent } from "react";
import { ClipboardPaste, Download, FileUp, Pencil, Plus, Trash2, X } from "lucide-react";

import { SearchField } from "@/components/arc/search-field";
import { HowItWorks } from "@/components/console/howItWorks";
import { FileDrop } from "@/components/fileDrop";
import { LANGUAGE_NAMES } from "@/lib/agentState";
import { lookup } from "@/lib/lookup";
import { Pagination } from "@/components/interior/pagination";
import {
  FIELD,
  FIELD_LABEL,
  FIELD_INLINE,
  MonoValue,
  PRIMARY_BUTTON_SM,
  QUIET_ICON_BUTTON,
  SECONDARY_BUTTON_SM,
  formatCount,
  formatPhone,
} from "@/components/ui";

import {
  MAX_CONTACTS_PER_UPLOAD,
  MAX_FILE_BYTES,
  SAMPLE_CSV,
  checkContacts,
  newEntry,
  parseCsv,
  rowsToEntries,
  type CheckedRow,
  type ContactEntry,
} from "./contactList";

/**
 * What the file drop says about the list (D-915). The script named is the calling agent's,
 * never a fixed one: a Hindi agent's owner is not told to write Telugu. English names need
 * no script note, and before an agent is chosen none is named.
 */
export const FILE_HINT = "A CSV with a phone column. Up to 4 MB.";

/** The tips behind "File tips": what else a list can carry, and how names are said best. */
export function fileTips(agentLanguage: string | null | undefined): string[] {
  const name = agentLanguage && agentLanguage !== "en-IN" ? lookup(LANGUAGE_NAMES, agentLanguage) : undefined;
  return [
    "Add other columns for what the agent should know about each person. It hears them on the call.",
    ...(name ? [`Names are said best written in ${name} script.`] : []),
  ];
}

const PAGE = 50;
/** What the reader below parses: delimited text, never a spreadsheet binary. */
const CSV_ACCEPT = ".csv,.tsv,.txt,text/csv";
type Panel = "none" | "paste" | "add";

/**
 * WHO TO CALL: a contact list built by importing a CSV, pasting, or adding one person at a
 * time, checked row by row before anything is sent.
 *
 * Every row says whether it will be called: ready, a duplicate of an earlier row, or not
 * readable (with the reason). The rules are the server's, mirrored in `contactList.ts`, so
 * the "ready" count is what the upload will add; the server re-checks and has the last
 * word. The file is read in the browser and never uploaded as a file.
 *
 * The do-not-call list is stated as a fact, not offered as a setting: it is enforced on
 * every dial and nothing here can turn it off.
 */
export function ContactEditor({
  entries,
  onChange,
  label = "Contacts",
  agentLanguage,
}: {
  entries: ContactEntry[];
  onChange: (next: ContactEntry[]) => void;
  label?: string;
  /** The calling agent's main language, when chosen: the file hint names its script. */
  agentLanguage?: string | null;
}) {
  const ids = useId();
  const [panel, setPanel] = useState<Panel>("none");
  const [pasteText, setPasteText] = useState("");
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const checked = useMemo(() => checkContacts(entries), [entries]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return checked.rows;
    return checked.rows.filter(
      ({ entry }) => entry.phone.toLowerCase().includes(q) || entry.name.toLowerCase().includes(q),
    );
  }, [checked.rows, query]);
  const pages = Math.max(1, Math.ceil(shown.length / PAGE));
  const current = Math.min(page, pages);
  const visible = shown.slice((current - 1) * PAGE, current * PAGE);
  const problems = checked.counts.invalid + checked.counts.duplicate;

  const append = (text: string, source: string) => {
    const { entries: added, dropped } = rowsToEntries(parseCsv(text));
    if (added.length === 0) {
      setNotice(`No rows found in ${source}.`);
      return;
    }
    onChange([...entries, ...added]);
    setNotice(
      `Added ${formatCount(added.length)} ${added.length === 1 ? "row" : "rows"} from ${source}.` +
        (dropped.length
          ? ` Skipped columns: ${dropped.join(", ")} (max 10 extra).`
          : ""),
    );
    setPage(1);
  };

  const readFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      setNotice(`${file.name} is over 4 MB. Split it into smaller files.`);
      return;
    }
    let text: string;
    try {
      text = await file.text();
    } catch {
      // A file moved or locked after it was picked cannot be read.
      setNotice(`${file.name} could not be opened. Pick it again.`);
      return;
    }
    append(text, file.name);
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    void readFile(event.dataTransfer.files[0]);
  };

  const downloadSample = () => {
    const url = URL.createObjectURL(new Blob([SAMPLE_CSV], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "calevate-contacts-sample.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  const remove = (id: string) => onChange(entries.filter((entry) => entry.id !== id));
  const update = (next: ContactEntry) =>
    onChange(entries.map((entry) => (entry.id === next.id ? next : entry)));
  const keepReady = () =>
    onChange(checked.rows.filter(({ status }) => status.kind === "ready").map(({ entry }) => entry));

  return (
    <section aria-label={label} className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {/* The native file input IS the control, inside a label styled as a button: one
            focusable thing, opened by click, Enter or Space, with the focus ring drawn on
            the label because the input is visually hidden. */}
        <label
          className={`${SECONDARY_BUTTON_SM} cursor-pointer has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app`}
        >
          <input
            type="file"
            accept={CSV_ACCEPT}
            className="sr-only"
            aria-label="Import a CSV file"
            onChange={(e) => {
              void readFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <FileUp aria-hidden className="h-3.5 w-3.5" />
          Import CSV
        </label>
        <button
          type="button"
          aria-expanded={panel === "paste"}
          onClick={() => setPanel(panel === "paste" ? "none" : "paste")}
          className={SECONDARY_BUTTON_SM}
        >
          <ClipboardPaste aria-hidden className="h-3.5 w-3.5" />
          Paste
        </button>
        <button
          type="button"
          aria-expanded={panel === "add"}
          onClick={() => setPanel(panel === "add" ? "none" : "add")}
          className={SECONDARY_BUTTON_SM}
        >
          <Plus aria-hidden className="h-3.5 w-3.5" />
          Add contact
        </button>
        <button
          type="button"
          onClick={downloadSample}
          className="press inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          <Download aria-hidden className="h-3.5 w-3.5" />
          Sample CSV
        </button>
      </div>

      {panel === "paste" && (
        <div className="settings-enter space-y-2">
          <label className="block">
            <span className={FIELD_LABEL}>Paste rows</span>
            <textarea
              rows={4}
              value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
              placeholder={"phone,name\n9876543210,Priya"}
              className={`${FIELD} font-mono text-xs`}
            />
          </label>
          <button
            type="button"
            disabled={pasteText.trim() === ""}
            onClick={() => {
              append(pasteText, "what you pasted");
              setPasteText("");
              setPanel("none");
            }}
            className={SECONDARY_BUTTON_SM}
          >
            Add these rows
          </button>
        </div>
      )}

      {panel === "add" && (
        <div className="settings-enter flex flex-wrap items-end gap-2">
          <label className="block min-w-0 flex-1 basis-40">
            <span className={FIELD_LABEL}>Phone</span>
            <input
              value={phone}
              inputMode="tel"
              onChange={(e) => setPhone(e.target.value)}
              placeholder="98765 43210"
              className={FIELD}
            />
          </label>
          <label className="block min-w-0 flex-1 basis-40">
            <span className={FIELD_LABEL}>Name (optional)</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className={FIELD} />
          </label>
          <button
            type="button"
            disabled={phone.trim() === ""}
            onClick={() => {
              onChange([...entries, newEntry(phone, name)]);
              setPhone("");
              setName("");
            }}
            className={SECONDARY_BUTTON_SM}
          >
            Add
          </button>
        </div>
      )}

      {notice && (
        <p role="status" className="flex items-start justify-between gap-2 text-xs text-ink-muted">
          <span>{notice}</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setNotice(null)}
            className="rounded-sm text-ink-faint hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            <X aria-hidden className="h-3.5 w-3.5" />
          </button>
        </p>
      )}

      {entries.length === 0 ? (
        <FileDrop
          label="Your contacts file"
          hint={FILE_HINT}
          accept={CSV_ACCEPT}
          validate={(file) =>
            file.size > MAX_FILE_BYTES
              ? "That file is over 4 MB. Split it into smaller files."
              : null
          }
          onFiles={([file]) => void readFile(file)}
        />
      ) : (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`space-y-2 rounded-card transition-shadow duration-(--duration-fast) ${dragging ? "ring-2 ring-brand" : ""}`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p aria-live="polite" className="text-sm tabular-nums text-ink">
              <span className="font-semibold">{formatCount(checked.counts.ready)} ready</span>
              {checked.counts.invalid > 0 && (
                <span className="text-danger"> · {formatCount(checked.counts.invalid)} can&apos;t be called</span>
              )}
              {checked.counts.duplicate > 0 && (
                <span className="text-ink-muted">
                  {" "}
                  · {formatCount(checked.counts.duplicate)} {checked.counts.duplicate === 1 ? "duplicate" : "duplicates"}
                </span>
              )}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              {problems > 0 && (
                <button type="button" onClick={keepReady} className={SECONDARY_BUTTON_SM}>
                  Remove {formatCount(problems)} that won&apos;t be called
                </button>
              )}
              <SearchField
                label="Search contacts"
                hideLabel
                placeholder="Search"
                value={query}
                onValueChange={(next) => {
                  setQuery(next);
                  setPage(1);
                }}
                className="w-full sm:w-48"
              />
            </div>
          </div>
          {checked.refusal && (
            <p role="alert" className="text-meta text-danger">
              {checked.refusal}
            </p>
          )}
          <ContactTable
            rows={visible}
            variables={checked.variables}
            onRemove={remove}
            onUpdate={update}
            captionId={`${ids}-caption`}
          />
          {pages > 1 && (
            <Pagination count={pages} page={current} onPageChange={setPage} label="Contact pages" />
          )}
        </div>
      )}

      <p className="text-xs text-ink-muted">
        Do-not-call numbers are never dialled. Max {formatCount(MAX_CONTACTS_PER_UPLOAD)} per upload.
      </p>
      <HowItWorks title="File tips" className="mt-0" items={fileTips(agentLanguage)} />
    </section>
  );
}

const STATUS_STYLE = {
  ready: "text-ink-muted",
  duplicate: "text-ink-muted",
  invalid: "text-danger",
} as const;

/** Number and status on a phone; name and the variable columns from `sm` and `md` up. Each
 * row can be edited in place (founder, 4 Nov 2026): the pencil opens it as a small form across
 * the whole row, at every width, and the row is checked again on save. */
function ContactTable({
  rows,
  variables,
  onRemove,
  onUpdate,
  captionId,
}: {
  rows: CheckedRow[];
  variables: string[];
  onRemove: (id: string) => void;
  onUpdate: (entry: ContactEntry) => void;
  captionId: string;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const columns = 4 + variables.length;
  return (
    <div className="overflow-hidden border-y border-line">
      <table className="w-full table-fixed text-left text-sm">
        <caption id={captionId} className="sr-only">
          Contacts and whether each will be called
        </caption>
        <thead>
          <tr className="border-b border-line bg-surface-muted text-xs text-ink-faint">
            <th scope="col" className="px-3 py-2 font-medium">Phone</th>
            <th scope="col" className="hidden px-3 py-2 font-medium sm:table-cell">Name</th>
            {variables.map((key) => (
              <th key={key} scope="col" className="hidden truncate px-3 py-2 font-medium md:table-cell">
                {key}
              </th>
            ))}
            <th scope="col" className="px-3 py-2 font-medium">Status</th>
            <th scope="col" className="w-20 px-1 py-2">
              <span className="sr-only">Edit or remove</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map(({ entry, status }) =>
            editing === entry.id ? (
              <tr key={entry.id}>
                <td colSpan={columns} className="px-3 py-2">
                  <EditRow
                    entry={entry}
                    variables={variables}
                    onSave={(next) => {
                      onUpdate(next);
                      setEditing(null);
                    }}
                    onCancel={() => setEditing(null)}
                  />
                </td>
              </tr>
            ) : (
            <tr key={entry.id}>
              <td className="truncate px-3 py-2">
                <MonoValue className="tabular-nums text-ink">
                  {status.kind === "invalid" ? entry.phone || "—" : formatPhone(status.e164)}
                </MonoValue>
              </td>
              <td className="hidden truncate px-3 py-2 text-ink-muted sm:table-cell">{entry.name || "—"}</td>
              {variables.map((key) => (
                <td key={key} className="hidden truncate px-3 py-2 text-ink-muted md:table-cell">
                  {entry.vars[key] ?? ""}
                </td>
              ))}
              <td className={`px-3 py-2 text-xs ${STATUS_STYLE[status.kind]}`}>
                {status.kind === "ready" ? "Ready" : status.kind === "duplicate" ? "Duplicate" : status.reason}
              </td>
              <td className="whitespace-nowrap px-1 py-1 text-right">
                <button
                  type="button"
                  onClick={() => setEditing(entry.id)}
                  aria-label={`Edit ${entry.phone || "this row"}`}
                  className={`press ${QUIET_ICON_BUTTON}`}
                >
                  <Pencil aria-hidden className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => onRemove(entry.id)}
                  aria-label={`Remove ${entry.phone || "this row"}`}
                  className={`press ${QUIET_ICON_BUTTON}`}
                >
                  <Trash2 aria-hidden className="h-3.5 w-3.5" />
                </button>
              </td>
            </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

/** One contact opened for editing: its number, name and any extra columns, saved together.
 * Enter saves and Escape cancels; the list checks the row again once it is saved. */
function EditRow({
  entry,
  variables,
  onSave,
  onCancel,
}: {
  entry: ContactEntry;
  variables: string[];
  onSave: (entry: ContactEntry) => void;
  onCancel: () => void;
}) {
  const ids = useId();
  const [phone, setPhone] = useState(entry.phone);
  const [name, setName] = useState(entry.name);
  const [vars, setVars] = useState<Record<string, string>>(entry.vars);
  const save = () => onSave({ ...entry, phone: phone.trim(), name: name.trim(), vars });
  const cancelOnEscape = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Escape") return;
    event.stopPropagation();
    onCancel();
  };
  return (
    <form
      noValidate
      className="flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (phone.trim() !== "") save();
      }}
    >
      <label htmlFor={`${ids}-phone`} className="flex min-w-0 flex-1 basis-40 flex-col gap-1">
        <span className={FIELD_LABEL}>Phone</span>
        <input
          id={`${ids}-phone`}
          // eslint-disable-next-line jsx-a11y/no-autofocus -- the row was just opened for this
          autoFocus
          onKeyDown={cancelOnEscape}
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
          inputMode="tel"
          autoComplete="off"
          className={`${FIELD_INLINE} w-full font-mono tabular-nums`}
        />
      </label>
      <label htmlFor={`${ids}-name`} className="flex min-w-0 flex-1 basis-40 flex-col gap-1">
        <span className={FIELD_LABEL}>Name</span>
        <input
          id={`${ids}-name`}
          onKeyDown={cancelOnEscape}
          value={name}
          onChange={(event) => setName(event.target.value)}
          autoComplete="off"
          className={`${FIELD_INLINE} w-full`}
        />
      </label>
      {variables.map((key) => (
        <label key={key} htmlFor={`${ids}-${key}`} className="flex min-w-0 flex-1 basis-32 flex-col gap-1">
          <span className={`${FIELD_LABEL} truncate`}>{key}</span>
          <input
            id={`${ids}-${key}`}
            onKeyDown={cancelOnEscape}
            value={vars[key] ?? ""}
            onChange={(event) => setVars((current) => ({ ...current, [key]: event.target.value }))}
            autoComplete="off"
            className={`${FIELD_INLINE} w-full`}
          />
        </label>
      ))}
      <div className="flex gap-2">
        <button type="submit" className={PRIMARY_BUTTON_SM} disabled={phone.trim() === ""}>
          Save
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
