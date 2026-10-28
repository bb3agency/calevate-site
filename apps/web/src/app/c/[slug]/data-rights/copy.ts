/**
 * The words this screen writes itself, one short line each (`tests/simpleCopyLegal.test.ts`).
 *
 * `DATA_RIGHTS_KEPT` holds the consequences of an erasure. They are stated above the
 * control that files one and are never folded behind a tap (UX-DOCTRINE §3: high
 * consequence never discloses), so they keep their words and sit outside the short-line
 * budget. Only the itemised list of what survives is behind "What is kept?".
 */
export const DATA_RIGHTS_COPY = {
  description: "Export or erase a person's data.",
  roleWhy: "A person can ask what you hold about them, or ask you to erase it.",
  exportButton: "Export someone's data",
  eraseButton: "Erase someone's data",

  registerHeading: "Erasure requests",
  registerTip: "Numbers are never listed here. Each request has a one-way code instead.",
  registerSub: "Newest first.",
  registerEmpty: "No erasure requests have been filed yet.",
  statusDone: "Erasure complete",
  statusNoProof: "Complete — no certificate recorded",
  statusWaiting: "Submitted — waiting to run",
  showCertificate: "Show the certificate",
  showDetails: "Show details",
  hide: "Hide details",
  requestId: "Request ID",
  numberCode: "Number code",
  numberCodeWhy: "A one-way code of the number. It proves the erasure only to someone who has the number.",
  running: "Running now. The certificate appears here when done.",
  noProofTitle: "Completed, but no certificate was recorded",
  noProofBody: "Do not tell the person it is done yet.",
  noProofAction: "Copy request ID to send us",
  limitsHeading: "What an erasure cannot do",
  certificateHeading: "Proof certificate",
  saveCertificate: "Save the certificate",
  erased: "Erased",
  notErased: "Not erased",
  vendorCopies: "Copies at the calling system",

  eraseTitle: "This cannot be undone",
  whatIsKept: "What is kept?",
  eraseField: "Number to erase permanently",
  eraseHint: "Check it twice: there is no undo.",
  eraseFieldMissing: "Enter the number to erase.",
  checkWhose: "Check whose record this is first",
  checking: "Checking…",
  checked: "Checked",
  holdNothing: "We hold nothing for this number.",
  holdNothingHint: "Expected a record? Check the digits.",
  allErased: "All of it will be erased.",
  eraseSubmit: "Erase this person's data",
  filing: "Filing…",
  filed: "Filed",
  alreadyOpen: "Already being erased, so nothing new was filed.",

  exportIntro: "One file with everything we hold for a number.",
  exportWhy: "Their calls, redacted transcripts, CRM record and consent history. Send the file to the person who asked.",
  exportField: "Their phone number",
  exportHint: "10 digits, or the full number with +.",
  exportFieldMissing: "Enter their phone number.",
  build: "Build the export",
  building: "Building…",
  built: "Built",
  ready: "The export is ready",
  readyBody: "Save it and send it to the person who asked.",
  readyWhy: "If we hold nothing for that number, the file says so. That fully answers them.",
  save: "Save the file",
  saved: "Saved",
  saveFailed: "Could not save the file",
  calls: "Calls",
  turns: "Transcript turns",
  leads: "CRM records",
  consents: "Consent records",
} as const;

export const DATA_RIGHTS_KEPT = {
  erased: "Every call, transcript, extracted field and CRM record we hold for this number is erased.",
  noRestore: "Nothing restores them.",
  ownRecord: "If this person is still a customer, you are erasing your own record of them too.",
  kept: "Some things are kept, and the certificate names each one with the rule that required it.",
  keptList:
    "The consent ledger that proves the calls were lawful, the billing ledger, any do-not-call entry, and the call audio, which Indian telecom rules require to be retained. The calls themselves survive only as rows with the personal details stripped out.",
} as const;

export const filedLine = (filed: string, completed: string | null): string =>
  completed ? `Filed ${filed} · done ${completed}` : `Filed ${filed}`;

export const erasedOn = (day: string): string => `Erased on ${day}, so the counts are low.`;

export const audioHeld = (recordings: string, until: string): string => `${recordings} kept by law until ${until}.`;
