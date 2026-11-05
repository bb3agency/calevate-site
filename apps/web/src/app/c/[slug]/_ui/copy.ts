/**
 * THE DEFAULT-VIEW WORDS of the home, attention, go-live, setup and first-agent screens, in
 * one place so `tests/simpleCopy.test.ts` can hold every line to the short-line rule (about
 * 60 characters). Words behind a "Why?" tap are not here: they may run longer.
 *
 * Counts and names are filled in by the screen; a function here returns the line it shows.
 */

const plural = (count: number, one: string, many: string) => (count === 1 ? one : many);

export const HOME = {
  nextTitle: "Next steps",
  nextSummary: (n: number) => (n === 0 ? "Nothing to do" : `${n} ${plural(n, "thing", "things")} to do`),
  nextReady: (score: number) => `${score}% ready`,
  nextShow: "Show",
  nextHide: "Hide",
  seeAll: "See all",
  groupNow: "Needs you now",
  groupBetter: "Make your agents better",
  // `one`/`many` are the business's own caller noun (`callersWord`); "hot lead" is a sales
  // word a business that sells nothing does not have (founder, 5 Nov 2026).
  goalReached: (n: number, one: string, many: string) => `${plural(n, one, many)} reached a goal`,
  goalReachedAction: "Follow up",
  missed: (n: number) => `${plural(n, "missed call", "missed calls")} today`,
  missedAction: "See missed calls",
  gaps: (n: number) => `${plural(n, "question", "questions")} not answered`,
  gapsAction: (n: number) => (n === 1 ? "Teach answer" : "Teach answers"),
  gapsFailed: "Couldn't check unanswered questions",
  // D-551: say the INCOMING half too; an owner must not think only campaigns stopped.
  creditStopped: "Calls in and out stopped: no credit",
  creditLow: "Credit is low",
  creditAction: "Add credit",
  allClear: "All clear. Nothing needs you.",
  tryAgain: "Try again",
  queue: (n: number) => `${plural(n, "thing needs", "things need")} you`,
  queueAction: "Review all",
  queueFailed: "Couldn't check your to-do list",
  lineFailed: "Couldn't check your phone lines",
  lineAction: "Check lines",
  lineMore: (n: number) => (n === 1 ? "+1 more line" : `+${n} more lines`),
  lineDetails: "Details",
  numbersFailed: "Couldn't check your numbers",
  meetTitle: "Meet your agent",
  meetSteps: ["Pick its job", "Tell it about you", "Hear it call you"] as const,
  meetStart: "Build my agent",
  meetContinue: "Continue building",
  goLiveTitle: "Go live",
  goLiveStepOf: (at: number, of: number) => `Go live: step ${at} of ${of}`,
  // The button names the step it opens, so no line under the row repeats it; only the
  // move, which the owner waits on rather than does, says what is happening.
  goLiveAction: {
    move: "See progress",
    verify: "Verify business",
    number: "Choose a number",
    switch_on: "Switch an agent on",
    done: "Open",
  },
  quietCalls: "No calls this week",
  quietLastWeek: (n: number, shown = String(n)) => `${shown} ${plural(n, "call", "calls")} last week`,
  quietLeads: (n: number, shown = String(n)) => `${shown} new ${plural(n, "lead", "leads")}`,
  quietNoAgent: "No agent yet",
  readinessTitle: "Ready for calls",
  readinessScore: (score: number) => `${score}%`,
  readinessLeft: (n: number) => `${n} ${plural(n, "fix", "fixes")} to reach 100%`,
  readinessDone: "Nothing left to fix",
  readinessHow: "How this is worked out",
  readinessLoading: "Checking how ready your agents are",
  // A fix's button names what it does; the server's sentence above it says why.
  readinessAction: {
    addKnowledge: "Add details",
    answerQuestions: "Answer questions",
    opening: "Edit opening line",
    live: "Apply changes",
    missed: "Teach answers",
  },
  readinessFailed: "Couldn't check how ready your agents are",
  forAgent: (name: string) => `For ${name}`,
  setupTitle: "Finish your business details",
  setupNeeded: "Your agents need this to take calls",
  setupLeft: (left: number, of: number) => `${left} of ${of} steps left`,
  setupAction: {
    hours: "Add opening hours",
    branches: "Add your address",
    services: "Add what you offer",
    faqs: "Add common questions",
    staff: "Add staff names",
    booking: "Add how to go ahead",
    contacts: "Add who takes calls",
    languages: "Choose languages",
  },
  setupHide: "Hide from dashboard",
  creditStatusStopped: "Calls in and out stopped",
  creditStatusLow: "Running low",
  creditStatusHealthy: "Healthy",
  trialLastDay: (left: string) => `Trial: ${left}. Add credit`,
  trialFree: (ends: string) => `Free trial until ${ends}`,
  afterHoursOwn: "Using your opening hours",
  afterHoursDefault: "Using 9am–9pm",
  afterHoursAdd: "Add your hours",
} as const;

/** Behind the ⓘ beside the readiness meter, so it may run longer than a default line. */
export const READINESS_WHY =
  "The average of your agents' scores. Each agent scores on what it knows, its opening " +
  "line, whether callers hear its latest version, and questions it could not answer in " +
  "the last 7 days.";

export const TRIAL = {
  title: "Your free trial",
  daysLeft: (n: number | null | undefined) =>
    n === null || n === undefined ? "Trial ended" : `${n} ${plural(n, "day", "days")} left`,
  callsToday: (used: number, cap: number) => `${used} of ${cap} test calls today`,
  minutesLeft: (left: string, free: string) => `${left} of ${free} minutes left`,
  minutesUsedUp: "Free minutes used up. Add credit.",
  rules: (minutes: string) => `Test calls: 9am–9pm, up to ${minutes} each`,
  howItWorks: "How test calls work",
  pledgeTitle: "Accept the no-cold-calls promise",
  pledgeAction: "Accept promise",
  agent: "Agent",
  number: "Number to call",
  noAgents: "No agent yet",
  buildFirst: "Build your first agent",
  agentsFailed: "Agents didn't load. Reload the page.",
  ownNumber: "This is my own number (rings any hour)",
  editAgents: "Edit agents",
  goLive: "Ready to go live?",
  goLiveAction: "Add credit",
  blocked: "This test call was not allowed.",
} as const;

export const ATTENTION = {
  description: "Most urgent first.",
  empty: "No problems right now.",
  emptyHint: "Anything we stop on purpose shows up here.",
  nextSteps: "See your next steps",
  more: (shown: string, total: string) => `Showing newest ${shown} of ${total}`,
  refused: "You need access to leads. Ask your owner.",
} as const;

export const GO_LIVE = {
  subtitle: "3 steps to real calls",
  gettingReady: "Getting your account ready. Your agents keep working.",
  agreementsTitle: "Accept the agreements",
  agreementsHint: "Needed before an agent can take calls.",
  reviewNote: "What to change:",
  skip: "Skip for now",
  skipping: "Skipping…",
  backToVerify: "Verify business first",
  seeSent: "See what you sent",
  switchTitle: "Switch an agent on",
  switchHint: "Pick the agent that takes calls.",
  liveTitle: "You're live",
  liveHint: "Your agent is taking calls.",
  dashboard: "Go to my dashboard",
  noAgent: "No agent to switch on yet",
  makeAgent: "Make an agent",
  taking: "Taking calls",
  notReady: "Not ready yet",
  ready: "Ready",
  switchOn: "Switch on",
} as const;

export const SETUP = {
  needed: "Needed for calls",
  stepOf: (at: number, of: number) => `Step ${at} of ${of}`,
  allSeen: "All steps seen",
  readyTitle: "Your agents have what they need",
  readyHint: "Agents now use these answers.",
  almostTitle: "Almost there",
  stillNeeded: "Still needed for calls",
  existingTitle: "Use your existing number",
  existingHint: "Keep the number callers already know.",
  existingWhy: "How it works",
  needNumber: "Get your Calevate number first",
  needNumberAction: "Get a number",
  existingDone: "Your existing number is set up",
  existingSettings: "See your number",
} as const;

export const FIRST = {
  jobHint: "Pick one or more. Change it later.",
  jobLocked: "Change this on its own page.",
  languageHint: "Every call starts in it.",
  languageLocked: "Change languages on its own page.",
  switches: "It switches when a caller does.",
  briefHint: "What you offer, who calls, how calls end.",
  briefDone: "All three recorded. Type anything else below.",
  sayIt: (language: string, left: number) =>
    `Speak ${language} or English. ${left} × 30 sec left.`,
  audioNotKept: "Only the text is kept, not the audio.",
  readingBrief: "Reading what you wrote…",
  questionsFailed: "We couldn't write your questions",
  questionsFailedHint: "Try again, or build without them.",
  hoursLater: "Different hours some days? Change later.",
  hearHint: "Chat with it on its page.",
  viewOnly: "Only the owner can do this step.",
  versionOne: "Version one is ready. It will ring you next.",
  resultHint: (length: string) => `${length} call. Here is what it heard.`,
  leadForm: "Connect your lead form",
  trialMinutes: (n: number) => `${n} free ${plural(n, "minute", "minutes")} left`,
  trialCalls: (n: number) => `About ${n} test ${plural(n, "call", "calls")}`,
  trialDays: (n: number) => `${n} ${plural(n, "day", "days")} left`,
} as const;

export const NEW_AGENT = {
  directionHint: "You can have several agents.",
  nameHint: "Only you see this. Callers don't.",
  languageHint: "It greets callers in this language.",
  capProblem: (min: number, max: number) => `Enter ${min}–${max} minutes, or leave blank.`,
  capHint: (min: string, max: string) => `Optional. Between ${min} and ${max}.`,
  capSubtitleDefault: (limit: string) => `${limit} (standard)`,
  createdOff: "Created switched off.",
  floorTitle: "What it says about itself",
  floor: [
    "Starts every call with its greeting only.",
    "AI and recording notices: off until you switch them on.",
    "Always answers honestly if asked: AI? Recorded?",
  ] as const,
  createdHint: "Switched off. Next: write what it says.",
  jobsHint: "Pick one. You check everything first.",
  jobUnavailable: "Not available yet. Start blank instead.",
} as const;
