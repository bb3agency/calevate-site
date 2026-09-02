"""User-facing messages are written for people, not for API clients.

No decision-log entry is cited here on purpose: this rule was set by the founder after
reading the screen below, and `docs/` belongs to another sweep. When it gets a number,
put it in this line.

WHAT THIS GUARDS. A live sign-in refusal was photographed reading:

    One or more fields are invalid.
    Correct the fields named in this response and send the request again.
    • password: String should have at least 12 characters
    Support reference: 9c83825c95f2495d87a4194ba0ef2849

Four failures in one box: a next step addressed to an API client, pydantic's own
validator text passed through verbatim (it names a TYPE), the input named in its
programmatic spelling, and a 32-character reference given the same weight as the one
thing the person had to do — use a longer password. `apps/api/core/errors.py` is where
three of the four came from and where they are fixed; this is what stops them coming
back, and stops the next raise site writing the same sentence somewhere else.

WHAT IT READS. The three strings of the problem+json ladder that a screen renders —
`title`, `detail`, `remediation` — wherever they are passed as literals to a
`*Error(...)` constructor, plus any `*_REMEDIATION` mapping. Nothing else: not
docstrings, not comments, not log lines, not `code`/`kind`/`field` (machine identifiers,
which SHOULD be machine-spelled). A guard that flagged legitimate prose would be turned
off within the week, and a turned-off guard is worse than none.

DELIBERATE LIMITS — each one is a place this cannot see, named so nobody mistakes a pass
for a promise:

- **Literals only.** A `detail=` built from a variable, or a sentence assembled by a
  helper, is invisible here. The vocabulary below is the check; the AST is only how it
  finds text to check.
- **The console's own copy is not read.** Button labels, empty states and form hints live
  in `apps/web/`; this reads the API's messages. The console has its own sweep.
- **Words a technical reader legitimately needs are NOT banned**: `endpoint`, `header`,
  `token`, `JSON`, `webhook`, `URL`. They appear in messages whose reader is whoever is
  wiring a webhook or calling the API, where a vaguer word would be less accurate, and
  accuracy outranks warmth. What is banned below is the vocabulary that is never right
  for anybody: a type name, a library's validator text, an exception class, a column
  name, and the second-person-to-a-machine phrasing of "send the request again".
- **`_UNSWEPT` is a ratchet, not an amnesty.** Each entry is a file whose messages were
  written before this rule and a count of what it still carries. The count may fall and
  may never rise: a new bad sentence in an old file fails here exactly like a new bad
  sentence in a new file. When a file's owner sweeps it, its line goes.

WHY NOT `scripts/check_*.py`. `tests/guardrail_audit_test.py` requires every such script
to be wired into both the Makefile and `.github/workflows/ci.yml`; this rule needs no
database, no network and no separate step, so it is an ordinary test in the suite CI
already runs. One way per problem.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where problem+json is raised. `packages/` is included so a shared helper that grows a
#: message is covered on the day it is written.
SCAN_ROOTS = ("apps/api", "apps/voice-runtime", "apps/workers", "packages")

#: The keyword arguments a screen renders. `code`, `kind` and `field` are machine
#: identifiers and are deliberately absent. Strings found in a wording MAPPING carry the
#: key `remediation` or `message` instead, since a mapping does not name its own role.
RENDERED_KEYS = frozenset({"title", "detail", "remediation"})


@dataclass(frozen=True)
class Message:
    """One string a person can end up reading, and where it is written."""

    file: str
    line: int
    key: str
    text: str


# --- the vocabulary -------------------------------------------------------------------
#
# Each rule is a class of leak, not a word list for its own sake.
#
# THE STANDARD BEHIND THEM, and the evidence class of each (hard rule 11): both sources
# are EGRESS-BLOCKED from this container, so neither page was opened here. What was read,
# on 2 Sep 2026, is web-search results quoting them.
#
# - Nielsen Norman Group, "Error-Message Guidelines"
#   (https://www.nngroup.com/articles/error-message-guidelines/): human-readable
#   language, error codes hidden or minimised and shown for diagnosis only, constructive
#   advice rather than a bare statement of the problem, and a tone that does not blame —
#   naming "invalid", "illegal" and "incorrect" as the phrasings that do. The last of
#   those is why `_BLAMING` exists below and why the support reference in the ladder is
#   secondary to the sentence.
# - GOV.UK Design System, "Error message" and the "Recover from validation errors"
#   pattern (https://design-system.service.gov.uk/components/error-message,
#   .../patterns/validation/): explain what went wrong AND how to fix it, and word it as
#   the person would ("Date you started the course must be after 31 August 2017"), which
#   is the shape `_message_for` in `apps/api/core/errors.py` renders every rule into.

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "a library's own validator text",
        re.compile(
            r"\b(?:string|input|value) should\b|value is not a valid|field required"
            r"|extra inputs are not permitted|ensure this value",
            re.I,
        ),
    ),
    (
        "a type name",
        re.compile(r"\b(?:NoneType|null|boolean|integer|string|datetime)\b", re.I),
    ),
    (
        "an internals word",
        re.compile(
            r"\b(?:payloads?|schemas?|parameters?|constraints?|validation|regexp?"
            r"|regular expression|tracebacks?|stack trace|serialis[ez]|deserialis[ez]"
            r"|exceptions?|attributes?|enum|mime ?type|query string|status code)\b",
            re.I,
        ),
    ),
    (
        "the request/response as a thing the reader can see",
        # "Request a new link" is a verb and stays; "Request blocked" and "repeat this
        # request" are the HTTP object, which no person reading a screen has in front of
        # them.
        re.compile(
            r"\b(?:the|this|a|your|each|every|that|its)\s+(?:HTTP\s+)?(?:request|response)\b"
            r"|^(?:Request|Response)\b(?!\s+(?:a|an|another|new))",
            re.I,
        ),
    ),
    (
        "a form input called a field",
        re.compile(
            r"\b(?:the|this|that|each|every|its|one or more)\s+fields?\b|fields? named", re.I
        ),
    ),
    ("an exception class", re.compile(r"\b[A-Z][A-Za-z]*(?:Error|Exception)\b")),
    (
        "a protocol or a status code",
        # `http://` and `https://` are addresses a person types; the bare words are not.
        re.compile(r"\bHTTPS?\b(?![:/])|\bHTTP\s*\d{3}\b", re.I),
    ),
    (
        # NN/g names these three as the phrasings that blame the reader for what the
        # system could not do. "That card is not valid" is fine; "Invalid card" is not.
        "a word that blames the reader",
        re.compile(r"\b(?:invalid|illegal|incorrect|malformed)\b", re.I),
    ),
    (
        "phrasing addressed to an API client",
        re.compile(r"send the request again|request body|in this response|on this response", re.I),
    ),
)

#: A `snake_case` name is a column, a key or a parameter in its machine spelling. Names
#: inside backticks are exempt: a message that says press `Idempotency-Key` is quoting a
#: literal the reader types, which is the one time the machine spelling IS the right word.
_MACHINE_NAME = re.compile(r"(?<![\w`{])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w`}])")

_QUOTED = re.compile(r"`[^`]*`")


def violations(text: str) -> list[str]:
    """What is wrong with one string, in the words a reviewer would use. Empty is clean."""
    readable = _QUOTED.sub("``", text)
    found = [
        f"{name}: {match.group(0)!r}"
        for name, pattern in _RULES
        if (match := pattern.search(readable))
    ]
    if machine := _MACHINE_NAME.search(readable):
        found.append(f"a name in its machine spelling: {machine.group(0)!r}")
    return found


# --- finding the strings --------------------------------------------------------------


def _literal(node: ast.expr) -> str | None:
    """A string literal, an f-string's fixed parts, or two of either added together.

    An f-string's `{}` holes are kept as `{}` rather than dropped: a sentence is judged on
    the words around the value, and joining the halves would invent adjacencies.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        parts = [
            value.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
            else "{}"
            for value in node.values
        ]
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        return left + right if left is not None and right is not None else None
    return None


def _raises_a_problem(call: ast.Call) -> bool:
    """`ProblemError(...)`, one of its constructors, or any error class in the tree.

    By NAME rather than by import: every problem type in this repo ends in `Error`, and a
    check that resolved imports would go blind the first time somebody aliased one.

    `cls(...)` and `super().__init__(...)` count too. They are how a constructor and a
    subclass write their messages — `ProblemError.unauthorized`'s "Please sign in" is a
    `cls(` call — so a check that only saw the class name by spelling would miss the
    defaults that every screen without its own sentence renders.
    """
    func = call.func
    if isinstance(func, ast.Name):
        return func.id.endswith("Error") or func.id == "cls"
    if isinstance(func, ast.Attribute):
        if func.attr == "__init__":
            return True
        return isinstance(func.value, ast.Name) and func.value.id.endswith("Error")
    return False


def _strings_in(node: ast.expr) -> list[str]:
    """The strings a wording mapping HOLDS — never the keys it is looked up by.

    A dict key is `"not_found"`, a machine identifier that the vocabulary below would
    (correctly, in a sentence) read as a column name. Walking the whole node would
    therefore report the ladder's own kinds as findings.
    """
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, ast.Dict):
        return [text for value in node.values if value is not None for text in _strings_in(value)]
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return [text for element in node.elts for text in _strings_in(element)]
    if isinstance(node, ast.JoinedStr | ast.BinOp):
        literal = _literal(node)
        return [literal] if literal else []
    return []


def _reads_as_prose(text: str) -> bool:
    """Is this a sentence, or an identifier that happens to live in a wording mapping?

    MEASURED, not assumed: `ARQ_TERMINAL_MESSAGES` in `apps/workers/settings.py` maps
    alert CODES (`job_retries_exhausted`) and a suffix-shaped rule reported both of them
    as leaked column names. A rendered message has at least two words; a code has none.
    """
    return " " in text.strip()


def _mapping_key(node: ast.Assign | ast.AnnAssign) -> str | None:
    """The kind of string a `..._REMEDIATION` / `..._TEXT` mapping holds, or None."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    for target in targets:
        if not isinstance(target, ast.Name):
            continue
        name = target.id.upper()
        if name.endswith("REMEDIATION"):
            return "remediation"
        if name.endswith(("_TEXT", "_MESSAGES", "_MESSAGE")):
            return "message"
    return None


def messages_in(source: str, where: str) -> list[Message]:
    """Every rendered string a module writes as a literal."""
    found: list[Message] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _raises_a_problem(node):
            for keyword in node.keywords:
                if keyword.arg in RENDERED_KEYS and (text := _literal(keyword.value)):
                    found.append(Message(where, node.lineno, keyword.arg, text))
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            # The ladder's floors and the framework handler's per-status wording are
            # MAPPINGS, not calls: `_DEFAULT_REMEDIATION` alone is the next step on every
            # refusal in the product that wrote none of its own. A scanner that walked
            # only constructors would be blind to the most-read strings there are.
            key = _mapping_key(node)
            if key is not None and node.value is not None:
                found.extend(
                    Message(where, node.lineno, key, text)
                    for text in _strings_in(node.value)
                    if _reads_as_prose(text)
                )
    return found


def rendered_messages(root: Path | None = None) -> list[Message]:
    """Every rendered string in the tree, sorted so a failure reads the same twice."""
    base = root or REPO_ROOT
    found: list[Message] = []
    for scan_root in SCAN_ROOTS:
        for path in sorted((base / scan_root).rglob("*.py")):
            relative = path.relative_to(base).as_posix()
            try:
                found.extend(messages_in(path.read_text(encoding="utf-8"), relative))
            except SyntaxError:
                # A file mid-edit does not parse. Skipping it is safe HERE and only here:
                # a module that will not compile cannot ship past ruff, mypy or the suite,
                # so nothing hides in one for longer than it takes to save the next time.
                continue
    return sorted(found, key=lambda m: (m.file, m.line, m.key, m.text))


def findings(root: Path | None = None) -> list[tuple[Message, list[str]]]:
    return [
        (message, bad) for message in rendered_messages(root) if (bad := violations(message.text))
    ]


# --- what the tree still carries ------------------------------------------------------
#
# Every entry is a file whose messages predate this rule, with the number of findings it
# held when the rule landed (2 Sep 2026). THE NUMBER MAY FALL AND MAY NEVER RISE: a new
# bad sentence in an old file fails here exactly like one in a new file. When a file's
# owner rewrites its messages, its line goes — the reasons below say what each one is
# waiting for, and none of them is "this is fine forever".
_UNSWEPT: dict[str, int] = {
    # Words for API-shaped things said to whoever is calling the API — an operator
    # pasting a registration number, an integrator wiring a lead source. Accurate today,
    # still not the words the console should print at a business owner.
    "apps/api/actions/service.py": 9,
    "apps/api/admin/routes.py": 3,
    "apps/api/admin/service.py": 1,
    "apps/api/agents/llm_models.py": 1,
    "apps/api/agents/publishing.py": 1,
    "apps/api/compliance/consent.py": 1,
    "apps/api/crm/routes.py": 1,
    "apps/api/crm/service.py": 1,
    "apps/api/ingest/routes.py": 3,
    "apps/api/ingest/service.py": 2,
    "apps/api/integrations/egress_guard.py": 1,
    "apps/api/ops/config_routes.py": 1,
    "apps/api/ops/config_service.py": 3,
    "apps/api/ops/model_price_routes.py": 1,
    "apps/api/ops/model_pricing.py": 1,
    "apps/api/ops/routes.py": 2,
    "apps/api/ops/service.py": 1,
    "apps/api/billing/payments.py": 4,
    "apps/api/billing/plans.py": 2,
    "apps/api/campaigns/service.py": 2,
    # Reached by a person, in the console, on an ordinary day. These are the ones worth
    # rewriting first.
    "apps/api/agents/experiments.py": 1,
    "apps/api/agents/extraction_routes.py": 1,
    "apps/api/agents/service.py": 1,
    "apps/api/authn/cookies.py": 2,
    "apps/api/authn/stepup.py": 1,
    "apps/api/copilot/sanitize.py": 1,
    "apps/api/copilot/service.py": 1,
    "apps/api/core/middleware.py": 4,
    "apps/api/core/stepup.py": 1,
    "apps/api/flags/service.py": 1,
    "apps/api/quality/service.py": 1,
    # The vendor leg. A voice-engine failure surfaces on an operator's screen, so these
    # are not exempt in principle — they are unswept, and the adapter is one owner away.
    "apps/api/engine/bolna.py": 1,
    "apps/api/engine/fake.py": 5,
    "apps/api/engine/vendor_http.py": 2,
    # NOT a person on the other end: the voice engine POSTs these webhooks and an ARQ job
    # reads these. "Payload too large" to the engine is the accurate word. Listed rather
    # than exempted, because the day one of these reaches a screen it should be counted.
    "apps/voice-runtime/tool_routes.py": 2,
    "apps/voice-runtime/webhook_routes.py": 4,
    "apps/workers/pipeline.py": 2,
    # Two audiences in one mapping: `_ASSIST_REMEDIATION` is keyed by (audience, reason)
    # and the OPERATOR half is deliberately technical — it names the module that owns the
    # ceiling, which is the point of it. The audience lives in the key, where this cannot
    # see it, so the operator lines are waived rather than rewritten.
    "apps/workers/extraction.py": 2,
}


# --- the sentences this exists to catch, and the ones it must not ----------------------

#: The photographed screen, plus one of each rule. Real strings where the tree had one.
_MUST_BE_CAUGHT = (
    "One or more fields are invalid.",
    "Correct the fields named in this response and send the request again.",
    "String should have at least 12 characters",
    "Request validation failed",
    "Input should be a valid integer",
    'Send the amount as a decimal string, for example "2500.00".',
    "Nothing was credited. Check the provider's payload contract.",
    "Repeat the request with the header X-Confirm-Action: confirm",
    "Request body exceeds 1048576 bytes.",
    "Send load_shed_mode, outbound_halted, or both.",
    "A ValueError escaped while saving.",
    "The server answered HTTP 502.",
    "Use YYYY-MM, or omit the parameter for the current month.",
    "Choose one of these, or send null to fall back to the account default.",
)

#: Sentences that must stay clean. Every one is real prose from this tree or from the
#: rewritten ladder — a guard is calibrated against what people actually write, not
#: against what is easy to pass.
_MUST_STAY_CLEAN = (
    "Password needs to be at least 12 characters.",
    "That card was not accepted by your bank.",
    "Email has to look like name@example.com.",
    "Tags needs at least 1 item.",
    "We could not find that lead.",
    "Request a new password reset link and use the newest email.",
    "Check the most recent email, or request a new code.",
    "Send an `Idempotency-Key` header — one fresh value per attempt.",
    "Only http:// and https:// destinations can receive leads; 'ftp://x' cannot.",
    "Use the https:// URL of your endpoint.",
    "Paste the API key or token from your provider's dashboard.",
    "Wait a few seconds, then try again.",
    "Reload the page — something changed since you opened it — then try again.",
    "This mapping would reject every lead: none of its rules says which field of your "
    "form carries the phone number.",
    "Your plan does not include outbound calling. Ask us to add it.",
    "The knowledge base is still being read. Try again in a minute.",
)


# ============================================================================
# wiring — the check is looking at the real messages
# ============================================================================


class TestWiring:
    def test_it_reads_the_real_tree_and_finds_a_lot_of_it(self) -> None:
        """A scanner that has drifted off the raise sites reports a clean tree by finding
        nothing at all, which is why the floor is pinned rather than the exact number."""
        messages = rendered_messages()
        assert len(messages) > 500, "the scan stopped seeing the tree's messages"
        assert {message.key for message in messages} >= RENDERED_KEYS
        files = {message.file for message in messages}
        assert "apps/api/core/errors.py" in files, "the ladder itself must be in scope"
        assert any(file.startswith("apps/voice-runtime/") for file in files)

    def test_it_sees_the_ladder_floor_that_every_screen_renders(self) -> None:
        """`_DEFAULT_REMEDIATION` is a mapping, not a call — the commonest next step in
        the product would be invisible to a scanner that only walked constructors."""
        ladder = {
            message.text
            for message in rendered_messages()
            if message.file == "apps/api/core/errors.py"
        }
        assert "Wait a few seconds, then try again." in ladder
        assert "Please sign in" in ladder

    def test_every_unswept_file_still_exists(self) -> None:
        """A waiver naming a file nobody has is a waiver nobody can retire."""
        for file in _UNSWEPT:
            assert (REPO_ROOT / file).is_file(), f"{file} is waived and does not exist"


# ============================================================================
# detection — it fails on the sentences it exists to catch
# ============================================================================


class TestDetection:
    def test_the_photographed_screen_is_caught_line_by_line(self) -> None:
        for sentence in _MUST_BE_CAUGHT:
            assert violations(sentence), f"not caught: {sentence!r}"

    def test_a_new_bad_message_in_a_clean_file_is_found_with_its_place(self) -> None:
        """The mutation is a raise site, written the way one is really written."""
        source = (
            "from apps.api.core.errors import ProblemError\n"
            "def f() -> None:\n"
            "    raise ProblemError(\n"
            '        kind="validation", code="x", title="Request validation failed",\n'
            '        detail="One or more fields are invalid.",\n'
            '        remediation="Correct the fields named in this response.",\n'
            "    )\n"
        )
        found = messages_in(source, "apps/api/probe.py")
        assert {message.key for message in found} == {"title", "detail", "remediation"}
        assert all(violations(message.text) for message in found)

    def test_an_f_string_message_is_read_rather_than_skipped(self) -> None:
        source = 'X = ProblemError(detail=f"String should have at least {least} characters.")\n'
        (message,) = messages_in(source, "apps/api/probe.py")
        assert violations(message.text)

    def test_a_remediation_map_is_read(self) -> None:
        source = (
            '_DEFAULT_REMEDIATION = {"validation": "Correct the fields named in this response."}\n'
        )
        (message,) = messages_in(source, "apps/api/probe.py")
        assert message.key == "remediation"
        assert violations(message.text)

    def test_a_waived_file_that_grows_a_new_bad_message_fails(self) -> None:
        """The waiver is a budget, not an amnesty: this is the mutation that proves it."""
        budgets = dict(_UNSWEPT)
        over = {file: budget - 1 for file, budget in budgets.items()}
        assert _over_budget(over), "a tightened budget reported nothing — the count is not read"

    def test_the_reason_names_the_class_rather_than_just_failing(self) -> None:
        assert "a library's own validator text: 'String should'" in violations(
            "String should have at least 12 characters"
        )
        assert "a name in its machine spelling: 'load_shed_mode'" in violations(
            "Send load_shed_mode, outbound_halted, or both."
        )


# ============================================================================
# calibration — it stays quiet on prose that is already right
# ============================================================================


class TestCalibration:
    def test_real_good_sentences_are_not_flagged(self) -> None:
        for sentence in _MUST_STAY_CLEAN:
            assert violations(sentence) == [], f"false positive: {sentence!r}"

    def test_request_as_a_verb_survives_and_request_as_an_object_does_not(self) -> None:
        """The distinction the vocabulary turns on. "Request a new code" is what a person
        does; "this request" is a thing only the
        caller's software can see."""
        assert violations("Request a new code and try again.") == []
        assert violations("Repeat this request with the same key.")

    def test_a_machine_name_the_reader_must_type_is_allowed_in_backticks(self) -> None:
        assert violations("Add a mapping from `phone_number` to your form's name.") == []
        assert violations("Add a mapping from phone_number to your form's name.")

    def test_the_machine_identifiers_of_the_ladder_are_not_read(self) -> None:
        """`code` and `kind` are switched on by the console and must stay machine-spelled;
        a guard that read them would demand they be prose."""
        source = (
            'X = ProblemError(kind="validation", code="validation_failed", detail="Check this.")\n'
        )
        assert [message.key for message in messages_in(source, "apps/api/probe.py")] == ["detail"]


# ============================================================================
# the line itself
# ============================================================================


def _over_budget(budgets: dict[str, int]) -> list[str]:
    counted: dict[str, int] = {}
    for message, _ in findings():
        counted[message.file] = counted.get(message.file, 0) + 1
    return [
        f"{file}: {count} finding(s), budget {budgets.get(file, 0)}"
        for file, count in sorted(counted.items())
        if count > budgets.get(file, 0)
    ]


class TestTheTreeHoldsTheLine:
    def test_no_file_carries_more_than_its_budget(self) -> None:
        over = _over_budget(_UNSWEPT)
        assert not over, "messages written for a machine, not a person:\n" + "\n".join(
            f"  {line}\n"
            + "\n".join(
                f"      {message.file}:{message.line} [{message.key}] {message.text!r}\n"
                f"        → {'; '.join(reasons)}"
                for message, reasons in findings()
                if message.file == line.split(":")[0]
            )
            for line in over
        )

    def test_the_ladder_every_screen_renders_is_clean(self) -> None:
        """`apps/api/core/errors.py` carries no waiver and never will: it is the file the
        photographed sign-in box came from, and the one whose strings reach every screen
        that never wrote its own."""
        assert "apps/api/core/errors.py" not in _UNSWEPT
        bad = [(m.line, m.text, r) for m, r in findings() if m.file == "apps/api/core/errors.py"]
        assert not bad, bad

    def test_a_real_validation_failure_renders_in_plain_words(self) -> None:
        """End to end, without the app: the handler's own output is held to the rule it
        polices. This is the exact failure from the photograph."""
        from apps.api.core.errors import humanise_validation_errors, validation_summary
        from pydantic import BaseModel, Field, ValidationError

        class SignIn(BaseModel):
            password: str = Field(min_length=12)

        try:
            SignIn.model_validate({"password": "short"})
        except ValidationError as exc:
            entries = humanise_validation_errors(exc.errors(), drop_source=False)
        assert entries[0]["message"] == "Password needs to be at least 12 characters."
        assert entries[0]["label"] == "Password"
        assert entries[0]["field"] == "password", "the console still needs the input's name"
        for entry in entries:
            assert violations(entry["message"]) == [], entry
        assert violations(validation_summary(entries)) == []
