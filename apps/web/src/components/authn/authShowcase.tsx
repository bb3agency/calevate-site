/**
 * The desktop panel beside the client realm's sign-in and setup forms: the product, shown.
 *
 * Two slices of the console a client is signing in to — a live call and the lead it left —
 * built from the same mockup parts as the home page, with the same illustrative clinic.
 * Exposed to assistive technology as one image with a short name, because to a screen
 * reader the content is decoration beside a form, not something to read through.
 */

import { CallCard, LeadCapturedCard } from "@/components/marketing/home/mockups/callCards";

export function AuthShowcase() {
  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-6 px-10 py-12">
      <div className="space-y-2">
        <p className="text-balance text-xl font-semibold tracking-tight text-ink">
          Every call answered. Every lead written down.
        </p>
        <p className="text-sm text-ink-muted">
          Your agent picks up in your customer&apos;s language and fills in the details
          your team asked for.
        </p>
      </div>
      <div role="img" aria-label="A live call with a business's agent, and the lead it captured" className="flex flex-col gap-3">
        <CallCard turns={2} />
        <LeadCapturedCard className="ml-8" />
      </div>
      <p className="text-xs text-ink-muted">Illustration, not a real customer.</p>
    </div>
  );
}
