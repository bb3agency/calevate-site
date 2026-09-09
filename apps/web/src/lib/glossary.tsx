/**
 * THE VOCABULARY. One definition per term, for every screen in both realms.
 *
 * `TermGloss` (components/ui) is the MECHANISM — an `<abbr>` whose meaning shows on hover,
 * focus and tap. This is the WORDS, and it exists because the mechanism alone let the same
 * term be explained four different ways: "Principal Entity" was
 * *"the client, as registered on DLT"* on one admin screen, *"the client's own
 * registration"* on another, *"the business the registrar recognises as responsible for
 * these campaigns"* on the client's, and — on a fourth — nothing at all, just the two
 * capitalised words. A reader who meets a term twice should meet the same sentence twice.
 *
 * ## How a screen uses it
 *
 *   <Term id="dlt" />                              → DLT, glossed
 *   <Term id="tm" term="telemarketer (TM)" />      → same gloss, this screen's spelling
 *   <Term id="kyc" audience="operator" />          → the operator's wording of it
 *
 * `term` overrides only what is PRINTED (a sentence may want "PE", "Principal Entity" or
 * "principal entity (PE)"); the explanation still comes from here, which is the drift this
 * file exists to stop. `audience` picks between two explanations of the same term where the
 * two realms genuinely need different ones — see below.
 *
 * ## Two audiences, and why the default is the client's
 *
 * A clinic owner in the client console does not know what a Principal Entity is and must
 * not be told in registrar language; an operator in the admin console can take the precise
 * term and needs it to match the registrar's own letter. So `gloss` is written for the
 * client — the stricter constraint, and correct for an operator reading it too — and
 * `operator` is added only where the precise version says something the plain one cannot.
 * A term with no `operator` entry reads the same on every screen, deliberately.
 *
 * ## What is deliberately NOT here
 *
 * Plain English is not glossed: a dotted underline on a word the reader already knows is
 * noise that teaches them to ignore the ones that matter. So IST, CSV, OTP, API, "do-not-
 * call list" and "credit" are bare everywhere by decision, not by omission. The line is
 * whether a competent reader of THAT screen would have to look it up: an Indian SMB owner
 * knows IST and OTP; nobody outside a telecom registrar knows what a Principal Entity is.
 *
 * The legal documents (`lib/legal/`) are also out of scope and must stay that way. They
 * define their terms in prose, in the body of the instrument, because that is what a
 * document someone signs has to do — and their text is content-hashed
 * (`tests/legalContentHash.test.ts`), so a tooltip inside one would change what was agreed.
 */

import { TermGloss } from "@/components/ui";

/** One term, as the reader meets it. */
interface GlossaryEntry {
  /** What is printed when a call site does not override it. */
  readonly term: string;
  /** The explanation, written for a client. */
  readonly gloss: string;
  /** The operator's version, where the precise wording says more than the plain one. */
  readonly operator?: string;
}

export const GLOSSARY = {
  dlt: {
    term: "DLT",
    gloss: "India's telecom message registry",
  },
  pe: {
    term: "Principal Entity",
    gloss: "the business the registrar recognises as responsible for these campaigns",
    operator: "the client, registered with the registrar in its own name",
  },
  tm: {
    term: "Telemarketer",
    gloss: "the business registered to place calls on another business's behalf — that is us",
    operator:
      "the business registered with India's telecom system to place calls on a client's behalf",
  },
  dpdp: {
    term: "DPDP",
    gloss: "India's Digital Personal Data Protection Act",
  },
  dnc: {
    term: "DNC",
    gloss: "do-not-call list",
  },
  dnd: {
    term: "DND",
    gloss: "India's national Do Not Disturb registry",
  },
  kyc: {
    term: "KYC",
    gloss: "the identity check a business has to pass before an account is opened",
    operator: "Know Your Customer — the business identity check",
  },
  series140: {
    term: "140",
    gloss: "India's marketing-call number range",
  },
  series160: {
    term: "160",
    gloss: "India's service-call number range",
  },
  dataFiduciary: {
    term: "data fiduciary",
    gloss: "the business responsible for this data under India's privacy law",
  },
} as const satisfies Record<string, GlossaryEntry>;

export type GlossaryId = keyof typeof GLOSSARY;

/**
 * A glossed term, from the one definition of it.
 *
 * Prefer this to `<TermGloss>` with the words typed in: the words are what drift.
 */
export function Term({
  id,
  term,
  audience = "client",
}: {
  id: GlossaryId;
  /** This screen's spelling of the term. The explanation is still the map's. */
  term?: string;
  audience?: "client" | "operator";
}) {
  const entry: GlossaryEntry = GLOSSARY[id];
  return (
    <TermGloss term={term ?? entry.term}>
      {audience === "operator" && entry.operator ? entry.operator : entry.gloss}
    </TermGloss>
  );
}
