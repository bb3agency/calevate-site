"use client";

/**
 * WHAT HOLDS THE ACCOUNT'S CALLING SETUPS, when a test call, Start or putting a line live
 * found none free (`engine_agent_allowance_full`). The account may have only so many at once
 * in existence, on a call or not; it is not how many calls run together. Each holder is a
 * link to its page with the one move that frees it; one being removed needs nothing.
 *
 * The holders come typed from the server: the refusal's problem+json members
 * (`EngineAgentAllowanceFull`, read with `problemOf`) or the launch check's
 * `BlockerOut.holders`. "Ask us to raise your limit" is the support mailbox, as every other
 * "contact us" on the client screens is (`billing/TopUp.tsx`).
 */

import Link from "next/link";

import { SECONDARY_BUTTON_SM } from "@/components/ui";
import { problemOf } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useClientRealm } from "@/lib/api/session";
import { resolvePlaceholders } from "@/lib/legal/placeholders";

export type SlotHolder = components["schemas"]["SlotHolder"];
type AllowanceContext = components["schemas"]["EngineAgentAllowanceFull"]["context"];

export const SLOTS_FULL_RULE = "engine_agent_allowance_full";

const LEADS: Record<AllowanceContext, string> = {
  test_call: "Test calls need a free calling setup.",
  start: "Starting needs a free calling setup.",
  line_live: "Putting a line live needs a free calling setup.",
};

/** "Test calls need a free calling setup. Your account can have 2, and both are in use:" */
export function slotsFullLead(context: AllowanceContext, limit: number | undefined): string {
  if (limit == null) return `${LEADS[context]} All of yours are in use:`;
  const inUse = limit === 1 ? "it is" : limit === 2 ? "both are" : "all are";
  return `${LEADS[context]} Your account can have ${limit}, and ${inUse} in use:`;
}

/** The mail a "raise your limit" press opens; the subject names the account. */
export function raiseLimitHref(slug: string): string {
  return `mailto:${resolvePlaceholders("{{SUPPORT_EMAIL}}")}?subject=${encodeURIComponent(
    `Raise our calling setup limit (${slug})`,
  )}`;
}

function holderPath(holder: SlotHolder): string {
  if (holder.kind === "inbound_line") return `/inbound/${holder.id}`;
  if (holder.kind === "campaign") return `/campaigns/${holder.id}`;
  return `/agents/${holder.id}`;
}

const KIND_WORDS: Record<SlotHolder["kind"], string> = {
  agent: "Agent",
  inbound_line: "Inbound line",
  campaign: "Campaign",
  script_trial: "Script trial",
};

function FreesIt({ holder, at }: { holder: SlotHolder; at: (path: string) => string }) {
  if (holder.removing) return <>Being removed. Nothing to do.</>;
  if (holder.kind === "inbound_line") return <>Archive the line to free it.</>;
  if (holder.kind === "campaign") return <>Stop the campaign to free it.</>;
  if (holder.kind === "script_trial") return <>Freed when the script trial ends.</>;
  return (
    <>
      It answers your calls until its{" "}
      <Link className="text-brand-strong underline" href={at("/inbound")}>
        Inbound line
      </Link>{" "}
      is live.
    </>
  );
}

/** The holders as links, each with what frees it, and the raise-the-limit button. */
export function SlotHolders({ slug, holders }: { slug: string; holders: readonly SlotHolder[] }) {
  const { href } = useClientRealm();
  const at = (path: string) => href(`/c/${slug}${path}`);
  return (
    <div className="mt-2 space-y-2">
      {holders.length > 0 && (
        <ul aria-label="Calling setups in use" className="space-y-1.5">
          {holders.map((holder, index) => (
            <li key={`${holder.kind}-${holder.id}-${index}`} className="text-meta text-ink-muted">
              <span className="text-ink">{KIND_WORDS[holder.kind]}: </span>
              <Link className="break-words font-medium text-brand-strong underline" href={at(holderPath(holder))}>
                {holder.name || "Untitled"}
              </Link>
              <span className="block sm:ml-2 sm:inline">
                <FreesIt holder={holder} at={at} />
              </span>
            </li>
          ))}
        </ul>
      )}
      <a className={`${SECONDARY_BUTTON_SM} w-full justify-center sm:w-auto`} href={raiseLimitHref(slug)}>
        Ask us to raise your limit
      </a>
    </div>
  );
}

function slotsFull(error: unknown) {
  const full = problemOf<"EngineAgentAllowanceFull">(error, SLOTS_FULL_RULE);
  return full?.context ? { ...full, context: full.context } : undefined;
}

/** Is this error the full-workspace refusal, carrying what holds each setup? */
export function isSlotsFull(error: unknown): boolean {
  return slotsFull(error) !== undefined;
}

/**
 * A refused request's full-workspace answer: the sentence for what was pressed, the holders
 * and the button. Null for any other error, which the caller words as usual.
 */
export function SlotsFullProblem({ slug, error }: { slug: string; error: unknown }) {
  const full = slotsFull(error);
  if (!full) return null;
  return (
    <div role="alert" className="mt-2 text-meta">
      <p className="text-danger">{slotsFullLead(full.context, full.limit)}</p>
      <SlotHolders slug={slug} holders={full.holders ?? []} />
    </div>
  );
}
