"use client";

import { useState } from "react";
import { BookOpenCheck } from "lucide-react";

import { MonoValue, NoticeBox, ProblemNotice, istDateToInstant } from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import {
  useRecordDltRegistration,
  type PeStatus,
  type TmLinkStatus,
} from "@/lib/api/admin";
import { Term } from "@/lib/glossary";

import { FIELD, PrimaryButton } from "./controls";

const PE_STATUSES: { value: PeStatus; label: string }[] = [
  { value: "not_started", label: "Not started — no application filed" },
  { value: "submitted", label: "Submitted — filed, awaiting the registrar" },
  { value: "active", label: "Active — granted and in force" },
  { value: "suspended", label: "Suspended — paused by the registrar" },
  { value: "rejected", label: "Rejected — refused by the registrar" },
];

const TM_LINK_STATUSES: { value: TmLinkStatus; label: string }[] = [
  { value: "not_linked", label: "Not linked — the client has not authorised us" },
  { value: "pending", label: "Pending — authorisation requested" },
  { value: "active", label: "Active — we may call on their behalf" },
  { value: "revoked", label: "Revoked — authorisation withdrawn" },
];

/**
 * The client's DLT Principal Entity registration, and its link to us (SEC-COMP §3).
 *
 * The symptom: three launch blockers (`pe_registration_missing`,
 * `pe_registration_not_active`, `tm_link_not_active`) tell the client "we handle this,
 * ask your account manager" — and the account manager had nowhere to record the answer
 * when the registrar gave it. Every one of those campaigns stayed blocked with no
 * control anywhere in the product to clear it.
 *
 * OPERATOR-ONLY, and that is the mechanism's integrity rather than a missing feature:
 * the launch gate reads these two statuses, so a client who could set them would be
 * clearing their own compliance blocker by choosing a value from a dropdown. There is
 * no client-realm route for this and there must not be one.
 *
 * Two statuses, not one "ready" flag, because they fail separately and the next action
 * differs — an unregistered entity is a registration the CLIENT takes out in their own
 * name (they are the Principal Entity); a missing TM link is an authorisation only they
 * can grant, from that same login. Both are theirs to do; ours is the TM-ID they bind
 * and our acceptance of the chain.
 */
export function DltRegistrationPanel({ tenantId, write }: { tenantId: string; write: ReturnType<typeof useAdminAccess> }) {
  const record = useRecordDltRegistration(tenantId);
  const [status, setStatus] = useState<PeStatus>("not_started");
  const [tmLink, setTmLink] = useState<TmLinkStatus>("not_linked");
  const [peId, setPeId] = useState("");
  const [entityName, setEntityName] = useState("");
  const [registeredAt, setRegisteredAt] = useState("");

  return (
    <div className="min-w-0 space-y-3 lg:col-span-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
        Entity registration with the{" "}
        <Term id="dlt" /> (
        <Term id="pe" term="PE" audience="operator" />)
      </h3>
      <p className="text-xs text-ink-muted">
        The registrar issues three separate registrations and none implies another: this
        one is the client&apos;s own entity, the number header is its own, the voice
        template is a third. The campaign launch check asks for all three by name.
      </p>

      {record.error && <ProblemNotice error={record.error} />}
      {record.data && (
        /* The API has no GET for this, so the panel can only show what THIS screen just
           wrote — never the stored state on load. Saying "recorded" and echoing the
           values back is the honest version; claiming to display current state we did
           not read would be worse than showing nothing. */
        <NoticeBox tone="ok" icon={<BookOpenCheck className="h-4 w-4" />}>
          <p className="text-xs">
            Recorded: entity registration{" "}
            <span className="font-medium">{record.data.status.replace(/_/g, " ")}</span>,{" "}
            <Term id="tm" term="TM" audience="operator" />{" "}
            link <span className="font-medium">{record.data.tm_link_status.replace(/_/g, " ")}</span>
            {record.data.pe_id && (
              <>
                , <Term id="pe" term="PE" audience="operator" /> id{" "}
                <MonoValue>{record.data.pe_id}</MonoValue>
              </>
            )}
            . The client&apos;s campaign launch check reflects this on its next refresh.
          </p>
        </NoticeBox>
      )}

      <form
        className="space-y-2"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          record.mutate({
            status,
            tm_link_status: tmLink,
            pe_id: peId.trim() || null,
            entity_name: entityName.trim() || null,
            // `<input type="date">` read as MIDNIGHT IST, not UTC and not the browser's.
            // UTC midnight is 05:30 IST, so "today" would be a moment that has not
            // happened yet and the server refuses a future registration date. The
            // browser's own midnight avoided that and introduced a worse one: this is the
            // date on an Indian registrar's letter, it is read back with `formatIST`, and
            // from a machine east of IST local midnight lands on the previous IST day —
            // so the same digits filed a different date depending on who typed them.
            // `istDateToInstant` (components/ui.tsx) is the one spelling of this.
            registered_at: istDateToInstant(registeredAt),
          });
        }}
      >
        <div className="flex flex-wrap gap-2">
          <select
            aria-label="Entity registration status"
            value={status}
            disabled={!write.allowed}
            onChange={(e) => setStatus(e.target.value as PeStatus)}
            className={FIELD}
          >
            {PE_STATUSES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            aria-label="Telemarketer link status"
            value={tmLink}
            disabled={!write.allowed}
            onChange={(e) => setTmLink(e.target.value as TmLinkStatus)}
            className={FIELD}
          >
            {TM_LINK_STATUSES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            value={peId}
            disabled={!write.allowed}
            onChange={(e) => setPeId(e.target.value)}
            placeholder="PE id from the registrar (optional)"
            className={`flex-1 font-mono ${FIELD}`}
          />
          <input
            value={entityName}
            disabled={!write.allowed}
            onChange={(e) => setEntityName(e.target.value)}
            placeholder="Registered entity name (optional)"
            className={`flex-1 ${FIELD}`}
          />
          <input
            type="date"
            // THE ZONE IS ON SCREEN, for `/admin/ops`'s reason, said there in full: a
            // `type="date"` carries no zone, so an unlabelled one reads as this machine's
            // calendar — and this field holds the date printed on an Indian registrar's
            // letter, which is IST wherever the operator is sitting. The two screens
            // record the same fact and now say the same thing about it.
            aria-label="Registered on (IST)"
            value={registeredAt}
            disabled={!write.allowed}
            onChange={(e) => setRegisteredAt(e.target.value)}
            className={FIELD}
          />
        </div>
        <p className="text-xs text-ink-muted">
          Re-recording is normal — it updates what is on file.
        </p>
        <PrimaryButton type="submit" disabled={record.isPending || !write.allowed}>
          {record.isPending ? "Recording…" : "Record registration"}
        </PrimaryButton>
      </form>
    </div>
  );
}
