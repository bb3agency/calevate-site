"""Extraction runners: the model calls, the offline one that keeps us honest, and the
ONE place that decides what happens when a provider cannot serve.

Post-call only, never in-call (TRD §7). Three implementations behind two selectors, and
the split between the selectors is the whole of D-127's G-2/G-7:

- **`SarvamExtractor`** — Sarvam 105B, free per token and sovereign. It is what
  `get_extractor()` returns, and after D-127 it is the ONLY thing `get_extractor()` can
  return besides the offline baseline.
- **`AzureOpenAIExtractor`** — Azure OpenAI in `AZURE_LOCATION` (D-127 G-1's leg, moved
  to Azure by D-410; the region is `eastus2` since D-449 withdrew the India residency
  claim, and no comment here should imply otherwise). It serves the USER-TRIGGERED work
  — re-summarise, reshape, ask-about — over the REDACTED copy of a call, and it is
  reached only through `run_assist()`.
- **`OfflineExtractor`** — deterministic, no network. Used when no provider key is
  configured, which makes `ENGINE=fake` + no keys a fully working local pipeline, and
  gives the regression harness a stable baseline to diff model output against.

All three return the same `ExtractionOutput`, validated against the schema, so a
provider swap is a config change (D-04's rationale) and not a code change.

--------------------------------------------------------------------------------------
WHY THE ASSIST PROVIDER IS NOT REACHABLE FROM `get_extractor()` (D-127 G-2 + G-7)
--------------------------------------------------------------------------------------
It used to be: Sarvam if a Sarvam key was configured, the other provider if only that
provider's key was. That ladder was written before there was a rule about WHOSE DATA
each provider sees, and it does not survive the rule. D-410 changed WHICH company holds
the second key and changed nothing about this argument, because the argument is about
the existence of a second processor and not about its name.

`workers/pipeline.py` computes `redacted = redact(turn.text)` and then appends
`turn.text` — the RAW turn, one line later, deliberately — to the string it hands
`extract_call`, because a CRM "callback number" field needs the actual digits and an
extractor reading `[REDACTED]` returns nothing worth storing. So the first post-call
extraction is THE raw-PII pass, and G-2 says the ASSIST leg never sees raw PII. A
config-reachable branch in which it does is not a fallback, it is a residency inversion
one absent environment variable away — the exact shape `check_model_residency` exists to
make impossible in URLs, applied to the selector instead.

**`GEMINI_EXTRACTION_DEFAULT is False`**, permanently, and the constant below is the
greppable form of that sentence so `check_docs_drift` §5 can catch the next document
that says otherwise. G-7 is not a compromise reached on cost or quality: it is the only
split under which both halves of D-127 are true at once.

**D-400 MOVED THE IN-CALL LLM LEG AND DID NOT MOVE THIS ONE; D-410 MOVED BOTH OF THOSE
TO AZURE OPENAI AND STILL DID NOT MOVE THIS ONE**, and the reason is the paragraph above
rather than an omission. Each founder decision has read as covering every model call this
product makes — "so LLM thing is solved" — and the same line of `pipeline.py` has
answered it the same way three times: this pass is the only one in the system that reads
`turn.text`. Both other surfaces see redacted or tenant-authored text. Moving this one is
a decision about WHOSE DATA a second processor sees, not about which model is better or
cheaper, so it stays raised rather than taken. `GEMINI_EXTRACTION_DEFAULT` remains False.

**THE CONSTANT KEEPS ITS NAME THROUGH D-410 ON PURPOSE.** Gemini is gone from this
product, so the name now reads as a fossil — but `check_docs_drift` §5 machine-checks
prose against this identifier BY NAME across the doc set, and renaming it would silently
unbind every one of those sentences in the same commit that changed what they are about.
The sentence it stands for has never been "no Gemini here"; it is "the first post-call
extraction does not run on the assist provider, whoever that is".

--------------------------------------------------------------------------------------
AVAILABILITY IS DECIDED ONCE (D-127 G-6, PLAN Part 15)
--------------------------------------------------------------------------------------
`assist_capability()` is the only place that answers "what happens when the assist
provider is unconfigured, over quota, or down", and it gives one of two answers: fall back to Sarvam
and SAY SO, or refuse with a message and a remediation. A silent fallback quietly
changes output quality with nobody told, which is the one outcome G-6 rules out — so the
disclosure travels on the capability object rather than being left to each surface to
remember. The shape is `billing/payments.PaymentCapability`'s, deliberately: one lookup,
one object, authored reason codes that name OUR configuration state and never a vendor's
error string.

**Scoring the model path.** The regression harness already runs against whatever
`get_extractor()` returns and keys its baseline by `model_name`, so scoring Sarvam
against the golden transcripts needs no flag and no new mode — it is

    SARVAM_API_KEY=... uv run python -m scripts.eval --client=<slug> --update-baseline

on a machine that holds a key, and the per-model baseline is the reviewable diff. A
credentialed mode was deliberately NOT added to CI: CI has no key, and giving it one
would ship committed transcripts to a provider on every push for a non-deterministic,
rate-limited, chargeable result that could not gate a merge anyway. What CI can gate
without credentials is the two ARTEFACTS this path is made of — the prompt's rules and
the validator's rejections — and that is `tests/extraction_prompt_test.py`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final, Protocol

import httpx
from calevate_shared.engine import (
    AZURE_LOCATION,
    AZURE_OPENAI_DEFAULT_MODEL,
    SARVAM_DEFAULT_LLM,
    azure_openai_base_url,
)
from calevate_shared.extraction import (
    ExtractionField,
    ExtractionOutput,
    ExtractionSchemaSpec,
    build_extraction_prompt,
    validate_extraction,
)

from apps.api.core.alerting import record_extraction_failure
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.workers.redaction import redact

log = get_logger(__name__)

#: The endpoint that receives the RAW, un-redacted transcript.
#:
#: `Final` FOR THE REASON `check_model_residency._is_builder_suffix` MAKES `frozen` A
#: LOAD-BEARING CONDITION OF ITS OWN EXEMPTION: "a rebindable module global is a knob".
#: The Azure endpoint is defended by a single builder, a single-literal rule and four AST
#: checks; this one had none of that, and it is the leg with the WORSE blast radius —
#: `GEMINI_EXTRACTION_DEFAULT is False` means the first post-call pass reads `turn.text`,
#: so a re-pointed host here exfiltrates caller PII rather than redacted prose.
#:
#: `Final` does not stop `module.SARVAM_CHAT_URL = ...` at runtime (nothing in Python
#: does) — it makes the rebind a mypy error in CI and a thing a reviewer sees. That is
#: the same strength the Azure suffix has, and this constant had strictly less.
SARVAM_CHAT_URL: Final = "https://api.sarvam.ai/v1/chat/completions"

#: The per-leg provider budget for the POST-CALL pipeline, where nobody is waiting.
#:
#: 30s is right there: an ARQ job holds no HTTP connection and no pooled Postgres
#: connection across the call, so the only cost of waiting is the job's own wall clock.
#: `pipeline.py` names this number in its retry arithmetic.
EXTRACTION_TIMEOUT_S: Final = 30.0

#: The per-leg provider budget for the USER-TRIGGERED assist, where somebody is.
#:
#: WHY A SECOND NUMBER AT ALL. `run_assist` runs two legs IN SERIES — Azure, then the
#: disclosed Sarvam fallback — so its worst case is TWICE the per-leg budget, plus the
#: route's own work (idempotency claim, quota gate, transcript load, `meter_assist`,
#: `write_audit`). At 30s a leg that is ~60s of provider wait behind `location /` on the
#: `api.` vhost, whose `proxy_read_timeout` is 60s: the edge gives up first and the client
#: gets a 504 INSTEAD OF THE FALLBACK'S ANSWER — the single outcome the fallback exists to
#: prevent. It also holds one pooled Postgres connection for the whole duration, because
#: `Depends(db)`'s transaction is open across it (see `crm/assist.py`).
#:
#: WHY THE FIX IS HERE AND NOT IN NGINX. Raising `proxy_read_timeout` was available and is
#: rejected: that directive sits on `location /`, a catch-all over every API route, so
#: buying headroom for one path lengthens how long EVERY slow upstream holds an edge
#: connection on the box that also runs Postgres. A client-side budget costs one route.
#:
#: WHY PER-LEG AND NOT ONE `asyncio.timeout` AROUND BOTH. A single whole-request deadline
#: is the tidier shape and is wrong here: firing mid-Azure it would abandon the request
#: outright and skip the fallback, handing the user a refusal on the one path that still
#: had a second model available. Two bounded legs are slower in the worst case and are the
#: only arrangement under which the fallback can actually answer.
#:
#: THE NUMBER IS PINNED TO NGINX BY A TEST, NOT BY THIS COMMENT.
#: `tests/assist_deadline_test.py` reads `proxy_read_timeout` out of
#: `infra/nginx/snippets/calevate-proxy.conf` and asserts
#: `2 * ASSIST_TIMEOUT_S + ASSIST_ROUTE_RESERVE_S < proxy` — two numbers in two languages
#: in two files, which a comment cannot keep honest.
ASSIST_TIMEOUT_S: Final = 15.0

#: What the route spends OUTSIDE the two provider legs, reserved rather than measured.
#:
#: Not a timeout anybody enforces — it is the headroom the arithmetic above subtracts for
#: the idempotency claim, the quota read, the transcript query, `meter_assist` and the
#: audit write, all of which are local Postgres round trips. Deliberately generous: the
#: cost of over-reserving is a slightly tighter provider budget, and the cost of
#: under-reserving is the 504 this whole seam exists to remove.
ASSIST_ROUTE_RESERVE_S: Final = 10.0

#: Does the FIRST post-call extraction run on the ASSIST provider — Gemini when this was
#: minted, Azure OpenAI since D-410? No, and D-127 G-7 says never.
#:
#: A greppable boolean rather than a paragraph, which is this repo's honesty device
#: (`PROVIDER_CREATES_ORDERS`, `ENGINE_REPORTS_TTS_MODEL`, `PROVISIONING_IMPLEMENTED`).
#: It exists because twenty-four `file:line` locations across the doc set stated Gemini's
#: role in prose that bound nothing, so `check_docs_drift` §5 could not see them drift —
#: and they had all drifted. Prose that quotes this name by value is now machine-checked
#: against the tree.
#:
#: Flipping it to True would require raw caller PII to reach a second processor, so it is
#: not a knob: it is a fact about which pass reads `turn.text`.
GEMINI_EXTRACTION_DEFAULT: Final = False


class Extractor(Protocol):
    model_name: str

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]: ...


def _first_json_object(text: str) -> dict[str, Any]:
    """Models wrap JSON in prose and fences no matter how firmly you ask. Take the
    first balanced object rather than failing the whole extraction on a stray ```.

    A RECOVERY, and a recovery is strictly weaker than a constraint — which is why the
    Azure path carries a constraint TOO (`build_azure_response_schema`) rather than
    instead. Under Structured Outputs this function has nothing left to do and runs as a
    no-op; it stays on that path because the strict form is documented rather than
    observed on our own resource, and the degrade that covers that gap lands here. It
    remains load-bearing for Sarvam, whose chat API publishes
    `response_format: {"type": "json_object"}` but no per-request schema, and for the
    offline runner. Deleting it because "the schema guarantees JSON now" would remove the
    only thing holding up the path taken when the schema is refused."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        if start == -1:
            return {}
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    break
    if candidate is None:
        return {}
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class SarvamExtractor:
    """D-36 default. Sarvam's chat API is OpenAI-compatible."""

    def __init__(
        self,
        api_key: str,
        model: str = SARVAM_DEFAULT_LLM,
        *,
        timeout_s: float = EXTRACTION_TIMEOUT_S,
    ) -> None:
        self._api_key = api_key
        self.model_name = model
        # INJECTED RATHER THAN READ, and defaulted to the post-call number so every
        # existing caller keeps the behaviour it had. The user-triggered path passes
        # `ASSIST_TIMEOUT_S` because it is one of TWO legs behind an edge deadline; the
        # ARQ path has nobody waiting on an HTTP connection and keeps 30s. A module-level
        # switch read here instead would make the budget depend on who happened to import
        # first, which is the shape of bug that only shows up under load.
        self._timeout_s = timeout_s

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            response = await client.post(
                SARVAM_CHAT_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.model_name,
                    "messages": [
                        {"role": "user", "content": build_extraction_prompt(spec, transcript)}
                    ],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
            )
        response.raise_for_status()
        body = response.json()
        # `choices` comes back EMPTY when the provider declines to answer (filtered
        # content, truncated generation). Indexing it blindly turned "the model said
        # nothing" into an IndexError that escaped the error ladder below and failed
        # the whole post-call job — losing the call to keep the fields.
        choices = body.get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        return _first_json_object(str(content))


#: How each schema field type is spelled in a JSON Schema Azure's Structured Outputs will
#: accept. LOWER-CASE, unlike Vertex's OpenAPI dialect, and a SMALLER set than JSON Schema
#: publishes: strict mode rejects the request outright if the schema uses a keyword it does
#: not support, which is why nothing here reaches for `format`, `minLength` or `pattern`.
#:
#: `date` is `string` and not `format: "date"` for the reason it was under Vertex, and now
#: for a second one. The prompt tells the model to keep a relative time in the caller's own
#: words ("repu udayam") and `coerce_value` parses ISO where it can; a schema-level date
#: format would make the model INVENT a calendar date for "tomorrow morning" to satisfy the
#: type, which is the one thing this whole path is built not to do. Strict mode does not
#: support `format` anyway — the product argument and the vendor constraint agree.
_AZURE_TYPES: Final[dict[str, str]] = {
    "text": "string",
    "number": "number",
    "bool": "boolean",
    "enum": "string",
    "date": "string",
}

#: The five keys every extraction returns regardless of schema (TRD §7). NOT nullable:
#: these are what `ExtractionOutput` always carries, and a model omitting one is a
#: malformed answer rather than an empty field.
_AZURE_FIXED_PROPERTIES: Final[dict[str, dict[str, Any]]] = {
    "summary": {"type": "string"},
    "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
    "outcome_tag": {
        "type": "string",
        "enum": ["resolved", "needs_follow_up", "transferred", "dropped"],
    },
    "out_of_scope": {"type": "boolean"},
    "callback_requested": {"type": "boolean"},
}

#: The label the schema travels under. Azure constrains it to `^[a-zA-Z0-9_-]+$`, so it is
#: spelled here rather than derived from a tenant's anything — and it is a LABEL, not an
#: identity: the schema itself differs per agent, so a name that tried to identify one
#: would be a second, wronger version of `extraction_schemas.version`.
AZURE_SCHEMA_NAME: Final = "calevate_call_extraction"


def _azure_property(field: ExtractionField) -> dict[str, Any]:
    """One schema field as a strict-mode property. Nullable, always.

    NULLABILITY IS A TYPE UNION HERE, not a `nullable` keyword — that is Vertex's OpenAPI
    dialect and strict mode rejects it. `["string", "null"]` is the JSON Schema spelling
    and it is what makes "the caller never said" expressible at all under a mode that
    requires every property to be present.

    A NULLABLE ENUM CARRIES `null` IN ITS OWN LIST. Omitting it leaves a schema no value
    can satisfy — `enum` restricts to the listed members, so a `null` permitted by the
    type union would be forbidden by the enum one line below it.
    """
    prop: dict[str, Any] = {"type": [_AZURE_TYPES[field.type], "null"]}
    if field.type == "enum" and field.enum_values:
        prop["enum"] = [*field.enum_values, None]
    if field.description:
        prop["description"] = field.description
    return prop


def build_azure_response_schema(spec: ExtractionSchemaSpec) -> dict[str, Any]:
    """The strict JSON Schema that makes valid, schema-shaped JSON a MODEL-SIDE guarantee.

    THE GUARANTEE IS BACK, and this function is the whole of it. Azure documents
    Structured Outputs (`response_format: {"type": "json_schema", "strict": true}`) on
    `gpt-4o-mini` and later — both models in `AZURE_OPENAI_MODELS` — and states that under
    it "the model will never return a response that deviates from the provided schema".
    That is the same class of promise Vertex's `responseSchema` made and it is why
    `_first_json_object` is a belt beside braces here rather than the only thing holding
    the output up. (VERIFIED-VENDOR-DOCS, 19 Aug 2026: Microsoft Learn
    `azure/foundry/openai/how-to/structured-outputs`. NOT verified against OUR deployment —
    see `AzureOpenAIExtractor.run` for what happens if this resource refuses it.)

    STRICT MODE'S THREE CONSTRAINTS, AND WHY NONE OF THEM COST US ANYTHING:

    1. **Every property must appear in `required`.** Under Vertex only the five fixed keys
       were required and a client's own field could be ABSENT. That reads like a conflict
       with "ABSENT MEANS NULL" and is not one: strict mode's answer to an optional field
       is a nullable type, so the field is always PRESENT and its value is `null` when the
       caller never said it. Downstream this is not a distinction at all —
       `coerce_value` short-circuits on `raw is None` and `validate_extraction` skips a
       None — so **an extraction schema is expressed exactly as it was before**; only the
       wire spelling of "nothing captured" changed. Crucially it still does NOT force the
       model to produce a value: forcing a client's `callback_number` to be non-null would
       push the model to invent one, and a phone number one digit wrong is the worst
       output this system can produce.
    2. **`additionalProperties: false`.** A chatty model cannot bolt an extra key on. This
       is strictly better than the old behaviour, where `validate_extraction` dropped
       unknown keys AFTER paying for them.
    3. **A reduced keyword set.** No `format`, no `pattern`, no bounds — see `_AZURE_TYPES`
       for why that costs this path nothing.

    ORDER IS PROPERTY ORDER, and it is load-bearing rather than cosmetic. Generation is
    left-to-right, so the model must read the transcript for facts before it writes the
    summary that would otherwise anchor them. Vertex needed a separate `propertyOrdering`
    list to say that; here the insertion order of `properties` IS the statement, which
    also DELETES a defect by construction: that parallel list named a colliding key twice
    and a `propertyOrdering` with a duplicate is a malformed object, so one client
    authoring a field called `summary` turned every assist for that tenant into a 400. A
    dict cannot hold a key twice, so the collision now resolves once — the fixed
    definition wins, in the fixed position, because the tenant's key is filtered out
    BEFORE the fixed five are appended rather than overwritten in place.

    ⚠ THE SCHEMA IS INPUT. It is serialised into the request and counted against the input
    token budget — a 30-field schema with descriptions is not free, which is why
    `AzureOpenAIExtractor` reads Azure's own `usage` block back rather than counting the
    prompt: `ai_assist_ktok_in` (D-137) has to be what the vendor charged for, and the
    schema is the part of that number nobody would have thought to add up.
    """
    properties: dict[str, Any] = {
        field.key: _azure_property(field)
        for field in spec.fields
        if field.key not in _AZURE_FIXED_PROPERTIES
    }
    properties.update(_AZURE_FIXED_PROPERTIES)
    return {
        "type": "object",
        "properties": properties,
        # Every key, because strict mode demands it — optionality lives in the type.
        "required": list(properties),
        "additionalProperties": False,
    }


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """What one model call cost, in the vendor's own count.

    Tokens, not thousands: `billing/ai_quota.ktok()` converts, once, where the money is,
    because `qty` is `NUMERIC` and a division done here would arrive as a float.
    """

    prompt_tokens: int
    output_tokens: int


def _azure_usage(body: dict[str, Any]) -> TokenUsage | None:
    """Azure's `usage` block as our own record, or None if it did not send one.

    NONE IS NOT ZERO and the difference is a billing one: a missing block means we do not
    know what this call cost, and metering it as zero would quietly give one tenant a
    free assist and move the platform brake by nothing. `record_ai_assist_usage` is
    therefore never called on a None, and that is the caller's rule to keep.

    `completion_tokens` IS THE WHOLE OUTPUT LEG AND NOTHING IS ADDED TO IT, which is the
    one line that changed shape when D-410 left Gemini. Vertex reported `thoughtsTokenCount`
    SEPARATELY from `candidatesTokenCount`, so the two had to be summed or a reasoning
    model would be under-metered; on the OpenAI wire format `completion_tokens_details`
    is a BREAKDOWN of `completion_tokens`, not an addition to it, and summing them would
    bill a tenant twice for the same tokens. Neither model this platform ships
    (`AZURE_OPENAI_MODELS`) emits reasoning tokens at all, so the arm is not reachable
    today — it is written down because "port the Gemini line across" is the tempting edit
    and it is wrong in the expensive direction.
    """
    raw = body.get("usage")
    if not isinstance(raw, dict):
        return None

    def _count(key: str) -> int:
        value = raw.get(key)
        return value if isinstance(value, int) and value >= 0 else 0

    total_in = _count("prompt_tokens")
    total_out = _count("completion_tokens")
    if total_in == 0 and total_out == 0:
        return None
    return TokenUsage(prompt_tokens=total_in, output_tokens=total_out)


class AzureOpenAIExtractor:
    """Azure OpenAI in `AZURE_LOCATION` (D-410). The dashboard-AI leg, and only that leg.

    ⚠ **THIS LEG IS NO LONGER IN INDIA AND THE DISCLOSURE OBLIGATION IS UNCHANGED BY THAT.**
    D-449 moved the resource to `eastus2`; D-127's G-1..G-7 rules still bind every request
    below — redaction BEFORE the call, no raw PII on the wire, the fallback disclosed —
    and they now matter more rather than less, because the redactor is the only thing
    standing between an Indian SMB's caller data and a US processor.

    THE ENDPOINT IS STILL THE DECISION, AND IT NO LONGER PROVES ITSELF — read this before
    trusting the residency guard. D-127 disqualified `generativelanguage.googleapis.com`
    because a global host names no region, and Vertex answered by putting `asia-south1`
    in the hostname AND the path, so `scripts/check_model_residency.py` could prove
    residency straight from this file's AST. Azure's shipped shape cannot:
    `<resource>.openai.azure.com` hides the region entirely. **Where the request is
    processed is a property of the Azure RESOURCE, asserted by config and verified once
    by a human in the portal — this code cannot demonstrate it and does not pretend to.**
    That is a real weakening against the Vertex design and it is the price of a static
    key; `AZURE_LOCATION` is the one spelling of the region we ship, and what the guard
    still proves is that no second spelling and no second URL builder exist.

    The REGIONAL hostname (`<region>.api.cognitive.microsoft.com`) would restore the
    AST proof and is rejected FOR NOW rather than forgotten: Azure documents the v1
    surface only on the custom-subdomain form, so shipping it would trade a
    confirmed-working endpoint for a stronger guard on an unconfirmed one.

    AUTH IS A STATIC API KEY IN AN `Authorization: Bearer` HEADER, which is the whole
    reason this class replaced a Vertex one. Azure's v1 surface
    (`https://<resource>.openai.azure.com/openai/v1/`) is OpenAI-compatible, takes no
    `api-version`, and accepts a key in that header — so there is no OAuth2 handshake, no
    12-hour ceiling, no refresh cron and no dead man watching the refresh cron. The
    classic surface (`/openai/deployments/<id>/chat/completions?api-version=YYYY-MM-DD`
    with an `api-key:` header) is deliberately NOT used: the dated `api-version` is a
    second thing to keep current, and `api-key` is not what an OpenAI-compatible client
    sends.

    THE MODEL AND THE DEPLOYMENT ARE TWO DIFFERENT STRINGS AND ONLY ONE GOES ON THE WIRE.
    On Azure you deploy a model under a deployment ID of your choosing and address THAT,
    so `model` in the request body is the DEPLOYMENT. `model_name` — what the eval
    baseline keys on, what a log line reports and what `LLM_MODELS[model].price`
    prices — is the underlying model, because a deployment ID is one operator's routing
    label and says nothing about cost or quality. Reporting the deployment as the model
    would silently re-baseline the whole regression harness on a console rename.

    THE SCHEMA GUARANTEE SURVIVED THE MIGRATION. This leg sends
    `response_format: {"type": "json_schema", "strict": true}` with a schema built from
    the agent's own extraction spec, which Azure documents on `gpt-4o-mini` and later as
    a promise that "the model will never return a response that deviates from the
    provided schema" — the same class of promise Vertex's `responseSchema` made, and it
    matters more than it sounds: this schema IS a client's CRM columns, so best-effort
    JSON parsing would be a product-visible regression rather than an internal one. See
    `build_azure_response_schema` for the three constraints strict mode adds and why none
    of them changes how an extraction schema is expressed.

    AND IT DEGRADES RATHER THAN FAILING, because the paragraph above is documented and
    UNOBSERVED HERE. Microsoft's docs are about the model and the API; nobody has yet
    watched OUR resource accept the parameter. A 400 on the first attempt is therefore
    retried ONCE with plain `json_object` and logged as `azure_json_schema_unsupported`,
    so a deployment that refuses the strong form still answers its user — with the weaker
    promise, said out loud in a log line, instead of an outage on a paragraph from a
    vendor's website. `_first_json_object` is what catches the output in that case, which
    is why it is belt beside braces here and not dead weight.

    WHAT IT IS ALLOWED TO SEE: redacted call data and tenant-authored config (G-2).
    `run_assist()` is the only caller and enforces that; this class does not re-check,
    because a guard in two places is a guard whose two halves eventually disagree about
    which one is authoritative.
    """

    def __init__(
        self,
        resource: str,
        api_key: str,
        deployment: str,
        model: str = AZURE_OPENAI_DEFAULT_MODEL,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = EXTRACTION_TIMEOUT_S,
    ) -> None:
        # Built ONCE, here, through the single builder — `azure_openai_base_url` is the
        # only thing in this repository allowed to spell an Azure endpoint, which is what
        # `check_model_residency` proves. A second f-string anywhere would be a second
        # place the host can be got wrong.
        self._url = f"{azure_openai_base_url(resource)}/chat/completions"
        self._api_key = api_key
        self._deployment = deployment
        self.model_name = model
        # Same injection seam, and the same ownership rule, as `GoogleSheetsTransport`: a
        # caller-supplied client is the caller's to close. It exists so tests drive this
        # adapter through httpx's real request plumbing (`httpx.MockTransport`) rather
        # than a hand-written stand-in that cannot get a URL wrong.
        self._client = client
        # Applies to the client this adapter OWNS. An injected client arrives with its own
        # timeout already configured and this does not reach in and rewrite it — same
        # ownership rule as `aclose()` above, and a caller who hands over a client has
        # already made the decision this argument makes.
        self._timeout_s = timeout_s
        #: What the LAST `run()` cost, as Azure counted it — never as we counted it.
        #:
        #: MUTABLE STATE ON AN ADAPTER, deliberately, and the bound is what makes it
        #: safe: `run_assist()` constructs one of these per assist and reads this
        #: attribute in the next statement, so there is never a second `run()` to race
        #: with. The rejected alternative was widening the `Extractor` Protocol to return
        #: usage — which would make `OfflineExtractor` and `SarvamExtractor` answer a
        #: question one of them cannot (no network) and the other need not (D-36 prices
        #: the Sarvam leg at zero), i.e. two implementations forced to state a number
        #: nobody meters. `record_ai_assist_usage` (D-137) meters the ASSIST leg, because
        #: that is the one that costs Calevate rupees.
        self.last_usage: TokenUsage | None = None

    def _log_refusal(self, status: int) -> None:
        """The one place an Azure non-2xx becomes something an operator can act on.

        WHY THIS EXISTS AT ALL. `extract_call`'s ladder records `type(exc).__name__`, so
        every failure on this path reaches the log as the single word `HTTPStatusError` —
        401 (the key), 404 (no such deployment on this resource), 429 (quota) and 5xx
        (Azure) all indistinguishable, on a path where the status is the whole diagnosis.

        THE BODY IS NEVER LOGGED (hard rule 6). Azure's error bodies quote the request,
        and the request on this path is a call transcript — redacted, but redacted text
        is still transcript-derived and does not belong in a log line. Neither the key
        nor the URL is logged either: the resource name is in the URL and the key is in
        a header, and an operator needs neither to act on any row below.
        """
        if status == 404:
            # THE CONFIGURATION GATE, at the only moment anyone is looking. On this
            # surface a 404 is not "no such model" — it is "no deployment by that ID on
            # this resource", which is the one mistake the model/deployment split makes
            # easy to walk into. Named so an operator greps it, and spelling out the
            # wrong fix because it is the tempting one.
            log.error(
                "azure_deployment_not_found",
                extra={
                    "region": AZURE_LOCATION,
                    "model": self.model_name,
                    "deployment": self._deployment,
                    "remedy": (
                        "AZURE_OPENAI_DEPLOYMENT must be the deployment ID as it appears "
                        "in the Azure portal, which is NOT the model name. Do not 'fix' "
                        "this by setting it to AZURE_OPENAI_MODEL, and do not point the "
                        "resource at another region: check_model_residency refuses a "
                        "second spelling of the region, and the one spelling is "
                        "AZURE_LOCATION."
                    ),
                },
            )
            return
        log.warning(
            "azure_request_refused",
            extra={"status": status, "model": self.model_name, "deployment": self._deployment},
        )

    async def _post(
        self,
        client: httpx.AsyncClient,
        spec: ExtractionSchemaSpec,
        transcript: str,
        *,
        response_format: dict[str, Any],
    ) -> httpx.Response:
        """One chat completion. The two callers below differ only in `response_format`."""
        return await client.post(
            self._url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                # THE DEPLOYMENT, not the model — see the class docstring.
                "model": self._deployment,
                "messages": [
                    {"role": "user", "content": build_extraction_prompt(spec, transcript)}
                ],
                "temperature": 0,
                "response_format": response_format,
            },
        )

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        owns_client = self._client is None
        # `follow_redirects=False` is load-bearing rather than tidy: a redirect off the
        # region-pinned host is a residency question, and answering it silently by
        # following the hop is the one thing this leg must not do.
        client = self._client or httpx.AsyncClient(timeout=self._timeout_s, follow_redirects=False)
        try:
            response = await self._post(
                client,
                spec,
                transcript,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": AZURE_SCHEMA_NAME,
                        "strict": True,
                        "schema": build_azure_response_schema(spec),
                    },
                },
            )
            if response.status_code == 400:
                # THE DEGRADE, and its trigger is deliberately ANY 400 rather than a
                # reading of the error body. The thing we cannot verify is exactly what
                # this resource says when it refuses `json_schema`, so a discriminator
                # keyed on `error.code` or `error.param` would be a guess about the very
                # payload in doubt — and guessing wrong means an outage on a documented
                # feature. A 400 is refused at request validation: no model time, no
                # tokens, a few milliseconds. So we simply ask again the weaker way. If
                # the 400 was really something else (a content filter, a malformed body),
                # the retry earns the same 400 and the ORIGINAL refusal is the one
                # reported, which is the right diagnosis.
                #
                # NOT MEMOISED, and that is the rejected alternative worth naming: a flag
                # remembering "this deployment refuses strict" would save one cheap round
                # trip per assist and would (a) be process-global mutable state needing a
                # reset seam for tests, and (b) go stale the moment the deployment is
                # upgraded — locking a fixed resource into the weak promise forever, with
                # nothing to notice. Paying milliseconds to re-ask is the cheaper mistake.
                degraded = await self._post(
                    client, spec, transcript, response_format={"type": "json_object"}
                )
                if not degraded.is_error:
                    log.warning(
                        "azure_json_schema_unsupported",
                        extra={
                            "model": self.model_name,
                            "deployment": self._deployment,
                            "consequence": (
                                "Structured Outputs was refused by this resource, so the "
                                "assist ran on json_object: valid JSON, but no model-side "
                                "guarantee that it matches the agent's extraction schema. "
                                "Confirm the deployment's model is gpt-4o-mini or later."
                            ),
                        },
                    )
                    response = degraded
        finally:
            if owns_client:
                await client.aclose()
        if response.is_error:
            self._log_refusal(response.status_code)
        response.raise_for_status()
        body = response.json()
        self.last_usage = _azure_usage(body)
        # `choices` comes back EMPTY, or carries a null `content`, when the provider
        # declines to answer — Azure's content filter is an ordinary response with
        # `finish_reason: "content_filter"`, not an exception, and Structured Outputs adds
        # a model-authored `refusal` beside `content` on the same footing. Neither is read
        # here: `refusal` is the model's prose ABOUT a call transcript, which is not a
        # thing this module logs or stores (hard rule 6), and both land as "no answer".
        # Same reasoning as the Sarvam path above — indexing blindly turns "the model said
        # nothing" into an IndexError, and losing the call to keep the fields is the wrong
        # trade.
        choices = body.get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        # STILL THE FENCE-STRIPPER AND NOT A BARE `json.loads`. Under strict mode the
        # content is a schema-shaped document and this is a no-op; on the degraded path it
        # is the only thing standing between a fenced answer and an empty extraction. One
        # parse path, correct under both promises.
        return _first_json_object(str(content or ""))


@dataclass(frozen=True)
class _Mention:
    """One place the caller names a candidate value, and whether they stood by it.

    `order` is (turn, clause, offset within the clause) — the position of the words in
    the call. It is what turns "the caller's LAST word on it" into a comparison rather
    than a guess, and it is why a mention is a record and not a boolean.
    """

    order: tuple[int, int, int]
    value: str
    asserted: bool


#: Words in a field LABEL that describe the column rather than the thing the caller
#: talks about. "Callback requested" is a column; what a caller says is "callback".
#: Stripping them is what lets the probe be the WHOLE subject ("site visit") instead of
#: its first word ("site") — see `_subject_pattern`.
_LABEL_STATE_WORDS = frozenset(
    {
        "a",
        "agreed",
        "an",
        "booked",
        "concern",
        "confirmed",
        "consent",
        "flag",
        "given",
        "interest",
        "interested",
        "is",
        "needed",
        "preference",
        "raised",
        "request",
        "requested",
        "required",
        "status",
        "the",
        "want",
        "wanted",
        "wants",
        "was",
        "yes",
    }
)


def _always(value: str) -> Callable[[re.Match[str]], str]:
    """A `value_of` for the fields whose candidate value is fixed by the pattern that
    found it — an enum member, or the single subject of a bool."""
    return lambda _match: value


@lru_cache(maxsize=512)
def _word_pattern(phrase: str) -> re.Pattern[str]:
    """`phrase` as whole words, whitespace-flexible.

    Word boundaries, not substrings: substring matching made the enum value `other`
    match inside "brother" and `caller` match the speaker prefix on every line. `\\b`
    is avoided because enum values legitimately end in punctuation ("4BHK+"), where it
    would flip meaning; the explicit lookarounds do not.
    """
    words = phrase.split()
    joined = r"\s+".join(re.escape(word) for word in words)
    return re.compile(rf"(?<!\w){joined}(?!\w)", re.IGNORECASE)


@lru_cache(maxsize=512)
def _subject_pattern(label: str) -> re.Pattern[str] | None:
    """What a caller has to say for this bool field's SUBJECT to have been mentioned.

    The label is a column name of the shape "<subject> <state>": strip the state words
    and the whole remainder must be spoken. "Site visit" keeps both words, so "mee site
    address cheppandi" — a caller asking where the site is — no longer sets
    `site_visit_interest`; "Callback requested" keeps "callback", so the caller saying
    "callback kavali" still does.

    LIMIT, stated rather than hidden: a client whose label carries subject words the
    caller never speaks ("Site visit kavala") now captures nothing where the old
    first-word probe captured something. That direction is deliberate — a miss is
    `capture_miss` (waivable, a weaker reader), a wrong `true` is `restraint`/
    `capture_wrong` (never waivable, and it sends a sales team to meet nobody).
    """
    words = [w for w in re.findall(r"[\w']+", label.lower()) if w not in _LABEL_STATE_WORDS]
    if not words:
        # A label that is nothing but state words ("Interested?"). Fall back to its
        # first word rather than probing on the empty string, which would match every
        # turn ever spoken.
        words = re.findall(r"[\w']+", label.lower())[:1]
    if not words:
        return None
    return _word_pattern(" ".join(words))


class OfflineExtractor:
    """Deterministic, no network. Reads what the transcript literally says.

    It is not a stub: it implements the one rule the prompt insists on — never invent
    a value that was not said — so a schema field with no evidence comes back null and
    the pipeline's null-handling is exercised for real in local runs and CI.

    **Every field is decided by one scan** (`_mentions` + `_settled`), whatever its
    type: find each place the caller names a candidate value, drop the ones a negation
    or an enquiry in the same clause disqualifies, and let the caller's LAST word on
    each value decide whether it stands. Four separate defects — a denied enum filed
    anyway, a superseded requirement beating the one the caller settled on, a
    self-corrected name kept in its first version, a topic word read as a consent —
    were four faces of "the first thing that matched wins, and nothing later can
    revoke it". They are fixed once, here, so a fifth field type cannot reintroduce it
    by taking its own shortcut.

    **What this cannot see**, stated because an honest limit beats a claim of
    comprehension, and because the next reader will otherwise assume the scan
    understands more than it does:

    - a negation more than one clause away from what it negates ("3BHK kavali. Antha
      budget ledu andi." does not retract the size, and a bare "kaadu kaadu" clause
      retracts nothing by itself — `_settled`'s last-word rule covers the common
      correction shape instead);
    - irony, sarcasm, and a hypothetical ("2BHK aithe baagundedi");
    - a correction the caller makes in a LATER CALL — every scan here is one
      transcript, and reconciling a lead across calls is the CRM's job, not this one's;
    - a value the caller never speaks in the words the schema uses (Telugu numerals, a
      budget said as "yabhai lakshalu"), which stays a miss, as it was before;
    - the pronoun a correction hangs on: "adi kaadu, rendodi" ("not that one, the
      second") names no value this scan can match.
    """

    model_name = "offline-heuristic"

    # `naa peru` / `my name is` only. The bare `peru` alternative this used to carry
    # matched the AGENT asking "Mee peru cheppandi?" and filed "Cheppandi" as the
    # caller's name — a fabricated CRM row from a question nobody answered.
    _NAME_RE = re.compile(
        r"(?:naa peru|naa pearu|my name is)\s+([A-Za-z][A-Za-z\s]{1,30}?)"
        r"(?:\s+(?:andi|garu|ji)\b|[,.]|$)",
        re.IGNORECASE,
    )
    _NEGATIVE = ("complaint", "angry", "worst", "refund", "cheating", "bad")
    _CALLBACK = ("call me back", "callback", "malli call", "tarvata call")
    # Negation triggers, Telugu · Hindi · English, word-bounded. A candidate value named
    # inside a clause that carries one of these is a caller REFUSING or RETRACTING the
    # thing, which is the opposite of the fact we would otherwise record.
    #
    # Word boundaries, not the substring test this list used to carry (which is why it
    # needed the trailing spaces in "no " and "not "): `no` sits inside half the English
    # lexicon and `not` inside "note", and a false negation DISCARDS a fact the caller
    # really stated.
    #
    # The cost of that choice, stated: Telugu also fuses negation into the verb
    # ("konaledu" = did not buy, "raledu" = did not come), and only the standalone forms
    # below are caught. A fused negation reads as an assertion of whatever else is in
    # the clause — which is why the list carries the standalone words a caller uses to
    # REFUSE or RETRACT, the two cases that put a wrong value in a client's CRM.
    _NEGATION_RE = re.compile(
        r"(?<!\w)(?:"
        r"ledu|ledhu|leedu|"  # "there is none" / "did not" — "avasaram ledu"
        r"vaddu|vaddhu|vaddandi|voddu|"  # "I don't want it"
        r"kaadu|kaadhu|kadu|"  # "it is not that" — the Telugu self-correction marker
        r"saripodu|saripodhu|saripoledu|"  # "that will not do"
        r"nahi|nahin|mat|"  # Hindi
        r"no|not|never|"
        r"don'?t|doesn'?t|didn'?t|won'?t|can'?t|cannot"
        r")(?!\w)"
        # The Telugu PROHIBITIVE is a suffix, not a word: "cheyakandi" (do not do it),
        # "ravaddu" (do not come), "cheyyoddu". Without this, "appointment cancel
        # cheyakandi" reads as a cancellation — the most expensive false positive in
        # the clinic vertical.
        r"|(?<!\w)\w+(?:akandi|akande|avaddu|oddu)(?!\w)",
        re.IGNORECASE,
    )
    # Clause boundaries — NegEx's "termination terms", as punctuation plus the two
    # contrastive conjunctions this product's transcripts actually use.
    # (dashes as escapes: a literal em/en dash in source is a lint-flagged homoglyph)
    _CLAUSE_SPLIT_RE = re.compile(
        "[,;.!?\u2026\u2014\u2013]+|\\s+(?:--|kaani|kani|but|however)\\s+", re.IGNORECASE
    )
    # "Did my booking get cancelled?" is not a cancellation. A caller who rings to ASK
    # about something says its name just as plainly as one who did it, so the word alone
    # cannot separate them — but the ASKING can be recognised, and that is a different
    # question with a real answer. The Telugu verb "to ask" is the `adag-`/`adug-` stem
    # (`adagataniki` = "in order to ask"), `telusuko-` is "to find out", and the English
    # equivalents follow.
    #
    # Deliberately verbs and not question marks: a transcript comes from an STT engine
    # that does not punctuate reliably, so a rule resting on "?" would work on the
    # fixtures and fail on production audio. Deliberately narrow, too — bare "check" is
    # left out because "I want to check in" is not an enquiry, and a false enquiry
    # DISCARDS a fact the caller really did state.
    _ASKING_RE = re.compile(
        r"(?<!\w)(?:adag\w*|adug\w*|telusuko\w*|ask\w*|enquir\w*|inquir\w*|wanted to know)(?!\w)",
        re.IGNORECASE,
    )
    # Speaker prefixes as the transcript writes them. Anything unprefixed is treated as
    # the caller only when there is no prefixed line at all (a transcript we cannot
    # attribute is not evidence about anybody).
    _CALLER_PREFIXES = ("caller:", "customer:", "user:")
    _AGENT_PREFIXES = ("agent:", "assistant:", "bot:")

    @classmethod
    def _caller_turns(cls, transcript: str) -> list[str]:
        """Only what the CALLER said, with the prefix stripped.

        Every field below describes the caller, and reading the agent's lines as
        evidence about them is how this extractor invented three different kinds of
        fact: a name out of the agent's question, a `true` out of a question the caller
        answered "ledu" to, and an enum out of the word `caller:` itself.
        """
        turns: list[str] = []
        saw_prefix = False
        for line in transcript.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lowered = stripped.lower()
            if lowered.startswith(cls._AGENT_PREFIXES):
                saw_prefix = True
                continue
            for prefix in cls._CALLER_PREFIXES:
                if lowered.startswith(prefix):
                    saw_prefix = True
                    turns.append(stripped[len(prefix) :].strip())
                    break
            else:
                if not lowered.startswith(cls._AGENT_PREFIXES):
                    turns.append(stripped)
        if saw_prefix:
            return [turn for turn in turns if turn]
        # No speaker labels anywhere: fall back to the whole transcript rather than
        # returning nothing, but that is a transcript we cannot attribute.
        return [line.strip() for line in transcript.splitlines() if line.strip()]

    @classmethod
    def _clauses(cls, turn: str) -> list[str]:
        """One turn split into the units a negation can reach across.

        This is the scope rule, and it is the one place worth departing from the
        established approach. NegEx (Chapman et al. 2001, and ConText after it) scopes a
        trigger over a fixed window — the current version, to the end of the SENTENCE
        unless a termination term ("but", "however") cuts it short — and its documented
        weakness is exactly that: with several candidate values inside one window it
        negates them all. That failure is not hypothetical here. "Manaki 3BHK ne kavali,
        2BHK saripodu" is one sentence holding both the requirement and its rejected
        alternative, and a sentence-wide scope files neither.

        So the scope is the CLAUSE: punctuation and a contrastive conjunction terminate
        it, as in NegEx, but they also START the next scope rather than merely ending
        the trigger's reach. What the departure buys is the clause above — the shape
        Telugu callers state a correction in — and it costs the ability to see a
        negation that sits in a clause of its own ("Iddaru... kaadu kaadu, muggurum"),
        which the last-word-wins rule in `_settled` covers instead.
        """
        return [clause.strip() for clause in cls._CLAUSE_SPLIT_RE.split(turn) if clause.strip()]

    @classmethod
    def _negated(cls, clause: str) -> bool:
        """Does this clause carry a negation trigger?

        Direction-blind, unlike NegEx's pre/post-trigger split, because this product is
        code-mixed: Telugu and Hindi are verb-final and negate AFTER the thing ("site
        visit vaddu", "2BHK saripodu"), English negates before it ("don't send"), and
        one clause here routinely holds both languages. Within a clause this short the
        direction carries no information the clause boundary does not already carry.
        """
        return cls._NEGATION_RE.search(clause) is not None

    @staticmethod
    def _asked_about(clause: str) -> bool:
        """Is this clause the caller ENQUIRING rather than stating?

        Clause-level, like `_negated`: the evidence and its qualifier live in one
        breath. "Naa booking cancel aipoyinda ani adagataniki call chesanu" is one
        clause — the matrix verb "adagataniki chesanu" governs the embedded complement
        inside it — so the word `cancel` never stands alone as a fact.

        It was turn-level until the scan below became the one path every field takes,
        and a turn-wide enquiry frame then swallowed the name in "Naa peru Naresh,
        doctor timings adagataniki chesanu": the caller enquired about the timings and
        STATED their name in the same turn. Both readings cannot be right, and the
        clause is the unit the qualifier actually attaches to.

        LIMIT: an enquiry frame that reaches across a comma into a later clause is not
        seen.
        """
        return OfflineExtractor._ASKING_RE.search(clause) is not None

    @classmethod
    def _mentions(
        cls,
        caller_turns: list[str],
        pattern: re.Pattern[str],
        value_of: Callable[[re.Match[str]], str],
    ) -> list[_Mention]:
        """Every place the caller names a candidate value, in the order they said it.

        The one scan behind every field type. `pattern` says what a mention looks like
        and `value_of` says which value that mention is about — a name, an enum member,
        or the single subject of a bool. Whether the caller MEANT it is decided here and
        only here: an enquiry in the clause means nothing in it was asserted at all, a
        negation in the clause means the value was asserted and then refused.

        The difference matters for `_settled`: an enquiry is not evidence either way, so
        it is skipped rather than recorded as a retraction — asking about a site visit
        neither books one nor cancels the one you agreed to a moment ago.
        """
        found: list[_Mention] = []
        for turn_index, turn in enumerate(caller_turns):
            for clause_index, clause in enumerate(cls._clauses(turn)):
                if cls._asked_about(clause):
                    continue
                asserted = not cls._negated(clause)
                for match in pattern.finditer(clause):
                    found.append(
                        _Mention(
                            order=(turn_index, clause_index, match.start()),
                            value=value_of(match),
                            asserted=asserted,
                        )
                    )
        return found

    @staticmethod
    def _settled(mentions: list[_Mention]) -> str | None:
        """The value the caller left standing, or None if they left none.

        THE property this extractor was missing, in four lines: for each candidate
        value the caller's LAST word on it decides whether it stands, and the field
        takes the last value still standing. Per-VALUE, deliberately — a caller
        rejecting 2BHK has not withdrawn the 3BHK they asked for in the same breath,
        while a caller who says "vaddu" about the one subject a bool field has really
        has withdrawn it.

        Nothing here can invent: with no mentions, or none that survived, the field is
        absent exactly as before.
        """
        latest: dict[str, _Mention] = {}
        for mention in sorted(mentions, key=lambda m: m.order):
            latest[mention.value] = mention
        standing = [m for m in latest.values() if m.asserted]
        return max(standing, key=lambda m: m.order).value if standing else None

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        caller_turns = self._caller_turns(transcript)
        caller_text = "\n".join(caller_turns)
        lowered = caller_text.lower()
        data: dict[str, Any] = {}

        for field in spec.fields:
            if field.type == "bool":
                probe = _subject_pattern(field.label)
                if probe is None:
                    continue
                # A bool has ONE candidate value, so every mention is about the same
                # thing and the caller's last word on it decides. True only when they
                # said it and left it standing; silence and a refusal both stay null,
                # because this extractor never invents a value that was not said and
                # "false" is a value.
                if self._settled(self._mentions(caller_turns, probe, _always("affirmed"))):
                    data[field.key] = True
                continue
            if field.key in ("name", "caller_name", "patient_name"):
                # Each spoken name is its own candidate value, so a caller who corrects
                # themselves ("naa peru Ravi, kaadu kaadu — naa peru Raviteja") is filed
                # under the correction rather than against it.
                name = self._settled(
                    self._mentions(
                        caller_turns, self._NAME_RE, lambda m: m.group(1).strip().title()
                    )
                )
                if name:
                    data[field.key] = name
                continue
            if field.type == "enum" and field.enum_values:
                mentions = [
                    mention
                    for enum_value in field.enum_values
                    for mention in self._mentions(
                        caller_turns, _word_pattern(enum_value), _always(enum_value)
                    )
                ]
                value = self._settled(mentions)
                if value:
                    data[field.key] = value

        all_lines = [ln for ln in transcript.splitlines() if ln.strip()]
        return {
            **data,
            # A TRANSCRIPT LINE, VERBATIM — speaker prefix and all. That is honest for a
            # deterministic baseline ("reads what the transcript literally says") and it
            # is why `calls.summary` is treated as transcript-derived text on every exit
            # rather than as a safely abstracted field: the API read path redacts it
            # (`crm.service.redacted_summary`), the outbound webhook redacts it
            # (`workers/pipeline`), the hot-lead notification redacts it
            # (`notifications._compose`) and the DPDP export masks foreign numbers out of
            # it (`compliance/export`). Making this abstractive would NOT retire any of
            # those: the model path writes free prose that can quote a number the caller
            # read out, and every summary already stored would keep whatever it holds.
            "summary": (all_lines[-1][:200] if all_lines else "No transcript available."),
            "sentiment": "negative" if any(w in lowered for w in self._NEGATIVE) else "neutral",
            "outcome_tag": (
                "needs_follow_up" if any(w in lowered for w in self._CALLBACK) else "resolved"
            ),
            "out_of_scope": False,
            "callback_requested": any(w in lowered for w in self._CALLBACK),
        }


def get_extractor() -> Extractor:
    """The FIRST post-call extraction's runner. Sarvam, or the offline baseline.

    There is no silent failover between providers, because they differ on data residency
    and that is not a runtime decision — the principle this docstring has always stated,
    now with the branch that contradicted it removed.

    THE ASSIST PROVIDER IS NOT REACHABLE FROM HERE (D-127 G-2/G-7). This function used to
    return the assist extractor when that provider's key was configured and a Sarvam key
    was not. The caller is `workers/pipeline.py`, which hands over the RAW transcript
    because a "callback number" field needs the actual digits — so that branch sent raw
    caller PII to a second processor whenever one environment variable was absent.
    `GEMINI_EXTRACTION_DEFAULT is False` is that decision as a fact the tree can be asked
    about; `run_assist()` is where the assist provider serves, over the redacted copy, at
    a user's request.

    THE CONSEQUENCE, STATED RATHER THAN DISCOVERED: a deployment holding only an Azure
    credential now extracts with `OfflineExtractor`. That is the intended direction — a
    deterministic reader that files what the transcript literally says is a smaller loss
    than a residency inversion — and it is not a state any environment is in:
    `runtime_config_missing_keys` has required `SARVAM_API_KEY` outside `local` since
    before D-127, so `/healthz/ready` is already red there.
    """
    settings = get_settings()
    if settings.sarvam_api_key:
        return SarvamExtractor(settings.sarvam_api_key)
    return OfflineExtractor()


# --- G-6: one place decides what happens when the assist provider cannot serve ------
#
# PLAN Part 15. Every reason code below is AUTHORED — it names OUR configuration state,
# never a vendor's error string, because these reach an alert, a client's screen and a
# support conversation.

#: No Azure OpenAI credential on this deployment: no resource, no key, or no deployment
#: ID. The ordinary state today — no Azure resource exists yet.
NO_CREDENTIAL_REASON: Final = "no_credential"
#: The tenant is past its included monthly assist quota and has not accepted the charge
#: (G-5). Supplied BY THE CALLER — see `assist_capability`.
QUOTA_EXHAUSTED_REASON: Final = "quota_exhausted"
#: The provider answered badly, or did not answer. Discovered by trying, so also supplied
#: by the caller after a failed attempt.
PROVIDER_UNAVAILABLE_REASON: Final = "provider_unavailable"
#: THERE IS NO `model_not_allowed` REASON, AND THE ABSENCE IS THE DESIGN. D-127 carried
#: `ai_studio_key_disqualified` in a fourth slot here, for a deployment that was
#: configured WRONGLY rather than not at all. Its Azure analogue would be "the configured
#: model is not one we ship" — and it cannot happen: `Settings.azure_openai_model` is
#: typed `AzureOpenAIModel`, a closed `Literal`, and `platform_config.validate_value`
#: checks a console write against that field definition before it is ever stored. The
#: allow-list is enforced at the boundary values enter through, which is strictly earlier
#: and strictly stronger than a check here, so a second one would be an arm no user can
#: reach, an authored sentence nobody reads, and a second place the rule is stated.

#: Provider names as they appear in a disclosure and in a log line.
AZURE_PROVIDER: Final = "azure"
SARVAM_PROVIDER: Final = "sarvam"

#: Is a per-tenant assist quota enforced on a path a client can reach? YES, since D-146.
#:
#: This constant spent its whole life False and the paragraph under it moved twice, which
#: is the argument for having minted it. D-137 built the ceiling (`require_ai_assist`),
#: the idempotent writer (`record_ai_assist_usage`), the brake on our own key
#: (`platform_ai_spend`) and the audited acceptance (`POST /v1/billing/ai-quota/extra`);
#: D-142 added this module's two ends of the wire, `run_assist(quota_exhausted=…)` and
#: `AssistResult.usage`. Every piece worked and nothing was enforced, because no route
#: joined them — the state a greppable boolean exists to stop a document describing as
#: "quota enforcement".
#:
#: `POST /v1/calls/{call_id}/assist` (`apps/api/crm/routes.py::assist_call`) is the middle.
#: It calls `require_ai_assist` BEFORE the provider is paid, hands the verdict to
#: `run_assist`, and meters `AssistResult.usage` back through `crm/assist.py::meter_assist`
#: — the three lines this comment named as its own closing condition, in that order.
#:
#: What True does NOT claim, because the next reader will ask: an assist whose token count
#: the provider did not return is money spent that no ceiling can see. It is refused a ledger row
#: rather than given a fabricated one, and it fires `ai_assist_unmeterable` so an operator
#: learns the meter stopped. Enforcement is real; it is not omniscient.
ASSIST_QUOTA_ENFORCED: Final = True

#: What each fallback reason means, in the words the client reads. One sentence per code,
#: written once: a disclosure composed at each surface is a disclosure that eventually
#: says something different on two screens about the same event.
_FALLBACK_DISCLOSURE: Final[dict[str, str]] = {
    NO_CREDENTIAL_REASON: (
        "This was written by Sarvam, not the assistant model, because no Azure OpenAI "
        "credential is configured on this deployment."
    ),
    QUOTA_EXHAUSTED_REASON: (
        "This was written by Sarvam, not the assistant model, because this month's "
        "included assistant usage is used up."
    ),
    PROVIDER_UNAVAILABLE_REASON: (
        "This was written by Sarvam, not the assistant model, because the assistant model "
        "did not answer."
    ),
}


@dataclass(frozen=True, slots=True)
class AssistCapability:
    """What this deployment can actually do about user-triggered AI, as one answer.

    `PaymentCapability`'s shape, for `PaymentCapability`'s reason: a caller must not be
    able to conclude "the assistant works" and then separately assume "so it is the
    preferred model answering". Both facts are one lookup and one object.

    `reason` is non-None exactly when `available` is False. `fallback_reason` is non-None
    exactly when `provider` is not the preferred one — and when it is set, `disclosure`
    is the sentence that MUST travel with the answer, in the response and on the screen
    (G-6). A fallback nobody is told about silently changes output quality, which is the
    single outcome that decision rules out.
    """

    available: bool
    provider: str | None = None
    reason: str | None = None
    fallback_reason: str | None = None

    @property
    def disclosure(self) -> str | None:
        """The sentence to show beside a fallback answer, or None when there was none."""
        if self.fallback_reason is None:
            return None
        return _FALLBACK_DISCLOSURE.get(self.fallback_reason)


def azure_credentials() -> tuple[str, str, str] | None:
    """Resource, key and deployment for Azure OpenAI, or None if this deployment lacks
    any of the three.

    THE ONLY read of the three `azure_openai_*` credential fields, so "configured" is
    decided once rather than by each caller's idea of which fields matter.

    ALL THREE OR NOTHING, because two of them are useless: a resource with no deployment
    ID cannot address anything, and a key with no resource has nowhere to go. What the
    ladder below distinguishes is UNSET from HALF-SET — a deployment with none of the
    three is the ordinary state and says nothing, while a deployment with one or two is
    an operator midway through a change, and reporting that as "unconfigured" sends them
    to install what they already installed (D-127 made the same distinction for a
    service-account key that was present and unparseable).

    THE LOG LINE NAMES FIELDS, NEVER VALUES. One of the three IS the credential.
    """
    settings = get_settings()
    resource = (settings.azure_openai_resource or "").strip()
    api_key = (settings.azure_openai_api_key or "").strip()
    deployment = (settings.azure_openai_deployment or "").strip()
    missing = [
        name
        for name, value in (
            ("azure_openai_resource", resource),
            ("azure_openai_api_key", api_key),
            ("azure_openai_deployment", deployment),
        )
        if not value
    ]
    if len(missing) == 3:
        return None
    if missing:
        log.error("azure_credential_incomplete", extra={"missing": missing})
        return None
    return resource, api_key, deployment


def azure_extractor(*, timeout_s: float = EXTRACTION_TIMEOUT_S) -> AzureOpenAIExtractor | None:
    """A ready Azure extractor for this deployment, or None if it holds no credential.

    ONE constructor, so nothing outside this module has to know that "the Azure client"
    is four configuration values rather than one. `scripts/eval.py`'s provider table
    wants exactly this: every other provider it scores is built from a single credential
    string and this one is not. A caller that assembled them itself would be the second
    place that decides what "configured" means, and the first place is
    `azure_credentials()`.

    THE MODEL IS READ WITHOUT A CHECK, which is not an omission — see
    `MODEL_NOT_ALLOWED`'s absence above. `azure_openai_model` is a closed `Literal` with
    a default, so it is always set and is always one this platform ships; `gpt-4.1-mini`
    is D-410's live switch and moving it is a console edit, not a deploy.

    `timeout_s` PASSES THROUGH RATHER THAN BEING DECIDED HERE, and defaults to the
    post-call budget so `scripts/eval.py` and the pipeline are unchanged. It is a keyword
    on the ONE constructor because the alternative — `run_assist` building the adapter
    inline to give it a different timeout — is exactly the second assembly of the same
    four settings this function exists to prevent.
    """
    credentials = azure_credentials()
    if credentials is None:
        return None
    resource, api_key, deployment = credentials
    return AzureOpenAIExtractor(
        resource,
        api_key,
        deployment,
        get_settings().azure_openai_model,
        timeout_s=timeout_s,
    )


def assist_capability(
    *, quota_exhausted: bool = False, provider_unavailable: bool = False
) -> AssistCapability:
    """THE selector (D-127 G-6). Every user-triggered AI surface asks this and nothing
    re-reads settings for itself.

    THE LADDER, and each rung is a decision rather than a check:

    1. **Azure serves it** when a credential resolves, the configured model is one we
       ship, the tenant is inside its quota and the provider has not just failed. This is
       the preferred answer and carries no disclosure, because nothing was substituted.
    2. **Sarvam serves it, disclosed**, when Azure cannot. A fallback is honest here:
       both are instruction-following LLMs over the same redacted text, and the difference
       is quality, not correctness — so the answer stands and the client is told whose it
       is. `OfflineExtractor` is deliberately NOT in this ladder: it is a deterministic
       reader of literal transcript text, and offering its output as "your re-summarised
       call" would be substituting a different KIND of thing while claiming to substitute
       a model.
    3. **Refuse**, with the reason that stopped Azure, when there is no Sarvam key
       either. `assist_unavailable()` turns that into a message with a remediation.

    `quota_exhausted` and `provider_unavailable` are ARGUMENTS rather than reads. Neither
    is knowable from configuration: the first is a per-tenant month-to-date sum that
    `usage_events` owns (`require_ai_assist`, reached through `crm/routes.py::assist_call`),
    and the second is only knowable by having just tried. Passing them in keeps this
    function a pure function of its inputs, which is what lets one test drive all six
    states without a database.
    """
    settings = get_settings()

    blocked: str | None = None
    if quota_exhausted:
        # Checked FIRST, and before credentials, because it is the one a user can act on:
        # a client at their ceiling needs the modal (G-5), not "no credential configured".
        blocked = QUOTA_EXHAUSTED_REASON
    elif provider_unavailable:
        blocked = PROVIDER_UNAVAILABLE_REASON
    elif azure_credentials() is None:
        blocked = NO_CREDENTIAL_REASON

    if blocked is None:
        return AssistCapability(available=True, provider=AZURE_PROVIDER)
    if settings.sarvam_api_key:
        return AssistCapability(available=True, provider=SARVAM_PROVIDER, fallback_reason=blocked)
    return AssistCapability(available=False, reason=blocked)


def assist_unavailable(capability: AssistCapability) -> ProblemError:
    """The refusal a user meets when nothing can serve. Never a bare 500, never a spinner.

    `remediation` is what SEC-COMP calls the actionable half and what `ProblemNotice`
    renders verbatim on the screen, so it is written for the person who will read it:
    a client can act on "top up" and cannot act on "configure a service account", so the
    two reasons get different sentences even though both are the same HTTP status.
    """
    reason = capability.reason or NO_CREDENTIAL_REASON
    remediation = {
        QUOTA_EXHAUSTED_REASON: (
            "This month's included AI assistance is used up. Add credit, or wait for the "
            "next billing month."
        ),
        PROVIDER_UNAVAILABLE_REASON: (
            "The assistant model did not answer and this deployment has no second model "
            "configured. Try again in a few minutes; if it persists, contact support."
        ),
    }.get(
        reason,
        "No AI provider is configured on this deployment. Install an Azure OpenAI "
        "resource (AZURE_OPENAI_RESOURCE + AZURE_OPENAI_API_KEY + "
        "AZURE_OPENAI_DEPLOYMENT) or a Sarvam API key (DEV-SETUP §4).",
    )
    return ProblemError(
        kind="dependency",
        code=f"assist_{reason}",
        title="AI assistance is not available",
        detail="This deployment cannot run the AI assistant right now.",
        remediation=remediation,
    )


@dataclass(frozen=True, slots=True)
class AssistResult:
    """One user-triggered assist: what came back, who wrote it, and what it cost.

    `usage` is non-None only for an AZURE answer that Azure counted — the leg that spends
    Calevate's rupees and the only one `record_ai_assist_usage` (D-137) has units for. A
    Sarvam fallback leaves it None because D-36 prices that leg at zero, and an Azure
    answer whose `usage` block did not arrive leaves it None because "we do not know" and
    "it was free" must not meter the same.
    """

    output: ExtractionOutput
    capability: AssistCapability
    usage: TokenUsage | None = None


async def run_assist(
    spec: ExtractionSchemaSpec, redacted_transcript: str, *, quota_exhausted: bool = False
) -> AssistResult:
    """Run ONE user-triggered assist over REDACTED call text (D-127 G-2, G-6, G-7).

    THE INPUT GUARD IS THE POINT, and it is structural rather than documentary. G-2 says
    this leg never sees raw PII; a parameter named `redacted_transcript` is a promise, and
    a promise is what `pipeline.py:750` broke by accident the last time two nearly
    identical strings sat one line apart. So the text is re-run through `redact()` and
    REFUSED if that pass still finds something — the caller must hand over
    `transcript_turns.text_redacted`, not `text`. This costs one regex sweep per assist
    and removes the whole class.

    THE REFUSAL WAS UNREACHABLE UNTIL D-146, and the paragraph that said so is worth
    keeping in its corrected form rather than deleting. This guard was written BEFORE any
    caller existed, for `check_model_residency`'s reason — the mistake it catches is one
    line of a route handler that nobody would re-read, and the moment to make it
    impossible is before the handler exists rather than after it ships.

    That bet paid immediately. `crm/routes.py::assist_call` is now the caller, and the
    sabotage that swaps `text_redacted` for `text` in `crm/assist.py`'s one SQL string
    does not first fail an assertion about bytes — it fails HERE, with
    `assist_input_not_redacted`, from inside the function the route calls. The guard
    catches the exact mistake its author predicted, in the exact place predicted.

    THE FALLBACK IS DISCLOSED, NEVER SILENT. Azure failing mid-flight re-asks the ONE
    selector with `provider_unavailable=True` rather than deciding locally, so a surface
    can never grow its own idea of what a failure means; the answer that comes back
    carries `capability.disclosure`, which the response and the screen must show.

    IT STILL DOES NOT METER OR CHARGE — `billing/ai_quota.py` owns both (D-137) — but it
    is now WIRED to the half that decides. `quota_exhausted` is the verdict of
    `require_ai_assist`, passed IN rather than read here, because the answer needs a
    session and a tenant and this module has neither; without the parameter the ceiling
    D-137 built could not reach the one function that runs an assist, which is a gate
    with no door. What it returns is the other half: `AssistResult.usage` is what
    `record_ai_assist_usage` needs for `tokens_in`/`tokens_out`, in Azure's own count.
    Money stays outside a model adapter; the numbers money is computed from come from it,
    because nowhere else can see them.
    """
    if redact(redacted_transcript).changed:
        # An authored refusal, not an assertion: this is reachable by a caller mistake and
        # a caller mistake deserves a message. Nothing about the text is logged.
        raise ProblemError(
            kind="validation",
            code="assist_input_not_redacted",
            title="This text has not been redacted",
            detail="AI assistance runs on redacted call text only.",
            remediation=(
                "Pass `transcript_turns.text_redacted` (or `calls.summary` after "
                "`crm.service.redacted_summary`), never the raw turn text."
            ),
        )

    capability = assist_capability(quota_exhausted=quota_exhausted)
    if not capability.available:
        raise assist_unavailable(capability)

    if capability.provider == AZURE_PROVIDER:
        # `azure_extractor()` rather than a second assembly of the same four settings: it
        # is the ONE constructor, and the branch that used to build the adapter inline
        # here was the second place that decided what "configured" means.
        #
        # `ASSIST_TIMEOUT_S`, NOT `EXTRACTION_TIMEOUT_S`: this leg is the FIRST of two
        # that a waiting browser pays for in series, behind a 60s edge deadline. See that
        # constant for the arithmetic and for why the bound is per-leg rather than one
        # deadline around both.
        extractor = azure_extractor(timeout_s=ASSIST_TIMEOUT_S)
        if extractor is not None:
            output = await extract_call(spec, redacted_transcript, extractor=extractor)
            failure = output.errors.get("_model")
            if failure is None:
                # A schema-invalid FIELD is still an answer (`valid=False`, per-field
                # errors) and belongs to the client to see. Only `_model` — the ladder's
                # code for "the provider did not give us anything" — is a provider event.
                return AssistResult(
                    output=output, capability=capability, usage=extractor.last_usage
                )
            # `extract_call` swallows a provider failure into `errors["_model"]` so a
            # post-call pipeline never loses a call over one. Here the user is waiting
            # and the answer is empty, so the same event means something different: ask
            # the ONE selector again, with the fact we now have, rather than deciding
            # locally what an Azure outage means.
            log.warning(
                "assist_provider_failed",
                extra={"model": extractor.model_name, "error": failure},
            )
        # `quota_exhausted` is re-stated rather than dropped: it cannot be True here
        # today (the ladder blocks on it first, so this branch is unreachable with it
        # set), and a re-ask that silently forgot an input would become wrong the moment
        # somebody reorders those rungs.
        capability = assist_capability(quota_exhausted=quota_exhausted, provider_unavailable=True)
        if not capability.available:
            raise assist_unavailable(capability)

    settings = get_settings()
    # Reachable only with `sarvam_api_key` set — `assist_capability` returns
    # `provider="sarvam"` on no other condition — but mypy cannot see that through the
    # capability object, and an `assert` here would be a crash where a refusal belongs.
    if not settings.sarvam_api_key:  # pragma: no cover - unreachable via the selector
        raise assist_unavailable(AssistCapability(available=False, reason=NO_CREDENTIAL_REASON))
    output = await extract_call(
        spec,
        redacted_transcript,
        # The SECOND leg, and the one whose answer the user actually gets when Azure was
        # slow. Giving it the post-call 30s here is what used to push the pair past the
        # edge deadline and replace this answer with a 504.
        extractor=SarvamExtractor(settings.sarvam_api_key, timeout_s=ASSIST_TIMEOUT_S),
    )
    return AssistResult(output=output, capability=capability)


async def extract_call(
    spec: ExtractionSchemaSpec, transcript: str, *, extractor: Extractor | None = None
) -> ExtractionOutput:
    """Run one extraction pass and validate it against the schema.

    A model failure does NOT fail the call: an extraction row still lands with
    `valid=False` and the error, so the call, the lead and the metering all survive an
    LLM outage. Losing the structured fields is recoverable; losing the call is not.
    """
    runner = extractor or get_extractor()
    try:
        raw = await runner.run(spec, transcript)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        # IndexError/TypeError belong here with the rest: a provider response whose
        # shape we did not expect is a MODEL failure, and this ladder exists so a model
        # failure costs the structured fields and never the call, the lead or the
        # metering (which all happen after this returns).
        record_extraction_failure(reason=type(exc).__name__)
        log.warning("extraction_failed", extra={"model": runner.model_name})
        return ExtractionOutput(valid=False, errors={"_model": type(exc).__name__})

    outcome = validate_extraction(spec, raw)
    if outcome.errors:
        record_extraction_failure(reason="schema_validation")

    sentiment = raw.get("sentiment")
    outcome_tag = raw.get("outcome_tag")
    return ExtractionOutput(
        data=outcome.data,
        summary=str(raw.get("summary") or "")[:2000],
        sentiment=sentiment if sentiment in ("positive", "neutral", "negative") else "neutral",
        outcome_tag=(
            outcome_tag
            if outcome_tag in ("resolved", "needs_follow_up", "transferred", "dropped")
            else "resolved"
        ),
        out_of_scope=bool(raw.get("out_of_scope")),
        callback_requested=bool(raw.get("callback_requested")),
        valid=outcome.valid,
        errors=outcome.errors,
    )


__all__ = [
    "ASSIST_QUOTA_ENFORCED",
    "AZURE_PROVIDER",
    "AZURE_SCHEMA_NAME",
    "GEMINI_EXTRACTION_DEFAULT",
    "NO_CREDENTIAL_REASON",
    "PROVIDER_UNAVAILABLE_REASON",
    "QUOTA_EXHAUSTED_REASON",
    "SARVAM_PROVIDER",
    "AssistCapability",
    "AssistResult",
    "AzureOpenAIExtractor",
    "Extractor",
    "OfflineExtractor",
    "SarvamExtractor",
    "TokenUsage",
    "assist_capability",
    "assist_unavailable",
    "azure_credentials",
    "azure_extractor",
    "build_azure_response_schema",
    "extract_call",
    "get_extractor",
    "run_assist",
]
