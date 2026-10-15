# Pip owner consent and unmasked processing (D-788) — legal revisions, 15 Oct 2026

What changed in the published legal set when Pip (the in-app assistant) stopped masking for
consented accounts, what each new sentence rests on, and what counsel should review. Evidence
class per CLAUDE.md hard rule 11.

## The decision

| Fact | Source | Class |
|---|---|---|
| Pip is off for a client account until the account owner ticks a consent box once, for the whole account; before that it is locked for every member. Who ticked, when, the disclosure version and a SHA-256 of the disclosure text are stored; a material change to the disclosure re-asks the owner | Founder decision, 15 Oct 2026 (D-788), relayed by the lead | FOUNDER-DECISION |
| After the tick Pip sends, unmasked, to its model providers: what a person types, attached files (already unmasked since D-781), and what its look-up tools read in the client's own account — lead phone numbers, contact details, full raw call transcripts and the unredacted summary | same | FOUNDER-DECISION (implementation by the lead, in parallel) |
| Each raw-transcript read by Pip writes an audit entry, as the dashboard's raw read does | same | FOUNDER-DECISION |
| The standby (the post-call extraction company) still receives only masked text, never files, never tool results, because its terms permit training on inputs | same; Sarvam ToS v2.0 s.17.5 as recorded in `docs/legal/SUBPROCESSOR-REGISTER.md` | FOUNDER-DECISION; VENDOR-PUBLISHED (relayed 27 Aug 2026) |
| Stored conversation turns hold what the person typed, unmasked; deleted on last-session end, "Start again", the transcript retention clock, account closure, and a caller's erasure by phone number. Distilled 180-day notes and saved-routine instructions stay redacted | same | FOUNDER-DECISION |
| The admin console's Pip is never masked and needs no tick | same | FOUNDER-DECISION |
| Every Calevate admin and staff member can see all of a client's data, including through the admin console's Pip; there is no need-to-know restriction in the product | Founder instruction, 15 Oct 2026 | FOUNDER-ATTESTED |

## The first provider's no-training position

| Claim | Source | Class |
|---|---|---|
| For Paid Services, "Google doesn't use your prompts (including associated system instructions, cached content, and files) or responses to improve our products"; prompts and responses are logged for a limited time solely to detect Prohibited Use Policy violations; they "may be stored transiently or cached in any country in which Google or its agents maintain facilities"; processing is under Google's processor data processing terms | ai.google.dev/gemini-api/terms (last updated 2026-04-28, effective 23 Mar 2026), read by the lead and relayed 15 Oct 2026 | VERIFIED-VENDOR-DOCS (relayed) |
| The production Gemini key belongs to a paid, billing-enabled Google Cloud project, so the paid-service terms apply | Founder, 15 Oct 2026 | FOUNDER-ATTESTED — no OPERATIONS gate added, on the founder's instruction |

The pages say this without naming the provider (the public set names no language-model
vendor; the named list is `docs/legal/SUBPROCESSOR-REGISTER.md`), scoped to "its paid service".

## Revisions published

All four are MATERIAL: someone who accepted the previous revision did not agree to unmasked
processing of their callers' data, to the staff-access disclosure, or to the wider
responsibility and indemnity.

| Document | Revision | Hash | What changed |
|---|---|---|---|
| Privacy Policy | 24 | `sha256:d8d860f9ede05b1d1c3bc9c01487ba06fa8dc0c85caa34418a03efc66406f4df` | §3.2 owner's tick, unmasked scope, stored turns and when they are deleted, redacted notes; §4.2 Pip reads full transcripts for whoever asks, audited; §4.3 all staff see all data, with confidentiality, MFA, recorded access, purpose; §6 the tick as the client's instruction; §8 unmasked content, paid-tier no-training, standby masked; §9 the 180-day row now covers only the distilled notes; §10.1 redaction is a default with two named exceptions; §12.4 erasure deletes stored turns holding the number, the notes are still not searched |
| Terms of Service | 18 | `sha256:b9fe2e2a915c756b2350e141c88a49ebb0599801a183bd300cb6a52cd4f240d8` | Clause 4 staff use Pip only after the owner's tick and can see transcript content through it; clause 5 turning Pip on and what the team enters are the client's responsibility, a "What Calevate is not responsible for" callout, and Calevate's own duties; clause 7 staff access; clause 14.2 indemnity widened. The cap in clause 14.1 already existed and is referenced, not changed |
| Data Processing Addendum | 16 | `sha256:a3890a3d7bd58f741d0308a276f3329594a95ad8a4ac9ecb19c1f8fa5ed9a761` | Clause 1 client responsibilities, "not responsible" list, our own duties; clause 2 the tick as documented instruction, unmasked scope, audit, paid-tier no-training, standby masked; clause 3 "need-to-know" replaced by the truthful staff-access statement; clause 8 stored turns and deletion; Annex A nature and categories; Annex B.2 staff and Calevate access |
| Sub-processors | 23 | `sha256:a40cd614549c6004ffc29f5d63add14c462cde7ee2488cb7c7be90135aca4398` | Post-call extraction row: what the standby receives; language-model row: unmasked after the tick, paid-tier no-training; §3.5 the tick, unmasked scope, standby, stored turns |

Mirrored in `apps/api/legal/catalogue.py` with `material=True`.

## Why the "not responsible" clause is drawn where it is (for counsel)

Under the DPDP Act 2023 s.8(1) the Data Fiduciary is responsible for processing by it or on its
behalf "irrespective of any agreement to the contrary", and a processor's own security,
breach-notification and deletion duties cannot be contracted away, so the clause excludes
responsibility only for the client's data, notices, consents, instructions, inputs and
decisions — never our own statutory duties — because an unenforceable blanket exclusion could
weaken the enforceable parts. (s.8(1) wording: REPORTED-REPRODUCTION via dpdpa.com, see
`docs/evidence/pip-attachments-2026-10.md`; check against the Gazette.)

Each document pairs the exclusion with the client's warranty and indemnity (Terms 14.2, DPA
clause 1) and with a positive statement of what Calevate does: process lawfully on
instructions, keep data secure, delete on schedule, notify breaches as the law requires, use
only disclosed providers. Both documents add that nothing limits a duty the law places on us
that cannot be limited by contract. This replaces D-781's choice not to use the words
"Calevate is not responsible", on the founder's instruction of 15 Oct 2026.

## Open, for a human

- **Counsel review recommended before relying on these clauses**, in particular: the
  enforceability of the "not responsible" callout and the widened indemnity under the Indian
  Contract Act and the DPDP Act; whether the owner's tick is a sufficient documented
  instruction under s.8(2) for unmasked processing of callers' data by a provider outside
  India; and whether the staff-access disclosure needs a matching internal access policy.
  This is drafting by engineers from primary and relayed sources, not legal advice.
- The pages say a client's staff member can ask Pip about any call and that Pip reads the full
  transcript to answer, although staff cannot open the raw transcript on a screen. That is
  what D-788 describes; if the build restricts raw-transcript tools to the owner role, Terms
  clause 4, Privacy §4.2 and DPA Annex B.2 must narrow to match.
- The public marketing copy (`apps/web/src/lib/marketing/compliance.ts`,
  `apps/web/src/components/marketing/faq.tsx`) still says transcripts come back redacted and
  raw text needs the right role, and that the dashboard assistant runs in East US 2; neither
  mentions Pip's unmasked reads or staff access. Owned by another lane; reported, not edited.
