"use client";

import { useId, useState, type ReactNode } from "react";
import { Check, RefreshCw, Search } from "lucide-react";

import { CHOICE_CARD, CHOICE_OFF, CHOICE_ON } from "@/components/console/choiceCard";
import { SegmentedControl } from "@/components/interior/segmented-control";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
  formatINR,
  formatCallCap,
  formatPhone,
} from "@/components/ui";
import { useTenants } from "@/lib/api/admin";
import { useThinnestWorkspace, type ConfigField } from "@/lib/api/opsConfig";
import { useTrialNumber } from "@/lib/api/opsTrialNumber";

import {
  controlKind,
  draftOf,
  listOf,
  optionFor,
  optionText,
  valueOf,
  type ControlKind,
} from "./configControl";

/**
 * The input for ONE setting, chosen by the control the server derived for it: a switch is
 * On/Off, a short closed choice is side by side, a long one is a list, a number carries its
 * unit and range, and a value that names something that exists — a rented number, our
 * workspace, a client — is PICKED from a live read of that thing, never typed. When that
 * read fails the picker says so with a Retry; it never falls back to a text box, because a
 * typed number is exactly the value that must not be trusted.
 *
 * Built from the kit: `SegmentedControl` (interior), the choice card (`console/choiceCard`),
 * the `FIELD*` classes, `ProblemNotice`, `Skeleton` and `NoticeBox`.
 */
export interface ConfigInputProps {
  field: ConfigField;
  draft: string;
  onChange: (draft: string) => void;
  /** The id the text-like input carries, so the form's label and error can name it. */
  inputId: string;
  /** The ids of the hint and the error under the input. */
  describedBy: string | undefined;
  invalid: boolean;
  disabled?: boolean;
}

export function ConfigInput(props: ConfigInputProps) {
  const kind = controlKind(props.field);
  switch (kind) {
    case "switch":
      return <SwitchInput {...props} />;
    case "segmented":
    case "select":
      return <ChoiceInput {...props} kind={kind} />;
    case "multi_select":
      return <MultiChoiceInput {...props} />;
    case "entity_picker":
      return <EntityPicker {...props} />;
    default:
      return <TypedInput {...props} kind={kind} />;
  }
}

// --- choices ---------------------------------------------------------------------------

function SwitchInput({ field, draft, onChange }: ConfigInputProps) {
  return (
    <div>
      <p className={FIELD_LABEL}>New value</p>
      <SegmentedControl
        className="mt-1"
        label={field.label}
        value={draft}
        onValueChange={onChange}
        options={[
          { value: "true", label: "On" },
          { value: "false", label: "Off" },
        ]}
      />
    </div>
  );
}

interface Card {
  value: string;
  title: ReactNode;
  detail?: ReactNode;
}

/**
 * A choice whose options deserve a line each, as cards with a native radio (or checkbox)
 * inside: arrow keys, the group's name and the checked state all come from the browser.
 */
function ChoiceCards({
  legend,
  cards,
  selected,
  onToggle,
  multiple = false,
}: {
  legend: string;
  cards: Card[];
  selected: (value: string) => boolean;
  onToggle: (value: string) => void;
  multiple?: boolean;
}) {
  const name = useId();
  return (
    <fieldset className="min-w-0">
      <legend className={FIELD_LABEL}>{legend}</legend>
      <div className="mt-1 grid gap-2 sm:grid-cols-2">
        {cards.map((card) => {
          const on = selected(card.value);
          return (
            <label key={card.value || "unset"} className={`${CHOICE_CARD} ${on ? CHOICE_ON : CHOICE_OFF} min-w-0`}>
              <input
                type={multiple ? "checkbox" : "radio"}
                name={name}
                value={card.value}
                checked={on}
                onChange={() => onToggle(card.value)}
                className="sr-only"
              />
              <span className="flex items-start justify-between gap-2">
                <span className="min-w-0 break-words text-sm font-medium text-ink">{card.title}</span>
                {on && <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand" />}
              </span>
              {card.detail && (
                <span className="mt-0.5 block break-words text-xs text-ink-muted">{card.detail}</span>
              )}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function ChoiceInput({
  field,
  draft,
  onChange,
  inputId,
  describedBy,
  invalid,
  kind,
}: ConfigInputProps & { kind: "segmented" | "select" }) {
  const unset = field.nullable ? [{ value: "", title: "Not set" }] : [];
  // The value in force is always a choice, even if a deployment ever serves one outside
  // its options, so the control never shows a value other than the one running.
  const current = draftOf(field, field.value);
  const stray =
    current !== "" && !optionFor(field, current)
      ? [{ value: current, title: `${current} (in force now)` }]
      : [];

  if (kind === "segmented") {
    const hinted = field.options.some((option) => option.hint);
    if (!hinted) {
      return (
        <div>
          <p className={FIELD_LABEL}>New value</p>
          <SegmentedControl
            className="mt-1"
            label={field.label}
            value={draft}
            onValueChange={onChange}
            options={[
              ...stray.map((s) => ({ value: s.value, label: s.title })),
              ...unset.map((u) => ({ value: u.value, label: u.title })),
              ...field.options.map((option) => ({ value: option.value, label: option.label })),
            ]}
          />
        </div>
      );
    }
    return (
      <ChoiceCards
        legend="New value"
        selected={(value) => value === draft}
        onToggle={onChange}
        cards={[
          ...stray,
          ...field.options.map((option) => ({
            value: option.value,
            title: option.label,
            detail: option.hint,
          })),
          ...unset,
        ]}
      />
    );
  }

  const chosen = optionFor(field, draft);
  return (
    <div>
      <label htmlFor={inputId} className={FIELD_LABEL}>
        New value
      </label>
      <select
        id={inputId}
        value={draft}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        className={`${FIELD} mt-1`}
      >
        {[...stray, ...unset].map((choice) => (
          <option key={choice.value || "unset"} value={choice.value}>
            {choice.title}
          </option>
        ))}
        {field.options.map((option) => (
          <option key={option.value} value={option.value}>
            {optionText(field, option)}
          </option>
        ))}
      </select>
      {chosen?.hint && <span className={FIELD_HINT}>{chosen.hint}</span>}
    </div>
  );
}

function MultiChoiceInput({ field, draft, onChange }: ConfigInputProps) {
  const values = listOf(draft);
  const toggle = (value: string) =>
    onChange(
      (values.includes(value) ? values.filter((v) => v !== value) : [...values, value]).join(","),
    );
  return (
    <div className="space-y-1">
      <ChoiceCards
        legend="Choose any"
        multiple
        selected={(value) => values.includes(value)}
        onToggle={toggle}
        cards={field.options.map((option) => ({
          value: option.value,
          title: option.label,
          detail: option.hint,
        }))}
      />
      <span className={FIELD_HINT}>
        {values.length === 0 ? "None chosen." : `${formatCount(values.length)} chosen.`}
      </span>
    </div>
  );
}

// --- typed values ------------------------------------------------------------------------

function rangeText(field: ConfigField): string | null {
  const { minimum, maximum, unit } = field.control;
  const kind = controlKind(field);
  if (kind === "percent") return "From 0 to 100%.";
  const shown = (bound: string) =>
    kind === "money_inr" ? formatINR(bound) : formatCount(Number(bound));
  const tail = unit && kind !== "money_inr" ? ` ${unit}` : "";
  if (minimum !== null && maximum !== null) {
    const low = field.control.minimum_exclusive ? `more than ${shown(minimum)}` : shown(minimum);
    return `Between ${low} and ${shown(maximum)}${tail}.`;
  }
  if (minimum !== null) return `At least ${shown(minimum)}${tail}.`;
  if (maximum !== null) return `At most ${shown(maximum)}${tail}.`;
  return null;
}

/** "= 3 minutes" under a duration, so 180 seconds is read the way a person counts it. */
function durationEcho(field: ConfigField, draft: string): string | null {
  if (controlKind(field) !== "duration" || !/^\d+$/.test(draft.trim())) return null;
  const amount = Number(draft.trim());
  const seconds = field.control.unit === "milliseconds" ? amount / 1000 : amount;
  return seconds >= 1 ? `That is ${formatCallCap(Math.round(seconds))}.` : null;
}

const INPUT_TYPES: Partial<Record<ControlKind | "unknown", { type: string; inputMode?: "numeric" | "decimal" | "tel" | "email" | "url" }>> = {
  number: { type: "text", inputMode: "numeric" },
  duration: { type: "text", inputMode: "numeric" },
  // `text` for money, never `number`: a number input hands back a float (hard rule 7).
  money_inr: { type: "text", inputMode: "decimal" },
  percent: { type: "text", inputMode: "decimal" },
  phone_in: { type: "tel", inputMode: "tel" },
  phone: { type: "tel", inputMode: "tel" },
  email: { type: "email", inputMode: "email" },
  url: { type: "url", inputMode: "url" },
};

function TypedInput({
  field,
  draft,
  onChange,
  inputId,
  describedBy,
  invalid,
  kind,
}: ConfigInputProps & { kind: ControlKind | "unknown" }) {
  const shape = INPUT_TYPES[kind] ?? { type: "text" };
  const prefix = kind === "money_inr" ? "₹" : kind === "phone_in" ? "+91" : null;
  const suffix = kind === "percent" ? "%" : null;
  const range = rangeText(field);
  const echo = durationEcho(field, draft);
  const unit = field.control.unit && kind !== "money_inr" && kind !== "percent" ? field.control.unit : null;
  const lines = [
    kind === "money_inr" && field.control.unit ? `Rupees ${field.control.unit}.` : null,
    unit && !range ? `In ${unit}.` : null,
    range,
    echo,
    field.control.help,
  ].filter((line): line is string => Boolean(line));
  const mono = kind === "text" || kind === "url" || kind === "unknown";
  return (
    <div>
      <label htmlFor={inputId} className={FIELD_LABEL}>
        New value{unit ? ` (${unit})` : ""}
      </label>
      <div className="relative">
        {prefix && (
          <span
            aria-hidden
            className="pointer-events-none absolute left-3 top-[calc(50%+2px)] -translate-y-1/2 text-sm text-ink-muted"
          >
            {prefix}
          </span>
        )}
        <input
          id={inputId}
          type={shape.type}
          inputMode={shape.inputMode}
          value={draft}
          onChange={(event) => onChange(event.target.value)}
          placeholder={field.control.placeholder ?? undefined}
          maxLength={field.control.max_length ?? undefined}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          className={`${FIELD} ${mono ? "font-mono" : "tabular-nums"} ${
            prefix === "+91" ? "pl-12" : prefix ? "pl-7" : ""
          } ${suffix ? "pr-8" : ""}`}
        />
        {suffix && (
          <span
            aria-hidden
            className="pointer-events-none absolute right-3 top-[calc(50%+2px)] -translate-y-1/2 text-sm text-ink-muted"
          >
            {suffix}
          </span>
        )}
      </div>
      {kind === "unknown" && (
        <span className={FIELD_HINT}>
          This console does not know how to draw this kind of setting yet, so it is shown as
          text. The platform still checks what you enter.
        </span>
      )}
      {lines.length > 0 && <span className={FIELD_HINT}>{lines.join(" ")}</span>}
    </div>
  );
}

// --- pickers fed from a live read --------------------------------------------------------

function EntityPicker(props: ConfigInputProps) {
  switch (props.field.control.source) {
    case "trial_numbers":
      return <TrialNumberPicker {...props} />;
    case "thinnest_workspace":
      return <WorkspacePicker {...props} />;
    case "tenants":
      return <TenantPicker {...props} />;
    default:
      return (
        <NoticeBox tone="warn" title="This console cannot list these choices yet">
          <p className="mt-1">
            The platform asks for a choice from a list this build does not know how to read.
            Reload once the console is updated.
          </p>
        </NoticeBox>
      );
  }
}

function RefreshButton({ onClick, busy }: { onClick: () => void; busy: boolean }) {
  return (
    <button type="button" onClick={onClick} disabled={busy} className={SECONDARY_BUTTON_SM}>
      <RefreshCw aria-hidden className={`h-3.5 w-3.5 ${busy ? "motion-safe:animate-spin" : ""}`} />
      {busy ? "Refreshing…" : "Refresh"}
    </button>
  );
}

/** Who the number reaches today, in words. */
function numberDetail(candidate: {
  rented: boolean;
  answered: boolean;
  label: string | null;
  answering_agent: string | null;
  calling_agent: string | null;
}): string {
  const parts = [candidate.label, candidate.rented ? "Rented from ThinnestAI" : "Brought from a carrier"];
  if (candidate.answering_agent) parts.push(`answered by ${candidate.answering_agent}`);
  else if (candidate.answered) parts.push("answered by an agent outside Calevate");
  else parts.push("nobody answers it");
  if (candidate.calling_agent) parts.push(`lent to ${candidate.calling_agent} for calling out`);
  return parts.filter(Boolean).join(" · ");
}

function TrialNumberPicker({ field, draft, onChange }: ConfigInputProps) {
  const numbers = useTrialNumber();
  if (numbers.error) {
    return (
      <div className="space-y-2">
        <p className={FIELD_LABEL}>New value</p>
        <ProblemNotice error={numbers.error} onRetry={() => void numbers.refetch()} />
      </div>
    );
  }
  if (numbers.isLoading || numbers.data === undefined) {
    return <Skeleton rows={2} label="Reading the numbers our ThinnestAI workspace holds…" />;
  }
  const data = numbers.data;
  const current = draftOf(field, field.value);
  const offered = new Set(data.candidates.map((candidate) => candidate.e164));
  const cards: Card[] = data.candidates.map((candidate) => ({
    value: candidate.e164,
    title: <span className="font-mono">{formatPhone(candidate.e164)}</span>,
    detail: numberDetail(candidate),
  }));
  if (current !== "" && !offered.has(current)) {
    cards.unshift({
      value: current,
      title: <span className="font-mono">{formatPhone(current)}</span>,
      detail: "In force now, but no longer a free number in our workspace.",
    });
  }
  if (field.nullable) {
    cards.push({ value: "", title: "No trial number", detail: "Trial test calls are switched off." });
  }
  return (
    <div className="space-y-2">
      {!data.engine_uses_it && (
        <NoticeBox tone="neutral" title="Not used by the current engine">
          <p className="mt-1">
            A shared trial number is used only when calls run on ThinnestAI, so there are no
            numbers to choose from.
          </p>
        </NoticeBox>
      )}
      {data.engine_uses_it && data.candidates.length === 0 && (
        <NoticeBox tone="warn" title="No free number in our ThinnestAI workspace">
          <p className="mt-1">
            Rent one in ThinnestAI&apos;s console under Phone Numbers, leave it unassigned,
            then refresh this list.
          </p>
        </NoticeBox>
      )}
      <ChoiceCards
        legend="Choose the number trial calls ring from"
        selected={(value) => value === draft}
        onToggle={onChange}
        cards={cards}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={FIELD_HINT}>
          Read live from ThinnestAI. Numbers recorded against a client are left out.
        </span>
        <RefreshButton onClick={() => void numbers.refetch()} busy={numbers.isFetching} />
      </div>
    </div>
  );
}

function WorkspacePicker({ field, draft, onChange }: ConfigInputProps) {
  const workspace = useThinnestWorkspace(true);
  if (workspace.error) {
    return (
      <div className="space-y-2">
        <p className={FIELD_LABEL}>New value</p>
        <ProblemNotice error={workspace.error} onRetry={() => void workspace.refetch()} />
      </div>
    );
  }
  if (workspace.isLoading || workspace.data === undefined) {
    return <Skeleton rows={1} label="Reading our workspace from ThinnestAI…" />;
  }
  const read = workspace.data;
  const current = draftOf(field, field.value);
  const cards: Card[] = [
    {
      value: read.workspace_id,
      title: `Use this workspace: ${read.name ?? "our ThinnestAI workspace"}`,
      detail: <span className="font-mono">{read.workspace_id}</span>,
    },
  ];
  if (current !== "" && current !== read.workspace_id) {
    cards.push({
      value: current,
      title: "The workspace set now",
      detail: (
        <>
          <span className="font-mono">{current}</span> — not the workspace our ThinnestAI key
          belongs to.
        </>
      ),
    });
  }
  if (field.nullable) {
    cards.push({ value: "", title: "Not set", detail: "Read from ThinnestAI when it is needed." });
  }
  return (
    <div className="space-y-2">
      <ChoiceCards
        legend="Choose our developer workspace"
        selected={(value) => value === draft}
        onToggle={onChange}
        cards={cards}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={FIELD_HINT}>Read live from ThinnestAI with our API key.</span>
        <RefreshButton onClick={() => void workspace.refetch()} busy={workspace.isFetching} />
      </div>
    </div>
  );
}

function TenantPicker({ field, draft, onChange }: ConfigInputProps) {
  const [query, setQuery] = useState("");
  const tenants = useTenants({ q: query, sort: "name" });
  const searchId = useId();
  const chosen = listOf(draft);
  // Names learned from any page read so far, so a chosen client keeps its name after the
  // search moves on. A chosen id never seen in a page is shown as the id itself.
  const [names, setNames] = useState<Record<string, string>>({});
  // Only rows that ARRIVED: a paused or failed read names no clients (§52).
  const rows = tenants.data ? tenants.data.rows : [];
  const unseen = rows.filter((row) => names[row.id] !== row.name);
  if (unseen.length > 0) {
    setNames((known) => ({ ...known, ...Object.fromEntries(unseen.map((row) => [row.id, row.name])) }));
  }
  const toggle = (id: string) =>
    onChange((chosen.includes(id) ? chosen.filter((v) => v !== id) : [...chosen, id]).join(","));

  return (
    <div className="space-y-2">
      <label htmlFor={searchId} className={FIELD_LABEL}>
        Find a client
      </label>
      <div className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
        />
        <input
          id={searchId}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Business name"
          autoComplete="off"
          className={`${FIELD} pl-9`}
        />
      </div>
      {tenants.error ? (
        <ProblemNotice error={tenants.error} onRetry={() => void tenants.refetch()} />
      ) : tenants.isLoading ? (
        <Skeleton rows={2} label="Reading the client list…" />
      ) : (
        <ChoiceCards
          legend={`Clients in the comparison (${formatCount(chosen.length)} chosen)`}
          multiple
          selected={(value) => chosen.includes(value)}
          onToggle={toggle}
          cards={[
            ...chosen
              .filter((id) => !rows.some((row) => row.id === id))
              .map((id) => ({ value: id, title: names[id] ?? id, detail: "Chosen" })),
            ...rows.map((row) => ({ value: row.id, title: row.name, detail: row.slug })),
          ]}
        />
      )}
      {field.control.multiple && valueOf(field, draft) === null && (
        <span className={FIELD_HINT}>No client is compared.</span>
      )}
    </div>
  );
}
