import type { LegalDocument } from "./types";

/**
 * The Refund and Cancellation Policy.
 *
 * Required as a published page by Indian payment aggregators at merchant onboarding —
 * alongside a privacy policy, terms, and real contact details — which is why it is a
 * document of its own rather than a clause in the Terms.
 *
 * The one structural fact that shapes it: the billing ledgers are append-only, so a refund
 * in this system is a NEW compensating entry rather than an edit of the entry it corrects
 * (`apps/api/billing/service.py`). That is why the policy talks about credit notes and
 * compensating entries rather than about "reversing" a charge — the product cannot reverse
 * one, by design, and a policy promising otherwise would describe a different product.
 */
export const REFUND_POLICY: LegalDocument = {
  slug: "refunds",
  title: "Refund & Cancellation Policy",
  shortTitle: "Refunds & Cancellation",
  summary:
    "When money comes back, when it does not, how to cancel, and how long a refund " +
    "takes.",
  appliesTo: "Every Calevate client. It forms part of the Terms of Service.",
  sections: [
    {
      id: "scope",
      heading: "1. What this covers",
      blocks: [
        {
          kind: "para",
          text:
            "Calevate is a subscription software service with metered telephone usage. " +
            "There is nothing physical to ship or return, so this policy is about money " +
            "rather than goods. It covers both ways of buying:",
        },
        {
          kind: "definitions",
          items: [
            {
              term: "Managed engagements",
              detail:
                "A one-off setup fee, a monthly fee with a stated number of included " +
                "minutes, and a per-minute rate for minutes beyond that. Invoiced in " +
                "arrears against a signed order form.",
            },
            {
              term: "Self-serve accounts",
              detail:
                "You top up a credit balance in advance, and calls draw it down as they " +
                "are metered.",
            },
          ],
        },
      ],
    },
    {
      id: "cancellation",
      heading: "2. Cancelling",
      subsections: [
        {
          id: "cancel-managed",
          heading: "2.1 A managed engagement",
          blocks: [
            {
              kind: "para",
              text:
                "Give us {{TERMINATION_NOTICE_DAYS}} days' written notice to " +
                "{{SUPPORT_EMAIL}}, expiring at the end of a billing month. The service " +
                "runs to the end of the notice period and you are invoiced for it, " +
                "including any usage in it. Nothing renews after that.",
            },
          ],
        },
        {
          id: "cancel-self-serve",
          heading: "2.2 A self-serve account",
          blocks: [
            {
              kind: "para",
              text:
                "Close it at any time from the dashboard or by writing to " +
                "{{SUPPORT_EMAIL}}. There is no notice period and no cancellation fee. " +
                "Closing stops future calls; it does not undo calls already made.",
            },
          ],
        },
        {
          id: "cancel-us",
          heading: "2.3 If we end it",
          blocks: [
            {
              kind: "para",
              text:
                "If we terminate for convenience, or you terminate because we materially " +
                "breached and did not fix it, we refund the unused portion of any prepaid " +
                "fee for the period after termination, and any unused credit balance in " +
                "full. If we terminate because you breached the Acceptable Use Policy, " +
                "prepaid fees for the remaining period are not refunded — but any unused " +
                "credit balance still is, less any amount you owe us.",
            },
          ],
        },
      ],
    },
    {
      id: "refundable",
      heading: "3. What we refund",
      blocks: [
        {
          kind: "list",
          items: [
            "A duplicate payment — you were charged twice for the same thing. Refunded in " +
              "full, and we do not require you to ask: we look for these.",
            "A payment that succeeded at the gateway but was not credited to your account. " +
              "Refunded or credited, whichever you prefer.",
            "An amount charged in error by us, including a metering fault. Corrected by a " +
              "credit note, and refunded to the payment instrument if you would rather " +
              "have the money than the credit.",
            "Unused credit on a self-serve account you close, less anything you owe us. " +
              "Credit purchased under a promotion or granted as goodwill has no cash value " +
              "and is not refundable.",
            "Prepaid fees for a period after we terminate for convenience, or after you " +
              "terminate for our material unremedied breach.",
            "Prepaid unused fees for a period after you terminate because you did not " +
              "accept an amendment to the Terms or a new sub-processor.",
          ],
        },
      ],
    },
    {
      id: "non-refundable",
      heading: "4. What we do not refund, and why",
      blocks: [
        {
          kind: "list",
          items: [
            "Minutes already used. The call happened, the carrier and the model providers " +
              "were paid for it, and the cost is not recoverable by us.",
            "The setup fee once the work it pays for has started — configuring your agent, " +
              "building your knowledge base, and running your Principal Entity " +
              "registration. If you cancel before that work starts, it is refunded in full.",
            "Third-party charges we incurred on your instruction: number rentals, " +
              "registration fees paid to an access provider, template approval charges. " +
              "These are paid onward and are not recoverable, and we will show you the " +
              "pass-through if you ask.",
            "A month already invoiced and consumed, where the complaint is about how well " +
              "the AI performed rather than about a fault in the service. See the note " +
              "below.",
            "Fees for a period during which the service was suspended because you breached " +
              "the Acceptable Use Policy, or because a registration you rely on lapsed.",
          ],
        },
        {
          kind: "callout",
          tone: "note",
          title: "About performance complaints",
          text:
            "An AI agent will sometimes mishear, mis-extract or answer badly, and the " +
            "Terms disclaim the accuracy of what it produces. That is not a licence to " +
            "charge you for a service that did not work: if the agent was genuinely not " +
            "functioning — it did not answer calls, it could not hear callers, extraction " +
            "failed wholesale — tell us and we will investigate the call records and issue " +
            "a credit for the affected period. What we will not do is refund a month " +
            "because a proportion of leads were imperfect, because that is the product " +
            "working as described.",
        },
      ],
    },
    {
      id: "how",
      heading: "5. How a refund is made, and how long it takes",
      blocks: [
        {
          kind: "list",
          ordered: true,
          items: [
            "Write to {{SUPPORT_EMAIL}} with the invoice number or the payment reference, " +
              "the amount, and what went wrong. There is no form.",
            "We acknowledge within 2 business days and tell you our decision within 7 " +
              "business days. If we need longer we will say so and why.",
            "An approved refund goes back to the original payment instrument — we cannot " +
              "send it anywhere else, and neither can the payment gateway.",
            "The gateway then takes {{REFUND_PROCESSING_DAYS}} business days to place the " +
              "money back with your bank or card issuer. Your bank may take longer to show " +
              "it, and that part is outside our control.",
            "Where GST was charged, the refund is accompanied by a credit note under " +
              "section 34 of the CGST Act referencing the original invoice, so your books " +
              "and ours agree.",
          ],
        },
        {
          kind: "callout",
          tone: "note",
          title: "Why a refund appears as a new entry rather than as a reversal",
          text:
            "Our billing ledgers are append-only by design: nothing already recorded is " +
            "edited or deleted, and a correction is a new entry of the opposite sign that " +
            "references the one it corrects. So on your statement you will see the " +
            "original charge and a separate compensating entry, not a charge that has " +
            "vanished. This is deliberate — it means your billing history can always be " +
            "re-derived and never quietly changes underneath you.",
        },
      ],
    },
    {
      id: "disputes",
      heading: "6. If you disagree, and chargebacks",
      blocks: [
        {
          kind: "para",
          text:
            "Tell us first — {{SUPPORT_EMAIL}}, or the Grievance Officer if you would " +
            "rather escalate. The grievance page states the timetable we hold ourselves to.",
        },
        {
          kind: "para",
          text:
            "If you raise a chargeback with your card issuer we will respond with the " +
            "usage and billing records. Raising a chargeback for a charge that is " +
            "genuinely owed is a breach of the Terms, and we may suspend the account while " +
            "it is resolved. Nothing here removes your right to go to a consumer forum or " +
            "to your card issuer; we would simply rather fix it ourselves.",
        },
      ],
    },
    {
      id: "contact",
      heading: "7. Contact",
      blocks: [
        {
          kind: "definitions",
          items: [
            { term: "Refunds and billing", detail: "{{SUPPORT_EMAIL}}, {{CONTACT_PHONE}}" },
            {
              term: "Escalation",
              detail:
                "{{GRIEVANCE_OFFICER_NAME}}, {{GRIEVANCE_OFFICER_DESIGNATION}}, " +
                "{{GRIEVANCE_OFFICER_EMAIL}}",
            },
            { term: "By post", detail: "{{LEGAL_ENTITY_NAME}}, {{REGISTERED_ADDRESS}}" },
          ],
        },
      ],
    },
  ],
};
