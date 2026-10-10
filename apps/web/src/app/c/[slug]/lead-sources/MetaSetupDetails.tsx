"use client";

import { useState, type ReactNode } from "react";
import { Eye, EyeOff, Inbox, ShieldAlert } from "lucide-react";

import { CopyButton } from "@/components/interior/copy-button";
import { NOTICE_TONES } from "@/components/ui";
import { API_BASE } from "@/lib/api/client";
import type { MetaSetup } from "@/lib/api/leadSources";

import { CODE, QUIET_BUTTON } from "./styles";

/**
 * The setup card's result — capability first, credential last and hidden.
 *
 * Order is the argument. `lead_retrieval_available` is an answer about THIS lead source,
 * not about the platform: the Graph adapter exists, but reading the answers a person
 * typed into a form needs a Page access token attached to this source, and until one is
 * every verified delivery lands as a RECORDED refusal. Someone about to spend twenty
 * minutes in the Meta App Dashboard should read that before they start, not discover it
 * in the rejections column afterwards — which is why the notice sits above the
 * credentials rather than in a footnote (the same argument `payment_capability` makes
 * about rendering a pay button for a deployment that cannot take payments).
 *
 * The reason code is SHOWN rather than translated into prose per value. It is the exact
 * string the deliveries table below prints against the refusal and the one support will
 * ask for, and a client-side lookup table would be a second place for that vocabulary to
 * live — the first time the server added a reason, this screen would confidently render
 * the wrong sentence for it.
 *
 * The verify token is treated as the credential the endpoint's own docstring says it
 * is: not fetched until asked for, never interpolated into a URL, and masked until
 * someone explicitly reveals it. It goes in Meta's "Verify token" FIELD — the callback
 * URL below carries no secret at all, which is what makes it safe to display.
 */
export function MetaSetupDetails({ setup }: { setup: MetaSetup }) {
  const [revealed, setRevealed] = useState(false);
  // Absolute, because Meta needs a URL it can reach; built from the API base and the
  // server's own path so the two cannot disagree. It carries no credential — the token
  // goes in Meta's own field, and putting it here instead would publish it in every
  // access log between Meta and us.
  const callbackUrl = `${API_BASE}${setup.callback_path}`;

  return (
    <div className="mt-4 space-y-4">
      {setup.lead_retrieval_available ? (
        <div className={`rounded-md border px-3 py-2 text-body ${NOTICE_TONES.ok}`}>
          <p className="font-medium">Lead answers will be collected.</p>
          <p className="mt-1">
            Once Meta accepts the details below, each verified delivery becomes a lead
            with the fields the person filled in.
          </p>
        </div>
      ) : (
        <div className={`rounded-md border px-3 py-2 text-body ${NOTICE_TONES.warn}`}>
          <p className="flex items-center gap-1.5 font-medium">
            <ShieldAlert className="h-4 w-4 shrink-0" aria-hidden />
            Read this first: lead answers are not collected yet.
          </p>
          <p className="mt-1">
            We verify each notification Meta sends and record it, so you will see every
            delivery below. But fetching what
            the person actually typed into your form needs a Meta Page access token for
            this lead source, and we do not hold one yet — so each lead is recorded as{" "}
            <span className="font-mono text-meta">
              {setup.lead_retrieval_reason ?? "unavailable"}
            </span>{" "}
            instead of becoming a lead you can call. Nothing is lost: every delivery is
            kept against its Meta lead ID and is claimed once the token is in place.
            Talk to us before pointing live ad spend at this — attaching it is a step we
            do for you, and it takes minutes.
          </p>
        </div>
      )}

      <dl className="space-y-3">
        <SetupRow label="Callback URL" hint="Paste into “Callback URL” in the Meta App Dashboard.">
          <CopyableValue value={callbackUrl} />
        </SetupRow>

        <SetupRow
          label="Verify token"
          hint="Paste into “Verify token”. It belongs in that field only — never in the URL."
        >
          <div className="flex flex-wrap items-center gap-2">
            <code className={CODE}>{revealed ? setup.verify_token : "•".repeat(24)}</code>
            <button
              type="button"
              onClick={() => setRevealed((value) => !value)}
              className={QUIET_BUTTON}
            >
              {revealed ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              {revealed ? "Hide" : "Reveal"}
            </button>
            <CopyButton value={setup.verify_token} label="Copy verify token" />
          </div>
        </SetupRow>

        <SetupRow
          label="Subscribe your Page to"
          hint="The field to tick when you subscribe your Page."
        >
          <code className={CODE}>{setup.subscribe_field}</code>
        </SetupRow>

        <SetupRow
          label="Signature header"
          hint="Every delivery is checked against this before we read a single field of it."
        >
          <code className={CODE}>{setup.signature_header}</code>
        </SetupRow>
      </dl>

      {/* These details are what you PASTE somewhere else. Nothing in this response has
          seen Meta, so none of it is evidence that the connection works — and a client
          who reads a filled-in setup card as "connected" will point ad spend at a
          handshake that never completed. The inbox is the only witness. */}
      <p className="flex items-start gap-2 text-meta text-ink-muted">
        <Inbox className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        Showing these details does not connect anything, and we cannot see your Meta
        setup from here. The first row in “Recent deliveries” is what tells you it
        worked.
      </p>
    </div>
  );
}
function SetupRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <div>
      <dt className="text-body font-medium text-ink">{label}</dt>
      <dd className="mt-1">{children}</dd>
      <p className="mt-1 text-meta text-ink-faint">{hint}</p>
    </div>
  );
}

function CopyableValue({ value }: { value: string }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <code className={CODE}>{value}</code>
      <CopyButton value={value} label="Copy callback URL" />
    </div>
  );
}
