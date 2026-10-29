"use client";

import { CopyButton } from "@/components/interior/copy-button";

import { ACCOUNT_MANAGER_PORTALS, sourceLabel } from "./sourceKinds";

/**
 * WHERE TO PASTE THE ADDRESS, for a sender that pushes to one (D-942). Short steps and a
 * copy button per step that needs one — the owner does this once, in another product.
 *
 * The portals' push is switched on by their account manager, so the step there is a
 * ready-made message to send; the field names in it are the ones the preset reads.
 */
export function PushSetup({ source, address }: { source: string; address: string }) {
  if (source === "indiamart") {
    return (
      <Steps
        steps={[
          "In IndiaMART: Lead Manager → Import/Export Leads → Push API.",
          "Paste the address above and activate it.",
          "Press Test there, then check the delivery log here.",
        ]}
      />
    );
  }
  if (source === "leadsquared") {
    return (
      <Steps
        steps={[
          "In LeadSquared, open Settings → API and Webhooks → Webhooks.",
          "Add a Lead Create webhook (JSON) with the address above.",
          "New LeadSquared leads now reach your agent.",
        ]}
      />
    );
  }
  if (ACCOUNT_MANAGER_PORTALS.includes(source)) {
    const portal = sourceLabel(source);
    const message = [
      `Please send our ${portal} leads to this address:`,
      address,
      "As each one arrives, by HTTPS POST (JSON or form).",
      "Fields: name, phone, email, city, project, message, lead_id.",
    ].join("\n");
    return (
      <div className="space-y-2 text-body">
        <Steps
          steps={[
            `Send this address to your ${portal} account manager.`,
            "Once it is on, send a test lead and check the log here.",
          ]}
        />
        <CopyButton variant="text" value={message} label="Copy message for account manager" />
      </div>
    );
  }
  return null;
}

function Steps({ steps }: { steps: string[] }) {
  return (
    <ol className="list-decimal space-y-1 pl-5 text-body text-ink">
      {steps.map((step) => (
        <li key={step}>{step}</li>
      ))}
    </ol>
  );
}
