"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, ReceiptIndianRupee, ShieldCheck } from "lucide-react";

import {
  Card,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatCount,
  formatINR,
} from "@/components/ui";
import { useAdminAccess } from "@/app/admin/access";
import { useCaps } from "@/lib/api/caps";
import { useRecomputeSpendCap, viewAsSession } from "@/lib/api/admin";

import { FIELD, PrimaryButton } from "./controls";

/**
 * The spend cap that is stopping this client's outbound dialling, and the one control
 * that clears it — `POST /v1/ops/tenants/{id}/spend-cap/recompute`.
 *
 * ## Why this lives here and not on /admin/ops
 *
 * It was the fourth operator endpoint with no path in the console, and the only one on
 * that list that names a TENANT: the route puts the tenant in its path and binds its
 * step-up confirmation to that tenant id, precisely so a header captured for one client
 * cannot be replayed against another (`spend_cap_confirmation`, `ops/routes.py`). Putting
 * it on the platform screen would mean a picker — a uuid or a dropdown, with no client's
 * name, no ceiling and no counters beside it, which is `runbooks/calls-stopped.md` §2's
 * curl in a nicer font and with the same failure available: the right button pressed for
 * the wrong client. Here, the operator is already looking at the account they mean, at
 * the ceilings that decide the answer, having arrived from the directory row badged
 * "capped" or from the runbook, which now names this screen.
 *
 * ## Where the flag is read from, which is not the obvious place
 *
 * `TenantSummary.capped` is already in hand on this screen and is NOT the state this
 * control moves. It is `SELECT capped FROM spend_state LIMIT 1` with no month predicate
 * (`admin/service.py`), while the compliance gate asks `spend_capped()`, which treats a
 * row stamped with a CLOSED month as no cap at all. So a tenant capped in July shows
 * `capped: true` on the directory in August while nothing is actually refusing their
 * dials. `CapsOut.capped` comes from `read_spend_counters`, which applies the same month
 * test as the gate — so that is the flag rendered here, and the directory's is reported
 * as the disagreement it is when the two differ.
 *
 * Read through impersonation (`billing:read`, non-mutating, so D-22 allows it and there
 * is no admin-realm twin of this read), WRITTEN through the admin surface with the tenant
 * in the path — the same split as KYC and the first-campaign hold.
 *
 * ## No cap state, no control
 *
 * A failed caps read renders the failure and NOTHING ELSE. The ops screen's rule, applied
 * where it belongs: this button's whole subject is a flag, and a screen that offered it
 * over an unreadable one would let an operator "release" a client who was never capped
 * and report success to them.
 */
export function SpendCapPanel({
  tenantId,
  slug,
  directoryCapped,
}: {
  tenantId: string;
  slug: string;
  directoryCapped: boolean;
}) {
  const caps = useCaps(viewAsSession(slug));
  const recompute = useRecomputeSpendCap(tenantId);
  // `ops:manage`, not `admin:tenants` — this is the one control on this screen whose route
  // lives under `/v1/ops`, and only `superadmin` holds it (core/rbac.py). Gating it with
  // the panel's neighbours would offer an `operator` a button whose only outcome is a 403.
  const write = useAdminAccess("ops:manage", "recompute a client's spend cap");
  const [confirm, setConfirm] = useState("");

  const data = caps.data;
  const ready = confirm === "RECOMPUTE";

  return (
    <Card title="Spend cap">
      {caps.error ? (
        <>
          <p className="mb-3 text-sm text-ink-muted">
            The cap state could not be read, so nothing is offered here.
          </p>
          <ProblemNotice error={caps.error} onRetry={() => caps.refetch()} />
        </>
      ) : caps.isLoading || !data ? (
        <Skeleton rows={3} />
      ) : (
        <div className="space-y-4">
          <NoticeBox
            tone={data.capped ? "stop" : "ok"}
            icon={
              data.capped ? (
                <AlertTriangle className="h-5 w-5" />
              ) : (
                <ShieldCheck className="h-5 w-5" />
              )
            }
            title={
              data.capped
                ? "Outbound calling is STOPPED for this client by the spend cap"
                : "Not capped — the spend cap is not stopping this client"
            }
          >
            <p className="mt-1 text-xs">
              {data.capped
                ? "Every outbound call is refused by the spend cap. Inbound calls are unaffected — their receptionist keeps answering."
                : "The spend cap is not refusing their calls. Any other blocker on this account is listed above."}
            </p>
            {/* The two flags come from different predicates and CAN disagree; when they
                do, the reason is almost always a row still stamped with a closed billing
                month. Saying so turns a confusing screen into a diagnosis. */}
            {directoryCapped !== data.capped && (
              <p className="mt-2 text-xs">
                The client directory shows this account as{" "}
                {directoryCapped ? "capped" : "not capped"}, which disagrees. That badge
                reads the flag without checking its billing month; this one applies the
                same month test the compliance gate does. A row left over from a closed
                month is the usual cause, and the recompute below writes nothing for it.
              </p>
            )}
          </NoticeBox>

          {/* MONEY AS STRINGS. Every rupee field here is an exact decimal the API sent as
              text (hard rule 7); `formatINR` groups the digits and never parses them. */}
          <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <CapFact
              label={`Spent · ${data.month}`}
              value={formatINR(data.spend_used_inr)}
              note={`${data.minutes_used} minutes`}
            />
            <CapFact
              label="Ceiling in force"
              value={formatINR(data.effective_cap_spend_inr)}
              note={
                data.effective_cap_minutes === null
                  ? "no minute ceiling"
                  : `${formatCount(data.effective_cap_minutes)} minutes`
              }
            />
            <CapFact
              label="Our ceiling (the plan's)"
              value={formatINR(data.plan_cap_spend_inr)}
              note={
                data.plan_cap_minutes === null
                  ? "no minute ceiling"
                  : `${formatCount(data.plan_cap_minutes)} minutes`
              }
              edit={{
                href: `/admin/tenants/${tenantId}/commercials`,
                label: "Change on Commercials",
              }}
            />
            {/* Theirs, and only they can move it — the one line that decides whether this
                button can help at all. NO edit link, deliberately: this column is the
                client's own instruction to stop them at a figure, and the operator
                console has no route that writes it (see `billing/cap_routes.py`). A link
                here would promise a control that does not exist. */}
            <CapFact
              label="Their own ceiling"
              value={formatINR(data.client_cap_spend_inr)}
              note={
                data.client_cap_minutes === null
                  ? "no minute ceiling"
                  : `${formatCount(data.client_cap_minutes)} minutes`
              }
            />
          </dl>

          {recompute.error && <ProblemNotice error={recompute.error} />}

          {/* The SERVER's before/after and the numbers that decided it. `capped: true`
              after a recompute is the route working, so it is rendered as an explanation
              rather than as a failure. */}
          {recompute.data && (
            <NoticeBox
              tone={recompute.data.capped ? "warn" : "ok"}
              icon={<ReceiptIndianRupee className="h-5 w-5" />}
              title={
                recompute.data.capped
                  ? "Recomputed — this client is still capped"
                  : recompute.data.capped_before
                    ? "Recomputed — the cap is released"
                    : "Recomputed — this client was not capped and still is not"
              }
            >
              <p className="mt-1 text-xs">
                {recompute.data.capped
                  ? `They have spent ${formatINR(recompute.data.spend_used_inr)} of ${formatINR(
                      recompute.data.effective_cap_spend_inr,
                    )} this month, so the ceiling in force is still the smaller number. Raise it (or ask them to raise theirs, if the effective ceiling is the client's) and run this again.`
                  : "Their next dial is allowed. Campaigns pick up at the next dispatch tick."}
              </p>
            </NoticeBox>
          )}

          <form
            className="space-y-3"
            // A typed confirmation is the only gate and it is not a rule about an answer,
            // so there is nothing for `useFormValidation` to word. `noValidate` all the
            // same, so a rule added later cannot be answered by the browser.
            noValidate
            onSubmit={(e) => {
              e.preventDefault();
              recompute.mutate(undefined, { onSuccess: () => setConfirm("") });
            }}
          >
            {/* WHAT IT DOES AND WHAT IT CANNOT DO, before the click. The second half is
                what stops this being read as an "un-cap" button. */}
            <div className="flex gap-3 rounded-card border border-line bg-app p-4 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
              <div className="min-w-0">
                <p className="font-semibold text-ink">
                  This client only — it re-derives the flag, it does not lift the cap
                </p>
                <p className="mt-1 text-ink-muted">
                  It compares the minutes and spend ALREADY metered this month against the
                  ceiling in force now. A client still over that ceiling stays stopped, so
                  raise the ceiling first if that is the fix — this is the second half of
                  that job, not a substitute for it. It never moves a counter, never
                  touches another client, and never affects inbound calls.
                </p>
                <p className="mt-1 text-xs text-ink-faint">
                  Recorded in the audit log against your admin account, and confirmed
                  against this client only.
                </p>
              </div>
            </div>

            <label className="block">
              <span className={FIELD_LABEL}>Type RECOMPUTE to confirm</span>
              <input
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                disabled={!write.allowed}
                placeholder="RECOMPUTE"
                className={`${FIELD} mt-1 block w-full font-mono`}
              />
            </label>

            <PrimaryButton
              type="submit"
              disabled={!write.allowed || !ready || recompute.isPending}
            >
              {recompute.isPending ? "Recomputing…" : "Recompute this client's spend cap"}
            </PrimaryButton>

            <RestrictionNote reason={write.reason} />
          </form>
        </div>
      )}
    </Card>
  );
}

/** One cap figure with the minute ceiling that goes with it — rupees and minutes are two
 * ceilings, and `LEAST` is taken over each independently. */
function CapFact({
  label,
  value,
  note,
  edit,
}: {
  label: string;
  value: string;
  note: string;
  /**
   * Where an operator changes this number, when it is one they may change.
   *
   * The panel already tells them to "raise the ceiling first if that is the fix" and
   * never said WHERE — a dead end in the middle of the instruction. Only OUR ceiling
   * gets one: the client's own is theirs to move (`PUT /v1/billing/caps` is client-realm
   * and stays that way), and offering a link there would promise a control this console
   * does not have.
   */
  edit?: { href: string; label: string };
}) {
  return (
    <div className="rounded-card border border-line bg-surface p-4">
      <dt className="text-xs uppercase tracking-wide text-ink-faint">{label}</dt>
      <dd className="mt-0.5 text-lg font-semibold tabular-nums text-ink">{value}</dd>
      <dd className="mt-0.5 text-xs text-ink-muted">{note}</dd>
      {edit && (
        <dd className="mt-1.5">
          <Link href={edit.href} className="text-xs font-medium text-brand hover:underline">
            {edit.label}
          </Link>
        </dd>
      )}
    </div>
  );
}
