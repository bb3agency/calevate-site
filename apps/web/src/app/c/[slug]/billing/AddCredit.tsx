"use client";

import { Drawer } from "@/components/console/drawer";
import { RestrictionNote } from "@/components/ui";
import type { Session } from "@/lib/api/client";

import { TopUp } from "./TopUp";

/**
 * Adding credit, in a drawer over the summary card: the pack picker and the payment outcome
 * (`TopUp`). A drawer rather than a view because it is a short job done from the balance,
 * and the balance should still be there, updated, when it closes.
 */
export function AddCreditDrawer({
  session,
  open,
  onClose,
  billingRefused,
}: {
  session: Session;
  open: boolean;
  onClose: () => void;
  billingRefused: boolean;
}) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Add credit"
      description="1 credit is ₹1. Choose a pack or your own amount."
      width="lg"
    >
      {billingRefused ? (
        <RestrictionNote reason="Prices and payment are limited to the account owner. Ask them to top up the account, or to give you owner access." />
      ) : (
        <TopUp session={session} />
      )}
    </Drawer>
  );
}
