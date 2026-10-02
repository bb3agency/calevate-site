"use client";

/**
 * THE CLIENT'S PHONE NUMBERS — record one, say which agent answers it, and (Model A only)
 * buy or release one.
 *
 * Primary job, in one sentence: *get this client's number answering an agent.*
 *
 * ## Why the recording form moved here (D-576, OURS-2)
 *
 * It used to live only in `CampaignSetup` — a panel headed "the prerequisites every client
 * campaign stalls on", with the series selector preselected to **160**, a DLT class. An
 * operator onboarding an INBOUND-ONLY client was therefore sent to a CAMPAIGN screen to
 * perform the one step that makes the phone ring, with an outbound-shaped default already
 * chosen for them. Recording a client's connection and attaching it to an agent are the
 * same job, and this is the screen named after it (UX §5: group by what the operator is
 * trying to do, never by API resource; §9 move 4: give it its own route).
 *
 * Nothing was deleted from the campaign screen that a campaign operator still needs: the
 * numbers list and the registrar's `Mark registered` action stay there, because a DLT
 * verdict is registrar paperwork and belongs beside the templates. What left is the second
 * copy of one form — two spellings of one fact is a defect even when both work (UX §5).
 *
 * ## Hierarchy (UX §1)
 *
 * The list is the screen: each row is where an operator says who answers a number, and a
 * number nobody answers says so on its own row. Recording a new number is the header's
 * action and opens in a drawer (the form keeps the screen's only `PRIMARY_BUTTON_LG`).
 * Buying is disclosed at the bottom — it is Model A, and this deployment holds no reseller
 * authorisation, so every call on that path refuses by name until one is recorded.
 *
 * ## Three things this screen must not get wrong
 *
 * 1. **A purchase spends real money on a recurring commitment and cannot be undone by
 *    retrying.** Confirmation states the monthly cost; `retry: false` on the mutation.
 * 2. **The going-live gate is a legal fact** and the screen prints the server's own
 *    refusal rather than composing a cheerier one.
 * 3. **`agent_id` and `engine_linked` are the two facts between a recorded number and a
 *    ringing phone.** Every row says where it stands on both.
 */

import { useState } from "react";
import { Plus, Search } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { ConfirmDialog } from "@/components/confirmDialog";
import { Drawer } from "@/components/console/drawer";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { useFormValidation } from "@/components/formValidation";
import {
  Disclosure,
  FIELD,
  FIELD_HINT,
  FIELD_INLINE,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  PRIMARY_BUTTON_LG,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
  formatPhone,
} from "@/components/ui";
import { useProvisionNumber, useTenant, useTenantAgents } from "@/lib/api/admin";
import {
  useAvailableNumbers,
  useBuyNumber,
  useReleaseNumber,
  useTenantNumberCosts,
  type AvailableNumber,
  type TenantNumberCost,
} from "@/lib/api/numbers";

import { NumberRow } from "./NumberRow";

type Series = "140" | "160" | "standard";

/**
 * A search result WITH a quoted monthly price — the only thing this screen will buy.
 *
 * ⚠ **THE PURCHASE USED TO SEND `monthly_price_usd ?? "0"`.** The button above is
 * disabled without a price, so the fallback was unreachable — and it was a FABRICATED
 * FIGURE on a money field sitting one edit away from being reached, which would have
 * recorded a rental that bills every month at a cost of nothing. Hard rule 7 is about the
 * numbers we record, and "the guard above happens to stop it" is the weakest form that
 * rule can take. Narrowing the state instead makes the whole class a type error: there is
 * no longer any value `buying` can hold for which a price has to be invented.
 */
type PricedNumber = AvailableNumber & { monthly_price_usd: string };

function isPriced(offer: AvailableNumber): offer is PricedNumber {
  return typeof offer.monthly_price_usd === "string" && offer.monthly_price_usd !== "";
}

export function NumbersScreen({ tenantId }: { tenantId: string }) {
  const tenant = useTenant(tenantId);
  const held = useTenantNumberCosts(tenantId);
  // The agents are read through impersonation, the same D-22 split every admin tenant
  // screen uses. The slug arrives with the tenant, so the query is disabled until it does.
  const agents = useTenantAgents(tenant.data ? tenant.data.slug : "");
  const write = useAdminAccess("admin:tenants", "record, attach or release a number");

  const record = useProvisionNumber(tenantId);
  const [e164, setE164] = useState("");
  const numberValid = useFormValidation();
  // **`standard`, NOT `160`.** The series is fixed when the operator issues the number and
  // the server refuses a mismatch by name; what a default decides is which mistake is easy.
  // A client's own published business line — the inbound case this platform's first client
  // is — is `standard`, and a 140/160 preselect quietly proposes a regulated class to
  // somebody recording an ordinary landline.
  const [series, setSeries] = useState<Series>("standard");

  const [country, setCountry] = useState<"IN" | "US">("IN");
  const [pattern, setPattern] = useState("");
  const [searching, setSearching] = useState(false);
  const offers = useAvailableNumbers(country, pattern, searching);

  const buy = useBuyNumber(tenantId);
  const release = useReleaseNumber(tenantId);
  const [buying, setBuying] = useState<PricedNumber | null>(null);
  const [releasing, setReleasing] = useState<TenantNumberCost | null>(null);
  const [recording, setRecording] = useState(false);

  const recordAction = (
    <button type="button" className={PRIMARY_BUTTON} disabled={!write.allowed} onClick={() => setRecording(true)}>
      <Plus aria-hidden className="h-4 w-4" />
      Record a number
    </button>
  );

  return (
    <div className="space-y-5">
      <PageHeader
        title="Numbers"
        description="Record the client's own connection, then choose which agent answers it."
        actions={recordAction}
      />

      <RestrictionNote reason={write.reason} />

      {held.error ? (
        <ProblemNotice error={held.error} onRetry={() => held.refetch()} />
      ) : held.isLoading || !held.data ? (
        <Skeleton rows={3} />
      ) : held.data.length === 0 ? (
        <EmptyState
          message="No numbers on this account. Nothing can make their phone ring until one is on file."
          action={recordAction}
        />
      ) : (
        <ul className="divide-y divide-line rounded-card border border-line bg-surface">
          {held.data.map((number) => (
            <NumberRow
              key={number.id}
              number={number}
              tenantId={tenantId}
              agents={agents.data}
              agentsFailed={Boolean(agents.error)}
              canWrite={write.allowed}
              onRelease={() => setReleasing(number)}
            />
          ))}
        </ul>
      )}

      {/* Disclosed, with the fact in the closed state: this path refuses by name on this
          deployment until a reseller authorisation is recorded (Model A). */}
      <Disclosure
        title="Buy a number"
        subtitle="Model A only: refused on this deployment until a reseller authorisation is recorded."
      >
        <div className="space-y-4 px-4 pb-4 sm:px-6">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className={FIELD_LABEL}>Country</span>
              <select
                className={FIELD_INLINE}
                value={country}
                onChange={(ev) => {
                  setCountry(ev.target.value as "IN" | "US");
                  setSearching(false);
                }}
              >
                <option value="IN">India</option>
                <option value="US">United States</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              {/* THE VENDOR'S OWN UNIT — "3-character prefix", not a regex and not a
                  city. Labelled in their terms so an operator typing "Hyderabad" is not
                  puzzled by an empty result. */}
              <span className={FIELD_LABEL}>Starts with (optional, up to 3 digits)</span>
              <input
                className={FIELD_INLINE}
                value={pattern}
                maxLength={8}
                placeholder="80"
                onChange={(ev) => {
                  setPattern(ev.target.value.trim());
                  setSearching(false);
                }}
              />
            </label>
            <button
              type="button"
              className={SECONDARY_BUTTON}
              disabled={!write.allowed || offers.isFetching}
              onClick={() => setSearching(true)}
            >
              <Search aria-hidden className="h-3.5 w-3.5" />
              {offers.isFetching ? "Searching…" : "Search"}
            </button>
          </div>

          {offers.error && <ProblemNotice error={offers.error} />}
          {buy.error && <ProblemNotice error={buy.error} />}

          {searching &&
            !offers.error &&
            (offers.isLoading || !offers.data ? (
              <Skeleton rows={3} />
            ) : offers.data.length === 0 ? (
              <p className="text-sm text-ink-muted">
                The voice platform has nothing available matching that. Try a different
                prefix — this is their inventory today, not a permanent answer.
              </p>
            ) : (
              <ul className="divide-y divide-line">
                {offers.data.map((offer) => (
                  <li key={offer.e164} className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
                    <span className="font-mono text-ink">{formatPhone(offer.e164)}</span>
                    {offer.region && <span className="text-ink-muted">{offer.region}</span>}
                    {offer.provider && <span className="text-xs text-ink-muted">{offer.provider}</span>}
                    <span className="text-ink-muted">
                      {/* The vendor's own figure, in the vendor's own currency. */}
                      {offer.monthly_price_usd
                        ? `$${offer.monthly_price_usd} / month`
                        : "no price quoted"}
                    </span>
                    <span className="ml-auto">
                      <button
                        type="button"
                        className={SECONDARY_BUTTON}
                        disabled={!write.allowed || !offer.monthly_price_usd || buy.isPending}
                        onClick={() => {
                          // The type, not the disabled attribute, is what keeps an
                          // unpriced number out of the purchase — see `PricedNumber`.
                          if (isPriced(offer)) setBuying(offer);
                        }}
                      >
                        Buy
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            ))}
          {searching && offers.data?.some((offer) => !offer.monthly_price_usd) && (
            <p className="text-xs text-ink-muted">
              A number with no quoted price cannot be bought: its monthly cost would never
              be recorded, and an unbilled monthly cost is a leak nobody sees.
            </p>
          )}
        </div>
      </Disclosure>

      <Drawer
        open={recording}
        onClose={() => setRecording(false)}
        title="Record a number"
        description="A connection this client already holds in their own name."
      >
        <form
          className="space-y-4"
          noValidate
          onSubmit={numberValid.onSubmit(() => {
            record.mutate(
              { e164, series },
              {
                onSuccess: () => {
                  setE164("");
                  setRecording(false);
                },
              },
            );
          })}
        >
          {/* The legal posture (Model B), stated where the number is entered. */}
          <p className="text-sm text-ink-muted">
            Calevate does not buy or resell this number: the client is the subscriber of
            record on their own operator account and issues us revocable credentials for
            it. Recording it here is what lets an agent be put on it.
          </p>
          {record.error && <ProblemNotice error={record.error} />}
          <label className="block">
            <span className={FIELD_LABEL}>The number, with its country code</span>
            <input
              {...numberValid.field("e164", "Enter the number to record.")}
              required
              minLength={8}
              value={e164}
              disabled={!write.allowed}
              onChange={(ev) => setE164(ev.target.value)}
              placeholder="+918041234567"
              className={`font-mono ${FIELD}`}
            />
          </label>
          {numberValid.error("e164")}
          <div>
            <label className="block">
              <span className={FIELD_LABEL}>Series</span>
              <select
                className={FIELD}
                value={series}
                disabled={!write.allowed}
                onChange={(ev) => setSeries(ev.target.value as Series)}
              >
                <option value="standard">standard — an ordinary business line</option>
                <option value="160">160 — service / transactional</option>
                <option value="140">140 — telemarketing / promotional</option>
              </select>
            </label>
            <div className={`${FIELD_HINT} flex items-start gap-1`}>
              <span>It must match the number&apos;s prefix; the server refuses a mismatch.</span>
              <InfoTip label="Series">
                The series is fixed when the operator issues the number, and the campaign
                launch gate matches it against a campaign&apos;s classification — a number
                filed under the wrong one dials the wrong traffic. The server checks it
                against the number&apos;s own prefix and refuses a disagreement rather than
                correcting it.
              </InfoTip>
            </div>
          </div>
          <button
            type="submit"
            className={`${PRIMARY_BUTTON_LG} max-sm:w-full max-sm:justify-center`}
            disabled={!write.allowed || record.isPending}
          >
            {record.isPending ? "Recording…" : "Record this number"}
          </button>
        </form>
      </Drawer>

      {buying && (
        <ConfirmDialog
          title={`Buy ${formatPhone(buying.e164)} for ${tenant.data?.name ?? "this client"}?`}
          confirmLabel="Buy the number"
          pendingLabel="Buying…"
          pending={buy.isPending}
          error={buy.error}
          onCancel={() => setBuying(null)}
          onConfirm={() =>
            buy.mutate(
              {
                e164: buying.e164,
                country,
                provider: buying.provider,
                monthly_price_usd: buying.monthly_price_usd,
              },
              { onSuccess: () => setBuying(null) },
            )
          }
        >
          <p>
            This charges the platform account now and{" "}
            <strong>${buying.monthly_price_usd} every month</strong> until the number is
            released. It cannot be undone by trying again — a repeat buys a second number
            and starts a second rental.
          </p>
        </ConfirmDialog>
      )}

      {releasing && (
        <ConfirmDialog
          title={`Give ${formatPhone(releasing.e164)} back to the voice platform?`}
          confirmLabel="Release the number"
          pendingLabel="Releasing…"
          pending={release.isPending}
          error={release.error}
          onCancel={() => setReleasing(null)}
          onConfirm={() => release.mutate(releasing.id, { onSuccess: () => setReleasing(null) })}
        >
          <p>
            Any agent answering it stops, the monthly charge stops, and the number goes
            back to the operator — it is not held for us and may not be available again.
            Anything still forwarding to it will reach nobody.
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}