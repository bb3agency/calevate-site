"""Guardrail: every vendor the CODE can send client data to is on the published register.

**THE FAILURE THIS EXISTS FOR.** `apps/web/src/lib/legal/subprocessors.ts` is the
authorised sub-processor list — clause 5 of the DPA makes it the list we notify changes
against, and the Privacy Policy incorporates it. It is checked today by
`apps/web/tests/legal.test.tsx`, which asks two questions: does the DPA avoid restating
the vendor list, and does the register render every identity it exports. Both compare the
register **against itself**. A vendor that is in the tree and on neither document is
perfectly consistent and completely invisible, and that is exactly how Supermemory came to
be two complete adapters (`apps/api/retrieval/supermemory.py`,
`supermemory_index.py`) whose settings `apps/api/core/platform_config.py` marks `LIVE` —
an operator can select it from the ops console with no deploy, at which point it receives
every published knowledge passage — while appearing nowhere on the page that tells a
client where their data goes.

The register's own header records an August 2026 audit that walked the same direction by
hand and found three missing vendors. This file is that audit as a gate, because the
August one closed the copy and left the MECHANISM open in its own words: *"nothing in the
tree can notice when our actual vendors and this list diverge."*

**HOW VENDOR IDENTITY IS DERIVED FROM CODE, AND WHY THIS SHAPE.** Two signals, both
structural, both chosen because they are what a vendor integration cannot exist without:

1. **A CREDENTIAL-SHAPED `Settings` FIELD.** `calevate_shared.config.Settings` is where
   every platform-held vendor credential and endpoint lives, and a field named
   `<vendor>_api_key` / `_auth_token` / `_base_url` / `_dsn` is the strongest evidence in
   this tree that we can reach a vendor at all. Derived by SHAPE rather than listed, so a
   new vendor's key is noticed the day it is added and not the day somebody remembers.
2. **A VENDOR ADAPTER MODULE.** `apps/api/engine/<vendor>.py` and
   `apps/api/retrieval/<vendor>*.py` are the two directories hard rule 2 lets hold vendor
   payload shapes on this side. A module there is a vendor we speak to.

Each signal yields a TOKEN (`supermemory`, `sarvam`, `azure_openai`, …), and `VENDOR_OF`
maps a token to the identity the register publishes — the two are not the same string and
must not be conflated: `gemini_api_key` and `google_oauth_client_secret` are both
**Google**, `azure_openai_api_key` is **Microsoft**. That map is the one hand-maintained
thing here, and it is small, one-directional and checked from both ends.

**BOTH DIRECTIONS, on `check_erasure_coverage`'s terms.**

* A token with no register identity fails — the missing-vendor direction, the one that
  costs a client their disclosure.
* A token deliberately outside the register is in `NOT_A_SUBPROCESSOR` with a reason (our
  own infrastructure, our own signing secrets, a vendor we only ever RECEIVE from).
* A register identity with no code signal at all is in `REGISTER_ONLY` with a reason —
  otherwise a vendor that left the tree lingers on a page a buyer's counsel reads, which
  is the drift the register's own header records for Clerk and Vertex.

**AND A BLIND-SPOT ARM** (`check_wiring`'s rule 5, `check_erasure_coverage`'s exit 2):
both sides of this comparison are parsed out of files, and a comparison whose right side
is empty answers "covered" for everything. So the scan asserts it can still see anchors on
each side before any verdict, and exits 2 REFUSED rather than printing one it cannot
stand behind.

Run: uv run python -m scripts.check_subprocessor_coverage    (no database needed)
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import get_args

from calevate_shared.config import EngineName

REPO_ROOT = Path(__file__).resolve().parent.parent

SETTINGS_SOURCE = REPO_ROOT / "packages" / "shared" / "src" / "calevate_shared" / "config.py"
REGISTER_SOURCE = REPO_ROOT / "apps" / "web" / "src" / "lib" / "legal" / "subprocessors.ts"
ADAPTER_DIRECTORIES: tuple[Path, ...] = (
    REPO_ROOT / "apps" / "api" / "engine",
    REPO_ROOT / "apps" / "api" / "retrieval",
)

#: An exemption is an argument, not a checkbox — `check_erasure_coverage`'s number and its
#: reasoning, kept the same so the registers cannot drift into different standards.
MIN_EXEMPTION_REASON = 40

#: The suffixes that make a `Settings` field a VENDOR REACH rather than a knob. A key, a
#: token, an auth id or a DSN is a credential; a base URL is an address we send to. All of
#: them mean "this deployment can talk to somebody".
_CREDENTIAL_SUFFIXES = (
    "_api_key",
    "_api_token",
    "_auth_token",
    "_auth_id",
    "_access_token",
    "_access_tokens",
    "_client_secret",
    "_key_secret",
    "_webhook_secret",
    "_base_url",
    "_endpoint",
    "_dsn",
)

#: token -> the identity the register publishes for it, or None when the token is a real
#: vendor reach whose identity the register deliberately does not name (the not-yet-chosen
#: hosting provider is the only such row today: `names: []`).
#:
#: THE MAP IS ONE-DIRECTIONAL AND IT IS THE ONLY HAND-MAINTAINED THING HERE. A token this
#: map does not know fails rather than being skipped, so adding a vendor to the tree costs
#: one line here and one row on the register — which is the point.
VENDOR_OF: dict[str, str | None] = {
    "sarvam": "Sarvam",
    "gnani": "Gnani",
    "supermemory": "Supermemory",
    # The media stream address and the two halves of the channel our own container on that
    # platform uses to reach our API. All the Pipecat Cloud leg, and `PIPECAT_WORKER_*` is
    # deliberately not a credential FOR Pipecat's API (see CLAUDE.md) — it still only
    # exists because the worker runs there. The bare `pipecat` token is derived below with
    # the other engine names.
    "pipecat_stream": "Pipecat Cloud",
    "pipecat_worker": "Pipecat Cloud",
    "pipecat_worker_api": "Pipecat Cloud",
    # R2 is Cloudflare's object storage; the endpoint is how we address it.
    "object_store": "Cloudflare",
    # NO IDENTITY, DELIBERATELY, and this is the one value in the map that means "the
    # register carries a row with no vendor name". An OTLP collector address is whatever
    # an operator points it at — our own box, or a hosted tracing vendor — so there is no
    # brand to publish, exactly as there is none for the hosting provider row. ⚠ THE LIMIT
    # IS WORTH STATING: a `None` here cannot be checked BY NAME against the register, so
    # the unnamed row it refers to is held by `apps/web/tests/legal.test.tsx`'s structural
    # checks and by a reader, not by this scan.
    "otel_exporter_otlp": None,
    "plivo": "Plivo",
    "razorpay": "Razorpay",
    "resend": "Resend",
    "sentry": "Sentry",
    "openai": "OpenAI",
    # Azure OpenAI is Microsoft's product; the register names the COMPANY in `names` and
    # the product in the Vendor cell, which is why these two tokens do not agree.
    "azure_openai": "Microsoft",
    # Three Google services, one identity. `gemini_api_key` is the model leg,
    # `google_oauth_client_secret` the Sheets and Calendar legs.
    "gemini": "Google",
    "google_oauth": "Google",
    # Both Meta legs: the Cloud API credential and the Lead Ads page tokens.
    "whatsapp_cloud": "Meta",
    "meta_page": "Meta",
}

#: Credential-shaped fields that reach NOBODY outside this system, each with the reason.
#: Without this the shape rule would report our own database, our own signing secrets and
#: our own callback addresses as undisclosed sub-processors, and a guard that cries about
#: `database_url` is one whose findings get skimmed.
NOT_A_SUBPROCESSOR: dict[str, str] = {
    "actions_callback": (
        "OUR OWN public address, handed to a client's integration so that it can call US "
        "back. Nothing of a client's is sent anywhere by its existence; it is the inbound "
        "door, not an outbound reach."
    ),
    "webhook": (
        "OUR OWN public address, used to build the callback URLs we publish to clients and "
        "to vendors. Same shape and same reason as the entry above: an address we are "
        "reached AT is not a vendor we send to."
    ),
    # ⚠ THIS ENTRY IS TRUE TODAY AND IS THE ONE HERE THAT CAN STOP BEING TRUE. Every other
    # line above describes an address we are REACHED AT, which no configuration can turn
    # into an outbound reach. This one describes a vendor seam with no vendor in it: the
    # identity-aggregator adapter set (D-635) contains one declared-and-unimplemented
    # provider and no other, `kyc_verification_provider` is unset on every deployment, and
    # `kyc_providers.available_provider()` refuses on both counts — so no client's data
    # reaches anybody through it, and the register would be naming a party that receives
    # nothing.
    #
    # CONFIGURING A PROVIDER MAKES IT A SUB-PROCESSOR AND THIS ENTRY FALSE. The aggregator
    # would be verifying an identity on our instruction, which is processing on our behalf
    # however the data reaches them, and `/legal/subprocessors` must gain a row (with its
    # own revision and hash) BEFORE `kyc_verification_provider` is ever set. Moving the
    # token to VENDOR_OF is the second half of that same change.
    "kyc_verification": (
        "The client identity-verification aggregator seam (D-635) with no aggregator in "
        "it: no provider is configured on any deployment, the one declared adapter is "
        "unimplemented because its documentation is egress-blocked, and the selector "
        "refuses on both counts — so nothing of a client's reaches anybody through it. "
        "Configuring a provider makes this false and requires a register row first; see "
        "the comment above this entry."
    ),
}

#: Register identities with no signal in the tree, each with the argument for keeping them
#: published. The other direction of the same rule: a vendor that left the code and stayed
#: on the page is the Clerk/Vertex drift the register's own header records.
REGISTER_ONLY: dict[str, str] = {
    "Exotel": (
        "A candidate carrier. No account, no credential and no adapter — the only carrier "
        "with code in the tree is Plivo. Published because the carrier is not chosen yet "
        "and a client evaluating the product is entitled to see the candidates."
    ),
    "Vobiz": (
        "A candidate carrier, on the same footing as Exotel: no account, no credential and "
        "no adapter. It is named so the register describes the decision that is open rather "
        "than only the one line of code that exists."
    ),
    "Cohere": (
        "A contingency embedding vendor, and the register's own header already records that "
        "it 'appears nowhere in the code at all, which is what Contingency. Not selected. "
        "should look like'. Kept as a declared alternative under the DPA's change clause."
    ),
    "AiSensy": (
        "A WhatsApp Business Solution Provider reached with a credential the CLIENT supplies "
        "for their own account, so there is no platform Settings field to find. The adapter "
        "is `apps/api/actions/whatsapp.py::build_aisensy`, outside the two directories this "
        "scan treats as vendor-adapter homes."
    ),
    "Interakt": (
        "The alternative Solution Provider beside AiSensy, on the same client-supplied "
        "credential and built by the same module. Same reason, same file."
    ),
}


#: What each side must still be able to see. A parse that silently stopped working would
#: otherwise report every vendor as undisclosed (noise, which gets exempted away) or every
#: register row as unbacked.
def _engine_vendor(engine: str) -> str | None:
    """The company behind one engine name, or `None` where there is no company.

    ⚠ **A FUNCTION OF COMPARISONS RATHER THAN A DICT, AND THE SHAPE IS THE POINT.** The
    engine set has exactly two homes (`calevate_shared.config.EngineName` and
    `pyproject.toml`'s import-linter contract), and `tests/engine_name_drift_test.py`
    refuses a third copy — correctly: this file had all three engine names as keys of one
    dict, which is a SET spelled a third time and the exact drift that guard exists to
    catch. A per-name comparison is what a factory does and is explicitly not flagged.

    It RAISES on a name it has not been taught, and that is the second half: the keys are
    generated from `EngineName` below, so adding a fourth engine fails this guard loudly
    instead of leaving its vendor silently unpublished — which is the failure this whole
    script was written for.
    """
    if engine == "fake":
        return None  # an in-process double; there is no company behind it.
    if engine == "bolna":
        return "Bolna"
    if engine == "cartesia":
        return "Cartesia"
    if engine == "pipecat":
        return "Pipecat Cloud"
    raise ValueError(
        f"{engine!r} is a declared engine with no vendor identity here. Add it, and add "
        "its row to apps/web/src/lib/legal/subprocessors.ts — an engine is a company that "
        "receives client data."
    )


# DERIVED, NOT SPELLED: the one place this file learns which engines exist is the
# canonical home. `update` rather than a literal merge so no collection in this module
# holds two engine names.
VENDOR_OF.update({name: _engine_vendor(name) for name in get_args(EngineName)})

SETTINGS_ANCHORS = frozenset({"sarvam", "sentry"})
REGISTER_ANCHORS = frozenset({"Bolna", "Microsoft", "Sarvam"})

_FIELD = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass
class CodeVendors:
    """The vendor tokens the tree can reach, and where each was found."""

    tokens: dict[str, list[str]] = field(default_factory=dict)
    blind_spots: list[str] = field(default_factory=list)

    def add(self, token: str, where: str) -> None:
        self.tokens.setdefault(token, []).append(where)


def settings_fields(path: Path = SETTINGS_SOURCE) -> list[str]:
    """Every annotated field name on `Settings`, read from the AST.

    The CLASS BODY and not a grep, for `check_erasure_coverage._module_strings_and_
    functions`' reason: a regex over the file would also match a field named in a comment
    or in one of this file's long prose blocks, and half the vendor discussion in this
    tree happens in comments.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return [
                statement.target.id
                for statement in node.body
                if isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and _FIELD.match(statement.target.id)
            ]
    return []


def _token_of(field_name: str) -> str | None:
    """The vendor token a credential-shaped field names, or None if it is not one.

    LONGEST SUFFIX FIRST. `razorpay_key_secret` ends in `_key_secret` and also in
    `_secret`; stripping the shorter one would leave the token `razorpay_key`, which maps
    to nothing and would be reported as an undisclosed vendor called "razorpay key".
    """
    for suffix in sorted(_CREDENTIAL_SUFFIXES, key=len, reverse=True):
        if field_name.endswith(suffix):
            token = field_name[: -len(suffix)]
            return token or None
    return None


def code_vendors() -> CodeVendors:
    """Every vendor token this tree can reach, from both signals."""
    found = CodeVendors()

    fields = settings_fields()
    if not fields:
        found.blind_spots.append(
            f"no annotated fields parsed from Settings in "
            f"{SETTINGS_SOURCE.relative_to(REPO_ROOT)} — the class was renamed, moved, or "
            "the parse broke, and every verdict below would be about this scan"
        )
    for name in fields:
        token = _token_of(name)
        if token is not None:
            found.add(token, f"Settings.{name}")

    for directory in ADAPTER_DIRECTORIES:
        if not directory.exists():
            found.blind_spots.append(
                f"adapter directory {directory.relative_to(REPO_ROOT)} does not exist"
            )
            continue
        for module in sorted(directory.glob("*.py")):
            stem = module.stem
            if stem.startswith("_") or stem.endswith("_test"):
                continue
            # A module is a vendor adapter only if its NAME is a token we already know
            # from a credential, or one the map names. Treating every module in these
            # directories as a vendor would report `service`, `routing` and `tiered` —
            # our own composition code — as undisclosed companies.
            for token in (stem, stem.split("_")[0]):
                if token in VENDOR_OF or token in found.tokens:
                    found.add(token, str(module.relative_to(REPO_ROOT)))
                    break
    return found


def register_identities(path: Path = REGISTER_SOURCE) -> set[str]:
    """Every identity the published register exports, read out of its `names` arrays.

    The TypeScript is parsed the shallow way on purpose: `names: [...]` is the field the
    register's own `SUBPROCESSOR_NAMES` is derived from, it is a literal in every row, and
    a real TS parser in a Python guard would be a second toolchain to keep alive. The
    anchors below are what makes the shallow read safe — if the shape ever changes, this
    stops finding Bolna and refuses to score.
    """
    text = path.read_text(encoding="utf-8")
    identities: set[str] = set()
    for block in re.findall(r"^\s*names:\s*\[([^\]]*)\]", text, re.MULTILINE):
        identities |= set(re.findall(r'"([^"]+)"', block))
    return identities


def evaluate(
    found: CodeVendors,
    published: set[str],
    *,
    vendor_of: dict[str, str | None] | None = None,
    not_a_subprocessor: dict[str, str] | None = None,
    register_only: dict[str, str] | None = None,
) -> list[str]:
    """Every failure the tree deserves. Pure — tests feed it synthetic inputs."""
    known = dict(VENDOR_OF if vendor_of is None else vendor_of)
    internal = dict(NOT_A_SUBPROCESSOR if not_a_subprocessor is None else not_a_subprocessor)
    register_only_reasons = dict(REGISTER_ONLY if register_only is None else register_only)
    failures: list[str] = []

    # 1. THE DIRECTION THAT COSTS A CLIENT THEIR DISCLOSURE.
    for token in sorted(found.tokens):
        where = ", ".join(sorted(set(found.tokens[token])))
        if token in internal:
            continue
        identity = known.get(token, ...)
        if identity is ...:
            failures.append(
                f"{token}: this deployment can reach a vendor by this name ({where}) and "
                "nothing here knows who it is. Map it in VENDOR_OF to the identity the "
                "sub-processor register publishes, or register it in NOT_A_SUBPROCESSOR "
                "with why nothing of a client's reaches anybody through it."
            )
            continue
        if identity is not None and identity not in published:
            failures.append(
                f"{identity}: reachable from this tree ({where}) and ABSENT from the "
                "sub-processor register. That register is the authorised list the DPA "
                "notifies changes against and the Privacy Policy incorporates, so a "
                "vendor missing from it is an undisclosed recipient of client data. Add "
                "the row — including its Status, which is where 'configured but not "
                "selected' is said honestly."
            )

    # 2. The reverse: a vendor on the page with nothing behind it.
    identities_in_code = {
        known[token]
        for token in found.tokens
        if token not in internal and known.get(token) is not None
    }
    for identity in sorted(published):
        if identity in identities_in_code or identity in register_only_reasons:
            continue
        failures.append(
            f"{identity}: published on the sub-processor register and reachable from "
            "nothing in this tree. A vendor that left the code and stayed on the page is "
            "the drift that kept Clerk and Vertex in client-facing copy after they were "
            "replaced. Remove the row, or register it in REGISTER_ONLY with why it is "
            "right that a client still sees it."
        )

    # 3. Both registers stay honest, `check_erasure_coverage`'s rule 4 exactly.
    for identity, reason in sorted(register_only_reasons.items()):
        if identity not in published:
            failures.append(
                f"{identity}: STALE REGISTER_ONLY entry — no such identity on the "
                "register. Remove it; a dead exemption hides the next real gap."
            )
        elif identity in identities_in_code:
            failures.append(
                f"{identity}: registered as having no code signal, and the scan found "
                "one. One of the two is wrong and a reviewer cannot tell which."
            )
        if len(reason.strip()) < MIN_EXEMPTION_REASON:
            failures.append(
                f"{identity}: REGISTER_ONLY reason is too thin to review ({reason.strip()!r})."
            )
    for token, reason in sorted(internal.items()):
        if token not in found.tokens:
            failures.append(
                f"{token}: STALE NOT_A_SUBPROCESSOR entry — no credential-shaped setting "
                "carries this token any more. Remove it."
            )
        if len(reason.strip()) < MIN_EXEMPTION_REASON:
            failures.append(
                f"{token}: NOT_A_SUBPROCESSOR reason is too thin to review "
                f"({reason.strip()!r}). State what it reaches and why no client's data "
                "goes through it."
            )
    return failures


def main() -> int:
    found = code_vendors()
    published = register_identities()

    # THE BLIND-SPOT ARM RUNS FIRST and exits 2, `check_erasure_coverage`'s convention:
    # "I could not see my subject" is a different answer from "I looked and this is
    # wrong", and a guard that cannot tell them apart has a green that means nothing.
    missing_settings = sorted(SETTINGS_ANCHORS - set(found.tokens))
    missing_register = sorted(REGISTER_ANCHORS - published)
    if found.blind_spots or missing_settings or missing_register:
        print("SUBPROCESSOR COVERAGE: REFUSED TO SCORE")
        for blind in found.blind_spots:
            print(f"  - {blind}")
        if missing_settings:
            print(
                f"  - the settings scan found {len(found.tokens)} vendor token(s) and "
                f"none of {missing_settings}"
            )
        if missing_register:
            print(
                f"  - the register scan found {len(published)} identit(ies) and none of "
                f"{missing_register}; `names:` no longer parses"
            )
        return 2

    failures = evaluate(found, published)
    if failures:
        print("SUBPROCESSOR COVERAGE: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"SUBPROCESSOR COVERAGE: OK ({len(found.tokens)} vendor token(s) in the tree; "
        f"{len(published)} identit(ies) published; {len(NOT_A_SUBPROCESSOR)} internal, "
        f"{len(REGISTER_ONLY)} published with no code signal)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
