"use client";

import { FileText } from "lucide-react";

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
      <NoticeBox
        tone="neutral"
        icon={<FileText className="h-4 w-4" aria-hidden />}
        title="This account is moving to prepaid calling credit"
      >
        <p className="mt-1">
          Every Calevate account now pays for calls from prepaid credit. Invoices we have
          already sent you stay valid and are honoured as issued, and no new monthly
          invoices are raised.
        </p>
      </NoticeBox>
      <p className="max-w-prose text-meta text-ink-muted">
        We will finish the move with you. Nothing on your account is lost.
      </p>
    </div>
  );
}
