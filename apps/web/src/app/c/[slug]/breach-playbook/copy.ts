/**
 * The breach playbook's words (D-943). Short lines by default; the reason behind a tap.
 *
 * Timelines: "without delay" to each affected person and to the Data Protection Board,
 * and a detailed report to the Board within 72 hours, are the DPDP Rules 2025 (Rule 7) as
 * REPORTED by secondary sources; CERT-In's 6-hour cyber-incident report is separate and
 * also secondary. The duties commence about 13 May 2027 (secondary; UNKNOWN whether a
 * proposed earlier date was notified). Source: `docs/research/research_notes/Calevate
 * market and technology edge/india_regulation.md` §3.
 */
export const BREACH_COPY = {
  description: "What to do if customer data leaks.",
  notAdvice: "General steps, not legal advice. Call your advocate early.",
  copyRecord: "Copy the record sheet",
  copyMessage: "Copy the message to customers",
  openRights: "Open Data rights",
  tellUs: "Tell Calevate",
} as const;

export type BreachStep = {
  title: string;
  line: string;
  when?: string;
  why?: string;
  action?: "record" | "message" | "rights" | "tell-us";
};

export const BREACH_STEPS: BreachStep[] = [
  {
    title: "Stop it",
    line: "Change passwords. Remove access for anyone who should not have it.",
    when: "Now",
    action: "tell-us",
    why: "If the leak came through your Calevate account, tell us at once so we can lock it down with you.",
  },
  {
    title: "Write down what happened",
    line: "When you found out, what data, how many people.",
    when: "Now — the clock starts when you find out",
    action: "record",
    why: "Every notice below asks for these facts. Write them while they are fresh.",
  },
  {
    title: "Tell the people affected",
    line: "Say what happened and what they can do.",
    when: "Without delay",
    action: "message",
    why: "Reported reading of the DPDP Rules 2025: each affected person is told without delay. Not checked against the Rules' own text.",
  },
  {
    title: "Tell the Data Protection Board",
    line: "A short notice now, a full report later.",
    when: "Without delay; full report within 72 hours",
    why: "Reported reading of the DPDP Rules 2025 (Rule 7). The Board can allow more time on request. These duties start about 13 May 2027.",
  },
  {
    title: "Check if CERT-In must be told",
    line: "A cyber attack may need its own report.",
    when: "Within 6 hours, if it applies",
    why: "CERT-In's cyber-incident rule runs alongside data-protection law. Reported, not checked here; ask your advocate.",
  },
  {
    title: "Answer the questions that follow",
    line: "People may ask what you hold about them.",
    action: "rights",
    why: "Requests to see or erase data must be answered within 90 days. Log them on Data rights.",
  },
];

/** A sheet to fill in, copied as plain text. Facts only, no customer data in it. */
export const RECORD_SHEET = [
  "DATA BREACH RECORD",
  "",
  "When we found out (date, time, IST):",
  "How we found out:",
  "What data was involved (names, phone numbers, call recordings, other):",
  "How many people are affected (about):",
  "What we have done to stop it:",
  "What people can do to protect themselves:",
  "Who to contact with questions (name, phone, email):",
  "Affected people told on (date, how):",
  "Data Protection Board told on (date):",
  "Detailed report sent on (date):",
].join("\n");

/** The message to affected customers: blanks in double braces, filled by the business. */
export const CUSTOMER_MESSAGE = [
  "Dear customer,",
  "",
  "On {{DATE}} we found that some of your information held by {{YOUR BUSINESS NAME}} " +
    "may have been seen by someone who should not have seen it.",
  "What was involved: {{WHAT DATA}}.",
  "What we have done: {{WHAT YOU DID}}.",
  "What you can do: {{WHAT THEY CAN DO, FOR EXAMPLE IGNORE CALLS ASKING FOR AN OTP}}.",
  "Questions: {{CONTACT NAME, PHONE, EMAIL}}.",
  "",
  "We are sorry. {{YOUR BUSINESS NAME}}",
].join("\n");
