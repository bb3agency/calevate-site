"use client";

import { useId, useState } from "react";
import { Plus } from "lucide-react";
import clsx from "clsx";

import { useAdminAccess } from "@/app/admin/access";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { RowMenu } from "@/components/arc/menu";
import { ADMIN_PAGE_WIDE, HAIRLINE_LIST, StatusPill } from "@/components/admin/kit";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Drawer } from "@/components/console/drawer";
import { EmptySketch } from "@/components/console/emptySketch";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { NOTICE_DOT } from "@/components/console/statusPill";
import { SegmentedControl } from "@/components/interior/segmented-control";
import {
  PRIMARY_BUTTON,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
  formatCount,
  formatIST,
  type NoticeTone,
} from "@/components/ui";
import {
  useAdminAnnouncements,
  useCreateAnnouncement,
  useEndAnnouncement,
  useUpdateAnnouncement,
  type AdminAnnouncement,
} from "@/lib/api/announcements";

import { AnnouncementForm } from "./AnnouncementForm";
import {
  EMPTY_DRAFT,
  audienceLabel,
  createInput,
  draftFrom,
  updateInput,
  validateDraft,
  type AnnouncementDraft,
} from "./announcementDraft";

const STATE: Record<AdminAnnouncement["state"], { label: string; tone: NoticeTone }> = {
  showing: { label: "Showing now", tone: "ok" },
  scheduled: { label: "Scheduled", tone: "neutral" },
  finished: { label: "Finished", tone: "neutral" },
  ended: { label: "Ended early", tone: "neutral" },
};

const TONE_DOT: Record<AdminAnnouncement["tone"], string> = {
  info: NOTICE_DOT.neutral,
  success: NOTICE_DOT.ok,
  warning: NOTICE_DOT.warn,
  critical: NOTICE_DOT.stop,
};

const TONE_WORD: Record<AdminAnnouncement["tone"], string> = {
  info: "Information",
  success: "Good news",
  warning: "Heads up",
  critical: "Urgent",
};

type Editing = { mode: "create" } | { mode: "edit"; row: AdminAnnouncement };

/**
 * The announcement composer (D-869): what every client console shows in the strip above
 * its top bar. Current and scheduled announcements first; past ones on the second tab.
 * The server audits every create, change and end, so nothing here keeps its own log.
 */
export function AnnouncementsScreen() {
  const write = useAdminAccess("admin:tenants", "publish announcements to clients");
  const [view, setView] = useState<"current" | "past">("current");
  const list = useAdminAnnouncements(view === "past");

  const create = useCreateAnnouncement();
  const update = useUpdateAnnouncement();
  const end = useEndAnnouncement();
  const createFeedback = useActionFeedback(create, {
    errorDisplay: "inline",
    successToast: (row) =>
      row.state === "scheduled" ? `Announcement scheduled for ${formatIST(row.starts_at)}` : "Announcement published",
    successDescription: (row) => `Shown to: ${audienceLabel(row)}.`,
  });
  const updateFeedback = useActionFeedback(update, {
    errorDisplay: "inline",
    successToast: "Announcement updated",
  });
  const endFeedback = useActionFeedback(end, {
    errorDisplay: "inline",
    successToast: "Announcement ended",
    successDescription: "Clients stop seeing it on their next page load.",
  });

  const [editing, setEditing] = useState<Editing | null>(null);
  const [original, setOriginal] = useState<AnnouncementDraft>(EMPTY_DRAFT);
  const [draft, setDraft] = useState<AnnouncementDraft>(EMPTY_DRAFT);
  const [tried, setTried] = useState(false);
  const [ending, setEnding] = useState<AdminAnnouncement | null>(null);
  const formId = useId();

  const open = (next: Editing) => {
    const start = next.mode === "edit" ? draftFrom(next.row) : EMPTY_DRAFT;
    create.reset();
    update.reset();
    setOriginal(start);
    setDraft(start);
    setTried(false);
    setEditing(next);
  };
  const close = () => setEditing(null);

  const errors = validateDraft(draft);
  const valid = Object.keys(errors).length === 0;
  const change = editing?.mode === "edit" ? updateInput(original, draft) : null;
  const unchanged = change !== null && Object.keys(change).length === 0;
  const dirty = JSON.stringify(draft) !== JSON.stringify(original);
  const saving = editing?.mode === "edit" ? updateFeedback : createFeedback;

  const submit = () => {
    setTried(true);
    if (!valid || saving.status === "pending" || !editing) return;
    if (editing.mode === "create") {
      create.mutate(createInput(draft), { onSuccess: close });
    } else if (change && !unchanged) {
      update.mutate({ id: editing.row.id, change }, { onSuccess: close });
    }
  };

  const rows = list.data?.items;
  return (
    <div className={ADMIN_PAGE_WIDE}>
      <PageHeader
        description="A one-line message shown across the top of client consoles: news, planned work, or something urgent."
        meta={
          list.data ? (
            <span>
              {formatCount(list.data.total)} {view === "current" ? "current or scheduled" : "past"}
            </span>
          ) : undefined
        }
        actions={
          <button
            type="button"
            className={PRIMARY_BUTTON}
            disabled={!write.allowed}
            onClick={() => open({ mode: "create" })}
          >
            <Plus aria-hidden className="h-4 w-4" />
            New announcement
          </button>
        }
      />
      <RestrictionNote reason={write.reason} />

      <div className="space-y-4">
        <SegmentedControl
          label="Which announcements"
          value={view}
          onValueChange={(value) => setView(value as "current" | "past")}
          options={[
            { value: "current", label: "Current" },
            { value: "past", label: "Past" },
          ]}
          className="w-full sm:w-auto"
        />

        {list.error ? (
          <EmptyState variant="error" message="Announcements did not load." error={list.error} onRetry={() => void list.refetch()} />
        ) : !rows ? (
          <Skeleton rows={3} label="Loading announcements…" />
        ) : rows.length === 0 ? (
          view === "current" ? (
            <EmptyState
              message="Nothing is being shown to clients."
              hint="An announcement appears in the strip above every client's top bar."
              illustration={<EmptySketch rows={[{ title: "xxxxxxxxxxxxxxxxxxxxxxxx", meta: "xxxxxxxxxxxxx", pill: "xxxxxxx", tone: "brand" }]} />}
              action={
                write.allowed ? (
                  <button type="button" className={SECONDARY_BUTTON} onClick={() => open({ mode: "create" })}>
                    Write an announcement
                  </button>
                ) : undefined
              }
            />
          ) : (
            <EmptyState message="No past announcements yet." hint="Announcements move here once they end." />
          )
        ) : (
          <ul className={HAIRLINE_LIST}>
            {rows.map((row) => (
              <AnnouncementRow
                key={row.id}
                row={row}
                canWrite={write.allowed}
                onEdit={() => open({ mode: "edit", row })}
                onEnd={() => {
                  end.reset();
                  setEnding(row);
                }}
              />
            ))}
          </ul>
        )}
      </div>

      <Drawer
        open={editing !== null}
        onClose={close}
        title={editing?.mode === "edit" ? "Change the announcement" : "New announcement"}
        description={
          editing?.mode === "edit" && editing.row.state === "showing"
            ? "Clients see the change on their next page load."
            : "Nothing is shown until you publish."
        }
        width="lg"
        formId={formId}
        dirty={dirty && saving.status !== "success"}
        footer={
          <div className="flex flex-wrap items-center justify-end gap-3">
            {editing?.mode === "edit" && unchanged ? (
              <span className="text-meta text-ink-muted">Nothing has changed yet.</span>
            ) : null}
            <button type="button" className={SECONDARY_BUTTON} onClick={close}>
              Cancel
            </button>
            <ActionButton
              type="submit"
              form={formId}
              status={saving.status}
              disabled={!write.allowed || (editing?.mode === "edit" && unchanged)}
              pendingLabel={editing?.mode === "edit" ? "Saving…" : "Publishing…"}
              successLabel={editing?.mode === "edit" ? "Saved" : "Published"}
            >
              {editing?.mode === "edit"
                ? "Save changes"
                : draft.startsAt
                  ? "Schedule"
                  : "Publish now"}
            </ActionButton>
          </div>
        }
      >
        <AnnouncementForm
          id={formId}
          draft={draft}
          onChange={setDraft}
          errors={errors}
          showErrors={tried}
          failure={editing?.mode === "edit" ? update.error : create.error}
          disabled={!write.allowed}
          onSubmit={submit}
        />
      </Drawer>

      {ending ? (
        <ConfirmDialog
          title="End this announcement now?"
          confirmLabel="End it now"
          pendingLabel="Ending…"
          successLabel="Ended"
          cancelLabel="Keep it showing"
          status={endFeedback.status}
          error={end.error}
          onCancel={() => setEnding(null)}
          onConfirm={() => end.mutate(ending.id, { onSuccess: () => setEnding(null) })}
        >
          <p className="break-words">
            “{ending.message}” stops showing to{" "}
            {ending.audience === "tenant" ? audienceLabel(ending) : audienceLabel(ending).toLowerCase()}. It moves to Past and
            cannot be shown again; to bring it back, write a new one.
          </p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

function AnnouncementRow({
  row,
  canWrite,
  onEdit,
  onEnd,
}: {
  row: AdminAnnouncement;
  canWrite: boolean;
  onEdit: () => void;
  onEnd: () => void;
}) {
  const state = STATE[row.state];
  const live = row.state === "showing" || row.state === "scheduled";
  const span =
    row.state === "ended"
      ? `${formatIST(row.starts_at)} to ${formatIST(row.ended_at)} (ended early)`
      : row.ends_at
        ? `${formatIST(row.starts_at)} to ${formatIST(row.ends_at)}`
        : `From ${formatIST(row.starts_at)}, until ended`;
  return (
    <li className="flex items-start gap-3 py-4 sm:px-2">
      <span
        aria-hidden
        className={clsx("mt-2 h-2 w-2 shrink-0 rounded-full", TONE_DOT[row.tone])}
      />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="break-words text-body font-medium text-ink">{row.message}</p>
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-meta text-ink-muted">
          <StatusPill tone={state.tone}>{state.label}</StatusPill>
          <span>{TONE_WORD[row.tone]}</span>
          <span aria-hidden>·</span>
          <span className="min-w-0 break-words">{audienceLabel(row)}</span>
        </p>
        <p className="text-meta text-ink-muted">{span} IST</p>
        {row.link_url ? (
          <p className="break-all text-meta text-ink-muted">
            Link: {row.link_label ? `${row.link_label} → ` : ""}
            {row.link_url}
          </p>
        ) : null}
      </div>
      {live && canWrite ? (
        <RowMenu
          label={`Actions for the announcement “${row.message.slice(0, 40)}”`}
          items={[
            { id: "edit", label: "Change", onSelect: onEdit },
            { id: "end", label: "End now", tone: "danger", onSelect: onEnd, separated: true },
          ]}
        />
      ) : null}
    </li>
  );
}
