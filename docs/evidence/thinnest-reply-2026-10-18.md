# ThinnestAI's 18 Oct 2026 reply (questions 1–18), checked against the docs snapshot of 18 Oct 2026

**Source of the claims.** Ashutosh K (founder, ThinnestAI) answered questions 1–18 of the email
drafted in `docs/vendor/thinnest-replies-2026-10-12.md` §15 on 18 Oct 2026, 11:19 IST. The founder
relayed it; its text is in that file, §16. On its own it is **VENDOR-STATED**. He wrote that items
5, 6 and 9 "need a release to be live", to be confirmed separately.

**Source of the verdicts.** `thinnest-findings/mirror/snapshots/2026-10-18/` is a full re-fetch of
every `.md` link in `https://docs.thinnest.ai/llms.txt` (UTC run 07:39–07:43; 285 of 285 pages, 0
failures; against `2026-10-15/`, 1 page added and 13 changed). Every path below is under
`thinnest-findings/mirror/snapshots/2026-10-18/pages/`. Everything cited is
**VERIFIED-VENDOR-DOCS** as of 18 Oct 2026. Where the docs are silent, the item says so and the
claim stays VENDOR-STATED.

## Summary

| # | Question | Verdict |
|---|---|---|
| 1 | A developer clone's id in a customer workspace | **VERIFIED in part.** `GET /voices` in a customer workspace lists the developer's clones with `sharedFromDeveloper: true`, "so every id here is one you can set" (`api-reference/voices/list-voices.md:7`, `:452-454`). That the id equals the developer workspace's `voiceId` is VENDOR-STATED |
| 2 | `billing` on a forwarded call with no agent | **VERIFIED.** Carrier fee only; `voicePlan` and `ratePerMinuteMicro` show the set-up plan, not what was charged; reconcile by `costMicro` (`api-reference/calls/get-call.md:1235-1243`) |
| 3 | What a free trial call is | **VERIFIED.** Null plan, rate and billed seconds only for a call paid from a free-plan workspace's trial minutes; a developer's own test calls carry them (`api-reference/calls/get-call.md:1246-1249`). The trial rate in a customer workspace on a trial is VENDOR-STATED |
| 4 | Carrier block and fee for a call that ended before the agent spoke | **VERIFIED.** ₹0.38 a minute in 30-second blocks, ₹0.19 each, `billedSeconds` rounded up to the block (`api-reference/calls/get-call.md:1235-1243`) |
| 5 | `billing` on List Calls | **DOCUMENTED** (`api-reference/calls/list-calls.md:772`; `whats-new/index.md`, 17 Oct). Live in production: **NOT CONFIRMED** (release pending, per the email) |
| 6 | `voice.reaskAfterSeconds`; reply languages | **DOCUMENTED.** `reaskAfterSeconds` 0, 1.5–10 or null (`api-reference/agents/update-agent.md:1452-1461`); `languages` up to four, the first the fallback, `languages` or `language` but not both, `secondLanguage` retired (`:754-780`). Live: **NOT CONFIRMED** (release pending) |
| 7 | Per-agent `byok` live everywhere | VENDOR-STATED |
| 8 | Post-call summary and extraction model; cached tokens | VENDOR-STATED. No page states which model writes the summary and the collected fields. Whether Google bills `cachedInputTokens` at its cached rate is "the provider's decision" |
| 9 | Own model on a Clear agent | **DOCUMENTED.** `409` only when the workspace brings no keys or only its voice key; `llm`, `llm_voice` and `all` can set an agent's model (`api-reference/agents/set-agent-byok-model.md:514-525`). Live: **NOT CONFIRMED** (release pending) |
| 10 | Prices | VENDOR-STATED. No page in the snapshot states Studio ₹3.00, Premium ₹2.50, Standard ₹2.00 a minute or the Scale plan's 5% |
| 11 | The speaking rules | VENDOR-STATED; the text is `docs/vendor/thinnest-speaking-rules-2026-10-18.md` |
| 12 | `voice.surfaces: []` on an agent with no number | **VERIFIED.** `phone_number_required` names adding `phone` with no number (`api-reference/agents/update-agent.md:612-622`) |
| 13 | What the model sees when the caller goes quiet | VENDOR-STATED. The docs define `nudgeAfterSeconds` and its silence window (`channels/voice.md:660-667`), not what the model receives |
| 14 | Where our instructions sit; caching | VENDOR-STATED. No page states the prompt order or the cached prefix |
| 15 | What "answers the phone" means for Place Call | **VERIFIED in part.** Place Call refuses when no agent answers the phone (`api-reference/calls/place-call.md:619-636`). That Answer calls must be on for a borrowing agent is VENDOR-STATED |
| 16 | Lending | **VERIFIED in part.** `callingAgent` "lets an agent call out on it without answering it" (`api-reference/phone-numbers/update-phone-number.md:7`, `:461`). One borrower at a time, and that lending adds no surface, are VENDOR-STATED |
| 17 | `Idempotency-Key` on renting a number | VENDOR-STATED. `api-reference/phone-numbers/rent-phone-number.md` does not mention it |
| 18 | 140-series numbers | **Different in the docs.** `channels/phone-numbers.md:188-215` describes a 140 number issued in the business's own name after DLT registration, applied for through ThinnestAI. The email says they do not offer them, their carrier requires a ₹1 lakh minimum commitment, and 140 is blocked as a forwarding destination. Calevate does not pursue promotional calling (founder, 18 Oct 2026) |
