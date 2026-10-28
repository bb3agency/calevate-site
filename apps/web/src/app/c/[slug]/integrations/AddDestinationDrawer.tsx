"use client";

import { useId, useState } from "react";
import { Webhook } from "lucide-react";

import { Drawer } from "@/components/console/drawer";
import { IconTile } from "@/components/console/iconTile";
import { InfoTip } from "@/components/console/infoTip";
import { PRIMARY_BUTTON } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import type { WriteAccess } from "@/lib/api/hooks";
import type { EndpointOptions } from "@/lib/api/integrations";

import { ChoiceCards } from "@/components/console/choiceCards";
import { CopyRow } from "../lead-sources/IssuedSecretNotice";
import { SheetsForm, SheetsUnavailable } from "./SheetsForm";
import { WebhookForm } from "./WebhookForm";

const KINDS = [
  { value: "webhook", label: "Send events to your own system", hint: "Your CRM or any web address." },
  { value: "sheet", label: "Send events to a Google Sheet", hint: "A row per event." },
] as const;

/**
 * ADD A DESTINATION: your own system (a signed webhook) or a Google Sheet.
 *
 * Both forms are built from ONE read (`options`), rendered by the screen only once it has
 * answered, so neither can offer a subscription the server no longer accepts. "Sheets is
 * not available" is likewise the server's selector, never a conclusion from silence. The
 * webhook's success step is the one moment its signing secret exists in plaintext.
 */
export function AddDestinationDrawer({
  open,
  onClose,
  session,
  options,
  write,
}: {
  open: boolean;
  onClose: () => void;
  session: Session;
  options: EndpointOptions;
  write: WriteAccess;
}) {
  const name = useId();
  const [kind, setKind] = useState<"webhook" | "sheet">("webhook");
  const [secret, setSecret] = useState<string | null>(null);

  const close = () => {
    setSecret(null);
    onClose();
  };

  return (
    <Drawer
      open={open}
      onClose={close}
      title={secret ? "Your signing secret" : "Add a destination"}
      width="lg"
      footer={
        secret ? (
          <button type="button" onClick={close} className={PRIMARY_BUTTON}>
            I&apos;ve saved it
          </button>
        ) : undefined
      }
    >
      {secret ? (
        <div className="space-y-3 text-body">
          <p className="font-medium text-ink">Copy this now — we will not show it again.</p>
          <CopyRow label="Signing secret" value={secret} copyLabel="Copy signing secret" />
          <p className="flex items-center gap-1 text-meta text-ink-muted">
            <span>
              Check the <code>X-Calevate-Signature</code> header on every request.
            </span>
            <InfoTip label="How to verify a delivery">
              It is the HMAC-SHA256 of <code>{"{timestamp}.{body}"}</code> using this secret.
              Reject anything older than five minutes.
            </InfoTip>
          </p>
        </div>
      ) : (
        <div className="space-y-5">
          <ChoiceCards
            legend="Where to send events"
            legendClassName="sr-only"
            name={name}
            value={kind}
            options={KINDS.map((option) => ({
              ...option,
              icon: <IconTile service={option.value === "sheet" ? "google_sheets" : null} icon={Webhook} />,
            }))}
            onChange={setKind}
            columns="sm:grid-cols-2"
          />
          {kind === "webhook" ? (
            <WebhookForm session={session} catalogue={options.events} write={write} onSecret={setSecret} />
          ) : options.sheets_delivery_available ? (
            <SheetsForm session={session} catalogue={options.events} write={write} />
          ) : (
            // The server's boolean, rendered; the words name the remediation the API's own
            // refusal names, so a client who meets both hears one story.
            <SheetsUnavailable
              headline="Google Sheets delivery is not switched on for your account."
              remediation="Send to your own system, or ask us to switch it on."
              footnote="This form appears once Sheets is on."
            />
          )}
        </div>
      )}
    </Drawer>
  );
}
