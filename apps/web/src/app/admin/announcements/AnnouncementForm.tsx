"use client";

import { useEffect, useState } from "react";
import clsx from "clsx";

import { AnnouncementBar, platformAnnouncementProps } from "@/components/arc/announcement-bar";
import { Combobox } from "@/components/arc/combobox";
import { Field } from "@/components/arc/field";
import { RadioGroup } from "@/components/arc/radio-group";
import { todayIST } from "@/components/arc/ist-dates";
import { IstDateTimeField } from "@/components/admin/istDateTimeField";
import { FIELD, FIELD_LABEL, ProblemNotice } from "@/components/ui";
import { useTenants } from "@/lib/api/admin";

import {
  AUDIENCE_OPTIONS,
  MAX_LINK_LABEL_CHARS,
  MAX_MESSAGE_CHARS,
  TONE_OPTIONS,
  messageLength,
  normaliseMessage,
  type AnnouncementDraft,
  type Audience,
  type DraftErrors,
  type Tone,
} from "./announcementDraft";

/**
 * The composer's fields and its live preview. The preview is the client's own
 * `AnnouncementBar` fed through `platformAnnouncementProps`, the mapping the client shell
 * uses, so what is previewed is what is shown. It is `inert`: its link would otherwise take
 * the operator to a client page inside the admin console.
 */
export function AnnouncementForm({
  id,
  draft,
  onChange,
  errors,
  showErrors,
  failure,
  disabled,
  onSubmit,
}: {
  id: string;
  draft: AnnouncementDraft;
  onChange: (next: AnnouncementDraft) => void;
  errors: DraftErrors;
  /** Errors are said once the operator has tried to send, never per keystroke. */
  showErrors: boolean;
  failure: unknown;
  disabled: boolean;
  onSubmit: () => void;
}) {
  const set = <K extends keyof AnnouncementDraft>(key: K, value: AnnouncementDraft[K]) =>
    onChange({ ...draft, [key]: value });
  const shown = (key: keyof DraftErrors) => (showErrors ? (errors[key] ?? null) : null);
  const length = messageLength(draft.message);
  const over = length > MAX_MESSAGE_CHARS;
  const near = !over && length >= MAX_MESSAGE_CHARS - 20;

  return (
    <form
      id={id}
      noValidate
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <section aria-labelledby={`${id}-preview`} className="space-y-2">
        <h3 id={`${id}-preview`} className={FIELD_LABEL}>
          How clients will see it
        </h3>
        <div inert className="overflow-hidden rounded-md border border-line">
          {normaliseMessage(draft.message) ? (
            <AnnouncementBar
              {...platformAnnouncementProps({
                message: normaliseMessage(draft.message),
                tone: draft.tone,
                link_url: draft.linkUrl.trim() || null,
                link_label: draft.linkLabel.trim() || null,
              })}
              role="region"
              label="Preview of the announcement"
              onDismiss={() => undefined}
            />
          ) : (
            <p className="px-4 py-2.5 text-body text-ink-faint">Your message appears here as you type.</p>
          )}
        </div>
        <p className="text-meta text-ink-muted">
          Clients see it above their top bar on every page until it ends or they dismiss it. A
          phone shows the same strip, wrapped.
        </p>
      </section>

      <Field label="Message" error={shown("message")} hint="One or two plain sentences. No formatting.">
        {(control) => (
          <div>
            <textarea
              {...control}
              rows={3}
              value={draft.message}
              disabled={disabled}
              aria-describedby={clsx(control["aria-describedby"], `${id}-count`)}
              onChange={(event) => set("message", event.target.value)}
              className={clsx(FIELD, "resize-y")}
            />
            <p
              id={`${id}-count`}
              className={clsx(
                "mt-1 text-right text-meta tabular-nums",
                over ? "font-medium text-danger" : near ? "text-warn" : "text-ink-muted",
              )}
            >
              {over
                ? `${length - MAX_MESSAGE_CHARS} over the ${MAX_MESSAGE_CHARS}-character limit`
                : `${length} of ${MAX_MESSAGE_CHARS} characters`}
            </p>
          </div>
        )}
      </Field>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,14rem)]">
        <Field
          label="Link (optional)"
          hint="An https:// address, or a console page such as /billing."
          error={shown("linkUrl")}
        >
          {(control) => (
            <input
              {...control}
              type="text"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              value={draft.linkUrl}
              disabled={disabled}
              placeholder="/billing"
              onChange={(event) => set("linkUrl", event.target.value)}
              className={FIELD}
            />
          )}
        </Field>
        <Field label="Link label" hint={`Up to ${MAX_LINK_LABEL_CHARS} characters.`} error={shown("linkLabel")}>
          {(control) => (
            <input
              {...control}
              type="text"
              value={draft.linkLabel}
              disabled={disabled}
              placeholder="Learn more"
              maxLength={MAX_LINK_LABEL_CHARS + 10}
              onChange={(event) => set("linkLabel", event.target.value)}
              className={FIELD}
            />
          )}
        </Field>
      </div>

      <RadioGroup
        label="Tone"
        options={TONE_OPTIONS}
        value={draft.tone}
        disabled={disabled}
        onChange={(value) => set("tone", value as Tone)}
      />

      <div className="space-y-3">
        <RadioGroup
          label="Who sees it"
          options={AUDIENCE_OPTIONS}
          value={draft.audience}
          disabled={disabled}
          onChange={(value) => set("audience", value as Audience)}
        />
        {draft.audience === "tenant" ? (
          <TenantPicker
            value={draft.targetTenantId}
            name={draft.targetTenantName}
            error={shown("target")}
            disabled={disabled}
            onChange={(tenantId, name) => onChange({ ...draft, targetTenantId: tenantId, targetTenantName: name })}
          />
        ) : null}
      </div>

      <div className="grid gap-5">
        <IstDateTimeField
          label="Starts"
          hint="Leave empty to show it as soon as you publish."
          value={draft.startsAt}
          min={todayIST()}
          clearable
          disabled={disabled}
          error={shown("startsAt")}
          onChange={(value) => set("startsAt", value)}
        />
        <IstDateTimeField
          label="Ends"
          hint="Leave empty to keep it up until you end it."
          value={draft.endsAt}
          min={todayIST()}
          clearable
          defaultTime="18:00"
          disabled={disabled}
          error={shown("endsAt")}
          onChange={(value) => set("endsAt", value)}
        />
      </div>

      <ProblemNotice error={failure} />
    </form>
  );
}

/** One client, found by typing; the directory search is the server's. */
function TenantPicker({
  value,
  name,
  error,
  disabled,
  onChange,
}: {
  value: string | null;
  name: string | null;
  error: string | null;
  disabled: boolean;
  onChange: (tenantId: string | null, name: string | null) => void;
}) {
  const [typed, setTyped] = useState("");
  const [query, setQuery] = useState("");
  // One directory read per pause in typing, not per keystroke.
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(typed), 250);
    return () => window.clearTimeout(timer);
  }, [typed]);
  const tenants = useTenants({ q: query, sort: "name" });
  const rows = tenants.data?.rows;
  const options = (rows ?? []).map((row) => ({ value: row.id, label: row.name, hint: `/c/${row.slug}` }));
  // The chosen client stays an option while a search that does not match it is on screen,
  // so the box keeps showing who was picked.
  if (value && name && !options.some((option) => option.value === value)) {
    options.unshift({ value, label: name, hint: "" });
  }
  return (
    <Combobox
      label="Client"
      hint="Type part of the business name or its address."
      error={error ?? (tenants.error ? "Clients could not be searched. Try again in a moment." : null)}
      options={options}
      value={value}
      disabled={disabled}
      placeholder="Search clients"
      onQueryChange={setTyped}
      loading={tenants.isFetching}
      loadingText="Searching clients…"
      emptyText={(typed) => (typed ? `No client matches “${typed}”` : "No clients yet")}
      onChange={(tenantId) =>
        onChange(tenantId, options.find((option) => option.value === tenantId)?.label ?? null)
      }
    />
  );
}
