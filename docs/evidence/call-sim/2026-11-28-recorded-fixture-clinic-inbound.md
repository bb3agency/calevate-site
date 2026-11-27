# Simulated calls (recorded)

- Recorded transcripts: `scripts/fixtures/call_sim/recorded/clinic_inbound`
- Holder: `fixture:clinic_inbound`
- Total: **185** of 200 (mean 92.5 over 2 personas)

`@n` is the transcript turn a kind first shows on. Steps are reached/expected.

| Persona | Score | Steps | Repeats | Done too soon | Moved on | Early stop | >1 ask | Asked known | AI answer | DNC step | Lookups | Other |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Asks a business question mid-step | 100 | ?/2 | - | - | - | - | - | - | - | - | 1/1 | - |
| Has an emergency | 85 | - | - | - | - | - | - | - | - | - | - | number_not_by_digit |

## Kinds across personas

| Kind | What it means | Personas |
|---|---|---|
| `number_not_by_digit` | Said a number as one quantity, not digit by digit | 1 |

## Notes

- Stand-ins, not model runs: business_question, urgent (see each recording's source).
- Script: stages.1.instruction: step 2 has an outcome and nowhere to go if it cannot be reached; give it an Otherwise, and a way out to a call back only for someone who still cannot after being guided step by step.
- Script: stages.0.scripts.en-IN: greets again or asks again whether now is a good time, which the opening line already did; start this step from what comes after their yes.
