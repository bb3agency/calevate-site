"""Guardrail: `apps/web/.env.example` ⟷ what the browser bundle actually reads.

`check_env_parity` guards the API's configuration in three directions and cannot see the
web tier at all: `apps/web` reads its own configuration straight out of `process.env`,
answers to no `Settings` class, and — until this file — was guarded by nothing.

**Why that is worse than ordinary config drift.** `next build` INLINES `NEXT_PUBLIC_*`:
every `process.env.NEXT_PUBLIC_X` is replaced by a hard-coded literal at build time, so a
key that is misspelled, renamed or simply absent does not throw and does not fail the
build — it becomes the empty string in the bundle, silently, and the failure arrives as a
broken screen in front of a client. The keys Clerk sign-in just introduced are the sharp
end of it: `NEXT_PUBLIC_AUTH_MODE` decides whether the browser presents a real Clerk token
or the local `dev:<realm>:<user-id>` credential, and `lib/auth/mode.ts` can only refuse a
value it receives — a name nobody types correctly resolves to `""`, which that file reads
as "unset".

So this asks four questions about the LIVE tree, in both directions, and every one of them
is decided against an artefact rather than a remembered list:

1. **Every variable the web package reads is declared.** The read direction is the one
   that ships broken screens.
2. **Every declared variable is read.** The stale direction: a key survives a refactor,
   stays in the template and in three deploy environments, and the next person configures
   something that has not existed for a month. A key that appears only as a STRING (never
   as `process.env.KEY`) counts as UNREAD on purpose — see question 4.
3. **No `NEXT_PUBLIC_` key is shaped like a secret.** Nothing with that prefix is private:
   it is served to every visitor as plain text. `_SECRET`, `_PASSWORD`, `_TOKEN`, a bare
   `_KEY` — each is refused unless `PUBLIC_BY_DESIGN` below records why that particular
   value is public by the VENDOR's own definition. Publishable keys are the legitimate
   case and they are the whole reason this is a registry rather than a ban.
4. **Nothing reads the environment in a form Next cannot inline.** Static replacement
   matches the literal expression `process.env.NAME` and nothing else: `process.env[name]`,
   `const { NEXT_PUBLIC_X } = process.env` and `const env = process.env` all survive
   type-checking, survive review, and are `undefined` in the browser.

Plus the shape this repo's newer guardrails all carry: an empty declaration whose reader
supplies a non-empty `??` default is refused (a copied template must not be worse than no
template), duplicate declarations are refused (the last line silently wins), and
`blind_spots()` fails rather than printing OK when the scan stops finding its subject.

WHERE THE KEYS ARE DECLARED, AND WHY IT IS A SECOND FILE
--------------------------------------------------------
`apps/web/.env.example`, not a section of the repo root's. Three reasons, in order of
weight:

* The root file is checked BOTH WAYS against `calevate_shared.config.Settings`, so a real
  `KEY=` line there that is not a Settings field fails `check_env_parity` — and none of
  these may BE Settings fields, because the API neither reads them nor should be able to
  (D-49 moved PostHog out of `Settings` for exactly this reason). That is what forced the
  browser keys to be written as COMMENTS in the root file: a declaration no machine can
  read, which is the gap this guardrail was written to close. Teaching the Python check to
  SKIP a section would have kept one file and given it two grammars, one of them
  unenforced — the same defect in a new place.
* Next loads `.env*` from the PACKAGE directory, never from the repo root, so
  `apps/web/.env.local` is the file that actually configures the browser. The template
  belongs beside the file it is a template for; a developer who copies the root
  `.env.example` to `.env` and expects the browser to notice is holding a wrong belief the
  layout gave them.
* The two halves have different lifetimes: the API's config is read at boot and validated
  by Pydantic, the browser's is frozen into a bundle at build time. One file that means
  "restart" on some lines and "rebuild" on others is a file people get wrong.

What a developer has to do: nothing. Every value in the template is the local default, so
the app runs with no `.env.local` at all, and `cp apps/web/.env.example apps/web/.env.local`
is a starting point rather than a switch. DEV-SETUP §4 says so too.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
* **It does not validate VALUES.** Whether a publishable key is well-formed, whether a URL
  parses, whether the two Clerk keys name the same applications the API's secrets do — none
  of that is decidable from this side. `@t3-oss/env-nextjs` is the standard tool for the
  value half and is deliberately not adopted here (research note below); the one value
  claim this file does make is the narrow, decidable one in `empty_default_overrides`.
* **It does not read `apps/web/tests/`.** A test is a consumer of configuration, not a
  declaration of it — `check_docs_drift` excludes `tests/` from the code vocabulary on the
  same grounds. It matters more here than there: `tests/signup.test.tsx` ASSIGNS
  `process.env.NEXT_PUBLIC_SELF_SERVE_SIGNUP_ENABLED`, and counting an assignment as a read
  would keep question 2 green for a key the app itself had stopped using.
* **It does not judge non-public reads in server code, because there is none yet.** A
  Server Component or a route handler may legitimately read `process.env.CLERK_SECRET_KEY`
  at request time, and nothing in this tree distinguishes a server module from a client one
  without Next's own module graph. Today `apps/web` has no `"use server"`, no `server-only`
  import and no route handler: every file it compiles goes to the browser, which is what
  makes question 4 decidable. THAT is the assumption to revisit when the first server-only
  module lands — the check must learn the distinction rather than grow an exemption list.
* **It does not police the root `.env.example`.** A `NEXT_PUBLIC_` line there already fails
  `check_env_parity` ("in .env.example but not Settings"), and two checks owning one answer
  is how they start disagreeing.
* **It does not parse TypeScript.** A real parser would mean either a Node process (this
  guardrail runs in CI's backend job, which has no Node) or a second toolchain. Comments are
  stripped by a small lexer so a renamed key cannot stay "alive" in the prose that describes
  it — the narrowing `check_wiring` and `check_docs_drift` both make — and the residual
  risk is a regex literal containing a quote desynchronising the lexer. That fails SAFE: a
  desynchronised scan loses reads, and a lost read is a loud "declared but nothing reads it",
  never a silent pass.

Run: `uv run python -m scripts.check_web_env_parity`  (also in `make guardrails` and CI)

WHY A SECOND SCRIPT AND NOT A SECTION OF `check_env_parity`. They share no artefact, no
parser and no failure prose: one imports `Settings` and walks Python ASTs, the other reads a
different file and lexes TypeScript. Merging them would put two unrelated registries behind
one exit code and one CI step name, so a red build would not say which tier was wrong — and
`check_env_parity`'s behaviour is pinned by `tests/guardrail_audit_test.py`, which this must
not disturb. They are cross-referenced in both directions instead.

Research note (2026-08, before writing this), so the next reader inherits the evidence:

* **`@t3-oss/env-nextjs`** (env.t3.gg/docs/nextjs; npmjs.com/package/@t3-oss/env-nextjs) —
  THE established answer for Next.js: one `createEnv({ server, client })` schema, Zod
  validation at build time, and a hard split between server and client keys. ADOPTED AS THE
  IDEA — declare the browser's configuration in ONE place and fail the BUILD rather than the
  screen — and rejected as the mechanism, for reasons that are about this repo and not about
  the library. It answers "is the value present and well-formed", not "does anything still
  read this key"; it cannot see a typo at a call site that bypasses the schema unless an
  ESLint rule bans `process.env` everywhere too; and taking it means a new runtime dependency
  in the bundle path (hard rule 9's territory) plus rewriting every read site in
  `apps/web/src`. Its half of the problem is real and this file says so above: if value
  validation is ever wanted, that is the tool, and the two compose — a schema module would be
  a `process.env.NAME` read like any other and would be checked here exactly as it is now.
* **ESLint (`n/no-process-env`, `no-restricted-properties`)** — can ban or channel
  `process.env` access, which is a useful complement and a different question again; it sees
  one file at a time and has no idea what is declared. Not adopted: the repo's parity rule
  already has a home (`make guardrails`), and a second place for the same rule is CLAUDE.md's
  "two ways of doing one thing".
* **`dotenv-linter`, `envalid`** — the former lints `.env` FILES for syntax/duplicates (a
  subset of what `declarations()` does below, in a language this pack does not otherwise use);
  the latter validates a Node process's env at runtime, which is the wrong time: the browser's
  values were frozen at build.
* **Next.js env-var semantics** — `NEXT_PUBLIC_*` is inlined at build time and "dynamic
  lookups will not be inlined": `process.env[varName]` and destructuring/aliasing `process.env`
  are named explicitly as the forms that break. That is question 4, and it is the vendor's own
  documented limitation rather than our inference. (nextjs.org's environment-variables guide
  is EGRESS-BLOCKED from this build environment, as Bolna's docs were for D-52, so this rests
  on search-surfaced quotations of it and on the observed behaviour of this repo's own build.)
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The package whose configuration this guards, and the file that declares it. Both
# relative, so the whole check can be pointed at a mirrored tree — every negative control
# in `tests/web_env_parity_guard_test.py` runs the real `main()` against a copy.
WEB_PACKAGE = Path("apps/web")
DECLARATION_FILE = WEB_PACKAGE / ".env.example"

# What `next build` compiles. `tests` is excluded on purpose (see the docstring), `public`
# holds no code, and `.next`/`node_modules` are output and vendor.
SOURCE_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts", ".cjs"})
EXCLUDED_DIRECTORIES = frozenset({"node_modules", ".next", "out", "tests", "public", "dist"})

# Set by the runtime, not by us — the web twin of `check_env_parity.INFRA_ENV_KEYS`.
# `NODE_ENV` is Next's own production signal (`lib/auth/mode.ts` depends on the fact that a
# deployment cannot forget it); `NEXT_RUNTIME` is set by Next per execution environment.
INFRA_ENV_KEYS: frozenset[str] = frozenset({"NODE_ENV", "NEXT_RUNTIME", "PORT", "CI", "TZ"})

# `NEXT_PUBLIC_` names that LOOK like credentials and are public by the vendor's own
# definition. A registry rather than a structural carve-out for the word "PUBLISHABLE":
# the point of question 3 is that browser-visible values get a REVIEWED decision, and a
# rule that reads a name for reassurance is a rule an attacker's naming can satisfy.
# `stale_registry()` fails on any entry that names no declared key, so this can only
# shrink, and `tests/web_env_parity_guard_test.py` pins the set so a new entry costs a
# visible diff in a test too.
PUBLIC_BY_DESIGN: dict[str, str] = {
    "NEXT_PUBLIC_CLERK_CLIENT_PUBLISHABLE_KEY": (
        "PUBLISHABLE is Clerk's own term for the half of the pair meant to ship in the "
        "browser: it identifies the application to clerk-js and grants nothing on its "
        "own. Its secret twin is CLERK_CLIENT_SECRET_KEY, which stays in the API's "
        "Settings and is never NEXT_PUBLIC_. Closes if Clerk ever stops splitting the pair"
    ),
    "NEXT_PUBLIC_CLERK_ADMIN_PUBLISHABLE_KEY": (
        "the admin realm's twin of the above, separate because TRD §11 and D-37 keep the "
        "two realms in two Clerk APPLICATIONS with no shared session logic — one entry "
        "covering both would be a per-vendor exemption where the repo keys them per value"
    ),
}

# Names that must not be browser-visible. Substrings for the words that mean "credential"
# in any position, suffixes for `_KEY`/`_TOKEN`, which are only credential-shaped at the
# END of a name (`NEXT_PUBLIC_SORT_KEY_LABEL` is not a secret and must not be reported —
# a guardrail with false positives trains people to add exemptions until it means nothing).
SECRET_SUBSTRINGS: tuple[str, ...] = ("SECRET", "PASSWORD", "PASSPHRASE", "PRIVATE", "CREDENTIAL")
SECRET_SUFFIXES: tuple[str, ...] = ("_KEY", "_TOKEN")

PUBLIC_PREFIX = "NEXT_PUBLIC_"

_DECLARATION = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
# The ONLY form Next inlines: the literal member expression.
_READ = re.compile(r"process\.env\.([A-Za-z_$][A-Za-z0-9_$]*)")
# `process.env` reached in any other way — subscripted, destructured, aliased, spread.
_OPAQUE = re.compile(r"process\.env(?!\s*\.\s*[A-Za-z_$])")
_MENTION = re.compile(r"NEXT_PUBLIC_[A-Z0-9_]+")
# `process.env.X ?? "fallback"` — the code's own default for a key.
_FALLBACK = re.compile(
    r"process\.env\.([A-Za-z_$][A-Za-z0-9_$]*)\s*\?\?\s*(\"[^\"]*\"|'[^']*'|`[^`]*`)"
)


# --- reading the artefacts ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Usage:
    """What the web package does with the environment, and where.

    Sites are `path:line` strings rather than counts: every failure below has to name a
    file a person can open, or the finding is a second investigation.
    """

    reads: dict[str, list[str]] = field(default_factory=dict)
    mentions: dict[str, list[str]] = field(default_factory=dict)
    fallbacks: dict[str, set[str]] = field(default_factory=dict)
    opaque: list[str] = field(default_factory=list)
    files: int = 0


@dataclass(frozen=True, slots=True)
class WebEnv:
    """Everything the sections below judge, collected once."""

    declared: dict[str, str]
    duplicates: list[str]
    usage: Usage
    # Whether the declaration file is THERE, kept apart from `declared` being empty: a
    # missing file and a file that stopped parsing are different failures with different
    # fixes, and reporting them as one would send the reader to the wrong place.
    declaration_exists: bool


def source_files(root: Path | None = None) -> list[Path]:
    """Every file `next build` would compile, from the live tree."""
    base = (root or REPO_ROOT) / WEB_PACKAGE
    if not base.exists():
        return []
    return sorted(
        path
        for path in base.rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and not EXCLUDED_DIRECTORIES & set(path.relative_to(base).parts)
    )


def strip_comments(source: str) -> str:
    """Blank out comments, keeping every other character in place.

    Offsets are preserved (comment characters become spaces, newlines stay newlines) so a
    match position still yields the right line number. Comments have to go for the reason
    `check_wiring` excludes docstrings from its column scan: a renamed key usually survives
    in the prose that describes it — `mode.ts` names `NEXT_PUBLIC_AUTH_MODE` five times in
    its docstring — and counting prose about the code as the code would blind question 2
    exactly where the drift is.

    A hand-rolled lexer rather than a regex because `"http://localhost:8000"` is not a
    comment; strings, template literals and their `${...}` holes are tracked for the same
    reason. Regex literals are NOT tracked: `/` in code is read as division, so a regex
    containing a quote can desynchronise this. That direction is safe — see the docstring.
    """
    out = list(source)
    stack: list[str] = ["code"]
    braces: list[int] = [0]
    index = 0
    length = len(source)

    def blank(position: int) -> None:
        if out[position] != "\n":
            out[position] = " "

    while index < length:
        character = source[index]
        following = source[index + 1] if index + 1 < length else ""
        context = stack[-1]

        if context == "code":
            if character == "/" and following == "/":
                while index < length and source[index] != "\n":
                    blank(index)
                    index += 1
                continue
            if character == "/" and following == "*":
                while index < length and source[index : index + 2] != "*/":
                    blank(index)
                    index += 1
                for _ in range(2):  # the closing `*/`
                    if index < length:
                        blank(index)
                        index += 1
                continue
            if character in "'\"":
                stack.append(character)
            elif character == "`":
                stack.append("`")
            elif character == "{":
                braces[-1] += 1
            elif character == "}":
                if braces[-1] == 0 and len(stack) > 1:
                    stack.pop()
                    braces.pop()
                else:
                    braces[-1] = max(0, braces[-1] - 1)
            index += 1
            continue

        if character == "\\":  # an escape inside any string form
            index += 2
            continue
        if context == "`":
            if character == "`":
                stack.pop()
            elif character == "$" and following == "{":
                stack.append("code")
                braces.append(0)
                index += 1
            index += 1
            continue
        # a single- or double-quoted string
        if character == context or character == "\n":
            stack.pop()
        index += 1

    return "".join(out)


def _line_of(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def usage(root: Path | None = None) -> Usage:
    """Where the web package touches `process.env`, read off the LIVE tree.

    Never a remembered list of keys: the whole failure mode is a key nobody remembered.
    """
    base = root or REPO_ROOT
    reads: dict[str, list[str]] = {}
    mentions: dict[str, list[str]] = {}
    fallbacks: dict[str, set[str]] = {}
    opaque: list[str] = []
    files = source_files(root)

    for path in files:
        code = strip_comments(path.read_text(encoding="utf-8"))
        where = path.relative_to(base).as_posix()
        for match in _READ.finditer(code):
            reads.setdefault(match.group(1), []).append(f"{where}:{_line_of(code, match.start())}")
        for match in _FALLBACK.finditer(code):
            fallbacks.setdefault(match.group(1), set()).add(match.group(2)[1:-1])
        for match in _OPAQUE.finditer(code):
            opaque.append(f"{where}:{_line_of(code, match.start())}")
        # A key NAMED in a string is not a key READ: Next inlines the member expression and
        # nothing else. Blanking the reads first is what keeps the two apart.
        residual = _READ.sub(lambda match: " " * len(match.group(0)), code)
        for match in _MENTION.finditer(residual):
            mentions.setdefault(match.group(0), []).append(
                f"{where}:{_line_of(residual, match.start())}"
            )

    return Usage(
        reads=reads,
        mentions=mentions,
        fallbacks=fallbacks,
        opaque=opaque,
        files=len(files),
    )


def declarations(path: Path) -> tuple[dict[str, str], list[str]]:
    """`{KEY: value}` from the declaration file, plus any key declared twice.

    A duplicate is a real trap and not a tidiness complaint: dotenv keeps the LAST
    assignment, so the line a reader edits may not be the line that wins. Same rule the
    API's half enforces on the root file.
    """
    if not path.exists():
        return {}, []
    values: dict[str, str] = {}
    order: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _DECLARATION.match(line.strip())
        if match:
            order.append(match.group(1))
            values[match.group(1)] = match.group(2).strip()
    return values, sorted({key for key in order if order.count(key) > 1})


def collect(root: Path | None = None) -> WebEnv:
    path = (root or REPO_ROOT) / DECLARATION_FILE
    declared, duplicates = declarations(path)
    return WebEnv(
        declared=declared,
        duplicates=duplicates,
        usage=usage(root),
        declaration_exists=path.exists(),
    )


# --- has the tree moved out from under this check? ------------------------------


def blind_spots(state: WebEnv) -> list[str]:
    """A check that cannot find its subject must say so, never print OK.

    Every question below is a comparison between a file and a scan, and both sides pass
    vacuously when empty: a moved `apps/web`, a renamed source directory or a lexer that
    has stopped matching would each report a spotless tree.
    """
    failures: list[str] = []
    if not state.declaration_exists:
        failures.append(
            f"{DECLARATION_FILE.as_posix()} does not exist — nothing declares the browser's "
            "configuration, so every key the bundle reads would be unchecked. Restore it "
            "(the template is also what a developer copies to .env.local)."
        )
    elif not state.declared:
        failures.append(
            f"{DECLARATION_FILE.as_posix()} parsed to zero keys — the file's shape changed "
            "and both directions of this check are now comparing against nothing"
        )
    if state.usage.files < 20:
        failures.append(
            f"only {state.usage.files} source file(s) found under {WEB_PACKAGE.as_posix()} — "
            "the scan is looking at the wrong place and would report OK on any drift"
        )
    if not state.usage.reads:
        failures.append(
            f"no `process.env` read found anywhere in {WEB_PACKAGE.as_posix()} — either the "
            "app stopped reading its configuration or the source scan is blind"
        )
    elif state.declared and not any(key.startswith(PUBLIC_PREFIX) for key in state.usage.reads):
        failures.append(
            f"{DECLARATION_FILE.as_posix()} declares {len(state.declared)} key(s) and the "
            f"scan found no `{PUBLIC_PREFIX}*` read at all — the browser configuration this "
            "check exists for has vanished from the tree, which is a moved subject far more "
            "often than it is a deleted feature"
        )
    return failures


# --- 1. every read is declared ---------------------------------------------------


def undeclared_reads(state: WebEnv) -> list[str]:
    """The direction that ships a broken screen.

    Covers mentions as well as reads: a key that appears only as a string constant is
    either dead or being looked up dynamically, and neither survives `next build`.
    """
    failures: list[str] = []
    for key, sites in sorted(state.usage.reads.items()):
        if key in state.declared or key in INFRA_ENV_KEYS:
            continue
        failures.append(
            f"{key} is read at {', '.join(sorted(sites))} and "
            f"{DECLARATION_FILE.as_posix()} does not declare it. `next build` inlines "
            f'`process.env.{key}`, so an undeclared key is not an error — it is `""` in '
            "the bundle and a broken screen in production. Declare it (with its local "
            "default) or delete the read."
        )
    for key, sites in sorted(state.usage.mentions.items()):
        if key in state.declared or key in state.usage.reads:
            continue
        failures.append(
            f"{key} is named at {', '.join(sorted(sites))} and is neither declared nor read "
            "as `process.env." + key + "`. Either it is a leftover constant, or something is "
            "reading it dynamically — which Next does not inline."
        )
    return failures


# --- 2. every declaration is read ------------------------------------------------


def unread_declarations(state: WebEnv) -> list[str]:
    """The stale direction — how a dead key survives a refactor.

    Nothing enforces this at runtime: an unread key is configured in three environments,
    documented, and decides nothing. The next person changes it and waits for an effect.
    """
    failures: list[str] = []
    for key in sorted(state.declared):
        if key in state.usage.reads:
            continue
        mentioned = state.usage.mentions.get(key)
        if mentioned:
            failures.append(
                f"{DECLARATION_FILE.as_posix()} declares {key}, and the only place the tree "
                f"names it is {', '.join(sorted(mentioned))} — as a string, not as "
                f"`process.env.{key}`. Next inlines the literal member expression and "
                "nothing else, so whatever reads it that way reads `undefined` in the "
                "browser."
            )
        else:
            failures.append(
                f"{DECLARATION_FILE.as_posix()} declares {key} and nothing in "
                f"{WEB_PACKAGE.as_posix()} reads it. Delete the line, or wire the read — a "
                "key that decides nothing is a key the next person will configure and wait "
                "for."
            )
    return failures


# --- 3. no NEXT_PUBLIC_ key is shaped like a secret ------------------------------


def _secret_shape(key: str) -> str | None:
    """The part of the name that reads as a credential, or None."""
    for word in SECRET_SUBSTRINGS:
        if word in key:
            return word
    for suffix in SECRET_SUFFIXES:
        if key.endswith(suffix):
            return suffix
    return None


def secret_shaped_keys(state: WebEnv, registry: dict[str, str] | None = None) -> list[str]:
    """Hard rule 6's neighbour: nothing prefixed `NEXT_PUBLIC_` is private.

    The value ships to every visitor in plain text, so the question is not whether the
    variable is handled carefully — it is whether the value is one we are content to
    publish. Both declared and read keys are judged: not declaring a secret is not a way
    around this.
    """
    known = PUBLIC_BY_DESIGN if registry is None else registry
    candidates = sorted(set(state.declared) | set(state.usage.reads) | set(state.usage.mentions))
    failures: list[str] = []
    for key in candidates:
        if not key.startswith(PUBLIC_PREFIX) or key in known:
            continue
        shape = _secret_shape(key)
        if shape is None:
            continue
        failures.append(
            f"{key} is named like a credential (`{shape}`) and carries the "
            f"`{PUBLIC_PREFIX}` prefix, which means `next build` writes its value into the "
            "JavaScript every visitor downloads — there is no private one. If this really "
            "is public by the vendor's own definition (a publishable key), add it to "
            "`PUBLIC_BY_DESIGN` in this script with the reason; if it is not, it belongs "
            "in the API's Settings and must never reach the browser."
        )
    return failures


# --- 4. nothing reads the environment in a form Next cannot inline ---------------


def uninlinable_reads(state: WebEnv) -> list[str]:
    """`process.env[name]`, destructuring, aliasing — all `undefined` in the browser.

    The vendor's own documented limitation: static replacement matches the literal
    expression `process.env.NAME`. Every other form type-checks, passes review, and is
    empty at runtime — the same silent failure the rest of this file is about, arriving
    through a refactor rather than through a typo.
    """
    return [
        f"{site} reaches `process.env` other than as `process.env.NAME`. Next inlines the "
        "literal member expression ONLY — a subscript, a destructure or an alias is not "
        "replaced at build time and is `undefined` in the browser. Spell the read out."
        for site in sorted(state.usage.opaque)
    ]


# --- the template must be safe to copy -------------------------------------------


def empty_default_overrides(state: WebEnv) -> list[str]:
    """An empty declaration that would OVERRIDE the code's own fallback.

    `??` falls back on `undefined`, not on `""` — and a bare `KEY=` line produces `""`.
    So a template that declares `NEXT_PUBLIC_API_BASE_URL=` turns
    `process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"` into `""` for
    everyone who copies it: every request goes relative and 404s. The declaration file has
    to be safe to copy or it is a trap wearing a template's clothes.
    """
    failures: list[str] = []
    for key, value in sorted(state.declared.items()):
        if value:
            continue
        defaults = sorted(default for default in state.usage.fallbacks.get(key, set()) if default)
        if defaults:
            failures.append(
                f"{DECLARATION_FILE.as_posix()} declares {key} empty, and the code reads it "
                f"as `process.env.{key} ?? {defaults[0]!r}`. `??` does not fall back on the "
                "empty string a bare `KEY=` line produces, so copying this template would "
                f'override that default with "". Declare the local value ({defaults[0]!r}) '
                "or drop the `??` from the read."
            )
    return failures


def duplicate_declarations(state: WebEnv) -> list[str]:
    return [
        f"{DECLARATION_FILE.as_posix()} declares {key} twice — dotenv keeps the LAST "
        "assignment, so the line somebody edits may not be the line that wins"
        for key in state.duplicates
    ]


def stale_registry(state: WebEnv, registry: dict[str, str] | None = None) -> list[str]:
    """`PUBLIC_BY_DESIGN` may only shrink, and every entry must still name something real.

    The two ways an exemption list becomes a hiding place, both refused: an entry for a key
    that no longer exists (a hole waiting for the next key to land on that name), and an
    entry whose reason is not an argument a reviewer can weigh. Same contract as
    `check_compliance_invariants.stale_exemptions` and `check_wiring.stale_baseline`.
    """
    known = PUBLIC_BY_DESIGN if registry is None else registry
    live = set(state.declared) | set(state.usage.reads)
    failures: list[str] = []
    for key, reason in sorted(known.items()):
        if key not in live:
            failures.append(
                f"PUBLIC_BY_DESIGN names {key}, which this tree neither declares nor reads — "
                "remove it before it starts covering something else"
            )
        if len(reason.strip()) < 40:
            failures.append(
                f"PUBLIC_BY_DESIGN entry {key} has a reason too thin to review: {reason!r}. "
                "Say what makes this value public by the vendor's own definition"
            )
    return failures


# --- gate -------------------------------------------------------------------------


def evaluate(state: WebEnv) -> tuple[tuple[str, list[str]], ...]:
    return (
        ("this check cannot see its own subject", blind_spots(state)),
        ("the browser reads a variable nothing declares", undeclared_reads(state)),
        ("a declared variable nothing reads", unread_declarations(state)),
        ("a browser variable named like a secret", secret_shaped_keys(state)),
        ("an environment read `next build` cannot inline", uninlinable_reads(state)),
        (
            "an empty declaration that overrides the code's own default",
            empty_default_overrides(state),
        ),
        ("the declaration file contradicts itself", duplicate_declarations(state)),
        ("a registry entry that no longer holds", stale_registry(state)),
    )


def main(root: Path | None = None) -> int:
    state = collect(root)
    failed = False
    for title, offenders in evaluate(state):
        if offenders:
            failed = True
            print(f"WEB ENV PARITY: FAIL — {title}")
            for offender in offenders:
                print(f"  - {offender}")
    if failed:
        print(
            f"\nA browser variable is declared in {DECLARATION_FILE.as_posix()}, read as "
            "`process.env.NAME`, and never a secret. `next build` inlines it, so an "
            "undeclared or misspelled key is not an error — it is the empty string, in "
            "production. (The API's half of this rule is scripts/check_env_parity.py.)"
        )
        return 1

    print(
        f"WEB ENV PARITY: OK ({len(state.declared)} browser key(s) declared and read, "
        f"{state.usage.files} source files scanned, "
        f"{len(PUBLIC_BY_DESIGN)} public-by-design exemption(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
