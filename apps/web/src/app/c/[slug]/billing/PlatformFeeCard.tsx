"use client";

import { useState } from "react";

import { Receipt } from "lucide-react";

import {
  Card,
  MonoValue,
  NoticeBox,
  PRIMARY_BUTTON,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  formatINR,
  formatIST,
} from "@/components/ui";
import { useConfirmTopUp } from "@/lib/api/billing";
import { useWriteAccess } from "@/lib/api/hooks";
import {
  feeMonth,
  feeStatusCopy,
  oldestUnpaid,
  platformFeeKey,
  useFeeOrder,
  usePlatformFee,
  type FeeOrder,
  type PlatformFee,
} from "@/lib/api/platformFee";
import { openRazorpayCheckout } from "@/lib/razorpayCheckout";
import { ApiProblem, type Session } from "@/lib/api/client";
import { useQueryClient } from "@tanstack/react-query";

/**
 * The monthly platform fee (D-707), on the client's billing screen.
 *
 * Rendered only when the fee is switched on for the platform, or when this account still
 * has a fee on its record. It is a SEPARATE payment: the card says so, and paying it opens
 * its own checkout for exactly the fee's amount — it never draws on calling credit, and
 * buying credit never pays it. While a fee is unpaid past its grace period OUTGOING calls
 * pause; the card says that incoming calls carry on, because that is the first thing an
 * owner worries about.
 */
export function PlatformFeeCard({ session }: { session: Session }) {
  const fee = usePlatformFee(session);
  if (fee.isLoading) return <Skeleton rows={2} label="Loading the platform fee" />;
  if (fee.error) return <ProblemNotice error={fee.error} onRetry={() => void fee.refetch()} />;
  if (!fee.data) return null;
  if (!fee.data.enabled && fee.data.charges.length === 0) return null;
  return <FeeBody session={session} fee={fee.data} />;
}

type PayStage =
  | { at: "idle" }
  | { at: "opening" }
  | { at: "bank"; order: FeeOrder }
  | { at: "verifying" }
  | { at: "received" }
  | { at: "failed"; problem: ApiProblem };

function FeeBody({ session, fee }: { session: Session; fee: PlatformFee }) {
  const write = useWriteAccess(session, "org:manage", "pay the platform fee");
  const order = useFeeOrder(session);
  const confirm = useConfirmTopUp(session);
  const queries = useQueryClient();
  const [stage, setStage] = useState<PayStage>({ at: "idle" });
  const owed = oldestUnpaid(fee);
  const amount = fee.amount_inr;

  const refresh = () => void queries.invalidateQueries({ queryKey: platformFeeKey(session.orgSlug) });

  const pay = (chargeId: string) => {
    setStage({ at: "opening" });
    order.mutate(chargeId, {
      onError: (error) => setStage({ at: "failed", problem: error as ApiProblem }),
      onSuccess: (data) => {
        if (data.provider_order_id === null) {
          setStage({ at: "bank", order: data });
          return;
        }
        void openRazorpayCheckout({
          keyId: data.key_id,
          orderId: data.provider_order_id,
          amountPaise: data.amount_paise,
          currency: data.currency,
          receipt: data.receipt,
          notes: data.notes,
          purpose: "Monthly platform fee",
          onSuccess: (response) => {
            setStage({ at: "verifying" });
            confirm.mutate(response, {
              onSuccess: () => {
                setStage({ at: "received" });
                refresh();
              },
              onError: (error) => setStage({ at: "failed", problem: error as ApiProblem }),
            });
          },
          onDismissed: () => setStage((now) => (now.at === "opening" ? { at: "idle" } : now)),
          onFailed: () => setStage({ at: "failed", problem: feePaymentFailed() }),
        })
          .then(() => setStage((now) => (now.at === "opening" ? { at: "idle" } : now)))
          .catch((error: unknown) => setStage({ at: "failed", problem: error as ApiProblem }));
      },
    });
  };

  return (
    <Card title="Monthly platform fee">
      <div className="space-y-4">
        <p className="max-w-prose text-body text-ink-muted">
          {amount ? (
            <>
              {formatINR(amount)} a month, paid separately from your calling credit. It never
              comes out of your balance, and buying credit never pays it.
            </>
          ) : (
            "The monthly platform fee is switched off. Nothing is owed for months to come."
          )}
        </p>

        {fee.exemption === "trial" && (
          <NoticeBox tone="ok" title="Not charged during your free trial">
            Your account pays no platform fee while it is on a free trial.
          </NoticeBox>
        )}
        {fee.exemption === "waiver" && (
          <NoticeBox tone="ok" title="Your account is not charged this fee">
            We have waived the monthly platform fee for your account.
          </NoticeBox>
        )}

        {fee.outbound_paused && (
          <NoticeBox tone="stop" title="Outgoing calls are paused">
            This month&apos;s platform fee is unpaid, so your agents are not placing outgoing
            calls. Incoming calls keep being answered. Pay the fee and calling resumes at once.
          </NoticeBox>
        )}

        {owed && (
          <div className="flex flex-wrap items-end justify-between gap-4 rounded-md border border-line p-4">
            <div className="space-y-1">
              <p className="text-meta text-ink-muted">{feeMonth(owed.period)}</p>
              <p className="text-title font-semibold">{formatINR(owed.amount_inr)}</p>
              <p className="text-meta text-ink-muted">
                {owed.status === "overdue"
                  ? `Unpaid since ${formatIST(owed.grace_ends_at)}`
                  : `Pay by ${formatIST(owed.grace_ends_at)} to keep outgoing calls running (${fee.grace_days}-day grace period)`}
              </p>
            </div>
            <div className="space-y-2">
              <button
                type="button"
                className={PRIMARY_BUTTON}
                disabled={!write.allowed || stage.at === "opening" || stage.at === "verifying"}
                onClick={() => pay(owed.id)}
              >
                <Receipt aria-hidden className="h-4 w-4" />
                Pay {formatINR(owed.amount_inr)}
              </button>
              <RestrictionNote reason={write.reason} />
            </div>
          </div>
        )}

        {stage.at === "bank" && (
          <NoticeBox tone="neutral" title="Pay by bank transfer">
            Online payment is not available yet. Transfer {formatINR(stage.order.amount_inr)} and
            quote the reference <MonoValue>{stage.order.receipt}</MonoValue>; we record it as
            soon as it arrives.
          </NoticeBox>
        )}
        {stage.at === "verifying" && <p className="text-meta text-ink-muted">Checking the payment…</p>}
        {stage.at === "received" && (
          <NoticeBox tone="ok" title="Payment received">
            Thank you. The fee shows as paid as soon as the payment is confirmed, usually within
            a minute.
          </NoticeBox>
        )}
        {stage.at === "failed" && <ProblemNotice error={stage.problem} />}
        {order.error != null && stage.at !== "failed" && <ProblemNotice error={order.error} />}
        {confirm.error != null && stage.at !== "failed" && <ProblemNotice error={confirm.error} />}

        {fee.charges.length > 0 && (
          <table className="w-full text-left text-body">
            <caption className="sr-only">Platform fees by month</caption>
            <thead>
              <tr className="text-meta text-ink-muted">
                <th scope="col" className="py-1 font-medium">Month</th>
                <th scope="col" className="py-1 font-medium">Amount</th>
                <th scope="col" className="py-1 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {fee.charges.map((charge) => (
                <tr key={charge.id} className="border-t border-line">
                  <td className="py-2">{feeMonth(charge.period)}</td>
                  <td className="py-2">{formatINR(charge.amount_inr)}</td>
                  <td className="py-2">{feeStatusCopy(charge.status).label}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

function feePaymentFailed(): ApiProblem {
  return new ApiProblem(0, {
    kind: "transient",
    type: "urn:calevate:browser/platform_fee_payment_failed",
    title: "The payment did not go through",
    detail: "The platform fee was not paid.",
    remediation:
      "Try again with the same or a different payment method. If your bank shows the amount " +
      "debited, tell us and we will trace it.",
  });
}
