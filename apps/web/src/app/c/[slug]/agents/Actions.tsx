"use client";

/**
 * The Actions tab — what an agent may DO mid-call (the ACTIONS feature).
 *
 * Master switch, saved credentials, and per-agent tool definitions across the three kinds
 * (Custom API, WhatsApp, Google Calendar). Every value binding is one of three things the
 * founder's spec names: a static value, a lead/call variable (</> — the caller's number,
 * the call id), or ✨ AI-decided (the model fills it from the conversation). A change
 * reaches live calls at the next publish, exactly like a voice or cap change.
 *
 * Types come off the generated client; nothing here recomputes server state.
 */

import { useState } from "react";
import { PlugZap, Plus, Trash2, KeyRound, FlaskConical, CalendarClock } from "lucide-react";

import {
  DANGER_BUTTON,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  ScrollRegion,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import {
  ACTION_KIND_LABELS,
  PROVIDER_LABELS,
  useAgentActions,
  useCreateAction,
  useCreateCredential,
  useCredentials,
  useCalendarConnect,
  useDeleteAction,
  useDeleteCredential,
  useSetActionEnabled,
  useSetMasterSwitch,
  useTestAction,
  type ActionParam,
  type ActionTool,
  type ActionToolInput,
  type IntegrationCredential,
} from "@/lib/api/actions";
import type { Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";

import { SectionHeading } from "./panels";

type Kind = "custom_api" | "whatsapp" | "calendar";
type Provider = "aisensy" | "meta_cloud" | "interakt" | "custom" | "google";
// Local unions for the two casts of a form-control string, so the wire-fixture guard's ban
// on asserting onto a GENERATED schema type does not apply (these are ours, not generated).
type CredKind = "aisensy" | "meta_cloud" | "interakt" | "custom_api" | "google_calendar";

const LEAD_VARS: { value: string; label: string }[] = [
  { value: "caller_phone", label: "Caller's phone number" },
  { value: "from_number", label: "From number" },
  { value: "to_number", label: "To number" },
  { value: "call_sid", label: "Call id" },
];

export function Actions({ agentId, session }: { agentId: string; session: Session }) {
  const actions = useAgentActions(session, agentId);
  const setMaster = useSetMasterSwitch(session, agentId);
  const [adding, setAdding] = useState<Kind | null>(null);

  if (actions.isPending) return <Skeleton rows={4} label="Loading actions…" />;
  if (actions.isError) return <ProblemNotice error={actions.error} onRetry={() => void actions.refetch()} />;

  const settings = actions.data;

  return (
    <section className="space-y-6">
      <SectionHeading icon={<PlugZap className="h-3.5 w-3.5" />}>Actions during the call</SectionHeading>
      <p className="text-sm text-ink-muted">
        Let this agent do things mid-call — send a WhatsApp, look something up, book a slot.
        Changes take effect on live calls the next time you publish the agent.
      </p>

      <label className="flex cursor-pointer items-start gap-3 rounded-card border border-line bg-app p-4">
        <input
          type="checkbox"
          role="switch"
          className="peer sr-only"
          checked={settings.api_actions_enabled}
          disabled={setMaster.isPending}
          onChange={(e) => setMaster.mutate(e.target.checked)}
        />
        <span
          aria-hidden
          className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full border border-line bg-surface transition-colors peer-checked:border-brand peer-checked:bg-brand after:absolute after:left-0.5 after:top-0.5 after:h-3.5 after:w-3.5 after:rounded-full after:bg-ink-faint after:transition-transform peer-checked:after:translate-x-4 peer-checked:after:bg-white"
        />
        <span>
          <span className="block text-sm font-medium text-ink">Enable API actions</span>
          <span className="block text-xs text-ink-muted">
            Master switch for every integration on this agent.
          </span>
        </span>
      </label>
      {setMaster.isError ? <ProblemNotice error={setMaster.error} /> : null}

      <Credentials session={session} />

      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-ink">Configured actions</h3>
        {settings.tools.length === 0 ? (
          <p className="text-sm text-ink-muted">No actions yet. Add one below.</p>
        ) : (
          <ul className="space-y-2">
            {settings.tools.map((tool) => (
              <ToolRow key={tool.id} tool={tool} agentId={agentId} session={session} />
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-ink">Add an action</h3>
        <div className="flex flex-wrap gap-2">
          {(["custom_api", "whatsapp", "calendar"] as Kind[]).map((kind) => (
            <button
              key={kind}
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => setAdding(kind)}
            >
              <Plus className="mr-1 inline h-3.5 w-3.5" />
              {ACTION_KIND_LABELS[kind]}
            </button>
          ))}
        </div>
        {settings.calendar_available ? null : (
          <p className={FIELD_HINT}>
            Google Calendar is not connected for your account yet — contact support to enable it.
          </p>
        )}
        {adding ? (
          <ActionForm
            kind={adding}
            agentId={agentId}
            session={session}
            onDone={() => setAdding(null)}
          />
        ) : null}
      </div>
    </section>
  );
}

function ToolRow({ tool, agentId, session }: { tool: ActionTool; agentId: string; session: Session }) {
  const setEnabled = useSetActionEnabled(session, agentId);
  const remove = useDeleteAction(session, agentId);
  const [testing, setTesting] = useState(false);
  const kindLabel = lookup(ACTION_KIND_LABELS, tool.kind) ?? tool.kind;
  const label =
    tool.kind === "whatsapp" && tool.provider
      ? `${kindLabel} · ${lookup(PROVIDER_LABELS, tool.provider) ?? tool.provider}`
      : kindLabel;

  return (
    <li className="rounded-card border border-line bg-app p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-ink">{tool.name}</p>
          <p className="truncate text-xs text-ink-muted">
            {label} · {tool.trigger === "after_call" ? "After the call" : "During the call"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => setTesting((v) => !v)}
          >
            <FlaskConical className="mr-1 inline h-3.5 w-3.5" />
            Test
          </button>
          <label className="flex items-center gap-1 text-xs text-ink-muted">
            <input
              type="checkbox"
              checked={tool.enabled}
              disabled={setEnabled.isPending}
              onChange={(e) => setEnabled.mutate({ toolId: tool.id, enabled: e.target.checked })}
            />
            On
          </label>
          <button
            type="button"
            className={DANGER_BUTTON}
            onClick={() => {
              if (confirm(`Remove the action “${tool.name}”?`)) remove.mutate(tool.id);
            }}
            aria-label={`Remove ${tool.name}`}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <p className="mt-2 text-xs text-ink-muted">{tool.description}</p>
      {setEnabled.error ? <ProblemNotice error={setEnabled.error} /> : null}
      {remove.error ? <ProblemNotice error={remove.error} /> : null}
      {testing ? <TestPanel tool={tool} agentId={agentId} session={session} /> : null}
    </li>
  );
}

function TestPanel({ tool, agentId, session }: { tool: ActionTool; agentId: string; session: Session }) {
  const test = useTestAction(session, agentId);
  // `tool.params` is a list of open dicts on the wire; read fields defensively (String())
  // rather than asserting onto a generated type (the wire-fixture guard bans that).
  const aiParams = tool.params.filter((p) => p.source !== "static");
  const [values, setValues] = useState<Record<string, string>>({});

  return (
    <div className="mt-3 rounded-card border border-line bg-surface p-3">
      <p className="text-xs font-medium text-ink">Test with sample values</p>
      <p className={FIELD_HINT}>
        This runs the real call — a WhatsApp test really sends, a booking really books.
      </p>
      <div className="mt-2 space-y-2">
        {aiParams.map((p) => {
          const nm = String(p.name);
          return (
            <div key={nm}>
              <label className="block">
                <span className={FIELD_LABEL}>{nm}</span>
                <input
                  className={FIELD}
                  value={values[nm] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [nm]: e.target.value }))}
                />
              </label>
            </div>
          );
        })}
      </div>
      <button
        type="button"
        className={`${PRIMARY_BUTTON_SM} mt-2`}
        disabled={test.isPending}
        onClick={() => test.mutate({ toolId: tool.id, values })}
      >
        {test.isPending ? "Running…" : "Run test"}
      </button>
      {test.isError ? <ProblemNotice error={test.error} /> : null}
      {test.data ? (
        <NoticeBox tone={test.data.ok ? "ok" : "warn"} title={`Result: ${test.data.status}`}>
          <ScrollRegion className="max-h-64" label="Test result">
            <pre className="whitespace-pre-wrap break-words text-xs">
              {JSON.stringify(test.data.payload, null, 2)}
            </pre>
          </ScrollRegion>
        </NoticeBox>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------- credentials ----

function Credentials({ session }: { session: Session }) {
  const creds = useCredentials(session);
  const create = useCreateCredential(session);
  const remove = useDeleteCredential(session);
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<CredKind>("aisensy");
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");

  return (
    <div className="space-y-3 rounded-card border border-line bg-app p-4">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-ink">
          <KeyRound className="h-3.5 w-3.5" /> Saved credentials
        </h3>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => setOpen((v) => !v)}>
          <Plus className="mr-1 inline h-3.5 w-3.5" /> Add credential
        </button>
      </div>
      <p className={FIELD_HINT}>
        Saved once and reused across actions. Rotating one updates every action that uses it.
        We never show the value back.
      </p>
      {creds.isPending ? (
        <Skeleton rows={1} />
      ) : creds.isError ? (
        <ProblemNotice error={creds.error} />
      ) : creds.data.length === 0 ? (
        <p className="text-sm text-ink-muted">No credentials saved yet.</p>
      ) : (
        <ul className="space-y-1">
          {creds.data.map((c: IntegrationCredential) => (
            <li key={c.id} className="flex items-center justify-between text-sm">
              <span className="text-ink">
                {c.label}{" "}
                <span className="text-ink-faint">
                  · {lookup(PROVIDER_LABELS, c.kind) ?? c.kind} · ····{c.last_four}
                </span>
              </span>
              <button
                type="button"
                className={DANGER_BUTTON}
                onClick={() => {
                  if (confirm(`Delete credential “${c.label}”?`)) remove.mutate(c.id);
                }}
                aria-label={`Delete ${c.label}`}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {remove.error ? <ProblemNotice error={remove.error} /> : null}
      {open ? (
        <form
          className="space-y-2 border-t border-line pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(
              { kind, label, secret },
              {
                onSuccess: () => {
                  setOpen(false);
                  setLabel("");
                  setSecret("");
                },
              },
            );
          }}
        >
          <div>
            <label className="block"><span className={FIELD_LABEL}>For</span>
              <select className={FIELD} value={kind} onChange={(e) => setKind(e.target.value as CredKind)}>
              <option value="aisensy">AiSensy API key</option>
              <option value="meta_cloud">Meta WhatsApp token</option>
              <option value="interakt">Interakt API key</option>
              <option value="custom_api">Custom API key / token</option>
            </select></label>
          </div>
          <div>
            <label className="block"><span className={FIELD_LABEL}>Name</span>
              <input className={FIELD} value={label} onChange={(e) => setLabel(e.target.value)} required /></label>
          </div>
          <div>
            <label className="block"><span className={FIELD_LABEL}>Secret</span>
              <input
              className={FIELD}
              type="password"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              required
            /></label>
          </div>
          {create.isError ? <ProblemNotice error={create.error} /> : null}
          <button type="submit" className={PRIMARY_BUTTON_SM} disabled={create.isPending}>
            {create.isPending ? "Saving…" : "Save credential"}
          </button>
        </form>
      ) : null}
    </div>
  );
}

// --------------------------------------------------------------- add form ----

interface DraftParam {
  name: string;
  source: "static" | "lead_var" | "ai";
  value: string;
  lead_var: string;
  description: string;
  type: "string" | "integer" | "number" | "boolean";
  required: boolean;
}

function newParam(): DraftParam {
  return { name: "", source: "ai", value: "", lead_var: "caller_phone", description: "", type: "string", required: false };
}

function toParam(p: DraftParam): ActionParam {
  return {
    name: p.name,
    source: p.source,
    value: p.source === "static" ? p.value : null,
    lead_var: p.source === "lead_var" ? p.lead_var : null,
    description: p.description,
    type: p.type,
    required: p.required,
  };
}

function ActionForm({
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
      const recipient = params.find((p) => p.source === "lead_var")?.name ?? params[0]?.name ?? "recipient";
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
          <label className="block"><span className={FIELD_LABEL}>Provider</span>
              <select
            className={FIELD}
            value={provider}
            onChange={(e) => setProvider(e.target.value as Provider)}
          >
            <option value="aisensy">AiSensy</option>
            <option value="meta_cloud">Meta Cloud API</option>
            <option value="interakt">Interakt</option>
            <option value="custom">Other (Custom API)</option>
          </select></label>
        </div>
      ) : null}

      <div>
        <label className="block"><span className={FIELD_LABEL}>Name (snake_case)</span>
              <input
          className={FIELD}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="send_price_list"
          required
        /></label>
      </div>
      <div>
        <label className="block"><span className={FIELD_LABEL}>When should the AI use this?</span>
              <textarea
          className={FIELD}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Send once the caller confirms they want the price list."
          rows={2}
          required
        /></label>
        <span className={FIELD_HINT}>Helps the AI understand WHEN to use this integration.</span>
      </div>

      {kind === "custom_api" ? (
        <>
          <div className="flex gap-2">
            <div className="w-28">
              <label className="block"><span className={FIELD_LABEL}>Method</span>
              <select className={FIELD} value={method} onChange={(e) => setMethod(e.target.value as "GET" | "POST")}>
                <option value="GET">GET</option>
                <option value="POST">POST</option>
              </select></label>
            </div>
            <div className="flex-1">
              <label className="block"><span className={FIELD_LABEL}>API URL</span>
              <input className={FIELD} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://api.yourstore.com/orders" required /></label>
            </div>
          </div>
        </>
      ) : null}

      {kind === "whatsapp" ? (
        <>
          <div>
            <label className="block"><span className={FIELD_LABEL}>
              {provider === "aisensy" ? "Campaign name" : "Template name"}
            </span>
              <input className={FIELD} value={template} onChange={(e) => setTemplate(e.target.value)} required /></label>
          </div>
          {provider !== "aisensy" ? (
            <div>
              <label className="block"><span className={FIELD_LABEL}>Template language</span>
              <input className={FIELD} value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="en" /></label>
            </div>
          ) : null}
          {provider === "meta_cloud" ? (
            <div>
              <label className="block"><span className={FIELD_LABEL}>Phone Number ID</span>
              <input className={FIELD} value={phoneNumberId} onChange={(e) => setPhoneNumberId(e.target.value)} required /></label>
            </div>
          ) : null}
        </>
      ) : null}

      {kind === "calendar" ? (
        <>
          <div className="flex gap-2">
            <div className="w-32">
              <label className="block"><span className={FIELD_LABEL}>Operation</span>
              <select className={FIELD} value={operation} onChange={(e) => setOperation(e.target.value as "book" | "check")}>
                <option value="check">Check availability</option>
                <option value="book">Book a slot</option>
              </select></label>
            </div>
            <div className="flex-1">
              <label className="block"><span className={FIELD_LABEL}>Calendar id</span>
              <input className={FIELD} value={calendarId} onChange={(e) => setCalendarId(e.target.value)} /></label>
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
          <label className="block"><span className={FIELD_LABEL}>When to run</span>
              <select className={FIELD} value={trigger} onChange={(e) => setTrigger(e.target.value as "during_call" | "after_call")}>
            <option value="during_call">During the call — AI decides</option>
            <option value="after_call">After the call ends — automatic</option>
          </select></label>
        </div>
        <div className="flex-1">
          <label className="block"><span className={FIELD_LABEL}>Filler line (spoken while it runs)</span>
              <input className={FIELD} value={preCall} onChange={(e) => setPreCall(e.target.value)} placeholder="One moment…" /></label>
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

function ParamEditor({ params, onChange }: { params: DraftParam[]; onChange: (p: DraftParam[]) => void }) {
  return (
    <div className="space-y-2 rounded-card border border-line bg-surface p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-ink">Parameters</span>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={() => onChange([...params, newParam()])}>
          <Plus className="mr-1 inline h-3.5 w-3.5" /> Add parameter
        </button>
      </div>
      {params.length === 0 ? <p className={FIELD_HINT}>No parameters yet.</p> : null}
      {params.map((p, i) => (
        <div key={i} className="space-y-1 rounded border border-line p-2">
          <div className="flex gap-2">
            <input
              className={FIELD}
              value={p.name}
              placeholder="name"
              onChange={(e) => onChange(params.map((q, j) => (j === i ? { ...q, name: e.target.value } : q)))}
            />
            <select
              className={FIELD}
              value={p.source}
              onChange={(e) => onChange(params.map((q, j) => (j === i ? { ...q, source: e.target.value as DraftParam["source"] } : q)))}
            >
              <option value="ai">✨ AI decides</option>
              <option value="lead_var">&lt;/&gt; Lead variable</option>
              <option value="static">Static value</option>
            </select>
            <button
              type="button"
              className={DANGER_BUTTON}
              onClick={() => onChange(params.filter((_, j) => j !== i))}
              aria-label="Remove parameter"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
          {p.source === "static" ? (
            <input
              className={FIELD}
              value={p.value}
              placeholder="value"
              onChange={(e) => onChange(params.map((q, j) => (j === i ? { ...q, value: e.target.value } : q)))}
            />
          ) : null}
          {p.source === "lead_var" ? (
            <select
              className={FIELD}
              value={p.lead_var}
              onChange={(e) => onChange(params.map((q, j) => (j === i ? { ...q, lead_var: e.target.value } : q)))}
            >
              {LEAD_VARS.map((v) => (
                <option key={v.value} value={v.value}>
                  {v.label}
                </option>
              ))}
            </select>
          ) : null}
          {p.source === "ai" ? (
            <input
              className={FIELD}
              value={p.description}
              placeholder="What should the AI collect? (e.g. the order id)"
              onChange={(e) => onChange(params.map((q, j) => (j === i ? { ...q, description: e.target.value } : q)))}
            />
          ) : null}
        </div>
      ))}
    </div>
  );
}
