"use client";

import { ShieldAlert, ShieldCheck } from "lucide-react";

import { Card, MonoValue, NoticeBox, ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import {
  peStatusCopy,
  tmLinkCopy,
  usePeRegistration,
  type PeRegistration,
} from "@/lib/api/dltRegistration";
import type { Session } from "@/lib/api/client";
import { Term } from "@/lib/glossary";

/**
 * The DLT half: whether the registrar has this business as a Principal Entity, and
 * whether that entity authorises Calevate to dial for it.
 *
 * This is the fact behind `pe_registration_missing` / `pe_registration_not_active` /
 * `tm_link_not_active` — three of the launch gate's refusals — and it had no screen. A
 * client whose campaign button was disabled could read the blocker and could not read the
 * registration it was about.
 *
 * §52 in three branches, and the middle one is the point: a read that FAILED must not
 * render as "nothing filed yet". `recorded: false` and "we could not ask" are opposite
 * facts that would produce the same card, and the first sends a client to their account
 * manager over a registration that may be perfectly active.
 *
 * Read-only with no control anywhere, and that is not an omission — see the module
 * docstring on `lib/api/dltRegistration.ts`. The write is operator-only because a client
 * who could set these two statuses would be clearing their own compliance gate. So there
 * is nothing here for `useWriteAccess` to gate, and no `RestrictionNote`: `org:read` is
 * held by every client role and survives a D-22 read-only session.
 */
export function DltRegistration({ session }: { session: Session }) {
  const registration = usePeRegistration(session);

  if (registration.isLoading) {
    return (
      <Card title="Campaign registration (DLT)">
        <Skeleton rows={4} />
      </Card>
    );
  }

  if (registration.error || !registration.data) {
    return (
      <Card title="Campaign registration (DLT)">
        <ProblemNotice
          error={
            registration.error ??
            new Error("Your DLT registration did not load, so we cannot say where it stands.")
          }
          onRetry={() => void registration.refetch()}
        />
      </Card>
    );
  }

  const pe = registration.data;
  return (
    <Card title="Campaign registration (DLT)">
      <DltVerdict registration={pe} />
      <DltStatuses registration={pe} />
      {pe.recorded && <DltOnFile registration={pe} />}
      {/* `term="registrar"` prints the word already in this sentence and attaches the
          glossary's own explanation to it — the gloss this module owes its reader
          (UX-DOCTRINE §5) without adding a word of copy. */}
      <p className="mt-3 text-xs text-ink-faint">
        We record this against the <Term id="dlt" term="registrar" /> on your behalf and
        cannot change what it says — there is no control here that sets your own status,
        for the same reason there is none above.
      </p>
    </Card>
  );
}

/**
 * Cleared or not, in one box — off `is_active`, never off `status`.
 *
 * The same doctrine as the KYC `Verdict`: the server computes the predicate the launch
 * gate asks (`PeRegistration.is_active` = both statuses active), so a screen that
 * recombined the two statuses itself would eventually disagree with the gate that actually
 * refuses the campaign. The icon is keyed on the same boolean as the sentence.
 */
function DltVerdict({ registration }: { registration: PeRegistration }) {
  const Icon = registration.is_active ? ShieldCheck : ShieldAlert;
  return (
    <NoticeBox
      tone={registration.is_active ? "ok" : registration.recorded ? "warn" : "neutral"}
      icon={<Icon className="h-5 w-5" />}
      title={
        registration.is_active
          ? "Your business is registered to run campaigns."
          : registration.recorded
            ? "Your DLT registration is not active yet."
            : "We have not filed a DLT registration for your business."
      }
    >
      <div className="min-w-0">
        <p className="mt-1">
          {registration.is_active
            ? "Nothing on the DLT side is holding up a campaign launch."
            : "Outbound campaigns cannot launch until both lines below are active."}
        </p>
        {!registration.is_active && (
          <p className="mt-2 font-semibold">
            Calls coming IN are unaffected — your agent keeps answering the phone.
          </p>
        )}
      </div>
    </NoticeBox>
  );
}

/**
 * The two statuses, side by side, because they fail separately and to different desks.
 *
 * The registrar approves the entity; YOU authorise Calevate as your telemarketer on the
 * registrar's portal. Collapsing them into one verdict would send half the clients who
 * read this to the wrong place — which is exactly why the API emits
 * `pe_registration_not_active` and `tm_link_not_active` as different blockers.
 *
 * A status this build cannot name prints the raw word from the wire with a sentence that
 * claims nothing about it. Vaguer than the table, and it cannot be wrong.
 */
function DltStatuses({ registration }: { registration: PeRegistration }) {
  const entity = peStatusCopy(registration.status);
  const link = tmLinkCopy(registration.tm_link_status);
  return (
    <dl className="mt-4 space-y-3 text-sm">
      <div>
        <dt className="font-semibold text-ink">
          Your business as a{" "}
          <Term id="pe" />
          : {entity?.label ?? registration.status ?? "not filed"}
        </dt>
        <dd className="text-ink-muted">
          {entity?.next ??
            (registration.recorded
              ? "Ask your account manager what this state means for your campaigns."
              : "Nothing has been filed with the registrar for your business yet. Ask your account manager to start it.")}
        </dd>
      </div>
      <div>
        <dt className="font-semibold text-ink">
          Calevate authorised to dial for you:{" "}
          {link?.label ?? registration.tm_link_status ?? "not filed"}
        </dt>
        <dd className="text-ink-muted">
          {link?.next ??
            (registration.recorded
              ? "Ask your account manager where this authorisation stands."
              : "This authorisation follows the registration above; there is nothing to authorise until that exists.")}
        </dd>
        <CalevateTelemarketerId registration={registration} />
      </div>
    </dl>
  );
}

/**
 * Calevate's OWN telemarketer registration number, shown to the client who needs it.
 *
 * The authorisation above is made BY THE CLIENT on the registrar's portal — `TM_LINK_COPY`
 * says so in as many words — and the portal asks for the telemarketer's registration
 * number. So the client needs ours, and until 2 September 2026 the only place it appeared
 * was `/legal/acceptable-use`, as `{{DLT_TELEMARKETER_ID}}` in a public legal document.
 * That is the wrong surface twice over: an operational identifier published to the open
 * web, and a client hunting a legal page for a number they need while filling in a form.
 * It is on this screen instead, behind a session, beside the sentence that asks for it.
 *
 * `calevate_tm_id` comes off `GET /v1/compliance/dlt-registration` and is sourced from
 * `platform_state`, which an operator writes in the ops console — never hard-coded here.
 * A missing id is a state, not an error: the registration itself is not through, which is
 * the platform-wide blocker the campaign screen renders as its own notice, and the honest
 * sentence is that there is nothing to authorise against yet rather than a blank.
 */
function CalevateTelemarketerId({ registration }: { registration: PeRegistration }) {
  const id = (registration.calevate_tm_id ?? "").trim();
  if (id === "") {
    return (
      <dd className="mt-1 text-ink-muted">
        Our own <Term id="tm" term="telemarketer" /> registration is not through yet, so
        there is nothing for you to authorise against on the registrar&apos;s portal. That
        holds up outbound campaigns for every Calevate account at once and there is nothing
        at your end that clears it. Calls coming IN are unaffected.
      </dd>
    );
  }
  return (
    <dd className="mt-1 text-ink-muted">
      The registrar asks for the telemarketer&apos;s registration number when you make that
      authorisation. Ours is <span className="font-mono text-ink">{id}</span>
      {registration.calevate_tm_active
        ? "."
        : " — though our registration is not active yet, so the authorisation cannot complete until it is."}
    </dd>
  );
}

/**
 * What is on file, shown to the business it is about.
 *
 * `verified_at` is when WE last checked this against the registrar, not when we last
 * hoped — the route's docstring is explicit — so it is labelled that way. A row with no
 * value is dropped rather than dashed, the same rule the KYC `OnFile` follows.
 */
function DltOnFile({ registration }: { registration: PeRegistration }) {
  const rows: { label: string; value: string | null; mono?: boolean }[] = [
    { label: "Registered business name", value: registration.entity_name },
    { label: "Principal Entity ID", value: registration.pe_id, mono: true },
    {
      label: "Registered with the registrar",
      value: registration.registered_at ? formatIST(registration.registered_at) : null,
    },
    {
      label: "We last checked",
      value: registration.verified_at ? formatIST(registration.verified_at) : null,
    },
  ];
  const present = rows.filter((row) => row.value !== null && row.value !== "");
  if (present.length === 0) return null;

  return (
    <dl className="mt-4 divide-y divide-line">
      {present.map((row) => (
        <div
          key={row.label}
          className="flex flex-wrap justify-between gap-2 py-2 text-sm first:pt-0 last:pb-0"
        >
          <dt className="text-ink-muted">{row.label}</dt>
          <dd className="font-semibold text-ink">
            {row.mono ? <MonoValue>{row.value}</MonoValue> : row.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
