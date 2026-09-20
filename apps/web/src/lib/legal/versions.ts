/**
 * The VERSION of each published document — the browser's copy of a fact the server owns.
 *
 * ## Why this file exists rather than a `version` field on `LegalDocument`
 *
 * A version here is not decoration: `apps/api/legal/` records it in an append-only
 * ledger every time an owner accepts a document, and every outbound gate compares a
 * stored row against the current one to decide whether the account may dial. So the
 * SOURCE OF TRUTH is `apps/api/legal/catalogue.py` — it is read by Postgres-side code on
 * a machine that never runs Node — and this module is the mirror the browser needs.
 * `scripts/check_docs_drift.py` fails CI when the two disagree, which is the same
 * mechanism §4b uses for the TTS rate card and for the same reason: a mirror nothing
 * checks is a mirror that is wrong the first time one side moves.
 *
 * It is a separate module rather than three more fields on `LegalDocument` so the drift
 * check has one small file to parse instead of eight prose modules, and so that editing a
 * document's TEXT and editing its VERSION are visibly different acts in a diff.
 *
 * ## The version carries the review state
 *
 * While `PENDING_LEGAL_REVIEW` (in `placeholders.ts`) stood, every document's current
 * version was `<revision>+pre-review`. It was turned off on 2 September 2026 when the set
 * was published, so every version changed, every acceptance recorded against a
 * `+pre-review` version stopped being current, and the server asked every client to
 * accept again. Nothing special-cased the flip — it falls out of the version string — but
 * it did need the same edit on both sides of the mirror, and the drift check names the
 * side that was missed.
 *
 * ## Adding a revision
 *
 * An edit to a document's OPERATIVE TEXT is a new entry in that document's `revisions`,
 * here AND in `catalogue.py`. `material: true` when somebody who accepted the previous
 * revision must accept again; `material: false` for a correction that changes nothing
 * anybody agreed to. The API decides what each flag DOES; this file only has to say the
 * same thing the API says.
 *
 * ## And the new entry carries a `contentHash`, which is what makes the rule enforceable
 *
 * The drift check could only ever compare IDENTITY — slug, revision, `material`, date —
 * and said so in terms: a clause edited in `terms.ts` with no revision appended left every
 * stored acceptance pointing at words that had changed, and nothing in the tree saw it.
 * `contentHash` is that missing half. It is a hash of the document's operative text as at
 * that revision, written by the person who appends the revision, and
 * `apps/web/tests/legalContentHash.test.ts` fails in both directions: text that moved with
 * no new revision, and a new revision whose words are identical to the one before it (a
 * different mistake — it re-asks every client to accept a document that did not change).
 *
 * Print the value with `pnpm -C apps/web legal:hashes`. Nothing writes this field for you,
 * on purpose: a hash a program refreshes is a checksum of itself.
 */

import { lookup } from "@/lib/lookup";

import { PENDING_LEGAL_REVIEW } from "./placeholders";

/** The suffix a version carries while the documents are still pre-legal-review. */
export const PRE_REVIEW_SUFFIX = "+pre-review";

/** One authored revision. `material` describes the STEP INTO it, not the document. */
export interface LegalRevision {
  readonly revision: string;
  readonly material: boolean;
  /**
   * WHAT THIS REVISION SAYS, as a hash of the document's operative text — the guard that
   * an acceptance row naming this revision still points at the words that were accepted.
   *
   * `sha256:<64 lowercase hex>` over `resolvePlaceholders(textOf(doc))`: every string a
   * reader of `/legal/<slug>` is shown, in document order, with the `{{PLACEHOLDER}}`
   * tokens resolved to their values — and nothing else. Not the module's imports, not its
   * comments, not its TypeScript formatting, not an anchor id, and not this table.
   * `apps/web/tests/legalContentHash.test.ts` computes it, states the definition in full,
   * and is the only thing that reads it; `pnpm -C apps/web legal:hashes` prints it.
   *
   * It is written BY A PERSON, in the same edit that appends the revision. Nothing in the
   * tree patches this field: a hash a guard could refresh is a checksum of itself.
   *
   * ABSENT ON A REVISION AUTHORED BEFORE THE GUARD EXISTED (7 September 2026). The text of
   * revision 3 is not in this repository and cannot be recovered from it, so no honest
   * value exists for it and none is invented (hard rule 11). The CURRENT revision of every
   * document carries one — the guard fails if it does not — so the history heals at the
   * first bump after this landed.
   */
  readonly contentHash?: string;
}

/** What the mirror holds for one document. */
export interface LegalVersionEntry {
  /** Mirrors the document's own `shortTitle`, and the API's `LegalDocumentSpec.title`. */
  readonly title: string;
  /** Does an unaccepted copy of this document stop the account operating? */
  readonly blocking: boolean;
  /** Oldest first; the last entry is current. */
  readonly revisions: readonly LegalRevision[];
  /**
   * The date the document starts binding, ISO-8601, or null while it has none.
   *
   * 2 September 2026 everywhere: the day the set was published. The prose spelling of
   * the same day is the `{{EFFECTIVE_DATE}}` placeholder, which the page header renders
   * under "In force from"; this is the machine form, and `catalogue.py` carries the same
   * string or CI says so.
   */
  readonly effectiveDate: string | null;
}

export const LEGAL_VERSIONS: Readonly<Record<string, LegalVersionEntry>> = {
  privacy: {
    title: "Privacy Policy",
    blocking: true,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: true },
      { revision: "3", material: true },
      { revision: "4", material: false },
      { revision: "5", material: false },
      // D-547. The second voice quality brought a second speech vendor, and the notice
      // now says so in the three places a reader would look: what it receives and what
      // its own terms let it do with that (§6), that we cannot say where it processes
      // (§8), and that voice synthesis is no longer wholly on the Indian provider. A NEW
      // RECIPIENT of caller-derived text is a new disclosure under the notice's own
      // §7 promise, so material.
      {
        revision: "6",
        material: true,
        contentHash: "sha256:468d870b16d23499b66f47ca14609601e99b9512b31a483012986df88ac12af0",
      },
      // §9 now publishes two retention periods this notice had never disclosed and one it
      // enforced in silence. `campaign_contacts` (an uploaded name and number for someone
      // who may never have been dialled) and `scheduled_callbacks` (a number plus a
      // model-written note about what one caller asked for) previously aged out NEVER;
      // they now expire on the lead and transcript clocks. And `caller_memory` — what an
      // agent remembers about a CALLER between calls — was enforced at 180 days and
      // appeared in no published table at all, which is the one omitted category whose
      // subject is the caller rather than the client's own staff.
      //
      // MATERIAL, AND THE JUDGEMENT IS THE CONSERVATIVE ONE ON PURPOSE. Nothing here is a
      // new use of anyone's data and every period either shortens a retention or names one
      // that was already running, so a case could be made that it only makes the notice
      // more honest. But the question this flag asks is "must somebody who accepted
      // revision 6 accept again", and a reader of revision 6 could not have known we held
      // an uploaded contact list indefinitely or remembered their callers for six months.
      // Learning what is kept about you is exactly the kind of thing a person agrees to,
      // so this re-asks rather than assuming the answer would be the same.
      {
        revision: "7",
        material: true,
        contentHash: "sha256:9cf7f8394aa1e973e0f83ffcff3f796b4d321df30fc9fd56fca77a637f459e87",
      },
      // D-629. SARVAM NO LONGER SYNTHESISES THE AGENT'S VOICE. It still hears every call
      // and still reads the first pass over the transcript, so nothing this notice says
      // about what it receives or what its terms permit changed; what changed is that the
      // cheaper voice quality passed to a third company (Gnani) and BOTH qualities are now
      // spoken by companies we cannot place. Two sentences a reader of revision 7 relied on
      // are WITHDRAWN rather than reworded: that voice synthesis ran on the Indian provider
      // for agents on the first quality (§6, §8), and that a client who would rather an
      // unplaceable synthesiser did not touch their callers could keep every agent on the
      // other quality (§6, §8). There is no such quality now.
      //
      // MATERIAL. A reader of revision 7 was told where their agent's voice was made and
      // was given a way to keep it with a company whose position we had read; both are
      // gone, and the company that takes over is one whose own pages nobody here has been
      // able to open. That is a change in who receives caller-derived text and in what we
      // promise about it — the same class of change revision 6 was material for.
      {
        revision: "8",
        material: true,
        contentHash: "sha256:fd0560de83acd3a964437e33c4bf23ab6fe5ef6a7f8ee026a566edb87e47ceca",
      },
      // D-635. A client may now verify their own identity through DigiLocker with a
      // licensed intermediary, so §4's KYC entry says what that route collects: the
      // intermediary handles the Aadhaar, we receive the confirmation, their reference,
      // the name they confirmed and the date, and the difference between a sole
      // proprietorship and a company is stated because the outcomes differ.
      //
      // MATERIAL, and the question is not whether the promise got weaker — it did not.
      // We still hold no Aadhaar number and no identity document, the section 29
      // reasoning is unchanged and the twelve-digit refusal now covers three more
      // fields. What a reader of revision 8 could not have known is that an INTERMEDIARY
      // may come to stand between them and us on this path, and a new party in a data
      // flow is a new disclosure — the same class of change revisions 6 and 8 were
      // material for, and the conservative reading is the right one on a notice.
      {
        revision: "9",
        material: true,
        contentHash: "sha256:7a16c3496d10e82c2eba428605eac34a21db1f27e4f1d53afe6d914028c9689b",
      },
    ],
    effectiveDate: "2026-09-02",
  },
  terms: {
    title: "Terms of Service",
    blocking: true,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: true },
      { revision: "3", material: true },
      { revision: "4", material: false },
      { revision: "5", material: false },
      // D-547. Clause 6.1 gains the credit-lot promise: each purchase of credit is
      // priced at the rates shown when it was made, one per voice, those rates hold
      // until that purchase is spent, credit does not expire, and credit is spent
      // oldest purchase first. A new operative fee term — what somebody agreed to
      // about what they pay changes — so material.
      {
        revision: "6",
        material: true,
        contentHash: "sha256:370891051573708df7f01e26bce83cc4ae85fc09ce1a5cdd329b9769fea96573",
      },
    ],
    effectiveDate: "2026-09-02",
  },
  "acceptable-use": {
    title: "Acceptable Use",
    blocking: true,
    revisions: [
      { revision: "1", material: true },
      {
        revision: "2",
        material: false,
        contentHash: "sha256:9d7c9cc2998214112f9c0f2e93f02e5e399fd541dccb2c8844356cddab901b26",
      },
    ],
    effectiveDate: "2026-09-02",
  },
  dpa: {
    title: "Data Processing Addendum",
    blocking: true,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: true },
      { revision: "3", material: true },
      { revision: "4", material: false },
      { revision: "5", material: false },
      // D-547. Clause 2 gains the second vendor whose published terms permit training,
      // clause 5 narrows its own warranty for the one register row whose data-processing
      // agreement nobody has established can be entered, and clause 9 stops saying voice
      // synthesis is wholly on the Indian provider. A narrowed warranty and a new
      // recipient are both changes to what somebody agreed to, so material.
      {
        revision: "6",
        material: true,
        contentHash: "sha256:a342c58ebf25971b113f7c5c2f0d22b5dd856c1a157cab7ab15d9d2a32222f9e",
      },
      // D-629. Clause 2's voice-synthesis bullet no longer names the company that hears
      // the call: it was removed from the synthesis leg and the cheaper voice quality
      // passed to a third company, of whose published position we have read NOTHING —
      // every one of its sites refuses a connection from the environment this is built in.
      // Clause 5's warranty gains a SECOND exception for that company, on the stronger
      // ground that we cannot even say whether it offers a data-processing agreement.
      // Clause 9 stops saying voice synthesis runs on the Indian provider for the first
      // voice quality, and WITHDRAWS the sentence that keeping your agents on that quality
      // kept your callers' data away from an unplaceable vendor — there is no longer a
      // quality that does.
      //
      // MATERIAL. A narrowed warranty and a withdrawn assurance both change what somebody
      // agreed to, which is exactly what revision 6 was material for.
      {
        revision: "7",
        material: true,
        contentHash: "sha256:ecc9cb2a327bc7d77345551267d67d7f87704e51afbbbb8ec20a2cb068d3f4cb",
      },
    ],
    effectiveDate: "2026-09-02",
  },
  subprocessors: {
    title: "Sub-processors",
    blocking: false,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: true },
      { revision: "3", material: true },
      // D-547. Cartesia joins the register as the voice-synthesis vendor for the second
      // voice quality, in its own row beside the contingency row it already had, with
      // section 3.6 for what its published documents permit and what we have not
      // established. A NEW SUB-PROCESSOR is the event clause 5 of the Data Processing
      // Addendum notifies against and a client may object to, so material.
      {
        revision: "4",
        material: true,
        contentHash: "sha256:a5f2af022ed41b32b8f51980dd49d51af7f5edc47e826df44788dc4f79f77bd8",
      },
      // D-615. THE PLATFORM THAT RUNS THE CALL WAS NOT IN THE REGISTER. D-592 moved the
      // conversation into a container of ours on Pipecat Cloud, which puts a new company
      // on the path the caller's AUDIO travels — the one category on that page that
      // cannot be redacted, masked or summarised on its way past — and no row named it.
      // Added with its own row and section 3.7, which lists what nobody here has
      // established about it (the operating entity, where `ap-south` is, its terms, its
      // retention, whether a DPA can be entered, its own sub-processors) rather than
      // filling any of it in: both of that vendor's hosts refuse a connection from this
      // build environment, re-measured 15 September 2026. The carrier row is widened in
      // the same revision, because under the same design the carrier now carries the
      // AUDIO and not only the numbers and the call records. A NEW SUB-PROCESSOR on the
      // call path is the event clause 5 of the Data Processing Addendum notifies against
      // and a client may object to, so material.
      {
        revision: "5",
        material: true,
        contentHash: "sha256:79ccad03ddd6d6819fd99939cc5e35b1e575a252236ec83fac4aa8a986d14470",
      },
      // 18 Sep 2026. THREE RECIPIENTS THAT WERE IN THE CODE AND ON NO PAGE, found by
      // auditing from the tree outwards rather than by re-reading the rows —
      // `scripts/check_subprocessor_coverage.py` is that audit turned into a gate, and
      // `docs/evidence/subprocessor-register-code-audit-2026-09-18.md` is the working.
      // Supermemory: two complete adapters whose settings the ops console can change at
      // runtime, so an operator selects it and the next question is served from it, at
      // which point it holds every published knowledge passage — FAQs, price lists, staff
      // names and contact numbers. Gnani: a THIRD voice-synthesis vendor, selectable per
      // agent, receiving the words the agent speaks. And an unnamed row for a tracing
      // collector, which is an address an operator sets and could point at a monitoring
      // vendor. All three are off, and "off" is not "undisclosed": a register that omits
      // a recipient a setting away from being live is the failure clause 5 exists for.
      // MATERIAL — new sub-processors are exactly what a client may object to.
      {
        revision: "6",
        material: true,
        contentHash: "sha256:1affe0b1386b062917def21846a17309e31a3b98fa18f09d7feccf96c2290ea3",
      },
      // D-629. No row is added and none is removed — what MOVED is which vendor does
      // what. The speech vendor's `does` cell loses "voice synthesis": it still hears
      // every call and still reads the transcript first, and nothing in its Location
      // cell, its Receives cell or section 3.4 narrowed by a word. The Gnani row, added
      // one revision ago as a third quality nobody could choose, becomes the vendor of
      // the CHEAPER of two qualities. And section 3.6 — written for one vendor — now
      // covers both, which is where the change bites: its closing assurance that a client
      // could keep every agent on the other voice quality and that this vendor would then
      // receive nothing of theirs is WITHDRAWN, because both qualities are now spoken by
      // companies whose position nobody here has read.
      //
      // MATERIAL. A register that re-assigns the most sensitive leg in the product from a
      // vendor whose terms are set out in section 3.4 to one whose pages cannot be opened
      // at all is telling a client something new about who processes what — the same
      // question they are entitled to object to under the notification clause, even
      // though the company itself was disclosed a revision earlier.
      {
        revision: "7",
        material: true,
        contentHash: "sha256:2c900be7085a14c8fea4aee922afa81775ecbb9064e3d33c3425f3d1a8394cbd",
      },
    ],
    effectiveDate: "2026-09-02",
  },
  refunds: {
    title: "Refunds & Cancellation",
    blocking: false,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: false },
      { revision: "3", material: false },
      // D-547. Section 1's description of a self-serve account gains the same promise
      // clause 6.1 of the Terms now makes: each top-up carries its own per-minute
      // rates, one per voice quality, fixed at purchase; credit does not expire and is
      // spent oldest purchase first. It changes what an unused balance MEANS in a
      // policy about money, so it is material rather than a correction.
      {
        revision: "4",
        material: true,
        contentHash: "sha256:d500936af9ef837489e89ff5bde191d2d6667361bfc0d7aed1b1f22499086cd2",
      },
    ],
    effectiveDate: "2026-09-02",
  },
  grievance: {
    title: "Grievance Redressal",
    blocking: false,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: false },
      {
        revision: "3",
        material: false,
        contentHash: "sha256:a89df0e1ea88c1eb4bbfb00a285628857cd71a4a563ce61247fd5f6f9ef4d4d4",
      },
    ],
    effectiveDate: "2026-09-02",
  },
  cookies: {
    title: "Cookies & Tracking",
    blocking: false,
    revisions: [
      { revision: "1", material: true },
      { revision: "2", material: false },
      // D-539. The client session cookie now carries a lifetime bounded by its own
      // session row, so it survives a browser close; revision 2 said it did not. A
      // correction to a factual description in a non-blocking notice — nobody accepted
      // anything that this changes — so `material: false`.
      {
        revision: "3",
        material: false,
        contentHash: "sha256:db63c997aedfa1276ee079ecac3eb539f0625fb8624ea5695ac92d5c87be176c",
      },
    ],
    effectiveDate: "2026-09-02",
  },
};

/**
 * The version string a reader of `/legal/<slug>` is looking at, or null for a slug the
 * mirror does not carry.
 *
 * `lookup` rather than an index, for the reason `legalDocument` gives: the argument comes
 * off a URL, and a keyed read with such a value is the prototype hazard `lib/lookup.ts`
 * exists to refuse.
 */
export function documentVersion(slug: string): string | null {
  const entry = lookup(LEGAL_VERSIONS, slug);
  if (entry === undefined || entry.revisions.length === 0) return null;
  const revision = entry.revisions[entry.revisions.length - 1].revision;
  return PENDING_LEGAL_REVIEW ? `${revision}${PRE_REVIEW_SUFFIX}` : revision;
}

/** How the version is shown to a reader — the string, plus what the suffix means. */
export function documentVersionLabel(slug: string): string | null {
  const version = documentVersion(slug);
  if (version === null) return null;
  return PENDING_LEGAL_REVIEW ? `${version} (draft, not yet reviewed)` : version;
}
