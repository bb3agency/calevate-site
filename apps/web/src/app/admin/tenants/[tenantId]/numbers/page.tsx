"use client";

/**
 * BUYING A PHONE NUMBER FOR A CLIENT — the operator screen for D-537.
 *
 * ## The three things this screen has to get right, in order of what they cost
 *
 * 1. **A PURCHASE SPENDS REAL MONEY ON A RECURRING COMMITMENT AND CANNOT BE UNDONE BY
 *    RETRYING.** The vendor's buy endpoint takes no idempotency key, so a repeat buys a
 *    second number and starts a second monthly rental. So: a confirmation that states the
 *    monthly cost rather than restating the command, `retry: false` on the mutation, and
 *    a button that is disabled the instant it is pressed. A double-click here is a bill.
 * 2. **THE GOING-LIVE GATE IS A LEGAL FACT AND MUST READ AS ONE.** Until a written
 *    reseller authorisation is recorded, every call here refuses with
 *    `number_resale_not_authorized`, and the server's own remediation says what is
 *    missing. The screen prints that refusal rather than composing a cheerier one — an
 *    operator who reads "not configured" goes looking for a setting, and there is no
 *    setting that fixes this.
 * 3. **`engine_linked` IS THE DIFFERENCE BETWEEN A NUMBER THAT RINGS AND ONE THAT DOES
 *    NOT.** It is False while the voice platform has no handle for the number, and an
 *    agent published to answer it will not — silently, with a success message. Every row
 *    says so, and the fix is on the same row.
 *
 * ## Prices are the vendor's own, in USD, and are never converted here
 *
 * The rupee is struck once, monthly, when the rental is metered, at that month's published
 * rate. A conversion in the browser would put a second exchange rate on a screen that
 * would not match the ledger.
 *
 * ## The search does not run on mount
 *
 * It is a vendor round trip on a rate-limited account. An operator opening a client must
 * not spend that budget on a question they did not ask.
 */

import Link from "next/link";
import { use, useState } from "react";
import { ArrowLeft, PhoneOff, Search } from "lucide-react";

import { useAdminAccess } from "@/app/admin/access";
import { ConfirmDialog } from "@/components/confirmDialog";
import {
  Card,
  EmptyState,
  FIELD,
  FIELD_LABEL,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON,
  Skeleton,
} from "@/components/ui";
import { useTenant } from "@/lib/api/admin";
import {
  useAvailableNumbers,
  useBuyNumber,
  useReleaseNumber,
  useSetNumberEngineRef,
  useTenantNumberCosts,
  type AvailableNumber,
  type TenantNumberCost,
} from "@/lib/api/numbers";

export default function TenantNumbersPage({
  params,
}: {
  params: Promise<{ tenantId: string }>;
}) {
  const { tenantId } = use(params);
  const tenant = useTenant(tenantId);
  const held = useTenantNumberCosts(tenantId);
  const write = useAdminAccess("admin:tenants", "buy or release a number for this client");

  const [country, setCountry] = useState<"IN" | "US">("IN");
  const [pattern, setPattern] = useState("");
  const [searching, setSearching] = useState(false);
  const offers = useAvailableNumbers(country, pattern, searching);

  const buy = useBuyNumber(tenantId);
  const release = useReleaseNumber(tenantId);
  const [buying, setBuying] = useState<AvailableNumber | null>(null);
  const [releasing, setReleasing] = useState<TenantNumberCost | null>(null);

  return (
    <div className="space-y-5">
      <Link
        href={`/admin/tenants/${tenantId}`}
        className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink"
      >
        <ArrowLeft className="h-4 w-4" />
        {tenant.data?.name ?? "Back to the client"}
      </Link>

      <div>
        <h1 className="text-lg font-semibold text-ink">Phone numbers</h1>
        <p className="mt-1 text-sm text-ink-muted">
          A number bought here is one this client forwards their own published number to.
          It carries a monthly rental we pay from the moment it is bought until it is
          released, and buying is not reversible by trying again.
        </p>
      </div>

      <RestrictionNote reason={write.reason} />

      <Card title="Numbers on this account">
        {held.error ? (
          <div className="p-4">
            <ProblemNotice error={held.error} onRetry={() => held.refetch()} />
          </div>
        ) : held.isLoading || !held.data ? (
          <div className="p-4">
            <Skeleton rows={3} />
          </div>
        ) : held.data.length === 0 ? (
          <EmptyState
            title="No numbers on this account"
            hint="Search below to buy one, or record a connection the client already holds from the client's main screen."
          />
        ) : (
          <ul className="divide-y divide-line">
            {held.data.map((number) => (
              <NumberRow
                key={number.id}
                number={number}
                tenantId={tenantId}
                canWrite={write.allowed}
                onRelease={() => setReleasing(number)}
              />
            ))}
          </ul>
        )}
      </Card>

      <Card title="Buy a number">
        <div className="space-y-4 p-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className={FIELD_LABEL}>Country</span>
              <select
                className={FIELD}
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
                className={FIELD}
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
              <Search className="mr-1.5 inline h-3.5 w-3.5" />
              {offers.isFetching ? "Searching…" : "Search"}
            </button>
          </div>

          {offers.error && <ProblemNotice error={offers.error} />}
          {buy.error && <ProblemNotice error={buy.error} />}

          {searching && !offers.error && (
            offers.isLoading || !offers.data ? (
              <Skeleton rows={3} />
            ) : offers.data.length === 0 ? (
              <p className="text-sm text-ink-muted">
                The voice platform has nothing available matching that. Try a different
                prefix — this is their inventory today, not a permanent answer.
              </p>
            ) : (
              <ul className="space-y-2">
                {offers.data.map((offer) => (
                  <li
                    key={offer.e164}
                    className="flex flex-wrap items-center gap-3 rounded-card border border-line p-3 text-sm"
                  >
                    <span className="font-mono text-ink">{offer.e164}</span>
                    {offer.region && <span className="text-ink-muted">{offer.region}</span>}
                    {offer.provider && (
                      <span className="rounded bg-brand-soft px-1.5 py-0.5 text-xs font-medium text-brand-strong">
                        {offer.provider}
                      </span>
                    )}
                    <span className="text-ink-muted">
                      {/* The vendor's own figure, in the vendor's own currency. Not
                          converted here — see the module note. */}
                      {offer.monthly_price_usd
                        ? `$${offer.monthly_price_usd} / month`
                        : "no price quoted"}
                    </span>
                    <span className="ml-auto">
                      <button
              type="button"
              className={PRIMARY_BUTTON}
                        disabled={!write.allowed || !offer.monthly_price_usd || buy.isPending}
                        onClick={() => setBuying(offer)}
                      >
                        Buy
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            )
          )}
          {searching && offers.data?.some((offer) => !offer.monthly_price_usd) && (
            <p className="text-xs text-ink-muted">
              A number with no quoted price cannot be bought: its monthly cost would never
              be recorded, and an unbilled monthly cost is a leak nobody sees.
            </p>
          )}
        </div>
      </Card>

      {buying && (
        <ConfirmDialog
          title={`Buy ${buying.e164} for ${tenant.data?.name ?? "this client"}?`}
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
                monthly_price_usd: buying.monthly_price_usd ?? "0",
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
          title={`Give ${releasing.e164} back to the voice platform?`}
          confirmLabel="Release the number"
          pendingLabel="Releasing…"
          pending={release.isPending}
          error={release.error}
          onCancel={() => setReleasing(null)}
          onConfirm={() =>
            release.mutate(releasing.id, { onSuccess: () => setReleasing(null) })
          }
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

/**
 * One held number, and the one action its state actually needs.
 *
 * `engine_linked` is the row's most important field even though it reads like plumbing: a
 * number without the voice platform's handle cannot be answered, and the publish that was
 * supposed to make it answer reported success. So the input to fix it is ON THE ROW rather
 * than behind a menu.
 */
function NumberRow({
  number,
  tenantId,
  canWrite,
  onRelease,
}: {
  number: TenantNumberCost;
  tenantId: string;
  canWrite: boolean;
  onRelease: () => void;
}) {
  const link = useSetNumberEngineRef(tenantId);
  const [ref, setRef] = useState("");

  return (
    <li className="space-y-2 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-ink">{number.e164}</span>
        <span className="rounded bg-brand-soft px-1.5 py-0.5 text-xs font-medium text-brand-strong">
          {number.series}
        </span>
        <span className="text-xs text-ink-muted">
          {number.engine_owned ? "we bought it" : "the client's own connection"}
        </span>
        {number.engine_owned && number.monthly_rental_usd && (
          <span className="text-xs text-ink-muted">${number.monthly_rental_usd} / month</span>
        )}
        {number.released && (
          <span className="text-xs text-ink-muted">released — no longer charged</span>
        )}
        {number.engine_owned && !number.released && canWrite && (
          <span className="ml-auto">
            <button type="button" className={SECONDARY_BUTTON} onClick={onRelease}>
              <PhoneOff className="mr-1.5 inline h-3.5 w-3.5" />
              Release
            </button>
          </span>
        )}
      </div>

      {!number.engine_linked && !number.released && (
        <div className="space-y-2 rounded-card border border-line bg-surface-muted p-2">
          <p className="text-xs text-ink-muted">
            The voice platform has no handle for this number, so no agent can answer it —
            publishing one will report success and the phone will not ring. Paste the
            identifier from the voice platform&apos;s own number list.
          </p>
          {link.error && <ProblemNotice error={link.error} />}
          <div className="flex flex-wrap gap-2">
            <input
              aria-label={`Voice platform identifier for ${number.e164}`}
              className={`flex-1 font-mono ${FIELD}`}
              value={ref}
              disabled={!canWrite}
              onChange={(ev) => setRef(ev.target.value.trim())}
              placeholder="3c90c3cc0d444b5088888dd25736052a"
            />
            <button
              type="button"
              className={SECONDARY_BUTTON}
              disabled={!canWrite || !ref || link.isPending}
              onClick={() => link.mutate({ numberId: number.id, ref })}
            >
              {link.isPending ? "Linking…" : "Link and route"}
            </button>
          </div>
          {link.data && (
            <p className="text-xs text-ink-muted">
              {link.data.failed > 0
                ? "Recorded, but the voice platform refused the routing — the number is not answering yet."
                : link.data.bound > 0
                  ? "Recorded, and the agent is now set to answer it."
                  : "Recorded. It will start answering when the agent is published."}
            </p>
          )}
        </div>
      )}
    </li>
  );
}
