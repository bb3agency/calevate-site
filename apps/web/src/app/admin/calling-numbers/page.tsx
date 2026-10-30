"use client";

import { useState } from "react";

import { ADMIN_PAGE_WIDE, HAIRLINE_LIST } from "@/components/admin/kit";
import { DatePicker } from "@/components/arc/calendar";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { formatDateLong, todayIST } from "@/components/arc/ist-dates";
import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatPhone,
} from "@/components/ui";
import { useAdminAccess, type AdminAccess } from "@/app/admin/access";
import { useFilingBoard, useMarkFiled, type ClientFiling } from "@/lib/api/callingNumberFilings";

/**
 * The numbers clients authorised us to register with the telephone company (D-941, amended
 * 30 Oct 2026), and whether we have. Clients with numbers still to file come first. The
 * client's calls never wait for this; the health board raises `calling_numbers_unfiled`
 * from a week before the enforcement date. No `<h1>`: the shell takes the title from the
 * nav list.
 */
export default function CallingNumbersPage() {
  const board = useFilingBoard();
  const write = useAdminAccess("admin:tenants", "mark calling numbers filed");
  if (board.isLoading) return <Skeleton rows={6} />;
  if (!board.data) {
    return (
      <ProblemNotice
        error={board.error ?? new Error("The calling numbers did not load.")}
        onRetry={() => void board.refetch()}
      />
    );
  }
  const { clients, alarm, enforced_from } = board.data;
  const late = clients.some((client) => client.unfiled > 0);
  return (
    <div className={ADMIN_PAGE_WIDE}>
      <PageHeader description="Numbers clients authorised us to register. File them, then mark them filed." />
      {alarm && late && (
        <NoticeBox tone="warn" title={`Register these before ${formatDateLong(enforced_from)}`}>
          Clients&apos; calls keep going, but unfiled numbers break the rule from that day.
        </NoticeBox>
      )}
      {clients.length === 0 ? (
        <EmptyState message="No client has authorised numbers yet." />
      ) : (
        <ul aria-label="Clients' calling numbers" className={HAIRLINE_LIST}>
          {clients.map((client) => (
            <li key={client.tenant_id} className="space-y-3 py-4 sm:px-2">
              <ClientRow client={client} write={write} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ClientRow({ client, write }: { client: ClientFiling; write: AdminAccess }) {
  return (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <span className="text-body font-medium text-ink">{client.name}</span>
        <span className="text-meta text-ink-muted">
          Authorised {formatDateLong(client.authorised_on)}
          {client.unfiled > 0 ? ` · ${client.unfiled} to file` : " · all filed"}
        </span>
      </div>
      <ul className="space-y-1 text-sm text-ink">
        {client.numbers.map((n) => (
          <li key={n.number} className="flex flex-wrap gap-x-4">
            <span className="tabular-nums">{formatPhone(n.number)}</span>
            <span className="text-ink-muted">
              {n.filed_on ? `Filed ${formatDateLong(n.filed_on)} · ${n.filing_reference ?? ""}` : "Not filed"}
            </span>
          </li>
        ))}
      </ul>
      {client.unfiled > 0 && <MarkFiled client={client} write={write} />}
    </>
  );
}

function MarkFiled({ client, write }: { client: ClientFiling; write: AdminAccess }) {
  const mark = useMarkFiled(client.tenant_id);
  const feedback = useActionFeedback(mark, { errorDisplay: "inline" });
  const unfiled = client.numbers.filter((n) => !n.filed_on).map((n) => n.number);
  const [ticked, setTicked] = useState<string[]>(unfiled);
  const [filedOn, setFiledOn] = useState<string>(todayIST());
  const [reference, setReference] = useState("");
  const referenceId = `filing-reference-${client.tenant_id}`;

  const toggle = (number: string, on: boolean) =>
    setTicked((current) => (on ? [...current, number] : current.filter((n) => n !== number)));

  return (
    <form
      noValidate
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        feedback.run({ numbers: ticked, filed_on: filedOn, filing_reference: reference.trim() });
      }}
    >
      <RestrictionNote reason={write.reason} />
      <fieldset className="space-y-1">
        <legend className={FIELD_LABEL}>Numbers you filed</legend>
        {unfiled.map((number) => (
          <label key={number} className="flex items-center gap-3 text-sm text-ink touch:min-h-11">
            <input
              type="checkbox"
              className="h-4 w-4 shrink-0 accent-brand-strong touch:h-5 touch:w-5"
              checked={ticked.includes(number)}
              disabled={!write.allowed}
              onChange={(event) => toggle(number, event.target.checked)}
            />
            <span className="tabular-nums">{formatPhone(number)}</span>
          </label>
        ))}
      </fieldset>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <DatePicker
          label="Filed on (IST)"
          value={filedOn || null}
          max={todayIST()}
          disabled={!write.allowed}
          onChange={(day) => setFiledOn(day ?? "")}
        />
        <div>
          <label htmlFor={referenceId} className={FIELD_LABEL}>
            Reference
          </label>
          <input
            id={referenceId}
            value={reference}
            maxLength={200}
            disabled={!write.allowed}
            onChange={(event) => setReference(event.target.value)}
            className={FIELD}
          />
          <span className={FIELD_HINT}>What the filing gave back.</span>
        </div>
      </div>
      <ActionButton
        type="submit"
        status={feedback.status}
        pendingLabel="Saving…"
        successLabel="Marked filed"
        disabled={!write.allowed || ticked.length === 0 || !filedOn || !reference.trim()}
      >
        Mark filed
      </ActionButton>
      <ProblemNotice error={mark.error} />
    </form>
  );
}
