"use client";

import Link from "next/link";
import { use } from "react";
import { ArrowLeft, CheckCircle2, CircleDot, UserRound } from "lucide-react";

import {
  Card,
  EmptyState,
  NoticeBox,
  ProblemNotice,
  Skeleton,
} from "@/components/ui";
import { useTenant } from "@/lib/api/admin";
import { useTenantReadiness, type ReadinessRow } from "@/lib/api/adminAccount";
import { lookup } from "@/lib/lookup";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

/**
 * Everything standing between this client and their first call, on one screen.
 *
 * The client already had this view (`/c/<slug>/agreements`, `GET /v1/legal/readiness`).
 * An operator did not: the answer to "why can't they dial yet" was assembled by hand from
 * the KYC screen, the campaign review screen, the DND scrub screen, the credits screen and
 * the agreements the client may not have accepted — five screens, in an order you had to
 * know, and no way to be sure you had checked them all. This is the same list from the
 * same gate predicates (`admin/account_routes.py` for why it is not a second derivation).
 *
 * **WHOSE MOVE IS THE COLUMN THAT MATTERS.** An operator scanning this is deciding one
 * thing: do I act, or do I chase the client? So the rows are grouped by actor with ours
 * first, and the count of ours is the sentence at the top. It is not a re-sort of a
 * server-ranked list — this list has no ranking, only a set, and every row in it is
 * blocking.
 *
 * **NO REMEDY BUTTONS, DELIBERATELY.** Each row LINKS to the screen that clears it and
 * changes nothing itself. Every one of those gates is an audited write with its own
 * permission, its own confirmation and its own record an auditor will read (the KYC
 * recording, the first-campaign release, the DND scrub attestation); a shortcut here
 * would be a second door to a compliance decision, reached from a screen that was
 * designed to be read rather than acted on.
 */

/** The operator's word for whose move a row is, and how it is painted. */
const ACTOR_COPY = {
  calevate: {
    heading: "Ours to clear",
    blurb: "These are waiting on somebody at Calevate. Nothing the client does moves them.",
  },
  client: {
    heading: "Theirs to clear",
    blurb:
      "These are the client's own to do. We can explain them and cannot do them — the " +
      "wording below is the same sentence they are shown on their own screen.",
  },
} as const;

/**
 * Where a rule is cleared, when the console has a screen for it.
 *
 * A `Record<string, …>` read through a miss-tolerant lookup rather than a map over a
 * union: the rule vocabulary grows whenever a gate does, and a console that only knew
 * some of the names would drop the rows it did not recognise — which on this screen means
 * hiding a live blocker. A rule with no entry renders with its reason and its next step
 * and no link, which is strictly more than the operator had before.
 */
const RULE_SCREENS: Record<string, { href: (tenantId: string) => string; cta: string }> = {
  kyc_missing: { href: (id) => `/admin/tenants/${id}/kyc`, cta: "Record verification" },
  kyc_not_verified: { href: (id) => `/admin/tenants/${id}/kyc`, cta: "Record verification" },
  first_campaign_review_pending: {
    href: (id) => `/admin/tenants/${id}/first-campaign-review`,
    cta: "Review the first campaign",
  },
  first_campaign_review_rejected: {
    href: (id) => `/admin/tenants/${id}/first-campaign-review`,
    cta: "Review the first campaign",
  },
  national_dnd_scrub_missing: {
    href: (id) => `/admin/tenants/${id}/dnd-scrub`,
    cta: "Record the scrub",
  },
  // The cap is RAISED on the record page (`SpendCapPanel`), not on the spend breakdown,
  // which is where the month's rupees are attributed and where nothing can be changed.
  spend_cap: { href: (id) => `/admin/tenants/${id}`, cta: "Open the cap" },
  no_credits: { href: (id) => `/admin/tenants/${id}/credits`, cta: "Open credits" },
  account_closed: { href: (id) => `/admin/tenants/${id}/closure`, cta: "Open closure" },
  // The client's own DLT registration is recorded from `CampaignSetup` on the record page.
  pe_registration_missing: { href: (id) => `/admin/tenants/${id}`, cta: "Record registration" },
  pe_registration_not_active: {
    href: (id) => `/admin/tenants/${id}`,
    cta: "Record registration",
  },
  // The client's own notice to their access provider. Recorded from the record page,
  // where the rest of their outbound paperwork lives.
  autodialer_notice_missing: { href: (id) => `/admin/tenants/${id}`, cta: "Record the notice" },
  autodialer_notice_withdrawn: {
    href: (id) => `/admin/tenants/${id}`,
    cta: "Record the notice",
  },
  // DELIBERATELY ABSENT: `autodialer_notice_not_yet_effective`. The paperwork is already
  // correct and the only thing between the account and dialling is the date arriving —
  // there is nothing for an operator to open, and a button would invite re-recording a
  // notice that is fine.
  // OURS, not this client's: our telemarketer registration and the PE-TM chain are one
  // platform-wide fact, and the panel that records them is on the ops switchboard. The
  // link leaves the account deliberately — an operator hunting this on the client's
  // screens would not find it, because it is not about this client.
  tm_registration_missing: { href: () => "/admin/ops", cta: "Open the ops switchboard" },
  tm_link_not_active: { href: () => "/admin/ops", cta: "Open the ops switchboard" },
  big_red_switch: { href: () => "/admin/ops", cta: "Open the ops switchboard" },
  // DELIBERATELY ABSENT: `agreements_not_accepted`. Accepting is the account owner's own
  // act and there is no admin path to it — `VIEW_AS_WITHHELD_ACTS` withholds it from a
  // view-as session for the same reason. A button here would be a door around that.
};
function RowCard({ row, tenantId }: { row: ReadinessRow; tenantId: string }) {
  // `lookup`, never an index: `rule` is a bare wire string (the vocabulary grows with the
  // gates), and indexing a table with one walks the prototype chain — `constructor`
  // resolves to the `Object` function, which `??` does not treat as missing.
  const screen = lookup(RULE_SCREENS, row.rule);
  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-ink">{row.title}</p>
          {/* The gate's own sentence, verbatim. The client is reading this same string on
              their screen, so a support call is two people quoting one sentence. */}
          <p className="mt-1 text-sm text-ink-muted">{row.reason}</p>
          <p className="mt-2 text-sm text-ink">{row.next_step}</p>
          <p className="mt-2 font-mono text-[11px] text-ink-faint">{row.rule}</p>
        </div>
        {screen && (
          <Link
            href={screen.href(tenantId)}
            className="shrink-0 rounded-md border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink hover:bg-black/5 dark:hover:bg-white/5"
          >
            {screen.cta}
          </Link>
        )}
      </div>
    </li>
  );
}

export default function TenantReadinessPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenantQuery = useTenant(tenantId);
  const readiness = useTenantReadiness(tenantId);

  const rows = readiness.data?.rows ?? [];
  const ours = rows.filter((row) => row.actor === "calevate");
  const theirs = rows.filter((row) => row.actor === "client");

  /*
   * READINESS, DECLARED TO THE SCREEN ASSISTANT.
   *
   * THE RULE NAMES AND THE COUNTS, NOT THE PROSE. The rule names are the vocabulary the
   * gates, the client's screen and this console all share, so they are what an operator
   * asks about ("what is kyc_missing?"). The `reason` strings are deliberately withheld:
   * several of them interpolate an operator's own free text (a rejection note), which is
   * neither ours to forward nor useful to a model that cannot act on it — the same line
   * the health board draws.
   *
   * NO FIELDS: nothing on this screen is writable.
   */
  useCopilotSurface({
    route: "/admin/tenants/{id}/readiness",
    title: "Readiness",
    realm: "admin",
    fields: [],
    facts: [
      { key: "tenant_id", label: "Tenant id", value: tenantId },
      { key: "client", label: "Client", value: tenantQuery.data?.name ?? "could not be read" },
      {
        key: "may_operate",
        label: "Is anything blocking this account's outgoing calls",
        value: readiness.data
          ? readiness.data.may_operate
            ? "no, nothing"
            : "yes"
          : readiness.error
            ? "could not be read"
            : "still loading",
      },
      {
        key: "blocking_rules",
        label: "The blocking gates, by rule name",
        value: readiness.data ? rows.map((row) => row.rule).join(", ") || "none" : "not known",
      },
      {
        key: "ours",
        label: "How many of them are Calevate's to clear",
        value: readiness.data ? String(readiness.data.blocked_on_calevate) : "not known",
      },
    ],
    apply: noFill,
  });

  const name = tenantQuery.data?.name ?? "this client";

  return (
    <div className="max-w-3xl space-y-5">
      <div>
        <Link
          href={`/admin/tenants/${tenantId}`}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-strong hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          {name}
        </Link>
        <h1 className="mt-1 text-xl font-semibold text-ink">Before their first call</h1>
        <p className="text-sm text-ink-muted">
          Every account-level condition holding up this client&apos;s outgoing calls, with
          whose move each one is. This is the same list the client sees on their own
          readiness screen. A campaign&apos;s own blockers — its template, its number, its
          contact list — belong to that campaign and are not here.
        </p>
      </div>

      {readiness.isLoading ? (
        <Card>
          <Skeleton rows={4} />
        </Card>
      ) : readiness.error ? (
        /* A failed read must not render as "nothing is in the way": that sentence would
           send an operator to tell a client they are clear to dial. */
        <ProblemNotice error={readiness.error} onRetry={() => void readiness.refetch()} />
      ) : readiness.data?.may_operate ? (
        <NoticeBox tone="ok" icon={<CheckCircle2 className="h-4 w-4" />} title="Nothing is in the way">
          Every account-level gate is clear, so this client&apos;s outgoing calls are not
          being refused for any reason this screen can see. A campaign of theirs may still
          have its own blockers.
        </NoticeBox>
      ) : (
        <>
          <NoticeBox
            tone={ours.length ? "warn" : "neutral"}
            icon={<CircleDot className="h-4 w-4" />}
            title={
              ours.length
                ? `${ours.length} of ${rows.length} are ours to clear`
                : `All ${rows.length} are the client's to clear`
            }
          >
            {ours.length
              ? "Start with the list below: nothing the client does will move these."
              : "There is nothing for us to do here. Everything outstanding needs the client to act."}
          </NoticeBox>

          {([["calevate", ours], ["client", theirs]] as const).map(([actor, group]) =>
            group.length ? (
              <Card
                key={actor}
                title={ACTOR_COPY[actor].heading}
                bodyClassName="p-0"
              >
                <p className="px-5 pt-4 text-sm text-ink-muted">{ACTOR_COPY[actor].blurb}</p>
                <ul className="mt-2 divide-y divide-line border-t border-line">
                  {group.map((row) => (
                    <RowCard key={row.rule} row={row} tenantId={tenantId} />
                  ))}
                </ul>
              </Card>
            ) : null,
          )}
        </>
      )}

      {readiness.data && !readiness.data.may_operate && rows.length === 0 && (
        /* Unreachable by construction — `may_operate` is `not rows` on the server — and
           rendered rather than ignored, because the alternative is a blank screen under a
           heading that says something is wrong. */
        <EmptyState
          title="This account is blocked, but nothing was listed"
          hint="That is a disagreement inside the readiness answer itself. Report it before telling the client anything."
        />
      )}

      <p className="flex items-start gap-2 text-xs text-ink-faint">
        <UserRound aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        Reading this screen is recorded against you in the audit log, like every other read
        of one client&apos;s own state.
      </p>
    </div>
  );
}
