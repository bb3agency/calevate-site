"use client";

/**
 * THE BOOKING JOB'S OWN VIEW, once it is set up: one switch, what it is set to, a way to
 * try it, and the two calendar steps behind it. The header (icon, name, line) is drawn by
 * `Actions`, the same as every other action's view.
 *
 * "Try it" runs the job's CHECK half with a time the owner picks. Checking reads the
 * calendar and books nothing, which is why it is safe to offer in the open; a real test of
 * the booking half (which really books) stays behind Manage on the step below, with its
 * warning.
 */

import { useState } from "react";

import { TEXT_ACTION } from "@/components/console/section";
import { ServiceLogo } from "@/components/console/serviceLogo";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { Disclosure, FIELD, ProblemNotice, SECONDARY_BUTTON, ToggleSwitch } from "@/components/ui";
import {
  RUN_STATUS_LABELS,
  useCredentials,
  useSetActionEnabled,
  useTestAction,
  type ActionTool,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

import { addMinutesLocal, daysLabel, hourLabel, keptHours, lengthLabel, readBooking } from "./jobs";
import { ToolRow } from "./ToolRow";


export function BookingJob({
  agentId,
  session,
  check,
  book,
  onChange,
}: {
  agentId: string;
  session: Session;
  check: ActionTool | undefined;
  book: ActionTool | undefined;
  onChange: () => void;
}) {
  const creds = useCredentials(session);
  const setEnabled = useSetActionEnabled(session, agentId);
  const settings = readBooking(check, book);
  const kept = keptHours(check, book);
  const parts = [check, book].filter((t): t is ActionTool => t !== undefined);
  const on = parts.length === 2 && parts.every((t) => t.enabled);
  const account = creds.data?.find((c) => c.id === settings.credentialId);
  const change = (
    <button type="button" className={TEXT_ACTION} onClick={onChange}>
      Change
    </button>
  );

  return (
    <div className="space-y-8">
      <div>
      <ToggleSwitch
        label="Use it on calls"
        hint={on ? "Your agent offers free times and books them." : "Your agent will not book anything."}
        checked={on}
        disabled={setEnabled.isPending || parts.length < 2}
        onChange={(next) => {
          for (const t of parts) setEnabled.mutate({ toolId: t.id, enabled: next });
        }}
      />
      {setEnabled.error ? <ProblemNotice error={setEnabled.error} /> : null}
      </div>

      <div>

      <SettingRows className="border-y border-line">
        <SettingRow
          label="Calendar"
          value={
            account ? (
              <span className="inline-flex items-center gap-1.5">
                <ServiceLogo service="google_calendar" className="h-5 w-5" />
                {`Google · ${account.label}`}
              </span>
            ) : (
              <span className="text-ink-muted">Not connected</span>
            )
          }
          action={change}
        />
        <SettingRow label="Length" value={lengthLabel(settings.durationMin)} action={change} />
        <SettingRow
          label="Hours"
          hint={
            kept === null
              ? "Not a rule yet: your agent could book at any time. Use Change to set your hours."
              : undefined
          }
          value={kept === null ? "Any time" : `${hourLabel(kept.from)} – ${hourLabel(kept.to)}`}
          action={change}
        />
        <SettingRow label="Days" value={daysLabel(settings.days)} action={change} />
      </SettingRows>
      {parts.length < 2 ? (
        <p className="mt-3 text-meta text-warn">
          Only half of this is set up, so your agent cannot book yet. Use Change to finish it.
        </p>
      ) : null}
      </div>

      {check ? <TryIt agentId={agentId} session={session} check={check} minutes={settings.durationMin} /> : null}

      <div className="border-t border-line">
      <Disclosure variant="inline" headingLevel={4} title="The two steps behind it">
        <ul className="divide-y divide-line">
          {parts.map((t) => (
            <ToolRow key={t.id} tool={t} agentId={agentId} session={session} />
          ))}
        </ul>
      </Disclosure>
      </div>
    </div>
  );
}

function TryIt({
  agentId,
  session,
  check,
  minutes,
}: {
  agentId: string;
  session: Session;
  check: ActionTool;
  minutes: number;
}) {
  const test = useTestAction(session, agentId);
  const [at, setAt] = useState("");
  const startParam = typeof check.config.start_param === "string" ? check.config.start_param : "start";
  const endParam = typeof check.config.end_param === "string" ? check.config.end_param : "end";
  const result = test.data;
  const payload = (result?.payload ?? {}) as { available?: unknown; free_slots?: unknown };
  const slots = Array.isArray(payload.free_slots)
    ? payload.free_slots
        .map((s) => (s && typeof s === "object" ? (s as { say?: unknown }).say : undefined))
        .filter((s): s is string => typeof s === "string")
    : [];

  return (
    <div>
      <h4 className="text-body font-medium text-ink">Try it</h4>
      <p className="mt-0.5 text-meta text-ink-muted">
        Pick a time and we check your calendar the way your agent would. Nothing is booked.
      </p>
      <form
        noValidate
        className="mt-3 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (!at) return;
          test.mutate({
            toolId: check.id,
            values: { [startParam]: at, [endParam]: addMinutesLocal(at, minutes * 3) },
            testPhone: null,
          });
        }}
      >
        <label className="block">
          <span className="sr-only">Time to check, India time</span>
          <input
            type="datetime-local"
            className={`${FIELD} mt-0 w-auto`}
            value={at}
            onChange={(e) => setAt(e.target.value)}
          />
        </label>
        <button type="submit" className={SECONDARY_BUTTON} disabled={!at || test.isPending}>
          {test.isPending ? "Checking…" : "Check this time"}
        </button>
      </form>
      {test.isError ? (
        <div className="mt-3">
          <ProblemNotice error={test.error} />
        </div>
      ) : null}
      {result ? (
        <p role="status" className="mt-3 text-body text-ink">
          {!result.ok
            ? (lookup(RUN_STATUS_LABELS, result.status) ?? "It did not work.")
            : payload.available === true
              ? `Free. Your agent would offer ${slots[0] ?? "that time"}.`
              : slots.length > 0
                ? `That time is taken. Free nearby: ${slots.slice(0, 3).join("; ")}.`
                : "Nothing is free around that time."}
        </p>
      ) : null}
    </div>
  );
}
