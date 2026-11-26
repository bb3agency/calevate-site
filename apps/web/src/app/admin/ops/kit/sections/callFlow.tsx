"use client";

import { useState } from "react";

import { ScenarioFlow } from "@/app/c/[slug]/campaigns/ScenarioFlow";
import { ProposalReview } from "@/app/c/[slug]/agents/[agentId]/script/ProposalReview";
import { CALL_BACK, DEFAULT_LIMITS, END, HAND_OVER, validate } from "@/app/c/[slug]/agents/[agentId]/script/scriptModel";
import type { LineWarning } from "@/app/c/[slug]/agents/[agentId]/script/stepExamples";
import { DESKTOP, useMedia } from "@/app/c/[slug]/agents/[agentId]/script/useMedia";
import { EMPTY_SCRIPT, type CallScript, type ConversationStage } from "@/lib/api/script";

import { KitDemo, KitSection } from "../kitLayout";

const stage = (over: Partial<ConversationStage> & Pick<ConversationStage, "id" | "name" | "step">): ConversationStage => ({
  mode: "guide",
  instruction: "",
  sounds_like: "",
  branches: [],
  otherwise: "",
  collect: [],
  procedure: [],
  position: null,
  scripts: {},
  qa: [],
  coaching: [],
  ...over,
});

/**
 * An eight-step onboarding call of the shape owners write: most scenarios have a way out to
 * an end point (busy, not interested, wants a person), a few go on to another step, and one
 * stays where it is until the caller picks a language.
 */
const ONBOARDING: CallScript = {
  ...EMPTY_SCRIPT,
  schema_version: 2,
  opening_line: "Namaste, this is the farm app's help desk. Is now a good time for two minutes?",
  stages: [
    stage({
      id: "intro",
      name: "Introduction",
      step: 1,
      instruction: "Say why we are calling: to help them start using the app.",
      // Kit lines are English placeholders for the call's language.
      examples: {
        "te-IN": {
          turns: [
            "We are calling to help you start the farm app today.",
            "This call is to get you going on the farm app.",
            "I can help you set up the farm app now. Please open it.",
          ],
          confused: "The farm app on your phone. I will help you open it.",
          stuck: "Look for the green leaf icon on your phone.",
          busy: "No problem. When should I call back?",
        },
      },
      branches: [
        { when: "Busy right now", target: CALL_BACK },
        { when: "Not interested", target: END },
      ],
    }),
    stage({
      id: "home",
      name: "App on home screen",
      step: 2,
      instruction: "Ask them to find the app icon on the home screen and open it.",
      sounds_like: "Please find the farm app on your home screen and open it.",
      branches: [{ when: "Not registered yet", target: "unreg" }],
    }),
    stage({
      id: "unreg",
      name: "Not registered",
      step: 2,
      instruction: "Walk them through signing up with their phone number.",
      branches: [{ when: "Wants to speak to a person", target: HAND_OVER }],
    }),
    stage({
      id: "login",
      name: "Login",
      step: 3,
      instruction: "Help them log in with the one-time code sent to their phone.",
      branches: [{ when: "Code never arrives", target: HAND_OVER }],
    }),
    stage({
      id: "lang",
      name: "Language",
      step: 4,
      instruction: "Ask which language they want the app in and help them pick it.",
      otherwise: "lang",
    }),
    stage({
      id: "farms",
      name: "My Farms",
      step: 5,
      instruction: "Add their first farm: its name, village and acres.",
      branches: [{ when: "Busy, call later", target: CALL_BACK }],
    }),
    stage({
      id: "expense",
      name: "First expense",
      step: 6,
      instruction: "Record one expense together, like seeds or fertiliser.",
      branches: [{ when: "Already added one", target: "dash" }],
    }),
    stage({
      id: "sale",
      name: "First sale",
      step: 7,
      instruction: "Record a sale so they see the profit figure change.",
      branches: [
        { when: "No sale yet", target: "dash" },
        { when: "Busy, call later", target: CALL_BACK },
      ],
    }),
    stage({
      id: "dash",
      name: "Dashboard",
      step: 8,
      instruction: "Show the dashboard: money in, money out, and this season's profit.",
    }),
    stage({
      id: "close",
      name: "Close",
      step: 8,
      instruction: "Thank them and tell them how to reach us again.",
      branches: [
        { when: "Happy with the app", target: END },
        { when: "Has more questions", target: HAND_OVER },
      ],
    }),
  ],
};

const WARNINGS: LineWarning[] = [
  {
    path: "stages.intro.examples.te-IN.turns.2",
    message: "Asks for two things at once.",
    detail: "Give one action and stop. The caller does one thing at a time.",
  },
];

/** The same flow with Pip's examples written on step 2, as a draft to review. */
const WITH_EXAMPLES: CallScript = {
  ...ONBOARDING,
  stages: ONBOARDING.stages.map((s) =>
    s.id === "home"
      ? {
          ...s,
          examples: {
            "te-IN": {
              turns: [
                "Please find the farm app on your home screen.",
                "Look at your home screen for the farm app.",
                "Find the farm app icon on your phone's home screen.",
                "Tell me when you see it, and open it.",
              ],
              confused: "The farm app, on the first screen of your phone.",
              stuck: "Swipe left once and look for the green leaf.",
              busy: "",
            },
          },
        }
      : s,
  ),
};

const WARNINGS_HOME: LineWarning[] = [
  {
    path: "stages.home.examples.te-IN.turns.3",
    message: "Asks them to say when it's done.",
    detail: "Give one action and stop; their own words show it is done.",
  },
];

/** The campaign's call flow, editable here with nothing saved, so it can be looked at. */
export function CallFlowSection() {
  const [script, setScript] = useState<CallScript>(ONBOARDING);
  const [selected, setSelected] = useState<string | null>(null);
  const desktop = useMedia(DESKTOP);
  return (
    <KitSection
      id="call-flow"
      title="Call flow"
      lead="A campaign's script as steps and scenarios. Lines join steps; a way out that ends the call sits on its scenario."
    >
      <KitDemo label="ScenarioFlow · eight steps with ways out" wide>
        <ScenarioFlow
          agent={null}
          hear={{ allowed: false, reason: null, unknown: false }}
          script={script}
          limits={DEFAULT_LIMITS}
          issues={validate(script, DEFAULT_LIMITS)}
          languages={["te-IN"]}
          selected={selected}
          readOnly={false}
          wide={desktop}
          onSelect={setSelected}
          onChange={setScript}
          onEditOpening={() => {}}
          warnings={WARNINGS}
          writeExamples={() => ({ run: () => {}, wait: null })}
        />
      </KitDemo>
      <KitDemo label="ProposalReview · Pip's examples on a step, with a warning on its line" wide>
        <ProposalReview
          current={ONBOARDING}
          proposal={WITH_EXAMPLES}
          languages={[{ tag: "te-IN", name: "Telugu" }]}
          warnings={WARNINGS_HOME}
          onApply={() => {}}
          onDiscard={() => {}}
        />
      </KitDemo>
    </KitSection>
  );
}
