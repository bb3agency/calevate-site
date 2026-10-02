"use client";

import { useId, useMemo, useState, type DragEvent } from "react";
import { ClipboardPaste, Download, FileUp, Plus, Search, Trash2, X } from "lucide-react";

import { Pagination } from "@/components/interior/pagination";
import {
  FIELD,
  FIELD_LABEL,
  MonoValue,
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

const PAGE = 50;
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
}: {
  entries: ContactEntry[];
  onChange: (next: ContactEntry[]) => void;
  label?: string;
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
          ? ` Columns not kept: ${dropped.join(", ")} (a contact holds up to 10 extra columns, and none may be called phone or name).`
          : ""),
    );
    setPage(1);
  };

  const readFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      setNotice(`${file.name} is larger than 4 MB. Split it, and add the rest from the campaign afterwards.`);
      return;
    }
    append(await file.text(), file.name);
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
            accept=".csv,.tsv,.txt,text/csv"
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
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`rounded-card border border-dashed px-4 py-8 text-center text-sm transition-colors duration-(--duration-fast) ${
            dragging ? "border-brand bg-brand-soft text-ink" : "border-line text-ink-muted"
          }`}
        >
          Drop a CSV file here, or use Import CSV. A column called phone is all it needs.
        </div>
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
              <label className="relative block">
                <span className="sr-only">Search contacts</span>
                <Search aria-hidden className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-faint" />
                <input
                  type="search"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(1);
                  }}
                  placeholder="Search"
                  className={`${FIELD} w-40 pl-7`}
                />
              </label>
            </div>
          </div>
          {checked.refusal && (
            <p role="alert" className="text-sm font-medium text-danger">
              {checked.refusal}
            </p>
          )}
          <ContactTable rows={visible} variables={checked.variables} onRemove={remove} captionId={`${ids}-caption`} />
          {pages > 1 && (
            <Pagination count={pages} page={current} onPageChange={setPage} label="Contact pages" />
          )}
        </div>
      )}

      <p className="text-xs text-ink-faint">
        Numbers on your do-not-call list are never dialled. One upload takes up to{" "}
        {MAX_CONTACTS_PER_UPLOAD.toLocaleString("en-IN")} contacts.
      </p>
    </section>
  );
}

const STATUS_STYLE = {
  ready: "text-ink-muted",
  duplicate: "text-ink-muted",
  invalid: "text-danger",
} as const;

/** Number and status on a phone; name and the variable columns from `sm` and `md` up. */
function ContactTable({
  rows,
  variables,
  onRemove,
  captionId,
}: {
  rows: CheckedRow[];
  variables: string[];
  onRemove: (id: string) => void;
  captionId: string;
}) {
  return (
    <div className="overflow-hidden rounded-card border border-line">
      <table className="w-full table-fixed text-left text-sm">
        <caption id={captionId} className="sr-only">
          Contacts and whether each will be called
        </caption>
        <thead>
          <tr className="border-b border-line bg-app text-xs text-ink-faint">
            <th scope="col" className="px-3 py-2 font-medium">Phone</th>
            <th scope="col" className="hidden px-3 py-2 font-medium sm:table-cell">Name</th>
            {variables.map((key) => (
              <th key={key} scope="col" className="hidden truncate px-3 py-2 font-medium md:table-cell">
                {key}
              </th>
            ))}
            <th scope="col" className="px-3 py-2 font-medium">Status</th>
            <th scope="col" className="w-12 px-1 py-2">
              <span className="sr-only">Remove</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map(({ entry, status }) => (
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
              <td className="px-1 py-1 text-right">
                <button
                  type="button"
                  onClick={() => onRemove(entry.id)}
                  aria-label={`Remove ${entry.phone || "this row"}`}
                  className="press inline-flex h-8 w-8 items-center justify-center rounded-md text-ink-faint hover:bg-ink/[0.06] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11"
                >
                  <Trash2 aria-hidden className="h-3.5 w-3.5" />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
