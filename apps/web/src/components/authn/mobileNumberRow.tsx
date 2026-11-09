"use client";

/**
 * The Mobile number row of the client account page (D-976): add, change or remove the
 * number on the person's own login.
 *
 * No code is sent to the number yet, so a typo would be stored and every WhatsApp alert or
 * payment approval would go to a stranger. The guard is a second look: the form never saves
 * what was typed, it shows the number back ("Is this right?") and saves only from there.
 * "Change" goes back to the field with the typing kept.
 *
 * The number arrives on `GET /v1/me` (`phone`); the write answers only what changed, so a
 * save refreshes that read rather than trusting the screen's own copy.
 */

import { useEffect, useRef, useState, type FormEvent } from "react";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { AuthField, AuthProblemNotice } from "@/components/authn/fields";
import { ConfirmDialog } from "@/components/confirmDialog";
import { TEXT_ACTION, TEXT_ACTION_DANGER } from "@/components/console/section";
import { SettingRow } from "@/components/console/settingRow";
import { formatPhone } from "@/components/ui";
import {
  MOBILE_NUMBER_ANCHOR,
  MOBILE_NUMBER_INVALID,
  MOBILE_NUMBER_USE,
  normaliseMobileNumber,
  setOwnMobileNumber,
  type MobileNumberChange,
} from "@/lib/authn/mobileNumber";

type Step = "closed" | "typing" | "checking";

/** What the row says once a save lands. A new number needs the alert agreement again. */
function savedLine(change: MobileNumberChange): string {
  if (change === "removed") return "Mobile number removed.";
  if (change === "changed") return "Saved. Turn WhatsApp alerts on again for the new number.";
  return "Mobile number saved.";
}

export function MobileNumberRow({ phone }: { phone: string | null }) {
  const client = useQueryClient();
  const [step, setStep] = useState<Step>("closed");
  const [typed, setTyped] = useState("");
  const [attempted, setAttempted] = useState(false);
  const [removing, setRemoving] = useState(false);
  const openButton = useRef<HTMLButtonElement>(null);
  const field = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (step === "typing") field.current?.focus();
  }, [step]);

  // Arriving from "Add your mobile number" (Alerts, auto top-up): the row is drawn after
  // `/v1/me` answers, too late for the browser's own jump to the anchor, so it scrolls
  // itself into view, and opens the field when there is no number yet. Once per visit.
  const row = useRef<HTMLDivElement>(null);
  const arrived = useRef(false);
  useEffect(() => {
    if (arrived.current || window.location.hash !== `#${MOBILE_NUMBER_ANCHOR}`) return;
    arrived.current = true;
    row.current?.scrollIntoView?.({ block: "center" });
    if (!phone) setStep("typing");
  }, [phone]);

  const save = useMutation({
    mutationFn: (next: string | null) => setOwnMobileNumber(next),
    onSuccess: async () => {
      // Every read that shows or depends on the number: who am I, and the alert state.
      await Promise.all([
        client.invalidateQueries({ queryKey: ["me"] }),
        client.invalidateQueries({ queryKey: ["whatsapp-alerts"] }),
      ]);
      setRemoving(false);
      close();
    },
  });
  const feedback = useActionFeedback(save, { errorDisplay: "inline" });

  const normalised = normaliseMobileNumber(typed);
  const fieldError =
    attempted && normalised === null && typed.trim() !== "" ? MOBILE_NUMBER_INVALID : null;

  function close(): void {
    setStep("closed");
    setTyped("");
    setAttempted(false);
    window.requestAnimationFrame(() => openButton.current?.focus());
  }

  const value = phone ? (
    <span className="tabular-nums">{formatPhone(phone)}</span>
  ) : (
    <span className="text-ink-muted">Not added</span>
  );

  return (
    <div ref={row} id={MOBILE_NUMBER_ANCHOR} className="scroll-mt-6">
      <SettingRow
        label="Mobile number"
        hint={
          save.isSuccess && step === "closed" ? (
            <span role="status" className="inline-flex items-start gap-1 text-brand-strong dark:text-brand-bright">
              <Check aria-hidden className="mt-1 h-3.5 w-3.5 shrink-0" />
              <span>{savedLine(save.data)}</span>
            </span>
          ) : (
            MOBILE_NUMBER_USE
          )
        }
        value={value}
        action={
          step === "closed" ? (
            <button
              ref={openButton}
              type="button"
              className={TEXT_ACTION}
              aria-label={phone ? "Change your mobile number" : "Add your mobile number"}
              onClick={() => {
                save.reset();
                setStep("typing");
              }}
            >
              {phone ? "Change" : "Add"}
            </button>
          ) : undefined
        }
      />

      {step === "typing" && (
        <form
          aria-label="Your mobile number"
          className="max-w-sm space-y-4 pb-5"
          noValidate
          onSubmit={(event: FormEvent) => {
            event.preventDefault();
            setAttempted(true);
            if (normalised !== null) setStep("checking");
          }}
        >
          <AuthField
            label="Mobile number"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="98765 43210"
            maxLength={32}
            value={typed}
            inputRef={field}
            onChange={(event) => setTyped(event.target.value)}
            onBlur={() => setAttempted(true)}
            hint="Ten digits. Add + and the country code if it is not Indian."
            error={fieldError}
          />
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <ActionButton type="submit" disabled={typed.trim() === ""}>
              Next
            </ActionButton>
            <button type="button" className={TEXT_ACTION} onClick={close}>
              Cancel
            </button>
            {phone && (
              <button
                type="button"
                className={TEXT_ACTION_DANGER}
                onClick={() => {
                  save.reset();
                  setRemoving(true);
                }}
              >
                Remove number
              </button>
            )}
          </div>
        </form>
      )}

      {step === "checking" && normalised !== null && (
        <div className="max-w-sm space-y-4 pb-5">
          <div>
            <p className="text-body text-ink">Is this right?</p>
            <p className="mt-1 text-title tabular-nums text-ink">{formatPhone(normalised)}</p>
            <p className="mt-1 text-meta text-ink-muted">
              We do not send a code to check it, so look at each digit.
            </p>
          </div>
          <AuthProblemNotice error={removing ? null : save.error} />
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <ActionButton
              status={removing ? "idle" : feedback.status}
              pendingLabel="Saving…"
              onClick={() => {
                if (!save.isPending) feedback.run(normalised);
              }}
            >
              Save
            </ActionButton>
            <button
              type="button"
              className={TEXT_ACTION}
              disabled={save.isPending}
              onClick={() => {
                save.reset();
                setStep("typing");
              }}
            >
              Change
            </button>
          </div>
        </div>
      )}

      {removing && (
        <ConfirmDialog
          title="Remove your mobile number?"
          confirmLabel="Remove number"
          pendingLabel="Removing…"
          status={feedback.status}
          error={save.error}
          onCancel={() => {
            save.reset();
            setRemoving(false);
          }}
          onConfirm={() => {
            if (!save.isPending) feedback.run(null);
          }}
        >
          <p>WhatsApp alerts and automatic top-ups stop until you add one again.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
