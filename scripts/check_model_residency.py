"""Guardrail: every Google model endpoint this tree can reach is Vertex AI `asia-south1`,
and the region is not something a console can change (D-127; PLAN-HARDENING-AND-GEMINI
Part 12).

WHY THIS EXISTS BEFORE THE CLIENT THAT WOULD VIOLATE IT. D-36 could state a residency
guarantee as a fact about a VENDOR — Sarvam is sovereign, therefore no transcript text
leaves India. D-127 puts a Google endpoint in the product, so that sentence is gone and
the replacement is a fact about a STRING: `asia-south1` rather than `us-central1`, nine
characters, in a URL nobody re-reads after the day it is written. Review does not
reliably catch nine characters. A check does, and it is decidable from syntax with no
network and no credential — which is why Part 12 lands before Part 13 rather than
alongside it.

THE ENDPOINT FACTS, and their evidence standing. **REPORTED, NOT READ** — this build
environment's egress proxy refuses `docs.cloud.google.com`, `modelavailability.com`,
`docs.litellm.ai` and `www.promptfoo.dev`, so no page below was fetched from this
repository; each is multiple independent search summaries agreeing (searched 15 Aug 2026),
which is the D-105 posture and is recorded here so the next reader inherits the evidence
rather than the conclusion:

* Vertex AI's regional service endpoint is `{REGION}-aiplatform.googleapis.com`, and the
  generate call is
  `https://asia-south1-aiplatform.googleapis.com/v1/projects/{PROJECT}` +
  `/locations/asia-south1/publishers/google/models/{MODEL}:generateContent`.
  So the region appears TWICE — in the host and in the path — and the two can disagree,
  which is why checks 2 and 4 are separate checks rather than one.
* The GLOBAL endpoint is the same host with no region prefix, and `locations/global` in
  the path. Google's own documentation says the caller cannot control which region
  processes the request on it. That is the exact shape check 1 bans.
* `asia-south1` is Mumbai. Gemini Flash and Flash-Lite are served there, and Google
  states customer data is stored in the region you specify for generally-available
  generative features. (Provisioned Throughput there is single-zone — a capacity fact,
  not a residency one, noted so nobody rediscovers it as an alarm.)
* The AI Studio / Gemini Developer API (`generativelanguage.googleapis.com`) offers no
  residency guarantee at all, and on the free tier Google states submitted prompts and
  responses are used to improve its products with human reviewers able to read them.
  Disqualified for this product — see the D-127 row.

CONFIRMING ANY OF THIS AGAINST THE VENDOR is an OPERATIONS §2-class gate on the day the
GCP project exists, not an engineering unknown: a wrong host fails LOUD (a 404 or a 401
from a host that does not serve our project), which is the safe direction.

FIVE CHECKS, because there are five ways the posture can be lost and only the first is
the one people picture:

1. **No global Google model host in any URL literal.** `generativelanguage.googleapis.com`
   and bare `aiplatform.googleapis.com` with no region prefix.
2. **Every `*-aiplatform.googleapis.com` literal carries `asia-south1`** — or a frozen
   constant that holds it.
3. **The region is a `Final` constant and cannot come from console-editable config.**
   `platform_config.managed_fields()` computes the console's editable set from
   `Settings.model_fields` minus the bootstrap keys minus credential-shaped names, so a
   field named `vertex_location` would be editable from a web form the day it is
   declared. A residency posture invertible by a click at 3am is not a posture. This is
   the doctrine `check_bootstrap_keys` applies to `APP_ENV` (D-95 §4), applied to the one
   other value whose change is a compliance event wearing a config diff.
4. **The `locations/…` path segment interpolates only that frozen constant.** A host
   pinned to Mumbai with `locations/global` in the path is not pinned to Mumbai.
5. **The check can still see.** A scan that has quietly stopped parsing reads exactly
   like a clean tree, so the run asserts it walked a plausible number of files and that
   it can still find this file's own `VERTEX_REGION` definition. Same argument
   `check_redaction_exposure.check_allowlist` makes when it refuses to pass on a route
   table with no permissions in it at all.

MECHANISM: the Python half reads the **AST**, not the source text, and reconstructs
f-strings into templates (`f"https://{X}-aiplatform..."` becomes
`https://{X}-aiplatform...` with `X` carrying the interpolated expression's source). Two
reasons, both learned here. First, `sarvam_model_identifier_test`'s: a correction has to
be EXPLAINED somewhere, and a regex over source flags the paragraph explaining it — this
very docstring names both banned hosts. Second, the region can only be judged where the
template shows where it CAME from, which a raw grep cannot do.

A CONSEQUENCE WORTH STATING RATHER THAN DISCOVERING: `"…/locations/{loc}/…".format(loc=X)`
is refused, because the template says `{loc}` and nothing about `X`. Use an f-string over
the frozen constant, or spell `asia-south1`. The rejected alternative was resolving
`.format()` arguments — it works for the literal call and not for a template passed
around, so it would buy a style allowance at the cost of a check that is right sometimes.

WHAT THIS CHECK CANNOT SEE, said plainly so nobody mistakes a green run for a whole
answer. It judges LITERALS. A host assembled by concatenation at runtime, read from an
environment variable, or returned by a vendor SDK that builds its own URL is invisible to
it — which is why check 3 exists and why it is a name-and-default check on `Settings`
rather than a URL check: if the value never appears in the tree, the tree cannot be
asked, and the only remaining defence is that there is nowhere console-editable for it to
live. It also cannot judge the two literals that DEFINE the banned hosts in this file,
which is the whole of its self-exemption now — see `SELF` and `_host_definition`; a URL
written anywhere else in this file is judged like any other file's. The non-Python half
is a LINE scan (`.ts`, `.json`, shell, nginx): a line naming
either host becomes a reference and is then judged by the same host and `locations/`
rules, so a `us-central1` URL in a TypeScript file is caught — but with no AST there is no
way to tell code from a `//` comment, so a comment naming a banned host in one of those
files WILL be reported. That false positive is accepted rather than engineered away: this
repo has no non-Python caller of a model provider, CLAUDE.md forbids one, and a comment
about a Google model host in the frontend is worth a human look anyway. It is a tripwire,
not a workhorse — `tests/model_residency_guard_test.py` steps on it deliberately, because
a tripwire with no subject in the tree is one nobody has evidence is connected.

NOT IN SCOPE: `oauth2.googleapis.com`, `sheets.googleapis.com` and
`www.googleapis.com/auth/spreadsheets` in `workers/google_sheets.py`. Those are the
tenant's OWN destination, chosen by them, disclosed in their DPA, and carry no model
inference. This check is about where a MODEL runs.

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

#: The ONLY region D-127 permits. Spelled HERE rather than imported, for the reason
#: `check_bootstrap_keys.BOOTSTRAP_KEYS` gives: a guardrail that imported the value it is
#: checking would be asking the code whether it agrees with itself. It is also this
#: check's own blindness canary (check 5) — the provenance scan must be able to find this
#: line, or it is not reading anything.
VERTEX_REGION: Final = "asia-south1"

#: The AI Studio / Gemini Developer API. Global host, no region anywhere in the URL.
AI_STUDIO_HOST: Final = "generativelanguage.googleapis.com"

#: Vertex's host WITHOUT its region prefix. Reached bare, this is the global endpoint.
VERTEX_HOST: Final = "aiplatform.googleapis.com"

#: Where a URL literal can ship. `scripts/` is in for `sarvam_model_identifier_test`'s
#: reason: `scripts/pilot/` drives a real vendor account and reads like a fixture.
SCANNED_TREES: Final[tuple[str, ...]] = ("apps", "packages", "scripts")

#: Directory names never scanned. `tests`/`fixtures` are out because a test naming a
#: banned host is asserting ABOUT it — this file's own negative controls do exactly that.
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

#: This file names both banned hosts because it bans them. Same shape as
#: `sarvam_model_identifier_test.CANONICAL_HOME` — but NARROWER than that one, and
#: narrower than this entry was when it shipped.
#:
#: IT USED TO SKIP THE WHOLE FILE for the endpoint checks, which made the guard the one
#: module in `apps/`, `packages/` and `scripts/` where a `us-central1` URL would have
#: passed. That is a poor place for the single hole: a guardrail is edited by whoever is
#: relaxing it. The file has to name the two hosts to ban them, and `_host_definition`
#: below says exactly what that costs — a template that IS one of the two host strings
#: and nothing else. Every other literal in this file is judged like any other file's,
#: so the sentence "the guard exempts itself" is now false by two lines rather than
#: true by a `continue`.
SELF: Final = "scripts/check_model_residency.py"

#: `Settings` field-name fragments that would put a model region under console control.
#: Names, not values, because the dangerous field is the one whose value is EMPTY in the
#: tree and supplied from the store — see "what this check cannot see".
REGION_KNOB_FRAGMENTS: Final[tuple[str, ...]] = (
    "region",
    "location",
    "residency",
    "vertex",
    "aiplatform",
)


@dataclass(frozen=True)
class DatedAllowance:
    """One file permitted to name one banned host, until a named piece of work removes it.

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


#: EMPTY, and that is the state this registry is supposed to reach. Its one entry was
#: `apps/workers/extraction.py`, whose `GEMINI_CHAT_URL` named the AI Studio Developer
#: API; PLAN Part 13 replaced it with `vertex_generate_url()` — Vertex `asia-south1`,
#: OAuth2 service-account bearer, 3.x Flash-Lite — and `stale_allowances()` then required
#: the entry to go, which is exactly the contract the entry was written under.
#:
#: Kept as a declared, typed, empty mapping rather than deleted along with its machinery:
#: the NEXT bounded exception has to land as a dated row with a closer, and a registry
#: that has to be re-invented is a registry somebody replaces with a `continue`.
ALLOWANCES: Final[dict[str, DatedAllowance]] = {}


@dataclass(frozen=True)
class Reference:
    """One URL-shaped literal, with where it is and what it renders to."""

    path: str
    line: int
    template: str

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

    The hole's SOURCE is what makes checks 2 and 4 possible — "the region came from
    `VERTEX_LOCATION`" and "the region came from `self._loc`" are the same string to a
    grep and are not the same fact.
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
    more than that one does: the whole subject here is a host that has to be NAMED in
    order to be banned. Without this the guard reports its own explanation as the offence,
    which teaches the next reader to delete the explanation. A `#` comment never reaches
    the AST at all, so only docstrings need excluding.
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


def _templates(path: Path) -> Iterator[tuple[str, int]]:
    """Every string template in one Python file — plain constants and rendered f-strings.

    Two exclusions. Docstrings, per `_docstrings`. And constants nested INSIDE an f-string:
    the rendered whole already covers them, and yielding both would report one literal
    twice with the second report missing the region it is being judged on.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skipped = _docstrings(tree) | {
        id(inner)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for inner in ast.walk(node)
        if inner is not node
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            yield _render(node), node.lineno
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skipped
        ):
            yield node.value, node.lineno


def _host_definition(template: str) -> bool:
    """Is this template the DECLARATION of a banned host rather than a use of one?

    Exactly the two host strings, standing alone. `AI_STUDIO_HOST: Final = "generative…"`
    is the name this file bans things BY; judging it would report the ban as the
    violation, and the bare `aiplatform.googleapis.com` constant would trip check 1 as a
    region-less global endpoint every single run.

    Applied ONLY inside `SELF` (see that constant). Tree-wide it would be a real hole —
    `HOST = "aiplatform.googleapis.com"` followed by `f"https://{HOST}/…"` is precisely
    the runtime-assembly shape "what this check cannot see" already admits to, and
    exempting the first half by name would turn an admitted blind spot into a supported
    idiom.
    """
    return template in (AI_STUDIO_HOST, VERTEX_HOST)


def url_references(roots: Iterable[Path] | None = None) -> list[Reference]:
    """Every literal in the tree that mentions a Google model host, Python and text alike."""
    references: list[Reference] = []
    for path in _files(roots, frozenset({".py"})):
        relative = _rel(path)
        for template, line in _templates(path):
            if relative == SELF and _host_definition(template):
                continue
            if AI_STUDIO_HOST in template or VERTEX_HOST in template:
                references.append(Reference(relative, line, template))
    for path in _files(roots, TEXT_SUFFIXES):
        relative = _rel(path)
        for line_number, source_line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            if AI_STUDIO_HOST in source_line or VERTEX_HOST in source_line:
                references.append(Reference(relative, line_number, source_line.strip()))
    return references


def template_count(roots: Iterable[Path] | None = None) -> int:
    """How many string templates the Python half parsed — check 5's first half."""
    return sum(1 for path in _files(roots, frozenset({".py"})) for _ in _templates(path))


# --- 3 (first half): where the region is allowed to come from -----------------


def _is_final(annotation: ast.expr) -> bool:
    """`Final`, `typing.Final`, `Final[str]`, `typing.Final[str]` — and nothing else.

    A plain `x: str = "asia-south1"` is NOT frozen: `Final` is what mypy strict (a CI
    gate here) refuses to let anything rebind, so it is the annotation that turns a
    convention into an enforced one.
    """
    node: ast.expr = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    if isinstance(node, ast.Attribute):
        return node.attr == "Final"
    return isinstance(node, ast.Name) and node.id == "Final"


def frozen_region_constants(roots: Iterable[Path] | None = None) -> dict[str, str]:
    """`NAME: Final = "asia-south1"` across the tree — name to the file that defines it."""
    constants: dict[str, str] = {}
    for path in _files(roots, frozenset({".py"})):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.value is not None
                and isinstance(node.value, ast.Constant)
                and node.value.value == VERTEX_REGION
                and _is_final(node.annotation)
            ):
                constants[node.target.id] = _rel(path)
    return constants


def loose_region_literals(roots: Iterable[Path] | None = None) -> list[str]:
    """Check 3, first half: a bare `"asia-south1"` that is NOT a `Final` constant's value.

    Every spelling of the region in shipped code has to be the one frozen name or a
    reference to it. The shape this is really aimed at is not a second constant — it is
    `def __init__(self, location: str = "asia-south1")`, a default argument that reads
    like a pin and is one keyword away from not being one.
    """
    failures: list[str] = []
    for path in _files(roots, frozenset({".py"})):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        frozen = {
            id(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _is_final(node.annotation)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and node.value == VERTEX_REGION
                and id(node) not in frozen
            ):
                failures.append(
                    f"{_rel(path)}:{node.lineno} spells {VERTEX_REGION!r} somewhere other "
                    "than a `Final` constant's value. D-127 pins the region so it cannot "
                    "be varied per call site or per caller — declare it once as "
                    "`VERTEX_LOCATION: Final = ...` (its home is beside SARVAM_DEFAULT_LLM "
                    "in calevate_shared/engine.py, where this repo already keeps the model "
                    "identity constants) and reference that."
                )
    return failures


# --- 1, 2 and 4: what the literals say ----------------------------------------


def _region_ok(token: str, frozen: Mapping[str, str]) -> bool:
    if token == VERTEX_REGION:
        return True
    if token.startswith("{") and token.endswith("}"):
        return token[1:-1].strip() in frozen
    return False


def _hosts_in(template: str) -> Iterator[tuple[int, str]]:
    """Each `aiplatform.googleapis.com` occurrence, with the host text before it.

    The prefix is read by walking back to the URL's authority boundary rather than by a
    regex, because the region itself contains a hyphen (`asia-south1`) and every regex
    that gets that right also matches half of `us-central1`.
    """
    index = template.find(VERTEX_HOST)
    while index != -1:
        start = index
        while start > 0 and template[start - 1] not in "/@ \t\"'\\":
            start -= 1
        yield index, template[start:index]
        index = template.find(VERTEX_HOST, index + 1)


def _location_segments(template: str) -> Iterator[str]:
    marker = "locations/"
    index = template.find(marker)
    while index != -1:
        rest = template[index + len(marker) :]
        segment: list[str] = []
        for character in rest:
            if character in "/?# \t\"'\\":
                break
            segment.append(character)
        yield "".join(segment)
        index = template.find(marker, index + 1)


def endpoint_failures(
    references: Iterable[Reference],
    frozen: Mapping[str, str] | None = None,
    allowances: Mapping[str, DatedAllowance] | None = None,
) -> list[str]:
    """Checks 1, 2 and 4 over the literals the scan found.

    `frozen` and `allowances` are injectable for the reason
    `check_redaction_exposure.check`'s exemptions are: a guardrail whose exemptions cannot
    be taken away in a test is a guardrail nobody can prove still sees anything.
    """
    constants = frozen_region_constants() if frozen is None else frozen
    permitted = ALLOWANCES if allowances is None else allowances
    failures: list[str] = []

    for reference in references:
        allowed = permitted.get(reference.path)

        if AI_STUDIO_HOST in reference.template and (
            allowed is None or allowed.host != AI_STUDIO_HOST
        ):
            failures.append(
                f"{reference} names {AI_STUDIO_HOST} — the AI Studio Developer API. It "
                "guarantees no data residency, and on the free tier Google uses prompts "
                "and responses to improve its products with human reviewers able to read "
                "them. D-127 disqualifies it; use Vertex AI "
                f"{VERTEX_REGION}-{VERTEX_HOST}."
            )

        for _, prefix in _hosts_in(reference.template):
            if allowed is not None and allowed.host == VERTEX_HOST:
                continue
            if not prefix:
                failures.append(
                    f"{reference} reaches {VERTEX_HOST} with no region prefix — the "
                    "GLOBAL Vertex endpoint, on which the caller cannot control which "
                    "region processes the request. D-127 requires "
                    f"{VERTEX_REGION}-{VERTEX_HOST}."
                )
                continue
            if not prefix.endswith("-"):
                failures.append(
                    f"{reference} names host {prefix}{VERTEX_HOST}, which is not a Vertex "
                    f"regional endpoint ({{region}}-{VERTEX_HOST}). Read it before "
                    "trusting it."
                )
                continue
            region = prefix[:-1]
            if not _region_ok(region, constants):
                failures.append(
                    f"{reference} sends model traffic to region {region!r}. D-127 permits "
                    f"{VERTEX_REGION!r} only — literally, or through a `Final` constant "
                    f"holding it (known: {sorted(constants) or 'none'}). This is a "
                    "residency change, not a config change."
                )

        for segment in _location_segments(reference.template):
            if not _region_ok(segment, constants):
                failures.append(
                    f"{reference} puts {segment!r} in the `locations/` path segment. A "
                    f"host pinned to {VERTEX_REGION} with another location in the path is "
                    "not pinned at all, and `locations/global` is the global endpoint "
                    "wearing a regional host. Interpolate the frozen constant "
                    f"(known: {sorted(constants) or 'none'}) or spell {VERTEX_REGION!r}."
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


# --- 3 (second half): the console can never decide this -----------------------


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
    """No `Settings` field may carry a model region, so none can become console-editable.

    Asserted against the WHOLE `Settings` model and not only against `managed_fields()`,
    because the console's editable set is DERIVED (`Settings.model_fields` minus the
    bootstrap keys minus credential-shaped names) — a new field is managed by default, so
    a check that read only the derived set would be reporting on a symptom.
    """
    if fields is None or managed is None:
        live_fields, live_managed = live_settings()
        fields = live_fields if fields is None else fields
        managed = live_managed if managed is None else managed
    editable = set(managed)
    failures: list[str] = []
    for name, default in sorted(fields.items()):
        lowered = name.lower()
        if any(fragment in lowered for fragment in REGION_KNOB_FRAGMENTS):
            where = "console-editable" if name in editable else "declared"
            failures.append(
                f"Settings.{name} is {where} and its name says it holds a model region or "
                "a Vertex endpoint. D-127 makes the region a frozen constant precisely so "
                "it cannot be changed from a web form at 3am — the same rule D-95 §4 "
                "applies to APP_ENV. Move it to a `Final` constant in code."
            )
            continue
        if isinstance(default, str) and (
            AI_STUDIO_HOST in default or VERTEX_HOST in default or default == VERTEX_REGION
        ):
            failures.append(
                f"Settings.{name} defaults to a Google model endpoint or region "
                f"({default!r}). Whatever its name says, it is the residency knob."
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
    if "VERTEX_REGION" not in constants:
        failures.append(
            "the provenance scan cannot find this file's own `VERTEX_REGION: Final` "
            "definition, so it would report ANY tree as having no frozen region constant "
            "— which is the state in which checks 2 and 4 silently accept nothing and "
            "reject everything, or the reverse. Fix `frozen_region_constants`."
        )
    if not list(references):
        failures.append(
            "no literal anywhere in the tree mentions a Google model host — including the "
            "one ALLOWANCES names. Either the scan stopped reading files, or the "
            "allowance is stale and `stale_allowances` should have said so."
        )
    return failures


def main() -> int:
    references = url_references()
    constants = frozen_region_constants()
    templates = template_count()

    failures = (
        blindness_failures(templates, constants, references)
        + endpoint_failures(references, constants)
        + stale_allowances(references)
        + loose_region_literals()
        + console_config_failures()
    )
    if failures:
        print("MODEL RESIDENCY: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nD-127: Gemini is reached through Vertex AI `asia-south1` and nowhere else, "
            "and the region is a frozen constant rather than a setting. If a global "
            "endpoint is genuinely needed for a bounded reason, it belongs in ALLOWANCES "
            "in this script WITH the date and the work that removes it — never as a "
            "silent skip."
        )
        return 1

    print(
        f"MODEL RESIDENCY: OK ({templates} string templates scanned, "
        f"{len(references)} Google model host literal(s) judged, region pinned to "
        f"{VERTEX_REGION} via {len(constants)} frozen constant(s), "
        f"{len(ALLOWANCES)} dated allowance(s) still current, "
        "no Settings field able to carry a region)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
