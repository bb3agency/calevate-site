"use client";

import { StatusPill } from "@/components/console/statusPill";
import { Disclosure, MonoValue, formatIST } from "@/components/ui";
import { peStatusCopy, tmLinkCopy, type PeRegistration } from "@/lib/api/dltRegistration";
import { Term } from "@/lib/glossary";

/**
 * The DLT registration on Verify your business: whether the registrar has this business as
 * a Principal Entity, and whether that entity authorises Calevate to dial for it.
 *
 * Shown only for a registration somebody filed. Since D-692 no gate asks for one, so an
 * empty record would read as a missing step on a page whose steps are what opens calling.
 *
 * §52: this takes a registration that ARRIVED. The page renders a failed read as a refusal
 * and never as "nothing filed yet": `recorded: false` and "we could not ask" are opposite
 * facts, and the first sends a client to their account manager over a registration that may
 * be perfectly active.
 *
 * Read-only with no control anywhere (see `lib/api/dltRegistration.ts`): the write is
 * operator-only because a client who could set these two statuses would be clearing their
 * own compliance gate. `org:read` is held by every client role, so nothing here is gated.
 */
export function DltDetails({ registration }: { registration: PeRegistration }) {
  // `is_active` is the server's predicate, never re-derived from the two statuses.
  const verdict = registration.is_active
    ? "Your business is registered on DLT."
    : "Your DLT registration is not active yet.";
  return (
    <section aria-labelledby="dlt-heading" className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 id="dlt-heading" className="text-heading text-ink">
          Campaign registration (<Term id="dlt" />)
        </h2>
        <StatusPill tone="neutral">Not needed to make calls</StatusPill>
      </div>
      <p className="text-sm font-semibold text-ink">{verdict}</p>
      {/* Kept for the record, and outgoing calls do not depend on it (D-692), so the detail
          is one tap away rather than a screen of statuses nobody acts on. */}
      <Disclosure variant="inline" headingLevel={3} title="Details" showLabel="Open" hideLabel="Close">
        <div className="space-y-3 pt-2">
          <p className="text-sm text-ink-muted">
            {registration.is_active
              ? "Kept on record. Outgoing calls do not depend on it."
              : "Not needed for outgoing calls, which depend on your verified business and the no-cold-calls pledge. Kept here for the record."}
          </p>
          <DltStatuses registration={registration} />
          <DltOnFile registration={registration} />
          {/* `term="registrar"` attaches the glossary's explanation to a word already in the
              sentence, without adding copy. */}
          <p className="text-xs text-ink-faint">
            We record this against the <Term id="dlt" term="registrar" /> on your behalf and
            cannot change what it says. There is no control here that sets your own status.
          </p>
        </div>
      </Disclosure>
    </section>
  );
}

function DltStatuses({ registration }: { registration: PeRegistration }) {
  const entity = peStatusCopy(registration.status);
  const link = tmLinkCopy(registration.tm_link_status);
  return (
    <dl className="space-y-3 text-sm">
      <div>
        <dt className="font-semibold text-ink">
          Your business as a{" "}
          <Term id="pe" />
          : {entity?.label ?? registration.status ?? "not filed"}
        </dt>
        <dd className="text-ink-muted">
          {entity?.next ??
            (registration.recorded
              ? "Ask us what this state means for your campaigns."
              : "Nothing has been filed with the registrar for your business yet. Ask us to start it.")}
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
              ? "Ask us where this authorisation stands."
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
        We do not hold a <Term id="tm" term="telemarketer" /> registration, so there is
        nothing for you to authorise against on the registrar&apos;s portal. Outgoing calls do
        not depend on it: they need your verified business and the no-cold-calls pledge.
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
    <dl className="divide-y divide-line">
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
