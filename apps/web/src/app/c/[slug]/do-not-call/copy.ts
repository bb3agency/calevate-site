/**
 * The words this screen writes itself, one short line each (`tests/simpleCopyLegal.test.ts`).
 *
 * `DNC_KEPT` is the compliance wording (TCCCPR, hard rule 5): the live-check notice, the
 * check verdicts a client repeats to a caller, and the one sentence that stops the consent
 * switch reading as permission. Those keep their words and are never behind a tap
 * (UX-DOCTRINE §3, §8.7), so they sit outside the short-line budget. The reason notes in
 * `sources.ts` are the same kind and stay there.
 */
export const DNC_COPY = {
  description: "Numbers your agents never dial.",
  fieldLabel: "Phone numbers",
  fieldTip: "Asks the same question the system asks before it dials. Anyone here can check.",
  fieldHint: "One number, or paste many.",
  enterNumber: "Enter the number to check.",
  reason: "Reason",
  check: "Check",
  checked: "Checked",
  added: "Added",
  invalid: "That does not look like a phone number.",
  invalidHint: "Use 10 digits, or the full number with +.",
  countAdded: "Added",
  countAlready: "Already on the list",
  countMalformed: "Not a usable number",
  totalsOnly: "Totals only, to protect privacy.",
  totalsWhy: "A list of who asked us to stop calling is personal data. Check one number to confirm it.",

  postureLabel: "Only call people who have opted in",
  postureHint: "Checked before every outbound call.",
  postureSaving: "Loading this account's calling posture",
  postureOnWhy: "Capture the opt-in first: a form, a booking, a reply, or an inbound call from them.",
  postureOffWhy: "Turn this on if you only contact your own customers about their own bookings. Off, this system stops checking and the choice of who is called stays with you.",

  listHeading: "Suppressed numbers",
  platformWide: "platform-wide",
  unknownReason: "unknown reason",
  emptyTitle: "Nobody is suppressed yet",
  emptyHint: "Callers who ask to stop are added here.",
  ownerCanRestore: "opt-out — an owner can restore it",
  opsOnly: "removed by operations only",
  permanent: "opt-out — cannot be undone",
  restore: "Restore",
  remove: "Remove",
  removing: "Removing…",
  removedToast: "Number taken off the list",
  removedToastBody: "Your agents can ring it again.",

  unsuppressTitle: "Let agents call this number again?",
  unsuppressConfirm: "Un-suppress this number",
  unsuppressKeep: "Keep it suppressed",
  unsuppressLine: "comes off your do-not-call list.",
  unsuppressEffect: "Your agents will be able to ring this person again",
  unsuppressSure: "Only do this if you know they are happy to be called.",

  restoreTitle: "Restore this number?",
  restoreConfirm: "Restore this number",
  restoring: "Restoring…",
  restoreKeep: "Keep it on the list",
  restoredToast: "Number restored",
  restoredToastBody: "Your agents can ring it again.",
  restoreWhyHeading: "Why should it come off?",
  restoreWhyNote: "Saved in your records with your name.",
  restoreNoteLabel: "How and when did they ask?",
  recorded: "What was recorded",
  noWords: "No words were kept. Open the call to read what was said.",
  openCall: "Open the call",
  noCall: "No call attached. Your team added it as their request.",
  restoreEffect: "Agents can ring it again straight away.",
} as const;

export const DNC_KEPT = {
  liveCheck: "Checked live before every single call, including for a campaign that is already running.",
  suppressed: "This number is suppressed, so no agent will call it.",
  suppressedGlobal: " Calevate has suppressed it across the whole platform, so it cannot be removed from this account.",
  suppressedTenant: " It was added to your account's list.",
  clear:
    "This number is not on the do-not-call list. Other checks, such as calling hours and consent, still apply to any actual call.",
  postureOn: "A number with no opt-in on file is refused rather than dialled.",
  postureOff: "Numbers with no opt-in on file are dialled.",
  notPermission: "Leaving this off is not permission to call strangers.",
  onYourList: "is on your list because this person was recorded as asking not to be called.",
  breaksLaw: "Calling someone who asked not to be called breaks the law.",
} as const;

export const manyNumbers = (count: string): string => `${count} numbers. Check one at a time.`;
export const tooMany = (count: string, max: string): string => `${count} numbers. Add up to ${max} at a time.`;
export const addLabel = (count: number, formatted: string): string =>
  count === 1 ? "Add 1 number" : `Add ${formatted} numbers`;
export const entriesLabel = (count: number, formatted: string): string =>
  `${formatted} ${count === 1 ? "entry" : "entries"}`;
export const showingLatest = (limit: string): string => `Showing the ${limit} most recently added`;
export const charsLeft = (n: number): string => `Short note, no phone numbers. ${n} left.`;
