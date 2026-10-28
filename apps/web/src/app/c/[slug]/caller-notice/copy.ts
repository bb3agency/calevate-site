/**
 * The words this screen writes itself. The notice, its disclaimer and the truthful-answer
 * guarantee are not short copy: the first two are the server's legal text and the third is
 * a compliance sentence kept word for word (UX-DOCTRINE §3), so they live in `KEPT`, which
 * the short-line guard skips.
 */
export const CALLER_NOTICE_COPY = {
  description: "Your privacy notice for callers.",
  copy: "Copy",
  downloadTxt: "Download as text (.txt)",
  downloadMd: "Download as Markdown (.md)",
  print: "Print or save as PDF",
  printTitle: "Privacy notice (draft)",
  panelLabel: "Your blanks and announcements",
  fillHeading: "Fill the blanks",
  fill: "Fill in",
  edit: "Edit",
  localOnly: "Saved on this device only. Not sent to us.",
  clear: "Clear what I typed",
  nothingListed: "No caller details listed yet.",
  nothingListedWhy: "Each detail a live agent collects is added to the notice.",
  offHeading: "Not said at the start of a call",
  offWhy: "These settings only cover what is said unprompted at the start of a call.",
  offAi: "That they are AI",
  offRecording: "That the call is recorded",
  loading: "Loading your privacy notice",
} as const;

/** Compliance sentences, kept word for word and therefore outside the short-line budget. */
export const CALLER_NOTICE_KEPT = {
  guarantee:
    "Every agent still answers truthfully whenever a caller asks whether they are speaking to an AI or whether the call is recorded. That cannot be switched off.",
  obligation: "Where one is off, your written notice is where the obligation lands.",
} as const;
