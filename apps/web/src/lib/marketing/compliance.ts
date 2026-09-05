import { BadgeCheck, Clock, Database, ShieldCheck } from "lucide-react";

/**
 * THE LEGALLY LOAD-BEARING MARKETING COPY, HELD IN ONE PLACE SO IT CANNOT DIVERGE.
 *
 * ⚠ **DO NOT REWORD ANYTHING IN THIS FILE.** Every sentence here has been through at least
 * one correction round, two of them after the product changed underneath the claim, and one
 * after the fact itself turned out to be wrong. They may be re-laid-out, shortened by
 * MOVING them behind a disclosure, or linked to. They may not be paraphrased, summarised or
 * "tightened" — a paraphrase of a corrected sentence is a new claim nobody has checked.
 *
 * ## Why a module and not two copies
 *
 * The homepage's trust band and `/security` both carry this text. Two copies of a sentence
 * that has been corrected three times is the drift CLAUDE.md's "one way per problem" rule
 * exists for, with the aggravating factor that the copy which falls behind is a
 * misrepresentation on a public page rather than a stale comment. `publicLanding.test.tsx`
 * pins several of these substrings; with one definition, that guard covers both surfaces.
 *
 * ## The corrections, so the next reader does not undo one
 *
 * - **The AI disclosure card was INVERTED by D-163.** It used to read "Every call says it
 *   is an AI … There is no configuration that turns it off". D-163 made the OPENING
 *   announcement a per-agent toggle, so the page was promising a buyer the exact thing the
 *   product hands their staff a switch for. What survives is narrower and is enforced
 *   rather than documented: `agents.ai_disclosure_line` is NOT NULL and non-blank
 *   (`apps/api/agents/models.py:192,304`), the dial gate refuses an agent without one, and
 *   `compose_engine_prompt` appends the truthful answer above the client's script on every
 *   publish and every drift sweep (hard rule 5).
 * - **The recording card lost its legal attribution.** It used to call 90 days "the TRAI
 *   floor". `docs/SECURITY-COMPLIANCE.md:424-432` records that the floor's own authority is
 *   in doubt and routes the question to counsel rather than answering it, so the page keeps
 *   the ENFORCED floor — the `recording_ttl_floor` CHECK and `RECORDING_FLOOR_DAYS = 90` in
 *   `apps/workers/retention.py:119` — and drops the claim about the outside world.
 * - **The residency paragraph has been narrowed four times and then WITHDRAWN as an India
 *   claim.** Its own comment below carries that history.
 */
export const COMPLIANCE_INVARIANTS: readonly {
  icon: typeof Clock;
  title: string;
  body: string;
}[] = [
  {
    icon: Clock,
    title: "9am to 9pm, always",
    body:
      "Fixed by the platform, not by a setting you can raise. A campaign cannot dial " +
      "outside them.",
  },
  {
    icon: ShieldCheck,
    title: "Do-not-call is checked first",
    body:
      "Scrubbed before every dispatch. Anyone who asks to be removed mid-call is added " +
      "immediately.",
  },
  {
    icon: BadgeCheck,
    title: "It never denies being an AI",
    body:
      "Every agent has an AI disclosure line and cannot go live without one. Whether " +
      "it volunteers that line at the start of a call is your setting; that it answers " +
      "honestly when a caller asks — “I am an AI assistant” — is not, and no " +
      "script can override it.",
  },
  {
    icon: Database,
    title: "Recordings are kept for at least 90 days",
    body:
      "The 90-day floor is enforced by the database itself, so a shorter retention " +
      "policy cannot be set — not by you and not by us.",
  },
];

/**
 * WHERE EACH PART OF A CALL RUNS. VERBATIM, AND PINNED IN BOTH DIRECTIONS.
 *
 * The residency card, narrowed FOUR times and now WITHDRAWN as an India claim (D-449,
 * 22 Aug 2026): the declared model region is Azure OpenAI `eastus2`, still Regional and not
 * Global, speech and first extraction untouched and still Sarvam. ⚠ AND ON 27 AUG 2026 THE
 * INDIAN HALF WAS NARROWED TOO: Sarvam is an Indian COMPANY, but its published privacy
 * policy ("Cross-Border Data Transfers", read by the founder 27 Aug 2026 and relayed —
 * `sarvam.ai` is egress-blocked from this container) says personal data may be processed
 * outside India, naming US cloud infrastructure and EU model/security vendors. So this text
 * may say the vendor is Indian and may NOT let a reader take that for residency.
 *
 * `publicLanding.test.tsx` pins the exact substrings in BOTH directions — it must say the
 * Indian half is Indian AND that the language model is not, it must keep "checked, not
 * proved by a build", and it must not claim a build proves residency. Deleting any of those
 * clauses is how the over-claim comes back looking like a tidy-up.
 *
 * DO NOT SPELL THE AZURE HOSTNAME ANYWHERE NEAR THIS TEXT. `scripts/check_model_residency.
 * py` line-scans (no TS AST), and a string naming the watched host reads to it as an
 * endpoint built by hand.
 */
export const WHERE_IT_RUNS =
  "Speech and the first reading of your transcript are Indian services, on every call — " +
  "an Indian COMPANY, which since 27 August 2026 we no longer let you read as processing " +
  "that stays in the country: that vendor’s own published privacy policy permits it to " +
  "process personal data outside India, including on United States cloud infrastructure, " +
  "and the sub-processor page says so in its own words. The language model is not Indian " +
  "either: it runs on a Microsoft Azure OpenAI account in the United States, in the East " +
  "US 2 region. Until 22 August 2026 that account was in South India and this card said " +
  "so, and we would rather withdraw the sentence than soften it. What our code still does " +
  "is pin the model to that one region — no part of our code can send it anywhere else " +
  "without editing one frozen constant — and the account’s own region is confirmed by a " +
  "person against Microsoft’s console and filed: checked, not proved by a build. The " +
  "platform that carries the call runs it on US infrastructure today, and the " +
  "sub-processor page says which part is where before you sign.";

/**
 * What happens to a caller's data once the call is over.
 *
 * Each of these is enforced rather than promised: tenant separation is FORCEd row-level
 * security on every query (hard rule 1), transcripts default to `text_redacted` in every
 * API response with raw text behind a role check and an `audit_log` write (hard rule 5),
 * and an erasure produces a signed certificate (`apps/api/compliance/deletion_proof.py`)
 * rather than a confirmation email.
 */
export const DATA_PROMISES: readonly { term: string; detail: string }[] = [
  {
    term: "One business cannot see another",
    detail:
      "Separation is enforced by the database on every query, not by application code " +
      "remembering to filter.",
  },
  {
    term: "Phone numbers are hidden by default",
    detail:
      "Transcripts come back redacted. Seeing the raw text takes the right role and " +
      "writes an audit entry.",
  },
  {
    term: "Deletion produces a certificate",
    detail:
      "If one of your customers asks you to delete what we hold on them, there is a " +
      "button for it and it says what was destroyed and when.",
  },
];

/**
 * The scenarios an agent is run against before it goes live — and, deliberately, NOT how it
 * scored on them.
 *
 * The founder's instruction of 5 Sep 2026: show numeric quality metrics only if they are
 * genuinely measured and defensible, and otherwise show nothing that looks like a score.
 * Checked before rendering: `tests/fixtures/golden_transcripts.json` really does carry a
 * case for each of these (`core5_happy_path`, `core5_interruption`, `wrong_number_call`,
 * `hostile_caller_complaint`, `silent_call`, `core5_compliance`, `telugu_script_booking`),
 * so the LIST is a fact. Nothing publishes a per-scenario pass/fail a client-facing page
 * could read, so no surface may render a rating, a percentage, a dot row or a bar — not
 * even a tick that reads as "passed". D-36 additionally records Telugu extraction quality
 * as UNMEASURED until task #87 scores it.
 */
export const TESTED_SCENARIOS: readonly string[] = [
  "A booking that goes to plan",
  "A caller who talks over the agent",
  "A wrong number",
  "An angry caller",
  "A silent line",
  "Someone asking to be taken off the list",
  "A booking made in Telugu",
];
