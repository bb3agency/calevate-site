"use client";

import Link from "next/link";
import { CheckCircle2, UserRound } from "lucide-react";

import {
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
} from "@/components/ui";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { useTenant } from "@/lib/api/admin";
import { useTenantReadiness, type ReadinessRow } from "@/lib/api/adminAccount";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

import { StatusPill } from "@/components/admin/kit";

/** Where a readiness rule is cleared in this console, and what the link says. */
export type RuleScreen = { href: (tenantId: string) => string; cta: string };

const ACTOR_COPY = {
  calevate: {
    heading: "Ours to clear",
    blurb: "Waiting on us. Nothing the client does moves these.",
  },
  client: {
    heading: "Theirs to clear",
    blurb: "The client's own to do. We can explain them, not do them.",
  },
} as const;

/**
 * Everything standing between this client and outbound calling, grouped by whose move it
 * is — the one decision an operator makes here: act, or chase the client.
 *
 * Read-only by design. Each row LINKS to the screen that clears it, because every gate is
 * an audited write with its own permission and confirmation; a shortcut here would be a
 * second door to a compliance decision. The first row that is ours carries the screen's
 * one primary action: it is the next thing to do.
 *
 * Not a `Checklist`: the server returns only the BLOCKERS, never the cleared gates, so a
 * "0 of 3 done" bar would describe a list the server never sent.
 */
export function ReadinessScreen({
  tenantId,
  ruleScreens,
}: {
  tenantId: string;
  ruleScreens: Record<string, RuleScreen>;
}) {
  const tenantQuery = useTenant(tenantId);
  const readiness = useTenantReadiness(tenantId);

  const rows = readiness.data?.rows ?? [];
  const ours = rows.filter((row) => row.actor === "calevate");
  const theirs = rows.filter((row) => row.actor === "client");
  const firstOurs = ours.find((row) => lookup(ruleScreens, row.rule) !== undefined);

  /*
   * The rule names and the counts, not the prose: several `reason` strings interpolate an
   * operator's own free text (a rejection note), which is not ours to forward to a model.
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

  const blocked = readiness.data !== undefined && !readiness.data.may_operate && rows.length > 0;

  return (
    <div className="max-w-4xl space-y-10">
      <PageHeader
        title="Before their first call"
        status={
          blocked ? (
            <StatusPill tone={ours.length ? "warn" : "neutral"}>
              {ours.length
                ? `${ours.length} of ${rows.length} are ours to clear`
                : `All ${rows.length} are the client's to clear`}
            </StatusPill>
          ) : null
        }
        description={
          <>
            Account-level conditions holding up outgoing calls, and whose move each is.{" "}
            <InfoTip label="this list">
              <p>
                This is the same list the client sees on their own readiness screen, with
                the same sentences, so a support call is two people quoting one line.
              </p>
              <p>
                A campaign&apos;s own blockers — its template, its number, its contact list
                — belong to that campaign and are not here.
              </p>
            </InfoTip>
          </>
        }
      />

      {readiness.isLoading ? (
        <Skeleton rows={4} />
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
      ) : rows.length === 0 ? (
        /* Unreachable by construction (`may_operate` is `not rows` on the server), and
           rendered rather than ignored so the screen is never blank under a blocked verdict. */
        <EmptyState
          message="This account is blocked, but nothing was listed. That is a disagreement inside the readiness answer itself — report it before telling the client anything."
        />
      ) : (
        ([["calevate", ours], ["client", theirs]] as const).map(([actor, group]) =>
          group.length ? (
            <section key={actor} aria-labelledby={`readiness-${actor}`}>
              <h3 id={`readiness-${actor}`} className="text-body font-semibold text-ink">
                {ACTOR_COPY[actor].heading}
              </h3>
              <p className="mt-0.5 text-body text-ink-muted">{ACTOR_COPY[actor].blurb}</p>
              <ul className="mt-3 divide-y divide-line border-y border-line">
                {group.map((row) => (
                  <RuleRow
                    key={row.rule}
                    row={row}
                    tenantId={tenantId}
                    screen={lookup(ruleScreens, row.rule)}
                    primary={row === firstOurs}
                  />
                ))}
              </ul>
            </section>
          ) : null,
        )
      )}

      <p className="flex items-start gap-2 text-meta text-ink-muted">
        <UserRound aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        Reading this screen is recorded against you in the audit log, like every other read
        of one client&apos;s own state.
      </p>
    </div>
  );
}

function RuleRow({
  row,
  tenantId,
  screen,
  primary,
}: {
  row: ReadinessRow;
  tenantId: string;
  screen: RuleScreen | undefined;
  primary: boolean;
}) {
  return (
    <li className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
      <div className="min-w-0">
        <p className="font-medium text-ink">{row.title}</p>
        {/* The gate's own sentence, verbatim: the client is reading this same string. */}
        <p className="mt-1 text-body text-ink-muted">{row.reason}</p>
        <p className="mt-1.5 text-body text-ink">{row.next_step}</p>
        <p className="mt-1.5 break-all font-mono text-meta text-ink-muted">{row.rule}</p>
      </div>
      {screen && (
        <Link
          href={screen.href(tenantId)}
          className={`${primary ? PRIMARY_BUTTON_SM : SECONDARY_BUTTON_SM} w-full shrink-0 justify-center sm:w-auto`}
        >
          {screen.cta}
        </Link>
      )}
    </li>
  );
}
