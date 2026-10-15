"use client";

/**
 * "I already send WhatsApp through another company": where to find the key in each
 * provider we connect to, step by step, then the existing Add-a-key form (D-784).
 *
 * The menu paths are the providers' own, read 15 Oct 2026:
 * - AiSensy: "Go to manage > API Key > Copy the key"; a message is sent through a Live
 *   API campaign whose name is the template (aisensy.com/tutorials/api-reference-docs).
 * - Interakt: "The API Key will be available in your Interakt Dashboard in Developer
 *   Settings"; public APIs are not on the Starter plan (interakt.shop/resource-center/
 *   how-to-send-whatsapp-templates-using-apis-webhooks).
 * - Meta: Business Settings > System users > Add, assign the app with Manage app, Generate
 *   token with `business_management`, `whatsapp_business_management` and
 *   `whatsapp_business_messaging` (developers.facebook.com/documentation/business-messaging/
 *   whatsapp/access-tokens.md, as quoted in docs/evidence/whatsapp-onboarding-2026-10.md).
 *
 * The "illustration" of each step is the menu path drawn as the clicks a person makes, never
 * a picture of the provider's screen: their screens change, and a fake screenshot would be a
 * claim about someone else's product.
 */

import { ChevronRight } from "lucide-react";
import { useState } from "react";

import { ServiceLogo } from "@/components/console/serviceLogo";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { SECONDARY_BUTTON_SM } from "@/components/ui";

import type { KeyKind } from "../../agents/actions/params";

type GuideKind = Extract<KeyKind, "aisensy" | "interakt" | "meta_cloud">;

type Step = { text: string; path?: string[] };

const GUIDES: Record<GuideKind, { label: string; steps: Step[]; note: string }> = {
  aisensy: {
    label: "AiSensy",
    steps: [
      { text: "Sign in to AiSensy and open the menu.", path: ["Manage", "API Key"] },
      { text: "Copy the key." },
      { text: "For each message your agent sends, set up an API campaign with your approved template and make it Live." },
      { text: "Paste the key here. On the action, type the campaign's name." },
    ],
    note: "AiSensy sends one Live API campaign per message.",
  },
  interakt: {
    label: "Interakt",
    steps: [
      { text: "Sign in to Interakt and open your settings.", path: ["Settings", "Developer Settings"] },
      { text: "Copy the key shown there." },
      { text: "Paste the key here. On the action, type the template name and its language." },
    ],
    note: "Interakt's API is not on its Starter plan.",
  },
  meta_cloud: {
    label: "Meta (WhatsApp Cloud API)",
    steps: [
      {
        text: "In Meta Business Settings, add a system user.",
        path: ["Business Settings", "System users", "Add"],
      },
      { text: "Assign your WhatsApp app to it with Manage app." },
      {
        text: "Generate a token with the three permissions Meta lists for business management, WhatsApp management and WhatsApp messaging. Choose how long it lasts: when it expires, your messages stop until you paste a new one.",
      },
      { text: "Copy the Phone number ID.", path: ["WhatsApp Manager", "API Setup"] },
      { text: "Paste the token here. On the action, add the Phone number ID." },
    ],
    note: "This needs a Meta app in your own business account. If you do not have one, connect through Meta above instead.",
  },
};

const ORDER: GuideKind[] = ["aisensy", "interakt", "meta_cloud"];

function MenuPath({ path }: { path: string[] }) {
  return (
    <span aria-label={`Menu path: ${path.join(", then ")}`} className="mt-1 flex flex-wrap items-center gap-1 text-meta">
      {path.map((part, i) => (
        <span key={part} className="inline-flex items-center gap-1">
          {i > 0 && <ChevronRight aria-hidden className="h-3 w-3 text-ink-faint" />}
          <span className="rounded-md border border-line px-1.5 py-0.5 font-medium text-ink">{part}</span>
        </span>
      ))}
    </span>
  );
}

export function KeyGuides({
  canWrite,
  onPasteKey,
}: {
  canWrite: boolean;
  onPasteKey: (kind: GuideKind) => void;
}) {
  const [kind, setKind] = useState<GuideKind>("aisensy");
  const guide = GUIDES[kind];
  return (
    <div className="space-y-4">
      <SegmentedControl
        label="Your WhatsApp provider"
        value={kind}
        onValueChange={(next) => setKind(next as GuideKind)}
        options={ORDER.map((k) => ({ value: k, label: GUIDES[k].label }))}
      />
      <div className="flex items-start gap-3">
        <ServiceLogo service={kind} className="mt-0.5 h-5 w-5" />
        <ol className="min-w-0 flex-1 space-y-3">
          {guide.steps.map((step, i) => (
            <li key={step.text} className="flex gap-3">
              <span
                aria-hidden
                className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border border-line text-meta text-ink-muted"
              >
                {i + 1}
              </span>
              <span className="min-w-0 text-body text-ink">
                {step.text}
                {step.path && <MenuPath path={step.path} />}
              </span>
            </li>
          ))}
        </ol>
      </div>
      <p className="text-meta text-ink-muted">{guide.note}</p>
      <button type="button" className={SECONDARY_BUTTON_SM} disabled={!canWrite} onClick={() => onPasteKey(kind)}>
        Paste the {kind === "meta_cloud" ? "token" : "key"}
      </button>
    </div>
  );
}
