"use client";

import { useState, type ReactNode } from "react";
import { CheckCircle2, Lock, TriangleAlert } from "lucide-react";

import { MonoValue, TimingBadge, ToneBadge } from "@/app/admin/ops/opsLanguage";
import { Drawer } from "@/components/console/drawer";
import { CopyButton } from "@/components/interior/copy-button";
import { Disclosure, NoticeBox, SECONDARY_BUTTON_SM } from "@/components/ui";
import type { ConfigField, ConfigWrite } from "@/lib/api/opsConfig";

import { ConfigForm } from "./ConfigForm";
import { appliesCopy, displayValue, lockedReason, settingState } from "./configControl";
import { etagOf } from "./configField";

type Access = { allowed: boolean; reason: string | null };

/**
 * One setting: its name, one plain sentence, the value as a person reads it, whether it is
 * the default or who changed it, and when a change applies — with a Change button that
 * opens the form in a drawer (a bottom sheet on a phone).
 *
 * The raw key, the environment variable and the stored value are in a closed "Technical
 * details" disclosure: they are what an engineer reads, never what the operator decides on.
 * The form is closed until asked for, because sixty open inputs is a screen where a stray
 * keystroke edits the platform.
 */
export function ConfigRow({ field, access }: { field: ConfigField; access: Access }) {
  const [open, setOpen] = useState(false);
  const [receipt, setReceipt] = useState<ConfigWrite | null>(null);
  const tag = etagOf(field);
  const state = settingState(field);
  const applies = appliesCopy(field);

  return (
    <div className="py-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
        <div className="min-w-0 sm:flex-1">
          <p className="text-[14px] font-medium text-ink">{field.label}</p>
          <p className="mt-0.5 text-[13px] text-ink-muted">{field.description}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <ToneBadge
              tone={state.tone === "changed" ? "ok" : "neutral"}
              icon={state.tone === "locked" ? <Lock aria-hidden className="h-3 w-3" /> : undefined}
            >
              {state.label}
            </ToneBadge>
            {field.editable && <TimingBadge applies={field.applies} />}
          </div>
          {field.source === "db" && field.note && (
            <p className="mt-1.5 break-words text-xs text-ink-muted">
              Reason: &ldquo;{field.note}&rdquo;
            </p>
          )}
        </div>
        <div className="flex min-w-0 items-center justify-between gap-3 sm:max-w-[45%] sm:flex-col sm:items-end sm:justify-start">
          <p className="min-w-0 break-words text-[15px] font-semibold text-ink [overflow-wrap:anywhere] sm:text-right">
            {displayValue(field, field.value)}
          </p>
          <RowAction
            field={field}
            tag={tag}
            access={access}
            onOpen={() => {
              // A receipt for the last write above the next form is how two changes
              // become one remembered change, so opening the form retires it.
              setReceipt(null);
              setOpen(true);
            }}
          />
        </div>
      </div>

      {!field.editable && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-ink-muted">
          <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{lockedReason(field)}</span>
        </p>
      )}
      {field.editable && tag === null && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-ink-muted">
          <Lock aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            The platform did not send a version tag for this setting, and it refuses a change
            that does not name the value it replaces. The platform and this screen are on
            different versions; reload once both are updated.
          </span>
        </p>
      )}

      {!open && receipt && (
        <WriteReceipt write={receipt} field={field} onDismiss={() => setReceipt(null)} />
      )}

      <div className="mt-1">
        <Disclosure variant="inline" headingLevel={4} title="Technical details">
          <TechnicalDetails field={field} appliesSentence={applies.sentence} />
        </Disclosure>
      </div>

      {/* Re-read on EVERY render: a refetch that turns the key env-pinned takes the form
          away, because the write it would send is one the API now refuses. */}
      <Drawer
        open={open && field.editable && tag !== null}
        onClose={() => setOpen(false)}
        title={`Change ${field.label}`}
        description={field.description}
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
    </div>
  );
}

function RowAction({
  field,
  tag,
  access,
  onOpen,
}: {
  field: ConfigField;
  tag: string | null;
  access: Access;
  onOpen: () => void;
}) {
  if (!field.editable || tag === null) return null;
  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={!access.allowed}
      title={access.reason ?? undefined}
      aria-label={`Change ${field.label}`}
      className={`${SECONDARY_BUTTON_SM} shrink-0`}
    >
      Change
    </button>
  );
}

function Detail({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[10rem_1fr] sm:gap-3">
      <dt className="text-xs font-medium text-ink-faint">{term}</dt>
      <dd className="min-w-0 break-words text-xs text-ink-muted [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

function TechnicalDetails({ field, appliesSentence }: { field: ConfigField; appliesSentence: string }) {
  const raw = field.value === null ? "null" : JSON.stringify(field.value);
  return (
    <dl className="space-y-1.5">
      <Detail term="Setting key">
        <span className="inline-flex flex-wrap items-center gap-1.5">
          <MonoValue>{field.key}</MonoValue>
          <CopyButton value={field.key} label={`Copy the key ${field.key}`} />
        </span>
      </Detail>
      <Detail term="Environment variable">
        <MonoValue>{field.env_var}</MonoValue>
      </Detail>
      <Detail term="Stored value">
        <MonoValue>{raw}</MonoValue>
      </Detail>
      <Detail term="Default">
        {field.has_default ? displayValue(field, field.default) : "None: it must be set on the server."}
      </Detail>
      {field.editable && <Detail term="When a change applies">{appliesSentence}</Detail>}
      {field.engine_scope && <Detail term="Used by">{field.engine_scope}</Detail>}
      {field.control.risk === "high" && field.control.risk_reason && (
        <Detail term="Why it needs care">{field.control.risk_reason}</Detail>
      )}
    </dl>
  );
}

/**
 * What the SERVER stored, after it stored it — every value from `ConfigWriteOut`, never the
 * draft. The write went to the STORE; the row above is what the process serving this
 * screen has in force, and on a stale snapshot those disagree for a few seconds.
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
  const applies = appliesCopy(write.field);
  const inForceHere = JSON.stringify(field.value) === JSON.stringify(write.field.value);
  // `recorded === false`: the submitted value was ALREADY stored, so nothing moved and no
  // audit entry exists.
  const recorded = write.recorded !== false;

  return (
    <div className="mt-3 space-y-2 rounded-card border border-line bg-surface-muted p-3">
      {/* Polite: the write already succeeded, so it must not interrupt. */}
      <p role="status" className="flex items-start gap-2 text-sm text-ink">
        <CheckCircle2 aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
        {recorded ? (
          <span className="min-w-0 break-words">
            Saved. {field.label} changed from{" "}
            <span className="font-semibold">{displayValue(write.field, write.previous)}</span> to{" "}
            <span className="font-semibold">{displayValue(write.field, write.field.value)}</span>.{" "}
            {applies.applies === "live" ? "It applies within a few seconds." : applies.label + "."}
          </span>
        ) : (
          <span className="min-w-0 break-words">
            No change: {field.label} was already{" "}
            <span className="font-semibold">{displayValue(write.field, write.field.value)}</span>,
            so nothing was saved or recorded.
          </span>
        )}
      </p>
      {recorded && applies.applies !== "live" && (
        <p className="text-xs text-ink-muted">{applies.sentence}</p>
      )}
      {recorded && !inForceHere && (
        <NoticeBox
          tone="warn"
          icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
          title="This screen has not picked up the change yet"
        >
          <p className="mt-1">
            It still shows {displayValue(field, field.value)}. That is normal for a few seconds;
            if it lasts, check the notice at the top of this screen about reaching the
            configuration store.
          </p>
        </NoticeBox>
      )}
      <button type="button" onClick={onDismiss} className={SECONDARY_BUTTON_SM}>
        Dismiss
      </button>
    </div>
  );
}
