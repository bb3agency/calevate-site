/**
 * The words this screen writes itself, one short line each (`tests/simpleCopyLegal.test.ts`).
 * The five rules under "How this record works" are compliance wording (SEC-COMP §4) and
 * stay in `HowItWorks.tsx`, inside its disclosure, with their words.
 */
export const CONSENT_COPY = {
  description: "Who agreed to get your WhatsApp messages.",
  separate: "This is a separate permission from calling.",
  descriptionTip: "Follow-ups go only to people recorded here. Calling follows the do-not-call list.",
  recordAnswer: "Record an answer",
  recordWhatTheySaid: "Record what they said",
  drawerTitle: "Record what a customer said",

  lookupHeading: "Can we message this number?",
  lookupTip: "Asks the same question the system asks before it sends a follow-up.",
  lookupLabel: "Phone number to check",
  lookupMissing: "Enter the number to check.",
  check: "Check",
  checked: "Checked",

  yes: "You may send this person WhatsApp messages.",
  until: "Current until",
  expired: "Not messageable — their opt-in has expired.",
  askAgain: "Ask again before messaging them.",
  stopped: "Not messageable — they asked us to stop.",
  declined: "Not messageable — they were asked and said no.",
  none: "Not messageable — nobody has asked them yet.",
  noneSkip: "Campaign follow-ups will skip this number.",
  noneHow: "Record their own answer, not an assumption.",
  unknown: "Not messageable — this record is one we cannot read.",
  unknownQuote: "The system will not message this number. Quote",
  unknownTail: "to us and we will explain.",

  recordIntro: "Nothing is edited or deleted. A new answer replaces the old.",
  numberLabel: "Their number",
  numberMissing: "Enter their number.",
  saidLabel: "What did they say?",
  saidYes: "They agreed to be messaged",
  saidNo: "They do not want messages",
  saidNoHint: "No proof needed. Anyone here can record it.",
  whichNo: "Which kind of no?",
  howKnow: "How do you know?",
  notOnBehalf: "Not on this list: an opt-in has to come from the customer.",
  whichCall: "Which call?",
  callPlaceholder: "Call ID from the Calls page",
  callRequired: "Required for a spoken opt-in.",
  callOptional: "Optional for a refusal.",
  optionalHere: " Optional here.",
  recordYes: "Record their opt-in",
  recordNo: "Record their refusal",
  recorded: "Recorded",
  nowStands: "Saved. Where this number stands now:",
} as const;

export const lapsedOn = (day: string): string => `Lapsed on ${day}.`;
