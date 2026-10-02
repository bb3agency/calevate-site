"use client";

import { useState } from "react";
import { CheckCircle2, Lock, TriangleAlert } from "lucide-react";

import { MonoValue, ProvenanceBadge, TimingBadge } from "@/app/admin/ops/opsLanguage";
import { Drawer } from "@/components/console/drawer";
import { NoticeBox, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { ConfigField, ConfigWrite } from "@/lib/api/opsConfig";

import { ConfigForm } from "./ConfigForm";
import {
  AppliesNotice,
  appliesVerdict,
  display,
  etagOf,
  provenance,
  readOnlyReason,
  settingLabel,
} from "./configField";

/**
 * One setting: what it is now, where it came from, and — when it can be changed — a Change
 * button that opens the form in a drawer.
 *
 * The form is closed until asked for: sixty settings each with an open input is a screen
 * where a stray keystroke edits the platform, and the row's job most of the time is to
 * answer "what is this set to, and who set it". The drawer is full-screen on a phone and
 * keeps the receipt on the ROW after it closes, so the confirmation outlives the form.
 */
export function ConfigRow({
  field,
  access,
}: {
  field: ConfigField;
  access: { allowed: boolean; reason: string | null };
}) {
  const [open, setOpen] = useState(false);
  const [receipt, setReceipt] = useState<ConfigWrite | null>(null);
  const verdict = appliesVerdict(field);
  const tag = etagOf(field);
  const label = settingLabel(field.key);

  return (
    <div className="py-3.5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
        <div className="min-w-0 sm:flex-1">
          <p className="text-[14px] font-medium text-ink">{label}</p>
          {/* `break-all`: unbroken snake_case keys and values have nowhere to wrap at 320px. */}
          <p className="mt-0.5 break-all text-xs text-ink-faint">
            <MonoValue>{field.key}</MonoValue> · {provenance(field)}
          </p>
          {field.source === "db" && field.note && (
            <p className="mt-1 text-xs text-ink-muted">&ldquo;{field.note}&rdquo;</p>
          )}
        </div>
        <div className="min-w-0 space-y-1.5 sm:max-w-[55%] sm:text-right">
          <p className="break-all text-[14px] font-semibold text-ink">
            <MonoValue>{display(field.value)}</MonoValue>
          </p>
          {/* Fed from the verdict, not the raw `applies`, so a live field carrying a caveat
              reads "after you republish" here exactly as it does in the form. */}
          <div className="flex flex-wrap items-center gap-1.5 sm:justify-end">
            <ProvenanceBadge source={field.source} />
            <TimingBadge applies={verdict.id} />
          </div>
          <RowControl
            field={field}
            tag={tag}
            access={access}
            label={label}
            onOpen={() => {
              // Opening the form retires the previous receipt: a confirmation for the last
              // write above the next one is how two changes become one remembered change.
              setReceipt(null);
              setOpen(true);
            }}
          />
        </div>
      </div>

      {/* Re-read on EVERY render: a refetch that turns the key env-pinned takes the form
          away, because the write it would send is one the API now refuses. */}
      <Drawer
        open={open && field.editable && tag !== null}
        onClose={() => setOpen(false)}
        title={`Change ${label}`}
        description={<MonoValue>{field.key}</MonoValue>}
        width="md"
      >
        {tag !== null && (
          <ConfigForm
            field={field}
            basis={tag}
            onDone={() => setOpen(false)}
            onWritten={(write) => {
              setReceipt(write);
              setOpen(false);
            }}
          />
        )}
      </Drawer>

      {!open && receipt && (
        <WriteReceipt write={receipt} field={field} onDismiss={() => setReceipt(null)} />
      )}
    </div>
  );
}

function RowControl({
  field,
  tag,
  access,
  label,
  onOpen,
}: {
  field: ConfigField;
  tag: string | null;
  access: { allowed: boolean; reason: string | null };
  label: string;
  onOpen: () => void;
}) {
  if (field.editable && tag === null) {
    // The API answered without a precondition token and refuses every write that carries
    // no `If-Match` (428), so an edit here could only be refused.
    return (
      <p className="flex items-start gap-1.5 text-left text-xs text-ink-muted sm:ml-auto sm:max-w-[18rem]">
        <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          This platform did not send a version tag for this setting, and it refuses any
          change that does not name the value being replaced. The console cannot offer an
          edit it knows would be refused — the platform and this screen are on different
          versions, which is not something your account can fix.
        </span>
      </p>
    );
  }
  if (field.editable) {
    return (
      <button
        type="button"
        onClick={onOpen}
        disabled={!access.allowed}
        title={access.reason ?? undefined}
        aria-label={`Change ${label}`}
        className={SECONDARY_BUTTON_SM}
      >
        Change
      </button>
    );
  }
  // Read-only WITH the reason — not a hidden row, not a dead input.
  return (
    <div className="flex items-start gap-1.5 text-left text-xs text-ink-muted sm:ml-auto sm:max-w-[18rem]">
      <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>{readOnlyReason(field)}</span>
    </div>
  );
}

/**
 * What the SERVER stored, after it stored it — every value from `ConfigWriteOut`, never the
 * draft. The last notice matters most: the write went to the STORE, and the row beside it
 * is what the process serving this screen has in force; on a stale snapshot those disagree,
 * and an operator reading only the row would conclude the save failed and do it again.
 */
function WriteReceipt({
  write,
  field,
  onDismiss,
}: {
  write: ConfigWrite;
  field: ConfigField;
  onDismiss: () => void;
}) {
  const verdict = appliesVerdict(write.field);
  const inForceHere = field.value === write.field.value;
  // `recorded === false`: the submitted value was ALREADY stored, so nothing moved and no
  // audit entry exists. Absent means an API that only ever recorded.
  const recorded = write.recorded !== false;

  return (
    <div className="mt-3 space-y-2 rounded-card border border-line bg-surface-muted p-3">
      {/* Polite: the write already succeeded, so it must not interrupt. */}
      <p role="status" className="flex items-start gap-2 text-sm text-ink">
        <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
        {recorded ? (
          <span>
            Stored. <MonoValue>{write.key}</MonoValue> was{" "}
            <MonoValue className="font-semibold">{display(write.previous)}</MonoValue> and the
            store now holds{" "}
            <MonoValue className="font-semibold">{display(write.field.value)}</MonoValue>, at
            configuration version <MonoValue>{write.config_version}</MonoValue>.
          </span>
        ) : (
          <span>
            Already the value. <MonoValue>{write.key}</MonoValue> was already{" "}
            <MonoValue className="font-semibold">{display(write.field.value)}</MonoValue>, so
            nothing was written, no audit entry was made, and no process was asked to
            re-read anything.
          </span>
        )}
      </p>
      {recorded && <AppliesNotice verdict={verdict} />}
      {recorded && !inForceHere && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="The process serving this screen has not picked it up yet"
        >
          <p className="mt-1">
            It still reports{" "}
            <MonoValue className="font-semibold">{display(field.value)}</MonoValue>. That is
            expected for a few seconds; if it persists, this process cannot reach the
            configuration store — check the banner at the top of this screen before assuming
            the change is in force anywhere.
          </p>
        </NoticeBox>
      )}
      <button type="button" onClick={onDismiss} className={SECONDARY_BUTTON_SM}>
        Dismiss
      </button>
    </div>
  );
}
