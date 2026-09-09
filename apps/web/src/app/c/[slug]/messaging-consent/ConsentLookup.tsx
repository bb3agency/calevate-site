"use client";

import { Search } from "lucide-react";

import {
  Card,
  FIELD_INLINE_ICON,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";

import { Verdict } from "./Verdict";
import { type ConsentForm } from "./consentForm";

/**
 * "Can we message this number?" — the question people arrive with, and the one thing
 * every session on this account may do (`leads:read`, so it survives a D-22 read-only
 * support session).
 */
export function ConsentLookup({ form }: { form: ConsentForm }) {
  /* Two forms on this screen, two `useFormValidation` instances: one refusal must never
     mark the other's field, and the ids the hook mints are per instance. */
  const valid = useFormValidation();
  const { lookup } = form;

  return (
    <Card title="Can we message this number?">
      <p className="text-sm text-ink-muted">
        Asks the same question the system asks itself before it sends a follow-up, so
        the answer cannot disagree with what actually happens.
      </p>
      <form
        className="mt-3 flex flex-wrap items-center gap-2"
        noValidate
        onSubmit={valid.onSubmit(() => {
          lookup.mutate(form.lookupPhone.trim());
        })}
      >
        {/* `min-w-0`: this wrapper is a flex item, and a flex item defaults to
            `min-width: auto` — so it took the search input's intrinsic ~256px width
            and would not shrink into the 254px row at 320px. The input's own
            `max-w-full` can only cap it once the wrapper is allowed to give. */}
        <div className="relative min-w-0">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
          <input
            {...valid.field("lookupPhone", "Enter the number to check.")}
            required
            value={form.lookupPhone}
            onChange={(e) => {
              form.setLookupPhone(e.target.value);
              // A stale verdict beside a changed number is worse than no verdict.
              // (TanStack Query v5 `reset()` clears mutation state —
              // tanstack.com/query/v5/docs/framework/react/reference/useMutation)
              lookup.reset();
            }}
            minLength={8}
            maxLength={20}
            inputMode="tel"
            autoComplete="off"
            placeholder="9876543210 or +919876543210"
            aria-label="Phone number to check"
            className={`${FIELD_INLINE_ICON} w-64 font-mono`}
          />
          {valid.error("lookupPhone")}
        </div>
        <button
          type="submit"
          /* The length rule is not repeated here — a button that is dead at seven
             digits explains nothing, and pressing it now says what is wrong. */
          disabled={lookup.isPending}
          className={PRIMARY_BUTTON_SM}
        >
          {lookup.isPending ? "Checking…" : "Check"}
        </button>
      </form>

      {/* A failed lookup is a refusal and nothing else. Every verdict this box can
          render is a claim about a PERSON's wishes; none of them may be printed on the
          strength of a request that never landed. */}
      {lookup.error != null && (
        <div className="mt-3">
          <ProblemNotice error={lookup.error} />
        </div>
      )}
      {lookup.data && (
        <div className="mt-3">
          <Verdict state={lookup.data} />
        </div>
      )}
    </Card>
  );
}
