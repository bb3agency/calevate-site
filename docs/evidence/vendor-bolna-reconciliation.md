# Bolna adapter — reconciliation against primary sources

**Date:** 2026-08-18. **Decisions:** D-260, D-261, D-262.
**Evidence:** `docs/vendor/bolna/` (harvest + classes). **Subject:**
`apps/api/engine/bolna.py`, `apps/api/engine/capabilities.py`,
`packages/shared/src/calevate_shared/engine.py`, `.../events.py`.

The adapter was written largely from reasoning and said so. This is the pass that replaced
reasoning with sources where sources exist, and sharpened the rest into named gates.

## What could actually be sourced

`bolna-ai/bolna` was **cloned and read in full** at commit `cd2e192` — the whole package,
not the README. That is a far stronger footing than the adapter previously stood on and it
is the origin of every VERIFIED-OSS row. The hosted docs remain unread: `docs.bolna.ai`,
`www.bolna.ai` (including its `/docs/` path) and `api.bolna.ai` are all `EGRESS_BLOCKED`,
so every hosted claim is a search summary.

## The table

| # | Assumption as it stood | Evidence class now | What changed |
|---|---|---|---|
| 1 | Task body needs no `toolchain` | **VERIFIED-OSS** — `Task.toolchain` has no default; runtime does `task["toolchain"]["pipelines"]` in two places, one of which decides audio-vs-text input | **FIXED.** Body now sends `{"execution": "parallel", "pipelines": [["transcriber","llm","synthesizer"]]}` — their own builder's value. Test + sabotage-verified. |
| 2 | Transcript is `assistant:`/`user:` prefixed text | **VERIFIED-OSS** — `format_messages` confirms both, **and** emits `system:`, `assistant_tool_call:`, `tool_response:` | **FIXED.** Those three matched nothing and were appended to the previous speaker's turn, splicing tool-call arguments into what the transcript said the agent said. Now recognised, skipped, and counted into `transcript_lines_unparsed`. Test + sabotage-verified. |
| 3 | Agent read-back nests everything under `agent_config` | **VERIFIED-OSS** — `GET /agent/{id}` returns `agent_config.model_dump()`, so `tasks` is at the ROOT | **FIXED.** `_agent_models` now falls back to the root like `_agent_name`/`_agent_greeting` already did; it was reporting `models_readable=False` for a readable agent. Test + sabotage-verified. |
| 4 | `family` selects the LLM vendor | **VERIFIED-OSS** — `family` is read by **nothing**; `llm_config["provider"]` selects the class; `Llm.provider` defaults to `"openai"`; `LLMProvider` has no `sarvam` | **NOT changed — sharpened + gated.** No correct `provider` value is derivable for D-36's Sarvam LLM, and `ModelConfig` has no `llm_provider` to carry one. Guessing would be a 400 or a mis-route. → **gate 16.** |
| 5 | `total_cost` / `cost_breakdown` are **USD cents** | **VERIFIED-OSS argues against** (their cost fn returns a rounded **dollar** float); **REPORTED-DOCS argues against** (all prices quoted in dollars/min) | **NOT changed — named + gated.** The bare `/ 100` became `_ASSUMED_MINOR_UNITS_PER_MAJOR` with the counter-evidence and the cost of being wrong (100x under-metering, no cap ever arms). Hosted billing ≠ that OSS function, so inference is not enough on the money path. → **gate 7 rewritten.** |
| 6 | `cost_breakdown` keys `platform`/`network` | **REPORTED-DOCS** — Get Execution summary names all five: `llm`, `network`, `platform`, `synthesizer`, `transcriber` | Unchanged (already correct). Two previously-unsourced keys now have a source; the other three are also VERIFIED-OSS. |
| 7 | "Their 15-value status enum" | **STILL UNVERIFIED** — the OSS repo has **no call-status enum at all**; the count had no source anywhere | **Comment corrected.** REPORTED-DOCS confirms only `scheduled → queued → in-progress → completed` and that `completed` is final. The other eleven keys stay unverified. |
| 8 | `voicemail` is a status value | **STILL UNVERIFIED, and contradicted in shape** — reported as a boolean field `answered_by_voice_mail`; OSS has it as `HangupReason.VOICEMAIL_DETECTED` | **NOT changed — marked + gated.** If it is a flag, our `voicemail` `CallStatus` is unreachable and voicemails read as ordinary completed calls. → **gate 17.** |
| 9 | Webhook payload == Get Execution shape | **REPORTED-DOCS** — "matches the Get Execution API response format" | Unchanged (`parse_webhook` already reuses `_snapshot`). Load-bearing for receiver *and* poller, so gate 1 keeps the byte-level comparison. |
| 10 | `billable_ready` ⇔ `status == "completed"` | **REPORTED-DOCS** — `completed` is the final status, after which recordings and extraction are done | Unchanged; now sourced rather than asserted. |
| 11 | `transfer=False` because unverified | **VERIFIED-OSS** — transfer **exists**, as an LLM-invoked in-call tool with a config-supplied number and a `has_transfer` latch; no REST route transfers a live execution | **Value unchanged, reason replaced.** `False` is now a statement about shape mismatch with `VoiceEngine.transfer(call_id, to, warm)`, not a shrug. Using the built-in is a design change (escalation number becomes engine config). → **gate 18.** |
| 12 | Repeat `DELETE` answers 404 | **VERIFIED-OSS (intent only)** — their server *raises* 404 for an absent agent, then swallows it in `except Exception` and returns **500** | **NOT changed — sharpened.** Upgraded from guessed to OSS-backed intent. Gate 2's sub-check still owns it. The 404-that-is-a-500 is now the worked example of why VERIFIED-OSS ≠ hosted. |
| 13 | Sarvam is selectable on all three legs (BYOK) | **VERIFIED-OSS on STT + TTS** (`SarvamTranscriber`, `SarvamSynthesizer`); **absent on LLM** (`LLMProvider` has no `sarvam`) | Capability flags unchanged. The LLM half folds into row 4 / gate 16. |
| 14 | `max_tokens` / `temperature` are the vendor's problem | **VERIFIED-OSS** — unsent, so defaults apply: `max_tokens=100`, `temperature=0.1` | **FIXED (D-283).** The body now sends `max_tokens: 400` and `temperature: 0.1` explicitly. 400 because a cap is a safety valve, not a style control — 100 tokens is ~45 Telugu words at ~2.1–2.3 tokens/word and a receptionist reading back three slots passes it, so the default truncates mid-sentence and the TTS speaks a fragment; the LLM leg is free per token (D-35/D-36) so the headroom costs nothing and `max_call_duration_s` bounds the other side. 0.1 because the vendor's default is RIGHT here — the agent reads a client's script with `TRUTHFUL_ANSWER_DIRECTIVE` under it and the failure that matters is paraphrasing a compliance sentence away — and it is sent anyway because a vendor default is somebody else's release note. Gate 16's read-back still records what comes back. |
| 15 | `GET /agent/{id}` echoes `agent_prompts` | **VERIFIED-OSS says no** — prompts are stored in a separate file and are not in the GET response | Unchanged. On that server `system_prompt_readable=False` is the honest answer, which is what the code already produces. Gate 2 measures the hosted path. |

## Schemas

`packages/shared/src/calevate_shared/engine.py` and `events.py` needed **no change**.
`CallStatus`, `ExecutionSnapshot` and `CostBreakdown` are all in our own vocabulary; the
one field whose meaning was in doubt (`voicemail`) is a mapping question inside the
adapter, not a schema defect. Hard rule 2 holds: the raw vendor document still crosses the
boundary only as `raw_document: bytes`, and no vendor key name was added to any typed
column.

## Gates opened or rewritten

| Gate | Question | Blocked on |
|---|---|---|
| 7 (rewritten) | Is `total_cost` in dollars or cents? | A Bolna account + one completed call |
| 16 (new) | Does the hosted agent object honour `provider` or `family`, and what value selects a non-OpenAI LLM? | A Bolna account |
| 17 (new) | Is `voicemail` a status, or only `answered_by_voice_mail`? | A Bolna account + one voicemail call |
| 18 (new) | Does the hosted agent accept a transfer tool; is there any REST live-transfer? | A Bolna account |

Every one is blocked on the same external thing — **a Bolna account with credentials** —
which is the pilot itself (OPERATIONS §2), not an engineering task anyone here can do.
