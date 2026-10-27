"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { TEXT_ACTION_DANGER } from "@/components/console/section";
import { ActionButton, useActionFeedback, type FeedbackStatus } from "@/components/arc/feedback";
import { MoneyInput } from "@/components/arc/money-input";
import { ConfirmDialog } from "@/components/confirmDialog";
import { SegmentedControl } from "@/components/interior/segmented-control";
import {
  Disclosure,
  NoticeBox,
  ProblemNotice,
  Skeleton,
  ToggleSwitch,
  formatINR,
  formatIST,
} from "@/components/ui";
import {
  MANDATE_STATUS_TEXT,
  type MandateMethod,
  useAutoRecharge,
  useConfirmMandate,
  useRechargeCharges,
  useSaveAutoRecharge,
  useStartMandate,
  useWithdrawMandate,
} from "@/lib/api/autoRecharge";
import type { Session } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import { rupeeProblem } from "@/lib/api/credits";
import { lookup } from "@/lib/lookup";
import { openRazorpayCheckout } from "@/lib/razorpayCheckout";

/**
 * Auto top-up (D-699): approve UPI Autopay or a card once, then choose when we top up, by
 * how much, and the most in a month. One collapsed card on the billing screen; the state
 * ("On", "Off") is on its closed row so nobody opens it to find out.
 *
 * Money stays a decimal STRING (hard rule 7). The fields show whole rupees (`MoneyInput`
 * with `paise={false}`) and hand back canonical strings, which are sent as they are.
 *
 * `available` is the top-up capability the Add credit drawer reads: a mandate is a provider
 * order, so on an account that can only pay by bank transfer the card offers neither the
 * payment-method setup nor the switch, and says why in one line — the page would otherwise
 * ask for UPI Autopay beside a drawer saying UPI is not on. An approval that already exists
 * is still shown, so it can be seen and withdrawn.
 *
 * The lag is stated, not hidden: automatic-payment rules mean the bank or UPI app notifies
 * the client at least a day before the debit, so a top-up lands one to two days after it
 * starts, and the threshold has to cover that.
 */
export function AutoRechargePanel({
  session,
  available = true,
}: {
  session: Session;
  available?: boolean;
}) {
  const write = useWriteAccess(session, "org:manage", "change auto top-up");
  const canManage = write.allowed;
  const settings = useAutoRecharge(session);
  const charges = useRechargeCharges(session);
  const save = useSaveAutoRecharge(session);
  const start = useStartMandate(session);
  const confirm = useConfirmMandate(session);
  const withdraw = useWithdrawMandate(session);
  // Every failure here is said in the one ProblemNotice under the fields, so none is toasted.
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const startFeedback = useActionFeedback(start, { errorDisplay: "inline" });
  const confirmFeedback = useActionFeedback(confirm, {
    errorDisplay: "inline",
    successToast: "Payment method approved",
    successDescription: "Turn on auto top-up when you are ready.",
  });
  const withdrawFeedback = useActionFeedback(withdraw, {
    errorDisplay: "inline",
    successToast: "Approval withdrawn",
    successDescription: "We will not top up your credit automatically.",
  });
  const [withdrawing, setWithdrawing] = useState(false);
  const [savingAmounts, setSavingAmounts] = useState(false);

  const [threshold, setThreshold] = useState("");
  const [amount, setAmount] = useState("");
  const [cap, setCap] = useState("");
  const [method, setMethod] = useState<MandateMethod>("upi");
  const [windowNote, setWindowNote] = useState<string | null>(null);
  const [checkoutProblem, setCheckoutProblem] = useState<unknown>(null);

  const data = settings.data;
  useEffect(() => {
    if (!data) return;
    setThreshold(twoPlaces(data.threshold_inr));
    setAmount(twoPlaces(data.amount_inr));
    setCap(twoPlaces(data.monthly_cap_inr));
  }, [data]);

  if (settings.isLoading) return <Skeleton rows={1} label="Loading auto top-up" />;
  if (settings.error || !data) {
    return (
      <ProblemNotice
        error={settings.error ?? new Error("Your auto top-up settings did not load.")}
        onRetry={() => void settings.refetch()}
      />
    );
  }
  const confirmed = data.mandate_status === "confirmed";
  const hasApproval = data.mandate_status !== "none";
  if (!available && !hasApproval && !data.enabled) {
    return (
      <div
        role="note"
        aria-label="Auto top-up"
        className="flex items-start gap-3 rounded-card border border-line bg-surface px-4 py-4 sm:px-6"
      >
        <span
          aria-hidden
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-muted text-ink-muted"
        >
          <RefreshCw className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-[15px] font-semibold text-ink">Auto top-up</p>
          <p className="text-meta text-ink-muted">{UNAVAILABLE}</p>
        </div>
      </div>
    );
  }

  const fieldProblem = rupeeProblem(threshold) ?? rupeeProblem(amount) ?? rupeeProblem(cap);
  const edited =
    threshold !== twoPlaces(data.threshold_inr) ||
    amount !== twoPlaces(data.amount_inr) ||
    cap !== twoPlaces(data.monthly_cap_inr);
  /* Approving runs two requests with the checkout window between them; the button shows
     whichever is in flight, and its tick once the approval is confirmed. */
  const approveStatus: FeedbackStatus =
    startFeedback.status === "pending" || startFeedback.status === "error"
      ? startFeedback.status
      : confirmFeedback.status;

  const persist = (enabled: boolean) =>
    saveFeedback.run({
      enabled,
      threshold_inr: threshold,
      amount_inr: amount,
      monthly_cap_inr: cap,
    });

  const approve = async () => {
    setWindowNote(null);
    setCheckoutProblem(null);
    // A refused start is already on screen as `start.error`; nothing more to do with it here.
    const checkout = await start.mutateAsync({ method, max_debit_inr: amount }).catch(() => null);
    if (checkout === null) return;
    // The checkout script can fail to load; it rejects with a problem worth showing.
    await openRazorpayCheckout({
      keyId: checkout.key_id,
      orderId: checkout.order_id,
      amountPaise: checkout.amount_paise,
      currency: "INR",
      receipt: checkout.order_id,
      notes: checkout.notes,
      recurringCustomerId: checkout.customer_id,
      onSuccess: (response) => confirmFeedback.run(response),
      onDismissed: () => setWindowNote("The approval window was closed. Nothing was set up."),
      onFailed: () =>
        setWindowNote("The approval did not go through. You can try again or use another method."),
    }).catch((problem: unknown) => setCheckoutProblem(problem));
  };

  const methodName = data.mandate_method === "card" ? "Card" : "UPI Autopay";
  return (
    <Disclosure
      title="Auto top-up"
      icon={<RefreshCw className="h-4 w-4" />}
      status={data.enabled ? "On" : "Off"}
      subtitle={
        data.enabled
          ? `Adds ${formatINR(data.amount_inr)} when credit falls below ${formatINR(data.threshold_inr)}`
          : "Refill your credit automatically when it runs low"
      }
      showLabel={confirmed ? "Change" : "Set up"}
      hideLabel="Close"
    >
      <div className="settings-enter space-y-6">
        {data.disabled_reason && (
          <NoticeBox tone="warn" title="Auto top-up is off">
            <p>{data.disabled_reason}</p>
          </NoticeBox>
        )}

        {/* 1. THE PAYMENT METHOD — the approval our payment provider holds; we never see
            card or UPI details. Nothing below can be switched on without it. */}
        <div className="space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h3 className="text-body font-semibold text-ink">Payment method</h3>
            {canManage && (confirmed || data.mandate_status === "paused") && (
              <button type="button" className={TEXT_ACTION_DANGER} onClick={() => setWithdrawing(true)}>
                Withdraw approval
              </button>
            )}
          </div>
          <p className="text-body text-ink-muted">
            {confirmed && data.mandate_method
              ? `${methodName} approved, up to ${formatINR(data.mandate_max_inr)} per top-up.`
              : (lookup(MANDATE_STATUS_TEXT, data.mandate_status) ?? data.mandate_status)}
          </p>
          {!available && <p className="text-meta text-ink-muted">{UNAVAILABLE}</p>}
          {canManage && available && !confirmed && (
            <div className="flex flex-wrap items-center gap-3">
              <SegmentedControl
                label="Payment method to approve"
                value={method}
                onValueChange={(next) => setMethod(next === "card" ? "card" : "upi")}
                options={[
                  { value: "upi", label: "UPI Autopay" },
                  { value: "card", label: "Card" },
                ]}
              />
              <ActionButton
                variant="secondary"
                status={approveStatus}
                successLabel="Approved"
                disabled={fieldProblem !== null}
                onClick={() => void approve()}
              >
                Approve a payment method
              </ActionButton>
            </div>
          )}
          {windowNote && <p className="text-meta text-ink-muted">{windowNote}</p>}
        </div>

        {/* 2. THE THREE AMOUNTS, whole rupees, in the order the rule reads aloud. */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <MoneyInput
            label="When credit falls below"
            paise={false}
            value={threshold}
            onChange={setThreshold}
            disabled={!canManage}
            hint={
              data.suggested_threshold_inr
                ? `We suggest at least ${formatINR(data.suggested_threshold_inr)}.`
                : "About two days of calling."
            }
          />
          <MoneyInput
            label="Top up by"
            paise={false}
            value={amount}
            onChange={setAmount}
            disabled={!canManage}
            hint={`At most ${formatINR(data.max_debit_inr)} each time.`}
          />
          <MoneyInput
            label="Monthly limit"
            paise={false}
            value={cap}
            onChange={setCap}
            disabled={!canManage}
            hint={`${formatINR(data.month_charged_inr)} used this month.`}
          />
        </div>

        {/* 3. THE SWITCH, and the save for amounts changed without touching it. */}
        <div className="flex flex-wrap items-center justify-between gap-4 border-t border-line pt-4">
          {canManage && !available ? (
            <span />
          ) : canManage ? (
            <ToggleSwitch
              label="Top up automatically"
              hint={confirmed ? undefined : "Approve a payment method first."}
              checked={data.enabled}
              disabled={!confirmed || fieldProblem !== null || saveFeedback.status === "pending"}
              onChange={(next) => {
                setSavingAmounts(false);
                persist(next);
              }}
            />
          ) : (
            <p className="text-meta text-ink-muted">
              {write.reason ?? "Only the account owner can change auto top-up."}
            </p>
          )}
          {canManage && (edited || (savingAmounts && saveFeedback.status !== "idle")) && (
            <ActionButton
              variant="secondary"
              status={saveFeedback.status}
              successLabel="Saved"
              disabled={fieldProblem !== null}
              onClick={() => {
                setSavingAmounts(true);
                persist(data.enabled);
              }}
            >
              Save amounts
            </ActionButton>
          )}
        </div>

        {fieldProblem && <p className="text-meta text-ink-muted">{fieldProblem}</p>}
        <ProblemNotice error={save.error ?? start.error ?? checkoutProblem ?? confirm.error} />

        <p className="max-w-prose text-meta text-ink-muted">
          Your bank or UPI app tells you at least a day before each debit, so the credit
          arrives one to two days later; calls keep running meanwhile. Turn it off or
          withdraw the approval at any time.
        </p>

        {charges.data && charges.data.length > 0 && (
          <div>
            <h3 className="text-body font-semibold text-ink">Recent automatic top-ups</h3>
            <ul className="mt-2 divide-y divide-line border-y border-line text-body">
              {charges.data.map((charge) => (
                <li key={charge.created_at} className="flex flex-wrap justify-between gap-x-4 py-2.5">
                  <span className="text-ink-muted">{formatIST(charge.created_at)}</span>
                  <span className="tabular-nums text-ink">
                    {formatINR(charge.amount_inr)} ·{" "}
                    {charge.status === "captured"
                      ? "Added"
                      : charge.status === "pending"
                        ? "In progress"
                        : "Did not go through"}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {withdrawing && (
        <ConfirmDialog
          title="Withdraw the payment approval?"
          confirmLabel="Withdraw approval"
          pendingLabel="Withdrawing"
          status={withdrawFeedback.status}
          error={withdraw.error}
          onCancel={() => {
            withdraw.reset();
            setWithdrawing(false);
          }}
          onConfirm={() => withdraw.mutate(undefined, { onSuccess: () => setWithdrawing(false) })}
        >
          Automatic top-ups stop, and your credit is no longer refilled when it runs low. To
          turn them on again you approve a payment method again.
        </ConfirmDialog>
      )}
    </Disclosure>
  );
}

/** Said wherever the card would otherwise offer a payment method this account cannot use. */
const UNAVAILABLE =
  "Automatic top-up needs online payment, which isn't on for your account yet. Talk to us to add credit by bank transfer.";

/**
 * The server's amount as `MoneyInput`'s canonical form ("500.00"), so an untouched field
 * compares equal to what was loaded. String work only: the fraction is cut or padded to
 * two places, never rounded through a number (hard rule 7).
 */
function twoPlaces(value: string): string {
  const [whole = "0", fraction = ""] = value.split(".");
  return `${whole}.${`${fraction}00`.slice(0, 2)}`;
}
