"use client";

import { useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Section } from "@/components/console/section";
import { InfoTip } from "@/components/console/infoTip";
import { FIELD, FIELD_LABEL, ProblemNotice, Skeleton, ToggleSwitch } from "@/components/ui";
import {
  offCells,
  useAlertPreferences,
  useSaveAlertPreferences,
  useSendAlertSample,
  type AlertKindRow,
  type AlertPreferences,
  type SampleChannel,
} from "@/lib/api/alertPreferences";
import { useClientSession } from "@/lib/api/session";
import { leadWords, useAccountCapabilities } from "@/lib/businessCapabilities";

/**
 * ALERTS YOU CAN SHAPE (D-1048): one table, rows = what happened, columns = where it arrives.
 * The server says which cells exist, which are always on and who may change the account ones
 * (email, WhatsApp, quiet hours, the daily limit: the owner's); this screen draws them and
 * sends back the cells left off. Bell and computer are each person's own.
 */

const CHANNELS = [
  { key: "bell", label: "Bell" },
  { key: "computer", label: "Computer" },
  { key: "email", label: "Email" },
  { key: "whatsapp", label: "WhatsApp" },
] as const;
const ACCOUNT_CHANNELS = new Set<string>(["email", "whatsapp"]);
const CAPS = [5, 8, 12, 20, 30, 50, 100];
const HOURS = Array.from({ length: 24 }, (_, h) => h);

function hourLabel(hour: number): string {
  const suffix = hour < 12 ? "am" : "pm";
  const twelve = hour % 12 === 0 ? 12 : hour % 12;
  return `${twelve} ${suffix}`;
}

export function AlertTable() {
  const session = useClientSession();
  const prefs = useAlertPreferences(session);
  return (
    <Section
      title="What you hear about"
      description="Choose where each alert reaches you."
      info={
        <p>
          Some alerts are always on, because missing them stops your calls. Bell and Computer are
          yours alone; the owner sets email and WhatsApp for the account.
        </p>
      }
    >
      {prefs.error != null ? (
        <ProblemNotice error={prefs.error} onRetry={() => void prefs.refetch()} />
      ) : !prefs.data ? (
        <Skeleton rows={6} label="Loading your alerts" />
      ) : (
        <AlertForm key={JSON.stringify(prefs.data)} prefs={prefs.data} />
      )}
    </Section>
  );
}

function AlertForm({ prefs }: { prefs: AlertPreferences }) {
  const session = useClientSession();
  const save = useSaveAlertPreferences(session);
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Alerts saved" });
  const words = leadWords(useAccountCapabilities());
  const [off, setOff] = useState<Set<string>>(() => new Set(offCells(prefs)));
  const [quiet, setQuiet] = useState(prefs.quiet_enabled);
  const [from, setFrom] = useState(prefs.quiet_start_hour);
  const [until, setUntil] = useState(prefs.quiet_end_hour);
  const [cap, setCap] = useState(prefs.daily_cap);
  const account = prefs.account_editable;

  const label = (row: AlertKindRow) =>
    row.key === "hot_lead" ? `${words.hotLead.charAt(0).toUpperCase()}${words.hotLead.slice(1)}` : row.label;

  const toggle = (cell: string, on: boolean) => {
    const next = new Set(off);
    if (on) next.delete(cell);
    else next.add(cell);
    setOff(next);
  };

  return (
    <form
      noValidate
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        feedback.run({
          off: [...off].sort(),
          quiet_enabled: quiet,
          quiet_start_hour: from,
          quiet_end_hour: until,
          daily_cap: cap,
        });
      }}
    >
      <div role="table" aria-label="Where each alert reaches you" className="border-y border-line">
        <div role="row" className="hidden grid-cols-[1fr_repeat(4,5rem)] gap-2 py-2 sm:grid">
          <span role="columnheader" className="text-meta text-ink-muted">
            What happened
          </span>
          {CHANNELS.map((c) => (
            <span key={c.key} role="columnheader" className="text-center text-meta text-ink-muted">
              {c.label}
            </span>
          ))}
        </div>
        {prefs.kinds.map((row) => (
          <div
            key={row.key}
            role="row"
            className="grid grid-cols-4 items-center gap-2 border-t border-line py-3 sm:grid-cols-[1fr_repeat(4,5rem)]"
          >
            <span role="rowheader" className="col-span-4 flex items-center gap-1 text-body text-ink sm:col-span-1">
              {label(row)}
              {row.always && row.why ? (
                <InfoTip label={`${label(row)}, always on`}>
                  <p>{row.why}</p>
                </InfoTip>
              ) : null}
            </span>
            {CHANNELS.map((c) => (
              <Cell
                key={c.key}
                state={row.cells[c.key] ?? "none"}
                channel={c.label}
                checked={!off.has(`${row.key}:${c.key}`)}
                disabled={ACCOUNT_CHANNELS.has(c.key) && !account}
                rowLabel={label(row)}
                onChange={(on) => toggle(`${row.key}:${c.key}`, on)}
              />
            ))}
          </div>
        ))}
      </div>
      {!account ? <p className="text-meta text-ink-muted">Email, WhatsApp and the limits below are set by the owner.</p> : null}

      <div className="space-y-3">
        <ToggleSwitch
          label="Quiet hours"
          hint="Email and WhatsApp wait, then come as one message."
          checked={quiet}
          disabled={!account}
          onChange={setQuiet}
        />
        {quiet ? (
          <div className="flex flex-wrap gap-4 pl-12">
            <HourSelect label="From" value={from} disabled={!account} onChange={setFrom} />
            <HourSelect label="Until" value={until} disabled={!account} onChange={setUntil} />
          </div>
        ) : null}
        <label className="block max-w-xs">
          <span className={FIELD_LABEL}>Most alert emails in a day</span>
          <select
            className={FIELD}
            value={cap}
            disabled={!account}
            onChange={(event) => setCap(Number(event.target.value))}
          >
            {CAPS.map((n) => (
              <option key={n} value={n}>
                {n}, then one email with the rest
              </option>
            ))}
          </select>
        </label>
      </div>

      {save.error ? <ProblemNotice error={save.error} /> : null}
      <ActionButton type="submit" variant="primary-sm" status={feedback.status} successLabel="Saved">
        Save alerts
      </ActionButton>

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <span className="text-meta text-ink-muted">Try it:</span>
        <SampleButton channel="email">Send me a sample email</SampleButton>
        {prefs.governs_account ? <SampleButton channel="whatsapp">Send me a sample WhatsApp</SampleButton> : null}
      </div>
    </form>
  );
}

function Cell({
  state,
  channel,
  checked,
  disabled,
  rowLabel,
  onChange,
}: {
  state: string;
  channel: string;
  checked: boolean;
  disabled: boolean;
  rowLabel: string;
  onChange: (on: boolean) => void;
}) {
  if (state === "none") {
    return (
      <span role="cell" className="text-center text-meta text-ink-faint">
        <span aria-hidden>–</span>
        <span className="sr-only">{`${channel}: not sent here`}</span>
      </span>
    );
  }
  if (state === "always") {
    return (
      <span role="cell" className="text-center text-meta text-ink-muted">
        <span className="sm:sr-only">{channel}: </span>Always
      </span>
    );
  }
  return (
    <span role="cell" className="flex justify-center">
      <label className="flex cursor-pointer items-center gap-1.5 touch:min-h-11">
        <input
          type="checkbox"
          className="h-4 w-4 accent-action"
          checked={checked}
          disabled={disabled}
          aria-label={`${rowLabel} by ${channel}`}
          onChange={(event) => {
            if (disabled) return;
            onChange(event.target.checked);
          }}
        />
        <span aria-hidden className="text-meta text-ink-muted sm:hidden">
          {channel}
        </span>
      </label>
    </span>
  );
}

function HourSelect({
  label,
  value,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  disabled: boolean;
  onChange: (hour: number) => void;
}) {
  return (
    <label className="block w-32">
      <span className={FIELD_LABEL}>{label}</span>
      <select
        className={FIELD}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {HOURS.map((h) => (
          <option key={h} value={h}>
            {hourLabel(h)}
          </option>
        ))}
      </select>
    </label>
  );
}

function SampleButton({ channel, children }: { channel: SampleChannel; children: string }) {
  const session = useClientSession();
  const send = useSendAlertSample(session);
  const feedback = useActionFeedback(send, {
    errorDisplay: "toast",
    successToast: (data) => (data.queued ? "Sample on its way" : "Sent a moment ago. Try again in a few minutes."),
  });
  return (
    <ActionButton variant="secondary-sm" status={feedback.status} successLabel="Sent" onClick={() => feedback.run(channel)}>
      {children}
    </ActionButton>
  );
}
