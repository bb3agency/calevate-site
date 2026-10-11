"use client";

import { InfoTip } from "@/components/console/infoTip";
import { CopyButton } from "@/components/interior/copy-button";
import { Disclosure, ProblemNotice, Skeleton, formatPhone } from "@/components/ui";
import {
  renderCode,
  useForwardingCodes,
  type CarrierGuide,
  type Carrier,
  type ForwardingCode,
  type ForwardingMode,
  type LineKind,
} from "@/lib/api/forwarding";
import type { Session } from "@/lib/api/client";

import { CARRIER_LABEL, CONDITION_LABEL } from "./copy";

const EVIDENCE_LABEL: Record<ForwardingCode["evidence"], string> = {
  carrier_own: "from the provider's own page",
  standards_body: "from the phone-network standard",
  web_secondary: "from forwarding guides, not the provider",
};

/** Which codes switch the chosen mode on: the three conditional forwards, or all calls. */
function activating(codes: ForwardingCode[], mode: ForwardingMode): ForwardingCode[] {
  const wanted = mode === "all_calls" ? ["all_calls"] : ["no_answer", "busy", "unreachable"];
  return wanted
    .map((condition) => codes.find((code) => code.condition === condition))
    .filter((code): code is ForwardingCode => code !== undefined && code.activate != null);
}

function CodeRow({ label, code }: { label: string; code: string }) {
  return (
    <li className="flex items-center justify-between gap-3 py-2.5">
      <div className="min-w-0">
        <p className="text-meta text-ink-muted">{label}</p>
        <p className="font-mono text-body tabular-nums text-ink [overflow-wrap:anywhere]">{code}</p>
      </div>
      <CopyButton value={code} label={`Copy the code: ${label}`} />
    </li>
  );
}

function CodeList({
  codes,
  numberE164,
  seconds,
  deactivate = false,
}: {
  codes: ForwardingCode[];
  numberE164: string;
  seconds: number;
  deactivate?: boolean;
}) {
  return (
    <ul className="divide-y divide-line border-y border-line">
      {codes.map((code, index) => {
        const text = deactivate ? code.deactivate : renderCode(code.activate, numberE164, seconds);
        if (!text) return null;
        return (
          <CodeRow key={`${code.condition}-${index}`} label={CONDITION_LABEL[code.condition] ?? code.condition} code={text} />
        );
      })}
    </ul>
  );
}

/**
 * THE CODES FOR ONE PHONE: what to dial once to switch the chosen forward on, and what
 * switches it off, with the Calevate number and ring time filled in. Copy buttons only:
 * a `tel:` link holding `*` or `#` is not dialled on an iPhone. Where a provider publishes
 * no codes (Jio) or the line is set by its provider (a landline, an office system), the
 * screen says so instead of guessing.
 */
export function ForwardingCodes({
  session,
  carrier,
  lineKind,
  mode,
  seconds,
  calevateNumber,
  headingLevel = 3,
}: {
  session: Session;
  carrier: Carrier;
  lineKind: LineKind;
  mode: ForwardingMode;
  seconds: number;
  calevateNumber: string;
  headingLevel?: 2 | 3 | 4;
}) {
  const catalogue = useForwardingCodes(session);
  if (catalogue.isLoading) return <Skeleton rows={3} label="Loading the codes" />;
  if (catalogue.error || !catalogue.data) {
    return <ProblemNotice error={catalogue.error} onRetry={() => void catalogue.refetch()} />;
  }
  const guide: CarrierGuide =
    lineKind === "mobile"
      ? (catalogue.data.carriers.find((g) => g.carrier === carrier) ?? catalogue.data.provider)
      : catalogue.data.provider;
  const number = formatPhone(calevateNumber);
  const when =
    mode === "all_calls"
      ? "every call"
      : `calls you don't answer within ${seconds} seconds, calls while you are busy, and calls when your phone is off`;

  if (guide.method === "ask_provider") {
    return (
      <div className="space-y-2">
        <p className="text-body text-ink">
          Ask your phone provider to enable call divert to <span className="font-mono tabular-nums">{number}</span> for {when}.
        </p>
        <p className="text-meta text-ink-muted">Office phone systems set this in the system itself.</p>
      </div>
    );
  }

  const sources = new Set(guide.codes.map((code) => code.evidence));
  return (
    <div className="space-y-4">
      {guide.method === "app" ? (
        <div className="space-y-1">
          <p className="text-body text-ink">
            {CARRIER_LABEL[carrier]} sets forwarding in its app or your phone&apos;s settings. Forward {when} to{" "}
            <span className="font-mono tabular-nums">{number}</span>.
          </p>
          {guide.app_path && <p className="text-meta text-ink-muted">{guide.app_path}</p>}
        </div>
      ) : (
        <div>
          <div className="flex items-center gap-1">
            <p className="text-body font-medium text-ink">
              {mode === "all_calls" ? "Dial this once" : "Dial these once, one after the other"}
            </p>
            <InfoTip label="Where these codes come from">
              {[...sources].map((source) => `Codes ${EVIDENCE_LABEL[source]}.`).join(" ")} The ring time
              is the phone-network standard&apos;s. You set them once; they stay on until you switch them off.
            </InfoTip>
          </div>
          <div className="mt-2">
            <CodeList codes={activating(guide.codes, mode)} numberE164={calevateNumber} seconds={seconds} />
          </div>
          {guide.note && <p className="mt-2 text-meta text-ink-muted">{guide.note}</p>}
        </div>
      )}

      {guide.unconfirmed.length > 0 && (
        <Disclosure
          title="Codes other sites give"
          subtitle="Not from the provider. Check in its app first."
          variant="inline"
          headingLevel={headingLevel === 2 ? 3 : 4}
        >
          <div className="space-y-3">
            {guide.unconfirmed.map((set) => (
              <div key={set.label}>
                <p className="text-meta font-medium text-ink">{set.label}</p>
                <CodeList
                  codes={set.label === "Standard codes" ? activating(set.codes, mode) : set.codes.filter((c) => c.activate)}
                  numberE164={calevateNumber}
                  seconds={seconds}
                />
              </div>
            ))}
          </div>
        </Disclosure>
      )}

      {guide.method === "codes" && (
        <Disclosure title="To switch it off" variant="inline" headingLevel={headingLevel === 2 ? 3 : 4}>
          <CodeList
            codes={guide.codes.filter((code) =>
              mode === "all_calls" ? code.condition === "all_calls" || code.condition === "everything" : code.condition !== "all_calls",
            )}
            numberE164={calevateNumber}
            seconds={seconds}
            deactivate
          />
        </Disclosure>
      )}
    </div>
  );
}
