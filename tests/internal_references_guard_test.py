"""Problem messages speak to the reader, not about our internals.

`plain_language_guard_test.py` keeps machine vocabulary (type names, validator text,
snake_case) out of the problem+json strings a screen renders. This guard reads the same
strings — `title`, `detail`, `remediation` and the wording mappings, found by that file's
`rendered_messages` — for a second class of leak: references a reader has no use for.

- Every message, operator-facing included: no hard rule number, decision id, design doc or
  section mark. Those are code-review artefacts and belong in a comment.
- Messages a CLIENT can reach (everything outside the operator modules below): also no
  data-model words (tenant, RLS, enum, schema, migration), no stack words (the API,
  endpoint, payload, webhook) and no voice or telephony vendor.

The web console's half is `apps/web/tests/internalReferencesGuard.test.ts`.

`ALLOWED` names the files where one banned word is the reader's own subject — a client
wiring a webhook — with the reason. `ROUTED` holds the counts in files owned by another
lane while their owner rewrites them; each count may fall and never rise.
"""

from __future__ import annotations

import ast
import re

from tests.plain_language_guard_test import (
    REPO_ROOT,
    SCAN_ROOTS,
    Message,
    _literal,
    rendered_messages,
)

#: Code-review artefacts. Banned for every reader, staff included.
ARTEFACT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a hard rule", re.compile(r"\bhard rules?\b", re.I)),
    ("a decision id", re.compile(r"\bD-\d{2,4}\b")),
    ("a section mark", re.compile(r"§")),
    (
        "a design doc",
        re.compile(r"\b(?:DATA-MODEL|TRD|BRD|FLOWS|OPERATIONS|SECURITY-COMPLIANCE|ROADMAP)\b"),
    ),
)

#: What a client has no use for, on top of the artefacts.
CLIENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    *ARTEFACT_RULES,
    ("our data model", re.compile(r"\b(?:tenants?|RLS|enums?|schemas?|migrations?)\b", re.I)),
    (
        "our stack",
        re.compile(r"\bthe API\b(?! key)|\bendpoints?\b|\bpayloads?\b|\bwebhooks?\b", re.I),
    ),
    (
        "a vendor",
        re.compile(
            r"\b(?:sarvam|cartesia|bulbul|saaras|sonic|gnani|timbre|vobiz|plivo|pipecat"
            r"|thinnest(?:ai)?|bolna|exotel)\b",
            re.I,
        ),
    ),
)

#: Modules whose messages reach operators, engines or jobs and never a client. They are
#: held to the artefact rules only.
NOT_CLIENT_FACING: tuple[str, ...] = (
    "apps/api/admin/",
    "apps/api/ops/",
    "apps/api/engine/",
    # Switching Studio voices on is an operator act (ops/hosted_voice_routes.py).
    "apps/api/agents/studio_voices.py",
    # Deployment settings an operator sets; the remediation names the variable.
    "apps/api/reliability/engine_actions.py",
    "apps/api/reliability/engine_webhooks.py",
    "apps/api/compliance/kyc_admin_routes.py",
    "apps/api/copilot/admin_",
    "apps/voice-runtime/",
    "apps/workers/",
)

#: `(file prefix, word pattern, reason)`: one word, in one place, where it is the
#: reader's own subject.
ALLOWED: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "apps/api/integrations/",
        re.compile(r"^(?:webhooks?|endpoints?|payloads?)$", re.I),
        "the client configures webhook deliveries to their own endpoint here",
    ),
    (
        "apps/api/ingest/",
        re.compile(r"^(?:webhooks?|endpoints?|payloads?)$", re.I),
        "a lead source is the client's own form posting to a webhook we give them",
    ),
    (
        "apps/api/actions/",
        re.compile(r"^(?:webhooks?|endpoints?|payloads?)$", re.I),
        "an agent action calls the client's own endpoint, which they configure here",
    ),
    (
        "apps/api/compliance/kyc_routes.py",
        re.compile(r"^endpoints?$", re.I),
        "the verification provider's callback route answers its not-found here; the "
        "reader is the provider, not a client",
    ),
)

#: Files owned by another lane at the time of this sweep; reported for routing.
ROUTED: dict[str, int] = {}


def _client_facing(file: str) -> bool:
    return not file.startswith(NOT_CLIENT_FACING)


#: A route path such as `/v1/admin/tenants/{}/credits`: an address the reader types, not
#: a word in the sentence.
_PATH = re.compile(r"/v1/\S+")


def offences(message: Message) -> list[str]:
    rules = CLIENT_RULES if _client_facing(message.file) else ARTEFACT_RULES
    text = _PATH.sub("", message.text)
    found = []
    for name, rule in rules:
        match = rule.search(text)
        if match is None:
            continue
        if any(
            message.file.startswith(prefix) and word.match(match.group(0))
            for prefix, word, _ in ALLOWED
        ):
            continue
        found.append(f"{name}: {match.group(0)!r}")
    return found


def _is_problem_constructor(call: ast.Call) -> bool:
    """`ProblemError.<kind>(...)`. A `ValueError("...")` is an invariant for the next
    developer and never reaches a screen as written, so positional text is read only here.
    """
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "ProblemError"
    )


def _positional_messages() -> list[Message]:
    """Sentences passed POSITIONALLY to a problem constructor.

    `ProblemError.business_rule("code", "What happened.")` carries its detail as an
    argument, which `rendered_messages` (keywords and mappings) does not read. A literal
    with a space in it is a sentence; the code beside it has none.
    """
    found: list[Message] = []
    for scan_root in SCAN_ROOTS:
        for path in sorted((REPO_ROOT / scan_root).rglob("*.py")):
            relative = path.relative_to(REPO_ROOT).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _is_problem_constructor(node):
                    for arg in node.args:
                        text = _literal(arg)
                        if text and " " in text.strip():
                            found.append(Message(relative, node.lineno, "detail", text))
    return found


def _findings() -> list[tuple[Message, list[str]]]:
    messages = [*rendered_messages(), *_positional_messages()]
    return [(m, bad) for m in messages if (bad := offences(m))]


def _over_budget() -> list[str]:
    by_file: dict[str, list[tuple[Message, list[str]]]] = {}
    for message, bad in _findings():
        by_file.setdefault(message.file, []).append((message, bad))
    return [
        f"{m.file}:{m.line} [{m.key}] {m.text!r} -> {'; '.join(bad)}"
        for file, found in sorted(by_file.items())
        if len(found) > ROUTED.get(file, 0)
        for m, bad in found
    ]


def test_it_catches_the_sentences_it_exists_for() -> None:
    client = Message("apps/api/agents/probe.py", 1, "detail", "")
    for text in (
        "The API stores the others (DATA-MODEL §3).",
        "It is never turned into a number here (hard rule 7).",
        "Superseded by D-679.",
        "This tenant has no plan.",
        "The ThinnestAI workspace refused it.",
    ):
        assert offences(Message(client.file, 1, "detail", text)), text
    assert offences(Message(client.file, 1, "detail", "Your calls keep going.")) == []


def test_operator_messages_may_be_technical_but_cite_no_artefact() -> None:
    operator = "apps/api/ops/probe.py"
    assert offences(Message(operator, 1, "detail", "The tenant's webhook payload")) == []
    assert offences(Message(operator, 1, "detail", "Refused under D-692."))


def test_allowed_words_stay_in_their_place() -> None:
    assert (
        offences(Message("apps/api/integrations/x.py", 1, "detail", "Your webhook failed.")) == []
    )
    assert offences(Message("apps/api/agents/x.py", 1, "detail", "Your webhook failed."))


def test_every_routed_and_allowed_file_exists() -> None:
    for file in ROUTED:
        assert (REPO_ROOT / file).is_file(), file
    for prefix, _, _ in ALLOWED:
        assert (REPO_ROOT / prefix).exists(), prefix


def test_no_message_cites_our_internals() -> None:
    over = _over_budget()
    assert not over, (
        "problem messages that point the reader at our internals. Say what happened and "
        "what to do in the reader's words; keep rules, decisions and docs in a comment:\n"
        + "\n".join(f"  {line}" for line in over)
    )
