"use client";

/**
 * ADDING ONE ACTION — the kind-specific form, and the wire body it builds.
 *
 * Split out of `Actions.tsx` (UX-DOCTRINE §6). The form is one component rather than three
 * because the SHARED half (name, when the AI should use it, credential, parameters,
 * trigger, filler line) is most of it and the kind-specific half is three short blocks —
 * three near-identical forms would be three places to fix the next shared field.
 */

import { useState } from "react";
import { CalendarClock } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
} from "@/components/ui";
import {
  ACTION_KIND_LABELS,
  useCalendarConnect,
  useCreateAction,
  useCredentials,
  type ActionToolInput,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";

import { ParamEditor } from "./ParamEditor";
import { toParam, type DraftParam, type Kind, type Provider } from "./params";

export function ActionForm({
  kind,
  agentId,
  session,
  onDone,
}: {
  kind: Kind;
  agentId: string;
  session: Session;
  onDone: () => void;
}) {
  const create = useCreateAction(session, agentId);
  const creds = useCredentials(session);
  const calendarConnect = useCalendarConnect(session);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [trigger, setTrigger] = useState<"during_call" | "after_call">("during_call");
  const [preCall, setPreCall] = useState("");
  const [credentialId, setCredentialId] = useState("");
  const [provider, setProvider] = useState<Provider>(kind === "calendar" ? "google" : "aisensy");
  const [params, setParams] = useState<DraftParam[]>([]);

  // custom_api
  const [method, setMethod] = useState<"GET" | "POST">("POST");
  const [url, setUrl] = useState("");
  // whatsapp
  const [template, setTemplate] = useState("");
  const [language, setLanguage] = useState("en");
  const [phoneNumberId, setPhoneNumberId] = useState("");
  // calendar
  const [operation, setOperation] = useState<"book" | "check">("check");
  const [calendarId, setCalendarId] = useState("primary");

  function buildBody(): ActionToolInput {
    const base = {
      name,
      description,
      trigger,
      pre_call_message: preCall || null,
      credential_id: credentialId || null,
      params: params.map(toParam),
    };
    if (kind === "custom_api") {
      return {
        ...base,
        kind: "custom_api",
        provider: null,
        config: {
          method,
          url,
          // Every AI/lead param is sent in the body for POST, else as a query param.
          body: method === "POST" ? params.map((p) => ({ key: p.name, param: p.name })) : [],
          query: method === "GET" ? params.map((p) => ({ key: p.name, param: p.name })) : [],
        },
      };
    }
    if (kind === "whatsapp") {
      const recipient =
        params.find((p) => p.source === "lead_var")?.name ?? params[0]?.name ?? "recipient";
      const bodyVars = params.filter((p) => p.name !== recipient).map((p) => p.name);
      return {
        ...base,
        kind: "whatsapp",
        provider,
        config: {
          recipient_param: recipient,
          template,
          language: provider === "aisensy" ? null : language,
          phone_number_id: provider === "meta_cloud" ? phoneNumberId : null,
          body_params: bodyVars,
        },
      };
    }
    // calendar
    const start = params.find((p) => p.name.includes("start"))?.name ?? params[0]?.name;
    const end = params.find((p) => p.name.includes("end"))?.name ?? null;
    return {
      ...base,
      kind: "calendar",
      provider: "google",
      config: {
        operation,
        calendar_id: calendarId,
        start_param: start,
        end_param: end,
        duration_min: operation === "book" && !end ? 30 : null,
        summary_param: params.find((p) => p.name.includes("summary"))?.name ?? null,
      },
    };
  }

  // Only from a read that actually ARRIVED — a paused (offline) query reports no error and
  // no data, so `creds.data` must be checked directly rather than defaulted to `[]` (§52).
  const credentialKind =
    kind === "custom_api" ? "custom_api" : kind === "calendar" ? "google_calendar" : provider;
  const relevantCreds = creds.data
    ? creds.data.filter((c) => c.kind === credentialKind)
    : undefined;

  return (
    <form
      className="space-y-3 rounded-card border border-line bg-app p-4"
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate(buildBody(), { onSuccess: onDone });
      }}
    >
      <p className="text-sm font-semibold text-ink">New {ACTION_KIND_LABELS[kind]} action</p>

      {kind !== "custom_api" && kind !== "calendar" ? (
        <div>
          <label className="block">
            <span className={FIELD_LABEL}>Provider</span>
            <select
              className={FIELD}
              value={provider}
              onChange={(e) => setProvider(e.target.value as Provider)}
            >
              <option value="aisensy">AiSensy</option>
              <option value="meta_cloud">Meta Cloud API</option>
              <option value="interakt">Interakt</option>
              <option value="custom">Other (Custom API)</option>
            </select>
          </label>
        </div>
      ) : null}

      <div>
        <label className="block">
          <span className={FIELD_LABEL}>Name (snake_case)</span>
          <input
            className={FIELD}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="send_price_list"
            required
          />
        </label>
      </div>
      <div>
        <label className="block">
          <span className={FIELD_LABEL}>When should the AI use this?</span>
          <textarea
            className={FIELD}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Send once the caller confirms they want the price list."
            rows={2}
            required
          />
        </label>
        <span className={FIELD_HINT}>Helps the AI understand WHEN to use this integration.</span>
      </div>

      {kind === "custom_api" ? (
        <div className="flex gap-2">
          <div className="w-28">
            <label className="block">
              <span className={FIELD_LABEL}>Method</span>
              <select
                className={FIELD}
                value={method}
                onChange={(e) => setMethod(e.target.value as "GET" | "POST")}
              >
                <option value="GET">GET</option>
                <option value="POST">POST</option>
              </select>
            </label>
          </div>
          <div className="flex-1">
            <label className="block">
              <span className={FIELD_LABEL}>API URL</span>
              <input
                className={FIELD}
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://api.yourstore.com/orders"
                required
              />
            </label>
          </div>
        </div>
      ) : null}

      {kind === "whatsapp" ? (
        <>
          <div>
            <label className="block">
              <span className={FIELD_LABEL}>
                {provider === "aisensy" ? "Campaign name" : "Template name"}
              </span>
              <input
                className={FIELD}
                value={template}
                onChange={(e) => setTemplate(e.target.value)}
                required
              />
            </label>
          </div>
          {provider !== "aisensy" ? (
            <div>
              <label className="block">
                <span className={FIELD_LABEL}>Template language</span>
                <input
                  className={FIELD}
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  placeholder="en"
                />
              </label>
            </div>
          ) : null}
          {provider === "meta_cloud" ? (
            <div>
              <label className="block">
                <span className={FIELD_LABEL}>Phone Number ID</span>
                <input
                  className={FIELD}
                  value={phoneNumberId}
                  onChange={(e) => setPhoneNumberId(e.target.value)}
                  required
                />
              </label>
            </div>
          ) : null}
        </>
      ) : null}

      {kind === "calendar" ? (
        <>
          <div className="flex gap-2">
            <div className="w-32">
              <label className="block">
                <span className={FIELD_LABEL}>Operation</span>
                <select
                  className={FIELD}
                  value={operation}
                  onChange={(e) => setOperation(e.target.value as "book" | "check")}
                >
                  <option value="check">Check availability</option>
                  <option value="book">Book a slot</option>
                </select>
              </label>
            </div>
            <div className="flex-1">
              <label className="block">
                <span className={FIELD_LABEL}>Calendar id</span>
                <input
                  className={FIELD}
                  value={calendarId}
                  onChange={(e) => setCalendarId(e.target.value)}
                />
              </label>
            </div>
          </div>
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() =>
              calendarConnect.mutate(undefined, {
                onSuccess: (r) => window.open(r.authorize_url, "_blank", "noopener"),
              })
            }
          >
            <CalendarClock className="mr-1 inline h-3.5 w-3.5" /> Connect Google Calendar
          </button>
          {calendarConnect.error ? <ProblemNotice error={calendarConnect.error} /> : null}
        </>
      ) : null}

      {/* Credential picker (WhatsApp, Custom API, Calendar all need one). */}
      {relevantCreds === undefined ? (
        <ProblemNotice error={creds.error ?? new Error("Saved credentials could not be loaded.")} />
      ) : (
        <div>
          <label className="block">
            <span className={FIELD_LABEL}>Credential</span>
            <select
              className={FIELD}
              value={credentialId}
              onChange={(e) => setCredentialId(e.target.value)}
            >
              <option value="">— none —</option>
              {relevantCreds.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label} (····{c.last_four})
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      <ParamEditor params={params} onChange={setParams} />

      <div className="flex gap-2">
        <div className="flex-1">
          <label className="block">
            <span className={FIELD_LABEL}>When to run</span>
            <select
              className={FIELD}
              value={trigger}
              onChange={(e) => setTrigger(e.target.value as "during_call" | "after_call")}
            >
              <option value="during_call">During the call — AI decides</option>
              <option value="after_call">After the call ends — automatic</option>
            </select>
          </label>
        </div>
        <div className="flex-1">
          <label className="block">
            <span className={FIELD_LABEL}>Filler line (spoken while it runs)</span>
            <input
              className={FIELD}
              value={preCall}
              onChange={(e) => setPreCall(e.target.value)}
              placeholder="One moment…"
            />
          </label>
        </div>
      </div>

      {create.isError ? <ProblemNotice error={create.error} /> : null}
      <div className="flex gap-2">
        <button type="submit" className={PRIMARY_BUTTON} disabled={create.isPending}>
          {create.isPending ? "Saving…" : "Save action"}
        </button>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
