"use client";

/**
 * The kind-specific half of an action — what this kind needs that the others do not — and
 * the `config` it becomes on the wire.
 *
 * One flat draft of strings for every kind rather than seven state shapes: the form keeps
 * one object, each block below edits the keys it owns, and `buildConfig` is the one place a
 * draft turns into the server's shape (validated again there, which is the real rule).
 */

import { CalendarClock } from "lucide-react";

import type { FormValidation } from "@/components/formValidation";
import { FIELD, FIELD_HINT, FIELD_LABEL, ProblemNotice } from "@/components/ui";
import { useConnectionsStatus, useCredentials, type ActionTool } from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";

import { spreadsheetId, type DraftParam, type Kind, type Provider } from "./params";

export type KindDraft = Record<string, string>;

function text(existing: ActionTool | undefined, key: string, fallback = ""): string {
  const value = existing?.config[key];
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return fallback;
}

function list(existing: ActionTool | undefined, key: string): string {
  const value = existing?.config[key];
  return Array.isArray(value) ? value.filter((v) => typeof v === "string").join(", ") : "";
}

function message(existing: ActionTool | undefined, key: string, fallback = ""): string {
  const msg = existing?.config.message;
  if (msg && typeof msg === "object" && !Array.isArray(msg)) {
    const value = (msg as Record<string, unknown>)[key];
    if (typeof value === "string") return value;
    if (Array.isArray(value)) return value.join(", ");
  }
  return fallback;
}

/** The draft a form starts from: a stored action's config, or each kind's defaults. */
export function initialDraft(kind: Kind, existing?: ActionTool): KindDraft {
  return {
    method: text(existing, "method", "POST"),
    url: text(existing, "url"),
    template: text(existing, "template"),
    language: text(existing, "language", "en"),
    phone_number_id: text(existing, "phone_number_id"),
    operation: text(existing, "operation", kind === "sheets" ? "record" : "check"),
    calendar_id: text(existing, "calendar_id", "primary"),
    duration_min: text(existing, "duration_min", "30"),
    spreadsheet: text(existing, "spreadsheet_id"),
    worksheet: text(existing, "worksheet", "Sheet1"),
    match_header: text(existing, "match_header", "Phone"),
    return_headers: list(existing, "return_headers"),
    module: text(existing, "module", "Leads"),
    amount_mode: existing?.config.fixed_amount_inr ? "fixed" : "asked",
    fixed_amount_inr: text(existing, "fixed_amount_inr"),
    min_amount_inr: text(existing, "min_amount_inr", "1"),
    max_amount_inr: text(existing, "max_amount_inr"),
    pay_description: text(existing, "description"),
    expire_minutes: text(existing, "expire_minutes", "1440"),
    msg_provider: message(existing, "provider", "aisensy"),
    msg_credential_id: message(existing, "credential_id"),
    msg_template: message(existing, "template"),
    msg_language: message(existing, "language", "en"),
    msg_phone_number_id: message(existing, "phone_number_id"),
    msg_body_values: message(existing, "body_values", "link"),
  };
}

const splitList = (raw: string): string[] =>
  raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

/** Draft → the server's `config` for this kind. */
export function buildConfig(
  kind: Kind,
  provider: Provider,
  d: KindDraft,
  params: DraftParam[],
): Record<string, unknown> {
  const named = params.map((p) => p.name).filter(Boolean);
  if (kind === "custom_api") {
    const fields = named.map((n) => ({ key: n, param: n }));
    return {
      method: d.method === "GET" ? "GET" : "POST",
      url: d.url,
      body: d.method === "GET" ? [] : fields,
      query: d.method === "GET" ? fields : [],
    };
  }
  if (kind === "whatsapp") {
    const recipient = params.find((p) => p.source === "lead_var")?.name ?? named[0] ?? "recipient";
    return {
      recipient_param: recipient,
      template: d.template,
      language: provider === "aisensy" ? null : d.language || "en",
      phone_number_id: provider === "meta_cloud" ? d.phone_number_id : null,
      body_params: named.filter((n) => n !== recipient),
    };
  }
  if (kind === "calendar") {
    const start = named.find((n) => n.includes("start")) ?? named[0];
    const end = named.find((n) => n.includes("end")) ?? null;
    return {
      operation: d.operation === "book" ? "book" : "check",
      calendar_id: d.calendar_id || "primary",
      start_param: start,
      end_param: end,
      duration_min: Number(d.duration_min) || 30,
      summary_param: named.find((n) => n.includes("summary") || n.includes("reason")) ?? null,
    };
  }
  if (kind === "sheets") {
    const base = { spreadsheet_id: spreadsheetId(d.spreadsheet), worksheet: d.worksheet };
    return d.operation === "lookup"
      ? {
          ...base,
          operation: "lookup",
          match_header: d.match_header,
          return_headers: splitList(d.return_headers),
        }
      : { ...base, operation: "record", columns: named.map((n) => ({ header: n, param: n })) };
  }
  if (kind === "payment_link") {
    const amount = params.find((p) => p.source === "ai" && p.name.includes("amount"))?.name;
    return {
      ...(d.amount_mode === "fixed"
        ? { fixed_amount_inr: d.fixed_amount_inr }
        : { amount_param: amount ?? "amount" }),
      min_amount_inr: d.min_amount_inr || "1",
      max_amount_inr: d.max_amount_inr,
      description: d.pay_description,
      expire_minutes: Number(d.expire_minutes) || 1440,
      message: {
        provider: d.msg_provider,
        credential_id: d.msg_credential_id,
        template: d.msg_template,
        language: d.msg_provider === "aisensy" ? null : d.msg_language || "en",
        phone_number_id: d.msg_provider === "meta_cloud" ? d.msg_phone_number_id : null,
        body_values: splitList(d.msg_body_values),
      },
    };
  }
  if (kind === "crm") {
    return {
      module: provider === "hubspot" ? "contacts" : d.module === "Contacts" ? "Contacts" : "Leads",
      fields: params
        .filter((p) => p.source === "ai" && p.name)
        .map((p) => ({ crm_field: p.name, param: p.name })),
    };
  }
  // caller_lookup
  if (provider === "sheet") {
    return {
      spreadsheet_id: spreadsheetId(d.spreadsheet),
      worksheet: d.worksheet,
      match_header: d.match_header,
      return_headers: splitList(d.return_headers),
    };
  }
  if (provider === "api") return { url: d.url };
  return { module: d.module === "Contacts" ? "Contacts" : "Leads" };
}

function Field({
  label,
  value,
  onChange,
  hint,
  placeholder,
  inputMode,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  hint?: string;
  placeholder?: string;
  inputMode?: "decimal" | "numeric" | "url";
}) {
  return (
    <div className="flex-1 sm:min-w-[10rem]">
      <label className="block">
        <span className={FIELD_LABEL}>{label}</span>
        <input
          className={FIELD}
          value={value}
          inputMode={inputMode}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      </label>
      {hint ? <span className={FIELD_HINT}>{hint}</span> : null}
    </div>
  );
}

export function KindFields({
  kind,
  provider,
  draft,
  onChange,
  session,
  valid,
}: {
  kind: Kind;
  provider: Provider;
  draft: KindDraft;
  onChange: (next: KindDraft) => void;
  session: Session;
  valid: FormValidation;
}) {
  const status = useConnectionsStatus(session);
  const creds = useCredentials(session);
  const set = (key: string) => (value: string) => onChange({ ...draft, [key]: value });
  const shareWith = status.data?.sheets_share_with;

  const sheetFields = (
    <>
      <div className="flex flex-wrap gap-2">
        <Field
          label="Sheet address"
          value={draft.spreadsheet}
          onChange={set("spreadsheet")}
          placeholder="https://docs.google.com/spreadsheets/d/…"
          inputMode="url"
        />
        <Field label="Tab name" value={draft.worksheet} onChange={set("worksheet")} />
      </div>
      <p className={FIELD_HINT}>
        {shareWith
          ? `Share the sheet with ${shareWith} as an Editor so your agent can use it.`
          : "Google Sheets is not available on your account yet."}
      </p>
    </>
  );

  if (kind === "custom_api" || (kind === "caller_lookup" && provider === "api")) {
    return (
      <div className="flex flex-wrap gap-2">
        {kind === "custom_api" ? (
          <div className="w-28">
            <label className="block">
              <span className={FIELD_LABEL}>Method</span>
              <select className={FIELD} value={draft.method} onChange={(e) => set("method")(e.target.value)}>
                <option value="GET">GET</option>
                <option value="POST">POST</option>
              </select>
            </label>
          </div>
        ) : null}
        <div className="flex-1 sm:min-w-[12rem]">
          <label className="block">
            <span className={FIELD_LABEL}>Secure address (https)</span>
            <input
              {...valid.field("url", "Enter the https:// address to call.")}
              className={FIELD}
              value={draft.url}
              inputMode="url"
              onChange={(e) => set("url")(e.target.value)}
              placeholder="https://api.yourbusiness.in/orders"
              required
            />
          </label>
          {valid.error("url")}
          {kind === "caller_lookup" ? (
            <span className={FIELD_HINT}>
              We call it with the caller&rsquo;s number as <code>?phone=</code>. Return only
              what the agent needs, such as their name.
            </span>
          ) : (
            <span className={FIELD_HINT}>
              Must answer within a few seconds. Anything that looks like a phone number, email
              or card number in the answer is hidden from the agent.
            </span>
          )}
        </div>
      </div>
    );
  }

  if (kind === "whatsapp") {
    return (
      <div className="flex flex-wrap gap-2">
        <Field
          label={provider === "aisensy" ? "Campaign name" : "Template name"}
          value={draft.template}
          onChange={set("template")}
          hint="An approved template. Messages are always sent as a template."
        />
        {provider !== "aisensy" ? (
          <Field label="Template language" value={draft.language} onChange={set("language")} />
        ) : null}
        {provider === "meta_cloud" ? (
          <Field
            label="Phone number ID"
            value={draft.phone_number_id}
            onChange={set("phone_number_id")}
            hint="From WhatsApp Manager → API Setup."
          />
        ) : null}
      </div>
    );
  }

  if (kind === "calendar") {
    return (
      <div className="flex flex-wrap gap-2">
        <div className="flex-1 sm:min-w-[10rem]">
          <label className="block">
            <span className={FIELD_LABEL}>
              <CalendarClock className="mr-1 inline h-3.5 w-3.5" />
              What it does
            </span>
            <select className={FIELD} value={draft.operation} onChange={(e) => set("operation")(e.target.value)}>
              <option value="check">Find free times</option>
              <option value="book">Book a time</option>
            </select>
          </label>
        </div>
        <Field
          label="Appointment length (minutes)"
          value={draft.duration_min}
          onChange={set("duration_min")}
          inputMode="numeric"
        />
        <Field
          label="Calendar"
          value={draft.calendar_id}
          onChange={set("calendar_id")}
          hint="“primary” is your main calendar. Times are in India time."
        />
      </div>
    );
  }

  if (kind === "sheets") {
    return (
      <div className="space-y-2">
        <label className="block">
          <span className={FIELD_LABEL}>What it does</span>
          <select className={FIELD} value={draft.operation} onChange={(e) => set("operation")(e.target.value)}>
            <option value="record">Write the caller&rsquo;s answers into a row</option>
            <option value="lookup">Look the caller up by phone number</option>
          </select>
        </label>
        {sheetFields}
        {draft.operation === "lookup" ? (
          <div className="flex flex-wrap gap-2">
            <Field label="Phone number column" value={draft.match_header} onChange={set("match_header")} />
            <Field
              label="Columns the agent may read"
              value={draft.return_headers}
              onChange={set("return_headers")}
              hint="Column headings, separated by commas."
            />
          </div>
        ) : (
          <p className={FIELD_HINT}>
            Each value below becomes a column with the same heading. One row per call; later
            answers on the same call update that row.
          </p>
        )}
      </div>
    );
  }

  if (kind === "payment_link") {
    if (creds.error || !creds.data) {
      return (
        <ProblemNotice
          error={creds.error ?? new Error("Your connected accounts could not be loaded.")}
          onRetry={() => void creds.refetch()}
        />
      );
    }
    const whatsappCreds = creds.data.filter((c) => c.kind === draft.msg_provider);
    return (
      <div className="space-y-2">
        <label className="block">
          <span className={FIELD_LABEL}>Amount</span>
          <select className={FIELD} value={draft.amount_mode} onChange={(e) => set("amount_mode")(e.target.value)}>
            <option value="asked">The agent says how much (add a value called amount)</option>
            <option value="fixed">Always the same amount</option>
          </select>
        </label>
        <div className="flex flex-wrap gap-2">
          {draft.amount_mode === "fixed" ? (
            <Field label="Amount (₹)" value={draft.fixed_amount_inr} onChange={set("fixed_amount_inr")} inputMode="decimal" />
          ) : null}
          <Field label="Smallest (₹)" value={draft.min_amount_inr} onChange={set("min_amount_inr")} inputMode="decimal" />
          <Field label="Largest (₹)" value={draft.max_amount_inr} onChange={set("max_amount_inr")} inputMode="decimal" />
          <Field
            label="Link expires after (minutes)"
            value={draft.expire_minutes}
            onChange={set("expire_minutes")}
            inputMode="numeric"
          />
        </div>
        <Field
          label="What the payment is for"
          value={draft.pay_description}
          onChange={set("pay_description")}
          hint="Shown to the caller on the payment page."
        />
        <p className="pt-1 text-xs font-medium text-ink">The WhatsApp message that carries the link</p>
        <div className="flex flex-wrap gap-2">
          <div className="flex-1 sm:min-w-[10rem]">
            <label className="block">
              <span className={FIELD_LABEL}>Sent with</span>
              <select
                className={FIELD}
                value={draft.msg_provider}
                onChange={(e) => onChange({ ...draft, msg_provider: e.target.value, msg_credential_id: "" })}
              >
                <option value="aisensy">AiSensy</option>
                <option value="meta_cloud">WhatsApp Cloud API</option>
                <option value="interakt">Interakt</option>
              </select>
            </label>
          </div>
          <div className="flex-1 sm:min-w-[10rem]">
            <label className="block">
              <span className={FIELD_LABEL}>WhatsApp account</span>
              <select
                className={FIELD}
                value={draft.msg_credential_id}
                onChange={(e) => set("msg_credential_id")(e.target.value)}
              >
                <option value="">— choose —</option>
                {whatsappCreds.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label} (····{c.last_four})
                  </option>
                ))}
              </select>
            </label>
          </div>
          <Field label="Template" value={draft.msg_template} onChange={set("msg_template")} />
          {draft.msg_provider === "meta_cloud" ? (
            <Field label="Phone number ID" value={draft.msg_phone_number_id} onChange={set("msg_phone_number_id")} />
          ) : null}
        </div>
        <Field
          label="Template blanks, in order"
          value={draft.msg_body_values}
          onChange={set("msg_body_values")}
          hint="Any of link, amount, description, separated by commas — for example: amount, link."
        />
        <p className={FIELD_HINT}>
          Links are created on your own Razorpay account and paid to you. Not available during a
          free trial.
        </p>
      </div>
    );
  }

  if (kind === "crm") {
    return (
      <div className="space-y-2">
        {provider === "zoho" ? (
          <label className="block">
            <span className={FIELD_LABEL}>Save as</span>
            <select className={FIELD} value={draft.module} onChange={(e) => set("module")(e.target.value)}>
              <option value="Leads">A lead</option>
              <option value="Contacts">A contact</option>
            </select>
          </label>
        ) : null}
        <p className={FIELD_HINT}>
          The caller&rsquo;s number is added for you and finds an existing record. Name each value
          below after the field it fills —{" "}
          {provider === "zoho" ? "for example Last_Name or Email" : "for example firstname or email"}.
          Saved in the background, so the call carries on.
        </p>
      </div>
    );
  }

  // caller_lookup: zoho, hubspot or sheet
  if (provider === "sheet") {
    return (
      <div className="space-y-2">
        {sheetFields}
        <div className="flex flex-wrap gap-2">
          <Field label="Phone number column" value={draft.match_header} onChange={set("match_header")} />
          <Field
            label="Columns the agent may read"
            value={draft.return_headers}
            onChange={set("return_headers")}
            hint="Column headings, separated by commas — for example Name, Last visit."
          />
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {provider === "zoho" ? (
        <label className="block">
          <span className={FIELD_LABEL}>Look in</span>
          <select className={FIELD} value={draft.module} onChange={(e) => set("module")(e.target.value)}>
            <option value="Leads">Leads</option>
            <option value="Contacts">Contacts</option>
          </select>
        </label>
      ) : null}
      <p className={FIELD_HINT}>
        Found by the caller&rsquo;s number, so the agent can greet them by name. It never reads
        anyone else&rsquo;s record. On calls your agent places, it is looked up before the phone
        rings; on calls that come in, the agent looks it up straight after its greeting. People
        who have called before are already remembered by your agent&rsquo;s caller memory, with
        no wait at all.
      </p>
    </div>
  );
}
