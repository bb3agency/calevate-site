"use client";

import { useCallback } from "react";

import { useToast } from "@/components/arc/toast";
import { ApiProblem } from "@/lib/api/client";

/** A colleague (or Pip) saved this Follow-up after the person last read it. */
export function isFollowUpConflict(error: unknown): boolean {
  return error instanceof ApiProblem && error.status === 409 && error.code === "follow_up_changed";
}

/**
 * The 409 answer every other screen gives: a warning toast, and the screen already shows
 * the colleague's version because the hooks refetch on settle. Returns whether it handled
 * the error, so the caller shows anything else inline.
 */
export function useConflictToast(): (error: unknown) => boolean {
  const toasts = useToast();
  return useCallback(
    (error: unknown) => {
      if (!isFollowUpConflict(error)) return false;
      toasts.toast({
        kind: "warning",
        title: "A colleague changed this first",
        description: "Nothing was changed. This now shows their version.",
      });
      return true;
    },
    [toasts],
  );
}
