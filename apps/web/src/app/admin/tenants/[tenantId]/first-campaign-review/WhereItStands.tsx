"use client";

import Link from "next/link";
import type { ComponentType } from "react";
import { Clock, Eye, Info, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";

import { NoticeBox, formatIST, type NoticeTone } from "@/components/ui";
import {
  firstCampaignState,
  type FirstCampaignHold,
  type FirstCampaignState,
} from "@/lib/api/firstCampaign";
import { viewAsHref } from "@/lib/api/session";

import { TonePill } from "../tonePill";

/**
 * The five states in the operator's words, with the tone and icon the client's own
 * `/c/[slug]/campaign-review` uses for each. The two screens are read side by side on a
 * support call, so a red box for the client and an amber one for the operator would be the
 * two realms contradicting each other about a compliance gate. Keyed on the STATE, not the
 * tone, because `warn` covers both "queued" and "held on a rule we cannot name".
 */
const OPERATOR_VERDICTS: Record<
  FirstCampaignState,
  { headline: string; pill: string; tone: NoticeTone; icon: ComponentType<{ className?: string }> }
> = {
  pending: {
    headline: "Held — nobody has reviewed this account yet.",
    pill: "Held · not reviewed",
    tone: "warn",
    icon: Clock,
  },
  rejected: {
    headline: "Held — a reviewer refused this account.",
    pill: "Held · refused",
    tone: "stop",
    icon: XCircle,
  },
  held_unknown: {
    headline: "Held on a rule this console does not recognise.",
    pill: "Held",
    tone: "warn",
    icon: ShieldAlert,
  },
  released: {
    headline: "Released — cleared for campaign calling.",
    pill: "Released",
    tone: "ok",
    icon: ShieldCheck,
  },
  never_applied: {
    headline: "This rule does not apply to this account.",
    pill: "Not applicable",
    tone: "neutral",
    icon: Info,
  },
};

/** The header's one-glance state, from the same reading as the panel below it. */
export function HoldPill({ hold }: { hold: FirstCampaignHold }) {
  const verdict = OPERATOR_VERDICTS[firstCampaignState(hold)];
  return <TonePill tone={verdict.tone}>{verdict.pill}</TonePill>;
}

/**
 * Where the account stands right now — the GATE's answer, never a re-derived one. `held`
 * comes from the predicate that refuses the launch and the dispatch tick, and
 * `firstCampaignState` is shared with the client's screen, including `never_applied`: a
 * managed account the rule exempts, which is NOT a released one.
 */
export function WhereItStands({
  hold,
  tenantName,
  slug,
}: {
  hold: FirstCampaignHold;
  tenantName: string;
  slug: string;
}) {
  const state = firstCampaignState(hold);
  const verdict = OPERATOR_VERDICTS[state];
  const Icon = verdict.icon;

  return (
    <NoticeBox tone={verdict.tone} icon={<Icon className="h-5 w-5" />} title={verdict.headline}>
      {state === "never_applied" && (
        <p className="mt-1 text-xs opacity-90">
          The hold is scoped to the self-serve and trial motions. {tenantName} was onboarded
          by a person, so no campaign of theirs is held by this rule — recording a decision
          here is possible and changes nothing about their calling.
        </p>
      )}
      {state === "held_unknown" && hold.reason && (
        <p className="mt-1 text-xs opacity-90">{hold.reason}</p>
      )}

      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
        <div>
          <dt className="opacity-70">Decision on file</dt>
          <dd className="mt-0.5 font-medium">{hold.status ?? "none — nobody has looked"}</dd>
        </div>
        <div>
          <dt className="opacity-70">Decided</dt>
          <dd className="mt-0.5 font-medium">
            {hold.decided_at ? `${formatIST(hold.decided_at)} IST` : "—"}
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="opacity-70">
            Note on file
            {hold.status === "rejected" && " — this is what the client is reading now"}
          </dt>
          <dd className="mt-0.5 whitespace-pre-wrap font-medium">{hold.decision_note ?? "—"}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="opacity-70">Campaign read</dt>
          {/* The id, not a name: it is evidence, not mechanism, and the campaign may since
              have been deleted (ON DELETE SET NULL, on purpose). */}
          <dd className="mt-0.5 break-all font-mono">{hold.reviewed_campaign_id ?? "—"}</dd>
        </div>
      </dl>

      {/* The view-as marker, not a bare client-realm link: without it the client shell
          would build a client session this operator does not have (lib/api/session.tsx). */}
      <p className="mt-3 text-xs opacity-80">
        <Link
          href={viewAsHref(slug, "/campaign-review")}
          className="inline-flex items-center gap-1 rounded-sm font-medium underline touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2"
          title="Read-only. Every page view is recorded in the audit log."
        >
          <Eye aria-hidden className="h-3.5 w-3.5" />
          What the client sees (read-only)
        </Link>{" "}
        — their own screen renders the note above verbatim.
      </p>
    </NoticeBox>
  );
}
