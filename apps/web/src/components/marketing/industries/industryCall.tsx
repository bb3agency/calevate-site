import { lookup } from "@/lib/lookup";
import { Chip, MaskedPhone, StatusPill, Tag, Window } from "@/components/marketing/home/mockups/kit";

/**
 * One call per trade, opened the way the console opens it — `app/c/[slug]/calls/[callId]`:
 * the header (number, status, outcome, the "date · duration · direction" line), the
 * "Transcript" card with "Agent"/"Caller" turns, and the "Captured details" and "Summary"
 * cards beside it.
 *
 * `captured` uses the trade's `VERTICAL_TEMPLATES` labels from `scripts/seed.py`, all of
 * them and in the seed's order (`tests/industryMockups.test.ts` diffs them against
 * `lib/marketing/industries.ts`, which `publicLanding.test.tsx` diffs against the seed).
 * Values are what the console prints: an enum's words rather than its snake_case value, a
 * yes/no field as "Yes"/"No", `Budget (lakhs)` as a bare number because the unit is in the
 * label.
 *
 * Every agent's first line carries the AI disclosure and the recording notice, because
 * both are volunteered by default (D-163, hard rule 5). The four calls are in the three
 * languages the product offers; a non-English turn carries its `lang` so a screen reader
 * switches voice, with the English under it. Outcomes are the console's `outcome_tag`
 * words ("resolved", "needs follow up") and a call-derived lead arrives as `new` — nothing
 * here is promoted to `hot`, because the pipeline only does that off an urgency or intent
 * field none of these templates filled with a trigger value (`apps/workers/pipeline.py`
 * `HOT_LEAD_FIELD_TRIGGERS`).
 */

type Lang = "te" | "hi" | "en";

interface CallTurn {
  readonly who: "Agent" | "Caller";
  /** The words as spoken. */
  readonly said: string;
  /** The English under it; absent when the call was in English. */
  readonly en?: string;
}

interface IndustryCall {
  readonly business: string;
  readonly lang: Lang;
  readonly language: string;
  readonly tail: string;
  readonly meta: string;
  readonly outcome: "resolved" | "needs follow up";
  readonly turns: readonly CallTurn[];
  readonly captured: readonly (readonly [label: string, value: string])[];
  readonly summary: string;
  readonly action: { readonly label: string; readonly tone: "emerald" | "sky" };
}

export const INDUSTRY_CALLS: Record<string, IndustryCall> = {
  clinics: {
    business: "Sunrise Dental",
    lang: "te",
    language: "Telugu",
    tail: "123",
    meta: "Today, 10:42 AM · 2:14 · inbound",
    outcome: "resolved",
    turns: [
      {
        who: "Agent",
        said: "నమస్కారం, Sunrise Dental. నేను AI అసిస్టెంట్‌ని, ఈ కాల్ రికార్డ్ చేయబడుతోంది. మీకు ఎలా సహాయం చేయగలను?",
        en: "Namaskaram, Sunrise Dental. I am an AI assistant, and this call is recorded. How can I help?",
      },
      {
        who: "Caller",
        said: "పంటి నొప్పిగా ఉంది, రూట్ కెనాల్ కావాలేమో. డాక్టర్ రావు గారు ఉంటారా?",
        en: "My tooth hurts, I may need a root canal. Is Dr Rao available?",
      },
      {
        who: "Agent",
        said: "ఉంటారు. ఈ వారంలో ఏ రోజు మీకు వీలవుతుంది?",
        en: "He is. Which day this week suits you?",
      },
      {
        who: "Caller",
        said: "మంగళవారం సాయంత్రం 6కి. ఇన్సూరెన్స్ లేదు, క్యాష్ కడతాను.",
        en: "Tuesday at 6 in the evening. No insurance, I will pay cash.",
      },
      {
        who: "Agent",
        said: "మంగళవారం సాయంత్రం 6 గంటలకు డాక్టర్ రావు గారితో బుక్ చేశాను.",
        en: "Booked with Dr Rao for Tuesday at 6 PM.",
      },
    ],
    captured: [
      ["Symptom / reason", "Root canal"],
      ["Preferred doctor", "Dr Rao"],
      ["Urgency", "this week"],
      ["Preferred slot", "Tuesday 6pm"],
      ["Insurance", "Cash"],
    ],
    summary:
      "Priya has tooth pain and may need a root canal. Asked for Dr Rao; booked for Tuesday evening, paying cash.",
    action: { label: "Check-up booked", tone: "emerald" },
  },
  property: {
    business: "Gachibowli Homes",
    lang: "te",
    language: "Telugu",
    tail: "418",
    meta: "Today, 7:18 PM · 3:02 · inbound",
    outcome: "resolved",
    turns: [
      {
        who: "Agent",
        said: "నమస్కారం, Gachibowli Homes. నేను AI అసిస్టెంట్‌ని, ఈ కాల్ రికార్డ్ చేయబడుతోంది. మీకు ఎలాంటి ఇల్లు కావాలి?",
        en: "Namaskaram, Gachibowli Homes. I am an AI assistant, and this call is recorded. What kind of home are you looking for?",
      },
      {
        who: "Caller",
        said: "గచ్చిబౌలిలో 3BHK కావాలి. బడ్జెట్ 80 లక్షల వరకు.",
        en: "A 3BHK in Gachibowli. Budget up to 80 lakhs.",
      },
      {
        who: "Agent",
        said: "ఎప్పటిలోగా తీసుకోవాలనుకుంటున్నారు?",
        en: "By when are you looking to buy?",
      },
      {
        who: "Caller",
        said: "ఈ నెలలోనే.",
        en: "This month itself.",
      },
      {
        who: "Agent",
        said: "శనివారం సైట్ విజిట్ బుక్ చేయనా?",
        en: "Shall I book a site visit for Saturday?",
      },
      {
        who: "Caller",
        said: "సరే, శనివారం ఉదయం.",
        en: "Okay, Saturday morning.",
      },
    ],
    captured: [
      ["Budget (lakhs)", "80"],
      ["Location", "Gachibowli"],
      ["BHK", "3BHK"],
      ["Timeline", "this month"],
      ["Site visit", "Yes"],
    ],
    summary:
      "Kiran wants a 3BHK in Gachibowli, up to 80 lakhs, buying this month. Agreed to a site visit on Saturday morning.",
    action: { label: "Site visit: Sat", tone: "emerald" },
  },
  insurance: {
    business: "Suraksha Advisors",
    lang: "en",
    language: "English",
    tail: "552",
    meta: "Yesterday, 4:05 PM · 2:41 · inbound",
    outcome: "needs follow up",
    turns: [
      {
        who: "Agent",
        said: "Hello, Suraksha Advisors. I am an AI assistant, and this call is recorded. How can I help?",
      },
      {
        who: "Caller",
        said: "My health policy is up for renewal soon, and I want more cover this time.",
      },
      {
        who: "Agent",
        said: "Of course. How much cover are you thinking of, and when is the current policy due?",
      },
      {
        who: "Caller",
        said: "Around ten lakh. It is due in about three weeks, with another company.",
      },
      {
        who: "Agent",
        said: "Thank you. Shall your advisor call you back on Thursday at 11 AM to go through it?",
      },
      { who: "Caller", said: "Yes, Thursday is fine." },
    ],
    captured: [
      ["Policy type", "health"],
      ["Sum assured", "10 lakh"],
      ["Renewal due", "22 Oct"],
      ["Existing insurer", "Another company"],
    ],
    summary:
      "Health policy due for renewal in three weeks with another insurer; wants around ten lakh of cover. Call-back booked for Thursday.",
    action: { label: "Call-back: Thu 11 AM", tone: "sky" },
  },
  coaching: {
    business: "Vision Academy",
    lang: "hi",
    language: "Hindi",
    tail: "907",
    meta: "Today, 11:26 AM · 1:58 · inbound",
    outcome: "resolved",
    turns: [
      {
        who: "Agent",
        said: "नमस्ते, Vision Academy. मैं एक AI असिस्टेंट हूँ, और यह कॉल रिकॉर्ड की जा रही है। मैं आपकी क्या मदद कर सकती हूँ?",
        en: "Namaste, Vision Academy. I am an AI assistant, and this call is recorded. How can I help?",
      },
      {
        who: "Caller",
        said: "मेरा बेटा NEET दोबारा देना चाहता है। उसने इस साल 12वीं पास की है।",
        en: "My son wants to sit NEET again. He finished Class 12 this year.",
      },
      {
        who: "Agent",
        said: "हमारा रिपीटर बैच है। क्या वह शुक्रवार को एक डेमो क्लास में बैठना चाहेगा?",
        en: "We have a repeater batch. Would he like to sit in on a demo class on Friday?",
      },
      {
        who: "Caller",
        said: "हाँ। फ़ीस कितनी है?",
        en: "Yes. What are the fees?",
      },
      {
        who: "Agent",
        said: "फ़ीस की पूरी जानकारी काउंसलर देंगे। शुक्रवार शाम 5 बजे का डेमो बुक कर दिया है।",
        en: "The counsellor will go through the fees. I have booked the demo for Friday at 5 PM.",
      },
    ],
    captured: [
      ["Course", "NEET repeater"],
      ["Class / year", "Class 12"],
      ["Fee concern", "Yes"],
      ["Demo booked", "Yes"],
    ],
    summary:
      "Parent asking about the NEET repeater batch for a son who finished Class 12. Asked about fees; demo class booked for Friday.",
    action: { label: "Demo: Friday", tone: "emerald" },
  },
};

function ConversationTurn({
  turn,
  lang,
  className = "",
}: {
  turn: CallTurn;
  lang: Lang;
  className?: string;
}) {
  const agent = turn.who === "Agent";
  return (
    <span className={`flex ${agent ? "justify-start" : "justify-end"} ${className}`}>
      <span
        className={`flex max-w-[88%] flex-col gap-0.5 rounded-xl px-3 py-2 ${
          agent ? "rounded-bl-sm bg-brand-soft dark:bg-brand-strong/20" : "rounded-br-sm bg-slate-100 dark:bg-white/[0.06]"
        }`}
      >
        <span className={`text-[11px] font-semibold ${agent ? "text-brand-strong dark:text-brand-bright" : "text-slate-600 dark:text-slate-300"}`}>
          {turn.who}
        </span>
        <span lang={lang} className="text-[13px] leading-snug text-ink">
          {turn.said}
        </span>
        {turn.en && <span className="text-[11px] leading-snug text-ink-muted">{turn.en}</span>}
      </span>
    </span>
  );
}

/** The opened call for one trade. Stacks below `md`; side column beside it from `md`. */
export function IndustryCallMock({ id }: { id: string }) {
  const call = lookup(INDUSTRY_CALLS, id);
  if (!call) return null;
  return (
    <Window title="Call logs" actions={<Chip tone="brand">{call.language}</Chip>}>
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line px-4 py-3 sm:px-5">
        <MaskedPhone tail={call.tail} className="text-[13px] font-semibold text-ink" />
        <Tag tone="emerald">completed</Tag>
        <Tag tone={call.outcome === "resolved" ? "brand" : "amber"}>{call.outcome}</Tag>
        <span className="w-full text-[11px] text-ink-muted lg:ml-auto lg:w-auto">
          {call.business} · {call.meta}
        </span>
      </span>
      <span className="flex flex-col md:flex-row">
        <span className="flex min-w-0 flex-1 flex-col gap-2 p-4 sm:p-5">
          <span className="text-[12px] font-semibold text-ink">Transcript</span>
          {call.turns.map((turn, i) => (
            <ConversationTurn
              key={turn.said}
              turn={turn}
              lang={call.lang}
              className={`mk-rise mk-s${Math.min(i + 1, 6)}`}
            />
          ))}
        </span>
        <span className="flex flex-col gap-3 border-t border-line bg-app/50 p-4 sm:p-5 md:w-64 md:shrink-0 md:border-t-0 md:border-l xl:w-72">
          <span className="mk-rise mk-s2 flex flex-col rounded-lg border border-line bg-surface">
            <span className="border-b border-line px-3 py-2 text-[11px] font-semibold text-ink-muted">
              Captured details
            </span>
            {call.captured.map(([label, value]) => (
              <span key={label} className="flex items-center justify-between gap-3 px-3 py-1.5 text-[12px]">
                <span className="shrink-0 text-ink-muted">{label}</span>
                <span className="truncate font-semibold text-ink">{value}</span>
              </span>
            ))}
          </span>
          <span className="mk-rise mk-s3 flex flex-col gap-1.5 rounded-lg border border-line bg-surface p-3">
            <span className="text-[11px] font-semibold text-ink-muted">Summary</span>
            <span className="text-[12px] leading-snug text-ink">{call.summary}</span>
          </span>
          <span className="mk-rise mk-s4 flex flex-wrap items-center gap-2 rounded-lg border border-brand/30 bg-surface p-3">
            <span className="text-[11px] font-semibold text-ink-muted">Lead</span>
            <StatusPill status="new" />
            <Tag tone={call.action.tone}>{call.action.label}</Tag>
          </span>
        </span>
      </span>
    </Window>
  );
}
