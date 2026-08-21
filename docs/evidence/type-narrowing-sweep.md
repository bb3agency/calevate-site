# Type-narrowing sweep — unannotated containers feeding `Literal` consumers

**Date:** 21 Aug 2026 · **Scope:** `apps/`, `packages/`, `scripts/` · **Checker:** mypy 2.3.0 `--strict`

## The defect class

An unannotated container literal infers the WIDE element type. `_SPEAKER_MAP = {...}`
in `apps/api/engine/bolna.py` inferred `dict[str, str]`; its values then satisfied
`TranscriptTurn.speaker: Literal["agent", "caller"]` by inference luck rather than by a
check. Adding one wrong value — `"operator": "supervisor"`, or a typo `"agnet"` — was
caught by nothing until Pydantic raised `ValidationError` at RUNTIME inside the post-call
pipeline, on a real customer's call.

**The fix is always at the DEFINITION** (`Final[dict[str, Speaker]]`), never a `cast()`
and never a widened `Literal`. A cast silences the checker while leaving the container
unguarded, which is the opposite of the point.

## THE ROOT CAUSE OF THE BLIND SPOT — measured, not inferred

`mypy --strict` passed the original `_SPEAKER_MAP` both before and after the fix. This
sweep found why, and it is one line of configuration.

`pyproject.toml` enables `plugins = ["pydantic.mypy"]` but carries **no
`[tool.pydantic-mypy]` section**, so `init_typed` takes its default of `false`. With
`init_typed = false` the plugin synthesises every model's `__init__` with field types of
`Any`. **Every Pydantic constructor call in this repository is therefore unchecked on
argument TYPES.** Only argument PRESENCE is checked.

Measured directly (probe file, since deleted):

```python
TranscriptTurn(call_id="c", idx=0, speaker="supervisor", text="x", at_ms=0)
#                                          ^^^^^^^^^^^^ not a member of Speaker at all
```
→ `uv run mypy` : **`Success: no issues found in 1 source file`**

Add `[tool.pydantic-mypy] init_typed = true` and the same expression errors. This is the
class's true root cause: the *producer* was unannotated AND the *consumer* was unchecked,
so nothing on the path could see the mistake.

### What `init_typed = true` costs, measured across the tree

| run | errors |
|---|---|
| before this sweep | **15** in 6 files |
| after this sweep | **9** in 3 files |

Every one of the six it eliminated was a real instance of this defect class. The nine
that remain are listed under **Blocked / report-only** below; six are in
`apps/api/agents/service.py` and one is a `dict`-invariance nit in the conformance
suite. **Turning the flag on is the single highest-value change available here** and it
is one line, but it would turn CI red until those two files land, and both are being
edited by other lanes right now — so it is reported rather than applied.

## Pyrefly

**Not installed in this environment** (`uv run pyrefly` → `Failed to spawn: pyrefly`; no
`pyrefly`/`pyright` binary in `.venv/bin`; no mention in `pyproject.toml` or `uv.lock`).
Per instruction it was NOT installed. The second source used instead was
`init_typed = true`, which reproduces exactly what Pyrefly saw on `_SPEAKER_MAP`: a wide
value reaching a narrow Pydantic field.

## Method

1. AST scan of all 298 Python files for every `Literal[...]` alias and `str`-valued
   `Enum` — **79 closed vocabularies** found.
2. AST scan for every container literal (annotated or not, module/class/function level,
   including position-wise slots of tuple-of-tuples) whose string contents are a subset
   of one of those 79 vocabularies.
3. AST scan for `.get(k, "<bare literal default>")` and for ternaries of two string
   literals.
4. `init_typed = true` run to enumerate every wide value reaching a Pydantic field.
5. Per-annotation sabotage: insert a value outside the `Literal`, run `uv run mypy`,
   confirm it errors, restore from a `cp` backup, confirm clean.

### A methodology trap worth recording

mypy's incremental cache keys on mtime **and size**. A sabotage that preserves length —
`"client"` → `"cleint"`, `"emergency"` → `"emergancy"` — and is then restored can leave
mypy reporting the SABOTAGED content from cache against a correct file on disk. It
happened twice here and reads exactly like a real failure. `touch` the file (or clear
`.mypy_cache`) after any same-length restore before believing the result.

---

## The table

`redden?` = did `uv run mypy` error when a value outside the `Literal` was placed in the
annotated container, under the repo's CURRENT config.

### Fixed

| file:line | container | was | now | fixed | reddened on sabotage |
|---|---|---|---|---|---|
| `apps/api/engine/fake.py:121` | `SAMPLE_TURNS` | `tuple[tuple[str, str], ...]` | `tuple[tuple[Speaker, str], ...]` | yes | **YES** |
| `apps/api/engine/fake.py:119` | `_STATUS_MAP` (replaces `known: set[str]` + `# type: ignore[assignment]`) | `set[str]`, hand-typed | `Final[dict[str, CallStatus]]`, **derived from `get_args(CallStatus)`** | yes | n/a — derived, cannot drift (see note) |
| `apps/api/engine/fake.py:319` | `self._calls` | `dict[str, dict[str, Any]]` | `dict[str, _StoredCall]` (TypedDict) | yes | **YES** (2 errors: `direction`, `status`) |
| `apps/api/engine/fake.py:779` | `direction=call.get("direction", "inbound")` | dead + unchecked default | `direction=call["direction"]` | yes | **NO under current config**; YES under `init_typed` |
| `apps/api/engine/cartesia.py:446` | `speaker` local (ternary of 2 literals) | inferred `str` | `speaker: Speaker` | yes | **YES** |
| `apps/api/quality/models.py:27` | `QA_VERDICTS` | unannotated → `tuple[str, ...]` | `tuple[Verdict, ...]` | yes | **YES** |
| `apps/api/quality/sampling.py:209` | `SampledCall.verdict` | `str \| None` | `Verdict \| None` | yes | **NO under current config**; YES under `init_typed` |
| `apps/api/crm/models.py:43` | `CALL_DIRECTIONS` | unannotated | `tuple[CallDirection, ...]` | yes | **YES** |
| `apps/api/crm/models.py:44` | `CALL_STATUSES` | unannotated | `tuple[CallStatus, ...]` | yes | **YES** |
| `apps/api/crm/models.py:55` | `OUTCOME_TAGS` | unannotated | `tuple[OutcomeTag, ...]` | yes | **YES** |
| `apps/api/crm/models.py:56` | `SENTIMENTS` | unannotated | `tuple[Sentiment, ...]` | yes | **YES** |
| `apps/api/crm/models.py:57` | `SPEAKERS` | unannotated | `tuple[Speaker, ...]` | yes | **YES** |
| `apps/api/crm/models.py:59` | `LEAD_STATUSES` | unannotated | `tuple[LeadStatus, ...]` | yes | **YES** |
| `apps/api/crm/performance.py:41` | `DIAL_ONLY_STATUSES` | unannotated | `tuple[CallStatus, ...]` | yes | **YES** |
| `apps/api/crm/performance.py:46` | `QUALIFIED_STATUSES` | unannotated | `tuple[LeadStatus, ...]` | yes | **YES** |
| `apps/api/crm/service.py:2182` | `CALLBACK_OUTCOMES` | unannotated | `tuple[OutcomeTag, ...]` | yes | **YES** |
| `apps/api/crm/service.py:2183` | `CALLBACK_STATUSES` | unannotated | `tuple[CallStatus, ...]` | yes | **YES** |
| `apps/api/authn/models.py:57` | `AUTHN_REALMS` | unannotated | `tuple[Realm, ...]` | yes | **YES** |
| `apps/api/reliability/models.py:29` | `LOAD_SHED_MODES` | unannotated | `tuple[LoadShedMode, ...]` | yes | **YES** |

**16 of 19 reddened under the repo's current configuration.** The three that did not are
each recorded honestly rather than counted as clean fixes:

* `fake.py` `_STATUS_MAP` — DERIVED from `get_args(CallStatus)`, so there is nothing to
  sabotage: a wrong member cannot be written. That is a stronger guarantee than an
  annotation that merely detects one, and it follows the established repo pattern
  (`config.SELECTABLE_ENGINES`, `rbac.KNOWN_PERMISSIONS`, `engine.AZURE_OPENAI_MODELS`).
  Verified runtime-identical: `get_args(CallStatus)` == the eight strings it replaced.
* `fake.py:779` and `sampling.py:209` — the guard is real but its consumer is a Pydantic
  constructor, so it can only be seen with `init_typed = true`. Both were sabotaged under
  both configurations and the results are printed below.

### Judged FINE — deliberately wide, with the reason

| file:line | container | verdict |
|---|---|---|
| `apps/api/integrations/service.py:105` | `EVENT_TYPES: tuple[str, ...]` | **FINE.** `integrations/routes.py:88-94` argues it explicitly: `EventName` is what THIS BUILD accepts, `EVENT_TYPES` is what the RUNNING deployment offers, and an older console must be able to SEE a name outside its own union in order to say so. Narrowing makes that gap unrepresentable and turns adding an event into a 500 out of response validation. |
| `apps/api/crm/service.py:62` | `LEAD_STATUSES: tuple[str, ...] = get_args(LeadStatus)` | **FINE.** Derived, so it cannot drift. Wide on purpose: its two uses are `dict.fromkeys` keys compared against arbitrary DB strings and a SQL `IN` list. Narrowing forces `dict[LeadStatus, int]`, which the line below (`counts[str(name)] = ...`) cannot satisfy without a cast. |
| `apps/api/authn/sessions.py:142` | `REALM_TIMEOUTS: Final[dict[str, RealmTimeouts]]` | **FINE.** Callers index it with `Realm`, which has THREE members (`client`, `admin`, `system`) against this dict's two. `_refuse_unknown_realm` is the runtime guard. A narrower key type would make the legitimate lookup a type error. |
| `apps/api/core/errors.py:264` | `by_status: dict[int, ErrorKind]` | **FINE** — already narrow. |
| `apps/api/core/loadshed.py:238` | `modes: tuple[LoadShedMode, ...]` | **FINE** — already narrow. |
| `apps/api/engine/cartesia.py:226` | `_STATUS_MAP: Final[dict[str, CallStatus]]` | **FINE** — already narrow; this is the pattern the other two adapters now match. |
| `apps/api/engine/bolna.py:290` | `_STATUS_MAP: dict[str, CallStatus]` | **FINE** — already narrow (not `Final`, cosmetic only). |
| `apps/api/engine/bolna.py:359` | `_AZURE_PROVIDER_KEYS: Final[dict[str, str]]` | **FINE.** Vendor field names → vendor placeholder prose. Neither side is a Literal in this repo. |
| `apps/api/engine/bolna.py:727` | `_MINOR_UNITS_PER_MAJOR: dict[str, Decimal]` | **FINE.** ISO currency code → `Decimal`. Money is `Decimal` (hard rule 7 ✓); no currency Literal exists. |
| `apps/api/engine/bolna.py:269` | `_VENDOR_STATUSES: frozenset[str]` | **FINE.** The VENDOR's vocabulary, correctly `str` — narrowing it to `CallStatus` would be the hard-rule-2 error of asserting their enum is ours. |
| `apps/api/crm/models.py` | `CONSENT_STATES`, `LEAD_SOURCES`, `LEAD_EVENT_TYPES` | **FINE.** No `Literal` counterpart exists anywhere; `crm/schemas.py:547` argues deliberately that `LeadEvent.type` stays `str`. |
| `scripts/pilot/results.py:55` | `STATUS_LABEL: dict[GateStatus, str]` | **FINE.** Key already narrow; values are display labels, not domain values. |
| `scripts/correct_tts_tier.py:77` | `TIER_CHOICES: tuple[TtsTier, ...]` | **FINE** — already narrow. |
| `scripts/check_docs_drift.py:961` | `TTS_DOC_ROW_TO_TIER: dict[str, str]` | **FINE by cost.** Narrowing to `dict[str, VoiceTier]` needs `apps.api.agents.voices` imported into a doc-linting script that currently imports NOTHING from `apps/`. The dependency costs more than the guard buys. |
| `scripts/eval.py:162` | `VERTICALS` | **FINE by cost.** It names which verticals the eval suite COVERS, not the closed set. Narrowing needs a FastAPI routes module (`apps.api.admin.routes`) imported into a CLI script. |
| `apps/api/agents/experiments.py:198-200` | `rate/rate_low/rate_high: float` | **FINE — not money.** A conversion PROPORTION over completed calls (`conversions / completed`). Hard rule 7 does not reach it. |

### Blocked / report-only — files owned by other lanes

| file:line | container | required | proposed fix |
|---|---|---|---|
| `apps/api/agents/models.py:44` | `NUMBER_SERIES` unannotated → `tuple[str, ...]` | `tuple[NumberSeries, ...]` | `from calevate_shared.engine import NumberSeries` (that module is already imported for `SELECTABLE_ENGINES`' sibling) then `NUMBER_SERIES: tuple[NumberSeries, ...] = ("140", "160", "standard")`. The tuple is interpolated into a `CheckConstraint`, so a typo here is a CHECK the API's Literal does not name. |
| `apps/workers/campaign_dispatch.py:173` | `ACTIVE_STATUSES` unannotated → `tuple[str, ...]` | `tuple[CallStatus, ...]` | `from calevate_shared.events import CallStatus` then `ACTIVE_STATUSES: tuple[CallStatus, ...] = ("queued", "ringing", "in_progress")`. It gates concurrency accounting; a misspelt member silently under-counts live lines. |
| `apps/api/agents/service.py:456` | `_to_config(agent: dict[str, object])` | a `TypedDict` for the agent row | `object` is the same hole `dict[str, Any]` was in `fake.py`. It produces SIX of the nine remaining `init_typed` errors: `direction` (`str` → `Literal["inbound","outbound","both"]`), `stt_provider`, `stt_model`, `tts_provider`, `tts_voice` (`object` → `str \| None`) and the `**in_call_llm(...)` unpack (`dict[str, object]` → `str \| None` / `Literal["azure_openai"] \| None`). The fix is the `_StoredCall` move applied to the agent row. |
| `packages/shared/tests/engine_conformance/contract_test.py:134` | `**dict[str, str]` into `CallContext` | `Mapping` | `dict` is invariant; the unpacked mapping should be built as the field's own type or the call written without `**`. Visible only under `init_typed`. |
| `apps/api/engine/bolna.py` | — | — | **No second instance of this class found.** All seven module-level containers were inspected (table above); `_SPEAKER_MAP` was already fixed by the caller of this sweep. |

### Duplicate vocabularies found (not this defect class, but the same failure mode)

Not fixed here because each needs the `Literal` MOVED beside the tuple (the move made in
`quality/`), and the modules that own the `Literal` import the models module — annotating
in place would be an import cycle.

* `("self_serve", "trial")` is hand-written **four** times —
  `billing/ai_quota.py:358`, `billing/payment_routes.py:118`, `billing/rates.py:389`,
  `compliance/service.py:248` — plus `SelfServeTier` in `tenancy/signup.py:77`. Two of the
  four carry a comment claiming the value is "named ONCE".
* `compliance/models.py:37/94/101` (`CONSENT_SOURCES`, `CONSENT_STATUSES`,
  `ALERT_OPTIN_STATUSES`) mirror Literals declared in `compliance/consent_routes.py` and
  `compliance/whatsapp_optin_routes.py`.
* `billing/models.py:37 CREDIT_REASONS` mirrors `CreditReason` in `billing/service.py:70`.

## Money-path floats (hard rule 7)

**None found.** Swept for `float` annotations, `Float()`/`REAL`/`DOUBLE` columns and
`Decimal(<float>)` construction across `apps/`, `packages/`, `scripts/`:

* No `Mapped[float]`, no `Float()`/`REAL`/`DOUBLE` column anywhere.
* No money-shaped field or variable annotated `float`.
* The only `float`s on a name that pattern-matched are
  `agents/experiments.py:198-200` — conversion proportions, not currency.
* `billing/payments.py:436 Decimal(amount) / PAISE_PER_RUPEE` takes an `int` (guarded
  three lines above by an explicit "not an integer number of paise" refusal) and divides
  by `Decimal(100)`. Exact.
* `billing/credit_routes.py:236 refuse_json_float` actively REFUSES a JSON float at the
  boundary, wired into two validators. The rule is enforced, not merely observed.

## What neither checker can catch, even after this sweep

1. **A Pydantic constructor argument, under the repo's current config.** Demonstrated
   twice above. `init_typed = true` closes it.
2. **A MISSING member.** `tuple[CallStatus, ...]` rejects a wrong member; a SHORTER tuple
   is still a valid `tuple[CallStatus, ...]`. Completeness has to be pinned behaviourally
   — `tests/dashboard_daily_test.py:109` walks `CALL_STATUSES` against the classifier and
   is the model for it.
3. **`.get(required_key, default)` on a TypedDict.** mypy resolves the return to the value
   type and **never type-checks the default at all**, because a required key can never
   fall through. So `call.get("direction", "inboud")` is simultaneously unreachable and
   unchecked — the worst of both. Found and removed at `fake.py:779`; the honest form is
   the subscript.
4. **Values arriving from raw SQL.** `_row(r: Any)` in `quality/sampling.py` means the
   narrow type on `SampledCall.verdict` states an invariant the DB CHECK enforces rather
   than one the function verifies. That is the correct division of labour, but it is worth
   naming: the type is a claim about the schema, not a proof from the code.

---

## Appendix — sabotage transcript

Every annotation below was sabotaged with a value outside its `Literal`, checked, then
restored from a `cp` backup and re-checked. Only representative errors are pasted; the
pattern is identical for the rest of the table. **Line numbers in this transcript are as
of the run that produced each error** — later edits in the same file shifted some of them,
so the table above is the authoritative index.

### Control — the class, before and after (`fake.py` `SAMPLE_TURNS`)

With the OLD wide annotation `tuple[tuple[str, str], ...]` and `("supervisor", ...)` in
the tuple:

```
Success: no issues found in 1 source file
```

With the annotation this sweep added, same bad value:

```
apps/api/engine/fake.py:73: error: Incompatible types in assignment (expression has type
"tuple[tuple[Literal['agent'], str], tuple[Literal['supervisor'], str], ...]",
variable has type "tuple[tuple[Literal['agent', 'caller'], str], ...]")  [assignment]
Found 1 error in 1 file (checked 1 source file)
```

Restored → `Success: no issues found in 1 source file`.

### `_StoredCall` TypedDict (`fake.py`)

`"direction": "outbund"` and `"status": "compleeted"` in `start_outbound_call`:

```
apps/api/engine/fake.py:505: error: Incompatible types (expression has type Literal['outbund'],
  TypedDict item "direction" has type "Literal['inbound', 'outbound']")  [typeddict-item]
apps/api/engine/fake.py:506: error: Incompatible types (expression has type Literal['compleeted'],
  TypedDict item "status" has type "Literal['queued', 'ringing', 'in_progress', 'completed',
  'failed', 'no_answer', 'busy', 'voicemail']")  [typeddict-item]
```

Restored → clean.

### `cartesia.py` speaker

`speaker: Speaker = "agent" if role in _AGENT_ROLES else "callerr"`:

```
apps/api/engine/cartesia.py:446: error: Incompatible types in assignment (expression has type
"Literal['agent', 'callerr']", variable has type "Literal['agent', 'caller']")  [assignment]
```

Restored → clean.

### `crm/models.py` — all six at once

One wrong member injected into each tuple:

```
apps/api/crm/models.py:44: ... Literal['internal']]      (CALL_DIRECTIONS)
apps/api/crm/models.py:45: ... Literal['no_ansewr']      (CALL_STATUSES)
apps/api/crm/models.py:56: ... Literal['needs_folow_up'] (OUTCOME_TAGS)
apps/api/crm/models.py:57: ... Literal['mixed']          (SENTIMENTS)
apps/api/crm/models.py:58: ... Literal['supervisor']     (SPEAKERS)
apps/api/crm/models.py:60: ... Literal['intrested']      (LEAD_STATUSES)
Found 6 errors in 1 file (checked 1 source file)
```

Restored → `Success: no issues found in 1 source file`.

### `crm/performance.py` + `crm/service.py`

```
apps/api/crm/performance.py:42: error: Incompatible types in assignment (... Literal['no_ansewr'] ...)
apps/api/crm/performance.py:47: error: Incompatible types in assignment (... Literal['wonn'] ...)
apps/api/crm/service.py:2182: error: Incompatible types in assignment (... Literal['droped'] ...)
apps/api/crm/service.py:2183: error: Incompatible types in assignment (... Literal['voicemale'] ...)
```

Restored → clean.

### `authn/models.py` + `reliability/models.py`

```
apps/api/authn/models.py:57: error: Incompatible types in assignment (expression has type
"tuple[Literal['admin'], Literal['cleint']]", variable has type
"tuple[Literal['client', 'admin', 'system'], ...]")  [assignment]
apps/api/reliability/models.py:29: error: Incompatible types in assignment (expression has type
"... Literal['emergancy'] ...", variable has type
"tuple[Literal['normal', 'reduced', 'emergency', 'maintenance'], ...]")  [assignment]
```

Restored → clean. (**This pair is where the mtime+size cache trap fired**: `cleint`/`client`
and `emergancy`/`emergency` are the same length, so mypy re-reported the sabotage against a
correct file until the files were `touch`ed.)

### `quality/models.py` — `QA_VERDICTS`

`("clean", "concern", "defect", "unclear")`:

```
apps/api/quality/models.py:27: error: Incompatible types in assignment (expression has type
"tuple[Literal['clean'], Literal['concern'], Literal['defect'], Literal['unclear']]",
variable has type "tuple[Literal['clean', 'concern', 'defect'], ...]")  [assignment]
```

Restored → clean.

### The two that need `init_typed = true` — both configurations measured

`QaSampleOut(verdict="unclear")` in `quality/sampling_routes.py`:

| config | result |
|---|---|
| repo's current `pyproject.toml` | `Success: no issues found in 1 source file` |
| `+ [tool.pydantic-mypy] init_typed = true` | `sampling_routes.py:181: error: Argument "verdict" to "QaSampleOut" has incompatible type "Literal['unclear']"; expected "Literal['clean', 'concern', 'defect'] \| None"  [arg-type]` |

`direction=call["status"]` (a `CallStatus` where a `CallDirection` belongs) in `fake.py`:

| config | result |
|---|---|
| repo's current `pyproject.toml` | `Success: no issues found in 1 source file` |
| `+ init_typed = true` | `fake.py:778: error: Argument "direction" to "ExecutionSnapshot" has incompatible type "Literal['queued', ...]"; expected "Literal['inbound', 'outbound']"  [arg-type]` |

That pair is the whole argument for the config change, stated twice with numbers.

## Gates run

```
uv run mypy apps packages          → Success: no issues found in 238 source files
uv run ruff check .                → All checks passed!
uv run lint-imports                → Contracts: 2 kept, 0 broken.
pytest (touched surfaces only)     → 404 passed
```

Tests run (scoped — five agents share 4 vCPU, so the full suite and the coverage ratchet
were deliberately NOT run): `packages/shared/tests/engine_conformance`,
`engine_audit_test`, `engine_capability_test`, `engine_event_ordering_test`,
`qa_sampling_test`, `dashboard_daily_test`, `performance_test`, `callback_test`,
`authn_session_test`, `loadshed_exemption_test`, `pipeline_audit_test`,
`poller_guarantee_test`.

No change in this sweep alters runtime behaviour. The three that touched executable
expressions are each provably identical on today's inputs:
`get_args(CallStatus)` equals the eight strings the hand-written `set[str]` held (asserted
at the console); `TERMINAL_STATUSES` equals the five-member tuple it replaced;
`call["direction"]` equals `call.get("direction", "inbound")` for a key both writers
always set. `ruff format` reported the files unchanged.
