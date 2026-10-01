"use client";

import { useMemo, useRef } from "react";

import { PageHeader } from "@/components/console/pageHeader";
import { RowMenu } from "@/components/console/rowMenu";
import { CopyButton } from "@/components/interior/copy-button";
import { NoticeDocument, printableClone } from "@/components/noticeDocument";
import { PRIMARY_BUTTON, ProblemNotice, Skeleton } from "@/components/ui";
import { useCallerNotice, type CallerNotice } from "@/lib/api/callerNotice";
import { useMe } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { blankKeys, fill, toPlainText, valueOf } from "@/lib/noticeDraft/blanks";
import { parseNotice } from "@/lib/noticeDraft/blocks";
import { printDocument } from "@/lib/printDocument";

import { downloadText } from "./download";
import { FillPanel } from "./FillPanel";
import { useBlankValues } from "./useBlankValues";

/**
 * The privacy notice a client owes their OWN callers (LEGAL-SURFACE F-8, D-179), as a
 * draft document they fill in and hand to their advocate.
 *
 * The words are the server's `notice_markdown`, rendered and never rewritten: rebuilding
 * them here would give one legal document two spellings. The disclaimer is shown above
 * the sheet AND stays inside it, because a warning that lives only beside the document
 * stops travelling once the text is copied out. The blanks are filled in this browser
 * only (`useBlankValues`); Copy, Download and Print all produce the filled text.
 *
 * No `useWriteAccess` gate: nothing is written to us, and the endpoint takes `org:read`
 * so a read-only "view as client" session (D-22) can open it with a client on the phone.
 */
export default function CallerNoticePage() {
  const session = useClientSession();
  const notice = useCallerNotice(session);

  // The document is declared by SHAPE, not text: the copilot has no business rewriting a
  // legal draft, and the four facts below are what a person on this screen asks about.
  useCopilotSurface({
    route: "/c/{slug}/caller-notice",
    title: "What you tell your callers",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: notice.data
          ? "the draft notice has loaded"
          : notice.isError
            ? "the draft failed to load, so nothing is shown"
            : "still loading",
      },
      ...(notice.data
        ? [
            { key: "collected_items", label: "Details itemised as collected from callers", value: String(notice.data.collected.length) },
            { key: "retention_lines", label: "Retention lines (how long each kind of record is kept)", value: String(notice.data.retention.length) },
            {
              key: "ai_disclosure_off",
              label: "Agents that do NOT announce they are an AI at the start",
              value: notice.data.ai_disclosure_off.join(", ") || "none — every agent announces it",
            },
            {
              key: "recording_notice_off",
              label: "Agents that do NOT announce the call is recorded",
              value: notice.data.recording_notice_off.join(", ") || "none — every agent announces it",
            },
            { key: "open_questions", label: "Things the draft says it cannot answer yet", value: notice.data.open_questions.join("; ") || "none" },
          ]
        : []),
    ],
    apply: noFill,
  });

  if (notice.isError) return <ProblemNotice error={notice.error} />;
  if (!notice.data) {
    return (
      <div className="mx-auto max-w-[46rem] rounded-sm border border-line bg-surface p-8">
        <Skeleton rows={8} label="Loading your privacy notice" />
      </div>
    );
  }
  return <Draft notice={notice.data} />;
}

function Draft({ notice }: { notice: CallerNotice }) {
  const session = useClientSession();
  const me = useMe(session);
  // Not persisted until we know this is not a support session.
  const persist = me.data !== undefined && !me.data.impersonating;
  const { values, set, clear } = useBlankValues(session.orgSlug, persist);
  const sheet = useRef<HTMLElement>(null);

  const blocks = useMemo(() => parseNotice(notice.notice_markdown), [notice.notice_markdown]);
  const keys = useMemo(() => blankKeys(notice.notice_markdown), [notice.notice_markdown]);
  const filled = fill(notice.notice_markdown, values);
  const done = keys.filter((key) => valueOf(values, key) !== null).length;

  const print = () => {
    if (sheet.current) void printDocument(printableClone(sheet.current, values), { title: "Privacy notice (draft)" });
  };

  return (
    <div className="space-y-5 pb-12">
      <PageHeader
        description={
          keys.length > 0
            ? `A draft notice for your callers, built from your settings. ${done} of ${keys.length} blanks filled.`
            : "A draft notice for your callers, built from your settings."
        }
        actions={
          <>
            <CopyButton value={filled} label="Copy" variant="text" />
            <RowMenu
              label="the draft"
              items={[
                { id: "txt", label: "Download as text (.txt)", onSelect: () => downloadText(toPlainText(filled), "privacy-notice-draft.txt", "text/plain") },
                { id: "md", label: "Download as Markdown (.md)", onSelect: () => downloadText(filled, "privacy-notice-draft.md", "text/markdown") },
              ]}
            />
            <button type="button" onClick={print} className={PRIMARY_BUTTON}>
              Print or save as PDF
            </button>
          </>
        }
      />

      {/* The server's own sentence, word for word, before the document it qualifies. */}
      <p role="note" className="rounded-md border border-warn-line bg-warn-soft px-3 py-2 text-[13px] leading-snug text-warn">
        {notice.disclaimer}
      </p>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_17rem] lg:items-start">
        <aside aria-label="Your blanks and announcements" className="lg:sticky lg:top-0 lg:col-start-2 lg:row-start-1">
          <FillPanel notice={notice} keys={keys} values={values} onClear={clear} />
        </aside>
        <div className="min-w-0 lg:col-start-1 lg:row-start-1 settings-enter">
          <NoticeDocument ref={sheet} blocks={blocks} values={values} onChange={set} />
        </div>
      </div>
    </div>
  );
}
