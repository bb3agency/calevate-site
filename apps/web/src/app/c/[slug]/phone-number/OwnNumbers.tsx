"use client";

import { Section } from "@/components/console/section";

/**
 * A PHONE NUMBER IN THE BUSINESS'S OWN NAME — three steps, and where this account stands on
 * each (D-693).
 *
 * The server says which step the account is on (`status.step`) and this screen only draws
 * it: verify the business, have the business details approved for phone numbers, then buy.
 * A step the server has not reached yet is shown as waiting, never as something to do, so a
 * client is not sent to a button the purchase gate will refuse.
 *
 * WHITE LABEL: nothing here names the company that hosts the calls, its plans or its price.
 * The account is "your calling account" and the price is ours (`inr_per_month`).
 *
 * The charge sentence after a purchase is worded from `first_period`, the server's record
 * of what the purchase actually did to the account — never from what we expected it to do.
 */

import { CheckCircle2, Clock, Info } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { ConfirmDialog } from "@/components/confirmDialog";
import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  MonoValue,
  NoticeBox,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  RestrictionNote,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatIST,
  formatINR,
  formatPhone,
} from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { ApiProblem } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import { codeOf } from "@/lib/authn/problems";
import {
  SEARCH_DIGITS_MAX,
  newRequestKey,
  searchDigits,
  useOwnAvailableNumbers,
  useOwnNumberCities,
  usePurchaseOwnNumber,
  useReleaseOwnNumber,
  useSendOwnBusinessDetails,
  type FirstPeriod,
  type OwnAvailableNumber,
  type OwnNumberDirection,
  type OwnNumbersStatus,
  type PurchasedOwnNumber,
} from "@/lib/api/ownNumbers";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { DIRECTIONS } from "./direction";

/** The refusals this journey can meet, each in the words of what to do next. */
const REFUSALS: Record<string, string> = {
  trial_numbers_unavailable:
    "Phone numbers are available once you add credit and verify your business. Nothing was charged.",
  engine_workspace_not_provisioned:
    "Your calling account is still being set up. Nothing was charged — try again in a few minutes.",
  kyc_not_verified: "Verify your business first. Nothing was charged.",
  business_details_kyc_not_verified:
    "Verify your business first. We send the business details once it is verified.",
  business_details_not_approved:
    "Your business details are not approved for phone numbers yet. Nothing was charged.",
  number_price_not_attested: "Numbers are not on sale yet. Nothing was charged.",
  // The server sends this for every refusal of the number itself: it may have been taken,
  // or the business details may still be under check. Nothing tells the two apart.
  engine_number_unavailable:
    "That number could not be bought: somebody else may have taken it, or your business details are still being checked. Nothing was charged — please pick another, or try again shortly.",
  engine_number_purchase_unconfirmed:
    "We could not confirm the purchase. Press Buy again: it finishes this same purchase and never buys a second number.",
  engine_number_agent_not_moved:
    "That agent is not published yet, so the number cannot be put on it. Publish the agent first, then press Buy again — or buy without an agent and choose one later.",
  number_insufficient_credit:
    "There is not enough calling credit for the first month. Top up, then press Buy again.",
};

/** A refusal in plain words where we know the code, and the server's own sentence where not. */
export function OwnNumberProblem({ error }: { error: unknown }) {
  if (!error) return null;
  const sentence = error instanceof ApiProblem ? lookup(REFUSALS, error.code) : undefined;
  if (sentence === undefined) return <ProblemNotice error={error} />;
  return (
    <div role="alert">
      <NoticeBox tone="warn">
        <p>{sentence}</p>
      </NoticeBox>
    </div>
  );
}

/**
 * What a purchase did to the account, from `first_period`. Claims a charge only when the
 * server says one happened.
 */
export function firstPeriodSentence(period: FirstPeriod, inrPerMonth: string | null): string {
  const monthly = inrPerMonth === null ? null : `${formatINR(inrPerMonth)} a month`;
  switch (period) {
    case "charged":
      return inrPerMonth === null
        ? "The first month was charged now."
        : `${formatINR(inrPerMonth)} charged now for the first month, then monthly.`;
    case "invoiced":
      return `${monthly ?? "The monthly charge"} — the first month is added to your next invoice.`;
    case "trial":
      return `${monthly ?? "The monthly charge"} — free during your trial; charging starts at the first renewal after it.`;
    case "replayed":
      return "Your earlier request already bought this number.";
    default:
      return monthly === null ? "" : `${monthly}.`;
  }
}

type StepState = "done" | "now" | "waiting";

function StepRow({
  index,
  title,
  state,
  children,
}: {
  index: number;
  title: string;
  state: StepState;
  children: ReactNode;
}) {
  const badge =
    state === "done"
      ? { text: "Done", tone: "bg-brand-soft text-brand-strong" }
      : state === "now"
        ? { text: "Next step", tone: "bg-ink/[0.06] text-ink" }
        : { text: "Waiting", tone: "border border-line text-ink-muted" };
  return (
    <li className="py-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-body font-semibold text-ink">
          {index}. {title}
        </h3>
        <span className={`rounded-full px-2 py-0.5 text-meta font-medium ${badge.tone}`}>{badge.text}</span>
      </div>
      <div className="mt-2 space-y-2 text-body text-ink-muted">{children}</div>
    </li>
  );
}

const KYC_COPY: Record<string, string> = {
  verified: "Your business is verified.",
  submitted: "Your documents are with our review team.",
  in_review: "Your documents are with our review team.",
  rejected: "We could not verify the business from what was sent. See what to fix.",
  expired: "Your verification has lapsed. Please verify the business again.",
  not_started: "Verify your business with its certificate and the owner's ID.",
};

/** The business-details application, in the client's words. */
const DETAILS_COPY: Record<string, string> = {
  none: "Not sent yet.",
  draft: "Started, but not sent yet.",
  submitted: "Being checked. This usually takes a few minutes.",
  accepted: "Approved. Phone numbers can be registered in your business's name.",
  rejected: "Not approved.",
  suspended: "Approval was withdrawn, and it cannot be restored from here. Please contact us and we will sort it out with you.",
  expired: "The approval has lapsed. Please send the details again.",
  unknown: "We could not read where this stands. We keep checking.",
};

/** The three steps, and the purchase once the server says the account is ready. */
export function OwnNumbersJourney({ status }: { status: OwnNumbersStatus }) {
  const { session, href } = useClientRealm();
  const send = useSendOwnBusinessDetails(session);
  const write = useWriteAccess(session, "org:manage", "get a phone number");
  const verifyHref = href(`/c/${session.orgSlug}/verify-business`);

  const kycDone = status.kyc_status === "verified";
  const detailsStatus = status.business_status ?? "none";
  const detailsDone = detailsStatus === "accepted" && status.step !== "business_details";
  const ready = status.step === "ready";

  return (
    <Section title="Get a phone number in your business's name">
      <div className="space-y-4 p-4">
        <p className="text-body text-ink-muted">
          Your phone numbers are registered in your business&apos;s own name. Three steps get you
          there, and this shows where each one stands.
        </p>

        {status.step === "add_credit" && (
          <NoticeBox tone="neutral" icon={<Clock aria-hidden className="h-4 w-4" />} title="Add credit to get started">
            <p className="mt-1">
              During your free trial, test calls ring from a shared Calevate number. Add credit
              to end the trial; then these three steps get you a number in your business&apos;s name.
            </p>
          </NoticeBox>
        )}

        {status.step === "workspace" && (
          <NoticeBox tone="neutral" icon={<Clock aria-hidden className="h-4 w-4" />} title="Your calling account is being set up">
            <p className="mt-1">
              We are setting up the account your phone numbers will live in. There is nothing for
              you to do — this page moves on by itself once it is ready.
            </p>
          </NoticeBox>
        )}

        <ol className="space-y-3">
          <StepRow index={1} title="Verify your business" state={kycDone ? "done" : "now"}>
            <p>{lookup(KYC_COPY, status.kyc_status) ?? KYC_COPY.not_started}</p>
            {!kycDone && (
              <Link href={verifyHref} className={SECONDARY_BUTTON_SM}>
                Verify your business
              </Link>
            )}
          </StepRow>

          <StepRow
            index={2}
            title="Business details for phone numbers"
            state={detailsDone ? "done" : kycDone ? "now" : "waiting"}
          >
            {!kycDone ? (
              <p>Once your business is verified, we send its details for approval for phone numbers.</p>
            ) : (
              <>
                <p>{lookup(DETAILS_COPY, detailsStatus) ?? DETAILS_COPY.unknown}</p>
                {status.business_submitted_at && detailsStatus === "submitted" && (
                  <p className={FIELD_HINT}>Sent {formatIST(status.business_submitted_at)}.</p>
                )}
                {status.business_review_note &&
                  (detailsStatus === "rejected" || detailsStatus === "suspended") && (
                    <NoticeBox tone="stop" title="What the review said">
                      <p className="mt-1">{status.business_review_note}</p>
                    </NoticeBox>
                  )}
                {/* Only a rejection is corrected and sent again; a suspension is not
                    (`RESUBMITTABLE` on the server), so its sentence above says to contact us. */}
                {detailsStatus === "rejected" && (
                  <p>
                    Fix and send again: correct the details under{" "}
                    <Link href={verifyHref} className="font-medium text-ink underline">
                      Verify your business
                    </Link>
                    , then send them again here.
                  </p>
                )}
                {status.can_send_business_details && (
                  <button
                    type="button"
                    className={PRIMARY_BUTTON_SM}
                    disabled={!write.allowed || send.isPending}
                    onClick={() => send.mutate()}
                  >
                    {send.isPending
                      ? "Sending…"
                      : detailsStatus === "none" || detailsStatus === "draft"
                        ? "Send business details"
                        : "Send the details again"}
                  </button>
                )}
                <OwnNumberProblem error={send.error} />
              </>
            )}
          </StepRow>

          <StepRow index={3} title="Buy a number" state={ready ? "now" : "waiting"}>
            {status.inr_per_month !== null && (
              <p>A number costs {formatINR(status.inr_per_month)} a month, for as long as you keep it.</p>
            )}
            {status.step === "price" ? (
              <p>Numbers are not on sale yet. We will let you know when they are.</p>
            ) : !ready ? (
              <p>You can choose a number here once the steps above are done.</p>
            ) : null}
          </StepRow>
        </ol>

        <RestrictionNote reason={write.reason} />
        {ready && <BuyOwnNumber canBuy={write.allowed} />}
      </div>
    </Section>
  );
}

const NO_AGENT = "";

/** City, then numbers a page at a time, then a confirmation that names the price. */
function BuyOwnNumber({ canBuy }: { canBuy: boolean }) {
  const { session, href } = useClientRealm();
  const cities = useOwnNumberCities(session, true);
  const agents = useAgents(session);
  const purchase = usePurchaseOwnNumber(session);
  const [city, setCity] = useState("");
  const [pattern, setPattern] = useState("");
  const [search, setSearch] = useState<{ city: string; pattern: string } | null>(null);
  const available = useOwnAvailableNumbers(session, search);

  const [chosen, setChosen] = useState<OwnAvailableNumber | null>(null);
  const [agentId, setAgentId] = useState(NO_AGENT);
  const [direction, setDirection] = useState<OwnNumberDirection>("both");
  // ONE key per press of Buy, held across that purchase's retries. Changing what is being
  // bought (agent, direction) is a different request and gets a fresh key.
  const [requestKey, setRequestKey] = useState("");
  const [bought, setBought] = useState<PurchasedOwnNumber | null>(null);

  const creditsHref = href(`/c/${session.orgSlug}/billing?tab=credits`);

  function open(offer: OwnAvailableNumber) {
    purchase.reset();
    setAgentId(NO_AGENT);
    setDirection("both");
    setRequestKey(newRequestKey());
    setChosen(offer);
  }

  if (cities.isLoading) return <Skeleton rows={2} label="Loading cities" />;
  if (cities.error || !cities.data) {
    return <ProblemNotice error={cities.error} onRetry={() => void cities.refetch()} />;
  }

  const pages = available.data?.pages;
  const numbers = pages === undefined ? undefined : pages.flatMap((page) => page.numbers);
  const chosenAgent = agents.data?.find((agent) => agent.id === agentId);

  return (
    <section aria-labelledby="buy-own-number" className="space-y-3">
      <h3 id="buy-own-number" className="text-body font-semibold text-ink">
        Choose a number
      </h3>

      {bought && (
        <NoticeBox
          tone="ok"
          icon={<CheckCircle2 aria-hidden className="h-4 w-4" />}
          title={`${formatPhone(bought.e164)} is yours`}
        >
          {firstPeriodSentence(bought.first_period, bought.inr_per_month) && (
            <p className="mt-1">{firstPeriodSentence(bought.first_period, bought.inr_per_month)}</p>
          )}
          {(bought.attachment === "partial" || bought.attachment === "refused") && (
            <p className="mt-1">
              We could not put it on the agent yet. Choose the agent on the number below.
            </p>
          )}
          {bought.attachment === "other_workspace" && (
            <p className="mt-1">
              It does not ring that agent yet: the agent has to be published again before it
              can answer this number. Publish the agent, then choose it on the number below.
            </p>
          )}
        </NoticeBox>
      )}

      {cities.data.length === 0 ? (
        <p className="text-body text-ink-muted">No city has numbers free right now. Please check again later.</p>
      ) : (
        <form
          noValidate
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (city) setSearch({ city, pattern: searchDigits(pattern) });
          }}
        >
          <label className="block">
            <span className={FIELD_LABEL}>City</span>
            <select className={FIELD} value={city} onChange={(event) => setCity(event.target.value)}>
              <option value="">Choose a city…</option>
              {cities.data.map((option) => (
                <option key={option.name} value={option.name}>
                  {option.name} ({option.available} free)
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className={FIELD_LABEL}>Digits it contains (optional)</span>
            <input
              className={FIELD}
              value={pattern}
              inputMode="numeric"
              maxLength={SEARCH_DIGITS_MAX}
              onChange={(event) => setPattern(searchDigits(event.target.value))}
            />
          </label>
          <button type="submit" className={SECONDARY_BUTTON_SM} disabled={!city || available.isFetching}>
            {available.isFetching && !available.isFetchingNextPage ? "Searching…" : "Show numbers"}
          </button>
        </form>
      )}

      {available.error && <OwnNumberProblem error={available.error} />}

      {search !== null &&
        !available.error &&
        (numbers === undefined ? (
          <Skeleton rows={3} label="Finding numbers" />
        ) : numbers.length === 0 ? (
          <p className="text-body text-ink-muted">
            No number is free in {search.city} right now. Try another city.
          </p>
        ) : (
          <>
            <ul className="border-y border-line">
              {numbers.map((offer) => (
                <li
                  key={offer.number}
                  className="flex flex-wrap items-center justify-between gap-3 border-b border-line py-3 last:border-b-0"
                >
                  <div>
                    <MonoValue className="text-ink">{formatPhone(offer.e164)}</MonoValue>
                    {offer.city && <p className="mt-1 text-meta text-ink-muted">{offer.city}</p>}
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    {offer.inr_per_month !== null && (
                      <span className="text-body font-medium text-ink">{formatINR(offer.inr_per_month)} a month</span>
                    )}
                    <button
                      type="button"
                      className={PRIMARY_BUTTON_SM}
                      disabled={!canBuy}
                      aria-label={`Buy ${formatPhone(offer.e164)}`}
                      onClick={() => open(offer)}
                    >
                      Buy
                    </button>
                  </div>
                </li>
              ))}
            </ul>
            {available.hasNextPage && (
              <button
                type="button"
                className={SECONDARY_BUTTON_SM}
                disabled={available.isFetchingNextPage}
                onClick={() => void available.fetchNextPage()}
              >
                {available.isFetchingNextPage ? "Loading…" : "Load more"}
              </button>
            )}
          </>
        ))}

      {chosen && (
        <ConfirmDialog
          title={`Buy ${formatPhone(chosen.e164)}`}
          confirmLabel="Buy this number"
          pendingLabel="Buying…"
          pending={purchase.isPending}
          error={null}
          onCancel={() => setChosen(null)}
          onConfirm={() =>
            purchase.mutate(
              {
                number: chosen.number,
                agent_id: agentId === NO_AGENT ? null : agentId,
                direction,
                request_key: requestKey,
              },
              {
                onSuccess: (result) => {
                  setBought(result);
                  setChosen(null);
                },
              },
            )
          }
        >
          {chosen.inr_per_month !== null && (
            <p className="text-ink">
              {formatINR(chosen.inr_per_month)} every month, for as long as you keep the number.
            </p>
          )}
          <p>It is registered in your business&apos;s name.</p>
          <label className="block">
            <span className={FIELD_LABEL}>The agent that answers it (optional)</span>
            <select
              className={FIELD}
              value={agentId}
              onChange={(event) => {
                setAgentId(event.target.value);
                setRequestKey(newRequestKey());
              }}
            >
              <option value={NO_AGENT}>No agent yet — I will choose later</option>
              {agents.data?.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>
          {chosenAgent && <p>Calls to it reach {chosenAgent.name}.</p>}
          <fieldset>
            <legend className={FIELD_LABEL}>What this number is for</legend>
            <div className="mt-2 space-y-2">
              {DIRECTIONS.map((option) => (
                <label key={option.value} className="flex items-start gap-2 text-body text-ink">
                  <input
                    type="radio"
                    className="mt-1"
                    name="own-number-direction"
                    value={option.value}
                    checked={direction === option.value}
                    onChange={() => {
                      setDirection(option.value);
                      setRequestKey(newRequestKey());
                    }}
                  />
                  <span>
                    {option.label}
                    <span className="block text-meta text-ink-muted">{option.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <OwnNumberProblem error={purchase.error} />
          {codeOf(purchase.error) === "number_insufficient_credit" && (
            <Link href={creditsHref} className={SECONDARY_BUTTON_SM}>
              Top up credit
            </Link>
          )}
          {codeOf(purchase.error) === "engine_number_unavailable" && (
            <button
              type="button"
              className={SECONDARY_BUTTON_SM}
              onClick={() => {
                setChosen(null);
                void available.refetch();
              }}
            >
              See what is still free
            </button>
          )}
        </ConfirmDialog>
      )}
    </section>
  );
}

/** Give a number up — permanent, and this month is not refunded. */
export function ReleaseOwnNumber({ numberId, e164 }: { numberId: string; e164: string }) {
  const { session } = useClientRealm();
  const release = useReleaseOwnNumber(session);
  const write = useWriteAccess(session, "org:manage", "give a phone number up");
  const [confirming, setConfirming] = useState(false);

  if (release.data?.released) {
    return (
      <p className="text-body text-ink-muted">
        {formatPhone(e164)} is released. Its monthly charge has stopped.
      </p>
    );
  }
  return (
    <div className="border-t border-line pt-4">
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={!write.allowed}
        title={write.reason ?? undefined}
        onClick={() => {
          release.reset();
          setConfirming(true);
        }}
      >
        Release this number
      </button>
      {confirming && (
        <ConfirmDialog
          title={`Release ${formatPhone(e164)}`}
          confirmLabel="Release it for good"
          pendingLabel="Releasing…"
          pending={release.isPending}
          error={null}
          onCancel={() => setConfirming(false)}
          onConfirm={() =>
            release.mutate(numberId, { onSuccess: () => setConfirming(false) })
          }
        >
          <NoticeBox tone="warn" icon={<Info aria-hidden className="h-4 w-4" />}>
            <ul className="list-disc space-y-1 pl-4">
              <li>Releasing is permanent. The number stops ringing straight away.</li>
              <li>It goes back to the pool, and anybody may take it next. You cannot get it back.</li>
              <li>This month is not refunded. The monthly charge stops.</li>
            </ul>
          </NoticeBox>
          <OwnNumberProblem error={release.error} />
        </ConfirmDialog>
      )}
    </div>
  );
}
