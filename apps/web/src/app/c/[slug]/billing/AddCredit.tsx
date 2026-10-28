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
      description="1 credit = ₹1. Pick a pack."
      width="lg"
    >
      {billingRefused ? (
        <RestrictionNote reason="Only the account owner can add credit." />
      ) : (
        <TopUp session={session} />
      )}
    </Drawer>
  );
}
