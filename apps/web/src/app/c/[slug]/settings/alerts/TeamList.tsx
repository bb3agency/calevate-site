"use client";

/**
 * The team half of "Who hears about hot leads" (D-904, D-967): the business's own addresses
 * that hear beside the owner. Each must be confirmed once with the code sent to it, because
 * its alert carries the caller's full number. WhatsApp is offered only when the account has its
 * own WhatsApp connected, and goes out through it.
 *
 * Writes are the owner's (`org:manage`); the server's refusal is shown in its own words.
 */

import Link from "next/link";
import { useId, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION, TEXT_ACTION_SM } from "@/components/console/section";
import { FIELD, FIELD_HINT, FIELD_LABEL, ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import {
  useAddTeamContact,
  useRemoveTeamContact,
  useResendTeamCode,
  useTeamContacts,
  useVerifyTeamContact,
  type TeamContact,
  type TeamContacts,
} from "@/lib/api/teamAlerts";

type Slot = "name" | "phone" | "why" | "link";

/** The orders a WhatsApp template's blanks may be filled in. */
const SLOT_ORDERS: readonly { value: string; slots: Slot[]; label: string }[] = [
  { value: "name,phone,why,link", slots: ["name", "phone", "why", "link"], label: "Name, number, why, link to the call" },
  { value: "name,phone,why", slots: ["name", "phone", "why"], label: "Name, number, why" },
];

export function TeamList({ canWrite, reason }: { canWrite: boolean; reason: string | null }) {
  const session = useClientSession();
  const contacts = useTeamContacts(session);
  const [adding, setAdding] = useState(false);

  if (contacts.isLoading) return <Skeleton rows={2} label="Checking your team" />;
  if (contacts.error || !contacts.data) {
    return (
      <ProblemNotice
        error={contacts.error ?? new Error("Your team could not be read just now.")}
        onRetry={() => void contacts.refetch()}
      />
    );
  }
  const data = contacts.data;
  const room = data.contacts.length < data.max_contacts;
  return (
    <>
      {data.contacts.map((contact) => (
        <ContactRow key={contact.id} contact={contact} canWrite={canWrite} reason={reason} />
      ))}
      <li className="py-4">
        {adding && room ? (
          <AddContact
            accounts={data.whatsapp_accounts}
            canWrite={canWrite}
            reason={reason}
            onDone={() => setAdding(false)}
          />
        ) : room ? (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={!canWrite}
            title={reason ?? undefined}
            onClick={() => setAdding(true)}
          >
            Add someone from your team
          </button>
        ) : (
          <p className="text-sm text-ink-muted">The list is full. Remove someone to add another.</p>
        )}
      </li>
    </>
  );
}

function ContactRow({ contact, canWrite, reason }: { contact: TeamContact; canWrite: boolean; reason: string | null }) {
  const session = useClientSession();
  const verify = useVerifyTeamContact(session);
  const resend = useResendTeamCode(session);
  const remove = useRemoveTeamContact(session);
  useActionFeedback(remove, { errorDisplay: "inline", successToast: "Removed" });
  const verifyFeedback = useActionFeedback(verify, { errorDisplay: "inline", successToast: "Confirmed" });
  const resendFeedback = useActionFeedback(resend, { errorDisplay: "inline", successToast: "New code sent" });
  const [code, setCode] = useState("");
  const codeId = useId();
  const error = verify.error ?? resend.error ?? remove.error;
  const unplugged = contact.channel === "whatsapp" && !contact.whatsapp_account_id;
  return (
    <li className="space-y-2 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="min-w-0">
          <p className="text-body font-medium text-ink [overflow-wrap:anywhere]">{contact.address}</p>
          <p className={`text-meta ${contact.verified && !unplugged ? "text-ink-muted" : "text-warn"}`}>
            {contact.channel === "whatsapp" ? "WhatsApp" : "Email"}
            {" · "}
            {!contact.verified ? "Waiting for the code" : unplugged ? "Its WhatsApp was disconnected" : "Hears every hot lead"}
          </p>
        </div>
        <button
          type="button"
          className={TEXT_ACTION_SM}
          disabled={!canWrite}
          title={reason ?? undefined}
          onClick={() => remove.mutate(contact.id)}
        >
          Remove
        </button>
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
      {error ? <ProblemNotice error={error} /> : null}
    </li>
  );
}

function AddContact({
  accounts,
  canWrite,
  reason,
  onDone,
}: {
  accounts: TeamContacts["whatsapp_accounts"];
  canWrite: boolean;
  reason: string | null;
  onDone: () => void;
}) {
  const { session, href } = useClientRealm();
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
          { onSuccess: onDone },
        );
      }}
    >
      {accounts.length > 0 ? (
        <fieldset className="flex flex-wrap gap-4 text-sm text-ink">
          <legend className={FIELD_LABEL}>Send by</legend>
          <label className="flex items-center gap-2 touch:min-h-11">
            <input type="radio" name="team-channel" checked={!whatsapp} onChange={() => setChannel("email")} />
            Email
          </label>
          <label className="flex items-center gap-2 touch:min-h-11">
            <input type="radio" name="team-channel" checked={whatsapp} onChange={() => setChannel("whatsapp")} />
            WhatsApp, from your own account
          </label>
        </fieldset>
      ) : (
        <p className={`${FIELD_HINT} flex flex-wrap items-center gap-x-3`}>
          <span>WhatsApp needs your own account.</span>
          <Link href={href(`/c/${session.orgSlug}/integrations`)} className={TEXT_ACTION}>
            Connect WhatsApp
          </Link>
        </p>
      )}
      <div>
        <label htmlFor={ids.address} className={FIELD_LABEL}>
          {whatsapp ? "Their WhatsApp number" : "Their email"}
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
            <span className={FIELD_HINT}>The confirm code goes in its &ldquo;why&rdquo; blank.</span>
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
      <div className="flex flex-wrap gap-2">
        <ActionButton type="submit" variant="primary-sm" status={feedback.status} successLabel="Code sent" disabled={!canWrite} title={reason ?? undefined}>
          Add and send code
        </ActionButton>
        <button type="button" className={SECONDARY_BUTTON_SM} onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
