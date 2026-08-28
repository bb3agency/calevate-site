"""Guardrail: this tree cannot construct a model endpoint except through the one builder
the LEG that owns it names, and every region a leg pins has exactly one spelling in code
(D-410, made a declared choice by D-432, opened to a set of legs when clients gained a
provider choice).

**WHAT A POSTURE IS NOW.** It is a NAME declared once in source (`DECLARED_POSTURE_NAME` in
`CONTRACT`) plus a CLOSED, ORDERED SET OF LEGS (`DECLARED_LEGS`), each of which says where
one provider's traffic goes and what it costs to prove it. `POSTURES` below — written HERE,
never imported from there — says what each name OBLIGES the tree to look like, leg by leg.
The mechanism is the COMPARISON of two independent statements, which is strictly more than
the tree could prove before D-432, because before there was nothing to disagree with:

* **check 0** (`declaration_failures`) fails when the DECLARATION drifts from the code — the
  one-line direction, and therefore the likely one. An unknown posture name is a hard
  failure; so is a `DECLARED_LEGS` tuple that is not the legs this spec expects, in order;
  so is a `PostureLeg` record whose region, provider, builder, host or gate says something
  the spec does not.
* **checks 1-4** fail when the CODE drifts from the declaration. Each is stated over EVERY
  declared leg rather than over one vendor.
* **check 7** (`inert_leg_failures`) is new and has no analogue in the mechanism it
  replaces: a declared leg that no model names, or whose builder nothing in the tree ever
  calls, is a FAILURE. Without it the permitted set rots into a wish list — a leg nobody
  exercises reads exactly like a leg that is enforced, and every check stated over it prints
  OK on an empty set.

================================================================================
**WHAT THIS GUARD NOW PROVES LESS OF — READ THIS BEFORE THE GREEN LINE.**
================================================================================

This file's doctrine is that a guard quietly checking less while still printing `OK` is
worse than a deleted one, so the weakening is recorded here rather than left in a diff.

**THE WRONG-VENDOR CLAUSE WENT FROM REFUSING THREE HOSTS OUT OF FOUR TO REFUSING ONE.**
Under `us-azure-openai` exactly one of the four watched hosts belonged to the declared
posture, so a literal naming any of the other three — `api.openai.com`,
`generativelanguage.googleapis.com`, `<region>.api.cognitive.microsoft.com` — was refused
for naming a vendor this product does not use. Under `multi-provider-byok` three of the four
belong to a declared leg, and the only host refused for belonging to NO leg is Azure's
REGIONAL form. That is a real reduction in what a hand-written endpoint has to get past, and
no amount of per-leg strictness gives it back: adopting a vendor means the guard can no
longer refuse that vendor's host on sight.

**AND THE OPENAI BAN IS GONE, NOT NARROWED.** `api.openai.com` used to be refused outright
with D-410's reason (their India residency covers storage at rest; inference runs in the
US). D-449 withdrew the India requirement, so that ground stopped discriminating, and the
host is now a declared leg's. What replaced the ban is weaker in kind (a single-literal rule
instead of a prohibition) and stronger in one respect (see below) — but the sentence "this
tree may not name OpenAI's API" is no longer true, and a reader who remembers it will be
wrong.

**TWO THINGS ARE BOUGHT BACK, AND THEY ARE WHY THE TRADE IS WORTH MAKING.**

1. **A REGION THIS GUARD CAN ACTUALLY PROVE, ON ONE LEG.** Azure's shipped endpoint names no
   region — the region is a property of the RESOURCE, and gates 20/20c are two standing
   human attestations. OpenAI's regional endpoints put it back in the authority:
   `us.api.openai.com` (VERIFIED-VENDOR-DOCS, `openai/openai-python@e43b422412a9`,
   `src/openai/_data_residency.py`). So `leg_builder_failures` reads the label off
   `openai_base_url()`'s own return template and requires it to be a `Final` holding that
   leg's region — the same machinery the dormant Azure regional-host branch has carried
   since D-410, now with a live subject. That leg delegates NOTHING: no gate 20, no gate
   20c, no portal reading. It is the first time since D-127 that any residency claim in this
   tree is provable from the AST.
2. **A LEG NOBODY USES IS A BUILD FAILURE** (check 7). The old table could hold a spec that
   nothing in the tree exercised — D-453 found exactly that, twice, when a posture's
   `permitted_host` was absent from a hand-written watched-host tuple and every check over
   it printed OK on an empty set. A declared leg must now be named by at least one model in
   the catalogue AND its builder must be called somewhere, or the run is red.

**AND THE GOOGLE LEG'S RULE MOVED FROM "ZERO LITERALS" TO "EXACTLY ONE" (D-478).** It used to
carry `builder=None`/`builder_suffix=None`, because the IN-CALL Google provider builds its own
client from a single API key and reads no base URL of ours — so its obligation was ZERO
literals anywhere. D-478 puts the DASHBOARD copilot on the Gemini OpenAI-compat
`/chat/completions` surface, which `google_openai_compat_base_url()` in the contract assembles,
so the leg now carries that arity-0 builder and its frozen suffix (`GEMINI_BUILDER_SUFFIX`).
The obligation is now the ordinary one every builder-carrying leg has: EXACTLY ONE frozen
literal in the contract may name the host, and every other literal, handler or fixture — the
in-call path included, which still names nothing — is refused. The region question did not
move: the Developer API has none to pin, in host, path or field.

================================================================================

WHAT THE FOUR STRUCTURAL CHECKS STILL SAY, PER LEG:

1. **ONE SPELLING OF EACH PINNED REGION.** `AZURE_LOCATION: Final = "eastus2"` and
   `OPENAI_DATA_RESIDENCY: Final = "us"` in the portability contract are the only places
   those regions are written. A second `Final`, a default argument, a dict value — anything
   else spelling one is refused, and a constant holding a region no declared leg pins (the
   withdrawn `southindia`, or `us` under a posture with no OpenAI leg) is refused by VALUE.
2. **NO `Settings` FIELD CAN CARRY A REGION**, by NAME or by default VALUE, and none can
   carry a hand-typed model endpoint for ANY vendor this file knows a leg for.
   `platform_config.managed_fields()` derives the ops console's editable set from
   `Settings.model_fields` minus the bootstrap keys minus credential-shaped names, so a
   field called `azure_location` would be editable from a web form the day it was declared,
   and a residency posture invertible by a click at 3am is not a posture. The vendor half is
   the union over EVERY known leg, never the declared ones alone: the field a half-finished
   posture move leaves behind names the vendor the tree has just LEFT.
3. **NO ENDPOINT IS CONSTRUCTIBLE EXCEPT THROUGH ITS LEG'S BUILDER.** For a leg with a
   builder, exactly ONE string literal in `apps/`, `packages/` and `scripts/` may contain
   its host: the `Final` suffix that builder is assembled from, in `BUILDER_HOME`, frozen.
   For a leg with no builder, ZERO.
4. **NO BUILDER CAN EMIT A REGION OTHER THAN ITS LEG'S.** It takes the arity the leg
   permits, no argument is region-shaped, its output template interpolates only that
   argument and module-level `Final`s, it RAISES rather than interpolating a caller value
   that is not a single DNS label (required only above arity zero — a fixed vendor endpoint
   has no hostile label to refuse), and where the leg's region IS in the host, the label in
   front of the host must resolve to the `Final` holding that region.

WHAT NO VERSION OF THIS CHECK CAN PROVE ON THE AZURE LEG, AND WHO OWNS IT INSTEAD. Two
facts, both properties of the Azure resource rather than of this repository, both invisible
from the endpoint, and the second is the more dangerous:

* **Is the resource in the region the leg pins (`eastus2` since D-449)?** OPERATIONS §2
  **gate 20** — a human reads the Location field on the resource's Overview blade, confirms
  it with `az cognitiveservices account show --query location`, and files the reading in
  `docs/evidence/` with a date and a name.
* **Is the deployment REGIONAL Standard rather than GLOBAL?** OPERATIONS §2 **gate 20c**.
  Global is Azure's DEFAULT deployment type and processes worldwide. A Global deployment
  inside the declared resource passes every check in this file and breaks the DPA. It costs
  money to get right (Regional runs ~5-10% above Global list), which is precisely why nobody
  will notice having left the default.

`delegation_failures()` is not decoration: it fails this build if those gates stop being
written down, because the honest half of a weakened guard is the pointer to whoever holds
the other half. And it is now stated PER LEG, so a leg that delegates nothing has to say so
in its spec rather than by omission.

THE AZURE REGIONAL HOSTNAME, AND WHY THIS FILE IS BUILT SO ADOPTING IT IS ONE LINE. Azure
also serves `<region>.api.cognitive.microsoft.com`, documented as interchangeable with the
custom subdomain — a hostname that CARRIES THE REGION, which would give the Azure leg the
property the OpenAI leg now has. D-410 rejects it FOR NOW on one ground: the
OpenAI-compatible v1 surface is documented only on the custom-subdomain form (and custom
subdomains are what Entra ID requires), so shipping it would trade a confirmed-working
endpoint for a stronger guard on an unconfirmed one. **OPERATIONS §2 gate 20d is the call
that settles it**: flip `REGIONAL_HOST_ADOPTED`, and the same scan that today REFUSES that
hostname starts requiring the label in front of it to be the Azure leg's region. Both
branches are exercised by `tests/model_residency_guard_test.py`, so the dormant one is not a
promise.

WHY THERE IS NO BLACKLIST OF OTHER AZURE REGIONS (`eastus`, `swedencentral`, or — since
D-449 — `southindia` itself). It was the obvious replacement for the `us-central1` check and
it is unreachable: a region string can only affect where a call lands by reaching an
endpoint, no endpoint is constructible outside a leg's builder (check 3), and no builder has
a region input (check 4). A ban on strings that cannot reach anything is a check with no
failure mode, and it would rot into "add your region to the list" the first time somebody
names a variable after a datacentre.

MECHANISM: the Python half reads the **AST**, not the source text, and reconstructs
f-strings into templates (`f"https://{X}{SUFFIX}"` becomes `https://{X}{SUFFIX}` with each
hole carrying the interpolated expression's source). Two reasons, both learned here. First,
`sarvam_model_identifier_test`'s: a correction has to be EXPLAINED somewhere, and a regex
over source flags the paragraph explaining it — this very docstring names every watched
host. Second, provenance: "the region came from `OPENAI_DATA_RESIDENCY`" and "the region
came from `self._loc`" are the same string to a grep and are not the same fact.

A CONSEQUENCE WORTH STATING RATHER THAN DISCOVERING: `"https://{r}.openai.azure.com/…"
.format(r=X)` is refused, because the template says `{r}` and nothing about `X`. Call the
builder. The rejected alternative was resolving `.format()` arguments — it works for the
literal call and not for a template passed around, so it would buy a style allowance at the
cost of a check that is right sometimes.

WHAT THIS CHECK CANNOT SEE BESIDES THE TWO PORTAL FACTS, said plainly so nobody mistakes a
green run for a whole answer. It judges LITERALS. A host assembled by concatenation at
runtime, read from an environment variable, or returned by a vendor SDK that builds its own
URL is invisible to it — which is why check 2 exists and why it is a name-and-default check
on `Settings` rather than a URL check: if the value never appears in the tree, the tree
cannot be asked, and the only remaining defence is that there is nowhere console-editable
for it to live. The RUNTIME half of that blind spot is covered elsewhere and deliberately:
`ModelConfig._llm_endpoint_is_coherent` refuses any `llm_base_url` the naming leg's own
builder could not have emitted, so the static check covers the literal and the validator
covers the value.

The literals that DEFINE the watched hosts in this file are its whole self-exemption — see
`SELF` and `_host_definition`; a URL written anywhere else in this file is judged like any
other file's. The non-Python half is a LINE scan (`.ts`, `.json`, shell, nginx): a line
naming a watched host becomes a reference and is judged by the same rules, so an Azure URL
in a TypeScript file is caught — but with no AST there is no way to tell code from a `//`
comment, so a comment naming one in those files WILL be reported. That false positive is
accepted rather than engineered away: this repo has no non-Python caller of a model
provider, CLAUDE.md forbids one, and a comment about a model host in the frontend is worth a
human look anyway.

NOT IN SCOPE: `oauth2.googleapis.com`, `sheets.googleapis.com` and
`www.googleapis.com/auth/spreadsheets` in `workers/google_sheets.py`. Those are the tenant's
OWN destination, chosen by them, disclosed in their DPA, and carry no model inference. This
check is about where a MODEL runs. IN SCOPE, AND THE LINE BETWEEN THEM IS A FULL HOSTNAME
RATHER THAN A DOMAIN: `generativelanguage.googleapis.com` is the Gemini Developer API, it is
a MODEL host, and it is a declared leg's — so it is watched, and the zero-literal rule above
is what judges it. Matching `.googleapis.com` instead would have swept every CRM export into
a residency check, which is the false positive that gets a guard switched off.

Run: `uv run python -m scripts.check_model_residency`   (also in `make guardrails`)
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]

#: THE REGIONS THIS CHECK KNOWS HOW TO ENFORCE — one `Final` per region any known leg pins,
#: spelled HERE rather than imported, for the reason `check_bootstrap_keys.BOOTSTRAP_KEYS`
#: gives: a guardrail that imported the value it is checking would be asking the code
#: whether it agrees with itself. They are also this check's own blindness canary (check 5)
#: — the provenance scan must be able to find EVERY one of these lines, or it is not reading
#: anything.
#:
#: **WHY THE WITHDRAWN REGION KEEPS A CONSTANT HERE (D-449).** Deleting `AZURE_REGION_INDIA`
#: when the declaration moved off `southindia` would have been one line, and it would have
#: blinded this check to the single most likely product of a half-finished posture move: a
#: leftover `AZURE_LOCATION: Final = "southindia"` in a tree that has moved on. A scan that
#: looked only for the DECLARED regions walks straight past that constant and reports "one
#: spelling of the region" — true, and useless.
AZURE_REGION_INDIA: Final = "southindia"
AZURE_REGION_US: Final = "eastus2"

#: **THE SHORTEST REGION TOKEN IN THIS FILE, AND THE COST IS NAMED RATHER THAN DISCOVERED.**
#: OpenAI's residency regions are two-letter (`DataResidency = Literal["global","us","eu",
#: "ae"]`), so `loose_region_literals` will refuse a bare `"us"` anywhere in `apps/`,
#: `packages/` or `scripts/` that is not a `Final`'s value. There are zero such literals
#: today (measured 22 Aug 2026) and a future one — a locale, a country column, a dict key —
#: turns the build red with a message naming `OPENAI_DATA_RESIDENCY`. That is the correct
#: trade: the alternative is a region this leg pins that no check can see, which is the
#: property the leg was adopted FOR.
OPENAI_REGION_US: Final = "us"

#: The name and home of the constants in shipped code allowed to hold those strings.
#: Both are asserted (check 1): a second constant, or the same one moved somewhere a
#: reader would not look for it, is a second spelling of a residency decision.
REGION_CONSTANT: Final = "AZURE_LOCATION"
OPENAI_REGION_CONSTANT: Final = "OPENAI_DATA_RESIDENCY"
BUILDER_HOME: Final = "packages/shared/src/calevate_shared/engine.py"

#: The functions permitted to produce each leg's endpoint (checks 3 and 4).
BUILDER: Final = "azure_openai_base_url"
OPENAI_BUILDER: Final = "openai_base_url"
GEMINI_BUILDER: Final = "google_openai_compat_base_url"

#: Azure OpenAI's CUSTOM-SUBDOMAIN host suffix — the form D-410 ships, and the form that
#: **carries no region**. The Azure leg's two human gates are downstream of that fact.
AZURE_HOST_SUFFIX: Final = ".openai.azure.com"

#: The rest of the Azure endpoint, exactly as `azure_openai_base_url` assembles it. The one
#: literal in the whole tree permitted to name an Azure host is this string, declared as a
#: `Final` in `BUILDER_HOME` (`_AZURE_ENDPOINT_SUFFIX`).
#:
#: SPELLED HERE RATHER THAN IMPORTED, like the region constants, and it buys something
#: extra: the v1 path shape is VERIFIED EVIDENCE (Microsoft Learn, 19 Aug 2026 — no
#: `api-version`, key in `Authorization: Bearer`), not a preference. If somebody edits the
#: path in `BUILDER_HOME`, this guard goes red and the edit has to be made deliberately in
#: both places, which is the correct amount of friction for a change that moves what a third
#: party is handed.
BUILDER_SUFFIX: Final = ".openai.azure.com/openai/v1"

#: Azure's REGIONAL host form, which puts the region back in the URL where a static check
#: can read it. Rejected FOR NOW by D-410 (the v1 surface is documented only on the custom
#: subdomain); OPERATIONS §2 gate 20d is the call that reopens it. See
#: `REGIONAL_HOST_ADOPTED`. It belongs to NO leg, which is what leaves it the only watched
#: host the wrong-vendor clause still refuses outright.
AZURE_REGIONAL_HOST_SUFFIX: Final = ".api.cognitive.microsoft.com"

#: OpenAI's own API.
#:
#: ⚠ **THIS USED TO BE A BAN AND IS NOW A DECLARED LEG'S HOST.** D-410 refused it because
#: OpenAI's India data residency covers storage at rest only and inference ran in the US;
#: D-449 stopped asking for Indian inference, so that ground stopped discriminating, and the
#: leg was adopted for the opposite reason — it is the ONLY host in this file that carries
#: its region in the authority. The watched string stays the BARE host (`api.openai.com`)
#: rather than the regional form, deliberately: `us.api.openai.com` contains it, so both
#: forms are seen, and the label in front of it is what tells the pinned endpoint from the
#: GLOBAL one. A watched string of `us.api.openai.com` would make the global endpoint —
#: the one that makes no regional claim at all — invisible.
OPENAI_DIRECT_HOST: Final = "api.openai.com"

#: The rest of that endpoint, kept beside the host for `BUILDER_SUFFIX`'s reason. It carries
#: the LEADING DOT because the dot belongs to the join between the residency label and the
#: host: a suffix starting at `api` would let a builder emit `https://usapi.openai.com/v1`,
#: which is somebody else's domain.
OPENAI_BUILDER_SUFFIX: Final = ".api.openai.com/v1"

#: Google's Gemini DEVELOPER API — the AI Studio (OpenAI-compat) surface, not Vertex.
#:
#: ⚠ **UNTIL D-478 ZERO LITERALS MAY NAME IT; NOW EXACTLY ONE MAY.** The in-call leg still
#: builds its own client from a single API key and reads no base URL of ours
#: (`bolna/llms/gemini_llm.py:48-49` @ `0172347b601e`, VERIFIED-OSS; the credential is one
#: entry named `GOOGLE`, `providers.md:105-109`). But D-478 puts the DASHBOARD copilot on the
#: Gemini OpenAI-compat `/chat/completions` surface directly — `google_openai_compat_base_url`
#: in `BUILDER_HOME` is the first place this product assembles a Gemini URL — so the leg's
#: obligation became the ordinary one every leg with a builder carries: exactly ONE frozen
#: literal (`GEMINI_BUILDER_SUFFIX` below, `_GOOGLE_OPENAI_COMPAT_SUFFIX` in the contract) may
#: name the host, and every other literal, handler or fixture is refused as before.
#:
#: IT IS THE FULL HOST AND NOT `.googleapis.com`, deliberately. `sheets.googleapis.com` and
#: `oauth2.googleapis.com` are the tenant's OWN destination on the Sheets leg and carry no
#: inference (see "NOT IN SCOPE" above); a suffix match would drag every CRM export into a
#: check about where a MODEL runs, which is how a guard gets turned off.
GEMINI_DIRECT_HOST: Final = "generativelanguage.googleapis.com"

#: The rest of the Gemini OpenAI-compat endpoint, exactly as `google_openai_compat_base_url`
#: assembles it (`_GOOGLE_OPENAI_COMPAT_SUFFIX` in `BUILDER_HOME`). Unlike the two suffixes
#: above it carries NO leading dot: nothing goes in front of the host — the builder takes no
#: argument and emits `https://` + this string whole — so the join is at the scheme, not at a
#: residency label. VERIFIED-LIVE: `POST https://<this>/chat/completions` with an OpenAI body
#: authenticated by `Authorization: Bearer <API_KEY>` (probed from this container, 27 Aug
#: 2026; native `:generateContent` 404'd — the compat path is the one that answers).
GEMINI_BUILDER_SUFFIX: Final = "generativelanguage.googleapis.com/v1beta/openai"

#: WOULD THE AZURE REGIONAL HOSTNAME RESTORE THE AST PROOF ON THAT LEG? Yes — and this flag
#: is the whole cost of adopting it, which is why the machinery is written now rather than
#: promised. `False`: naming `AZURE_REGIONAL_HOST_SUFFIX` in shipped code is a failure,
#: because D-410 ships the custom subdomain and a second endpoint form would be a second
#: residency story for one leg. `True`: it becomes the EXPECTED form and the label in front
#: of it is checked against the Azure leg's region — which is exactly the check the OpenAI
#: leg already runs on its own builder, so the branch is no longer hypothetical machinery.
#:
#: FLIPPING IT IS NOT THE WHOLE CHANGE and the comment says so rather than letting somebody
#: find out: gate 20d has to pass first (does v1 actually answer there), then
#: `azure_openai_base_url()` moves to the regional form, then this flag, then a decision-log
#: entry naming the gate as the evidence.
REGIONAL_HOST_ADOPTED: Final = False


# --- 0: WHICH POSTURE IS DECLARED, AND WHICH LEGS IT CONTAINS -----------------

#: The portability contract: where the declaration lives and where the builders live.
#: A separate name from `BUILDER_HOME` even though they are the same path today, because
#: they are two different obligations — a posture that moved its builders would still have
#: to declare itself here.
CONTRACT: Final = "packages/shared/src/calevate_shared/engine.py"

#: The `Final` that NAMES the posture, the record built from it that the RUNTIME reads, and
#: the tuple of leg constants that record carries.
DECLARATION_CONSTANT: Final = "DECLARED_POSTURE_NAME"
POSTURE_RECORD_CONSTANT: Final = "DECLARED_POSTURE"
LEGS_CONSTANT: Final = "DECLARED_LEGS"


@dataclass(frozen=True)
class LegSpec:
    """What ONE leg of a declared posture obliges the tree to look like.

    HELD HERE AND NEVER IMPORTED FROM THE CONTRACT, for `AZURE_REGION_INDIA`'s reason and
    more sharply. The contract states which legs are in force; this table states what each
    one costs. If the spec were imported, editing the declaration would edit the obligation
    in the same commit and the guard would agree with any tree it was shown — the "reads a
    flag and shrugs" failure this mechanism exists to avoid.

    **THE LEG IS THE UNIT AND THE POSTURE IS THE SET, WHICH IS WHAT CHANGED.** Every field
    below used to sit on `PostureSpec`, because there was one leg and its properties were the
    posture's. A client choosing their own provider makes each of them a per-leg fact, and
    the checks below are stated over `spec.legs` rather than over a vendor.
    """

    #: The name of the module `Final` in `CONTRACT` that declares this leg. Check 0 reads
    #: `DECLARED_LEGS` as a tuple of NAMES and compares it to these, in order, so a leg
    #: renamed or reordered in the contract is caught before any of its fields are read.
    constant: str
    #: Our closed vocabulary's member for this leg (`calevate_shared.engine.LlmProvider`).
    provider: str
    #: The region this leg PINS, or `None` for one making no regional claim.
    region: str | None
    #: The single frozen constant permitted to spell it. `None` means the guard requires that
    #: NO shipped constant spells a region FOR THIS LEG — and, across the whole table, that a
    #: constant holding a region no declared leg pins cannot sit in the tree at all.
    region_constant: str | None
    #: Is that region in the endpoint's AUTHORITY, where check 4 can read it off the
    #: builder's own return template? The single most consequential field here: `True` means
    #: a build proves the region and `delegated_gate` is legitimately `None`; `False` means
    #: the region is a property of an account and a human owes an attestation.
    region_in_host: bool
    #: Does the API address a DEPLOYMENT id the operator chose, rather than the model's own
    #: name? Cross-checked against the declared record because it is the field a reader would
    #: call cosmetic, and it is what decides whether `azure_openai_deployment` and
    #: `azure_openai_model` are two things or one (`engine.ModelBinding`).
    addresses_a_deployment: bool
    #: The ONE function permitted to build this leg's endpoint, and how many arguments it may
    #: take. Zero means a fixed vendor endpoint with no caller input — and with no caller
    #: input there is no hostile label to refuse, which is why the DNS-label refusal is
    #: required only above arity zero. `None`/`None` means this leg takes NO base URL from us
    #: at all, and then `builder_suffix` is `None` too and the host's literal budget is ZERO.
    builder: str | None
    builder_arity: int | None
    #: The one literal in the tree permitted to name this leg's host: only in `BUILDER_HOME`,
    #: only as a `Final`, and only this exact string. `None` on a builder-less leg.
    builder_suffix: str | None
    #: The watched host this leg may name at all. Every other watched host is refused on it.
    permitted_host: str
    #: The word(s) a `Settings` field name would carry if it named THIS leg's vendor. Read by
    #: `console_config_failures` through `KNOWN_VENDOR_TOKENS`, which is the union over every
    #: leg of every posture — never over the declared ones alone.
    #:
    #: STATED HERE RATHER THAN DERIVED FROM `provider` OR `permitted_host`, and both
    #: rejections are worth keeping. Splitting `provider` ("google") would miss
    #: `gemini_base_url`, because a vendor's PRODUCT name and its provider slug are routinely
    #: different words and a field is named after whichever one the engineer had in mind.
    #: Splitting `permitted_host` would yield "api", "com" and "googleapis" — tokens so broad
    #: that `sarvam_api_url` would be refused, which is the false positive that gets a name
    #: check deleted rather than obeyed.
    vendor_tokens: tuple[str, ...]
    #: `(constant, word)` that must share a line in `OPERATIONS_DOC`, naming the human gate
    #: that owns what this check cannot prove. `None` for a leg that delegates nothing —
    #: itself a claim the spec has to make out loud rather than by omission.
    delegated_gate: tuple[str, str] | None
    #: One line printed on every run saying what a green result does and does not mean here.
    warrant: str


#: The three legs the declared posture contains, as specs. Written out one per constant for
#: the same reason the contract writes them that way: check 0 compares SCALARS read from the
#: AST, and a leg inlined into a tuple would arrive as one opaque source string.
AZURE_LEG: Final = LegSpec(
    constant="AZURE_OPENAI_LEG",
    provider="azure_openai",
    region=AZURE_REGION_US,
    region_constant=REGION_CONSTANT,
    region_in_host=False,
    addresses_a_deployment=True,
    builder=BUILDER,
    builder_arity=1,
    builder_suffix=BUILDER_SUFFIX,
    permitted_host=AZURE_HOST_SUFFIX,
    vendor_tokens=("azure",),
    delegated_gate=(REGION_CONSTANT, "portal"),
    warrant=(
        "the region is spelled once and it is not an Indian one, no Settings field can "
        "carry a region, no Azure endpoint is constructible outside the one builder, and "
        "that builder has no region input — but NOTHING HERE CLAIMS INDIAN RESIDENCY ANY "
        "MORE (D-449), and the region itself is attested by a human in the portal rather "
        "than proved here"
    ),
)

AZURE_LEG_INDIA: Final = LegSpec(
    constant="AZURE_OPENAI_LEG",
    provider="azure_openai",
    region=AZURE_REGION_INDIA,
    region_constant=REGION_CONSTANT,
    region_in_host=False,
    addresses_a_deployment=True,
    builder=BUILDER,
    builder_arity=1,
    builder_suffix=BUILDER_SUFFIX,
    permitted_host=AZURE_HOST_SUFFIX,
    vendor_tokens=("azure",),
    delegated_gate=(REGION_CONSTANT, "portal"),
    warrant=(
        "the region is spelled once, no Settings field can carry one, no Azure endpoint is "
        "constructible outside the one builder, and that builder has no region input"
    ),
)

OPENAI_LEG: Final = LegSpec(
    constant="OPENAI_DIRECT_LEG",
    provider="openai",
    region=OPENAI_REGION_US,
    region_constant=OPENAI_REGION_CONSTANT,
    # THE ONE `True` IN THE TABLE, AND THE REASON THE LEG IS WORTH HAVING.
    region_in_host=True,
    addresses_a_deployment=False,
    builder=OPENAI_BUILDER,
    builder_arity=0,
    builder_suffix=OPENAI_BUILDER_SUFFIX,
    permitted_host=OPENAI_DIRECT_HOST,
    vendor_tokens=("openai",),
    # NOTHING IS DELEGATED, AND IT IS A CLAIM RATHER THAN AN OMISSION. The region is in the
    # authority and check 4 reads it off the builder, so there is no residency fact left for
    # a person to confirm. The one thing this file cannot see — the project entitlement
    # behind the regional host — fails LOUD at the vendor rather than silently falling back
    # to the global endpoint, so sending somebody to a console to re-observe an error the
    # first call would raise is not a gate, it is paperwork.
    delegated_gate=None,
    warrant=(
        "the region is IN THE HOSTNAME and this file proves it from the builder's own "
        "return template — one endpoint constructor, one literal naming it, one frozen "
        "constant holding the region, and NO human attestation owed. It is the only leg "
        "here whose residency claim a build can settle"
    ),
)

GOOGLE_LEG: Final = LegSpec(
    constant="GOOGLE_DIRECT_LEG",
    provider="google",
    # NO REGION, AND THE DISTINCTION FROM `OPENAI_LEG` IS WORTH THE SENTENCE. OpenAI HAS
    # regions and this posture pins one. Google's Developer API has none AT ALL — the region
    # is not unset, it is UNEXPRESSIBLE: `googleapis/python-genai@66807187f212`,
    # `google/genai/_api_client.py:681-682` raises `ValueError("Gemini API does not support
    # project/location.")` before a packet leaves the machine.
    region=None,
    region_constant=None,
    region_in_host=False,
    addresses_a_deployment=False,
    # ONE BUILDER, ARITY ZERO (D-478). The Developer API has no region to pass and the
    # copilot needs no base URL of its own, so `google_openai_compat_base_url()` takes NO
    # argument and returns `https://` + `GEMINI_BUILDER_SUFFIX` whole — modelled on
    # `OPENAI_LEG`'s arity-0 builder, minus its region (which Google's host cannot carry).
    # With arity 0 there is no hostile label to interpolate, so check 4 requires no DNS-label
    # raise here; the obligation is check 3's "exactly ONE literal names the host". See
    # `GEMINI_DIRECT_HOST`.
    builder=GEMINI_BUILDER,
    builder_arity=0,
    builder_suffix=GEMINI_BUILDER_SUFFIX,
    permitted_host=GEMINI_DIRECT_HOST,
    # BOTH WORDS, because the vendor and the product are named differently by different
    # people and a `Settings` field gets whichever the author had in mind.
    # `Settings.gemini_api_key` already exists in this tree (the AI Studio key no surface
    # opens), which is the evidence that "gemini" is the word people reach for here — and a
    # token list that had only "google" would let `gemini_base_url` through.
    vendor_tokens=("google", "gemini"),
    # NOTHING IS DELEGATED because there is no regional claim to confirm. ⚠ WHAT WOULD NEED A
    # GATE ON THE DAY ANY MODEL ON THIS LEG BECAME SELECTABLE is COMMERCIAL rather than
    # residency-shaped and is NOT invented here: Google's free tier states it uses submitted
    # prompts and responses to improve its products with human reviewers able to read them,
    # and only the PAID tier does not — so "is this key a paid key" is an OPERATIONS §2 gate
    # somebody has to write, together with the decision that makes a Gemini model selectable.
    delegated_gate=None,
    warrant=(
        "NO REGIONAL CLAIM IS MADE OR CHECKABLE on this leg, and unlike every other row "
        "here the vendor could not make one if it wanted to — the Developer API has no "
        "region in its host, none in its path and no field in which to ask for one. Since "
        "D-478 the copilot builds the OpenAI-compat endpoint here, so the rule is the "
        "ordinary one: EXACTLY ONE frozen literal may name the host — the builder's suffix "
        "in BUILDER_HOME — and every other literal, handler or fixture is refused"
    ),
)


@dataclass(frozen=True)
class PostureSpec:
    """What one declared posture obliges the tree to look like: a name and a set of legs.

    ADDING A POSTURE OR A LEG IS DELIBERATELY NOT FREE. A name this table does not know is a
    hard failure, so a new posture is a spec written HERE by somebody who has had to say, in
    advance and in one place, what would PROVE the tree is really in it — plus a
    decision-log entry. That is the reviewed change D-432 traded a thirty-file refactor for;
    it is not a smaller version of the same freeze.
    """

    name: str
    #: Ordered, and the order is compared: `DECLARED_LEGS` in the contract must name these
    #: constants in this sequence. Order carries no dispatch, but a tuple compared as a SET
    #: would let a reordering pass unread, and the first leg is the one every failure message
    #: names first.
    legs: tuple[LegSpec, ...]
    warrant: str

    def leg(self, provider: str) -> LegSpec | None:
        return next((one for one in self.legs if one.provider == provider), None)

    @property
    def permitted_hosts(self) -> frozenset[str]:
        return frozenset(one.permitted_host for one in self.legs)


#: EVERY POSTURE THIS TREE KNOWS HOW TO CHECK. Exactly one of them is declared.
#:
#: THE FOUR UNDECLARED ROWS ARE FIXTURES WITH A JOB, not history. A mechanism that can only
#: express the posture in force proves nothing about the posture in force, so
#: `tests/residency_posture_test.py` states the SHIPPED tree against every one of them and
#: watches this guard refuse. Between them they exercise every shape the checks can take: a
#: single-leg posture (does the guard notice a leg the tree HAS and the declaration does
#: not?), a posture pinning a DIFFERENT region on the same vendor (does it compare region
#: values, or only names?), and two whose builder does not exist in the contract at all.
#:
#: `us-azure-openai` AND `india-azure-openai` ARE THE TWO THIS PRODUCT HAS ACTUALLY BEEN IN.
#: Keeping them is what lets an auditor arriving with a superseded DPA ask "would this tree
#: pass as the posture that document describes" and get an answer rather than an opinion.
POSTURES: Final[dict[str, PostureSpec]] = {
    "multi-provider-byok": PostureSpec(
        name="multi-provider-byok",
        legs=(AZURE_LEG, OPENAI_LEG, GOOGLE_LEG),
        warrant=(
            "three legs, checked one at a time: each pinned region has exactly one frozen "
            "spelling, no Settings field can carry a region or any known vendor's endpoint, "
            "each leg's endpoint has exactly one constructor (the Google leg's, since D-478, "
            "being its arity-0 OpenAI-compat builder), no builder has a region input, and no "
            "declared leg is inert. ⚠ ONLY THE OPENAI LEG'S REGION IS PROVED HERE — Azure's "
            "is attested by a human in the portal (gates 20/20c) and Google's does not exist"
        ),
    ),
    "us-azure-openai": PostureSpec(
        name="us-azure-openai",
        legs=(AZURE_LEG,),
        warrant=(
            "one Azure leg, in East US 2 — the posture D-449 declared and D-454's provider "
            "choice superseded. NOTHING HERE CLAIMS INDIAN RESIDENCY: D-449 withdrew that "
            "claim rather than narrowing it"
        ),
    ),
    "india-azure-openai": PostureSpec(
        name="india-azure-openai",
        legs=(AZURE_LEG_INDIA,),
        warrant=(
            "one Azure leg, in South India — the posture D-449 WITHDREW. It is kept "
            "checkable so the question 'would this tree still pass as an Indian one' has an "
            "answer rather than an opinion"
        ),
    ),
    "openai-direct": PostureSpec(
        name="openai-direct",
        legs=(OPENAI_LEG,),
        warrant=(
            "one OpenAI-direct leg, pinned to the `us` residency endpoint and provable from "
            "the AST, with no Azure endpoint constructible anywhere in the tree"
        ),
    ),
    "google-direct": PostureSpec(
        name="google-direct",
        legs=(GOOGLE_LEG,),
        warrant=(
            "one Gemini Developer API leg, which makes NO REGIONAL CLAIM and cannot, with "
            "exactly one endpoint literal permitted — the OpenAI-compat builder's suffix "
            "(D-478) — and every other mention of the host refused"
        ),
    ),
}

#: EVERY leg any known posture declares, deduplicated by constant+region. Derived, never a
#: second list: the three sets below are all stated over it, and a leg added to a posture
#: with a host, a vendor word or a region missing from them would be a spec nothing enforces
#: — which is the exact defect D-453 found twice.
KNOWN_LEGS: Final[tuple[LegSpec, ...]] = tuple(
    dict.fromkeys(leg for spec in POSTURES.values() for leg in spec.legs)
)

#: EVERY region any known leg pins. It holds the WITHDRAWN region as well as the declared
#: ones, so check 1 can see a frozen constant the declaration has moved off — the one thing a
#: declared-region-only scan is structurally unable to notice.
KNOWN_REGIONS: Final[frozenset[str]] = frozenset(
    leg.region for leg in KNOWN_LEGS if leg.region is not None
)

#: EVERY model host any known leg may name. It feeds `WATCHED_HOSTS` (what the scan can SEE)
#: and `endpoint_failures` (what it refuses), so a leg cannot land with a `permitted_host` no
#: scan looks for and no clause judges.
KNOWN_POSTURE_HOSTS: Final[frozenset[str]] = frozenset(leg.permitted_host for leg in KNOWN_LEGS)

#: EVERY vendor word any known leg answers to. Read by `console_config_failures` and by
#: nothing else.
#:
#: **WHY THE UNION AND NOT THE DECLARED POSTURE'S OWN TOKENS.** The artefact a half-finished
#: posture move leaves behind is a `Settings` field for the vendor the tree has just LEFT —
#: `azure_openai_base_url` surviving a move to OpenAI direct, `openai_base_url` surviving a
#: move back — so a check that knew only the declared vendors would be blind to precisely the
#: case it most needs to catch, while still printing OK.
KNOWN_VENDOR_TOKENS: Final[frozenset[str]] = frozenset(
    token for leg in KNOWN_LEGS for token in leg.vendor_tokens
)

#: Where a URL literal can ship. `scripts/` is in for `sarvam_model_identifier_test`'s
#: reason: `scripts/pilot/` drives a real vendor account and reads like a fixture.
SCANNED_TREES: Final[tuple[str, ...]] = ("apps", "packages", "scripts")

#: Directory names never scanned. `tests`/`fixtures` are out because a test naming a
#: watched host is asserting ABOUT it — this file's own negative controls do exactly that.
SKIPPED_DIRS: Final[frozenset[str]] = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".next",
        ".turbo",
        "dist",
        "build",
        "coverage",
        "tests",
        "fixtures",
    }
)

#: Non-Python files the text half reads. Deliberately narrow: source and config, never
#: markdown or a lockfile.
TEXT_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".yaml", ".yml", ".sh", ".conf", ".sql"}
)

#: This file names the watched hosts because it watches them. Same shape as
#: `sarvam_model_identifier_test.CANONICAL_HOME`, and as narrow as that one.
#:
#: IT IS NOT A WHOLE-FILE SKIP, and the reason is worth keeping: the guard is edited by
#: whoever is relaxing the guard, so making it the one module where a hand-built endpoint
#: passes would put the single hole in the worst possible place.
SELF: Final = "scripts/check_model_residency.py"

#: `Settings` field-name fragments that would put a model region under console control.
#: Names, not values, because the dangerous field is the one whose value is EMPTY in the
#: tree and supplied from the store — see "what this check cannot see".
#:
#: THIS TUPLE NEEDS NO VENDOR AND THAT IS WHY IT IS THE MODEL THE ENDPOINT HALF WAS REBUILT
#: AGAINST. "region", "location", "residency", "datacenter" and "posture" mean the same thing
#: whoever is serving the model, so this check has never had a vendor to fall behind.
REGION_KNOB_FRAGMENTS: Final[tuple[str, ...]] = (
    "region",
    "location",
    "residency",
    "datacenter",
    # D-432: the DECLARED POSTURE is source, never configuration. A field called
    # `llm_posture` would invert the residency decision from a text box.
    "posture",
)

#: The ENDPOINT half of the same rule. A `Settings` field whose name pairs a vendor word
#: (`KNOWN_VENDOR_TOKENS`, derived from the leg table) with one of these is a model endpoint
#: in a text box. Check 3 says each leg's endpoint has exactly one constructor; a console
#: field called `azure_openai_base_url` would be a second one, made of a web form.
#:
#: STILL A PAIR AND NEVER THE WORDS ALONE, because plenty of settings are legitimately URLs
#: (`webhook_base_url`, `database_url`, `object_store_endpoint`) and banning the word would
#: be a check people route around by renaming.
#:
#: `base` IS IN THE LIST AND IS NOT PADDING. `AZURE_OPENAI_API_BASE` is the vendor's OWN name
#: for this value — one of the four flat credential entries the engine stores (D-417) — and
#: OpenAI's SDK reads `OPENAI_API_BASE`, so it is the likeliest spelling of the field this
#: check exists to refuse and it carries no `url`, `endpoint` or `host` at all.
ENDPOINT_KNOB_WORDS: Final[tuple[str, ...]] = ("url", "endpoint", "host", "base")


def _endpoint_knob_vendor(lowered: str) -> str | None:
    """Which vendor a `Settings` field name carries, LEFTMOST match first.

    A field is named `<vendor>_<product>_<thing>`, so the leftmost token is the vendor and
    `azure_openai_base_url` is Azure's rather than OpenAI's — which matters only for which
    builder the failure message points at, but a message that named the wrong constructor
    would send the reader to the wrong file. Longest wins on a tie so a vendor whose token
    is a prefix of another's cannot shadow it.
    """
    hits = [
        (lowered.find(token), -len(token), token)
        for token in KNOWN_VENDOR_TOKENS
        if token in lowered
    ]
    return min(hits)[2] if hits else None


@dataclass(frozen=True)
class DatedAllowance:
    """One file permitted to name one watched host, until a named piece of work removes it.

    A DEFERRAL, not an exemption, and the difference is `stale_allowances()`: the moment
    the file stops carrying the literal, this entry FAILS as stale and must be deleted.
    So the registry can only ever shrink, and only by the defect being fixed.
    """

    host: str
    recorded: str
    reason: str
    removed_by: str


#: EMPTY, and that is the state this registry is supposed to stay in. It held one entry
#: under D-127 (`apps/workers/extraction.py`, whose `GEMINI_CHAT_URL` named the AI Studio
#: Developer API); the work that closed it landed and `stale_allowances()` then REQUIRED
#: the entry to go, which is exactly the contract it was written under.
ALLOWANCES: Final[dict[str, DatedAllowance]] = {}


@dataclass(frozen=True)
class Reference:
    """One URL-shaped literal, with where it is, what it renders to, and whether it is
    frozen.

    `frozen` is carried because a leg's ONE permitted literal is permitted on three
    conditions together — the right file, the exact string, and `Final` — and a reader of
    `endpoint_failures` should not have to re-derive the third from somewhere else.
    """

    path: str
    line: int
    template: str
    frozen: bool = False

    def __str__(self) -> str:
        return f"{self.path}:{self.line}"


# --- reading the tree ---------------------------------------------------------


def _scanned_roots(roots: Iterable[Path] | None) -> tuple[Path, ...]:
    return tuple(REPO_ROOT / tree for tree in SCANNED_TREES) if roots is None else tuple(roots)


def _files(roots: Iterable[Path] | None, suffixes: frozenset[str]) -> Iterator[Path]:
    for root in _scanned_roots(roots):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if SKIPPED_DIRS & set(path.parts):
                continue
            yield path


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:  # a doctored tree under tmp_path — negative controls only
        return path.as_posix()


def _render(node: ast.JoinedStr) -> str:
    """An f-string as a template: literal pieces kept, each hole as `{<expression>}`.

    The hole's SOURCE is what makes checks 1 and 4 possible — and it is what lets the
    region-in-host check read `{OPENAI_DATA_RESIDENCY}` off a builder rather than reading
    `us` and having to trust it came from the constant.
    """
    parts: list[str] = []
    for piece in node.values:
        if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
            parts.append(piece.value)
        elif isinstance(piece, ast.FormattedValue):
            parts.append("{" + ast.unparse(piece.value) + "}")
    return "".join(parts)


def _docstrings(tree: ast.AST) -> set[int]:
    """Ids of Constant nodes that are docstrings — prose ABOUT the code, not a value.

    `check_docs_drift._docstring_constants` for the same reason, and this file needs it
    more than that one does: the whole subject here is a set of hosts that have to be
    NAMED in order to be watched. Without this the guard reports its own explanation as the
    offence, which teaches the next reader to delete the explanation. A `#` comment never
    reaches the AST at all, so only docstrings need excluding.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def _is_final(annotation: ast.expr) -> bool:
    """`Final`, `typing.Final`, `Final[str]`, `typing.Final[str]` — and nothing else.

    A plain `x: str = "eastus2"` is NOT frozen: `Final` is what mypy strict (a CI gate
    here) refuses to let anything rebind, so it is the annotation that turns a convention
    into an enforced one.
    """
    node: ast.expr = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    if isinstance(node, ast.Attribute):
        return node.attr == "Final"
    return isinstance(node, ast.Name) and node.id == "Final"


def _frozen_value_ids(tree: ast.AST) -> set[int]:
    """Ids of the Constant nodes that are a `Final` annotation's value.

    ONE definition, three readers (`loose_region_literals`, `frozen_region_constants` and
    the reference scan), because "is this literal frozen" answered two ways is a guard
    that disagrees with itself about its own exemption.
    """
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and node.value is not None and _is_final(node.annotation)
    }


def _frozen_strings(tree: ast.AST) -> dict[str, str]:
    """`NAME -> value` for every module-level `NAME: Final = "literal"` in one parsed file.

    Read by the region-in-host check, which has to resolve a builder's template holes far
    enough to see the hostname WITHOUT resolving the one hole whose provenance is the whole
    point — see `_resolve_holes`.
    """
    return {
        node.target.id: node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.value is not None
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and _is_final(node.annotation)
    }


#: The contract's own counterpart of `_host_definition`: a leg record has to NAME the host
#: it permits, in the same way and for the same reason this guard has to name the hosts it
#: watches. `PostureLeg(permitted_host="api.openai.com")` is a DECLARATION, and reporting it
#: as a hand-built endpoint would report the declaration as the offence — the failure mode
#: `_docstrings` exists to prevent, one level up.
#:
#: IT IS A STRUCTURAL CONDITION, NOT A STRING ONE, and that is what keeps the hole smaller
#: than `SELF`'s. `SELF` is exempted by exact string anywhere in the file, which is
#: acceptable there because the guard calls no vendor. `CONTRACT` is the file that HOLDS the
#: builders, so a by-string exemption would license `HOST = ".openai.azure.com"` followed by
#: an f-string over it — precisely the runtime-assembly blind spot this file admits to. Only
#: a literal standing in the `permitted_host=` position of a `PostureLeg(...)` call is
#: exempt, and nothing can be interpolated out of that position.
LEG_RECORD: Final = "PostureLeg"
LEG_HOST_KEYWORD: Final = "permitted_host"


def _leg_host_declarations(tree: ast.AST) -> set[int]:
    """Ids of the Constant nodes standing in `PostureLeg(permitted_host=...)`."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != LEG_RECORD:
            continue
        for keyword in node.keywords:
            if keyword.arg == LEG_HOST_KEYWORD and isinstance(keyword.value, ast.Constant):
                ids.add(id(keyword.value))
    return ids


def _templates(path: Path) -> Iterator[tuple[str, int, bool]]:
    """Every string template in one Python file — plain constants and rendered f-strings —
    with a flag saying whether it is a `Final`'s value.

    Three exclusions. Docstrings, per `_docstrings`. Constants nested INSIDE an f-string:
    the rendered whole already covers them, and yielding both would report one literal
    twice with the second report missing the context it is being judged on. And, in
    `CONTRACT` only, the leg records' own `permitted_host=` declarations — see
    `_leg_host_declarations`.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    frozen = _frozen_value_ids(tree)
    skipped = _docstrings(tree) | {
        id(inner)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for inner in ast.walk(node)
        if inner is not node
    }
    if _rel(path) == CONTRACT:
        skipped |= _leg_host_declarations(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            yield _render(node), node.lineno, False
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skipped
        ):
            yield node.value, node.lineno, id(node) in frozen


#: The hosts a literal has to mention before this check has an opinion about it: EVERY known
#: leg's own host, plus the one form that belongs to no leg.
#:
#: DERIVED RATHER THAN LISTED (and it was listed, which is how it fell a vendor behind the
#: table). A hand-written tuple beside the specs is the `KNOWN_REGIONS` failure class in a
#: second place: a leg whose host is missing from here has a `permitted_host` no scan ever
#: looks for, so `endpoint_failures` sees no reference, says nothing, and that leg's rule is
#: unenforced under the one posture it exists for. `AZURE_REGIONAL_HOST_SUFFIX` is appended
#: because it is not any leg's permitted host — it is the rejected-FOR-NOW form of one, and
#: its clause in `endpoint_failures` is what gives it a reason to be watched at all.
WATCHED_HOSTS: Final[tuple[str, ...]] = (*sorted(KNOWN_POSTURE_HOSTS), AZURE_REGIONAL_HOST_SUFFIX)


def _mentions_watched_host(text: str) -> bool:
    return any(host in text for host in WATCHED_HOSTS)


#: Endpoint hosts a `Settings` DEFAULT may not carry, ON TOP OF `WATCHED_HOSTS`.
#: Read by `console_config_failures` and by nothing else.
#:
#: TODAY THAT IS THE SARVAM CHAT HOST, and it is PROPHYLACTIC: no `Settings` field points
#: at it, so this clause guards a field nobody has written yet. It is here because
#: `managed_fields()` derives the console-editable set by SUBTRACTION, so a future
#: `sarvam_base_url` would be editable from a web form the day it was declared, with nothing
#: to notice. A text box that re-points THIS leg is worse than one that re-points a language
#: leg: Sarvam runs the first post-call extraction over the RAW transcript
#: (`GEMINI_EXTRACTION_DEFAULT is False`), so the payload is caller PII rather than redacted
#: prose.
#:
#: WHY IT IS NOT IN `WATCHED_HOSTS`: that tuple feeds `endpoint_failures`, where every
#: failure clause names its OWN host and its own remedy, so a host with no clause there
#: produces exactly zero findings. What adding it WOULD do is widen `SELF_DECLARATIONS` and
#: pull the host into the docs-prose machinery — cost with no check behind it.
SETTINGS_ENDPOINT_HOSTS: Final[tuple[str, ...]] = ("api.sarvam.ai",)


#: The strings `SELF` is allowed to spell: every watched host, plus each builder suffix it
#: grants the tree's exemptions FOR. Nothing is a URL and nothing carries a scheme — see
#: `_host_definition`. Derived, so a watched host this file could not declare would be this
#: file failing its own check rather than a silent hole.
SELF_DECLARATIONS: Final[tuple[str, ...]] = (
    *WATCHED_HOSTS,
    *sorted({leg.builder_suffix for leg in KNOWN_LEGS if leg.builder_suffix is not None}),
)


def _host_definition(template: str) -> bool:
    """Is this template the DECLARATION of a watched host rather than a use of one?

    Exactly the strings in `SELF_DECLARATIONS`, standing alone. `AZURE_HOST_SUFFIX: Final =
    ".openai.azure.com"` is the name this file watches things BY, and each builder suffix is
    the string it permits in `BUILDER_HOME`; judging either would report the watch as the
    violation.

    THE EXEMPTION IS A HANDFUL OF EXACT STRINGS, NOT A FILE — one per watched host plus one
    per builder suffix, derived so the count follows the leg table rather than a comment. Not
    one of them has a scheme or a host label in front of it, so none of them is an endpoint.

    Applied ONLY inside `SELF` (see that constant). Tree-wide it would be a real hole —
    `HOST = ".openai.azure.com"` followed by `f"https://x{HOST}/…"` is precisely the
    runtime-assembly shape "what this check cannot see" already admits to, and exempting the
    first half by name would turn an admitted blind spot into a supported idiom.
    """
    return template in SELF_DECLARATIONS


def _is_builder_suffix(reference: Reference, leg: LegSpec) -> bool:
    """The ONE literal in the tree allowed to name this leg's host: its builder's suffix.

    THREE CONDITIONS, ALL OF THEM, and each one is load bearing. The right FILE, because the
    exemption is for the constructor and not for the string. The exact STRING, because a
    suffix that had grown a query parameter or lost `/v1` would be a different endpoint
    wearing the exemption. And `Final`, because a rebindable module global is a knob.

    A leg with no builder has no suffix and therefore no exemption at all, which is the
    zero-literal rule stated as an early `False` rather than as a separate branch.
    """
    return (
        leg.builder_suffix is not None
        and reference.path == BUILDER_HOME
        and reference.template == leg.builder_suffix
        and reference.frozen
    )


def endpoint_references(roots: Iterable[Path] | None = None) -> list[Reference]:
    """Every literal in the tree that mentions a watched model host, Python and text alike."""
    references: list[Reference] = []
    for path in _files(roots, frozenset({".py"})):
        relative = _rel(path)
        for template, line, frozen in _templates(path):
            if relative == SELF and _host_definition(template):
                continue
            if _mentions_watched_host(template):
                references.append(Reference(relative, line, template, frozen))
    for path in _files(roots, TEXT_SUFFIXES):
        relative = _rel(path)
        for line_number, source_line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            if _mentions_watched_host(source_line):
                references.append(Reference(relative, line_number, source_line.strip()))
    return references


def template_count(roots: Iterable[Path] | None = None) -> int:
    """How many string templates the Python half parsed — check 5's first half."""
    return sum(1 for path in _files(roots, frozenset({".py"})) for _ in _templates(path))


def _final_string_constants(name: str, roots: Iterable[Path] | None = None) -> list[Reference]:
    """Every `<name>: Final = "<literal>"` in the tree, carrying its value as the template.

    A `Reference` rather than a bespoke tuple, because the thing being reported is exactly
    what `Reference` already reports — a path, a line and a string — and a second shape for
    it is a second `__str__` in the failure messages.
    """
    found: list[Reference] = []
    for path in _files(roots, frozenset({".py"})):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == name
                and node.value is not None
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and _is_final(node.annotation)
            ):
                found.append(Reference(_rel(path), node.lineno, node.value.value, frozen=True))
    return found


def declared_posture_name(
    found: Iterable[Reference] | None = None,
) -> tuple[str | None, list[str]]:
    """WHICH posture this tree declares, plus the failures that make the answer unusable.

    Read from the AST rather than imported, per this file's not-imported doctrine. The
    declaration must be a bare `Final` string literal in `CONTRACT` and there must be
    exactly one of it in the tree: a second one is a second answer to where this product's
    models run, which is the defect check 1 exists for one level down.
    """
    references = list(_final_string_constants(DECLARATION_CONSTANT) if found is None else found)
    if not references:
        return None, [
            f'no module declares `{DECLARATION_CONSTANT}: Final = "<posture>"`. Since D-432 '
            "the residency posture is a DECLARED name in source, not something a reader "
            "infers from thirty files agreeing with each other — without it this check does "
            "not know which body of rules it is enforcing, and a guard that does not know "
            "what it is checking has verified nothing."
        ]
    if len(references) > 1:
        return None, [
            f"`{DECLARATION_CONSTANT}` is declared in more than one place: "
            f"{[str(reference) for reference in references]}. There is one posture; a "
            "second declaration is a second answer, and nothing downstream would notice "
            "the day they stopped agreeing."
        ]
    only = references[0]
    if only.path != CONTRACT:
        return None, [
            f"`{DECLARATION_CONSTANT}` is declared in {only.path}, not in {CONTRACT}. The "
            "declaration belongs in the portability contract beside the builders it governs "
            "— that is where a reader checking residency looks, and where the runtime reads "
            "it from."
        ]
    return only.template, []


def _record_keywords(source: str, constant: str) -> dict[str, object] | None:
    """The keyword arguments of `<constant>: Final = SomeRecord(...)`.

    Constants come back as their VALUES; anything else comes back as its unparsed SOURCE,
    because "the region came from `AZURE_LOCATION`" and "the region came from a literal
    beside it" are the same string to a value check and are not the same fact — the
    identical argument `_render` makes for f-string holes, and the reason a leg's `region`
    can be compared to the NAME of the constant that must hold it.
    """
    for node in ast.walk(ast.parse(source)):
        if (
            not isinstance(node, ast.AnnAssign)
            or not isinstance(node.target, ast.Name)
            or node.target.id != constant
            or node.value is None
        ):
            continue
        if not _is_final(node.annotation) or not isinstance(node.value, ast.Call):
            return None
        fields: dict[str, object] = {}
        for keyword in node.value.keywords:
            if keyword.arg is None:
                continue
            value = keyword.value
            fields[keyword.arg] = (
                value.value if isinstance(value, ast.Constant) else ast.unparse(value)
            )
        return fields
    return None


def _tuple_elements(source: str, constant: str) -> list[str] | None:
    """The unparsed elements of `<constant>: Final = (A, B, C)`.

    SOURCE RATHER THAN VALUES, deliberately: what has to be compared is that the contract
    names THESE leg constants in THIS order, and resolving them to records would compare the
    fields twice while proving nothing about which names carry them.
    """
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == constant
            and node.value is not None
            and _is_final(node.annotation)
            and isinstance(node.value, ast.Tuple)
        ):
            return [ast.unparse(element) for element in node.value.elts]
    return None


def declaration_failures(
    name: str,
    record: dict[str, object] | None = None,
    spec: PostureSpec | None = None,
    source: str | None = None,
) -> list[str]:
    """Check 0: the declared name is one this guard knows, the posture RECORD says what that
    posture is supposed to say, and every LEG it names says what that leg is supposed to say.

    THIS IS THE HALF THAT FAILS WHEN THE DECLARATION DRIFTS FROM THE CODE. Checks 1-4 fail
    when the code drifts from the declaration; this fails when somebody edits the declaration
    to describe a tree that has not moved — the cheaper and therefore likelier direction,
    because it is one line.

    IT READS SCALARS, WHICH IS WHY EACH LEG IS ITS OWN MODULE `Final` IN THE CONTRACT. An
    inline tuple of records would arrive here as one opaque source string and this whole
    check would degrade to string matching against a rendering nobody controls.
    """
    known = POSTURES.get(name) if spec is None else spec
    if known is None:
        return [
            f"the declared residency posture {name!r} is not one this check knows (known: "
            f"{sorted(POSTURES)}). A posture arrives as a `PostureSpec` in {SELF} saying "
            "what would PROVE the tree is really in it, plus a decision-log entry — never "
            "as a name the guard shrugs at. An unknown name is the one input that would let "
            "this whole mechanism be bypassed with a single word."
        ]
    text = (REPO_ROOT / CONTRACT).read_text(encoding="utf-8") if source is None else source
    fields = _record_keywords(text, POSTURE_RECORD_CONSTANT) if record is None else record
    if fields is None:
        return [
            f"{CONTRACT} declares no `{POSTURE_RECORD_CONSTANT}: Final = ResidencyPosture("
            "...)` this check can read. The name alone is not the posture — the record is "
            "what the RUNTIME reads (`agents.service.in_call_llm`, `engine.bind_model`), so "
            "a name with no record beside it is a declaration nothing obeys."
        ]
    failures: list[str] = []
    for field, want in sorted({"name": DECLARATION_CONSTANT, "legs": LEGS_CONSTANT}.items()):
        got = fields.get(field, "<absent>")
        if got != want:
            failures.append(
                f"{CONTRACT}'s `{POSTURE_RECORD_CONSTANT}` declares {field}={got!r} but "
                f"posture {name!r} requires {want!r}. The declaration and the code are in "
                f"two different postures at once. Fix whichever is wrong DELIBERATELY: if "
                f"the tree really moved, the `PostureSpec` in {SELF} and a decision-log "
                "entry move with it; if only this line moved, it is a residency change made "
                "by accident."
            )
    if record is not None:
        # A doctored record is a fixture for the two fields above; reading the real leg
        # constants underneath it would judge a tree the fixture is not describing.
        return failures
    return failures + _leg_declaration_failures(known, text)


def _leg_declaration_failures(spec: PostureSpec, source: str) -> list[str]:
    """The leg half of check 0: `DECLARED_LEGS` names these constants in this order, and each
    one's `PostureLeg(...)` keywords say what the spec requires."""
    declared = _tuple_elements(source, LEGS_CONSTANT)
    if declared is None:
        return [
            f"{CONTRACT} declares no `{LEGS_CONSTANT}: Final = (...)` this check can read. "
            "A posture is a name plus a closed set of legs; with no tuple to read, the name "
            "describes nothing and every per-leg check below has no subject."
        ]
    expected_constants = [leg.constant for leg in spec.legs]
    if declared != expected_constants:
        return [
            f"{CONTRACT}'s `{LEGS_CONSTANT}` is {declared}, but posture {spec.name!r} "
            f"requires {expected_constants} in that order. A leg the declaration adds is a "
            "vendor this product may send a client's caller's words to; a leg it drops is "
            "one the tree still builds endpoints for. Both are decision-log changes."
        ]
    failures: list[str] = []
    for leg in spec.legs:
        fields = _record_keywords(source, leg.constant)
        if fields is None:
            failures.append(
                f"{CONTRACT} declares no `{leg.constant}: Final = PostureLeg(...)` this "
                f"check can read, though `{LEGS_CONSTANT}` names it. Each leg is its own "
                "module constant precisely so this comparison reads SCALARS — an inline "
                "record would arrive as one opaque source string."
            )
            continue
        expected: dict[str, object] = {
            "provider": leg.provider,
            "region": leg.region_constant,
            "region_in_host": leg.region_in_host,
            "addresses_a_deployment": leg.addresses_a_deployment,
            "builder": leg.builder,
            "builder_arity": leg.builder_arity,
            "permitted_host": leg.permitted_host,
        }
        for field, want in sorted(expected.items()):
            got = fields.get(field, "<absent>")
            if got != want:
                failures.append(
                    f"{CONTRACT}'s `{leg.constant}` declares {field}={got!r} but posture "
                    f"{spec.name!r} requires {want!r} on the {leg.provider!r} leg. The "
                    "declaration and the code are in two different postures at once."
                )
    return failures


def declared_spec() -> PostureSpec:
    """The spec every check below defaults to.

    RAISES rather than falling back to a default posture, and the absence of a fallback is
    the point: "which posture is this tree in" has no safe default answer, and a guard that
    invented one would enforce a posture nobody declared. `main()` resolves the declaration
    FIRST and returns before any check runs, so in the shipped path this cannot fire; it is
    reachable only by calling a check directly against a tree whose declaration is broken.
    """
    name, failures = declared_posture_name()
    if name is None or name not in POSTURES:
        raise RuntimeError(
            "the residency posture cannot be resolved, so no check below knows what it is "
            f"enforcing: {failures or [f'unknown posture {name!r}']}"
        )
    return POSTURES[name]


# --- 1: one spelling of each pinned region ------------------------------------


def frozen_region_constants(roots: Iterable[Path] | None = None) -> dict[str, tuple[str, str]]:
    """`NAME: Final = "<any region in KNOWN_REGIONS>"` — name to (file, region held).

    IT SCANS FOR EVERY KNOWN REGION AND CARRIES THE ONE IT FOUND. A scan for the DECLARED
    regions alone would report a leftover `AZURE_LOCATION: Final = "southindia"` as no region
    constant at all, and every check downstream would agree the tree spells its regions once.
    Carrying the value is what lets `single_spelling_failures` say WHICH region is frozen and
    refuse it against the ones the declaration pins.
    """
    constants: dict[str, tuple[str, str]] = {}
    for path in _files(roots, frozenset({".py"})):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.value is not None
                and isinstance(node.value, ast.Constant)
                and node.value.value in KNOWN_REGIONS
                and _is_final(node.annotation)
            ):
                constants[node.target.id] = (_rel(path), node.value.value)
    return constants


def loose_region_literals(roots: Iterable[Path] | None = None) -> list[str]:
    """Check 1, first half: a bare region literal that is NOT a `Final` constant's value.

    The shape this is really aimed at is not a second constant — it is
    `def __init__(self, location: str = "eastus2")`, a default argument that reads like a pin
    and is one keyword away from not being one.

    STATED OVER `KNOWN_REGIONS` RATHER THAN OVER THE DECLARED ONES, because the loose literal
    a posture move leaves behind spells the region the tree just left, and a scan for the
    region it just arrived at would never look at it.
    """
    failures: list[str] = []
    for path in _files(roots, frozenset({".py"})):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        frozen = _frozen_value_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and node.value in KNOWN_REGIONS
                and id(node) not in frozen
            ):
                failures.append(
                    f"{_rel(path)}:{node.lineno} spells {node.value!r} somewhere other "
                    "than a `Final` constant's value. Each leg's region is pinned so it "
                    "cannot be varied per call site or per caller — reference the constant "
                    f"that holds it ({sorted(_region_constants())}). On the Azure leg this "
                    "matters MORE than it did under Vertex, not less: the endpoint no "
                    "longer carries the region, so 'there is one spelling of it' is the "
                    "whole of what code can still say."
                )
    return failures


def _region_constants() -> frozenset[str]:
    """Every constant name any known leg permits to hold a region."""
    return frozenset(leg.region_constant for leg in KNOWN_LEGS if leg.region_constant is not None)


def single_spelling_failures(
    constants: Mapping[str, tuple[str, str]] | None = None, spec: PostureSpec | None = None
) -> list[str]:
    """Check 1, second half: outside this guard, each declared leg's region constant is the
    ONLY frozen constant holding that leg's region, and nothing freezes a region no declared
    leg pins.

    STRICTER THAN THE VERTEX GUARD, WHICH ACCEPTED ANY `Final`, and the strictness is bought
    by the weakening. When the region appeared in every model URL, a second constant holding
    the same string was untidy and harmless — checks on the URLs would have caught a
    divergence the moment one was used. On the Azure leg there are no such URLs. A second
    constant is a second answer to "which region is this product in", with nothing downstream
    able to notice when the two stop agreeing.

    IT JUDGES THE VALUE AND NOT ONLY THE NAME. `AZURE_LOCATION: Final = "southindia"` under a
    declaration that says otherwise is exactly the tree a half-finished posture move leaves,
    and it satisfies every name-shaped check ever written here.

    `SELF` is excluded because this file spells every known region as its own canaries, which
    is the not-imported doctrine and not a second decision.
    """
    posture = declared_spec() if spec is None else spec
    found = frozen_region_constants() if constants is None else constants
    shipped = {name: where for name, where in found.items() if where[0] != SELF}
    expected = {
        leg.region_constant: (BUILDER_HOME, leg.region)
        for leg in posture.legs
        if leg.region_constant is not None and leg.region is not None
    }
    if shipped == expected:
        return []
    failures: list[str] = []
    for constant, want in sorted(expected.items()):
        got = shipped.get(constant)
        if got is None:
            failures.append(
                f"no shipped module defines `{constant}: Final = {want[1]!r}`. On this leg "
                "the region is a residency fact this tree states; if it has moved, point "
                f"the `LegSpec` in {SELF} at its new home deliberately, because every other "
                "check here reads it."
            )
        elif got != want:
            # THE WRONG-REGION ARM IS SEPARATE FROM THE TWO-SPELLINGS ARM ON PURPOSE. They
            # are different defects with different fixes and, more to the point, different
            # consequences: two constants holding the SAME region is a tidiness failure that
            # will one day become a contradiction, while ONE constant holding a region the
            # declaration does not pin is the contradiction already.
            failures.append(
                f"posture {posture.name!r} pins {want[1]!r} on its {constant} leg, but "
                f"shipped code freezes {got[1]!r} in {got[0]}. This is what a half-finished "
                "posture move looks like — the declaration has moved and a constant has "
                "not, or the reverse. The tree is asserting two regions at once and only "
                "one of them can be where the deployment is."
            )
    stray = {name: where for name, where in shipped.items() if name not in expected}
    if stray:
        failures.append(
            f"posture {posture.name!r} permits region constants {sorted(expected) or 'none'}, "
            f"but shipped code also freezes {sorted(stray.items())}. A region constant no "
            "declared leg pins is a promise nothing keeps — either the leg that needs it is "
            "missing from the declaration, or the constant is a leftover. Delete it, or "
            "declare the posture that actually holds. (This is also the arm that catches a "
            "SECOND spelling of a region a leg does pin: `AZURE_REGION_FOR_BILLING` beside "
            "`AZURE_LOCATION` is two answers to where this product's models run, and — "
            "unlike under D-127 — no URL in this tree would reveal the day they diverge.)"
        )
    # NO CATCH-ALL ARM BELOW, and its absence is deliberate rather than an oversight. The
    # three arms above are exhaustive over `shipped != expected`: a key expected and absent,
    # a key expected with a different value, and a key nobody expected. A fourth "something
    # else is wrong" branch could not be reached by any input, and an unreachable defensive
    # arm is a suppression the coverage ratchet counts and a reader cannot evaluate.
    return failures


# --- 3: no endpoint outside each leg's builder --------------------------------


def _labelled_hosts(template: str, suffix: str) -> Iterator[str]:
    """Each occurrence of `suffix`, with the label text immediately before it.

    The prefix is read by walking back to the URL's authority boundary rather than by a
    regex, because a resource name may itself contain hyphens and every regex that gets
    that right also matches half of something else.
    """
    index = template.find(suffix)
    while index != -1:
        start = index
        while start > 0 and template[start - 1] not in "/@ \t\"'\\":
            start -= 1
        yield template[start:index]
        index = template.find(suffix, index + 1)


def _region_ok(token: str, frozen: Mapping[str, tuple[str, str]], region: str | None) -> bool:
    """Does this label in a hostname name the region the leg pins?

    IT COMPARES THE CONSTANT'S VALUE, NOT MERELY THAT THE NAME IS FROZEN, and that is a real
    distinction rather than pedantry: `frozen` holds every constant spelling any KNOWN
    region, so `{AZURE_LOCATION}` resolving to a frozen constant says nothing about WHICH
    region it resolves to. Accepting a name because it is frozen would wave through exactly
    the leftover-constant tree check 1 exists to refuse.

    `region is None` (a leg making no regional claim) accepts nothing: there is no region for
    a hostname to be carrying, so a regional label under such a leg is a claim the
    declaration does not make.
    """
    if region is None:
        return False
    if token == region:
        return True
    if token.startswith("{") and token.endswith("}"):
        held = frozen.get(token[1:-1].strip())
        return held is not None and held[1] == region
    return False


def endpoint_failures(
    references: Iterable[Reference],
    frozen: Mapping[str, tuple[str, str]] | None = None,
    allowances: Mapping[str, DatedAllowance] | None = None,
    spec: PostureSpec | None = None,
) -> list[str]:
    """Check 3 over the literals the scan found, plus the host that belongs to no leg.

    `frozen` and `allowances` are injectable for the reason
    `check_redaction_exposure.check`'s exemptions are: a guardrail whose exemptions cannot be
    taken away in a test is a guardrail nobody can prove still sees anything.
    """
    posture = declared_spec() if spec is None else spec
    constants = frozen_region_constants() if frozen is None else frozen
    permitted = ALLOWANCES if allowances is None else allowances
    failures: list[str] = []

    for reference in references:
        allowed = permitted.get(reference.path)

        # THE HOST THAT BELONGS TO NO LEG. Azure's regional form is not a residency defect —
        # it is the STRONGER form, and refusing it for the same reason as a hand-built
        # subdomain URL would teach the next reader that a region in a hostname is somehow
        # suspect. What makes it a failure today is that one leg ships ONE endpoint form.
        for label in _labelled_hosts(reference.template, AZURE_REGIONAL_HOST_SUFFIX):
            if allowed is not None and allowed.host == AZURE_REGIONAL_HOST_SUFFIX:
                continue
            azure = posture.leg("azure_openai")
            if not REGIONAL_HOST_ADOPTED:
                failures.append(
                    f"{reference} names Azure's REGIONAL host form "
                    f"({label or '{region}'}{AZURE_REGIONAL_HOST_SUFFIX}). D-410 ships the "
                    f"custom-subdomain form ({BUILDER}()) and records this one as "
                    "rejected-FOR-NOW: the OpenAI-compatible v1 surface is documented only "
                    "on the custom subdomain. It is not rejected on residency — it would "
                    "IMPROVE residency by putting the region back in the URL, which is "
                    f"exactly what {OPENAI_BUILDER}() already does on its own leg — so the "
                    "way in is OPERATIONS §2 gate 20d, then the builder, then "
                    "`REGIONAL_HOST_ADOPTED`, then a decision-log entry. Two endpoint forms "
                    "at once is two residency stories for one leg."
                )
                continue
            if azure is None:
                failures.append(
                    f"{reference} names Azure's regional host form, but posture "
                    f"{posture.name!r} declares no Azure leg at all."
                )
                continue
            if not _region_ok(label, constants, azure.region):
                failures.append(
                    f"{reference} sends model traffic to region {label!r}. The Azure leg of "
                    f"posture {posture.name!r} permits {azure.region!r} only — literally, or "
                    f"through a `Final` constant holding THAT VALUE (known: "
                    f"{sorted(constants) or 'none'}). This is a residency change, not a "
                    "config change."
                )

        # THE PER-LEG RULES. Every watched host in this literal is either some DECLARED leg's
        # — in which case that leg's own budget applies — or it belongs to no declared leg,
        # which is the wrong-vendor refusal.
        for host in sorted(KNOWN_POSTURE_HOSTS):
            if host not in reference.template:
                continue
            if allowed is not None and allowed.host == host:
                continue
            leg = next((one for one in posture.legs if one.permitted_host == host), None)
            if leg is None:
                failures.append(
                    f"{reference} names {host} — a model host this guard knows as some "
                    f"leg's, and not one posture {posture.name!r} declares (it declares "
                    f"{sorted(posture.permitted_hosts)}). Either the tree has not been "
                    "moved to the posture it declares, or the declaration was edited "
                    "without the tree. Both are residency changes; neither is a tidy-up."
                )
                continue
            failures.extend(_leg_literal_failures(reference, leg, constants))

    return failures


def _leg_literal_failures(
    reference: Reference, leg: LegSpec, constants: Mapping[str, tuple[str, str]]
) -> list[str]:
    """What ONE declared leg permits a literal naming its host to be.

    Three outcomes, and the first is the only quiet one: the builder's own frozen suffix in
    `BUILDER_HOME`; a leg with NO builder, where the budget is zero and every literal is a
    failure; and everything else, which is an endpoint built by hand.
    """
    if _is_builder_suffix(reference, leg):
        return []
    if leg.builder is None:
        # THE ZERO-LITERAL RULE, WHICH IS STRONGER THAN EVERY OTHER LEG'S. It reads as an
        # absence and is the opposite: this leg takes no base URL from us, so a literal
        # naming its host is not a second constructor, it is a first one — for an endpoint
        # the engine would never read.
        return [
            f"{reference} names {leg.permitted_host}, and the {leg.provider!r} leg permits "
            "ZERO literals naming its host anywhere in this tree — including in "
            f"{BUILDER_HOME}. It has no builder because the engine builds its own client "
            "from a single API key and never reads a base URL of ours, so this string "
            "cannot be an endpoint anybody sends: it is either dead configuration or a "
            "second, undeclared way to reach the vendor. If this leg is meant to take an "
            f"endpoint, that is a `builder` and a `builder_suffix` in the `LegSpec` in "
            f"{SELF}, in the contract, and a decision-log entry — together."
        ]
    if leg.region_in_host and not any(
        _region_ok(label.removesuffix("."), constants, leg.region)
        for label in _labelled_hosts(reference.template, leg.permitted_host)
    ):
        # A LITERAL ON A REGION-PINNING LEG THAT DOES NOT CARRY THE REGION. On this leg the
        # difference between the pinned endpoint and the vendor's GLOBAL one is a label, and
        # the global one makes no regional claim at all — so it earns its own sentence rather
        # than being lumped in with "built by hand".
        return [
            f"{reference} names {leg.permitted_host} without the {leg.region!r} residency "
            f"label in front of it. On the {leg.provider!r} leg that is the vendor's GLOBAL "
            "endpoint — inference wherever they have capacity, which is not a regional "
            f"claim — and it is one label away from the pinned one. {leg.builder}() is the "
            f"only thing that spells it, from `{leg.region_constant}`."
        ]
    hostile = (
        " This is not tidiness: the caller-supplied label lands at the FRONT of the "
        f"authority, so a hand-written f-string is where `https://evil.example/x"
        f"{leg.permitted_host}` comes from, and the builder is the only thing that refuses it."
        if leg.builder_arity
        else (
            f" {leg.builder}() takes no caller input, so there is no hostile label to refuse "
            "here — what a second literal costs is that the endpoint stops having one "
            "definition to read."
        )
    )
    return [
        f"{reference} builds a {leg.provider} model endpoint by hand. Exactly ONE literal in "
        f"this tree may name {leg.permitted_host} — the `Final` suffix "
        f"{leg.builder_suffix!r} in {BUILDER_HOME}, which {leg.builder}() assembles — and "
        "every other caller goes through that function." + hostile + " It is also what "
        "check 4 rests on — a second constructor is a constructor nothing here has read."
    ]


def stale_allowances(
    references: Iterable[Reference], allowances: Mapping[str, DatedAllowance] | None = None
) -> list[str]:
    """A dated allowance whose defect is gone is a hole with a comment on it."""
    permitted = ALLOWANCES if allowances is None else allowances
    found = list(references)
    failures: list[str] = []
    for path, allowance in sorted(permitted.items()):
        if any(
            reference.path == path and allowance.host in reference.template for reference in found
        ):
            continue
        failures.append(
            f"ALLOWANCES entry {path} no longer carries {allowance.host} — the work that "
            f"closes it has landed ({allowance.removed_by}). DELETE the entry: an "
            "allowance that outlives its defect is how the next global endpoint ships "
            "unnoticed."
        )
    return failures


# --- 2: the console can never decide this -------------------------------------


def live_settings() -> tuple[dict[str, object], set[str]]:
    """The real `Settings` fields (name to default) and the console-editable subset.

    Split out so `console_config_failures` can be pointed at a doctored pair in a test:
    a check whose subject cannot be faked is a check nobody can watch fail.
    """
    from apps.api.core.platform_config import managed_fields
    from calevate_shared.config import Settings

    return (
        {name: field.default for name, field in Settings.model_fields.items()},
        set(managed_fields()),
    )


def console_config_failures(
    fields: Mapping[str, object] | None = None,
    managed: Iterable[str] | None = None,
    spec: PostureSpec | None = None,
) -> list[str]:
    """No `Settings` field may carry a model region or a hand-typed model endpoint.

    Asserted against the WHOLE `Settings` model and not only against `managed_fields()`,
    because the console's editable set is DERIVED (`Settings.model_fields` minus the
    bootstrap keys minus credential-shaped names) — a new field is managed by default, so
    a check that read only the derived set would be reporting on a symptom.

    THIS IS THE CHECK D-410 DID NOT WEAKEN. It never depended on the region appearing in a
    URL; it depends on the region having nowhere console-editable to live, which is as true
    of three legs as it was of one.

    **IT IS ALSO THE CLAUSE THE CLIENT DPA POINTS AT.** `apps/web/src/lib/legal/dpa.ts`
    warrants that "no configuration setting may carry a region, an endpoint or a posture";
    the region and posture halves have always been vendor-neutral, and the endpoint half is
    stated over `KNOWN_VENDOR_TOKENS` — deliberately NOT over the declared legs alone,
    because the field a half-finished migration leaves behind names the vendor the tree has
    just left.
    """
    posture = declared_spec() if spec is None else spec
    if fields is None or managed is None:
        live_fields, live_managed = live_settings()
        fields = live_fields if fields is None else fields
        managed = live_managed if managed is None else managed
    editable = set(managed)
    pinning = [leg for leg in posture.legs if leg.region_constant is not None]
    failures: list[str] = []
    for name, default in sorted(fields.items()):
        lowered = name.lower()
        where = "console-editable" if name in editable else "declared"
        if any(fragment in lowered for fragment in REGION_KNOB_FRAGMENTS):
            remedy = (
                "each leg's region is a frozen constant "
                f"({sorted(leg.region_constant for leg in pinning)}) precisely so it cannot "
                "be changed from a web form at 3am — the same rule D-95 §4 applies to "
                "APP_ENV. Move it to a `Final` constant in code."
                if pinning
                else (
                    f"posture {posture.name!r} pins NO region on any leg, so there is no "
                    "constant to move this into — the field should not exist. A console "
                    "knob naming a region under a posture that makes no regional claim is a "
                    "promise the declaration does not make."
                )
            )
            failures.append(
                f"Settings.{name} is {where} and its name says it holds a model region. " + remedy
            )
            continue
        vendor = _endpoint_knob_vendor(lowered)
        word = next((fragment for fragment in ENDPOINT_KNOB_WORDS if fragment in lowered), None)
        if vendor is not None and word is not None:
            builders = sorted(
                {
                    leg.builder or "no builder at all — that leg takes no base URL"
                    for leg in KNOWN_LEGS
                    if vendor in leg.vendor_tokens
                }
            )
            failures.append(
                f"Settings.{name} is {where} and its name pairs the model vendor "
                f"{vendor!r} with the endpoint word {word!r} — it holds a model ENDPOINT, "
                f"in a text box. That vendor's endpoint has exactly one constructor in "
                f"this tree ({', '.join(f'{one}()' for one in builders)}), and a console "
                "field beside it is a second one — check 3 exists to make sure there is "
                "only ever the one. Store the vendor's ACCOUNT-shaped inputs (a resource "
                "id, a key, a deployment name) and let the builder assemble the URL. "
                "THE VENDOR DOES NOT HAVE TO BE A DECLARED ONE and this is checked "
                f"against every known leg's ({sorted(KNOWN_VENDOR_TOKENS)}): the field a "
                "half-finished posture move leaves behind names the vendor the tree just "
                "LEFT, so a check that knew only the declared vendors would be blind to "
                "exactly the case it exists for."
            )
            continue
        if isinstance(default, str) and any(host in default for host in SETTINGS_ENDPOINT_HOSTS):
            # BEFORE the watched-host clause and with its own `continue`, so the two never
            # report one field twice.
            failures.append(
                f"Settings.{name} defaults to a model endpoint ({default!r}) on the leg "
                "that reads the RAW transcript. `managed_fields()` derives the "
                "console-editable set by subtraction, so this field is a web form that "
                "re-points caller PII at a host of the operator's choosing. Keep the "
                "endpoint a `Final` constant in `apps/workers/extraction.py`."
            )
            continue
        if isinstance(default, str) and (
            _mentions_watched_host(default) or default in KNOWN_REGIONS
        ):
            failures.append(
                f"Settings.{name} defaults to a model endpoint or a region ({default!r}). "
                "Whatever its name says, it is the residency knob."
            )
    return failures


# --- 4: no builder can emit a region other than its leg's ---------------------


def _is_pattern_guarded_raise(node: ast.AST, arguments: set[str]) -> bool:
    """An `if` that raises, guarded by a `fullmatch`/`match` call on the builder's argument.

    WHAT THIS IS DISTINGUISHING, because "the builder raises" sounds like enough and is
    not. `if not resource: raise` is a presence check and accepts `"evil.example/x"` — the
    one input the refusal exists for. `if not _RE.fullmatch(resource): raise` is a SHAPE
    check. Both contain an `ast.Raise`, so the coarse check passes either, and the
    difference is the whole security property.

    It still cannot prove the predicate can FIRE — see `leg_builder_failures`.
    """
    if not isinstance(node, ast.If):
        return False
    if not any(isinstance(inner, ast.Raise) for inner in ast.walk(node)):
        return False
    for call in ast.walk(node.test):
        if not isinstance(call, ast.Call):
            continue
        function = call.func
        name = function.attr if isinstance(function, ast.Attribute) else None
        if name not in ("fullmatch", "match"):
            continue
        if any(
            isinstance(argument, ast.Name) and argument.id in arguments for argument in call.args
        ):
            return True
    return False


def _resolve_holes(template: str, values: Mapping[str, str], keep: Iterable[str]) -> str:
    """Substitute `{NAME}` holes with the `Final` values they name, EXCEPT the ones in `keep`.

    THE EXCEPTION IS THE WHOLE POINT. A builder's return template is
    `https://{OPENAI_DATA_RESIDENCY}{_OPENAI_ENDPOINT_SUFFIX}` — the hostname is inside the
    second constant, so nothing can be read off the template until it is resolved, and
    resolving BOTH would yield `https://us.api.openai.com/v1`, which proves the string and
    loses the provenance. Keeping the region hole unresolved leaves
    `https://{OPENAI_DATA_RESIDENCY}.api.openai.com/v1`, where `_region_ok` can do what it
    was written for: check that the label came from the constant that must hold it.
    """
    protected = set(keep)
    resolved = template
    for name, value in values.items():
        if name in protected:
            continue
        resolved = resolved.replace("{" + name + "}", value)
    return resolved


def builder_failures(source: str | None = None, spec: PostureSpec | None = None) -> list[str]:
    """Check 4 over every declared leg that has a builder."""
    posture = declared_spec() if spec is None else spec
    text = (REPO_ROOT / BUILDER_HOME).read_text(encoding="utf-8") if source is None else source
    return [failure for leg in posture.legs for failure in leg_builder_failures(leg, text)]


def leg_builder_failures(leg: LegSpec, source: str) -> list[str]:
    """Check 4, read off ONE leg's builder.

    THE CHECK THAT REPLACED "the region in the URL is Mumbai", and on two of the three legs it
    answers a different question because those vendors only permit a different question. Where
    the region is not in the URL, what is judged is that there is no region INPUT: the arity
    the leg permits, no region-shaped parameter, interpolation of nothing but that argument
    and module `Final`s, and a refusal of anything that is not a single DNS label. A builder
    shaped like that has no OTHER region to emit — a structural argument rather than an
    evidential one, and saying which of the two you have is the whole point of this file.

    **WHERE THE REGION *IS* IN THE URL, THE EVIDENTIAL ANSWER IS BACK.** On a leg with
    `region_in_host`, this reads the label immediately before the permitted host out of the
    builder's own return template and requires it to be the `Final` holding that leg's
    region. That is the check D-127 had and D-410 lost, running again — on the OpenAI leg
    today, and on the Azure leg the day gate 20d flips `REGIONAL_HOST_ADOPTED`.

    ⚠ **THE DNS-LABEL HALF IS A SHAPE CHECK AND CANNOT PROVE THE REFUSAL IS EFFECTIVE**,
    which was learned by sabotaging it rather than by reasoning about it. A guard rewritten to
    `if False and not _RE.fullmatch(resource)` keeps the raise and the pattern call and
    refuses nothing. THE BEHAVIOUR IS PROVED ELSEWHERE AND DELIBERATELY:
    `tests/in_call_llm_provider_test.py` CALLS the builder with the attack strings and
    requires a `ValueError`.
    """
    if leg.builder is None:
        # A LEG WITH NO BUILDER HAS NOTHING FOR THIS CHECK TO READ, and that is not a gap:
        # its whole obligation is the zero-literal rule in check 3. Demanding a function here
        # would be demanding an endpoint the engine would never read.
        return []
    tree = ast.parse(source)
    frozen_values = _frozen_strings(tree)
    frozen_names = set(frozen_values)
    builder = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == leg.builder
        ),
        None,
    )
    if builder is None:
        return [
            f"{BUILDER_HOME} defines no `{leg.builder}()`. It is the ONE constructor the "
            f"{leg.provider!r} leg permits for a model endpoint, and the thing check 3's "
            "single exemption is granted for; if it has been renamed or moved, this file "
            "has to be pointed at it deliberately, because a guard that cannot find its "
            "subject has verified nothing."
        ]

    failures: list[str] = []
    arguments = builder.args
    positional = [argument.arg for argument in (*arguments.posonlyargs, *arguments.args)]
    extra = [argument.arg for argument in arguments.kwonlyargs]
    if arguments.vararg is not None:
        extra.append(f"*{arguments.vararg.arg}")
    if arguments.kwarg is not None:
        extra.append(f"**{arguments.kwarg.arg}")
    if len(positional) != leg.builder_arity or extra:
        failures.append(
            f"{leg.builder}() takes {positional + extra} — the {leg.provider!r} leg permits "
            f"exactly {leg.builder_arity}. Every extra parameter is a way for a caller to "
            "vary the endpoint, and the endpoint is the only thing standing between our "
            "configuration and where a third party sends a client's caller's words."
        )
    for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs):
        if any(fragment in argument.arg.lower() for fragment in REGION_KNOB_FRAGMENTS):
            why = (
                f"because `{leg.region_constant}` cannot be the only spelling of the region "
                "if a caller can pass another one."
                if leg.region_constant is not None
                else (
                    f"because the {leg.provider!r} leg pins NO region — a region parameter "
                    "here would be a residency control the declaration says does not exist, "
                    "which is worse than a wrong one because it reads as reassuring."
                )
            )
            failures.append(
                f"{leg.builder}() takes a parameter named {argument.arg!r}. A builder must "
                "have NO region input at all — that absence is the structural half of check "
                "4, " + why
            )

    # THE DNS-LABEL REFUSAL IS REQUIRED ONLY WHERE THERE IS A CALLER INPUT TO REFUSE. It
    # exists because Azure puts the caller's resource at the FRONT of the authority; a leg
    # whose builder takes no argument has no hostile label to interpolate, and demanding a
    # raise there would be a check with no failure mode.
    if leg.builder_arity and not any(isinstance(node, ast.Raise) for node in ast.walk(builder)):
        failures.append(
            f"{leg.builder}() never raises. It must REFUSE a value that is not a single DNS "
            "label rather than interpolate it: it lands at the front of the authority, so "
            f"`https://evil.example/x{leg.permitted_host}` is a URL whose HOST is an "
            "attacker's and whose tail merely reads like ours."
        )
    elif leg.builder_arity and not any(
        _is_pattern_guarded_raise(node, set(positional)) for node in ast.walk(builder)
    ):
        failures.append(
            f"{leg.builder}() raises, but not behind a pattern match on {positional}. A "
            "refusal conditioned on emptiness or on `None` accepts `evil.example/x`, which "
            "is the only input that matters — the value becomes the first label of the "
            "hostname, so what has to be checked is its SHAPE, against a regex, not its "
            "presence. (This check reads the shape and cannot prove the predicate can fire; "
            "`tests/in_call_llm_provider_test.py` calls the builder with the attack strings "
            "and is what proves that.)"
        )

    returns = [node for node in ast.walk(builder) if isinstance(node, ast.Return)]
    if not returns:
        failures.append(f"{leg.builder}() returns nothing this check can read.")
    permitted_holes = set(positional) | frozen_names
    for statement in returns:
        value = statement.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            failures.extend(_region_in_host_failures(leg, value.value, frozen_values, statement))
            continue
        if not isinstance(value, ast.JoinedStr):
            failures.append(
                f"{leg.builder}() line {statement.lineno} returns an expression that is not "
                "a string template, so this check cannot tell what URL it produces. Build "
                "the endpoint as one f-string over the argument and module `Final`s — a "
                "constructor whose output is unreadable from the AST is a constructor "
                "check 3's exemption cannot be granted for."
            )
            continue
        for piece in value.values:
            if not isinstance(piece, ast.FormattedValue):
                continue
            hole = ast.unparse(piece.value)
            if hole not in permitted_holes:
                failures.append(
                    f"{leg.builder}() line {statement.lineno} interpolates {hole!r} into "
                    f"the endpoint. Only the argument(s) and module-level `Final`s may "
                    f"appear (known: {sorted(permitted_holes)}). Anything else is a value "
                    "computed at runtime, which is exactly the shape this file says under "
                    "'what this check cannot see' that it is blind to."
                )
        failures.extend(_region_in_host_failures(leg, _render(value), frozen_values, statement))
    return failures


def _region_in_host_failures(
    leg: LegSpec,
    template: str,
    frozen_values: Mapping[str, str],
    statement: ast.Return,
) -> list[str]:
    """THE PRIZE: on a leg whose region is in the authority, prove it from the builder.

    Everything else in check 4 argues that a builder has no OTHER region to emit. This
    READS the region it does emit, off the label in front of the host, and requires it to
    have come from the constant that holds it. It is the only evidential residency check
    left in this tree, and the reason the OpenAI leg owes no human attestation.
    """
    if not leg.region_in_host or leg.region_constant is None:
        return []
    resolved = _resolve_holes(template, frozen_values, keep=(leg.region_constant,))
    labels = [label.removesuffix(".") for label in _labelled_hosts(resolved, leg.permitted_host)]
    constants = {leg.region_constant: (BUILDER_HOME, frozen_values.get(leg.region_constant, ""))}
    if labels and all(_region_ok(label, constants, leg.region) for label in labels):
        return []
    return [
        f"{leg.builder}() line {statement.lineno} emits {resolved!r}, which does not carry "
        f"the {leg.region!r} residency label in front of {leg.permitted_host}. This leg was "
        "adopted BECAUSE its region is in the authority where a build can read it — an "
        "endpoint without the label is the vendor's GLOBAL surface, which routes wherever "
        f"they have capacity. The label must be `{leg.region_constant}`, whose value is "
        f"{frozen_values.get(leg.region_constant, '<not a Final in this file>')!r}."
    ]


# --- 5: the check can still see -----------------------------------------------


#: Floor for the Python half. The tree parses thousands; anything near this means the
#: walk broke, and a broken walk reports a clean tree.
MINIMUM_TEMPLATES: Final = 200


def blindness_failures(
    templates: int,
    constants: Mapping[str, tuple[str, str]],
    references: Iterable[Reference],
    spec: PostureSpec | None = None,
) -> list[str]:
    posture = declared_spec() if spec is None else spec
    found = list(references)
    failures: list[str] = []
    if templates < MINIMUM_TEMPLATES:
        failures.append(
            f"the AST walk found only {templates} string templates across {SCANNED_TREES} "
            "— it is blind. Fix the scan rather than lowering MINIMUM_TEMPLATES."
        )
    # THE PARSE CANARY IS ONE PROBE PER KNOWN REGION. This file defines a `Final` for every
    # region in `KNOWN_REGIONS`, so every one of them must come back from the scan of `SELF`;
    # a scan that found the declared regions and missed the withdrawn one is precisely the
    # half-blind scan that would report a leftover constant as absent.
    unseen = sorted(
        region
        for region in KNOWN_REGIONS
        if not any(home == SELF and held == region for home, held in constants.values())
    )
    if unseen:
        failures.append(
            f"the provenance scan cannot find this file's own `Final` definition(s) for "
            f"{unseen} — every region in KNOWN_REGIONS is spelled in {SELF} exactly so the "
            "scan has something it must be able to see. Missing one means it would report "
            "a tree as having no frozen constant for that region, which is the state in "
            "which checks 1 and 3 silently accept nothing and reject everything, or the "
            "reverse. Fix `frozen_region_constants`."
        )
    # The SUBJECT canary is per-leg: a leg that pins no region has no constant to find, and
    # its ABSENCE is what `single_spelling_failures` requires instead.
    absent = sorted(
        leg.region_constant
        for leg in posture.legs
        if leg.region_constant is not None and leg.region_constant not in constants
    )
    if absent:
        failures.append(
            f"the scan cannot find {absent} as `Final` in shipped code. That is the SUBJECT "
            "canary rather than the parse canary: the KNOWN_REGIONS probe above proves this "
            "file can still read a `Final`, and this proves there is still a residency "
            "decision in the tree for it to be reading."
        )
    # THE REFERENCE CANARY IS PER LEG WITH A BUILDER, and it cannot be stated over legs
    # without one: the Google leg's whole rule is that NO literal names its host, so
    # demanding a reference for it would demand the violation.
    for leg in posture.legs:
        if leg.builder is None:
            continue
        if not any(leg.permitted_host in reference.template for reference in found):
            failures.append(
                f"no literal anywhere in the tree mentions {leg.permitted_host}, the host "
                f"the {leg.provider!r} leg permits — not even the builder's own `Final` "
                f"suffix ({leg.builder_suffix!r}) in {BUILDER_HOME}. Either the scan stopped "
                f"reading files, or {leg.builder}(), the one constructor that leg is built "
                "around, has gone."
            )
    return failures


# --- 6: the half a human owns is written down ---------------------------------


#: Where the facts this file cannot prove are owned. Named as data because
#: `delegation_failures` reads it and `main()` prints it, and a delegation stated in two
#: places is one that will eventually name two different gates.
OPERATIONS_DOC: Final = "docs/OPERATIONS.md"


def delegated_notice(spec: PostureSpec) -> str:
    """What a green run of this check does NOT cover, leg by leg.

    IT SAYS THE WITHDRAWAL OUT LOUD. Anyone who has read the pre-D-449 text will supply the
    old meaning — "the models run in India, a human just has to confirm it" — from memory,
    and a notice that merely swapped one region name into the same sentence would let them.

    **AND IT NAMES THE LEG THAT OWES NOTHING, WHICH IS NEW AND IS NOT DECORATION.** A reader
    who meets a delegation notice and finds every leg in it learns that this guard proves no
    region anywhere. One of the three legs now proves its own, and saying which one is the
    difference between an honest report and a pessimistic one.
    """
    lines: list[str] = []
    for leg in spec.legs:
        if leg.delegated_gate is None:
            if leg.region_in_host:
                lines.append(
                    f"* {leg.provider}: NOTHING IS DELEGATED. Its region ({leg.region}) is "
                    f"the first label of the authority and {leg.builder}() is proved to "
                    "emit it, so no human attestation is owed on this leg at all."
                )
            else:
                lines.append(
                    f"* {leg.provider}: NOTHING IS DELEGATED, because there is no regional "
                    "claim to confirm — the vendor cannot express one. There is nothing "
                    "here for a person to check and nothing for a DPA to warrant beyond "
                    "'somewhere in the vendor's cloud'."
                )
            continue
        lines.append(
            f"* {leg.provider}: NOT PROVED HERE, AND NO VERSION OF THIS CHECK CAN PROVE IT — "
            f"that the resource named by `azure_openai_resource` is in {leg.region}, and "
            f"that its deployment is REGIONAL Standard rather than GLOBAL. Both are "
            f"properties of the RESOURCE, invisible in "
            f"`https://<resource>{AZURE_HOST_SUFFIX}/openai/v1`; Global is Azure's DEFAULT "
            f"deployment type and processes worldwide. A human confirms both once in the "
            f"Azure portal — {OPERATIONS_DOC} §2 gates 20 and 20c — and files the reading "
            f"in docs/evidence/."
        )
    return (
        "WHAT A GREEN RUN DOES NOT COVER, PER LEG:\n"
        + "\n".join(lines)
        + "\n⚠ UNDER D-449 THE REGION THE AZURE LEG DELEGATES IS NO LONGER AN INDIAN ONE: "
        "the India residency claim was WITHDRAWN, not upgraded. Gates 20/20c confirm a US "
        "resource; nothing in this tree promises a client that their callers' words stay in "
        "India, and any document that still does is out of date. Under D-127 this file "
        "proved the region from the AST on every leg; it now does so on exactly one, and "
        "that is D-410's recorded cost rather than an oversight."
    )


def delegation_failures(document: str | None = None, spec: PostureSpec | None = None) -> list[str]:
    """Check 6: the facts this guard gave up are written down somewhere a human owns them.

    WHY A GUARDRAIL CHECKS A DOCUMENT. Because the failure this whole design is trying to
    avoid is not "the region is wrong" — it is "the region is nobody's job and the build is
    green". A weakened check plus a live gate is an honest posture; a weakened check plus a
    deleted gate is the same green output covering strictly less.

    Deliberately LOOSE about wording and strict about substance: it wants a line naming the
    constant under test and the place a human looks. Pinning the gate's prose would make
    every rewording of an operations document a red build.
    """
    posture = declared_spec() if spec is None else spec
    delegating = [leg for leg in posture.legs if leg.delegated_gate is not None]
    if not delegating:
        return []
    text = (
        (REPO_ROOT / OPERATIONS_DOC).read_text(encoding="utf-8") if document is None else document
    )
    lines = text.splitlines()
    failures: list[str] = []
    for leg in delegating:
        assert leg.delegated_gate is not None  # `delegating` selected on it
        constant, word = leg.delegated_gate
        if any(constant in line and word in line.lower() for line in lines):
            continue
        failures.append(
            f"{OPERATIONS_DOC} carries no gate naming `{constant}` and the Azure portal, "
            f"which the {leg.provider!r} leg delegates to. That gate is where the residency "
            "fact this check CANNOT prove is confirmed by a person, so without it the tree "
            "asserts a region nobody has ever read and this script prints OK over the gap. "
            "Restore the gate (20: the resource's Location; 20c: Regional rather than Global "
            "deployment) or, if the leg genuinely changed, change it here deliberately with "
            "a decision-log entry."
        )
    return failures


# --- 7: no declared leg is inert ----------------------------------------------


def live_model_providers() -> dict[str, list[str]]:
    """Which provider each model in the catalogue names — imported, like `live_settings()`.

    IMPORTING IS CORRECT HERE AND NOT A BREACH OF THE NOT-IMPORTED DOCTRINE, and the
    distinction is worth stating because this file argues the opposite three times above.
    What may never be imported is the SPEC — the statement of what the tree must look like —
    because a guard that read its own obligations from the thing it is judging agrees with
    every tree. The catalogue is the thing being JUDGED, exactly like `Settings` is in check
    2, and reading it out of the AST would be a second parser for a dict nobody disputes.
    """
    from calevate_shared.engine import LLM_MODELS

    providers: dict[str, list[str]] = {}
    for name, model in sorted(LLM_MODELS.items()):
        providers.setdefault(model.provider, []).append(name)
    return providers


def builder_call_sites(roots: Iterable[Path] | None = None) -> dict[str, list[str]]:
    """Every call to a function named like a leg's builder, as `builder -> ["path:line"]`.

    A CALL, NOT A MENTION. `ast.Call` with the name in function position — so a docstring
    naming the builder, an `__all__` entry and an import do not count. The point of check 7
    is that somebody actually builds this leg's endpoint; a leg whose builder is only ever
    imported is a leg nothing runs.
    """
    wanted = {leg.builder for leg in KNOWN_LEGS if leg.builder is not None}
    sites: dict[str, list[str]] = {name: [] for name in sorted(wanted)}
    for path in _files(roots, frozenset({".py"})):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else None
            )
            if name in wanted:
                sites[name].append(f"{_rel(path)}:{node.lineno}")
    return sites


def inert_leg_failures(
    providers: Mapping[str, Sequence[str]] | None = None,
    calls: Mapping[str, Sequence[str]] | None = None,
    spec: PostureSpec | None = None,
) -> list[str]:
    """Check 7: a declared leg that nothing uses is a wish list entry, not a permission.

    **THE DEFECT THIS EXISTS FOR HAS ALREADY HAPPENED TWICE**, which is why it is a check
    rather than a convention. D-453 found a posture whose `permitted_host` was absent from a
    hand-written watched-host tuple: nothing scanned for the host, so nothing produced a
    reference, so every clause stated over that posture ran on an empty set and printed OK.
    A declared leg has the same shape of hole one level up. If no model names it, nothing can
    ever be configured onto it and its endpoint rules are enforced against nothing; if
    nothing calls its builder, the ONE literal check 3 exempts is the suffix of a function
    that never runs.

    TWO SEPARATE ARMS BECAUSE THEY FAIL APART AND HAVE DIFFERENT FIXES. A leg with models and
    no caller is a half-wired feature (CLAUDE.md: "a route nobody mounted"). A leg with a
    caller and no models is a permission granted to nobody. Reporting them as one finding
    would send the reader to the wrong half.
    """
    posture = declared_spec() if spec is None else spec
    named = live_model_providers() if providers is None else providers
    sites = builder_call_sites() if calls is None else calls
    failures: list[str] = []
    for leg in posture.legs:
        if not named.get(leg.provider):
            failures.append(
                f"posture {posture.name!r} declares a {leg.provider!r} leg and NO model in "
                "the catalogue names it. A leg no model can be configured onto is a "
                "permission granted to nobody: every rule this file states about it — one "
                "builder, one literal, one region constant — is enforced against an empty "
                "set, and the run prints OK. Either give it an `LlmModelSpec` in "
                f"{CONTRACT} (a withdrawn one counts — `selectable=False` with a reason is "
                "still a model that names the leg), or take the leg out of the declaration."
            )
        if leg.builder is not None and not sites.get(leg.builder):
            failures.append(
                f"nothing in {SCANNED_TREES} ever CALLS {leg.builder}(), the one "
                f"constructor the {leg.provider!r} leg permits. Check 3 grants that "
                "function's suffix the tree's single literal exemption, so an uncalled "
                "builder is an exemption held by dead code — and the leg it belongs to is a "
                "half-wired feature, which this repository counts as a defect shipped "
                "rather than progress deferred."
            )
    return failures


def main() -> int:
    # CHECK 0 RUNS ALONE AND RETURNS FIRST, deliberately. Every check below is stated
    # relative to the declared posture, so a tree whose declaration cannot be resolved has
    # no rules to be judged against — and a guard that fell back to a default posture
    # would enforce one nobody declared, which is worse than printing nothing.
    name, resolution = declared_posture_name()
    if name is None:
        print("MODEL RESIDENCY: FAIL")
        for failure in resolution:
            print(f"  - {failure}")
        return 1
    declaration = declaration_failures(name)
    if declaration:
        print("MODEL RESIDENCY: FAIL")
        for failure in declaration:
            print(f"  - {failure}")
        return 1
    posture = POSTURES[name]

    references = endpoint_references()
    constants = frozen_region_constants()
    templates = template_count()

    failures = (
        blindness_failures(templates, constants, references, posture)
        + single_spelling_failures(constants, posture)
        + loose_region_literals()
        + console_config_failures()
        + endpoint_failures(references, constants, None, posture)
        + stale_allowances(references)
        + builder_failures(None, posture)
        + delegation_failures(None, posture)
        + inert_leg_failures(spec=posture)
    )
    if failures:
        print("MODEL RESIDENCY: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        print(
            f"\nDECLARED POSTURE {posture.name!r} ({DECLARATION_CONSTANT} in {CONTRACT}), "
            f"legs {[leg.provider for leg in posture.legs]}: {posture.warrant}. If a second "
            "endpoint or a second spelling is genuinely needed for a bounded reason, it "
            "belongs in ALLOWANCES in this script WITH the date and the work that removes "
            "it — never as a silent skip. If the POSTURE itself is meant to change, that is "
            f"the `PostureSpec` in {SELF}, this declaration, and a decision-log entry — "
            "together, in one reviewed commit."
        )
        print(f"\n{delegated_notice(posture)}")
        return 1

    print(
        f"MODEL RESIDENCY: OK — declared posture {name!r} over "
        f"{[leg.provider for leg in posture.legs]} ({templates} string templates scanned; "
        f"{len(references)} model host literal(s) judged and only each leg's own builder "
        f"suffix permitted; {len(ALLOWANCES)} dated allowance(s) still current)"
    )
    print(f"  what that proves under this posture: {posture.warrant}.")
    print(f"\n{delegated_notice(posture)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
