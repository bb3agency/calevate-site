"use client";


import { NoticeBox } from "@/components/ui";

/**
 * The wallet header for an account still on the retired invoiced motion.
 *
 * Since D-707 every client buys prepaid credits and the migration moved every invoiced
 * account onto them, so this only renders for an account that has not been moved yet (the
 * tier is admitted for one more release). It says what is happening rather than offering
 * a balance about nothing: invoices already issued stand, and new calling is paid from
 * credit.
 */
export function InvoicedAccount() {
  return (
    // One notice, not a notice and a stray line under its border: the reassurance belongs
    // to the same message.
    <NoticeBox tone="neutral" title="Moving to prepaid calling credit">
      <p>Invoices already sent stay valid. No new ones.</p>
      <p className="mt-1 text-ink-muted">Nothing on your account is lost.</p>
    </NoticeBox>
  );
}
