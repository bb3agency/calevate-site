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
    <div className="space-y-2">
      <NoticeBox tone="neutral" title="Moving to prepaid calling credit">
        Invoices we already sent stay valid and are honoured as issued. No new monthly invoices
        are raised.
      </NoticeBox>
      <p className="max-w-prose text-meta text-ink-muted">
        We will finish the move with you. Nothing on your account is lost.
      </p>
    </div>
  );
}
