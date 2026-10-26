"use client";

import { useEffect, useState } from "react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { FIELD, ProblemNotice, formatINR } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { rupeeFault } from "@/lib/api/credits";
import { useWriteAccess } from "@/lib/api/hooks";
import { useSetLowBalanceAlert, type Wallet } from "@/lib/api/wallet";

/**
 * THE LOW-CREDIT WARNING LINE. The owner is emailed, and the dashboard says so, when the
 * balance falls below it. "0" stops that warning; the one that says credit has RUN OUT is
 * always sent, because that is when calls stop. Money stays a decimal string (hard rule 7).
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
  // "0" is a real answer here: it switches the low warning off.
  const problem =
    fault === "missing"
      ? "Enter an amount, or 0 to stop this warning."
      : fault === "shape"
        ? "Digits only, like 500 or 500.50 — no commas or ₹ sign."
        : null;
  const off = fault === "zero";
  const changed = line.trim() !== wallet.low_balance_threshold_inr;

  return (
    <Section
      title="Low-credit warning"
      info="We email the account owner once each time the balance drops below this. When credit runs out you are always told, whatever this says."
    >
      <SettingRows className="border-y border-line">
        <SettingRow
          label="Warn me below (₹)"
          htmlFor="low-balance-line"
          hint={
            off
              ? "Only the warning that credit has run out will be sent."
              : wallet.low_balance_alert_chosen
                ? "Your own choice."
                : `Calevate's usual line, ${formatINR(wallet.low_balance_threshold_inr)}.`
          }
          action={
            wallet.low_balance_alert_chosen && write.allowed ? (
              <button
                type="button"
                className={TEXT_ACTION}
                disabled={save.isPending}
                onClick={() => feedback.run(null)}
              >
                Use Calevate&apos;s
              </button>
            ) : undefined
          }
          control={
            <input
              id="low-balance-line"
              inputMode="decimal"
              value={line}
              disabled={!write.allowed}
              aria-invalid={problem ? true : undefined}
              aria-describedby={problem ? "low-balance-line-problem" : undefined}
              onChange={(e) => setLine(e.target.value)}
              className={`${FIELD} w-32 text-right`}
            />
          }
        />
      </SettingRows>
      {problem && (
        <p id="low-balance-line-problem" className="mt-2 text-meta text-warn">
          {problem}
        </p>
      )}
      {save.error ? <ProblemNotice error={save.error} /> : null}
      {changed && (
        <div className="mt-3">
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
        </div>
      )}
    </Section>
  );
}
