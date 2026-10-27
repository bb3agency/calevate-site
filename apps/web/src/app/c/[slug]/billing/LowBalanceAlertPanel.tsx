"use client";

import { useEffect, useState } from "react";
import { BellRing } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { TEXT_ACTION } from "@/components/console/section";
import { Disclosure, FIELD, FIELD_HINT, ProblemNotice, formatINR, hasNonZeroDigit } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { rupeeFault } from "@/lib/api/credits";
import { useWriteAccess } from "@/lib/api/hooks";
import { useSetLowBalanceAlert, type Wallet } from "@/lib/api/wallet";

/**
 * THE LOW-CREDIT WARNING LINE. The owner is emailed, and the dashboard says so, when the
 * balance falls below it. "0" stops that warning; the one that says credit has RUN OUT is
 * always sent, because that is when calls stop. Money stays a decimal string (hard rule 7).
 *
 * A collapsed card beside auto top-up: the line it is set to is on the closed row.
 */
/** Only the warning line's two fields: the panel reads nothing else of the wallet. */
export type AlertLine = Pick<Wallet, "low_balance_threshold_inr" | "low_balance_alert_chosen">;

export function LowBalanceAlertPanel({ session, wallet }: { session: Session; wallet: AlertLine }) {
  const write = useWriteAccess(session, "org:manage", "change the low-credit warning");
  const save = useSetLowBalanceAlert(session);
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Saved" });
  const [line, setLine] = useState(wallet.low_balance_threshold_inr);
  useEffect(() => setLine(wallet.low_balance_threshold_inr), [wallet.low_balance_threshold_inr]);

  const fault = rupeeFault(line);
  const problem =
    fault === "missing"
      ? "Enter an amount, or 0 to stop this warning."
      : fault === "shape"
        ? "Digits only, like 500 or 500.50 — no commas or ₹ sign."
        : null;
  const off = fault === "zero";
  const changed = line.trim() !== wallet.low_balance_threshold_inr;

  return (
    <Disclosure
      title="Low-credit email"
      icon={<BellRing className="h-4 w-4" />}
      status={
        hasNonZeroDigit(wallet.low_balance_threshold_inr)
          ? `Below ${formatINR(wallet.low_balance_threshold_inr)}`
          : "Off"
      }
      subtitle="We email the owner once when the balance drops below this line"
      showLabel="Change"
      hideLabel="Close"
    >
      <div className="settings-enter space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="low-balance-line" className="block text-meta font-medium text-ink">
              Warn me below (₹)
            </label>
            <input
              id="low-balance-line"
              inputMode="decimal"
              value={line}
              disabled={!write.allowed}
              aria-invalid={problem ? true : undefined}
              aria-describedby="low-balance-line-hint"
              onChange={(e) => setLine(e.target.value)}
              className={`${FIELD} w-36 tabular-nums`}
            />
          </div>
          {changed && (
            <ActionButton
              type="button"
              status={feedback.status}
              disabled={!write.allowed || problem !== null}
              pendingLabel="Saving…"
              successLabel="Saved"
              onClick={() => feedback.run(line.trim())}
            >
              Save
            </ActionButton>
          )}
          {wallet.low_balance_alert_chosen && write.allowed && (
            <button
              type="button"
              className={TEXT_ACTION}
              disabled={save.isPending}
              onClick={() => feedback.run(null)}
            >
              Use Calevate&apos;s
            </button>
          )}
        </div>
        <p id="low-balance-line-hint" className={problem ? "text-meta text-warn" : FIELD_HINT}>
          {problem ??
            (off
              ? "Only the warning that credit has run out will be sent."
              : wallet.low_balance_alert_chosen
                ? "Your own choice. Running out is always emailed, whatever this says."
                : `Calevate's usual line, ${formatINR(wallet.low_balance_threshold_inr)}. Running out is always emailed.`)}
        </p>
        {save.error ? <ProblemNotice error={save.error} /> : null}
      </div>
    </Disclosure>
  );
}
