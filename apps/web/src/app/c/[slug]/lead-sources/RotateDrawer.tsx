"use client";

import { useId, useState } from "react";

import { Drawer } from "@/components/console/drawer";
import { FieldMessage, useFormValidation } from "@/components/formValidation";
import { PasswordInput } from "@/components/passwordInput";
import { FIELD_LABEL, PRIMARY_BUTTON, ProblemNotice, SECONDARY_BUTTON } from "@/components/ui";
import type { LeadSource, useRotateLeadSourceSecret } from "@/lib/api/leadSources";

import { IssuedSecretNotice, type IssuedSecret } from "./IssuedSecretNotice";
import { rowName } from "./SourcesList";
import { META_SOURCE } from "./sourceKinds";
import { FIELD } from "./styles";

/**
 * A NEW SECRET for one source, with a grace window for the old one.
 *
 * The default window is an hour: a planned rotation, where the client still has to paste
 * the new value into a form vendor. Zero is a revocation and is named for what it costs, so
 * nobody picks it because it sounds tidiest and drops the leads submitted meanwhile.
 * A refused rotation keeps the drawer open with the pasted App Secret in place.
 */
export function RotateDrawer({
  source,
  onClose,
  rotate,
}: {
  source: LeadSource | null;
  onClose: () => void;
  rotate: ReturnType<typeof useRotateLeadSourceSecret>;
}) {
  const formId = useId();
  const [grace, setGrace] = useState("60");
  const [appSecret, setAppSecret] = useState("");
  const [issued, setIssued] = useState<IssuedSecret | null>(null);
  const valid = useFormValidation();
  const appSecretTrack = valid.track("appSecret", "Paste the new Meta App Secret.");
  const errorId = `${useId()}-new-app-secret-error`;
  const isMeta = source?.source === META_SOURCE;

  const close = () => {
    setIssued(null);
    setAppSecret("");
    setGrace("60");
    rotate.reset();
    onClose();
  };

  return (
    <Drawer
      open={source !== null}
      onClose={close}
      title={issued ? "New secret issued" : "Issue a new secret"}
      description={source ? rowName(source) : undefined}
      footer={
        issued ? (
          <button type="button" onClick={close} className={PRIMARY_BUTTON}>
            I&apos;ve saved it
          </button>
        ) : (
          <>
            <button type="button" onClick={close} className={SECONDARY_BUTTON}>
              Cancel
            </button>
            <button type="submit" form={formId} disabled={rotate.isPending} className={PRIMARY_BUTTON}>
              {rotate.isPending ? "Issuing…" : "Issue new secret"}
            </button>
          </>
        )
      }
    >
      {issued ? (
        <IssuedSecretNotice issued={issued} />
      ) : (
        source && (
          <form
            id={formId}
            noValidate
            className="space-y-4"
            onSubmit={valid.onSubmit(() =>
              rotate.mutate(
                {
                  webhookId: source.id,
                  graceMinutes: Number(grace),
                  appSecret: isMeta ? appSecret.trim() || undefined : undefined,
                },
                {
                  onSuccess: (result) => {
                    setIssued({
                      secret: result.secret,
                      header: result.secret_header,
                      path: null,
                      expiresAt: result.previous_secret_expires_at,
                    });
                    setAppSecret("");
                  },
                },
              ),
            )}
          >
            {rotate.error != null && <ProblemNotice error={rotate.error} />}
            {isMeta && (
              <div className="text-xs text-ink-muted">
                <span className={FIELD_LABEL}>Your new Meta App Secret</span>
                <PasswordInput
                  inputRef={appSecretTrack.ref}
                  onInput={appSecretTrack.onInput}
                  required
                  aria-label="New Meta App Secret"
                  aria-invalid={valid.message("appSecret") ? true : undefined}
                  aria-describedby={valid.message("appSecret") ? errorId : undefined}
                  reveals="new app secret"
                  value={appSecret}
                  onChange={(e) => setAppSecret(e.target.value)}
                  wrapperClassName="mt-1 block w-full"
                  className={`${FIELD} font-mono`}
                />
                {valid.message("appSecret") ? (
                  <FieldMessage id={errorId}>{valid.message("appSecret")}</FieldMessage>
                ) : null}
              </div>
            )}
            <label className="block">
              <span className={FIELD_LABEL}>Keep the old secret working for</span>
              <select
                aria-label="How long the old secret keeps working"
                value={grace}
                onChange={(e) => setGrace(e.target.value)}
                className={`${FIELD} mt-1 block w-full`}
              >
                <option value="60">1 hour (recommended)</option>
                <option value="1440">24 hours</option>
                <option value="0">Stop it immediately — my secret leaked</option>
              </select>
            </label>
          </form>
        )
      )}
    </Drawer>
  );
}
