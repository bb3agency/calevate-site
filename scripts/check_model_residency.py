"""Guardrail: this tree cannot construct an Azure OpenAI endpoint except through the one
builder, and the region it is pinned to has exactly one spelling in code (D-410).

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

1. **ONE SPELLING OF THE REGION.** `AZURE_LOCATION: Final = "southindia"` in the
   portability contract is the only place the region is written. A second `Final`, a
   default argument, a dict value — anything else spelling it is refused. Stricter than
   the Vertex version, which permitted any `Final`: with the region no longer checkable
   against a URL, "there is one of it" is doing more of the work and has to hold harder.
2. **NO `Settings` FIELD CAN CARRY A REGION**, by NAME or by default VALUE, and none can
   carry a hand-typed Azure endpoint either. `platform_config.managed_fields()` derives
   the ops console's editable set from `Settings.model_fields` minus the bootstrap keys
   minus credential-shaped names, so a field called `azure_location` would be editable
   from a web form the day it was declared, and a residency posture invertible by a click
   at 3am is not a posture. This property is UNCHANGED from D-127 and is the one part of
   the old guard that lost nothing in the migration.
3. **NO AZURE ENDPOINT IS CONSTRUCTIBLE EXCEPT THROUGH `azure_openai_base_url()`.**
   Exactly ONE string literal in `apps/`, `packages/` and `scripts/` may contain an Azure
   OpenAI host: the `Final` suffix that builder is assembled from. Every other literal
   naming one is a second way to build an endpoint, which is the shape check 4 could then
   say nothing about.
4. **THE BUILDER CANNOT EMIT A NON-INDIA REGION.** It takes ONE argument, that argument is
   not region-shaped, its output template interpolates only that argument and module-level
   `Final`s, and it RAISES rather than interpolating a resource that is not a single DNS
   label. There is no region input, so there is no non-India region to emit — and because
   the resource lands at the FRONT of the authority, refusing anything but a DNS label is
   what stops `resource = "evil.example/x"` producing a URL whose host is somebody else's.

WHAT NO VERSION OF THIS CHECK CAN PROVE, AND WHO OWNS IT INSTEAD. Two facts, both
properties of the Azure resource rather than of this repository, both invisible from the
endpoint, and the second is the more dangerous:

* **Is the resource in `southindia`?** OPERATIONS §2 **gate 20** — a human reads the
  Location field on the resource's Overview blade, confirms it with
  `az cognitiveservices account show --query location`, and files the reading in
  `docs/evidence/` with a date and a name.
* **Is the deployment REGIONAL Standard rather than GLOBAL?** OPERATIONS §2 **gate 20c**.
  Global is Azure's DEFAULT deployment type and processes worldwide. A Global deployment
  inside a South India resource passes every check in this file and is a residency breach.
  It costs money to get right (Regional runs ~5-10% above Global list), which is precisely
  why nobody will notice having left the default.

`delegation_failures()` is not decoration: it fails this build if those gates stop being
written down, because the honest half of a weakened guard is the pointer to whoever holds
the other half.

THE REGIONAL HOSTNAME, AND WHY THIS FILE IS BUILT SO ADOPTING IT IS ONE LINE. Azure also
serves `southindia.api.cognitive.microsoft.com`, documented as interchangeable with the
custom subdomain — a hostname that CARRIES THE REGION, which would hand check 1 back its
evidence and make this guard as strong as the Vertex one was. D-410 rejects it FOR NOW on
one ground: the OpenAI-compatible v1 surface is documented only on the custom-subdomain
form (and custom subdomains are what Entra ID requires), so shipping it would trade a
confirmed-working endpoint for a stronger guard on an unconfirmed one. **OPERATIONS §2
gate 20d is the call that settles it**, and the machinery is already here and already
tested: flip `REGIONAL_HOST_ADOPTED`, and the same scan that today REFUSES that hostname
starts requiring the label in front of it to be `AZURE_LOCATION`. Both branches are
exercised by `tests/model_residency_guard_test.py`, so the dormant one is not a promise.

WHY THERE IS NO BLACKLIST OF OTHER AZURE REGIONS (`eastus`, `swedencentral` — the two a
reader will reach for, since they are `gpt-4.1-mini`'s default quota regions). It was the
obvious replacement for the `us-central1` check and it is unreachable: a region string can
only affect where a call lands by reaching an endpoint, no endpoint is constructible
outside the builder (check 3), and the builder has no region input (check 4). A ban on
strings that cannot reach anything is a check with no failure mode, and it would rot into
"add your region to the list" the first time somebody names a variable after a datacentre.

MECHANISM: the Python half reads the **AST**, not the source text, and reconstructs
f-strings into templates (`f"https://{X}{SUFFIX}"` becomes `https://{X}{SUFFIX}` with each
hole carrying the interpolated expression's source). Two reasons, both learned here. First,
`sarvam_model_identifier_test`'s: a correction has to be EXPLAINED somewhere, and a regex
over source flags the paragraph explaining it — this very docstring names all three watched
hosts. Second, provenance: "the region came from `AZURE_LOCATION`" and "the region came
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

#: The ONLY region D-410 permits. Spelled HERE rather than imported, for the reason
#: `check_bootstrap_keys.BOOTSTRAP_KEYS` gives: a guardrail that imported the value it is
#: checking would be asking the code whether it agrees with itself. It is also this
#: check's own blindness canary (check 5) — the provenance scan must be able to find this
#: line, or it is not reading anything.
AZURE_REGION: Final = "southindia"

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
#: SPELLED HERE RATHER THAN IMPORTED, like `AZURE_REGION`, and it buys something extra: the
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

#: WOULD THE REGIONAL HOSTNAME RESTORE THE AST PROOF? Yes — and this flag is the whole
#: cost of adopting it, which is why the machinery below is written now rather than
#: promised. `False`: naming `AZURE_REGIONAL_HOST_SUFFIX` in shipped code is a failure,
#: because D-410 ships the custom subdomain and a second endpoint form would be a second
#: residency posture. `True`: it becomes the EXPECTED form and the label in front of it is
#: checked against `AZURE_REGION` — check 1's lost evidence, back.
#:
#: FLIPPING IT IS NOT THE WHOLE CHANGE and the comment says so rather than letting somebody
#: find out: gate 20d has to pass first (does v1 actually answer there), then
#: `azure_openai_base_url()` moves to the regional form, then this flag, then a decision-log
#: entry naming the gate as the evidence. What the flag buys is that the GUARD is not the
#: thing standing in the way, and that the stronger branch is tested before it is needed.
REGIONAL_HOST_ADOPTED: Final = False

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
#: cannot run without. `ENDPOINT_KNOB_FRAGMENTS` below is what took over the part of that
#: job which still makes sense.
REGION_KNOB_FRAGMENTS: Final[tuple[str, ...]] = (
    "region",
    "location",
    "residency",
    "datacenter",
)

#: Fragment PAIRS that would make a `Settings` field a hand-typed Azure endpoint: a name
#: carrying the vendor AND a URL word. Check 3 says the endpoint has exactly one
#: constructor; a console field called `azure_openai_base_url` would be a second one, made
#: of a text box.
#:
#: A PAIR RATHER THAN "url", because plenty of settings are legitimately URLs (webhooks,
#: the engine's own base) and banning the word would be a check people route around by
#: renaming. The vendor's name beside it is what makes the intent unambiguous.
ENDPOINT_KNOB_FRAGMENTS: Final[tuple[tuple[str, str], ...]] = (
    ("azure", "url"),
    ("azure", "endpoint"),
    ("azure", "host"),
)


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

    A plain `x: str = "southindia"` is NOT frozen: `Final` is what mypy strict (a CI gate
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


#: The hosts a literal has to mention before this check has an opinion about it.
WATCHED_HOSTS: Final[tuple[str, ...]] = (
    AZURE_HOST_SUFFIX,
    AZURE_REGIONAL_HOST_SUFFIX,
    OPENAI_DIRECT_HOST,
)


def _mentions_watched_host(text: str) -> bool:
    return any(host in text for host in WATCHED_HOSTS)


#: The strings `SELF` is allowed to spell: the three watched hosts, plus the builder
#: suffix it grants the tree's one exemption FOR. Nothing is a URL and nothing carries a
#: scheme — see `_host_definition`.
SELF_DECLARATIONS: Final[tuple[str, ...]] = (*WATCHED_HOSTS, BUILDER_SUFFIX)


def _host_definition(template: str) -> bool:
    """Is this template the DECLARATION of a watched host rather than a use of one?

    Exactly the strings in `SELF_DECLARATIONS`, standing alone. `AZURE_HOST_SUFFIX: Final =
    ".openai.azure.com"` is the name this file watches things BY, and `BUILDER_SUFFIX` is
    the string it permits in `BUILDER_HOME`; judging either would report the watch as the
    violation.

    THE EXEMPTION IS FOUR EXACT STRINGS, NOT A FILE. Not one of them has a scheme or a
    host label in front of it, so none of them is an endpoint — a URL written anywhere in
    this file is judged like any other file's, which matters because a guardrail is edited
    by whoever is relaxing the guardrail.

    Applied ONLY inside `SELF` (see that constant). Tree-wide it would be a real hole —
    `HOST = ".openai.azure.com"` followed by `f"https://x{HOST}/…"` is precisely the
    runtime-assembly shape "what this check cannot see" already admits to, and exempting
    the first half by name would turn an admitted blind spot into a supported idiom.
    """
    return template in SELF_DECLARATIONS


def _is_builder_suffix(reference: Reference) -> bool:
    """The ONE literal in the tree allowed to name an Azure host: the builder's suffix.

    THREE CONDITIONS, ALL OF THEM, and each one is load bearing. The right FILE, because
    the exemption is for the constructor and not for the string. The exact STRING, because
    a suffix that had grown a query parameter or lost `/v1` would be a different endpoint
    wearing the exemption. And `Final`, because a rebindable module global is a knob.
    """
    return (
        reference.path == BUILDER_HOME and reference.template == BUILDER_SUFFIX and reference.frozen
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


# --- 1: one spelling of the region --------------------------------------------


def frozen_region_constants(roots: Iterable[Path] | None = None) -> dict[str, str]:
    """`NAME: Final = "southindia"` across the tree — name to the file that defines it."""
    constants: dict[str, str] = {}
    for path in _files(roots, frozenset({".py"})):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.value is not None
                and isinstance(node.value, ast.Constant)
                and node.value.value == AZURE_REGION
                and _is_final(node.annotation)
            ):
                constants[node.target.id] = _rel(path)
    return constants


def loose_region_literals(roots: Iterable[Path] | None = None) -> list[str]:
    """Check 1, first half: a bare `"southindia"` that is NOT a `Final` constant's value.

    The shape this is really aimed at is not a second constant — it is
    `def __init__(self, location: str = "southindia")`, a default argument that reads like
    a pin and is one keyword away from not being one.
    """
    failures: list[str] = []
    for path in _files(roots, frozenset({".py"})):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        frozen = _frozen_value_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and node.value == AZURE_REGION
                and id(node) not in frozen
            ):
                failures.append(
                    f"{_rel(path)}:{node.lineno} spells {AZURE_REGION!r} somewhere other "
                    "than a `Final` constant's value. D-410 pins the region so it cannot "
                    "be varied per call site or per caller — reference "
                    f"`calevate_shared.engine.{REGION_CONSTANT}` instead. This matters "
                    "MORE than it did under Vertex, not less: the endpoint no longer "
                    "carries the region, so 'there is one spelling of it' is the whole of "
                    "what code can still say."
                )
    return failures


def single_spelling_failures(constants: Mapping[str, str] | None = None) -> list[str]:
    """Check 1, second half: outside this guard, `AZURE_LOCATION` in the portability
    contract is the ONLY frozen constant holding the region.

    STRICTER THAN THE VERTEX GUARD, WHICH ACCEPTED ANY `Final`, and the strictness is
    bought by the weakening. When the region appeared in every model URL, a second
    constant holding the same string was untidy and harmless — checks 2 and 4 read the
    URLs and would have caught a divergence the moment one was used. There are no such
    URLs now. A second constant is a second answer to "which region is this product in",
    with nothing downstream able to notice when the two stop agreeing.

    `SELF` is excluded because this file spells the region as its own canary (see
    `AZURE_REGION`), which is the not-imported doctrine and not a second decision.
    """
    found = frozen_region_constants() if constants is None else constants
    shipped = {name: home for name, home in found.items() if home != SELF}
    if shipped == {REGION_CONSTANT: BUILDER_HOME}:
        return []
    if not shipped:
        return [
            f"no shipped module defines `{REGION_CONSTANT}: Final = {AZURE_REGION!r}`. The "
            "region is the one residency fact this tree still states; if it has moved, "
            f"point `REGION_CONSTANT`/`BUILDER_HOME` at its new home deliberately, "
            "because every other check here reads it."
        ]
    return [
        f"the region {AZURE_REGION!r} is frozen in more than one place, or somewhere other "
        f"than `{REGION_CONSTANT}` in {BUILDER_HOME}: {sorted(shipped.items())}. D-410 "
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


def _region_ok(token: str, frozen: Mapping[str, str]) -> bool:
    if token == AZURE_REGION:
        return True
    if token.startswith("{") and token.endswith("}"):
        return token[1:-1].strip() in frozen
    return False


def endpoint_failures(
    references: Iterable[Reference],
    frozen: Mapping[str, str] | None = None,
    allowances: Mapping[str, DatedAllowance] | None = None,
) -> list[str]:
    """Check 3 over the literals the scan found, plus the two hosts that are refused outright.

    `frozen` and `allowances` are injectable for the reason
    `check_redaction_exposure.check`'s exemptions are: a guardrail whose exemptions cannot
    be taken away in a test is a guardrail nobody can prove still sees anything. `frozen`
    is unused while `REGIONAL_HOST_ADOPTED` is False and is NOT removed for it — it is the
    parameter the restored region check reads, and deleting it would make adopting the
    regional hostname a signature change in four places instead of one flag.
    """
    constants = frozen_region_constants() if frozen is None else frozen
    permitted = ALLOWANCES if allowances is None else allowances
    failures: list[str] = []

    for reference in references:
        allowed = permitted.get(reference.path)

        if OPENAI_DIRECT_HOST in reference.template and (
            allowed is None or allowed.host != OPENAI_DIRECT_HOST
        ):
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
            if not _region_ok(label, constants):
                failures.append(
                    f"{reference} sends model traffic to region {label!r}. D-410 permits "
                    f"{AZURE_REGION!r} only — literally, or through a `Final` constant "
                    f"holding it (known: {sorted(constants) or 'none'}). This is a "
                    "residency change, not a config change."
                )

        if AZURE_HOST_SUFFIX not in reference.template:
            continue
        if _is_builder_suffix(reference):
            continue
        if allowed is not None and allowed.host == AZURE_HOST_SUFFIX:
            continue
        failures.append(
            f"{reference} builds an Azure OpenAI endpoint by hand. Exactly ONE literal in "
            f"this tree may name {AZURE_HOST_SUFFIX} — the `Final` suffix "
            f"{BUILDER_SUFFIX!r} in {BUILDER_HOME}, which {BUILDER}() assembles — and "
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
    """No `Settings` field may carry a model region or a hand-typed Azure endpoint.

    Asserted against the WHOLE `Settings` model and not only against `managed_fields()`,
    because the console's editable set is DERIVED (`Settings.model_fields` minus the
    bootstrap keys minus credential-shaped names) — a new field is managed by default, so
    a check that read only the derived set would be reporting on a symptom.

    THIS IS THE CHECK D-410 DID NOT WEAKEN, and it is worth knowing that while reading the
    rest of this file. It never depended on the region appearing in a URL; it depends on
    the region having nowhere console-editable to live, which is as true of Azure as it
    was of Vertex.
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
        if any(vendor in lowered and word in lowered for vendor, word in ENDPOINT_KNOB_FRAGMENTS):
            failures.append(
                f"Settings.{name} is {where} and its name says it holds an Azure OpenAI "
                f"endpoint. There is exactly one constructor for that URL, {BUILDER}(), "
                "and a console text box beside it is a second one — check 3 in this file "
                f"exists to make sure there is only ever the one. Store the RESOURCE "
                "(`azure_openai_resource`) and let the builder assemble the rest."
            )
            continue
        if isinstance(default, str) and (
            _mentions_watched_host(default) or default == AZURE_REGION
        ):
            failures.append(
                f"Settings.{name} defaults to a model endpoint or a region ({default!r}). "
                "Whatever its name says, it is the residency knob."
            )
    return failures


# --- 4: the builder cannot emit a non-India region ----------------------------


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


def builder_failures(source: str | None = None) -> list[str]:
    """Check 4, read off `azure_openai_base_url` itself.

    THE CHECK THAT REPLACED "the region in the URL is Mumbai", and it answers a different
    question because Azure only permits a different question. There is no region in the URL
    to judge, so what is judged is that **there is no region INPUT**: one parameter, not
    region-shaped, interpolated with nothing but module `Final`s, and refused unless it is
    a single DNS label. A builder shaped like that has no non-India region to emit, which
    is a structural argument rather than an evidential one — and saying which of the two
    you have is the whole point of this file's rewrite.

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
            if isinstance(node, ast.FunctionDef) and node.name == BUILDER
        ),
        None,
    )
    if builder is None:
        return [
            f"{BUILDER_HOME} defines no `{BUILDER}()`. It is the ONE constructor for an "
            "Azure OpenAI endpoint and the thing check 3's single exemption is granted "
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
    if len(positional) != 1 or extra:
        failures.append(
            f"{BUILDER}() takes {positional + extra} — it must take exactly one argument, "
            "the resource name. Every extra parameter is a way for a caller to vary the "
            "endpoint, and the endpoint is the only thing standing between our "
            "configuration and where a third party sends a client's caller's words."
        )
    for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs):
        if any(fragment in argument.arg.lower() for fragment in REGION_KNOB_FRAGMENTS):
            failures.append(
                f"{BUILDER}() takes a parameter named {argument.arg!r}. The builder must "
                "have NO region input at all — that absence is the whole of check 4, "
                f"because `{REGION_CONSTANT}` cannot be the only spelling of the region if "
                "a caller can pass another one. Azure's endpoint has nowhere to put a "
                "region anyway; a parameter that changed nothing would be worse than its "
                "absence."
            )

    if not any(isinstance(node, ast.Raise) for node in ast.walk(builder)):
        failures.append(
            f"{BUILDER}() never raises. It must REFUSE a resource that is not a single DNS "
            "label rather than interpolate it: the resource lands at the front of the "
            f"authority, so `https://evil.example/x{AZURE_HOST_SUFFIX}/openai/v1` is a URL "
            "whose HOST is an attacker's and whose tail merely reads like ours."
        )
    elif not any(_is_pattern_guarded_raise(node, set(positional)) for node in ast.walk(builder)):
        failures.append(
            f"{BUILDER}() raises, but not behind a pattern match on {positional}. A refusal "
            "conditioned on emptiness or on `None` accepts `evil.example/x`, which is the "
            "only input that matters — the resource becomes the first label of the "
            "hostname, so what has to be checked is its SHAPE, against a regex, not its "
            "presence. (This check reads the shape and cannot prove the predicate can "
            "fire; `tests/in_call_llm_provider_test.py` calls the builder with the attack "
            "strings and is what proves that.)"
        )

    returns = [node for node in ast.walk(builder) if isinstance(node, ast.Return)]
    if not returns:
        failures.append(f"{BUILDER}() returns nothing this check can read.")
    permitted_holes = set(positional) | frozen_names
    for statement in returns:
        value = statement.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            continue
        if not isinstance(value, ast.JoinedStr):
            failures.append(
                f"{BUILDER}() line {statement.lineno} returns an expression that is not a "
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
                    f"{BUILDER}() line {statement.lineno} interpolates {hole!r} into the "
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
    templates: int, constants: Mapping[str, str], references: Iterable[Reference]
) -> list[str]:
    failures: list[str] = []
    if templates < MINIMUM_TEMPLATES:
        failures.append(
            f"the AST walk found only {templates} string templates across {SCANNED_TREES} "
            "— it is blind. Fix the scan rather than lowering MINIMUM_TEMPLATES."
        )
    if "AZURE_REGION" not in constants:
        failures.append(
            "the provenance scan cannot find this file's own `AZURE_REGION: Final` "
            "definition, so it would report ANY tree as having no frozen region constant "
            "— which is the state in which checks 1 and 3 silently accept nothing and "
            "reject everything, or the reverse. Fix `frozen_region_constants`."
        )
    if REGION_CONSTANT not in constants:
        failures.append(
            f"the scan cannot find `{REGION_CONSTANT}: Final` in shipped code. That is the "
            "SUBJECT canary rather than the parse canary: `AZURE_REGION` above proves this "
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

DELEGATED_NOTICE: Final = (
    f"NOT PROVED HERE, AND NO VERSION OF THIS CHECK CAN PROVE IT: that the Azure resource "
    f"named by `azure_openai_resource` is in {AZURE_REGION}, and that its deployment is "
    f"REGIONAL Standard rather than GLOBAL. Both are properties of the RESOURCE, invisible "
    f"in `https://<resource>{AZURE_HOST_SUFFIX}/openai/v1`; Global is Azure's DEFAULT "
    f"deployment type and processes worldwide. A human confirms both once in the Azure "
    f"portal — {OPERATIONS_DOC} §2 gates 20 and 20c — and files the reading in "
    f"docs/evidence/. Under D-127 this file proved the region from the AST. It no longer "
    f"can, and that is D-410's recorded cost rather than an oversight."
)


def delegation_failures(document: str | None = None) -> list[str]:
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
    text = (
        (REPO_ROOT / OPERATIONS_DOC).read_text(encoding="utf-8") if document is None else document
    )
    if any(REGION_CONSTANT in line and "portal" in line.lower() for line in text.splitlines()):
        return []
    return [
        f"{OPERATIONS_DOC} carries no gate naming `{REGION_CONSTANT}` and the Azure portal. "
        "That gate is where the residency fact this check CANNOT prove is confirmed by a "
        "person, so without it the tree asserts a region nobody has ever read and this "
        "script prints OK over the gap. Restore the gate (20: the resource's Location; "
        "20c: Regional rather than Global deployment) or, if the posture genuinely changed, "
        "change it here deliberately with a decision-log entry."
    ]


def main() -> int:
    references = endpoint_references()
    constants = frozen_region_constants()
    templates = template_count()

    failures = (
        blindness_failures(templates, constants, references)
        + single_spelling_failures(constants)
        + loose_region_literals()
        + console_config_failures()
        + endpoint_failures(references, constants)
        + stale_allowances(references)
        + builder_failures()
        + delegation_failures()
    )
    if failures:
        print("MODEL RESIDENCY: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        print(
            f"\nD-410: both LLM surfaces run on Azure OpenAI in `{AZURE_REGION}`. The "
            f"region is a frozen constant (`{REGION_CONSTANT}`) rather than a setting, and "
            f"the endpoint has exactly one constructor (`{BUILDER}()`). If a second "
            "endpoint or a second spelling is genuinely needed for a bounded reason, it "
            "belongs in ALLOWANCES in this script WITH the date and the work that removes "
            "it — never as a silent skip."
        )
        print(f"\n{DELEGATED_NOTICE}")
        return 1

    print(
        f"MODEL RESIDENCY: OK ({templates} string templates scanned; region spelled once, "
        f"as `{REGION_CONSTANT}` in {BUILDER_HOME}; {len(references)} Azure/OpenAI host "
        f"literal(s) judged and only {BUILDER}()'s own suffix permitted; the builder takes "
        f"one validated resource label and no region; no Settings field able to carry "
        f"either; {len(ALLOWANCES)} dated allowance(s) still current)"
    )
    print(f"\n{DELEGATED_NOTICE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
