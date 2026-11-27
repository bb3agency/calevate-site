# Simulated-call release gate and first-run eval (W3.1, W3.3, W3.13, W3.14 fixtures)

## What exists

- **Real-call personas.** `scripts/fixtures/call_sim/recorded/rytu/stops_early.json` is the
  founder's Telugu call of 27 Nov 2026 (21:35), and `bare_okay.json` is his call of 28 Nov 2026
  (00:48). Both transcripts are as the call page showed them, with the person's name replaced
  ("Ravi") and no number. Their agent lines are the defects being measured and must never be
  used as examples. The step readings are the founder's. The personas `stops_early` (stops
  once three things are done) and `bare_okay` (an injected "Okay." on caller turns 3, 5, 7 and 9)
  replay both shapes live, and `forgot_registering` now asks what the business is.
- **New scorecard kinds** (`scripts/call_sim/scorecard.py`): `bare_okay_accepted`,
  `left_unsaid`, `records_claim` and `number_not_by_digit`. A bare acknowledgement is no
  longer read as "done" (`done_signal`), and an Indian-language sentence counts as an action
  only when it holds one of the caller-action verbs the founder listed. Other kinds the founder
  named were already there: `claimed_complete` (read from the step reading), `asks_when_done`
  (asks the caller to report back), `several_actions`, `same_opening`/`same_closing` and
  `spoken_number`.
- **Release gate**: `python -m scripts.eval_calls --release --holder campaign:<id>` gives
  10 live runs of each release persona. It counts gated kinds per run and fails when a kind's
  share of runs rises against `live-baseline.json`, or when a hard-rule kind shows at all. The
  counts are written beside the report as `.json`. Row in `docs/OPERATIONS.md` §3.1.
- **First-run end-to-end eval** (`python -m scripts.eval_script_writer --cases
  first_run_rytu,first_run_clinic_inbound`). Each case runs brief → questions → answers → main
  task, calling window and pinned facts (the product's own code) → script. The cases are the
  28 Nov first-run brief, verbatim, and a fictional English inbound clinic brief that carries a
  fee and an urgent number. Each is scored on seven checks:
  - an areas question asked of a remote business, or a question the brief already answers;
  - the opening exists and, on a placed call, passes `placed_opening_problems`;
  - one step per owner task;
  - the brief's facts are pinned;
  - the Never rules are pinned;
  - the owner's numbers reach the call;
  - the calling window is applied.
- **Inbound fixture** `scripts/fixtures/call_sim/clinic_inbound.json`, with two stand-ins:
  - an emergency number written as `108`, which is flagged;
  - a fee written as `500 rupees`, which is an amount and is not flagged.

## Scores on the current checks (recorded, no model)

These score the **recorded** transcripts, so the two evidence calls show what 0.5.96 and
0.5.97 said. They do not measure what the current prompt makes the model say. Only a live run
measures that.

| Recording | Score | Kinds found (first turn) |
|---|---|---|
| stops_early (27 Nov 21:35) | 0 | records_claim @10, several_actions @16, asked_done_too_soon @18, same_opening @28, same_closing @44, bare_okay_accepted @54, claimed_complete @58, left_unsaid @58, too_long, formal_words |
| bare_okay (28 Nov 00:48) | 40 | several_actions @10, asked_done_too_soon @10, bare_okay_accepted @26, same_closing @34, asks_when_done @36, same_opening @44, formal_words |

- Total for the `rytu` set is 1010 of 1700 over 17 personas, and the baseline has been
  rewritten. The 15 earlier personas' scores are unchanged.
- First-run eval, recorded stand-ins: both cases PASS.
- Clinic note: the code reads **0** tasks from an inbound brief ("tell them our timings and
  fees, and book appointments"), because `owner_words.owner_tasks` reads only lists of things
  the person does. The clinic's plan is therefore the writer's own reading of the brief.
- Clinic urgent number: "If a caller has chest pain ... call 108" opens with "If". That makes
  it a case rather than a stated fact, so it is not pinned, and only the script can carry the
  number (tested).

## Detector gaps seen on the evidence calls (not this lane's files)

- 21:35 turn 16 is read as `several_actions`, but it gives one action. The quoted button label
  "Tap here to Install on Android" carries two English action verbs
  (`script_lint.stacked_line`). The kind is right for the call (turns 34, 48 and 54), but the
  first turn is wrong.
- `asked_done_too_soon` on 21:35 turn 18 ("is the icon on your home screen?") is a question
  about what the caller sees, which is the asked-for behaviour (`turn_checks`).
- `left_unsaid` reads only whether the agent offered to finish later (a question, or a call
  back booked). It cannot tell from words whether a Telugu reply named what is left, because
  the step names are English. `claimed_complete` (the step judge) covers the false
  "all done".

## What remains to run live (no Google key here: `GEMINI_API_KEY` empty, exit 2)

1. On the VPS: `eval_calls --release --holder campaign:<Rytu Khata campaign id>`. Review the
   counts, then commit the report and `--write-live-baseline`. The W3.1 acceptance is 0 of each
   gated kind across 10 runs per persona. W3.13's is 0 `claimed_complete` and 0 `left_unsaid`.
2. `eval_script_writer --cases first_run_rytu,first_run_clinic_inbound --live --spend --format
   json`, then `--import-live` to replace the stand-ins. Acceptance: both PASS live.
3. `eval_calls --fixture clinic_inbound --live --personas urgent,business_question --runs 10`
   to measure `number_not_by_digit` and `spoken_number` on the in-call model (W3.14).
