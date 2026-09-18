# The sub-processor register, audited FROM THE CODE — 18 September 2026

**The question.** Not "is every row on `apps/web/src/lib/legal/subprocessors.ts` correct"
— `apps/web/tests/legal.test.tsx` already asks a version of that — but the opposite one:
**which third party can this tree send a client's data to, and is it on the page?** The
register is the authorised list under clause 5 of the DPA and the Privacy Policy
incorporates it, so a vendor missing from it is an undisclosed recipient.

The register's own header records an August 2026 pass of the same shape, which found three
client-switched integrations (Google Calendar, AiSensy, Interakt) and then said the part
that mattered: *"nothing in the tree can notice when our actual vendors and this list
diverge."* This pass closed that with `scripts/check_subprocessor_coverage.py` and found
two more vendors on the way.

## What the guard derives, and from what

| Signal | Source | Why it is the right signal |
| --- | --- | --- |
| A credential-shaped `Settings` field (`*_api_key`, `*_auth_token`, `*_base_url`, `*_endpoint`, `*_dsn`, …) | `packages/shared/src/calevate_shared/config.py::Settings`, parsed from the AST | A platform-held vendor credential or address is the strongest evidence in this tree that a deployment can reach a vendor at all. Derived by SHAPE, so a new key is noticed the day it lands. |
| A vendor adapter module | `apps/api/engine/*.py`, `apps/api/retrieval/*.py` | The two directories hard rule 2 permits vendor payload shapes in on this side. |

Tokens map to published identities through one hand-maintained dict (`VENDOR_OF`), because
the two are not the same string: `azure_openai_api_key` is **Microsoft**, and `gemini_api_key`
and `google_oauth_client_secret` are both **Google**. Both directions are checked, on
`check_erasure_coverage`'s terms — a token with no identity fails, an identity with no
token fails, and each exemption carries a reason of at least 40 characters.

## The two findings

### 1. Supermemory — VERIFIED-IN-REPO, and the reason the guard exists

`apps/api/retrieval/supermemory.py` (read) and `supermemory_index.py` (write) are complete
adapters. `apps/api/core/platform_config.py` marks `retrieval_provider`,
`supermemory_base_url`, `supermemory_api_key` and `supermemory_embedding_model` all `LIVE`
— and `retrieval/service.get_retriever` runs per request holding no state, which the config
file states outright is what makes the setting an off switch. So an operator selects it in
the ops console and the **next question** is served from it. At that point it holds every
published `kb_chunks` passage: SECURITY-COMPLIANCE §4 describes that content as "FAQs,
price lists, staff names and contact numbers".

It appeared on no legal page. `legal.test.tsx` could not have caught it: both of its vendor
loops read `SUBPROCESSOR_NAMES`, which is derived from the register, so a vendor absent
from the register and absent from the DPA is *consistent*.

The row now published says four things, each of which is checkable in this tree and none of
which is a claim about the vendor:

* it is off — `retrieval_provider` defaults to `compiled-facts` (`config.py:855`);
* turning it on is an operator setting with no release, which is why the Status cell says
  so rather than leaving a reader to assume a deploy stands between them and it;
* the intended deployment is **self-hosted on our own VPS** (`docs/PIPECAT-MIGRATION.md`
  §8, as recorded in `supermemory.py`'s docstring), so in the intended mode nothing reaches
  the company at all — but the address is a setting, and a register must describe the
  capability;
* the purge on account closure rests on an **ASSUMED** reading of the vendor's delete
  surface. `supermemory_index.py`'s own docstring: *"The tag rests on an ASSUMED reading of
  their delete surface; the ledger rests on what we recorded sending."* `deletion_proof` is
  `False` for this provider. The client-facing Status cell says this in plain words
  instead of implying a verified deletion.

⚠ **EVIDENCE CLASS: UNKNOWN for the vendor.** `supermemory.ai` is egress-blocked from this
container (measured 14 Sep 2026, recorded in `supermemory.py`). Nobody here has read its
terms, its retention position or its delete route, and nothing in the row claims otherwise.

### 2. Gnani — found by the same scan, and it is a THIRD voice-synthesis vendor

`gnani_api_key` is a `Settings` field; `agents/voices.TtsModel` is
`Literal["bulbul:v3", "sonic-3.5", "timbre-v2.5"]`, three members not two; `timbre-v2.5` is
Gnani's, `apps/api/agents/gnani_voices.py` is the catalogue and
`apps/voice-worker/voice_worker/gnani_tts.py` is the leg. A Gnani agent sends the words the
agent is about to speak, a turn at a time, to `wss://api.vachana.ai/api/v1/tts` — exactly
the Cartesia row's data category, to a vendor with no row at all.

⚠ **NOTE FOR THE NEXT READER: `CLAUDE.md` still describes `TtsModel` as a two-member
Literal.** That is stale as of D-618. It is flagged here rather than silently
worked around (hard rule 11, and the docs set wins), and correcting it is OUTSTANDING.

Two things hold Gnani off today and both are in the published Status cell: no credential is
installed, and **no price exists anywhere** — `ops/model_pricing.TTS_PROVIDERS` includes
`gnani` precisely so a price CAN be attested, `VOICE_TIER_OF_PROVIDER["gnani"] is None`,
and `ops/voice_curation_routes._form` therefore renders the provider `selectable=False`
with a reason. Hard rule 7 is what keeps it unofferable, which is a stronger gate than a
feature flag.

⚠ **EVIDENCE CLASS.** VERIFIED-IN-REPO for everything about our behaviour. The vendor's own
hosts (`gnani.ai`, `docs.gnani.ai`, `api.vachana.ai`) are EGRESS-BLOCKED from this
container — all three measured HTTP 000 on 15 Sep 2026, recorded in `gnani_tts.py`. The
protocol facts in that module are VENDOR-PUBLISHED (founder's reading, 15 Sep 2026) and
VERIFIED-VENDOR-SDK (`pipecat-gnani` 0.5.12, hash-pinned). **No residency, retention or
deletion position has been read for this vendor**, and the register's Location cell says
NOT VERIFIED rather than inferring a country from the company's nationality — the exact
mistake §3.4 of that page records having made once about Sarvam.

### A third row, added for completeness rather than as a finding

`otel_exporter_otlp_endpoint` is a credential-shaped reach with no company behind it: an
OTLP collector is whatever an operator points it at. It is unset (no collector, no tracing,
the SDK is not even imported), and it now has an unnamed register row of the same shape as
the hosting-provider row. ⚠ The guard cannot check an UNNAMED row by name — a `None` in
`VENDOR_OF` is an assertion this scan makes about itself, held by a reader.

## What this guard does NOT establish

* **It does not check what a row SAYS.** Location, retention and status cells are prose a
  human writes; this only checks that a vendor with code has a row and a row has code.
* **It does not see a client-supplied credential.** AiSensy and Interakt are reached with
  the client's own credential, so no platform `Settings` field names them; they are
  `REGISTER_ONLY` entries with that reason written out.
* **It is not yet wired into CI.** It belongs in the guardrails job of
  `.github/workflows/ci.yml` beside `check_rls_coverage` and `check_erasure_coverage`; it
  needs no database. The wiring is OUTSTANDING and this line is the record of it.
