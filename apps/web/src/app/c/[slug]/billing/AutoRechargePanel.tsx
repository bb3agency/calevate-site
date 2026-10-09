"use client";

import { useEffect, useState } from "react";

import {
  Card,
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  SECONDARY_BUTTON,
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
 * Auto-recharge (D-699): approve UPI Autopay or a card once, then choose when we top up,
 * by how much, and the most in a month. Money stays a decimal STRING here (hard rule 7):
 * fields are checked with `rupeeProblem` and sent as typed.
 *
 * The lag is stated, not hidden: the rules for automatic payments mean the bank or UPI app
 * notifies the client at least a day before the debit, so a top-up lands one to two days
 * after it starts, and the threshold has to cover that.
 */
export function AutoRechargePanel({ session }: { session: Session }) {
  const write = useWriteAccess(session, "org:manage", "change auto-recharge");
  const canManage = write.allowed;
  const settings = useAutoRecharge(session);
  const charges = useRechargeCharges(session);
  const save = useSaveAutoRecharge(session);
  const start = useStartMandate(session);
  const confirm = useConfirmMandate(session);
  const withdraw = useWithdrawMandate(session);

  const [threshold, setThreshold] = useState("");
  const [amount, setAmount] = useState("");
  const [cap, setCap] = useState("");
  const [method, setMethod] = useState<MandateMethod>("upi");
  const [windowNote, setWindowNote] = useState<string | null>(null);

  const data = settings.data;
  useEffect(() => {
    if (!data) return;
    setThreshold(data.threshold_inr);
    setAmount(data.amount_inr);
    setCap(data.monthly_cap_inr);
  }, [data]);

  if (settings.isLoading) return <Skeleton rows={3} label="Loading auto-recharge" />;
  if (settings.error || !data) return <ProblemNotice error={settings.error} />;

  const fieldProblem = rupeeProblem(threshold) ?? rupeeProblem(amount) ?? rupeeProblem(cap);
  const confirmed = data.mandate_status === "confirmed";

  const persist = (enabled: boolean) =>
    save.mutate({
      enabled,
      threshold_inr: threshold.trim(),
      amount_inr: amount.trim(),
      monthly_cap_inr: cap.trim(),
    });

  const approve = async () => {
    setWindowNote(null);
    const checkout = await start.mutateAsync({ method, max_debit_inr: amount.trim() });
    await openRazorpayCheckout({
      keyId: checkout.key_id,
      orderId: checkout.order_id,
      amountPaise: checkout.amount_paise,
      currency: "INR",
      receipt: checkout.order_id,
      notes: checkout.notes,
      recurringCustomerId: checkout.customer_id,
      onSuccess: (response) => confirm.mutate(response),
      onDismissed: () => setWindowNote("The approval window was closed. Nothing was set up."),
      onFailed: () =>
        setWindowNote("The approval did not go through. You can try again or use another method."),
    });
  };

  return (
    <Card
      title="Auto-recharge"
      info="We top up your credit automatically when it runs low, using a payment method you approve once. Razorpay, our payment gateway, holds the approval; we never see card or UPI details."
    >
      <div className="space-y-4">
        <NoticeBox tone={confirmed ? "ok" : "neutral"} title="Payment method">
          <p>
            {lookup(MANDATE_STATUS_TEXT, data.mandate_status) ?? data.mandate_status}
            {confirmed && data.mandate_method && (
              <> ({data.mandate_method === "upi" ? "UPI Autopay" : "card"}, up to{" "}
              {formatINR(data.mandate_max_inr)} per top-up)</>
            )}
          </p>
        </NoticeBox>

        {data.disabled_reason && (
          <NoticeBox tone="warn" title="Auto-recharge is off">
            <p>{data.disabled_reason}</p>
          </NoticeBox>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block">
            <span className={FIELD_LABEL}>Top up when credit falls below (₹)</span>
            <input
              className={FIELD}
              inputMode="decimal"
              value={threshold}
              disabled={!canManage}
              onChange={(e) => setThreshold(e.target.value)}
            />
            <span className={FIELD_HINT}>
              {data.suggested_threshold_inr
                ? `Your recent calling suggests at least ${formatINR(data.suggested_threshold_inr)}.`
                : "Cover about two days of calling."}
            </span>
          </label>
          <label className="block">
            <span className={FIELD_LABEL}>Top up by (₹)</span>
            <input
              className={FIELD}
              inputMode="decimal"
              value={amount}
              disabled={!canManage}
              onChange={(e) => setAmount(e.target.value)}
            />
            <span className={FIELD_HINT}>
              At most {formatINR(data.max_debit_inr)}: larger automatic payments need you to
              approve each one.
            </span>
          </label>
          <label className="block">
            <span className={FIELD_LABEL}>At most per month (₹)</span>
            <input
              className={FIELD}
              inputMode="decimal"
              value={cap}
              disabled={!canManage}
              onChange={(e) => setCap(e.target.value)}
            />
            <span className={FIELD_HINT}>
              {formatINR(data.month_charged_inr)} topped up automatically this month.
            </span>
          </label>
        </div>

        <p className="text-sm text-ink-muted">
          When your credit falls below the level you set, we email you and start a top-up.
          Your bank or UPI app notifies you at least a day before the money is taken, so the
          credit usually arrives one to two days later; your calls keep running meanwhile.
          You can turn this off or withdraw the approval at any time.
        </p>

        {fieldProblem && <p className="text-sm text-ink-muted">{fieldProblem}</p>}

        {canManage ? (
          <div className="flex flex-wrap items-center gap-3">
            <ToggleSwitch
              label="Auto-recharge"
              checked={data.enabled}
              disabled={!confirmed || fieldProblem !== null || save.isPending}
              onChange={(next) => persist(next)}
            />
            {!confirmed && (
              <>
                <select
                  aria-label="Payment method to approve"
                  className={FIELD}
                  value={method}
                  onChange={(e) => setMethod(e.target.value === "card" ? "card" : "upi")}
                >
                  <option value="upi">UPI Autopay</option>
                  <option value="card">Debit or credit card</option>
                </select>
                <button
                  type="button"
                  className={PRIMARY_BUTTON}
                  disabled={fieldProblem !== null || start.isPending}
                  onClick={() => void approve()}
                >
                  Approve a payment method (₹1)
                </button>
              </>
            )}
            {(confirmed || data.mandate_status === "paused") && (
              <button
                type="button"
                className={SECONDARY_BUTTON}
                disabled={withdraw.isPending}
                onClick={() => withdraw.mutate()}
              >
                Withdraw approval
              </button>
            )}
          </div>
        ) : (
          <p className="text-sm text-ink-muted">
            {write.reason ?? "Only the account owner can change auto-recharge."}
          </p>
        )}

        {windowNote && <p className="text-sm text-ink-muted">{windowNote}</p>}
        <ProblemNotice error={save.error ?? start.error ?? confirm.error ?? withdraw.error} />

        {charges.data && charges.data.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold text-ink">Recent automatic top-ups</h3>
            <ul className="mt-2 divide-y divide-line text-sm">
              {charges.data.map((charge) => (
                <li key={charge.created_at} className="flex justify-between py-2">
                  <span>{formatIST(charge.created_at)}</span>
                  <span>
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
    </Card>
  );
}
