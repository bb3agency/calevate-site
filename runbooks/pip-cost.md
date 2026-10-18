# Runbook — checking what Pip costs, and whether the prompt cache is working

No alarm sends you here. Use it after a deploy that touches Pip's prompt or tools, when the
AI spend card looks higher than expected, or when the founder asks whether a change kept the
quality and cut the cost (D-816).

## 1. Is the provider's prompt cache being hit?

Every metered assist logs `ai_assist_metered` (client accounts) or
`platform_ai_assist_metered` (the admin console) with `feature`, `model`, `input_count` and
`cached_input_count`. Counts only; no question or answer is logged.

* `cached_input_count` is a number: the provider reported its cache hits. Hit rate =
  sum(`cached_input_count`) / sum(`input_count`) over a day, per `feature`.
* `cached_input_count` is `null`: the provider sent no cached count, which is NOT zero hits.
  Google documents no cached field on its OpenAI-compatible surface
  (ai.google.dev/gemini-api/docs/openai, read 18 Oct 2026), so Gemini answers may show
  `null` while Google's own billing shows cache savings. Compare the month's ledger with the
  Google Cloud billing export for the same model before concluding anything.

## 2. Price cached input at the cached rate

Ops console → model prices → the model → "Update price". Enter the input, output and
**cached input** figures from the same invoice (US$ per million tokens). From then on, when
the provider reports cached tokens, the ledger writes them as `ai_assist_10ktok_cached_in`
at the cached rate and the rest as `ai_assist_ktok_in`. With no cached figure attested, all
input is priced at the input rate, as it was before D-816.

## 3. Compare Pip before and after a change (the live eval)

Runs on a deployment that holds the real keys, never in CI. It costs real money and prints
the total.

```
uv run python -m scripts.copilot_tool_eval --live --spend --tenant=<demo account id> \
    --record=before.json
# deploy the change
uv run python -m scripts.copilot_tool_eval --live --spend --tenant=<demo account id> \
    --record=after.json
uv run python -m scripts.copilot_tool_eval --compare before.json after.json
```

* Use a demo account: its leads and calls are what the client questions read. Answers are
  passed through `redact()` before they are written to the record file.
* Every question runs the production loop on the production model tiers. No principal is
  passed, so every write tool refuses and nothing is changed.
* Read the comparison per question: the tools chosen should be the same or better, the
  answers should say the same thing, and input tokens and rupees should fall.
* Without `--spend` the script refuses. `--only=admin` or `--only=client` runs one realm.
