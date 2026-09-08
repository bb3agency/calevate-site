"""Guardrail: every table holding a data principal's data is reached by an erasure arm.

**WHY THIS EXISTS AT ALL.** Every comparable obligation in this repository is structurally
enumerated — tenant isolation by `check_rls_coverage` (against `pg_class`/`pg_policy`,
both directions), append-only ledgers by `check_ledger_immutability`, operator alarms by
`check_alarm_wiring`, response length by `check_list_bounds`. The DPDP §12 erasure — the
legally most expensive of them, because its output is a CERTIFICATE we hand to a data
principal — was enforced by reading. Twice that failed, months apart, and the code records
both: `handoff_attempts` ("nothing else named this table: not `execute_deletion_request`,
not `deletion_proof`, not the tenant-erasure register, and not one `retention_policies`
category, so the row survived BOTH clocks") and `outbox_messages` ("every tenant-scoped arm
of both erasures was structurally blind to it"). Each was found by a person, late.

The failure it permits is silent and expensive: a new table lands holding a caller's words
or number, ships WITH its RLS policy and its list bound because those gates exist, is
reached by no erasure arm — and a §12 certificate is then issued that is FALSE while
nothing turns red.

**THE RULE.** Every live table carrying a SUBJECT-LINKED column either appears in the SQL
of an erasure arm, or is listed in `ERASURE_EXEMPT` with a reason a reviewer can weigh.
Both directions, on `check_rls_coverage`'s terms: a table with no arm fails, and an
exemption naming a table that no longer exists fails too.

**THE THREE SHAPES**, taken from `check_rls_coverage`'s rule 7 rather than invented beside
it — that file already had to answer "which tables hold a person's data" and its answers
are imported here where they are the same question:

1. **A SUBJECT HANDLE.** A column naming the data principal directly: any `*e164*` column,
   `phone`, or one of our one-way `*subject_ref*` handles. This is what the erasure is
   KEYED on, so a table carrying one is a table the erasure was supposed to find.
2. **A LINK TO A CALL OR A LEAD.** A foreign key to `calls` or `leads` — the two rows the
   subject erasure enumerates first. A child of either is that person's data at one remove,
   and the `ON DELETE CASCADE` never fires because a DPDP erasure EMPTIES a call rather
   than deleting it (`_erase_handoff_briefs` had to be written to say exactly this).
3. **A FREE-TEXT OR JSONB PAYLOAD.** The caller's own words, or a body holding them.
   `_INLINE_PAYLOAD_COLUMNS` is imported from `check_rls_coverage` verbatim — the same two
   jsonb columns it added rule 7c for — and widened here with the text columns this repo
   actually stores prose in, because `handoff_attempts.reason` and
   `knowledge_gap_occurrences.question_redacted` are the exact shape that got missed.

Column names are ENUMERATED rather than pattern-matched, for `check_rls_coverage`'s own
reason: the property that matters is "this column holds a person's data", which is a
judgement about a column and not a spelling. `name` is deliberately NOT in the list — it is
the label of an agent, a campaign or a saved view far more often than it is a caller's, and
a rule producing twenty entries nobody would ever ask about is a register nobody reads,
which is the failure mode the register exists to avoid.

**WHAT COUNTS AS COVERED, AND WHY IT IS A CALL GRAPH RATHER THAN A GREP.** `retention.py`
holds BOTH clocks — the retention sweep and the erasure — and a table swept by retention
but unreachable by erasure is precisely the defect `handoff_attempts` was ("survived BOTH
clocks" is one sentence about two different failures). So coverage is computed from the SQL
reachable FROM THE ERASURE ENTRYPOINTS: each entrypoint's body, the module-level SQL
constants it names, and the helpers it calls, followed across the erasure modules. A table
named only in a comment or only in a sweep arm is NOT covered, which is the whole point.

**AND A BLIND-SPOT ARM (`check_wiring`'s rule 5, `check_metadata_columns`' exit 2).** Three
of the questions here compare a live schema against a set extracted from source, and a
comparison whose right side is empty answers "covered" for nothing and "exempt" for
everything — or, worse, a moved file makes the scan see no SQL at all and every table
fails, which reads as noise and gets exempted away. So the extraction is checked against
anchors it must always find before any verdict is reached, and a scan that cannot see its
own subject exits 2 REFUSED rather than printing a verdict.

Run: uv run python -m scripts.check_erasure_coverage   (needs a migrated DB; owner URL)
"""

from __future__ import annotations

import ast
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Connection, Engine, create_engine, text

from scripts.check_rls_coverage import _INLINE_PAYLOAD_COLUMNS

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

#: An exemption is an argument, not a checkbox — `check_rls_coverage`'s constant and its
#: reasoning, kept at the same number so the two registers cannot drift into different
#: standards of proof.
MIN_EXEMPTION_REASON = 40

# ── shape 1: a column naming the data principal ────────────────────────────────────────
#: Enumerated for `check_rls_coverage`'s reason. `email` is deliberately absent: every
#: email column in this schema (`users`, `admin_users`, `invitations`) belongs to the
#: CLIENT'S OWN STAFF or to ours — a different data principal on a different lawful basis,
#: whose data ends with the ENGAGEMENT and not with one caller's §12 request. That is the
#: same distinction `_erase_handoff_briefs` makes about `destination_e164`.
_SUBJECT_HANDLE_COLUMNS = ("phone", "subject_ref", "erased_subject_ref", "caller_ref")

_SUBJECT_HANDLE_SQL = text(
    "SELECT DISTINCT c.relname FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "JOIN pg_attribute a ON a.attrelid = c.oid "
    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
    "AND (a.attname LIKE '%%e164%%' OR a.attname = ANY(:cols)) "
    "AND a.attnum > 0 AND NOT a.attisdropped"
)

# ── shape 2: a foreign key into the two rows an erasure enumerates ─────────────────────
_SUBJECT_PARENTS = ("calls", "leads")

_SUBJECT_FK_SQL = text(
    "SELECT DISTINCT c.relname FROM pg_constraint k "
    "JOIN pg_class c ON c.oid = k.conrelid "
    "JOIN pg_class f ON f.oid = k.confrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE k.contype = 'f' AND n.nspname = 'public' AND f.relname = ANY(:parents)"
)

# ── shape 3: the caller's own words, or a body holding them ────────────────────────────
#: Text columns this repo stores PROSE in. `handoff_attempts.reason`/`summary` and
#: `knowledge_gap_occurrences.question_redacted` are why the list is not shorter: both are
#: a model's or a caller's sentences, both survived redaction intact ("redaction removes
#: IDENTIFIERS from a sentence and leaves the SENTENCE"), and one of them is a table that
#: no erasure arm reached for months.
_FREE_TEXT_COLUMNS = (
    "content",
    "text",
    "text_redacted",
    "summary",
    "question_redacted",
    "note",
    "notes",
    "reason",
    "body",
    "transcript",
)
#: jsonb bodies. `_INLINE_PAYLOAD_COLUMNS` is `check_rls_coverage`'s own pair, imported so
#: a column added there is a column asked about here. `data` and `moments` are this file's
#: addition: `call_extractions.data` is "the caller's name, their callback number and every
#: schema field the model captured", which is the densest personal-data column in the
#: schema and is not a `payload`.
_PAYLOAD_COLUMNS = (*_INLINE_PAYLOAD_COLUMNS, "data", "moments")

_PROSE_TABLE_SQL = text(
    "SELECT DISTINCT c.relname FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "JOIN pg_attribute a ON a.attrelid = c.oid "
    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND a.attnum > 0 "
    "AND NOT a.attisdropped AND ("
    "  (a.attname = ANY(:text_cols) AND a.atttypid IN ('text'::regtype, 'varchar'::regtype))"
    "  OR (a.attname = ANY(:json_cols) AND a.atttypid = 'jsonb'::regtype))"
)

_ALL_TABLE_SQL = text(
    "SELECT c.relname FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')"
)

# ── the erasure surface, as source ─────────────────────────────────────────────────────
#: The modules that hold erasure SQL. Enumerated rather than globbed because the question
#: is "which code is an erasure", and that is a judgement: `workers/retention.py` holds the
#: erasure AND the retention sweep, and only one of them discharges a §12 request.
ERASURE_SOURCES: tuple[Path, ...] = (
    REPO_ROOT / "apps" / "workers" / "retention.py",
    REPO_ROOT / "apps" / "api" / "compliance" / "tenant_erasure.py",
    REPO_ROOT / "apps" / "api" / "compliance" / "deletion.py",
    REPO_ROOT / "apps" / "api" / "retrieval" / "caller_erasure.py",
    REPO_ROOT / "apps" / "api" / "insights" / "service.py",
)

#: Where an erasure BEGINS. The walk starts here and follows calls, so the retention
#: sweep's own arms — which live in the same file and reach many of the same tables — are
#: not mistaken for erasure coverage.
ERASURE_ENTRYPOINTS: tuple[str, ...] = (
    "execute_deletion_request",
    "execute_tenant_erasure",
)

#: Tables the walk must find before this file is entitled to a verdict. If it stops seeing
#: these, the scan is broken (a moved file, a renamed entrypoint, a refactor into a class)
#: and every answer it gives is worthless — `check_wiring`'s `blind_spots()` exactly.
COVERAGE_ANCHORS = frozenset(
    {
        "calls",
        "leads",
        "transcript_turns",
        "call_extractions",
        "campaign_contacts",
        "copilot_memories",
        "outbox_messages",
        "handoff_attempts",
    }
)

#: `FROM x`, `UPDATE x`, `DELETE FROM x`, `INTO x`, `JOIN x` — every way a table's name
#: appears in the SQL this repo writes. Deliberately generous: a table MENTIONED anywhere
#: in an erasure statement is one the author had in mind, and the cost of counting a JOIN
#: as coverage is far below the cost of a false gap that trains people to exempt.
_TABLE_IN_SQL = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO)\s+(?:ONLY\s+)?\"?([a-z_][a-z0-9_]*)\"?", re.IGNORECASE
)
#: Words that follow those keywords and are not tables.
_SQL_NOISE = frozenset({"select", "values", "set", "only", "lateral", "where", "as"})


# ── what is deliberately outside an erasure, and why ───────────────────────────────────
#
# `RLS_EXEMPT_TENANT_COLUMNS`' contract, one obligation along: this dict is the ONE place a
# reviewer learns what an erasure does not reach and on what argument. Every entry has to
# survive the question a regulator asks — "you certified this person was erased; what is
# in that table?" — and several of these entries are also published to the data principal
# in `compliance/deletion.ERASURE_LIMITATIONS`, which is where the client-facing wording
# of the same fact lives.
ERASURE_EXEMPT: dict[str, str] = {
    # ── append-only ledgers (hard rule 4) ───────────────────────────────────────────────
    "consent_ledger": (
        "Append-only proof that a call was permitted, carrying the caller's number by "
        "design. Erasing it would destroy the evidence that the contact was lawful rather "
        "than reduce what is known about the person — and hard rule 4 forbids the DELETE "
        "in any case. Published to the data principal: ERASURE_LIMITATIONS 'consent "
        "records', ERASURE_EXCEPTIONS keyword 'consent'."
    ),
    "usage_events": (
        "Append-only ledger of minutes and money, linked to a call and carrying no "
        "personal data of its own. Deleting a row would silently rewrite a closed billing "
        "period (hard rules 4 and 7). Published: ERASURE_LIMITATIONS 'billing records'."
    ),
    "whatsapp_alert_optin_ledger": (
        "Append-only record of a CLIENT STAFF member consenting to receive hot-lead "
        "alerts on their own mobile. A different data principal on a different lawful "
        "basis: the number is the client's employee's, not the caller's, and it ends with "
        "the engagement rather than with one caller's §12 request."
    ),
    # ── the client's own people, not the caller ────────────────────────────────────────
    "users": (
        "The client's own staff accounts — their email and their mobile, held to log them "
        "in and to reach them. `_erase_handoff_briefs`' distinction exactly: a different "
        "data principal, whose data the tenant erasure ends (`memberships` in the "
        "tenant-erasure register) and whose own §12 request would be a different request."
    ),
    "agent_handoff_members": (
        "The client's staff rota for warm transfers: a label, a note and the member's own "
        "mobile. `_erase_handoff_briefs` states the position on this exact number — "
        "clearing it would delete the client's record of who takes their calls while "
        "removing nothing of the caller's. Staff numbers end with the ENGAGEMENT."
    ),
    "admin_copilot_conversation_turns": (
        "What a CALEVATE OPERATOR typed to the admin console assistant, redacted on write. "
        "It is platform-scoped (no tenant_id, RLS-exempt for that reason) and holds our "
        "own staff's words about the platform, not a caller's; it expires on the operator's "
        "own session-run clock."
    ),
    "admin_copilot_memories": (
        "The admin console assistant's distilled notes, platform-scoped and redacted on "
        "write for the same reason as the turns above. Our operators' words about the "
        "platform, on their own expiry clock, and never a caller's record."
    ),
    # ── phone numbers that are not a caller's ──────────────────────────────────────────
    "phone_numbers": (
        "The DIDs the client rents and answers on — the number that RANG, not the number "
        "that rang it. It is the business's own telephone number, held to route calls and "
        "to bill the rental, and it survives every caller's erasure by definition."
    ),
    "dnc_list": (
        "Suppression, and erasing it would make the person CALLABLE again — the opposite "
        "of what the entry is for. It records a number and a scope and nothing else about "
        "the person. Published to the data principal: ERASURE_LIMITATIONS 'do-not-call', "
        "ERASURE_EXCEPTIONS keyword 'do-not-call'."
    ),
    # ── the erasure's own machinery ────────────────────────────────────────────────────
    "processor_erasure_tasks": (
        "The obligation this erasure could NOT discharge, recorded rather than implied "
        "(D-433): a vendor id to quote in a written deletion request, and a `subject_ref` "
        "that is already the one-way handle. Erasing it would delete the only record that "
        "a sub-processor still holds a copy — the opposite of the duty."
    ),
    "retention_worklist": (
        "Platform sweep bookkeeping: three columns — a tenant id, the `reason` that tenant "
        "was registered as sweepable (an authored string of ours), and when. No caller's "
        "data of any kind, and it is what makes the other clock run."
    ),
    # ── operator and client prose that is not about a caller ───────────────────────────
    "credit_ledger": (
        "Append-only money (hard rules 4 and 7). Its `reason` is an authored code or an "
        "operator's note about a top-up or an adjustment — the client's commercial record, "
        "with no caller named in it."
    ),
    "platform_settings": (
        "Platform configuration, one row for the whole deployment. Its `note` is an "
        "operator's note about a setting; no tenant's data and no caller's."
    ),
    "platform_list_rate_cancellations": (
        "Platform pricing state: which rate card was withdrawn before it took effect, "
        "which operator withdrew it and their stated `reason`. A card is deployment-wide "
        "and prices no one client, so no data principal is named here even indirectly — "
        "and it is append-only (hard rule 4) because a withdrawal that could itself be "
        "un-recorded would spring the cancelled card back into force on every reader at "
        "once. RLS-exempt on the same ground."
    ),
    "platform_maintenance_windows": (
        "Platform state: a window and the operator's `reason` for it. Deployment-wide, "
        "never about a person, and RLS-exempt for the same reason."
    ),
    "tenant_feature_flags": (
        "Configuration rows: a flag, a tenant and the operator's `reason` for setting it. "
        "The client's account configuration rather than any caller's record."
    ),
    "prompt_versions": (
        "The agent's own SCRIPT — the prompt body and our notes on it, authored by the "
        "client or by us. It is what the agent SAYS, not what any caller said; a caller's "
        "words never reach it."
    ),
    "dlt_templates": (
        "Registered DLT template bodies. Regulator-approved message text with variable "
        "placeholders, authored by the client and registered with the DLT platform — no "
        "caller's data, and the registration is a compliance artefact we cannot alter."
    ),
    "idempotency_records": (
        "Replay protection: a key and a stored `response_payload` so a retried request "
        "returns the same answer. Platform-scoped, already RLS-exempt for that reason, and "
        "scrubbed on its own short reliability clock (`prune_reliability_tables`) rather "
        "than per subject — a subject predicate over a hashed replay key does not exist."
    ),
    "qa_reports": (
        "The stored monthly QA report. Its `data` is a `calevate_shared.QaReport`, "
        "computed by `scripts/qa_report` from the GOLDEN-TRANSCRIPT FIXTURES rather than "
        "from any tenant's calls, and the model is built so there is nothing to mask: "
        "scenario class labels (ours), extraction field labels (the client's own column "
        "names) and counts, asserted against every fixture by "
        "tests/eval_qa_report_test.py. No caller is in it to erase."
    ),
    "lead_events": (
        "The lead TIMELINE, and this entry rests on an audit rather than on a schema "
        "property, which is why it is written out. `crm/service.py`'s payload audit reads "
        "all six producers in three deployables: every one writes our own ids, our own "
        "enum values and authored snake_case codes — never a phone number, transcript text "
        "or an extraction payload — and the read path whitelists KEYS and re-checks VALUES "
        "against `_AUTHORED_CODE` so a seventh producer writing prose degrades to 'no "
        "detail' instead of to a leak. A producer that writes a caller's words to this "
        "column breaks that audit, and this entry with it."
    ),
    "kb_retrieval_logs": (
        "⚠ THE ONE ENTRY HERE THAT IS TRUE ABOUT THE ROWS AND NOT ABOUT THE COLUMN, so "
        "it is written out at length. `kb_retrieval_logs.query` is `NOT NULL` text and its "
        "own model says it would hold RAW CALLER UTTERANCES — a table an erasure would "
        "have to reach the day it holds anything. It holds nothing: nothing writes it and "
        "nothing can yet, because in-call retrieval happens inside the engine (D-33) and "
        "neither surface the engine gives us reports a retrieval outcome (pilot gate 8). "
        "That model note is dated and argued at `apps/api/kb/models.py::KbRetrievalLog`, "
        "and it is ENFORCED rather than believed: "
        "`tests/kb_tiers_test.py::test_the_knowledge_gap_report_has_no_producer_and_cannot"
        "_yet` fails the day ANY file under `apps/` names this table, which is the day a "
        "producer lands and the day this entry must be replaced by an erasure arm on both "
        "paths. That test is why this exemption cannot expire silently, and it is the only "
        "reason an exemption of this shape is acceptable at all."
    ),
    "call_engine_latency": (
        "The engine's own per-turn timings for one call — milliseconds and a component "
        "name, nothing else. Numbers about a conversation are not a record of the person "
        "who had it, and the call row itself is erased."
    ),
    "call_variant_assignments": (
        "Which prompt variant a call was assigned, for the experiment arm. A call id and a "
        "variant id; no words, no number, and the call is erased through `calls`."
    ),
    "qa_call_samples": (
        "The SAMPLING decision: which calls a reviewer was asked to score, and the score. "
        "It holds ids and rubric outcomes, not transcript text — and the sampler already "
        "skips an erased tenant. The sampled call's own words go with `calls`."
    ),
}


@dataclass(frozen=True)
class SchemaState:
    """Everything the evaluation needs, so the evaluation is pure and testable."""

    subject_handle_tables: frozenset[str] = frozenset()
    subject_linked_tables: frozenset[str] = frozenset()
    prose_tables: frozenset[str] = frozenset()
    all_tables: frozenset[str] = frozenset()

    @property
    def in_scope(self) -> frozenset[str]:
        return self.subject_handle_tables | self.subject_linked_tables | self.prose_tables

    def shapes_of(self, table: str) -> str:
        shapes = [
            label
            for label, tables in (
                ("subject handle", self.subject_handle_tables),
                ("link to a call/lead", self.subject_linked_tables),
                ("free-text or jsonb payload", self.prose_tables),
            )
            if table in tables
        ]
        return ", ".join(shapes)


@dataclass
class ErasureReach:
    """The tables the erasure entrypoints can actually reach, and how it was worked out."""

    tables: frozenset[str] = frozenset()
    visited: frozenset[str] = frozenset()
    statements: int = 0
    blind_spots: list[str] = field(default_factory=list)


def fetch_state(engine: Engine) -> SchemaState:
    with engine.connect() as conn:
        return read_state(conn)


def read_state(conn: Connection) -> SchemaState:
    """The four catalog reads, on a caller's connection.

    Split out from `fetch_state` so a test can create a doctored table inside a
    transaction, ask this the question, and roll back — proving the LIVE arm sees a new
    un-erased table without leaving one in a database four other lanes are using.
    """
    handles = {
        r[0] for r in conn.execute(_SUBJECT_HANDLE_SQL, {"cols": list(_SUBJECT_HANDLE_COLUMNS)})
    }
    linked = {r[0] for r in conn.execute(_SUBJECT_FK_SQL, {"parents": list(_SUBJECT_PARENTS)})}
    prose = {
        r[0]
        for r in conn.execute(
            _PROSE_TABLE_SQL,
            {"text_cols": list(_FREE_TEXT_COLUMNS), "json_cols": list(_PAYLOAD_COLUMNS)},
        )
    }
    every = {r[0] for r in conn.execute(_ALL_TABLE_SQL)}
    return SchemaState(
        subject_handle_tables=frozenset(handles),
        subject_linked_tables=frozenset(linked),
        prose_tables=frozenset(prose),
        all_tables=frozenset(every),
    )


def _literal_of(node: ast.AST) -> str | None:
    """The literal text of a string node, f-strings included.

    F-STRINGS ARE NOT OPTIONAL HERE. Half the SQL in this tree is built with one —
    `_TRANSCRIPT_DELETE_SQL` interpolates the shared `_CLOCK` expression,
    `_SCRUB_CHUNKS_SQL` interpolates the forgotten-marker constant — and an f-string
    is an `ast.JoinedStr`, not an `ast.Constant`. Reading only constants silently missed
    `caller_chunks`, a table the erasure demonstrably DOES scrub: the guard's first run
    reported it as an uncovered gap. Interpolations become a SPACE rather than being
    elided, so `FROM {table}` cannot fuse into a table name that never existed.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return " ".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return None


def _tables_in(sql: str) -> set[str]:
    return {
        match.group(1).lower()
        for match in _TABLE_IN_SQL.finditer(sql)
        if match.group(1).lower() not in _SQL_NOISE
    }


def _module_strings_and_functions(
    path: Path,
) -> tuple[dict[str, str], dict[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Module-level string constants, and every function defined in the module.

    Docstrings are excluded from the string harvest by construction: only ASSIGNMENTS are
    read, and a docstring is an expression statement. That matters more than it looks —
    `retention.py`'s prose names half the schema, and a scan that read it would report
    coverage the code does not have, which is the one failure mode a guard must not have.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants: dict[str, str] = {}
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            literal = _literal_of(node.value)
            if literal is not None:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = literal
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            literal = _literal_of(node.value)
            if literal is not None and isinstance(node.target, ast.Name):
                constants[node.target.id] = literal
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions[node.name] = node
    return constants, functions


def _executable_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Every node of a function EXCEPT its own docstring.

    The exclusion is the load-bearing half. `retention.py`'s prose names half the schema
    and quotes SQL while explaining it — `_erase_handoff_briefs`' docstring alone talks
    about `agent_handoff_members` — so a scan that read docstrings would report coverage
    the code does not have. A guard that manufactures its own green is worse than none.
    """
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return [node for statement in body for node in ast.walk(statement)]


def erasure_reach(sources: tuple[Path, ...] = ERASURE_SOURCES) -> ErasureReach:
    """Every table named in SQL reachable from an erasure entrypoint.

    A bounded call graph rather than a grep, for the reason in the module docstring: this
    file's subject lives beside the RETENTION SWEEP, whose arms reach many of the same
    tables on a completely different clock, and counting those as erasure coverage would
    have re-passed `handoff_attempts` — the table whose comment says it "survived BOTH
    clocks". Resolution is by plain function NAME across the scanned modules, which is
    enough here (these five files define no duplicate names) and is checked by the anchors:
    a resolution that silently stopped working stops finding them.
    """
    blind: list[str] = []
    constants: dict[str, str] = {}
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for path in sources:
        if not path.exists():
            blind.append(f"erasure source {path.relative_to(REPO_ROOT)} does not exist")
            continue
        module_constants, module_functions = _module_strings_and_functions(path)
        constants.update(module_constants)
        functions.update(module_functions)

    tables: set[str] = set()
    visited: set[str] = set()
    statements = 0
    queue = list(ERASURE_ENTRYPOINTS)
    for name in ERASURE_ENTRYPOINTS:
        if name not in functions:
            blind.append(f"erasure entrypoint `{name}` is defined in none of the scanned sources")

    while queue:
        name = queue.pop()
        if name in visited or name not in functions:
            continue
        visited.add(name)
        for node in _executable_nodes(functions[name]):
            literal = _literal_of(node)
            if literal is not None:
                found = _tables_in(literal)
                if found:
                    statements += 1
                tables |= found
            elif isinstance(node, ast.Name) and node.id in constants:
                found = _tables_in(constants[node.id])
                if found:
                    statements += 1
                tables |= found
            elif isinstance(node, ast.Call):
                target = node.func
                callee = (
                    target.id
                    if isinstance(target, ast.Name)
                    else target.attr
                    if isinstance(target, ast.Attribute)
                    else None
                )
                if callee is not None and callee in functions:
                    queue.append(callee)
    return ErasureReach(
        tables=frozenset(tables),
        visited=frozenset(visited),
        statements=statements,
        blind_spots=blind,
    )


def evaluate(
    state: SchemaState,
    reach: ErasureReach,
    *,
    exemptions: dict[str, str] | None = None,
) -> list[str]:
    """Every failure the live schema deserves. Pure — tests feed it synthetic states."""
    exempt = dict(ERASURE_EXEMPT if exemptions is None else exemptions)
    failures: list[str] = []

    # 1. Every in-scope table is reached by an erasure arm, or exempt with a reason.
    for table in sorted(state.in_scope):
        if table in exempt or table in reach.tables:
            continue
        failures.append(
            f"{table}: holds a data principal's data ({state.shapes_of(table)}) and is "
            "named by NO erasure arm. A §12 certificate issued while this table still "
            "holds the subject's record is false. Erase it, or register it in "
            "ERASURE_EXEMPT with why it is correct that the data survives."
        )

    # 2. The register stays honest, both directions — `check_rls_coverage`'s rule 4. A dead
    #    exemption is worse than no exemption: it reads as a considered decision about a
    #    table, and it hides the next real gap behind a name nobody rechecks.
    for table, reason in sorted(exempt.items()):
        if table not in state.all_tables:
            failures.append(
                f"{table}: STALE erasure exemption — no such table. Remove the entry; a "
                "dead exemption hides the next real gap."
            )
        elif table not in state.in_scope:
            failures.append(
                f"{table}: erasure exemption for a table that carries no subject-linked "
                "column, so nothing here would have asked about it. Remove the entry — a "
                "register that answers questions nobody asked is one nobody reads."
            )
        if table in reach.tables:
            failures.append(
                f"{table}: listed as ERASURE_EXEMPT and also reached by an erasure arm. "
                "One of the two is wrong, and a reviewer cannot tell which."
            )
        if len(reason.strip()) < MIN_EXEMPTION_REASON:
            failures.append(
                f"{table}: erasure exemption reason is too thin to review "
                f"({reason.strip()!r}). State whose data it is and why erasing it would "
                "be wrong or impossible."
            )
    return failures


def main() -> int:
    reach = erasure_reach()
    # THE BLIND-SPOT ARM RUNS FIRST, and it exits 2 rather than 1 (`check_metadata_columns`'
    # convention): "I could not see my subject" is a different answer from "I looked and
    # this is wrong", and a guard that cannot tell them apart is one whose green means
    # nothing. An empty or truncated scan would otherwise report every table as uncovered,
    # which reads as noise and gets exempted away.
    missing_anchors = sorted(COVERAGE_ANCHORS - reach.tables)
    if reach.blind_spots or missing_anchors:
        print("ERASURE COVERAGE: REFUSED TO SCORE")
        for blind in reach.blind_spots:
            print(f"  - {blind}")
        if missing_anchors:
            print(
                f"  - the erasure walk found {len(reach.tables)} table(s) and none of "
                f"{missing_anchors}. Those tables are erased by code this file can no "
                "longer see, so every verdict below would be about the scan and not "
                "about the tree."
            )
        return 2

    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    engine = create_engine(url.replace("+asyncpg", "+psycopg"))
    try:
        state = fetch_state(engine)
    finally:
        engine.dispose()

    failures = evaluate(state, reach)
    if failures:
        print("ERASURE COVERAGE: FAIL")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(
        f"ERASURE COVERAGE: OK ({len(state.in_scope)} subject-linked tables; "
        f"{len(state.in_scope & reach.tables)} reached by an erasure arm "
        f"({reach.statements} statements across {len(reach.visited)} functions); "
        f"{len(ERASURE_EXEMPT)} registered with a reason)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
