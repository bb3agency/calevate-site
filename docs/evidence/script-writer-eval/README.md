# Script writer evaluation

Reports of `python -m scripts.eval_script_writer`, which scores Pip's script writer on the
fixed case set in `tests/fixtures/script_writer_cases/`. The module docstring is the full
account of what each check reads and what a live run does and does not reproduce.

## Files here

- `<date>-recorded.md`: the recorded outputs scored with no model. Until a live run is
  imported these are stand-ins: the production Rytu Khata script of 25 Nov 2026 in English
  stand-in form, and hand-written fake model outputs for the other cases. They test the
  checks, not the writer.
- `live-<date>.json`: a live run from the VPS (below). Its `markdown` field is the report;
  its `outputs` are the scripts the writer wrote.

## A live run, on the VPS

Our Gemini key is only on the VPS. One command, from the deployed checkout (the image holds
`scripts/` but not `tests/`, so the case set is copied into the running workers container):

```
sudo -u calevate bash -lc 'cd /var/www/calevate && C="docker compose -p calevate \
  -f compose.prod.yml" && $C cp tests/fixtures/script_writer_cases workers:/tmp/swc \
  && $C exec -T workers python -m scripts.eval_script_writer --cases-dir /tmp/swc \
  --live --spend --judge --judge-against recorded --format json \
  > docs/evidence/script-writer-eval/live-$(date +%F).json'
```

It needs a deploy that includes `scripts/eval_script_writer.py`. It writes each case's first
script as a campaign or line is written (draft, one refining edit, code's mends) on our
Gemini leg, scores it, and prints the tokens used. Nothing is metered to an account.
`--judge` scores naturalness alone; `--judge-against recorded` compares each new script with
the recorded one in both orders (a verdict the order changes is reported as a split). Both
judges are uncalibrated against founder-labelled calls and run on the writer's own model
family; the report says so. Drop both for the deterministic checks only.

To make a live run the new recorded set (in the dev container, not on the host):

```
uv run python -m scripts.eval_script_writer --import-live docs/evidence/script-writer-eval/live-<date>.json
uv run python -m scripts.eval_script_writer --write-baseline --write-report
```

## CI

`tests/eval_script_writer_test.py` scores the recorded set against
`tests/fixtures/script_writer_cases/baseline.json`. A count that moves either way fails
until the baseline is rewritten with `--write-baseline`. The judge never runs in CI.
