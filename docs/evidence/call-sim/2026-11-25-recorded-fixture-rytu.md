# Simulated calls (recorded)

- Recorded transcripts: `scripts/fixtures/call_sim/recorded/rytu`
- Holder: `fixture:rytu`
- Total: **1030** of 1500 (mean 68.7 over 15 personas)

`@n` is the transcript turn a kind first shows on. Steps are reached/expected.

| Persona | Score | Steps | Repeats | Done too soon | Moved on | >1 ask | Asked known | AI answer | DNC step | Lookups | Other |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Cooperative | 70 | 3/3 | said_again @14 | - | - | several_actions @6 | - | - | - | - | no_breath, early_comma |
| Silent while doing a step | 60 | 1/2 | - | - | - | several_questions @8, several_actions @12 | - | - | - | 0/1 | steps_short, no_breath, missed_lookup |
| Garbled replies | 20 | 3/2 | said_again @14, asked_again @24, same_closing @26 | asked_done_too_soon @16 | moved_on_unclear @16 | several_questions @16, several_actions @4 | asked_known_value @6 | - | - | - | no_breath, too_long, early_comma |
| Not now | 100 | - | - | - | - | - | - | - | - | - | - |
| Not interested | 95 | - | same_opener_twice @6 | - | - | - | - | - | - | - | - |
| Wrong person | 95 | - | - | - | - | - | - | - | - | - | opened_again |
| Doesn't remember registering | 70 | 1/1 | - | - | - | several_actions @8 | - | - | - | 0/1 | no_breath, too_long, missed_lookup |
| iPhone instead of Android | 65 | 1/2 | said_again @6 | - | - | several_actions @4 | - | - | - | - | steps_short, no_breath |
| Asks a business question mid-step | 50 | 2/2 | said_again @10 | - | - | several_actions @4 | - | - | - | 0/1 | no_breath, too_long, early_comma, missed_lookup |
| Gets stuck | 30 | 2/2 | said_again @18, same_opening @10, same_opener_twice @8 | - | - | several_actions @18 | - | - | - | 0/1 | early_comma, no_breath, opened_again, brackets, too_long, missed_lookup |
| Asks to repeat | 40 | 1/2 | said_again @8, repeated_turn @6 | - | - | several_actions @4 | - | - | - | 0/1 | steps_short, no_breath, too_long, missed_lookup |
| Answers in English letters | 75 | 2/3 | same_opener_twice @8 | - | - | several_actions @6 | - | - | - | - | steps_short, no_breath |
| Impatient | 75 | 2/2 | same_opener_twice @8 | - | - | several_actions @6 | - | - | - | - | early_comma, no_breath, too_long |
| Asks if this is an AI | 85 | 1/1 | - | - | - | several_actions @6 | - | yes | - | - | too_long, no_breath |
| Asks to be removed | 100 | - | - | - | - | - | - | - | yes | - | - |

## Kinds across personas

| Kind | What it means | Personas |
|---|---|---|
| `no_breath` | no breath | 11 |
| `several_actions` | Gave the caller more than one thing to do in one turn | 11 |
| `too_long` | Said too much in one turn | 7 |
| `said_again` | Said the same line again | 6 |
| `early_comma` | early comma | 5 |
| `missed_lookup` | Did not look up your information when it was needed | 5 |
| `same_opener_twice` | Opened two replies in a row with the same reaction | 4 |
| `steps_short` | Did not get as far through the steps as a good call does | 4 |
| `opened_again` | Greeted the caller again in the middle of the call | 2 |
| `several_questions` | several questions | 2 |
| `asked_again` | Asked the same question again, word for word | 1 |
| `asked_done_too_soon` | Asked if a step was done before the caller could do it | 1 |
| `asked_known_value` | Asked for something the call already knew | 1 |
| `brackets` | Read out something in brackets | 1 |
| `moved_on_unclear` | Moved on after an unclear reply | 1 |
| `repeated_turn` | repeated turn | 1 |
| `same_closing` | Ended reply after reply with the same words | 1 |
| `same_opening` | Began reply after reply with the same words | 1 |

## Notes

- Stand-ins, not model runs: cooperative, silent, garbled, not_now, not_interested, wrong_person, forgot_registering, iphone, business_question, stuck, asks_repeat, english_letters, impatient, asks_ai, remove_me (see each recording's source).
- Script: stages.s2: a way out's condition is the step title 'Add Farms'
- Script: stages.s3: a way out's condition is the step title 'Enter Expenses'
- Script: stages.s4: a way out's condition is the step title 'Enter Sales'
- Script: stages.s5: a way out's condition is the step title 'Dashboard'
- Script: stages.s6: a way out's condition is the step title 'Finalise the call'
- Script: stages.s7: a way out's condition is the step title 'Not registered'
- Script: stages.6.scripts.en-IN: opens with the reaction "thank you"; the agent copies it into every reply. Start it with its own point, or vary how the lines open.
