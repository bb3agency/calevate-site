"use client";

/**
 * TELL MY TEAM (D-904): who on the business's team hears about a caller who needs a person, and
 * when this agent tells them.
 *
 * The addresses are the account's (one list for every agent); each must be confirmed once with
 * the code sent to it, because the alert carries the caller's full number. WhatsApp is offered
 * only when the account has its own WhatsApp connected, and goes out through it.
 *
 * Writes are the owner's (`org:manage`); the server's refusal is shown in its own words.
 */

import { useId, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION_SM } from "@/components/console/section";
import { FIELD, FIELD_HINT, FIELD_LABEL, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";
import {
  useAddTeamContact,
  useDefaultTeamContact,
  useRemoveTeamContact,
  useResendTeamCode,
  useSaveTeamAlertRule,
  useTeamAlertRule,
  useTeamContacts,
  useVerifyTeamContact,
  type TeamAlertRule,
  type TeamContact,
  type TeamContacts,
} from "@/lib/api/teamAlerts";

type Slot = "name" | "phone" | "why" | "link";

/** The orders a WhatsApp template's blanks may be filled in. */
const SLOT_ORDERS: readonly { value: string; slots: Slot[]; label: string }[] = [
  { value: "name,phone,why,link", slots: ["name", "phone", "why", "link"], label: "Name, number, why, link to the call" },
  { value: "name,phone,why", slots: ["name", "phone", "why"], label: "Name, number, why" },
];

export function TeamAlertsPanel({ agent }: { agent: Agent }) {
  const session = useClientSession();
  const contacts = useTeamContacts(session);
  const rule = useTeamAlertRule(session, agent.id);
  const write = useWriteAccess(session, "org:manage", "change who hears about callers");

  if (contacts.isLoading || rule.isLoading) return <Skeleton rows={4} />;
  if (contacts.error || rule.error || !contacts.data || !rule.data) {
    return (
      <ProblemNotice
        error={contacts.error ?? rule.error ?? new Error("Your team settings could not be read just now.")}
        onRetry={() => {
          void contacts.refetch();
          void rule.refetch();
        }}
      />
    );
  }
  return (
    <div className="space-y-8">
      <Contacts data={contacts.data} canWrite={write.allowed} reason={write.reason} />
      <When agentId={agent.id} rule={rule.data} contacts={contacts.data.contacts} canWrite={write.allowed} reason={write.reason} />
    </div>
  );
}

// ------------------------------------------------------------------ where to send

function Contacts({ data, canWrite, reason }: { data: TeamContacts; canWrite: boolean; reason: string | null }) {
  return (
    <div className="space-y-3">
      <h4 className="text-sm font-semibold text-ink">Where to send</h4>
      {data.contacts.length === 0 ? (
        <p className="text-sm text-ink-muted">No team address yet. Add the email your team reads.</p>
      ) : (
        <ul className="divide-y divide-line border-y border-line">
          {data.contacts.map((contact) => (
            <ContactRow key={contact.id} contact={contact} canWrite={canWrite} reason={reason} />
          ))}
        </ul>
      )}
      {data.contacts.length < data.max_contacts ? (
        <AddContact accounts={data.whatsapp_accounts} canWrite={canWrite} reason={reason} />
      ) : null}
    </div>
  );
}

function ContactRow({ contact, canWrite, reason }: { contact: TeamContact; canWrite: boolean; reason: string | null }) {
  const session = useClientSession();
  const verify = useVerifyTeamContact(session);
  const resend = useResendTeamCode(session);
  const makeDefault = useDefaultTeamContact(session);
  const remove = useRemoveTeamContact(session);
  const verifyFeedback = useActionFeedback(verify, { errorDisplay: "inline", successToast: "Confirmed" });
  const resendFeedback = useActionFeedback(resend, { errorDisplay: "inline", successToast: "New code sent" });
  const [code, setCode] = useState("");
  const codeId = useId();
  const error = verify.error ?? resend.error ?? makeDefault.error ?? remove.error;
  const where = contact.channel === "whatsapp" ? `WhatsApp ${contact.address}` : contact.address;
  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="min-w-0 text-sm text-ink [overflow-wrap:anywhere]">
          {where}
          {contact.is_default ? <span className="ml-2 text-meta text-ink-faint">Used by default</span> : null}
        </span>
        <span className={`text-meta ${contact.verified ? "text-ink-muted" : "text-warn"}`}>
          {contact.verified
            ? contact.channel === "whatsapp" && !contact.whatsapp_account_id
              ? "Its WhatsApp connection was removed"
              : "Confirmed"
            : "Waiting for the code"}
        </span>
      </div>
      {!contact.verified ? (
        <form
          noValidate
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (code.trim()) verifyFeedback.run({ id: contact.id, code: code.trim() });
          }}
        >
          <div>
            <label htmlFor={codeId} className={FIELD_LABEL}>
              Code we sent there
            </label>
            <input
              id={codeId}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={12}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              className={`${FIELD} w-32`}
              disabled={!canWrite}
            />
          </div>
          <ActionButton type="submit" variant="primary-sm" status={verifyFeedback.status} successLabel="Confirmed" disabled={!canWrite} title={reason ?? undefined}>
            Confirm
          </ActionButton>
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={!canWrite || resendFeedback.status === "pending"}
            onClick={() => resendFeedback.run(contact.id)}
          >
            Send a new code
          </button>
        </form>
      ) : null}
      <div className="flex flex-wrap gap-3">
        {!contact.is_default ? (
          <button type="button" className={TEXT_ACTION_SM} disabled={!canWrite} title={reason ?? undefined} onClick={() => makeDefault.mutate(contact.id)}>
            Use by default
          </button>
        ) : null}
        <button type="button" className={TEXT_ACTION_SM} disabled={!canWrite} title={reason ?? undefined} onClick={() => remove.mutate(contact.id)}>
          Remove
        </button>
      </div>
      {error ? <ProblemNotice error={error} /> : null}
    </li>
  );
}

function AddContact({
  accounts,
  canWrite,
  reason,
}: {
  accounts: TeamContacts["whatsapp_accounts"];
  canWrite: boolean;
  reason: string | null;
}) {
  const session = useClientSession();
  const add = useAddTeamContact(session);
  const feedback = useActionFeedback(add, { errorDisplay: "inline", successToast: "Code sent" });
  const [channel, setChannel] = useState<"email" | "whatsapp">("email");
  const [address, setAddress] = useState("");
  const [account, setAccount] = useState(accounts[0]?.id ?? "");
  const [template, setTemplate] = useState("");
  const [language, setLanguage] = useState("");
  const [order, setOrder] = useState(SLOT_ORDERS[0].value);
  const ids = { address: useId(), account: useId(), template: useId(), language: useId(), order: useId() };
  const whatsapp = channel === "whatsapp";

  return (
    <form
      noValidate
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!address.trim()) return;
        add.mutate(
          whatsapp
            ? {
                channel,
                address: address.trim(),
                whatsapp: {
                  account_id: account,
                  template: template.trim(),
                  language: language.trim() || null,
                  body_values: SLOT_ORDERS.find((o) => o.value === order)?.slots ?? ["name", "phone", "why"],
                },
              }
            : { channel, address: address.trim() },
          { onSuccess: () => setAddress("") },
        );
      }}
    >
      {accounts.length > 0 ? (
        <fieldset className="flex flex-wrap gap-4 text-sm text-ink">
          <legend className={FIELD_LABEL}>Send by</legend>
          <label className="flex items-center gap-2">
            <input type="radio" name="team-channel" checked={!whatsapp} onChange={() => setChannel("email")} />
            Email
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" name="team-channel" checked={whatsapp} onChange={() => setChannel("whatsapp")} />
            WhatsApp, from your own account
          </label>
        </fieldset>
      ) : (
        <p className={FIELD_HINT}>To send on WhatsApp, connect your own WhatsApp account first.</p>
      )}
      <div>
        <label htmlFor={ids.address} className={FIELD_LABEL}>
          {whatsapp ? "Team WhatsApp number" : "Team email"}
        </label>
        <input
          id={ids.address}
          type={whatsapp ? "tel" : "email"}
          autoComplete="off"
          maxLength={254}
          value={address}
          onChange={(event) => setAddress(event.target.value)}
          className={FIELD}
          disabled={!canWrite}
        />
        <span className={FIELD_HINT}>
          {whatsapp ? "With the country code, for example +91 98765 43210." : "We send it a code to confirm it."}
        </span>
      </div>
      {whatsapp ? (
        <>
          <div>
            <label htmlFor={ids.account} className={FIELD_LABEL}>
              Your WhatsApp account
            </label>
            <select id={ids.account} value={account} onChange={(event) => setAccount(event.target.value)} className={FIELD}>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={ids.template} className={FIELD_LABEL}>
              Approved template
            </label>
            <input id={ids.template} maxLength={512} value={template} onChange={(event) => setTemplate(event.target.value)} className={FIELD} />
            <span className={FIELD_HINT}>The code to confirm the number is sent in its &ldquo;why&rdquo; blank.</span>
          </div>
          <div>
            <label htmlFor={ids.language} className={FIELD_LABEL}>
              Template language
            </label>
            <input id={ids.language} maxLength={16} value={language} onChange={(event) => setLanguage(event.target.value)} className={`${FIELD} w-32`} />
            <span className={FIELD_HINT}>For example en or te.</span>
          </div>
          <div>
            <label htmlFor={ids.order} className={FIELD_LABEL}>
              Its blanks, in order
            </label>
            <select id={ids.order} value={order} onChange={(event) => setOrder(event.target.value)} className={FIELD}>
              {SLOT_ORDERS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
        </>
      ) : null}
      {add.error ? <ProblemNotice error={add.error} /> : null}
      <ActionButton type="submit" variant="primary-sm" status={feedback.status} successLabel="Code sent" disabled={!canWrite} title={reason ?? undefined}>
        Add and send code
      </ActionButton>
    </form>
  );
}

// ------------------------------------------------------------------ when

function When({
  agentId,
  rule,
  contacts,
  canWrite,
  reason,
}: {
  agentId: string;
  rule: TeamAlertRule;
  contacts: TeamContact[];
  canWrite: boolean;
  reason: string | null;
}) {
  const session = useClientSession();
  const save = useSaveTeamAlertRule(session, agentId);
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved" });
  const [contactId, setContactId] = useState(rule.contact_id ?? "");
  const [outcomes, setOutcomes] = useState<string[]>(rule.on_outcomes);
  const [fields, setFields] = useState<Record<string, string[]>>(
    Object.fromEntries(rule.on_fields.map((f) => [f.key, f.values])),
  );
  const [inCall, setInCall] = useState(rule.in_call);
  const sendToId = useId();

  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate({
          contact_id: contactId || null,
          on_outcomes: outcomes,
          on_fields: Object.entries(fields)
            .filter(([, values]) => values.length > 0)
            .map(([key, values]) => ({ key, values })),
          in_call: inCall,
        });
      }}
    >
      <h4 className="text-sm font-semibold text-ink">When this agent tells them</h4>
      {rule.sends_to === null ? (
        <p role="status" className="text-sm text-warn">
          Nothing is sent until an address is confirmed.
        </p>
      ) : null}
      <div>
        <label htmlFor={sendToId} className={FIELD_LABEL}>
          Send to
        </label>
        <select id={sendToId} value={contactId} onChange={(event) => setContactId(event.target.value)} className={FIELD} disabled={!canWrite}>
          <option value="">The address used by default</option>
          {contacts.map((c) => (
            <option key={c.id} value={c.id}>
              {c.channel === "whatsapp" ? `WhatsApp ${c.address}` : c.address}
            </option>
          ))}
        </select>
      </div>

      <fieldset className="space-y-1.5">
        <legend className={FIELD_LABEL}>After a call that ends as</legend>
        {rule.outcomes.map((o) => (
          <label key={o.key} className="flex items-start gap-2 text-sm text-ink">
            <input type="checkbox" className="mt-0.5" disabled={!canWrite} checked={outcomes.includes(o.key)} onChange={() => setOutcomes(toggle(outcomes, o.key))} />
            <span>{o.label}</span>
          </label>
        ))}
      </fieldset>

      {rule.fields.map((field) => (
        <fieldset key={field.key} className="space-y-1.5">
          <legend className={FIELD_LABEL}>After a call where &ldquo;{field.label}&rdquo; is</legend>
          {field.values.map((value) => (
            <label key={value} className="flex items-start gap-2 text-sm text-ink">
              <input
                type="checkbox"
                className="mt-0.5"
                disabled={!canWrite}
                checked={(fields[field.key] ?? []).includes(value)}
                onChange={() => setFields({ ...fields, [field.key]: toggle(fields[field.key] ?? [], value) })}
              />
              <span>{value}</span>
            </label>
          ))}
        </fieldset>
      ))}

      <label className="flex items-start gap-2 text-sm text-ink">
        <input type="checkbox" className="mt-0.5" disabled={!canWrite} checked={inCall} onChange={(event) => setInCall(event.target.checked)} />
        <span>
          During a call, when the agent cannot help, it tells the team at once and says so to the caller.
          {inCall && !rule.in_call_live && rule.in_call ? (
            <span className="block text-meta text-warn">Off until an address is confirmed.</span>
          ) : null}
        </span>
      </label>
      <p className={FIELD_HINT}>The team gets the caller&rsquo;s name, full number, call time, why, and a link to the call.</p>

      {save.error ? <ProblemNotice error={save.error} /> : null}
      <div className="flex flex-wrap gap-2">
        <ActionButton type="submit" variant="primary-sm" status={feedback.status} successLabel="Saved" disabled={!canWrite} title={reason ?? undefined}>
          Save
        </ActionButton>
      </div>
    </form>
  );
}
