"use client";

import { useRef } from "react";
import { Printer } from "lucide-react";

import { Drawer } from "@/components/console/drawer";
import { ReceiptDocument } from "@/components/receiptDocument";
import { PRIMARY_BUTTON, ProblemNotice, Skeleton } from "@/components/ui";
import { usePaymentReceipt } from "@/lib/api/wallet";
import type { Session } from "@/lib/api/client";
import { printDocument } from "@/lib/printDocument";

/**
 * One payment's receipt, in the console's shared Drawer.
 *
 * Printed through `printDocument`, which copies ONLY the receipt into a hidden frame:
 * `window.print()` printed the console's fixed-height shell, so a receipt came out as the
 * sidebar, the header and whatever of the sheet fitted on one screen.
 */
export function ReceiptSheet({
  session,
  paymentRef,
  onClose,
}: {
  session: Session;
  paymentRef: string | null;
  onClose: () => void;
}) {
  const receipt = usePaymentReceipt(session, paymentRef);
  const sheet = useRef<HTMLDivElement>(null);

  return (
    <Drawer
      open={paymentRef !== null}
      onClose={onClose}
      title="Payment receipt"
      closeLabel="Close the receipt"
      initialFocus="container"
      footer={
        receipt.data ? (
          <button
            type="button"
            onClick={() => {
              if (sheet.current) {
                void printDocument(sheet.current, { title: `Receipt ${paymentRef ?? ""}`.trim() });
              }
            }}
            className={PRIMARY_BUTTON}
          >
            <Printer className="h-4 w-4" aria-hidden />
            Print or save as PDF
          </button>
        ) : undefined
      }
    >
      {receipt.isLoading && <Skeleton rows={4} label="Loading your receipt" />}
      {receipt.error && (
        <ProblemNotice error={receipt.error} onRetry={() => void receipt.refetch()} />
      )}
      {receipt.data && (
        <div ref={sheet}>
          <ReceiptDocument data={receipt.data} />
        </div>
      )}
    </Drawer>
  );
}
