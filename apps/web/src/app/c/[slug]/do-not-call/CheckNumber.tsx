"use client";

import { type ReactNode } from "react";
import { CheckCircle2, PhoneOff, Search, ShieldAlert } from "lucide-react";

import {
  Card,
  FIELD_INLINE_ICON,
  NOTICE_TONES,
  PRIMARY_BUTTON_SM,
  ProblemNotice,
  type NoticeTone,
} from "@/components/ui";
import { useFormValidation } from "@/components/formValidation";
import { useCheckDncNumber } from "@/lib/api/dnc";
import { type Session } from "@/lib/api/client";

/**
 * "Did we stop calling this person?" — the question everybody arrives with, and the one
 * thing every session on this account may do (`leads:read`, so it survives a D-22
 * read-only support session).
 *
 * **Checking a number is a POST.** The number is the personal data; a GET would put it in
 * browser history, access logs and the referrer of the next page. It never goes in the
 * URL, and the answer is held in component state, not a query cache.
 */
export function CheckNumber({
  session,
  phone,
  onPhoneChange,
}: {
  session: Session;
  phone: string;
  onPhoneChange: (next: string) => void;
}) {
  const check = useCheckDncNumber(session);
  const valid = useFormValidation();

  return (
    <Card title="Check a number">
      <p className="text-sm text-ink-muted">
        This asks the same question the system asks itself before it dials, so the
        answer cannot disagree with what actually happens. Anyone with access to this
        account can check.
      </p>
      <form
        className="mt-3 flex flex-wrap items-center gap-2"
        noValidate
        onSubmit={valid.onSubmit(() => {
          // POST with the number in the BODY. Never a query string, never the URL —
          // the number is the personal data (see the API's dnc_routes docstring).
          check.mutate(phone.trim());
        })}
      >
        {/* `min-w-0`: this wrapper is a flex item, and a flex item defaults to
            `min-width: auto` — so it took the search input's intrinsic ~256px width
            and would not shrink into the 254px row at 320px. The input's own
            `max-w-full` can only cap it once the wrapper is allowed to give. */}
        <div className="relative min-w-0">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
          <input
            {...valid.field("phone", "Enter the number to check.")}
            required
            value={phone}
            onChange={(e) => {
              onPhoneChange(e.target.value);
              // A stale verdict beside a changed number is worse than no verdict.
              check.reset();
            }}
            minLength={8}
            maxLength={20}
            inputMode="tel"
            autoComplete="off"
            placeholder="9876543210 or +919876543210"
            aria-label="Phone number to check"
            className={`${FIELD_INLINE_ICON} w-64 font-mono`}
          />
          {valid.error("phone")}
        </div>
        <button
          type="submit"
          /* The length rule is answered at the field now, so the button stays live and
             a press produces a sentence rather than nothing. */
          disabled={check.isPending}
          className={PRIMARY_BUTTON_SM}
        >
          {check.isPending ? "Checking…" : "Check"}
        </button>
      </form>

      {check.error != null && (
        <div className="mt-3">
          <ProblemNotice error={check.error} />
        </div>
      )}

      {/* A failed check renders the notice above and NOTHING else: "not on the
          do-not-call list" is the single most dangerous sentence this screen can print
          about a request that never landed. */}
      {check.data && (
        <div className="mt-3">
          {!check.data.valid ? (
            <Verdict tone="warn" icon={<ShieldAlert className="h-4 w-4" />}>
              That does not look like a phone number we can dial. Indian mobiles work
              as ten digits, or write the full number starting with +.
            </Verdict>
          ) : check.data.suppressed ? (
            <Verdict tone="stop" icon={<PhoneOff className="h-4 w-4" />}>
              This number is suppressed — no agent will call it.
              {check.data.scope === "global"
                ? " Calevate has suppressed it across the whole platform, so it cannot be removed from this account."
                : " It was added to your account's list."}
            </Verdict>
          ) : (
            <Verdict tone="ok" icon={<CheckCircle2 className="h-4 w-4" />}>
              This number is not on the do-not-call list. Other checks — calling hours,
              consent — still apply to any actual call.
            </Verdict>
          )}
        </div>
      )}
    </Card>
  );
}

/**
 * A compliance verdict, in the four tones `NOTICE_TONES` already defines.
 *
 * Local rather than shared for the reason ui.tsx gives at `NOTICE_TONES`: only the
 * palette is common between screens, the shape is not. (This one carries an icon and one
 * paragraph; the consent screen's carries two.)
 */
function Verdict({
  tone,
  icon,
  children,
}: {
  tone: NoticeTone;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <p className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${NOTICE_TONES[tone]}`}>
      <span className="mt-0.5 shrink-0" aria-hidden>
        {icon}
      </span>
      <span>{children}</span>
    </p>
  );
}
