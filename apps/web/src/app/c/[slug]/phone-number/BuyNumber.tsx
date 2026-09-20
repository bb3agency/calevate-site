"use client";

/**
 * BUYING A NUMBER — and, for as long as this deployment may not sell one, saying so.
 *
 * ## The refusal is the screen, not its edge case
 *
 * `Settings.number_resale_authorization` is unset, so every route behind this panel
 * answers `number_purchase_is_operator_led` today and will until somebody outside this
 * repository signs something. A dead button, a spinner or a cheerful "no numbers yet"
 * would each leave a client waiting for a thing that is not coming. So that refusal
 * renders the SERVER's own sentence and its remediation, offers no purchase control at
 * all, and names what happens instead — an operator arranges the number.
 *
 * The words are the server's and are never re-worded here. The API deliberately answers
 * ONE sentence whichever of our gates is shut, so that the shape of an error cannot
 * publish which of our papers is missing; a console that guessed a cause would eventually
 * tell a client to wait for paperwork on a deployment whose engine simply sells nothing.
 *
 * ## Verification gates ACTIVATION, not the sale
 *
 * `POST /v1/numbers/purchase` does not ask whether the holder is verified; the number
 * arrives `activated: false` and cannot be given to an agent until they are. So this
 * screen sells to an unverified client and tells them plainly what they are getting —
 * blocking the purchase would be the console inventing a rule the connection does not
 * have, and hiding the consequence would be selling them a number that cannot ring.
 *
 * ## Why the holder is recorded on its own, before any purchase
 *
 * It cannot be changed afterwards — the operator who issues the connection holds the same
 * details — so the sentence saying so has to be readable while the fields are still
 * editable. Recording it inside the purchase would disclose a permanent consequence at
 * the moment of committing to a different one.
 *
 * ## Affordability is the API's answer, not a subtraction in a browser
 *
 * The fee and the balance are both shown before the confirm button, and the decision is
 * the server's `number_insufficient_credit` (hard rule 7 — a browser that compares two
 * rupee decimals is a browser that disagrees with the ledger). That refusal is rendered
 * as a top-up route rather than as a fault.
 */

import { AlertTriangle, Info, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import {
  Card,
  EmptyState,
  FIELD,
  FIELD_LABEL,
  MonoValue,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatINR,
} from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useKycRecord } from "@/lib/api/kyc";
import {
  INSUFFICIENT_CREDIT_CODE,
  NUMBER_TAKEN_CODE,
  OPERATOR_LED_CODE,
  useNumberHolder,
  useOfferedNumbers,
  usePurchaseNumber,
  useRecordNumberHolder,
  type CallDirection,
  type HolderType,
  type NumberHolderIn,
  type OfferedNumber,
} from "@/lib/api/numberProvisioning";
import { useClientRealm } from "@/lib/api/session";
import { useWallet } from "@/lib/api/wallet";
import { useIdempotencyKey } from "@/lib/authn/useIdempotencyKey";

import { DIRECTIONS, OutboundRestriction } from "./direction";

/** A refusal's machine code, its sentence and what to do instead — whatever it carried. */
function refusal(error: unknown): { code: string; detail: string; remediation: string | null } | null {
  if (!error || typeof error !== "object") return null;
  const problem = error as { code?: unknown; message?: unknown; remediation?: unknown };
  if (typeof problem.code !== "string") return null;
  return {
    code: problem.code,
    detail: typeof problem.message === "string" ? problem.message : "",
    remediation: typeof problem.remediation === "string" ? problem.remediation : null,
  };
}

/**
 * The one sentence a client handing over identity details is owed.
 *
 * It is true and it is the reassuring half: the connection is registered to THEM. What
 * happens without verification is stated separately, as a fact about the number rather
 * than as a penalty.
 */
const OWNER_SENTENCE =
  "The connection is registered to your business, not to Calevate. That is why the " +
  "identity check is yours to complete, and it is what makes you the owner of the number.";

function VerifyLink({ href }: { href: string }) {
  return (
    <Link href={href} className={SECONDARY_BUTTON_SM}>
      Verify your business
    </Link>
  );
}

/** What a client reads on a deployment that may not supply numbers. */
function CannotSupply({
  detail,
  remediation,
  verifyHref,
  unverified,
}: {
  detail: string;
  remediation: string | null;
  verifyHref: string;
  unverified: boolean;
}) {
  return (
    <div className="space-y-3 p-4">
      <NoticeBox tone="neutral" icon={<Info aria-hidden className="h-4 w-4" />}>
        <p className="text-ink">{detail}</p>
        {remediation && <p className="mt-2 text-ink-muted">{remediation}</p>}
      </NoticeBox>
      <p className="text-sm text-ink-muted">
        There is nothing for you to do here. You can also bring a connection you already
        hold with an Indian operator — you stay the account holder and can withdraw our
        access at any time.
      </p>
      {unverified && (
        <div className="space-y-2">
          <p className="text-sm text-ink-muted">
            Either route needs your business verified first, and you can do that now.
          </p>
          <VerifyLink href={verifyHref} />
        </div>
      )}
    </div>
  );
}

const HOLDER_TYPES: { value: HolderType; label: string }[] = [
  { value: "individual", label: "An individual" },
  { value: "business", label: "A registered business" },
];

/**
 * Whose name the connection goes into — asked once, and then fixed.
 *
 * The permanence is stated above the fields rather than beside the button, because it is
 * the fact that decides whether somebody should check the spelling before typing on.
 */
function HolderBlock() {
  const session = useClientRealm().session;
  const holder = useNumberHolder(session);
  const record = useRecordNumberHolder(session);
  const [draft, setDraft] = useState<NumberHolderIn>({
    holder_type: "business",
    holder_name: "",
    holder_email: "",
  });

  if (holder.isLoading) return <Skeleton rows={2} label="Loading who your numbers are registered to" />;
  if (holder.error || !holder.data) {
    return <ProblemNotice error={holder.error} onRetry={() => holder.refetch()} />;
  }

  if (holder.data.recorded) {
    return (
      <div className="rounded-card border border-line p-3">
        <p className="text-sm font-medium text-ink">Your numbers are registered to</p>
        <p className="mt-1 text-sm text-ink">
          {holder.data.holder_name} ({holder.data.holder_email})
        </p>
        <p className="mt-1 text-xs text-ink-muted">
          Recorded once and reused for every number you take. It cannot be changed — the
          operator who issues the connection holds the same details.
        </p>
      </div>
    );
  }

  const complete = draft.holder_name.trim() !== "" && draft.holder_email.trim() !== "";

  return (
    <div className="rounded-card border border-line p-3">
      <p className="text-sm font-medium text-ink">Who the number is registered to</p>
      <p className="mt-1 text-sm text-ink-muted">
        We collect this once and reuse it for every number you take afterwards. It cannot
        be changed later, so please check it before you save it.
      </p>

      <fieldset className="mt-3">
        <legend className={FIELD_LABEL}>They are</legend>
        <div className="mt-2 flex flex-wrap gap-4">
          {HOLDER_TYPES.map((kind) => (
            <label key={kind.value} className="flex items-center gap-2 text-sm text-ink">
              <input
                type="radio"
                name="holder-type"
                value={kind.value}
                checked={draft.holder_type === kind.value}
                onChange={() => setDraft({ ...draft, holder_type: kind.value })}
              />
              <span>{kind.label}</span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <label className={FIELD_LABEL} htmlFor="holder-name">
            Full name, as it appears on the registration
          </label>
          <input
            id="holder-name"
            className={FIELD}
            value={draft.holder_name}
            autoComplete="name"
            onChange={(event) => setDraft({ ...draft, holder_name: event.target.value })}
          />
        </div>
        <div>
          <label className={FIELD_LABEL} htmlFor="holder-email">
            Email address for the operator&apos;s paperwork
          </label>
          <input
            id="holder-email"
            type="email"
            className={FIELD}
            value={draft.holder_email}
            autoComplete="email"
            onChange={(event) => setDraft({ ...draft, holder_email: event.target.value })}
          />
        </div>
      </div>

      {record.error && (
        <div className="mt-3">
          <ProblemNotice error={record.error} />
        </div>
      )}

      <button
        type="button"
        className={`mt-3 ${PRIMARY_BUTTON_SM}`}
        disabled={!complete || record.isPending}
        onClick={() => record.mutate(draft)}
      >
        {record.isPending ? "Saving…" : "Save these details"}
      </button>
    </div>
  );
}

/** One number on offer. */
function OfferRow({
  offer,
  canBuy,
  blockedReason,
  onBuy,
}: {
  offer: OfferedNumber;
  canBuy: boolean;
  blockedReason: string | null;
  onBuy: () => void;
}) {
  const where = [offer.locality, offer.region].filter(Boolean).join(", ");
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-line p-3">
      <div>
        <MonoValue className="text-ink">{offer.e164}</MonoValue>
        {where !== "" && <p className="mt-1 text-xs text-ink-muted">{where}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm font-medium text-ink">
          {formatINR(offer.inr_per_month)} a month
        </span>
        <button
          type="button"
          className={PRIMARY_BUTTON_SM}
          disabled={!canBuy}
          title={blockedReason ?? undefined}
          onClick={onBuy}
        >
          Buy this number
        </button>
      </div>
    </li>
  );
}

export function BuyNumber() {
  const { session, href } = useClientRealm();
  const offers = useOfferedNumbers(session);
  const holder = useNumberHolder(session, offers.data !== undefined);
  const kyc = useKycRecord(session);
  const wallet = useWallet(session);
  const purchase = usePurchaseNumber(session);
  const write = useWriteAccess(session, "org:manage", "buy a phone number");

  const [chosen, setChosen] = useState<OfferedNumber | null>(null);
  const [direction, setDirection] = useState<CallDirection>("inbound");

  const verifyHref = href(`/c/${session.orgSlug}/verification`);
  const creditsHref = href(`/c/${session.orgSlug}/billing?tab=credits`);

  /* ONE KEY PER ATTEMPT, held across that attempt's retries, and fresh when the request
     changes. The API hashes the body, so a client who picks a different number or changes
     what it is for is making a different request and needs a different key; a retry after
     "top up first" is the SAME request and reuses this one, which is what makes the
     second press a replay rather than a second rental. */
  const idempotencyKey = useIdempotencyKey(
    `buy-number:${session.orgSlug}:${chosen?.e164 ?? ""}:${direction}`,
  );

  const closed = refusal(offers.error);
  const verified = kyc.data?.is_verified === true;
  const bought = purchase.data;

  return (
    <Card title="Getting a phone number">
      {offers.isLoading || kyc.isLoading ? (
        <div className="p-4">
          <Skeleton rows={3} label="Loading what we can supply" />
        </div>
      ) : closed?.code === OPERATOR_LED_CODE ? (
        <CannotSupply
          detail={closed.detail}
          remediation={closed.remediation}
          verifyHref={verifyHref}
          unverified={kyc.data !== undefined && !verified}
        />
      ) : offers.error || !offers.data || kyc.error || !kyc.data ? (
        <div className="p-4">
          <ProblemNotice
            error={offers.error ?? kyc.error}
            onRetry={() => {
              void offers.refetch();
              void kyc.refetch();
            }}
          />
        </div>
      ) : (
        <div className="space-y-4 p-4">
          <p className="text-sm text-ink-muted">{OWNER_SENTENCE}</p>

          <NoticeBox
            tone={verified ? "ok" : "warn"}
            icon={
              verified ? (
                <ShieldCheck aria-hidden className="h-4 w-4" />
              ) : (
                <AlertTriangle aria-hidden className="h-4 w-4" />
              )
            }
          >
            {verified ? (
              <p>
                Your business is verified, so a number you buy here can be put on an agent
                straight away.
              </p>
            ) : (
              <div className="space-y-2">
                <p>
                  You can buy a number now. It will not be able to make or take calls until
                  your business is verified — Indian telecom rules require the holder of a
                  connection to be identified before it carries traffic — and it is held
                  for you in the meantime.
                </p>
                <VerifyLink href={verifyHref} />
              </div>
            )}
          </NoticeBox>

          {bought && (
            <NoticeBox tone={bought.activated ? "ok" : "warn"} title={`${bought.e164} is yours`}>
              {bought.activated ? (
                <p>
                  {formatINR(bought.inr_per_month)} a month from today. Choose the agent
                  that uses it below.
                </p>
              ) : (
                <div className="space-y-2">
                  <p>
                    {formatINR(bought.inr_per_month)} a month from today. It cannot take or
                    make calls, and cannot be put on an agent, until your business is
                    verified.
                  </p>
                  <VerifyLink href={verifyHref} />
                </div>
              )}
            </NoticeBox>
          )}

          <HolderBlock />

          <RestrictionNote reason={write.reason} />

          {offers.data.length === 0 ? (
            <EmptyState
              title="No numbers are free to take right now"
              hint="Our supplier has none available at the moment. Talk to us and your account manager can source one."
            />
          ) : (
            <>
              {wallet.data?.prepaid === true && (
                <p className="text-sm text-ink-muted">
                  Your calling credit is {formatINR(wallet.data.balance_inr)}. The first
                  month is taken from it when you buy.
                </p>
              )}
              <ul className="space-y-2">
                {offers.data.map((offer) => (
                  <OfferRow
                    key={offer.e164}
                    offer={offer}
                    canBuy={write.allowed && holder.data?.recorded === true}
                    blockedReason={
                      write.allowed
                        ? // Only once we KNOW there is no registrant: while the read is
                          // in flight the button is off with nothing said about why,
                          // rather than naming a step that may already be done.
                          holder.data !== undefined && !holder.data.recorded
                          ? "Save who the number is registered to first."
                          : null
                        : write.reason
                    }
                    onBuy={() => {
                      purchase.reset();
                      setDirection("inbound");
                      setChosen(offer);
                    }}
                  />
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {chosen && (
        <ConfirmDialog
          title={`Buy ${chosen.e164}`}
          confirmLabel="Buy this number"
          pendingLabel="Buying…"
          pending={purchase.isPending}
          error={purchase.error}
          onCancel={() => setChosen(null)}
          onConfirm={() =>
            purchase.mutate(
              { e164: chosen.e164, direction, idempotencyKey },
              { onSuccess: () => setChosen(null) },
            )
          }
        >
          <p className="text-ink">
            {formatINR(chosen.inr_per_month)} every month, for as long as you keep the
            number. The first month comes off your calling credit now.
          </p>
          {wallet.data?.prepaid === true && (
            <p>Your credit is {formatINR(wallet.data.balance_inr)} before this purchase.</p>
          )}
          <p>{OWNER_SENTENCE}</p>
          {holder.data?.recorded === true && (
            <p>
              It is registered to {holder.data.holder_name}, and that cannot be changed
              afterwards.
            </p>
          )}

          <fieldset>
            <legend className={FIELD_LABEL}>What this number is for</legend>
            <div className="mt-2 space-y-2">
              {DIRECTIONS.map((option) => (
                <label key={option.value} className="flex items-start gap-2 text-sm text-ink">
                  <input
                    type="radio"
                    className="mt-1"
                    name="purchase-direction"
                    value={option.value}
                    checked={direction === option.value}
                    onChange={() => setDirection(option.value)}
                  />
                  <span>
                    {option.label}
                    <span className="block text-xs text-ink-muted">{option.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <OutboundRestriction direction={direction} series={chosen.series} />

          {!verified && (
            <p>
              It will not be able to make or take calls until your business is verified.
              Nothing else about the purchase changes.
            </p>
          )}

          {refusal(purchase.error)?.code === INSUFFICIENT_CREDIT_CODE && (
            <Link href={creditsHref} className={SECONDARY_BUTTON_SM}>
              Top up credit
            </Link>
          )}
          {refusal(purchase.error)?.code === NUMBER_TAKEN_CODE && (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => {
                setChosen(null);
                void offers.refetch();
              }}
            >
              See what is still available
            </button>
          )}
        </ConfirmDialog>
      )}
    </Card>
  );
}
