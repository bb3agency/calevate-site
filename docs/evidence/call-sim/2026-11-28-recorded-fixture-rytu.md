# Simulated calls (recorded)

- Recorded transcripts: `scripts/fixtures/call_sim/recorded/rytu`
- Holder: `fixture:rytu`
- Total: **1010** of 1700 (mean 59.4 over 17 personas)

`@n` is the transcript turn a kind first shows on. Steps are reached/expected.

| Persona | Score | Steps | Repeats | Done too soon | Moved on | Early stop | >1 ask | Asked known | AI answer | DNC step | Lookups | Other |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Cooperative | 60 | 3/3 | said_again @14, same_opening @14 | asks_when_done @6 | - | - | several_actions @6 | - | - | - | - | no_breath, early_comma |
| Silent while doing a step | 55 | 1/2 | - | asks_when_done @12 | - | - | several_questions @8, several_actions @12 | - | - | - | 0/1 | steps_short, no_breath, missed_lookup |
| Garbled replies | 15 | 3/2 | said_again @14, asked_again @24, same_closing @26 | asked_done_too_soon @16, asks_when_done @4 | moved_on_unclear @16 | - | several_questions @16, several_actions @4 | asked_known_value @6 | - | - | - | no_breath, too_long, early_comma |
| Not now | 100 | - | - | - | - | - | - | - | - | - | - | - |
| Not interested | 95 | - | same_opener_twice @6 | - | - | - | - | - | - | - | - | - |
| Wrong person | 95 | - | - | - | - | - | - | - | - | - | - | opened_again |
| Doesn't remember registering | 65 | 1/1 | - | asks_when_done @8 | - | - | several_actions @8 | - | - | - | 0/1 | no_breath, too_long, missed_lookup |
| iPhone instead of Android | 60 | 1/2 | said_again @6 | asks_when_done @4 | - | - | several_actions @4 | - | - | - | - | steps_short, no_breath |
| Asks a business question mid-step | 45 | 2/2 | said_again @10 | asks_when_done @4 | - | - | several_actions @4 | - | - | - | 0/1 | no_breath, too_long, early_comma, missed_lookup |
| Gets stuck | 25 | 2/2 | said_again @18, same_opening @10, same_opener_twice @8 | asks_when_done @8 | - | - | several_actions @10 | - | - | - | 0/1 | early_comma, no_breath, opened_again, brackets, too_long, missed_lookup |
| Asks to repeat | 35 | 1/2 | said_again @8, repeated_turn @6 | asks_when_done @4 | - | - | several_actions @4 | - | - | - | 0/1 | steps_short, no_breath, too_long, missed_lookup |
| Answers in English letters | 70 | 2/3 | same_opener_twice @8 | asks_when_done @6 | - | - | several_actions @6 | - | - | - | - | steps_short, no_breath |
| Impatient | 70 | 2/2 | same_opener_twice @8 | asks_when_done @6 | - | - | several_actions @6 | - | - | - | - | early_comma, no_breath, too_long |
| Asks if this is an AI | 80 | 1/1 | - | asks_when_done @6 | - | - | several_actions @6 | - | yes | - | - | too_long, no_breath |
| Stops early at a known step | 0 | 7/3 | same_opening @28, same_opener_twice @14, same_closing @44 | asked_done_too_soon @18 | bare_okay_accepted @54 | claimed_complete @58, left_unsaid @58 | several_actions @16 | - | - | - | - | early_comma, no_breath, records_claim, too_long, formal_words |
| Says a bare okay | 40 | 8/2 | same_opening @44, same_opener_twice @10, same_closing @34 | asked_done_too_soon @10, asks_when_done @36 | bare_okay_accepted @26 | - | several_actions @10 | - | - | - | - | early_comma, no_breath, formal_words |
| Asks to be removed | 100 | - | - | - | - | - | - | - | - | yes | - | - |

## Kinds across personas

| Kind | What it means | Personas |
|---|---|---|
| `no_breath` | no breath | 13 |
| `several_actions` | Gave the caller more than one thing to do in one turn | 13 |
| `asks_when_done` | Kept asking the caller to say when each step was done | 12 |
| `too_long` | Said too much in one turn | 8 |
| `early_comma` | early comma | 7 |
| `said_again` | Said the same line again | 6 |
| `same_opener_twice` | Opened two replies in a row with the same reaction | 6 |
| `missed_lookup` | Did not look up your information when it was needed | 5 |
| `same_opening` | Began reply after reply with the same words | 4 |
| `steps_short` | Did not get as far through the steps as a good call does | 4 |
| `asked_done_too_soon` | Asked if a step was done before the caller could do it | 3 |
| `same_closing` | Ended reply after reply with the same words | 3 |
| `bare_okay_accepted` | Took a bare okay as done and gave the next thing to do | 2 |
| `formal_words` | Used textbook words | 2 |
| `opened_again` | Greeted the caller again in the middle of the call | 2 |
| `several_questions` | several questions | 2 |
| `asked_again` | Asked the same question again, word for word | 1 |
| `asked_known_value` | Asked for something the call already knew | 1 |
| `brackets` | Read out something in brackets | 1 |
| `claimed_complete` | Said the task was finished when steps were left | 1 |
| `left_unsaid` | Let a caller who stopped early go without offering to finish later | 1 |
| `moved_on_unclear` | Moved on after an unclear reply | 1 |
| `records_claim` | Said records or a system show something, which the agent cannot look up | 1 |
| `repeated_turn` | repeated turn | 1 |

## Notes

- Stand-ins, not model runs: cooperative, silent, garbled, not_now, not_interested, wrong_person, forgot_registering, iphone, business_question, stuck, asks_repeat, english_letters, impatient, asks_ai, stops_early, bare_okay, remove_me (see each recording's source).
- Script: stages.s2: a way out's condition is the step title 'Add Farms'
- Script: stages.s3: a way out's condition is the step title 'Enter Expenses'
- Script: stages.s4: a way out's condition is the step title 'Enter Sales'
- Script: stages.s5: a way out's condition is the step title 'Dashboard'
- Script: stages.s6: a way out's condition is the step title 'Finalise the call'
- Script: stages.s7: a way out's condition is the step title 'Not registered'
- Script: stages.6.scripts.en-IN: opens with the reaction "thank you"; the agent copies it into every reply. Start it with its own point, or vary how the lines open.
- Script: stages.0.scripts.en-IN: says more than 2 short sentences or asks more than one question in one turn; keep it to one point or one question, then let them speak.
