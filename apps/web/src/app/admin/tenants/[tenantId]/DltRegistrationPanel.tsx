"use client";

import { useState } from "react";
import { BookOpenCheck } from "lucide-react";

import { Section } from "@/components/console/section";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  MonoValue,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  istDateToInstant,
} from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import {
  useRecordDltRegistration,
  type PeStatus,
  type TmLinkStatus,
} from "@/lib/api/admin";
import { Term } from "@/lib/glossary";


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
    <Section
      title="Entity registration"
      description={
        <>
          The client&apos;s own registration with the <Term id="dlt" /> registrar as a
          principal entity (<Term id="pe" term="PE" audience="operator" />), and their link to
          us.
        </>
      }
      info="The registrar issues three separate registrations and none implies another: this one is the client's own entity, the number header is its own, the voice template is a third. None of them is needed to launch a campaign; this is a record for clients who registered."
    >

      {record.error && <ProblemNotice error={record.error} />}
      {record.data && (
        /* The API has no GET for this, so the panel can only show what THIS screen just
           wrote — never the stored state on load. Echoing what was recorded is the honest
           version; claiming to display a current state we did not read would be worse. */
        <NoticeBox tone="ok" icon={<BookOpenCheck className="h-4 w-4" />}>
          <p>
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
            .
          </p>
        </NoticeBox>
      )}

      <form
        className="mt-4 max-w-sm space-y-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          record.mutate({
            status,
            tm_link_status: tmLink,
            pe_id: peId.trim() || null,
            entity_name: entityName.trim() || null,
            // The date on an Indian registrar's letter, read as MIDNIGHT IST whatever zone
            // the operator is in: UTC midnight is a future moment in IST (refused), and the
            // browser's midnight files a different day east of IST. `istDateToInstant` is
            // the one spelling of this.
            registered_at: istDateToInstant(registeredAt),
          });
        }}
      >
        <div className="space-y-4">
          <div>
            <label htmlFor="dlt-pe-status" className={FIELD_LABEL}>
              Entity registration status
            </label>
            <select
              id="dlt-pe-status"
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
          </div>
          <div>
            <label htmlFor="dlt-tm-link" className={FIELD_LABEL}>
              Telemarketer link status
            </label>
            <select
              id="dlt-tm-link"
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
          <div>
            <label htmlFor="dlt-pe-id" className={FIELD_LABEL}>
              PE id from the registrar (optional)
            </label>
            <input
              id="dlt-pe-id"
              value={peId}
              disabled={!write.allowed}
              onChange={(e) => setPeId(e.target.value)}
              className={`${FIELD} font-mono`}
            />
          </div>
          <div>
            <label htmlFor="dlt-entity-name" className={FIELD_LABEL}>
              Registered entity name (optional)
            </label>
            <input
              id="dlt-entity-name"
              value={entityName}
              disabled={!write.allowed}
              onChange={(e) => setEntityName(e.target.value)}
              className={FIELD}
            />
          </div>
          <div>
            {/* The zone is in the label: a `type="date"` carries none, and this is the
                date on an Indian registrar's letter wherever the operator sits. */}
            <label htmlFor="dlt-registered-at" className={FIELD_LABEL}>
              Registered on (IST)
            </label>
            <input
              id="dlt-registered-at"
              type="date"
              value={registeredAt}
              disabled={!write.allowed}
              onChange={(e) => setRegisteredAt(e.target.value)}
              className={FIELD}
            />
          </div>
        </div>
        <span className={FIELD_HINT}>Re-recording is normal — it updates what is on file.</span>
        <div className="flex justify-end">
          <button
            type="submit"
            className={PRIMARY_BUTTON}
            disabled={record.isPending || !write.allowed}
          >
            {record.isPending ? "Recording…" : "Record registration"}
          </button>
        </div>
      </form>
    </Section>
  );
}