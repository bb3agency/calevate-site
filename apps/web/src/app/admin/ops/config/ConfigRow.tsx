"use client";

import { Fragment, useState, type ReactNode } from "react";
import { CheckCircle2, Lock, TriangleAlert } from "lucide-react";

import { MonoValue } from "@/app/admin/ops/opsLanguage";
import { WriteFailure } from "@/app/admin/writeFailure";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Drawer } from "@/components/console/drawer";
import { TEXT_ACTION } from "@/components/console/section";
import { CopyButton } from "@/components/interior/copy-button";
import { TypedConfirmation, confirmationMatches } from "@/components/typedConfirmation";
import { Disclosure, NoticeBox } from "@/components/ui";
import { useRevertConfig, type ConfigField, type ConfigValue, type ConfigWrite } from "@/lib/api/opsConfig";

import { ConfigForm } from "./ConfigForm";
import {
  appliesCopy,
  confirmPhrase,
  displayValue,
  engineOnlyLabel,
  lockedReason,
  settingState,
} from "./configControl";
import { etagOf } from "./configField";

type Access = { allowed: boolean; reason: string | null };

/**
 * One setting as one label–value row: the name and the value in force on one line, with
 * "Change" (and "Reset to default" when the value is not the default) as text actions
 * after the value. Under it, one meta line says where the value came from. When a change
 * takes effect is a fixed property of the setting, not a state, so it lives in Details and
 * in the change drawer; on the row it read as a pending task that never cleared.
 *
 * The key, the environment variable and the full timing explanation sit in a closed
 * "Details" disclosure: an engineer reads them, the operator decides on the row. The form
 * is in a drawer and closed until asked for, because sixty open inputs is a screen where a
 * stray keystroke edits the platform.
 *
 * A setting the current engine does not read is drawn quieter, with its meta line naming
 * the engine it is for. It stays editable: an operator prepares an engine switch here.
 */
export function ConfigRow({ field, access }: { field: ConfigField; access: Access }) {
  const recessive = !field.used_by_current_engine;
  const [open, setOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [receipt, setReceipt] = useState<ConfigWrite | null>(null);
  const tag = etagOf(field);
  const notSet = field.value === null;

  return (
    <div className="py-3.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <p
          className={`min-w-0 flex-1 basis-48 text-body font-medium [overflow-wrap:anywhere] ${recessive ? "text-ink-muted" : "text-ink"}`}
        >
          {field.label}
        </p>
        <div className="ml-auto flex min-w-0 max-w-full flex-wrap items-baseline justify-end gap-x-4 gap-y-1 sm:max-w-[60%]">
          <p
            className={`min-w-0 text-right text-body tabular-nums [overflow-wrap:anywhere] ${notSet || recessive ? "text-ink-muted" : "text-ink"}`}
          >
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
            onReset={() => {
              setReceipt(null);
              setResetting(true);
            }}
          />
        </div>
      </div>

      <p className="mt-0.5 max-w-prose text-meta text-ink-muted [text-wrap:pretty]">{field.description}</p>
      <MetaLine field={field} recessive={recessive} />
      {field.source === "db" && field.note && (
        <p className="mt-0.5 truncate text-meta text-ink-muted" title={field.note}>
          &ldquo;{field.note}&rdquo;
        </p>
      )}

      {!field.editable && (
        <p className="mt-1 max-w-prose text-meta text-ink-muted">{lockedReason(field)}</p>
      )}
      {field.editable && tag === null && (
        <p className="mt-1 max-w-prose text-meta text-ink-muted">
          The platform did not send a version tag for this setting, and it refuses a change
          that does not name the value it replaces. The platform and this screen are on
          different versions; reload once both are updated.
        </p>
      )}

      {!open && receipt && (
        <WriteReceipt write={receipt} field={field} onDismiss={() => setReceipt(null)} />
      )}

      {resetting && tag !== null && (
        <ResetDialog
          field={field}
          basis={tag}
          onClose={() => setResetting(false)}
          onWritten={(write) => {
            setReceipt(write);
            setResetting(false);
          }}
        />
      )}

      <Disclosure
        variant="inline"
        headingLevel={4}
        title="Details"
        className="mt-0.5 border-b-0! [&>summary]:w-fit [&>summary]:py-1 [&>summary_h4]:text-meta [&>summary_h4]:text-ink-muted [&>div]:pb-1"
      >
        <TechnicalDetails field={field} recessive={recessive} />
      </Disclosure>

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

/**
 * Where the value came from, as one line of plain text rather than a row of chips.
 */
function MetaLine({ field, recessive }: { field: ConfigField; recessive: boolean }) {
  const state = settingState(field);
  const parts: ReactNode[] = [];
  const only = recessive ? engineOnlyLabel(field.engine_scope) : null;
  if (only) parts.push(<span key="only">{only}</span>);
  parts.push(
    <span key="state" className="inline-flex items-center gap-1">
      {state.tone === "locked" && <Lock aria-hidden className="h-3 w-3 shrink-0" />}
      {state.label}
    </span>,
  );
  return (
    <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-meta text-ink-muted">
      {/* The separator travels with the part after it, so a wrapped line never ends on a dot. */}
      {parts.map((part, index) =>
        index === 0 ? (
          <Fragment key={index}>{part}</Fragment>
        ) : (
          <span key={index} className="inline-flex items-center gap-1.5">
            <span aria-hidden className="text-ink-faint">
              ·
            </span>
            {part}
          </span>
        ),
      )}
    </p>
  );
}

/** Whether a stored value can be taken away: there is a row, and a default to fall back to. */
export function canReset(field: ConfigField): boolean {
  return field.editable && field.source === "db" && field.has_default;
}

/** "Clear" when the default is no value at all, otherwise "Reset to default". */
export function resetLabel(field: ConfigField): string {
  return field.default === null ? "Clear" : "Reset to default";
}

function RowAction({
  field,
  tag,
  access,
  onOpen,
  onReset,
}: {
  field: ConfigField;
  tag: string | null;
  access: Access;
  onOpen: () => void;
  onReset: () => void;
}) {
  if (!field.editable || tag === null) return null;
  return (
    <div className="flex shrink-0 items-baseline gap-4">
      {canReset(field) && (
        <button
          type="button"
          onClick={onReset}
          disabled={!access.allowed}
          title={access.reason ?? undefined}
          aria-label={`${resetLabel(field)}: ${field.label}`}
          className={`${TEXT_ACTION} text-ink-muted! hover:text-ink!`}
        >
          {resetLabel(field)}
        </button>
      )}
      <button
        type="button"
        onClick={onOpen}
        disabled={!access.allowed}
        title={access.reason ?? undefined}
        aria-label={`Change ${field.label}`}
        className={TEXT_ACTION}
      >
        Change
      </button>
    </div>
  );
}

/**
 * Removing the stored value so the default applies again. Conditional on the version tag
 * the row was read at, like every write here, and a high-risk setting asks for the value
 * it returns to, as the form does.
 */
function ResetDialog({
  field,
  basis,
  onClose,
  onWritten,
}: {
  field: ConfigField;
  basis: string;
  onClose: () => void;
  onWritten: (write: ConfigWrite) => void;
}) {
  const revert = useRevertConfig();
  const [confirm, setConfirm] = useState("");
  const high = field.control.risk === "high";
  const phrase = confirmPhrase(field, field.default);
  const ready = !high || confirmationMatches(confirm, phrase);
  const applies = appliesCopy(field);
  const label = resetLabel(field);

  return (
    <ConfirmDialog
      title={field.default === null ? `Clear ${field.label}?` : `Reset ${field.label} to its default?`}
      confirmLabel={label}
      pendingLabel="Saving…"
      pending={revert.isPending}
      confirmDisabled={!ready}
      error={null}
      onCancel={onClose}
      onConfirm={() => {
        if (!ready || revert.isPending) return;
        revert.mutate({ key: field.key, ifMatch: basis }, { onSuccess: onWritten });
      }}
    >
      <p className="text-ink">
        {displayValue(field, field.value)} is removed and{" "}
        <span className="font-semibold">{displayValue(field, field.default)}</span> applies.{" "}
        {applies.sentence}
      </p>
      {high && field.control.risk_reason && <p>{field.control.risk_reason}</p>}
      <p>The audit log records this as a return to the default.</p>
      {revert.error && <WriteFailure error={revert.error} actionLabel={label} />}
      {high && (
        <TypedConfirmation
          id={`reset-config-${field.key}`}
          phrase={phrase}
          value={confirm}
          onChange={setConfirm}
        />
      )}
    </ConfirmDialog>
  );
}


/** A value in the form the store holds it: `0.3` for 30%, `thinnest` for ThinnestAI. */
function storedForm(value: ConfigValue): string {
  return typeof value === "string" ? value : String(value);
}

/**
 * What an engineer needs and the operator does not decide on: the key and the variable
 * (each copyable), the stored form when it reads differently from the row, the default
 * when the row is not on it, and the timing explanation in full, once.
 */
function TechnicalDetails({ field, recessive }: { field: ConfigField; recessive: boolean }) {
  const stored = field.value === null ? null : storedForm(field.value);
  const showStored = stored !== null && stored !== displayValue(field, field.value);
  const offDefault = field.source !== "default" || !field.has_default;
  const risky = field.control.risk === "high" && field.control.risk_reason;
  return (
    <div className="space-y-1 text-meta text-ink-muted">
      <p className="flex flex-wrap items-center gap-x-4 gap-y-0.5">
        <CodeWithCopy term="Setting key" value={field.key} />
        <CodeWithCopy term="Environment variable" value={field.env_var} />
      </p>
      {showStored && (
        <p className="[overflow-wrap:anywhere]">
          Stored as <MonoValue className="text-ink">{stored}</MonoValue>
        </p>
      )}
      {offDefault && (
        <p>
          {field.has_default
            ? <>Default: {displayValue(field, field.default)}</>
            : "No default: it must be set on the server."}
        </p>
      )}
      {/* The row truncates the reason; a phone has no hover to read the rest. */}
      {field.source === "db" && field.note && (
        <p className="max-w-prose break-words">Reason given: &ldquo;{field.note}&rdquo;</p>
      )}
      {field.editable && <p className="max-w-prose">{appliesCopy(field).sentence}</p>}
      {field.engine_scope && !recessive && <p>{field.engine_scope}</p>}
      {risky && (
        <p className="max-w-prose">
          <span className="font-medium text-ink">Needs care: </span>
          {field.control.risk_reason}
        </p>
      )}
    </div>
  );
}

function CodeWithCopy({ term, value }: { term: string; value: string }) {
  return (
    <span className="inline-flex min-w-0 max-w-full items-center gap-0.5">
      <span className="sr-only">{term}: </span>
      <MonoValue className="min-w-0 text-ink [overflow-wrap:anywhere]">{value}</MonoValue>
      <CopyButton value={value} label={`Copy the ${term.toLowerCase()} ${value}`} />
    </span>
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
    <div className="mt-2 space-y-2 border-l-2 border-brand/40 py-0.5 pl-3">
      {/* Polite: the write already succeeded, so it must not interrupt. */}
      <p role="status" className="flex items-start gap-2 text-body text-ink">
        <CheckCircle2 aria-hidden className="mt-1 h-4 w-4 shrink-0 text-brand" />
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
        <p className="text-meta text-ink-muted">{applies.sentence}</p>
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
      <button type="button" onClick={onDismiss} className={`${TEXT_ACTION} text-meta!`}>
        Dismiss
      </button>
    </div>
  );
}
