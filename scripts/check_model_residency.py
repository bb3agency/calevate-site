"""Guardrail: this tree cannot construct a model endpoint except through the one builder
its DECLARED residency posture names, and the region that posture pins has exactly one
spelling in code (D-410, made a declared choice by D-432).

**WHAT D-432 CHANGED, IN ONE PARAGRAPH.** Until D-432 the India posture was not declared
anywhere: it was IMPLIED by about thirty files agreeing with each other — a `Final` region,
a provider `Literal`, a builder, four settings, two price tables, a console panel and two
guards. Nothing named the decision, so nothing could check the pieces still agreed, and
changing it was a refactor nobody would attempt. That is not a decision that has been made;
it is one frozen by accident, with the freezing mistaken for rigour. So the posture is now a
NAME declared once in source (`DECLARED_POSTURE_NAME` in `CONTRACT`), and `POSTURES` below —
written HERE, never imported from there — says what each name OBLIGES the tree to look like.
The mechanism is the COMPARISON of two independent statements, which is strictly more than
the tree could prove before, because before there was nothing to disagree with:

* **check 0** (`declaration_failures`) fails when the DECLARATION drifts from the code — the
  one-line direction, and therefore the likely one. An unknown posture name is a hard
  failure; so is a `DECLARED_POSTURE` record whose `region`, `llm_provider` or
  `addresses_a_deployment` says something the declared posture's spec does not.
* **checks 1-4** fail when the CODE drifts from the declaration. Each is now stated over the
  declared spec rather than over Azure: under `india-azure-openai` they are
  character-for-character D-410's checks; under a posture pinning no region they INVERT and
  require that no shipped constant freezes one at all.

**WHAT D-449 CHANGED.** The declared posture moved from `india-azure-openai`
(`southindia`) to `us-azure-openai` (`eastus2`) — still Azure OpenAI, still Regional
Standard rather than Global. **That is a WITHDRAWAL of the India residency claim and never
an upgrade of anything**, and this file says so on every run (`delegated_notice`) because a
reader who has seen the old wording will otherwise supply the old meaning. It is also the
change that showed this mechanism could express only two shapes — "pins southindia" and
"pins nothing" — because the region was a module constant every check compared against
rather than a property of the declared spec. It is now the latter, and `KNOWN_REGIONS`
carries the WITHDRAWN region alongside the declared one, so the leftover a half-finished
posture move produces (`AZURE_LOCATION: Final = "southindia"` in a tree declaring the US
posture) is found and named rather than passed over by a scan looking only for `eastus2`.

**IT IS NOT A KNOB AND MUST NEVER BECOME ONE.** The declaration is a `Final` string literal
in the portability contract. It is not a `Settings` field, not an environment variable and
not a `platform_config` row — check 2 refuses any settings name carrying `posture`,
`residency`, `region` or `location`, and check 0 refuses a declaration that is not a bare
`Final` literal in `CONTRACT`. D-95 §4 is unchanged: a residency posture invertible from a
web form at 3am is not a posture. What D-432 bought is that changing it is a small reviewed
commit plus a decision-log entry instead of a thirty-file refactor — not that it is cheap.

**THIS CHECK CHANGED JOB AT D-410 AND IS WEAKER THAN IT WAS. THAT IS RECORDED HERE RATHER
THAN PAPERED OVER, BECAUSE A GUARD THAT QUIETLY CHECKS LESS THAN IT USED TO WHILE STILL
PRINTING `OK` IS WORSE THAN A DELETED ONE.**

WHAT IT USED TO PROVE. Vertex AI put `asia-south1` in the hostname AND in the `locations/`
path segment (`https://asia-south1-aiplatform.googleapis.com/v1/projects/{p}/locations/
asia-south1/...`). So residency was a fact about a STRING, and this file could settle it
from the AST with no network and no credential: every Google model URL in the tree
demonstrably named Mumbai, or the build was red. D-127's whole posture was checkable.

WHAT IT PROVES NOW. Azure OpenAI's shipped endpoint is
`https://<resource>.openai.azure.com/openai/v1` and **it names no region at all** — the
region is a property of the Azure RESOURCE, chosen by whoever created it in the portal and
invisible in every request. No amount of reading this tree will find it. So the four
things below are what is left, and they are structural rather than evidential: they prove
there is no code path by which model traffic is aimed somewhere else WITHOUT editing one
`Final` constant, which is a different and lesser claim than "the traffic goes to Mumbai".

1. **ONE SPELLING OF THE REGION.** `AZURE_LOCATION: Final = "eastus2"` in the
   portability contract is the only place the region is written. A second `Final`, a
   default argument, a dict value — anything else spelling it is refused. Stricter than
   the Vertex version, which permitted any `Final`: with the region no longer checkable
   against a URL, "there is one of it" is doing more of the work and has to hold harder.
2. **NO `Settings` FIELD CAN CARRY A REGION**, by NAME or by default VALUE, and none can
   carry a hand-typed model endpoint for ANY vendor this file knows a posture for either.
   `platform_config.managed_fields()` derives
   the ops console's editable set from `Settings.model_fields` minus the bootstrap keys
   minus credential-shaped names, so a field called `azure_location` would be editable
   from a web form the day it was declared, and a residency posture invertible by a click
   at 3am is not a posture. This property is UNCHANGED from D-127 and is the one part of
   the old guard that lost nothing in the migration — **except for one thing, which is
   named here rather than left as a diff**: the ENDPOINT half of it carried a hard-coded
   tuple of Azure token pairs, so `openai_base_url` or `gemini_api_base` passed under
   every posture including the declared one, and this file printed OK while enforcing the
   client DPA's "no configuration setting may carry … an endpoint" for one vendor out of
   three. The vendor half now comes from `POSTURES` (`KNOWN_VENDOR_TOKENS`) and the union
   is deliberate: the field a half-finished posture move leaves behind names the vendor
   the tree has just LEFT, so a check stated over the declared vendor alone is blind to
   precisely the case it exists for. Same argument `frozen_region_constants()` makes for
   scanning every posture's region rather than only the declared one.
3. **NO AZURE ENDPOINT IS CONSTRUCTIBLE EXCEPT THROUGH `azure_openai_base_url()`.**
   Exactly ONE string literal in `apps/`, `packages/` and `scripts/` may contain an Azure
   OpenAI host: the `Final` suffix that builder is assembled from. Every other literal
   naming one is a second way to build an endpoint, which is the shape check 4 could then
   say nothing about.
4. **THE BUILDER CANNOT EMIT A REGION OTHER THAN THE DECLARED POSTURE'S.** It takes ONE
   argument, that argument is not region-shaped, its output template interpolates only that
   argument and module-level `Final`s, and it RAISES rather than interpolating a resource
   that is not a single DNS label. There is no region input, so there is no OTHER region to
   emit — the claim is about SINGULARITY, not about which country wins it, which is why
   D-449 could move the region without touching this check at all — and because
   the resource lands at the FRONT of the authority, refusing anything but a DNS label is
   what stops `resource = "evil.example/x"` producing a URL whose host is somebody else's.

WHAT NO VERSION OF THIS CHECK CAN PROVE, AND WHO OWNS IT INSTEAD. Two facts, both
properties of the Azure resource rather than of this repository, both invisible from the
endpoint, and the second is the more dangerous:

* **Is the resource in the DECLARED region (`eastus2` since D-449)?** OPERATIONS §2
  **gate 20** — a human reads the
  Location field on the resource's Overview blade, confirms it with
  `az cognitiveservices account show --query location`, and files the reading in
  `docs/evidence/` with a date and a name.
* **Is the deployment REGIONAL Standard rather than GLOBAL?** OPERATIONS §2 **gate 20c**.
  Global is Azure's DEFAULT deployment type and processes worldwide. A Global deployment
  inside the declared resource passes every check in this file and breaks the DPA.
  It costs money to get right (Regional runs ~5-10% above Global list), which is precisely
  why nobody will notice having left the default.

`delegation_failures()` is not decoration: it fails this build if those gates stop being
written down, because the honest half of a weakened guard is the pointer to whoever holds
the other half.

THE REGIONAL HOSTNAME, AND WHY THIS FILE IS BUILT SO ADOPTING IT IS ONE LINE. Azure also
serves `<region>.api.cognitive.microsoft.com`, documented as interchangeable with the
custom subdomain — a hostname that CARRIES THE REGION, which would hand check 1 back its
evidence and make this guard as strong as the Vertex one was. D-410 rejects it FOR NOW on
one ground: the OpenAI-compatible v1 surface is documented only on the custom-subdomain
form (and custom subdomains are what Entra ID requires), so shipping it would trade a
confirmed-working endpoint for a stronger guard on an unconfirmed one. **OPERATIONS §2
gate 20d is the call that settles it**, and the machinery is already here and already
tested: flip `REGIONAL_HOST_ADOPTED`, and the same scan that today REFUSES that hostname
starts requiring the label in front of it to be `AZURE_LOCATION`. Both branches are
exercised by `tests/model_residency_guard_test.py`, so the dormant one is not a promise.

WHY THERE IS NO BLACKLIST OF OTHER AZURE REGIONS (`eastus`, `swedencentral`, or — since
D-449 — `southindia` itself). It was the
obvious replacement for the `us-central1` check and it is unreachable: a region string can
only affect where a call lands by reaching an endpoint, no endpoint is constructible
outside the builder (check 3), and the builder has no region input (check 4). A ban on
strings that cannot reach anything is a check with no failure mode, and it would rot into
"add your region to the list" the first time somebody names a variable after a datacentre.

MECHANISM: the Python half reads the **AST**, not the source text, and reconstructs
f-strings into templates (`f"https://{X}{SUFFIX}"` becomes `https://{X}{SUFFIX}` with each
hole carrying the interpolated expression's source). Two reasons, both learned here. First,
`sarvam_model_identifier_test`'s: a correction has to be EXPLAINED somewhere, and a regex
over source flags the paragraph explaining it — this very docstring names every watched
host. Second, provenance: "the region came from `AZURE_LOCATION`" and "the region came
from `self._loc`" are the same string to a grep and are not the same fact.

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
`ModelConfig._llm_endpoint_is_coherent` refuses any `llm_base_url` our own builder could not
have emitted, so the static check covers the literal and the validator covers the value.

The two literals that DEFINE the watched hosts in this file are its whole self-exemption —
see `SELF` and `_host_definition`; a URL written anywhere else in this file is judged like
any other file's. The non-Python half is a LINE scan (`.ts`, `.json`, shell, nginx): a line
naming a watched host becomes a reference and is judged by the same rules, so an Azure URL
in a TypeScript file is caught — but with no AST there is no way to tell code from a `//`
comment, so a comment naming one in those files WILL be reported. That false positive is
accepted rather than engineered away: this repo has no non-Python caller of a model
provider, CLAUDE.md forbids one, and a comment about an Azure OpenAI host in the frontend is
worth a human look anyway. It is a tripwire, not a workhorse —
`tests/model_residency_guard_test.py` steps on it deliberately, because a tripwire with no
subject in the tree is one nobody has evidence is connected.

NOT IN SCOPE: `oauth2.googleapis.com`, `sheets.googleapis.com` and
`www.googleapis.com/auth/spreadsheets` in `workers/google_sheets.py`. Those are the
tenant's OWN destination, chosen by them, disclosed in their DPA, and carry no model
inference. This check is about where a MODEL runs. (Google left the model legs entirely at
D-410; it remains a sub-processor for Sheets alone, SECURITY-COMPLIANCE §4.)
IN SCOPE, AND THE LINE BETWEEN THEM IS A FULL HOSTNAME RATHER THAN A DOMAIN:
`generativelanguage.googleapis.com` is the Gemini Developer API, it is a MODEL host, and
`google-direct` is a posture in the table below — so it is watched exactly like
`api.openai.com` is. Matching `.googleapis.com` instead would have swept every CRM export
into a residency check, which is the false positive that gets a guard switched off.

Run: `uv run python -m scripts.check_model_residency`   (also in `make guardrails`)
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]

#: THE REGIONS THIS CHECK KNOWS HOW TO ENFORCE — one `Final` per pinning posture, spelled
#: HERE rather than imported, for the reason `check_bootstrap_keys.BOOTSTRAP_KEYS` gives: a
#: guardrail that imported the value it is checking would be asking the code whether it
#: agrees with itself. They are also this check's own blindness canary (check 5) — the
#: provenance scan must be able to find EVERY one of these lines, or it is not reading
#: anything.
#:
#: **WHY THE WITHDRAWN REGION KEEPS A CONSTANT HERE (D-449).** Deleting
#: `AZURE_REGION_INDIA` when the declaration moved to `us-azure-openai` would have been one
#: line, and it would have blinded this check to the single most likely product of a
#: half-finished posture move: a leftover `AZURE_LOCATION: Final = "southindia"` in a tree
#: that now declares the US posture. A scan that looked only for the DECLARED region walks
#: straight past that constant and reports "one spelling of the region" — true, and
#: useless. So `frozen_region_constants()` scans `KNOWN_REGIONS`, which is every region any
#: KNOWN posture pins, and `single_spelling_failures()` refuses a constant holding a region
#: the declaration has moved off, by name and by value.
AZURE_REGION_INDIA: Final = "southindia"
AZURE_REGION_US: Final = "eastus2"

#: The name and home of the ONE constant in shipped code allowed to hold that string.
#: Both are asserted (check 1): a second constant, or the same one moved somewhere a
#: reader would not look for it, is a second spelling of the residency decision.
REGION_CONSTANT: Final = "AZURE_LOCATION"
BUILDER_HOME: Final = "packages/shared/src/calevate_shared/engine.py"

#: The one function permitted to produce an Azure OpenAI endpoint (checks 3 and 4).
BUILDER: Final = "azure_openai_base_url"

#: Azure OpenAI's CUSTOM-SUBDOMAIN host suffix — the form D-410 ships, and the form that
#: **carries no region**. Everything this file lost is downstream of that fact.
AZURE_HOST_SUFFIX: Final = ".openai.azure.com"

#: The rest of the endpoint, exactly as `azure_openai_base_url` assembles it. The one
#: literal in the whole tree permitted to name an Azure host is this string, declared as a
#: `Final` in `BUILDER_HOME` (`_AZURE_ENDPOINT_SUFFIX`).
#:
#: SPELLED HERE RATHER THAN IMPORTED, like the region constants, and it buys something
#: extra: the
#: v1 path shape is VERIFIED EVIDENCE (Microsoft Learn, 19 Aug 2026 — no `api-version`,
#: key in `Authorization: Bearer`), not a preference. If somebody edits the path in
#: `BUILDER_HOME`, this guard goes red and the edit has to be made deliberately in both
#: places, which is the correct amount of friction for a change that moves what a third
#: party is handed.
BUILDER_SUFFIX: Final = ".openai.azure.com/openai/v1"

#: Azure's REGIONAL host form, which puts the region back in the URL where a static check
#: can read it. Rejected FOR NOW by D-410 (the v1 surface is documented only on the custom
#: subdomain); OPERATIONS §2 gate 20d is the call that reopens it. See
#: `REGIONAL_HOST_ADOPTED`.
AZURE_REGIONAL_HOST_SUFFIX: Final = ".api.cognitive.microsoft.com"

#: OpenAI's own API. DISQUALIFIED on residency and named here so the refusal is a check
#: rather than a memory: OpenAI's India data residency covers **storage at rest only** —
#: inference still runs in the US, and in-region GPU inference exists only in the US and
#: Europe. For a phone call the transcript IS the inference input, so the half of that
#: promise that would matter to us is the half it does not make.
#:
#: THIS IS THE ONE BAN THAT SURVIVED THE MIGRATION INTACT. It is the direct successor to
#: D-127's ban on the AI Studio Developer API, and the risk is HIGHER now rather than
#: lower: Azure's v1 surface is OpenAI-compatible, so the client that talks to it would
#: talk to `api.openai.com` unchanged. One edited base URL is the whole distance between
#: the shipped posture and a disqualified one.
OPENAI_DIRECT_HOST: Final = "api.openai.com"

#: Google's Gemini DEVELOPER API — the AI Studio surface, not Vertex. Named here for
#: OPENAI_DIRECT_HOST's exact reason: it is the third vendor a `PostureSpec` can express,
#: so the scan has to be able to SEE it before the spec below means anything.
#:
#: VERIFIED-VENDOR-DOCS via `docs/evidence/gemini-direct-api.md:270-273` (Microsoft's
#: `azure-docs` repository on github.com, read 22 Aug 2026 — every Google documentation
#: host is egress-blocked here, so the vendor's own page was NOT read). Base URL
#: `https://generativelanguage.googleapis.com/v1beta/openai`, `POST /chat/completions`,
#: a STATIC key in `Authorization: Bearer`.
#:
#: IT IS THE FULL HOST AND NOT `.googleapis.com`, deliberately. `sheets.googleapis.com`
#: and `oauth2.googleapis.com` are the tenant's OWN destination on the Sheets leg and
#: carry no inference (see "NOT IN SCOPE" above); a suffix match would drag every CRM
#: export into a check about where a MODEL runs, which is how a guard gets turned off.
GEMINI_DIRECT_HOST: Final = "generativelanguage.googleapis.com"

#: The rest of that endpoint, kept beside the host for `BUILDER_SUFFIX`'s reason: the path
#: shape is evidence, and an edit to it should be deliberate rather than incidental.
GEMINI_DIRECT_PATH: Final = "/v1beta/openai"

#: WOULD THE REGIONAL HOSTNAME RESTORE THE AST PROOF? Yes — and this flag is the whole
#: cost of adopting it, which is why the machinery below is written now rather than
#: promised. `False`: naming `AZURE_REGIONAL_HOST_SUFFIX` in shipped code is a failure,
#: because D-410 ships the custom subdomain and a second endpoint form would be a second
#: residency posture. `True`: it becomes the EXPECTED form and the label in front of it is
#: checked against the declared posture's region — check 1's lost evidence, back.
#:
#: FLIPPING IT IS NOT THE WHOLE CHANGE and the comment says so rather than letting somebody
#: find out: gate 20d has to pass first (does v1 actually answer there), then
#: `azure_openai_base_url()` moves to the regional form, then this flag, then a decision-log
#: entry naming the gate as the evidence. What the flag buys is that the GUARD is not the
#: thing standing in the way, and that the stronger branch is tested before it is needed.
REGIONAL_HOST_ADOPTED: Final = False


# --- 0: WHICH POSTURE IS DECLARED (D-432) -------------------------------------
#
# Before D-432 the India posture was not declared anywhere. It was IMPLIED by ~30 files
# agreeing with each other, so nothing could check that they still agreed and changing it
# was a refactor nobody would attempt — a decision frozen by accident, with the freezing
# mistaken for rigour. The posture is now a NAME in source (`CONTRACT`'s
# `DECLARED_POSTURE_NAME`) and the table below is what each name OBLIGES the tree to look
# like. The two statements are independent and are COMPARED, which is what makes this
# mechanism stronger than the hard-wiring it replaced rather than a flag the guard shrugs
# at: checks 1-4 fail when the code drifts from the declaration, and check 0 fails when
# the declaration drifts from the code.

#: The portability contract: where the declaration lives and where the builder lives.
#: A separate name from `BUILDER_HOME` even though they are the same path today, because
#: they are two different obligations — a posture that moved its builder would still have
#: to declare itself here.
CONTRACT: Final = "packages/shared/src/calevate_shared/engine.py"

#: The `Final` that NAMES the posture, and the record built from it that the RUNTIME reads.
DECLARATION_CONSTANT: Final = "DECLARED_POSTURE_NAME"
POSTURE_RECORD_CONSTANT: Final = "DECLARED_POSTURE"


@dataclass(frozen=True)
class PostureSpec:
    """What one declared posture obliges the tree to look like.

    HELD HERE AND NEVER IMPORTED FROM THE CONTRACT, for `AZURE_REGION_INDIA`'s reason and
    more
    sharply. The contract states which posture is in force; this table states what that
    posture costs. If the spec were imported, editing the declaration would edit the
    obligation in the same commit and the guard would agree with any tree it was shown —
    the "reads a flag and shrugs" failure this mechanism exists to avoid.

    ADDING A POSTURE IS DELIBERATELY NOT FREE. A name this table does not know is a hard
    failure, so a new posture is a spec written HERE by somebody who has had to say, in
    advance and in one place, what would PROVE the tree is really in it — plus a
    decision-log entry. That is the reviewed change D-432 traded a thirty-file refactor
    for; it is not a smaller version of the same freeze.
    """

    #: The declared name, carried on the record as well as being the `POSTURES` key so a
    #: failure message can say WHICH posture refused rather than describing it.
    name: str
    #: The region this posture PINS, or `None` for one making no regional claim.
    region: str | None
    #: The single frozen constant permitted to spell it. `None` means the guard requires
    #: that NO shipped constant spells a region at all — so a leftover `AZURE_LOCATION`
    #: cannot sit in a tree whose declaration has moved on.
    region_constant: str | None
    #: Our closed vocabulary's member for this leg (`calevate_shared.engine.LlmProvider`).
    llm_provider: str
    #: The word(s) a `Settings` field name would carry if it named THIS posture's vendor.
    #: Read by `console_config_failures` through `KNOWN_VENDOR_TOKENS`, which is the union
    #: over every posture — never over the declared one alone.
    #:
    #: STATED HERE RATHER THAN DERIVED FROM `llm_provider` OR `permitted_host`, and both
    #: rejections are worth keeping. Splitting `llm_provider` ("google") would miss
    #: `gemini_base_url`, because a vendor's PRODUCT name and its provider slug are
    #: routinely different words and a field is named after whichever one the engineer had
    #: in mind. Splitting `permitted_host` would yield "api", "com" and "googleapis" —
    #: tokens so broad that `sarvam_api_url` would be refused, which is the false positive
    #: that gets a name check deleted rather than obeyed. So the spec's author states the
    #: vendor's words, in the same place they state everything else this posture costs.
    vendor_tokens: tuple[str, ...]
    #: Does the API address a DEPLOYMENT id the operator chose rather than the model's own
    #: name? Cross-checked against the declared record because it is the field a reader
    #: would call cosmetic, and it is what decides whether `azure_openai_deployment` and
    #: `azure_openai_model` are two things or one (`engine.ModelBinding`).
    addresses_a_deployment: bool
    #: The ONE function permitted to build this posture's endpoint, and how many arguments
    #: it may take. Zero means a fixed vendor endpoint with no caller input — and with no
    #: caller input there is no hostile label to refuse, which is why the DNS-label refusal
    #: is required only above arity zero.
    builder: str
    builder_arity: int
    #: The one literal in the tree permitted to name this posture's host: only in
    #: `BUILDER_HOME`, only as a `Final`, and only this exact string.
    builder_suffix: str
    #: The watched host this posture may name at all. Every other watched host is refused.
    permitted_host: str
    #: `(constant, word)` that must share a line in `OPERATIONS_DOC`, naming the human gate
    #: that owns what this check cannot prove. `None` for a posture that delegates nothing
    #: — itself a claim the spec has to make out loud rather than by omission.
    delegated_gate: tuple[str, str] | None
    #: One line printed on every run saying what a green result does and does not mean.
    warrant: str


#: EVERY POSTURE THIS TREE KNOWS HOW TO CHECK. Exactly one of them is declared.
#:
#: `india-azure-openai` IS HERE AND IT IS NO LONGER DECLARED (D-449). It stays for the same
#: reason `openai-direct` earns its row, and the argument is if anything sharper for a
#: posture the product has actually left: a mechanism that can only express the posture in
#: force proves nothing about the posture in force. With the withdrawn spec still present,
#: `tests/residency_posture_test.py` can state the SHIPPED tree against it and watch this
#: guard name both regions in its refusal — which is what turns "the generalization is
#: load-bearing" from a design intention into an observed fact. Deleting the row would also
#: delete the only way to ask "would this tree pass as an Indian one", which is the question
#: an auditor reading a superseded DPA will arrive with.
#:
#: `openai-direct` IS HERE AND IT IS NOT AN OFFER. It is the posture D-410 DISQUALIFIED on
#: residency (OpenAI's India residency covers storage at rest; inference runs in the US, and
#: for a phone call the transcript IS the inference input), and it earns its row for one
#: reason: a mechanism that can only express the posture already in force proves nothing
#: about the posture already in force. With a second spec present,
#: `tests/residency_posture_test.py` declares it over the REAL tree and watches this guard
#: refuse — which turns "the guard fails when code and declaration disagree" from a design
#: intention into an observed fact. Declaring it for real would also have to change
#: `apps/web/src/lib/legal/dpa.ts`, which warrants the declared posture to clients in an
#: executed agreement; that is a legal act, not a config change.
#:
#: `google-direct` IS HERE AND IT IS NOT AN OFFER EITHER. It is the second posture D-448
#: refused, and it is a row rather than a paragraph because a table that could express two
#: vendors was a table whose vendor-independence nobody could observe: every check stated
#: over "Azure or not Azure" reads as general and is not, and the only way to tell the
#: difference is to state a THIRD vendor and watch what breaks. Two things break, both
#: fixed in the same change that added this row and neither of them decorative — the
#: `Settings`-endpoint check knew only Azure's name (so `openai_base_url` sailed through
#: under EVERY posture, including the declared one), and the watched-host set was a
#: hand-written tuple (so this posture's own host would have been invisible to check 3 and
#: its `permitted_host` inert). ⚠ TWO FACTS THIS ROW DOES NOT CARRY, and they are no longer
#: unknown — they are simply not this file's to hold. The engine-side wire value for the
#: provider and the name of the credential entry it is stored under are both settled, to
#: the vendor's own enum and OpenAPI rather than to a dashboard label
#: (`docs/evidence/llm-provider-postures.md` §1 and §2). They stay out because a
#: `PostureSpec` states what the TREE must look like; an adapter that read a wire value
#: from this table would be reading it from the file least likely to be checked against the
#: vendor, which is the D-417 failure wearing a different hat.
POSTURES: Final[dict[str, PostureSpec]] = {
    "us-azure-openai": PostureSpec(
        name="us-azure-openai",
        region=AZURE_REGION_US,
        region_constant=REGION_CONSTANT,
        llm_provider="azure_openai",
        vendor_tokens=("azure",),
        addresses_a_deployment=True,
        builder=BUILDER,
        builder_arity=1,
        builder_suffix=BUILDER_SUFFIX,
        permitted_host=AZURE_HOST_SUFFIX,
        delegated_gate=(REGION_CONSTANT, "portal"),
        warrant=(
            "the region is spelled once and it is not an Indian one, no Settings field "
            "can carry a region, no Azure endpoint is constructible outside the one "
            "builder, and that builder has no region input — but NOTHING HERE CLAIMS "
            "INDIAN RESIDENCY ANY MORE, because D-449 withdrew that claim"
        ),
    ),
    "india-azure-openai": PostureSpec(
        name="india-azure-openai",
        region=AZURE_REGION_INDIA,
        region_constant=REGION_CONSTANT,
        llm_provider="azure_openai",
        vendor_tokens=("azure",),
        addresses_a_deployment=True,
        builder=BUILDER,
        builder_arity=1,
        builder_suffix=BUILDER_SUFFIX,
        permitted_host=AZURE_HOST_SUFFIX,
        delegated_gate=(REGION_CONSTANT, "portal"),
        warrant=(
            "the region is spelled once, no Settings field can carry one, no Azure "
            "endpoint is constructible outside the one builder, and that builder has no "
            "region input"
        ),
    ),
    "openai-direct": PostureSpec(
        name="openai-direct",
        region=None,
        region_constant=None,
        llm_provider="openai",
        vendor_tokens=("openai",),
        addresses_a_deployment=False,
        builder="openai_base_url",
        builder_arity=0,
        # An f-string, so this file does not itself spell a watched host outside
        # `SELF_DECLARATIONS` — `_render` turns it into `https://{OPENAI_DIRECT_HOST}/v1`,
        # which mentions no host, while the VALUE is the literal the tree would have to
        # carry. The same trick the docstring exemption would otherwise have to grow for.
        builder_suffix=f"https://{OPENAI_DIRECT_HOST}/v1",
        permitted_host=OPENAI_DIRECT_HOST,
        delegated_gate=None,
        warrant=(
            "NO REGIONAL CLAIM IS MADE OR CHECKABLE under this posture — inference runs "
            "where the vendor runs it. What is still proved is one endpoint constructor, "
            "one literal naming it, and no Settings field able to carry a region or an "
            "endpoint"
        ),
    ),
    "google-direct": PostureSpec(
        # ⚠ CHECKABLE, AND REFUSED ON MERIT — the two are different claims and this table
        # only makes the first. A spec here means the guard could hold the tree to this
        # posture, exactly as `openai-direct`'s row does; it has never meant the posture is
        # on offer. `docs/evidence/llm-provider-postures.md` refuses this one, and NOT on
        # residency (D-449 spent that argument and it is not recycled here): Gemini's
        # thinking tokens draw on the SAME `max_output_tokens` budget as the reply and can
        # return a candidate carrying no `content` field at all. On a phone call that is
        # SILENCE, not a clipped sentence — a failure mode with no analogue on the other
        # two providers, mitigated by the engine only on `gemini-2.5-flash`, which retires
        # 16 Oct, while every `gemini-3.*` successor takes a non-zero thinking level with
        # no way to zero it. The row stays because a mechanism that can only express the
        # postures we like proves nothing about the posture in force.
        name="google-direct",
        # NO REGION, AND THE DISTINCTION FROM `openai-direct` IS WORTH THE SENTENCE.
        # OpenAI HAS regions and none of them is India (D-448: `DataResidency` is a closed
        # `Literal` of four). Google's Developer API has none AT ALL — the region is not
        # unset, it is UNEXPRESSIBLE: no region in the host, none in the path, no field in
        # which to ask for one, and Google's own docs say to use Vertex if residency
        # matters (`docs/evidence/gemini-direct-api.md:55-68`). Both spell `region=None`
        # here because this table records what the tree must LOOK like, and the two arrive
        # at the same obligation — zero frozen region constants — by different routes.
        region=None,
        region_constant=None,
        # OUR vocabulary's member, not the engine's wire value. `LlmProvider` is closed to
        # `azure_openai` today, so this name — like `openai-direct`'s — is a member the
        # tree would have to GROW before the posture could be declared, which is part of
        # what makes declaring one a reviewed commit rather than an edited word. The
        # engine-side value is a SEPARATE fact that happens to be the same string, and the
        # coincidence is why it is worth saying: it is `"google"`, VERIFIED to the vendor's
        # own enum rather than to a dashboard label
        # (`docs/evidence/llm-provider-postures.md:134`, and the credential entry is a
        # single `GOOGLE` at `:225`). It is still not carried here — a `PostureSpec` says
        # what the TREE must look like, and an adapter reading a wire value out of this
        # table would be reading it from the file least likely to be checked against the
        # vendor. D-417 is the row about what guessing one costs.
        llm_provider="google",
        # BOTH WORDS, because the vendor and the product are named differently by
        # different people and a `Settings` field gets whichever the author had in mind.
        # `Settings.gemini_api_key` already exists in this tree (the AI Studio key no
        # surface opens), which is the evidence that "gemini" is the word people reach for
        # here — and a token list that had only "google" would let `gemini_base_url`
        # through, which is the whole defect this field exists to close.
        vendor_tokens=("google", "gemini"),
        # The Developer API addresses the model by its own published name
        # (`gemini-2.5-flash`); there is no operator-chosen deployment id to indirect
        # through, which is Azure's peculiarity and not a general one.
        addresses_a_deployment=False,
        builder="gemini_base_url",
        # A fixed vendor endpoint with no caller input, like `openai-direct` — so there is
        # no hostile label to interpolate at the front of the authority and the DNS-label
        # refusal check 4 requires above arity zero does not apply.
        builder_arity=0,
        # An f-string for `openai-direct`'s reason: `_render` turns it into
        # `https://{GEMINI_DIRECT_HOST}{GEMINI_DIRECT_PATH}`, which names no host, while
        # the VALUE is the literal the tree would have to carry.
        #
        # ⚠ MARKED ASSUMPTION — WHICH OF TWO SURFACES, NOT WHICH HOST. The host is settled
        # and it is the only part any check here reads. The PATH is not: this is the
        # OpenAI-COMPATIBLE base (`/v1beta/openai`, VERIFIED-VENDOR-DOCS via Microsoft's
        # `azure-docs`, `docs/evidence/gemini-direct-api.md:270-273`), chosen because every
        # leg in this product speaks the OpenAI wire format. Google's own client instead
        # sets `base_url = "https://generativelanguage.googleapis.com/"` with
        # `api_version = "v1beta"` and speaks the NATIVE protocol
        # (`docs/evidence/llm-provider-postures.md:829-837`) — and that is the client the
        # engine's Google leg actually is. So whichever surface a declaration adopts, this
        # string is set DELIBERATELY in the same commit: the guard goes red the moment the
        # builder's own `Final` disagrees with it, which is the friction `BUILDER_SUFFIX`
        # was written to create rather than a gap in it.
        builder_suffix=f"https://{GEMINI_DIRECT_HOST}{GEMINI_DIRECT_PATH}",
        permitted_host=GEMINI_DIRECT_HOST,
        # NOTHING IS DELEGATED, AND THAT IS A CLAIM RATHER THAN AN OMISSION. A delegated
        # gate names the human who confirms a fact this check cannot prove; under a
        # posture where the region is unexpressible there is no such fact, and sending a
        # person to a console to confirm a region that does not exist would be worse than
        # sending them nowhere. ⚠ WHAT WOULD STILL NEED A GATE ON THE DAY THIS POSTURE IS
        # DECLARED is COMMERCIAL rather than residency-shaped and is NOT invented here:
        # Google's free tier states it uses submitted prompts and responses to improve its
        # products with human reviewers able to read them, and only the PAID tier does not
        # (D-448) — so "is this key a paid key" is an OPERATIONS §2 gate somebody has to
        # write, in a file this lane does not own, together with the decision-log entry
        # that declares the posture.
        delegated_gate=None,
        warrant=(
            "NO REGIONAL CLAIM IS MADE OR CHECKABLE under this posture, and unlike every "
            "other row here the vendor could not make one if it wanted to — the Developer "
            "API has no region in its host, none in its path and no field in which to ask "
            "for one. What is still proved is one endpoint constructor, one literal "
            "naming it, and no Settings field able to carry a region or an endpoint"
        ),
    ),
}

#: EVERY region any known posture pins — DERIVED from `POSTURES`, never a second list
#: written beside it. Two properties follow and both were bought by D-449's move. It cannot
#: drift when a posture is added (the `AZURE_LIST_PRICE_USD_PER_MTOK` failure class: a
#: parallel table nobody updates), and because it holds the WITHDRAWN region as well as the
#: declared one, check 1 can see a frozen constant the declaration has moved off — the one
#: thing a declared-region-only scan is structurally unable to notice.
KNOWN_REGIONS: Final[frozenset[str]] = frozenset(
    spec.region for spec in POSTURES.values() if spec.region is not None
)

#: EVERY model host any known posture may name — DERIVED from `POSTURES`, for exactly the
#: reasons `KNOWN_REGIONS` is. It feeds `WATCHED_HOSTS` (what the scan can SEE) and
#: `endpoint_failures` (what it refuses), so a posture added to the table above cannot land
#: with a `permitted_host` no scan looks for and no clause judges — which is the shape a
#: spec that was decorative rather than enforced would have, and it would have printed OK.
KNOWN_POSTURE_HOSTS: Final[frozenset[str]] = frozenset(
    spec.permitted_host for spec in POSTURES.values()
)

#: EVERY vendor word any known posture answers to — DERIVED from `POSTURES`, never a second
#: list beside it. Read by `console_config_failures` and by nothing else.
#:
#: **WHY THE UNION AND NOT THE DECLARED POSTURE'S OWN TOKENS**, which is the whole of what
#: this constant buys and is the argument `frozen_region_constants()` already makes one
#: level down. The artefact a half-finished posture move leaves behind is a `Settings`
#: field for the vendor the tree has just LEFT — `azure_openai_base_url` surviving a move
#: to OpenAI direct, `openai_base_url` surviving a move back — so a check that knew only
#: the declared vendor would be blind to precisely the case it most needs to catch, while
#: still printing OK. The union also makes the check bite BEFORE any second posture is
#: declared: under today's Azure declaration an `openai_base_url` field is refused, which
#: is correct, because there is no leg in this product for it to configure.
KNOWN_VENDOR_TOKENS: Final[frozenset[str]] = frozenset(
    token for spec in POSTURES.values() for token in spec.vendor_tokens
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
#: passes would put the single hole in the worst possible place. The file has to name the
#: hosts to watch them, and `_host_definition` below says exactly what that costs — a
#: template that IS one of the watched host strings and nothing else.
SELF: Final = "scripts/check_model_residency.py"

#: `Settings` field-name fragments that would put a model region under console control.
#: Names, not values, because the dangerous field is the one whose value is EMPTY in the
#: tree and supplied from the store — see "what this check cannot see".
#:
#: `vertex`/`aiplatform` are GONE from this tuple and `azure` did NOT replace them, which
#: is the one place D-410 required this check to get LOOSER. Under D-127 no `Settings`
#: field had any business naming the model vendor at all. Azure's endpoint is built from
#: four legitimate `azure_openai_*` settings — a resource, a key, a deployment id and a
#: model — so a fragment banning the vendor's name would ban the configuration the leg
#: cannot run without. `ENDPOINT_KNOB_WORDS` below, paired with `KNOWN_VENDOR_TOKENS`, is
#: what took over the part of that job which still makes sense: the vendor's name is fine
#: on a field holding a resource or a key, and refused on one holding a URL.
#:
#: THIS TUPLE NEEDS NO POSTURE AND THAT IS WHY IT IS THE MODEL THE ENDPOINT HALF WAS
#: REBUILT AGAINST. "region", "location", "residency", "datacenter" and "posture" mean the
#: same thing whoever is serving the model, so this check has never had a vendor to fall
#: behind. The endpoint half had Azure's name hard-coded in it and did fall behind, which
#: is the asymmetry `KNOWN_VENDOR_TOKENS` closes.
REGION_KNOB_FRAGMENTS: Final[tuple[str, ...]] = (
    "region",
    "location",
    "residency",
    "datacenter",
    # D-432: the DECLARED POSTURE is source, never configuration. A field called
    # `llm_posture` would invert the residency decision from a text box, which is the one
    # thing the declaration mechanism must never become — so the word joins the list the
    # day the concept exists rather than the day somebody tries it.
    "posture",
)

#: The ENDPOINT half of the same rule, and the half `REGION_KNOB_FRAGMENTS` above was
#: already principled about while this one was not. A `Settings` field whose name pairs a
#: vendor word (`KNOWN_VENDOR_TOKENS`, derived from `POSTURES`) with one of these is a
#: model endpoint in a text box. Check 3 says the endpoint has exactly one constructor; a
#: console field called `azure_openai_base_url` would be a second one, made of a web form.
#:
#: **THIS TUPLE USED TO CARRY THE VENDOR TOO — `("azure", "url")` and two siblings — AND
#: THAT WAS A HOLE RATHER THAN A SIMPLIFICATION.** It meant `openai_base_url` and
#: `gemini_api_base` were accepted under every posture including the declared one, so the
#: DPA's warranty that "no configuration setting may carry … an endpoint"
#: (`apps/web/src/lib/legal/dpa.ts`) had a vendor-shaped gap in its enforcement that no
#: run of this guard would ever mention. The vendor half now comes from the posture table,
#: where a vendor is a thing somebody had to declare; this tuple keeps only the part that
#: is genuinely vendor-independent — the words that mean "a URL".
#:
#: STILL A PAIR AND NEVER THE WORDS ALONE, because plenty of settings are legitimately
#: URLs (`webhook_base_url`, `database_url`, `object_store_endpoint`) and banning the word
#: would be a check people route around by renaming. The vendor's name beside it is what
#: makes the intent unambiguous.
#:
#: `base` IS IN THE LIST AND IS NOT PADDING. `AZURE_OPENAI_API_BASE` is the vendor's OWN
#: name for this value — it is one of the four flat credential entries the engine stores
#: (D-417) — so `azure_openai_api_base` is the single likeliest spelling of the field this
#: check exists to refuse, and it carries no `url`, `endpoint` or `host` at all. The three
#: fragments this file shipped with would have waved it through.
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
    So the registry can only ever shrink, and only by the defect being fixed. Identical
    contract to `check_wiring.UNWIRED_BASELINE` and `check_docs_drift.DEFERRED_MIRRORS`,
    for the identical reason — an exemption nobody can take away is one nobody can prove
    still describes reality.
    """

    host: str
    recorded: str
    reason: str
    removed_by: str


#: EMPTY, and that is the state this registry is supposed to stay in. It held one entry
#: under D-127 (`apps/workers/extraction.py`, whose `GEMINI_CHAT_URL` named the AI Studio
#: Developer API); the work that closed it landed and `stale_allowances()` then REQUIRED
#: the entry to go, which is exactly the contract it was written under.
#:
#: Kept as a declared, typed, empty mapping rather than deleted along with its machinery:
#: the NEXT bounded exception has to land as a dated row with a closer, and a registry
#: that has to be re-invented is a registry somebody replaces with a `continue`.
ALLOWANCES: Final[dict[str, DatedAllowance]] = {}


@dataclass(frozen=True)
class Reference:
    """One URL-shaped literal, with where it is, what it renders to, and whether it is
    frozen.

    `frozen` is carried because the ONE permitted Azure literal in the tree is permitted
    on three conditions together — the right file, the exact string, and `Final` — and a
    reader of `endpoint_failures` should not have to re-derive the third from somewhere
    else.
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

    The hole's SOURCE is what makes checks 1 and 4 possible — and, on the day gate 20d
    passes, what will make the regional-host region check possible too.
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


def _templates(path: Path) -> Iterator[tuple[str, int, bool]]:
    """Every string template in one Python file — plain constants and rendered f-strings —
    with a flag saying whether it is a `Final`'s value.

    Two exclusions. Docstrings, per `_docstrings`. And constants nested INSIDE an f-string:
    the rendered whole already covers them, and yielding both would report one literal
    twice with the second report missing the context it is being judged on.
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
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            yield _render(node), node.lineno, False
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skipped
        ):
            yield node.value, node.lineno, id(node) in frozen


#: The hosts a literal has to mention before this check has an opinion about it: EVERY
#: known posture's own host, plus the one form that belongs to no posture.
#:
#: DERIVED RATHER THAN LISTED (and it was listed, which is how it fell a vendor behind the
#: table above). A hand-written tuple beside `POSTURES` is the `KNOWN_REGIONS` failure
#: class in a second place: a posture added to the table with a host missing from here has
#: a `permitted_host` no scan ever looks for, so `endpoint_failures` sees no reference,
#: says nothing, and the posture's own single-constructor rule is unenforced under the one
#: posture it exists for. `AZURE_REGIONAL_HOST_SUFFIX` is appended because it is not any
#: posture's permitted host — it is the rejected-FOR-NOW form of one, and its clause in
#: `endpoint_failures` is what gives it a reason to be watched at all (see
#: `test_the_raw_transcript_host_is_deliberately_not_a_watched_host` for the rule this
#: obeys: a host with no clause behind it is cost with no check).
WATCHED_HOSTS: Final[tuple[str, ...]] = (*sorted(KNOWN_POSTURE_HOSTS), AZURE_REGIONAL_HOST_SUFFIX)


def _mentions_watched_host(text: str) -> bool:
    return any(host in text for host in WATCHED_HOSTS)


#: Endpoint hosts a `Settings` DEFAULT may not carry, ON TOP OF `WATCHED_HOSTS`.
#: Read by `console_config_failures` and by nothing else.
#:
#: TODAY THAT IS THE SARVAM CHAT HOST, and it is PROPHYLACTIC: no `Settings` field points
#: at it, so this clause guards a field nobody has written yet. It is here because
#: `managed_fields()` derives the console-editable set by SUBTRACTION — `Settings` minus
#: bootstrap keys minus credential-shaped names — so a future `sarvam_base_url` would be
#: editable from a web form the day it was declared, with nothing to notice. A text box
#: that re-points THIS leg is worse than one that re-points Azure's: Sarvam runs the first
#: post-call extraction over the RAW transcript (`GEMINI_EXTRACTION_DEFAULT is False`), so
#: the payload is caller PII rather than redacted prose.
#:
#: WHY IT IS NOT IN `WATCHED_HOSTS`, which is the obvious-looking place and was the wrong
#: suggestion. That tuple feeds `endpoint_failures`, and every failure clause there names
#: its OWN host and its own remedy — Azure's builder, the regional form, OpenAI-direct's
#: disqualification. A host with no clause of its own produces exactly zero findings
#: there. What adding it WOULD do is widen `SELF_DECLARATIONS`, i.e. grow the set of
#: strings this file exempts from its own scan, and pull the host into the docs-prose
#: machinery — cost with no check behind it. One reader, one constant, one clause.
SETTINGS_ENDPOINT_HOSTS: Final[tuple[str, ...]] = ("api.sarvam.ai",)


#: The strings `SELF` is allowed to spell: every watched host, plus the builder suffix it
#: grants the tree's one exemption FOR. Nothing is a URL and nothing carries a scheme —
#: see `_host_definition`. Derived, so a watched host this file could not declare would be
#: this file failing its own check rather than a silent hole.
SELF_DECLARATIONS: Final[tuple[str, ...]] = (*WATCHED_HOSTS, BUILDER_SUFFIX)


def _host_definition(template: str) -> bool:
    """Is this template the DECLARATION of a watched host rather than a use of one?

    Exactly the strings in `SELF_DECLARATIONS`, standing alone. `AZURE_HOST_SUFFIX: Final =
    ".openai.azure.com"` is the name this file watches things BY, and `BUILDER_SUFFIX` is
    the string it permits in `BUILDER_HOME`; judging either would report the watch as the
    violation.

    THE EXEMPTION IS A HANDFUL OF EXACT STRINGS, NOT A FILE — one per watched host plus
    the builder suffix, and `SELF_DECLARATIONS` derives them so the count follows the
    posture table rather than a comment. Not one of them has a scheme or a host label in
    front of it, so none of them is an endpoint — a URL written anywhere in this file is
    judged like any other file's, which matters because a guardrail is edited by whoever
    is relaxing the guardrail.

    Applied ONLY inside `SELF` (see that constant). Tree-wide it would be a real hole —
    `HOST = ".openai.azure.com"` followed by `f"https://x{HOST}/…"` is precisely the
    runtime-assembly shape "what this check cannot see" already admits to, and exempting
    the first half by name would turn an admitted blind spot into a supported idiom.
    """
    return template in SELF_DECLARATIONS


def _is_builder_suffix(reference: Reference, spec: PostureSpec) -> bool:
    """The ONE literal in the tree allowed to name an Azure host: the builder's suffix.

    THREE CONDITIONS, ALL OF THEM, and each one is load bearing. The right FILE, because
    the exemption is for the constructor and not for the string. The exact STRING, because
    a suffix that had grown a query parameter or lost `/v1` would be a different endpoint
    wearing the exemption. And `Final`, because a rebindable module global is a knob.
    """
    return (
        reference.path == BUILDER_HOME
        and reference.template == spec.builder_suffix
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
            "declaration belongs in the portability contract beside the builder it governs "
            "— that is where a reader checking residency looks, and where the runtime reads "
            "it from."
        ]
    return only.template, []


def _declared_record(source: str) -> dict[str, object] | None:
    """The keyword arguments of `DECLARED_POSTURE: Final = ResidencyPosture(...)`.

    Constants come back as their VALUES; anything else comes back as its unparsed SOURCE,
    because "the region came from `AZURE_LOCATION`" and "the region came from a literal
    beside it" are the same string to a value check and are not the same fact — the
    identical argument `_render` makes for f-string holes.
    """
    for node in ast.walk(ast.parse(source)):
        if (
            not isinstance(node, ast.AnnAssign)
            or not isinstance(node.target, ast.Name)
            or node.target.id != POSTURE_RECORD_CONSTANT
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


def declaration_failures(
    name: str, record: dict[str, object] | None = None, spec: PostureSpec | None = None
) -> list[str]:
    """Check 0: the declared name is one this guard knows, and the RECORD built from it says
    what that posture is supposed to say.

    THIS IS THE HALF THAT FAILS WHEN THE DECLARATION DRIFTS FROM THE CODE. Checks 1-4 fail
    when the code drifts from the declaration; this fails when somebody edits the
    declaration to describe a tree that has not moved — the cheaper and therefore likelier
    direction, because it is one line. `region=AZURE_LOCATION` under a posture that makes no
    regional claim, or `llm_provider="azure_openai"` under one that does not run on Azure,
    is a tree in two states at once and is refused here by name.
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
    fields = (
        _declared_record((REPO_ROOT / CONTRACT).read_text(encoding="utf-8"))
        if record is None
        else record
    )
    if fields is None:
        return [
            f"{CONTRACT} declares no `{POSTURE_RECORD_CONSTANT}: Final = ResidencyPosture("
            "...)` this check can read. The name alone is not the posture — the record is "
            "what the RUNTIME reads (`agents.service.in_call_llm`, `engine.bind_model`), so "
            "a name with no record beside it is a declaration nothing obeys."
        ]
    expected: dict[str, object] = {
        "name": DECLARATION_CONSTANT,
        "llm_provider": known.llm_provider,
        "region": known.region_constant,
        "addresses_a_deployment": known.addresses_a_deployment,
    }
    failures: list[str] = []
    for field, want in sorted(expected.items()):
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
    return failures


def declared_spec() -> PostureSpec:
    """The spec every check below defaults to.

    RAISES rather than falling back to a default posture, and the absence of a fallback is
    the point: "which posture is this tree in" has no safe default answer, and a guard that
    invented one would enforce a posture nobody declared. `main()` resolves the declaration
    FIRST and returns before any check runs, so in the shipped path this cannot fire; it is
    reachable only by calling a check directly against a tree whose declaration is broken,
    which is what `tests/residency_posture_test.py` does to it.
    """
    name, failures = declared_posture_name()
    if name is None or name not in POSTURES:
        raise RuntimeError(
            "the residency posture cannot be resolved, so no check below knows what it is "
            f"enforcing: {failures or [f'unknown posture {name!r}']}"
        )
    return POSTURES[name]


# --- 1: one spelling of the region --------------------------------------------


def frozen_region_constants(roots: Iterable[Path] | None = None) -> dict[str, tuple[str, str]]:
    """`NAME: Final = "<any region in KNOWN_REGIONS>"` — name to (file, region held).

    IT SCANS FOR EVERY KNOWN REGION AND CARRIES THE ONE IT FOUND, which is D-449's whole
    widening rather than a convenience. Until the posture moved, "the region" was one
    string, so a name and a file said everything; a scan for the DECLARED region alone
    would now report a leftover `AZURE_LOCATION: Final = "southindia"` as no region
    constant at all, and every check downstream would agree the tree spells its region
    once. Carrying the value is what lets `single_spelling_failures` say WHICH region is
    frozen and refuse it against the one the declaration pins.
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
    `def __init__(self, location: str = "eastus2")`, a default argument that reads like
    a pin and is one keyword away from not being one.

    STATED OVER `KNOWN_REGIONS` RATHER THAN OVER THE DECLARED ONE (D-449), because the
    loose literal a posture move leaves behind spells the region the tree just left, and a
    scan for the region it just arrived at would never look at it.
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
                    "than a `Final` constant's value. D-410 pins the region so it cannot "
                    "be varied per call site or per caller — reference "
                    f"`calevate_shared.engine.{REGION_CONSTANT}` instead. This matters "
                    "MORE than it did under Vertex, not less: the endpoint no longer "
                    "carries the region, so 'there is one spelling of it' is the whole of "
                    "what code can still say."
                )
    return failures


def single_spelling_failures(
    constants: Mapping[str, tuple[str, str]] | None = None, spec: PostureSpec | None = None
) -> list[str]:
    """Check 1, second half: outside this guard, `AZURE_LOCATION` in the portability
    contract is the ONLY frozen constant holding the region.

    STRICTER THAN THE VERTEX GUARD, WHICH ACCEPTED ANY `Final`, and the strictness is
    bought by the weakening. When the region appeared in every model URL, a second
    constant holding the same string was untidy and harmless — checks 2 and 4 read the
    URLs and would have caught a divergence the moment one was used. There are no such
    URLs now. A second constant is a second answer to "which region is this product in",
    with nothing downstream able to notice when the two stop agreeing.

    IT NOW JUDGES THE VALUE AND NOT ONLY THE NAME (D-449). While there was one known
    region, "a frozen constant named `AZURE_LOCATION`, in the contract" was the whole
    obligation, because there was nothing else it could be holding. Once a second region is
    knowable the name proves nothing: `AZURE_LOCATION: Final = "southindia"` under a
    declaration that says `us-azure-openai` is exactly the tree a half-finished posture move
    leaves, and it satisfies every name-shaped check ever written here.

    `SELF` is excluded because this file spells both known regions as its own canaries (see
    `AZURE_REGION_INDIA`), which is the not-imported doctrine and not a second decision.
    """
    posture = declared_spec() if spec is None else spec
    found = frozen_region_constants() if constants is None else constants
    shipped = {name: where for name, where in found.items() if where[0] != SELF}
    # THE INVERSION D-432 ADDED, and it is the half that makes the declaration mean
    # something. Under a posture that PINS a region there must be exactly one frozen
    # constant spelling it, in the contract. Under a posture that pins NONE there must be
    # ZERO — a leftover `AZURE_LOCATION` in a tree whose declaration has moved on is a
    # residency claim the product is no longer making, still sitting in the source a
    # reader (or an auditor) would check it against.
    if posture.region_constant is None:
        if not shipped:
            return []
        return [
            f"posture {posture.name!r} pins no region, but shipped code still "
            f"freezes one: {sorted(shipped.items())}. A region constant under a posture "
            "that makes no regional claim is a promise nothing keeps. Delete it, or "
            "declare the posture that actually holds."
        ]
    if shipped == {posture.region_constant: (BUILDER_HOME, posture.region)}:
        return []
    if not shipped:
        return [
            f"no shipped module defines `{posture.region_constant}: Final = "
            f"{posture.region!r}`. The "
            "region is the one residency fact this tree still states; if it has moved, "
            f"point `REGION_CONSTANT`/`BUILDER_HOME` at its new home deliberately, "
            "because every other check here reads it."
        ]
    # THE WRONG-REGION ARM IS SEPARATE FROM THE TWO-SPELLINGS ARM ON PURPOSE (D-449). They
    # are different defects with different fixes and, more to the point, different
    # consequences: two constants holding the SAME region is a tidiness failure that will
    # one day become a contradiction, while ONE constant holding a region the declaration
    # does not pin is the contradiction already — the tree quietly running (or claiming to
    # run) somewhere the declared posture, the DPA and the operations gates all say it does
    # not. A message that lumped them together would name neither region, and naming both
    # is the only way a reader can tell which half of the move was left undone.
    misplaced = {name: where for name, where in shipped.items() if where[1] != posture.region}
    if misplaced:
        return [
            f"posture {posture.name!r} pins the region {posture.region!r}, but shipped "
            f"code freezes a different one: "
            f"{sorted((name, held, home) for name, (home, held) in misplaced.items())}. "
            "This is what a half-finished posture move looks like — the declaration has "
            "moved and a constant has not, or the reverse. Whichever it is, the tree is "
            "asserting two regions at once and only one of them can be where the "
            "deployment is. Fix it DELIBERATELY: a region constant is not a rename."
        ]
    return [
        f"the region {posture.region!r} is frozen in more than one place, or somewhere "
        f"other than `{posture.region_constant}` in {BUILDER_HOME}: "
        f"{sorted(shipped.items())}. D-410 "
        "permits ONE spelling. Two constants holding the same region is two answers to "
        "where this product's models run, and — unlike under D-127 — no URL in this tree "
        "would reveal the day they stop agreeing."
    ]


# --- 3: no endpoint outside the one builder -----------------------------------


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
    """Does this label in a REGIONAL hostname name the region the declared posture pins?

    IT COMPARES THE CONSTANT'S VALUE, NOT MERELY THAT THE NAME IS FROZEN, and since D-449
    that is a real distinction rather than pedantry: `frozen` now holds every constant
    spelling any KNOWN region, so `{AZURE_LOCATION}` resolving to a frozen constant says
    nothing about WHICH region it resolves to. Accepting a name because it is frozen would
    wave through exactly the leftover-constant tree check 1 exists to refuse.

    `region is None` (a posture making no regional claim) accepts nothing: there is no
    region for a hostname to be carrying, so a regional hostname under such a posture is a
    claim the declaration does not make.
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
    """Check 3 over the literals the scan found, plus the two hosts that are refused outright.

    `frozen` and `allowances` are injectable for the reason
    `check_redaction_exposure.check`'s exemptions are: a guardrail whose exemptions cannot
    be taken away in a test is a guardrail nobody can prove still sees anything. `frozen`
    is unused while `REGIONAL_HOST_ADOPTED` is False and is NOT removed for it — it is the
    parameter the restored region check reads, and deleting it would make adopting the
    regional hostname a signature change in four places instead of one flag.
    """
    posture = declared_spec() if spec is None else spec
    constants = frozen_region_constants() if frozen is None else frozen
    permitted = ALLOWANCES if allowances is None else allowances
    failures: list[str] = []

    for reference in references:
        allowed = permitted.get(reference.path)
        #: Hosts already reported for THIS literal, so the general clause below cannot
        #: repeat a refusal one of the specific clauses has already made with its own
        #: reason. Same discipline as `console_config_failures`' `continue`s.
        reported: set[str] = set()

        # The OpenAI-direct ban is POSTURE-CONDITIONAL since D-432 and nothing else about
        # it moved. Under the declared India posture it is exactly the ban D-410 wrote.
        # Under a posture whose permitted host IS `api.openai.com` it would be banning the
        # endpoint the product runs on — so it stands down there and the single-literal
        # rule below takes over, which is the same rule Azure gets, not a weaker one.
        if (
            posture.permitted_host != OPENAI_DIRECT_HOST
            and OPENAI_DIRECT_HOST in reference.template
            and (allowed is None or allowed.host != OPENAI_DIRECT_HOST)
        ):
            reported.add(OPENAI_DIRECT_HOST)
            failures.append(
                f"{reference} names {OPENAI_DIRECT_HOST} — OpenAI's own API, which D-410 "
                "DISQUALIFIES on residency. Their India data residency covers storage at "
                "rest only; inference still runs in the US, and for a phone call the "
                "transcript IS the inference input. Azure OpenAI's v1 surface is "
                "OpenAI-compatible, which is exactly why this is one edited base URL away "
                f"— use {BUILDER}()."
            )

        for label in _labelled_hosts(reference.template, AZURE_REGIONAL_HOST_SUFFIX):
            if allowed is not None and allowed.host == AZURE_REGIONAL_HOST_SUFFIX:
                continue
            if not REGIONAL_HOST_ADOPTED:
                failures.append(
                    f"{reference} names Azure's REGIONAL host form "
                    f"({label or '{region}'}{AZURE_REGIONAL_HOST_SUFFIX}). D-410 ships the "
                    f"custom-subdomain form ({BUILDER}()) and records this one as "
                    "rejected-FOR-NOW: the OpenAI-compatible v1 surface is documented only "
                    "on the custom subdomain. It is not rejected on residency — it would "
                    "IMPROVE residency by putting the region back in the URL — so the way "
                    "in is OPERATIONS §2 gate 20d, then the builder, then "
                    "`REGIONAL_HOST_ADOPTED`, then a decision-log entry. Two endpoint "
                    "forms at once is two residency postures."
                )
                continue
            if not _region_ok(label, constants, posture.region):
                failures.append(
                    f"{reference} sends model traffic to region {label!r}. Posture "
                    f"{posture.name!r} permits {posture.region!r} only — literally, or "
                    f"through a `Final` constant holding THAT VALUE (known: "
                    f"{sorted(constants) or 'none'}). This is a residency change, not a "
                    "config change."
                )

        # THE WRONG-VENDOR RULE, stated over EVERY known posture's host rather than over
        # Azure's. It used to name `AZURE_HOST_SUFFIX` and nothing else, which was right
        # while Azure was the only host any posture could permit and became a hole the
        # moment a third vendor got a row: a Gemini endpoint literal under the declared
        # Azure posture matched no clause at all and fell through to the `continue` below,
        # so this guard refused a hand-written OpenAI URL and accepted a hand-written
        # Google one. Two things follow from stating it over `KNOWN_POSTURE_HOSTS`, and
        # the second is what makes the declaration bite: any vendor the table knows is
        # refused unless the declaration names it, and under any posture but Azure's the
        # Azure suffix stops being permitted AT ALL — including in the contract — so a
        # tree that still builds Azure endpoints cannot quietly wear a declaration saying
        # it does not.
        foreign = sorted(
            host
            for host in KNOWN_POSTURE_HOSTS - reported - {posture.permitted_host}
            if host in reference.template and (allowed is None or allowed.host != host)
        )
        if foreign:
            failures.append(
                f"{reference} names {', '.join(foreign)} — a model host this guard knows "
                f"as some posture's, and not the DECLARED posture's. {posture.name!r} "
                f"builds its endpoint with {posture.builder}() and permits only "
                f"{posture.permitted_host}. Either the tree has not been moved to the "
                "posture it declares, or the declaration was edited without the tree. "
                "Both are residency changes; neither is a tidy-up."
            )
            continue
        if posture.permitted_host not in reference.template:
            continue
        if _is_builder_suffix(reference, posture):
            continue
        if allowed is not None and allowed.host == posture.permitted_host:
            continue
        failures.append(
            f"{reference} builds an Azure OpenAI endpoint by hand. Exactly ONE literal in "
            f"this tree may name {posture.permitted_host} — the `Final` suffix "
            f"{posture.builder_suffix!r} in {BUILDER_HOME}, which {posture.builder}() "
            "assembles — and "
            "every other caller goes through that function. This is not tidiness: the "
            "resource name lands at the FRONT of the authority, so a hand-written "
            f"f-string is where `https://evil.example/x{AZURE_HOST_SUFFIX}/openai/v1` "
            "comes from, and the builder is the only thing that refuses it. It is also "
            "what check 4 rests on — a second constructor is a constructor nothing here "
            "has read."
        )

    return failures


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
    fields: Mapping[str, object] | None = None, managed: Iterable[str] | None = None
) -> list[str]:
    """No `Settings` field may carry a model region or a hand-typed model endpoint.

    Asserted against the WHOLE `Settings` model and not only against `managed_fields()`,
    because the console's editable set is DERIVED (`Settings.model_fields` minus the
    bootstrap keys minus credential-shaped names) — a new field is managed by default, so
    a check that read only the derived set would be reporting on a symptom.

    THIS IS THE CHECK D-410 DID NOT WEAKEN, and it is worth knowing that while reading the
    rest of this file. It never depended on the region appearing in a URL; it depends on
    the region having nowhere console-editable to live, which is as true of Azure as it
    was of Vertex.

    **IT IS ALSO THE CLAUSE THE CLIENT DPA POINTS AT.** `apps/web/src/lib/legal/dpa.ts`
    warrants that "no configuration setting may carry a region, an endpoint or a posture";
    the region and posture halves have always been vendor-neutral (`REGION_KNOB_FRAGMENTS`
    names no vendor), and the endpoint half was Azure-only until it was stated over
    `KNOWN_VENDOR_TOKENS`. That asymmetry meant the warranty's middle term stopped being
    enforced for any vendor the tree had not yet moved to — and, worse, for the vendor it
    had just moved off, which is the field a half-finished migration actually leaves
    behind. It is deliberately NOT stated over the DECLARED posture alone for that reason.
    """
    if fields is None or managed is None:
        live_fields, live_managed = live_settings()
        fields = live_fields if fields is None else fields
        managed = live_managed if managed is None else managed
    editable = set(managed)
    failures: list[str] = []
    for name, default in sorted(fields.items()):
        lowered = name.lower()
        where = "console-editable" if name in editable else "declared"
        if any(fragment in lowered for fragment in REGION_KNOB_FRAGMENTS):
            failures.append(
                f"Settings.{name} is {where} and its name says it holds a model region. "
                f"D-410 makes the region a frozen constant (`{REGION_CONSTANT}`) precisely "
                "so it cannot be changed from a web form at 3am — the same rule D-95 §4 "
                "applies to APP_ENV. Move it to a `Final` constant in code."
            )
            continue
        vendor = _endpoint_knob_vendor(lowered)
        word = next((fragment for fragment in ENDPOINT_KNOB_WORDS if fragment in lowered), None)
        if vendor is not None and word is not None:
            builders = sorted(
                {spec.builder for spec in POSTURES.values() if vendor in spec.vendor_tokens}
            )
            failures.append(
                f"Settings.{name} is {where} and its name pairs the model vendor "
                f"{vendor!r} with the endpoint word {word!r} — it holds a model ENDPOINT, "
                f"in a text box. That vendor's endpoint has exactly one constructor in "
                f"this tree ({', '.join(f'{one}()' for one in builders)}), and a console "
                "field beside it is a second one — check 3 exists to make sure there is "
                "only ever the one. Store the vendor's ACCOUNT-shaped inputs (a resource "
                "id, a key, a deployment name) and let the builder assemble the URL. "
                "THE VENDOR DOES NOT HAVE TO BE THE DECLARED ONE and this is checked "
                f"against every posture's ({sorted(KNOWN_VENDOR_TOKENS)}): the field a "
                "half-finished posture move leaves behind names the vendor the tree just "
                "LEFT, so a check that knew only the declared vendor would be blind to "
                "exactly the case it exists for."
            )
            continue
        if isinstance(default, str) and any(host in default for host in SETTINGS_ENDPOINT_HOSTS):
            # BEFORE the watched-host clause and with its own `continue`, so the two never
            # report one field twice. See `SETTINGS_ENDPOINT_HOSTS` for why this host is
            # deliberately absent from `WATCHED_HOSTS` and therefore from every other
            # check in this file.
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


# --- 4: the builder cannot emit a region other than the declared one ----------


def _is_pattern_guarded_raise(node: ast.AST, arguments: set[str]) -> bool:
    """An `if` that raises, guarded by a `fullmatch`/`match` call on the builder's argument.

    WHAT THIS IS DISTINGUISHING, because "the builder raises" sounds like enough and is
    not. `if not resource: raise` is a presence check and accepts `"evil.example/x"` — the
    one input the refusal exists for. `if not _RE.fullmatch(resource): raise` is a SHAPE
    check. Both contain an `ast.Raise`, so the coarse check passes either, and the
    difference is the whole security property.

    It still cannot prove the predicate can FIRE — see `builder_failures`. It is aimed at
    the realistic regression (somebody simplifies the guard) rather than at a contrived
    one, and the runtime test named there is what covers the rest.
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


def builder_failures(source: str | None = None, spec: PostureSpec | None = None) -> list[str]:
    """Check 4, read off `azure_openai_base_url` itself.

    THE CHECK THAT REPLACED "the region in the URL is Mumbai", and it answers a different
    question because Azure only permits a different question. There is no region in the URL
    to judge, so what is judged is that **there is no region INPUT**: one parameter, not
    region-shaped, interpolated with nothing but module `Final`s, and refused unless it is
    a single DNS label. A builder shaped like that has no OTHER region to emit, which
    is a structural argument rather than an evidential one — and saying which of the two
    you have is the whole point of this file's rewrite.

    THE WORDING USED TO NAME INDIA, AND THAT WAS A LATENT FALSEHOOD RATHER THAN A TYPO.
    Check 4 never proved anything about a COUNTRY: it proves the builder admits no region
    input, so whatever region the declared posture pins is the only one constructible.
    D-449 moved the declared region from `southindia` to `eastus2` and this function needed
    no edit — which is the proof the property was always singularity. The prose survived
    the move naming a country the tree had left, so a reader checking whether the guard
    still meant what it said would have found it asserting the opposite of the posture.

    THE DNS-LABEL REFUSAL IS PART OF CHECK 4 AND NOT A SEPARATE CONCERN. `VERTEX_LOCATION`
    sat at the FRONT of its host, so whatever a caller interpolated after it landed in a
    PATH and the host stayed Google's. Azure's custom subdomain puts the CALLER'S value at
    the very front of the authority, so a builder that interpolated freely would let
    `resource = "evil.example/x"` produce a URL whose host is somebody else's and whose
    tail merely reads like Azure — a region change and a vendor change in one string.

    ⚠ **THIS IS A SHAPE CHECK AND IT CANNOT PROVE THE REFUSAL IS EFFECTIVE**, which was
    learned by sabotaging it rather than by reasoning about it. It asserts that a `raise`
    exists and that it is guarded by a pattern match on the argument; a guard rewritten to
    `if False and not _RE.fullmatch(resource)` keeps both and refuses nothing, and no
    amount of AST reading distinguishes a predicate that can fire from one that cannot.
    THE BEHAVIOUR IS PROVED ELSEWHERE AND DELIBERATELY: `tests/in_call_llm_provider_test
    .py::test_a_resource_that_is_not_one_dns_label_is_refused_rather_than_interpolated`
    CALLS the builder with the attack strings and requires a `ValueError`. Between the two
    there is a static check on the shape and a runtime check on the effect, which is the
    same split `ModelConfig._llm_endpoint_is_coherent` and this whole file already make.

    `source` is injectable so the negative controls can hand it a builder that has grown a
    `location=` parameter, which the real file cannot be made to do without editing it.
    """
    posture = declared_spec() if spec is None else spec
    text = (REPO_ROOT / BUILDER_HOME).read_text(encoding="utf-8") if source is None else source
    tree = ast.parse(text)
    frozen_names = {
        node.target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and _is_final(node.annotation)
    }
    builder = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == posture.builder
        ),
        None,
    )
    if builder is None:
        return [
            f"{BUILDER_HOME} defines no `{posture.builder}()`. It is the ONE constructor "
            f"posture {posture.name!r} permits for a model endpoint, and the thing "
            "check 3's single exemption is granted "
            "for; if it has been renamed or moved, this file has to be pointed at it "
            "deliberately, because a guard that cannot find its subject has verified "
            "nothing."
        ]

    failures: list[str] = []
    arguments = builder.args
    positional = [argument.arg for argument in (*arguments.posonlyargs, *arguments.args)]
    extra = [argument.arg for argument in arguments.kwonlyargs]
    if arguments.vararg is not None:
        extra.append(f"*{arguments.vararg.arg}")
    if arguments.kwarg is not None:
        extra.append(f"**{arguments.kwarg.arg}")
    if len(positional) != posture.builder_arity or extra:
        failures.append(
            f"{posture.builder}() takes {positional + extra} — the declared posture "
            f"permits exactly {posture.builder_arity}. Every extra parameter is a way for a "
            "caller to vary the "
            "endpoint, and the endpoint is the only thing standing between our "
            "configuration and where a third party sends a client's caller's words."
        )
    for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs):
        if any(fragment in argument.arg.lower() for fragment in REGION_KNOB_FRAGMENTS):
            failures.append(
                f"{posture.builder}() takes a parameter named {argument.arg!r}. The builder "
                "must "
                "have NO region input at all — that absence is the whole of check 4, "
                f"because `{REGION_CONSTANT}` cannot be the only spelling of the region if "
                "a caller can pass another one. Azure's endpoint has nowhere to put a "
                "region anyway; a parameter that changed nothing would be worse than its "
                "absence."
            )

    # THE DNS-LABEL REFUSAL IS REQUIRED ONLY WHERE THERE IS A CALLER INPUT TO REFUSE.
    # It exists because Azure puts the caller's resource at the FRONT of the authority; a
    # posture whose builder takes no argument has no hostile label to interpolate, and
    # demanding a raise there would be a check with no failure mode.
    if posture.builder_arity and not any(isinstance(node, ast.Raise) for node in ast.walk(builder)):
        failures.append(
            f"{posture.builder}() never raises. It must REFUSE a resource that is not a "
            "single DNS "
            "label rather than interpolate it: the resource lands at the front of the "
            f"authority, so `https://evil.example/x{AZURE_HOST_SUFFIX}/openai/v1` is a URL "
            "whose HOST is an attacker's and whose tail merely reads like ours."
        )
    elif posture.builder_arity and not any(
        _is_pattern_guarded_raise(node, set(positional)) for node in ast.walk(builder)
    ):
        failures.append(
            f"{posture.builder}() raises, but not behind a pattern match on {positional}. A "
            "refusal "
            "conditioned on emptiness or on `None` accepts `evil.example/x`, which is the "
            "only input that matters — the resource becomes the first label of the "
            "hostname, so what has to be checked is its SHAPE, against a regex, not its "
            "presence. (This check reads the shape and cannot prove the predicate can "
            "fire; `tests/in_call_llm_provider_test.py` calls the builder with the attack "
            "strings and is what proves that.)"
        )

    returns = [node for node in ast.walk(builder) if isinstance(node, ast.Return)]
    if not returns:
        failures.append(f"{posture.builder}() returns nothing this check can read.")
    permitted_holes = set(positional) | frozen_names
    for statement in returns:
        value = statement.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            continue
        if not isinstance(value, ast.JoinedStr):
            failures.append(
                f"{posture.builder}() line {statement.lineno} returns an expression that is "
                "not a "
                "string template, so this check cannot tell what URL it produces. Build "
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
                    f"{posture.builder}() line {statement.lineno} interpolates {hole!r} "
                    "into the "
                    f"endpoint. Only the resource argument and module-level `Final`s may "
                    f"appear (known: {sorted(permitted_holes)}). Anything else is a value "
                    "computed at runtime, which is exactly the shape this file says under "
                    "'what this check cannot see' that it is blind to."
                )
    return failures


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
    failures: list[str] = []
    if templates < MINIMUM_TEMPLATES:
        failures.append(
            f"the AST walk found only {templates} string templates across {SCANNED_TREES} "
            "— it is blind. Fix the scan rather than lowering MINIMUM_TEMPLATES."
        )
    # THE PARSE CANARY IS NOW ONE PROBE PER KNOWN REGION (D-449), which is strictly stronger
    # than the single `AZURE_REGION` probe it replaces AND keeps working where that one
    # would have gone dark. This file defines a `Final` for every region in `KNOWN_REGIONS`,
    # so every one of them must come back from the scan of `SELF`; a scan that found the
    # declared region and missed the withdrawn one is precisely the half-blind scan that
    # would report a leftover constant as absent. The old probe also had a failure of its
    # own: under a posture pinning NO region it asserted a constant this file might not
    # define, so it could only ever be right for as long as the declared posture pinned
    # something.
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
    # The SUBJECT canary is posture-conditional: under a posture that pins no region
    # there is no region constant to find, and its ABSENCE is what
    # `single_spelling_failures` requires instead. Asserting presence unconditionally
    # would make the guard demand a residency claim the declaration does not make.
    if posture.region_constant is not None and posture.region_constant not in constants:
        failures.append(
            f"the scan cannot find `{posture.region_constant}: Final` in shipped code. That "
            "is the "
            "SUBJECT canary rather than the parse canary: the KNOWN_REGIONS probe above "
            "proves this "
            "file can still read a `Final`, and this proves there is still a residency "
            "decision in the tree for it to be reading."
        )
    if not list(references):
        failures.append(
            "no literal anywhere in the tree mentions an Azure OpenAI host — not even the "
            f"builder's own `Final` suffix in {BUILDER_HOME}. Either the scan stopped "
            "reading files, or the one constructor this check is built around has gone."
        )
    return failures


# --- 6: the half a human owns is written down ---------------------------------


#: Where the two facts this file cannot prove are owned. Named as data because
#: `delegation_failures` reads it and `main()` prints it, and a delegation stated in two
#: places is one that will eventually name two different gates.
OPERATIONS_DOC: Final = "docs/OPERATIONS.md"


def delegated_notice(spec: PostureSpec) -> str:
    """What a green run of this check does NOT cover, in the DECLARED posture's own region.

    A FUNCTION SINCE D-449, and it had to become one: it names the region, and the region
    is a property of the posture rather than of this file. As a module `Final` it read the
    one region that was hard-wired, so under any other declaration it would have printed
    the wrong region under a green result — a guard telling a reader the opposite of what
    it had just verified, in the one paragraph a reader relies on for what was NOT verified.

    IT SAYS THE WITHDRAWAL OUT LOUD. Anyone who has read the old text will supply the old
    meaning — "the models run in India, a human just has to confirm it" — from memory, and
    a notice that merely swapped one region name into the same sentence would let them.
    D-449 did not improve residency; it gave the claim up.
    """
    return (
        f"NOT PROVED HERE, AND NO VERSION OF THIS CHECK CAN PROVE IT: that the Azure "
        f"resource named by `azure_openai_resource` is in {spec.region}, and that its "
        f"deployment is REGIONAL Standard rather than GLOBAL. Both are properties of the "
        f"RESOURCE, invisible in `https://<resource>{AZURE_HOST_SUFFIX}/openai/v1`; Global "
        f"is Azure's DEFAULT deployment type and processes worldwide. A human confirms both "
        f"once in the Azure portal — {OPERATIONS_DOC} §2 gates 20 and 20c — and files the "
        f"reading in docs/evidence/. Under D-127 this file proved the region from the AST. "
        f"It no longer can, and that is D-410's recorded cost rather than an oversight. "
        f"⚠ AND UNDER D-449 THE REGION IT DELEGATES IS NO LONGER AN INDIAN ONE: the India "
        f"residency claim was WITHDRAWN, not upgraded. Gates 20/20c now confirm a US "
        f"resource; nothing in this tree promises a client that their callers' words stay "
        f"in India, and any document that still does is out of date."
    )


def delegation_failures(document: str | None = None, spec: PostureSpec | None = None) -> list[str]:
    """Check 6: the fact this guard gave up is written down somewhere a human owns it.

    WHY A GUARDRAIL CHECKS A DOCUMENT. Because the failure this whole rewrite is trying to
    avoid is not "the region is wrong" — it is "the region is nobody's job and the build is
    green". A weakened check plus a live gate is an honest posture; a weakened check plus a
    deleted gate is the same green output covering strictly less, which is the defect class
    this repository keeps finding. If somebody tidies gates 20/20c away, this line is what
    makes the tidying visible in CI instead of in an audit.

    Deliberately LOOSE about wording and strict about substance: it wants a line naming the
    constant under test and the place a human looks. Pinning the gate's prose would make
    every rewording of an operations document a red build, which is how a check gets
    deleted rather than corrected.
    """
    posture = declared_spec() if spec is None else spec
    if posture.delegated_gate is None:
        return []
    constant, word = posture.delegated_gate
    text = (
        (REPO_ROOT / OPERATIONS_DOC).read_text(encoding="utf-8") if document is None else document
    )
    if any(constant in line and word in line.lower() for line in text.splitlines()):
        return []
    return [
        f"{OPERATIONS_DOC} carries no gate naming `{constant}` and the Azure portal. "
        "That gate is where the residency fact this check CANNOT prove is confirmed by a "
        "person, so without it the tree asserts a region nobody has ever read and this "
        "script prints OK over the gap. Restore the gate (20: the resource's Location; "
        "20c: Regional rather than Global deployment) or, if the posture genuinely changed, "
        "change it here deliberately with a decision-log entry."
    ]


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
    )
    if failures:
        print("MODEL RESIDENCY: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        # THE EPILOGUE IS POSTURE-AWARE, and it has to be: it used to state D-410's
        # posture as a fact, which under any other declaration would be the guard telling
        # a reader the opposite of what it had just refused.
        print(
            f"\nDECLARED POSTURE {posture.name!r} ({DECLARATION_CONSTANT} in {CONTRACT}): "
            f"{posture.warrant}. If a second endpoint or a second spelling is genuinely "
            "needed for a bounded reason, it belongs in ALLOWANCES in this script WITH the "
            "date and the work that removes it — never as a silent skip. If the POSTURE "
            f"itself is meant to change, that is the `PostureSpec` in {SELF}, this "
            "declaration, and a decision-log entry — together, in one reviewed commit."
        )
        if posture.delegated_gate is not None:
            print(f"\n{delegated_notice(posture)}")
        return 1

    print(
        f"MODEL RESIDENCY: OK — declared posture {name!r} ({templates} string templates "
        f"scanned; {len(references)} model host literal(s) judged and only "
        f"{posture.builder}()'s own suffix permitted; {len(ALLOWANCES)} dated allowance(s) "
        "still current)"
    )
    print(f"  what that proves under this posture: {posture.warrant}.")
    if posture.delegated_gate is None:
        return 0
    print(f"\n{delegated_notice(posture)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
