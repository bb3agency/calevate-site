"""Guardrail: every alarm this platform can raise is documented, and every alarm the
documents promise is raised. Both directions, derived from the tree rather than listed.

WHY THIS FILE EXISTS. `docs/OPERATIONS.md` §4 has promised "complaint-spike on campaign;
engine 5xx spike; cert/domain expiry" since the section was written, and for as long as it
said so **nothing anywhere raised any of the three**. That is worse than having no alarm:
an operator reads the runbook, believes they will be told, and stops looking. The 18 Aug
deep-dive register lists it as still open, which is the second time a human had to notice
it by reading.

The mirror-image defect was larger and nobody had noticed it at all: at the time this
guard was written, **44 of the 65 alarm codes this tree can raise appeared in no document
anywhere**. `retention_below_trai_floor` on a phone at 3am, with nothing to look it up in,
is a page that costs an operator the length of a code search before they can even start.

Both are the same defect — a promise and a capability drifting apart — so both are one
check, and neither may be answered by a list somebody maintains. What IS maintained is the
alarm index in `runbooks/alarm-index.md`, which is the DOCUMENT an operator reads; this
guard's job is to keep it true in both directions.

═══════════════════════════════════════════════════════════════════════════════
WHAT COUNTS AS "RAISED" — five shapes, because `alert()` is called five ways
═══════════════════════════════════════════════════════════════════════════════
1. **A literal code**: `alert("WORKER_STALL", "outbound_pool_empty")`. The common case.
2. **An f-string code**: `f"unhandled_exception:{type(exc).__name__}"`. The literal PREFIX
   is the alarm; the suffix is the variable an operator reads afterwards. Resolved by
   taking the prefix, which is exactly what the alert fingerprint keys on.
3. **A `ProblemError` carrying a `failure_stage`**, which `core/errors.py`'s handler
   relays into `alert()` verbatim. This is the shape that is easiest to miss by reading —
   the alarm is a hundred lines from the `alert()` call — and it is how `engine_rejected`
   and `engine_rate_limited` reach a phone.
4. **A module CONSTANT** (`code=MIRROR_PENDING_CODE`) or a **`*_code` field on a frozen
   descriptor** (`meter.slow_code`, `meter.body_timeout_code` — the voice-runtime
   ack-budget alarms). Both are literals one hop away: the first is resolved through the
   module's own top-level string assignments, the second by collecting every `*_code=`
   keyword literal in the tree, which is how such a descriptor is built.
5. **The HOST BACKUP CHAIN**, in shell. `scripts/backup/*.sh` cannot call `alert()` — it
   runs as `postgres`, outside every Python process — so it emits the same shape and
   reaches the same inbox through `notify.sh` → `host_alert.py` (OPERATIONS §4). An
   operator cannot tell the two apart when the mail arrives, so neither can this guard.

Anything the scanner CANNOT resolve is a failure, not a shrug: `DYNAMIC_ALERT_SITES`
below names the two call sites whose code is a runtime value, the codes they can raise,
and the reason — and the guard re-verifies that each named code is still a literal in that
file, so a rename breaks the build rather than the index.

WHAT IT ALSO CHECKS, AND WHY EACH ONE IS THE SAME DEFECT ONE STEP OVER:

* **Metrics.** `core/alerting.py` says in its own docstring that metrics are NAMED DOMAIN
  RECORDERS and that "ad-hoc counters are not accepted" — and three modules were emitting
  `metrics_log.info("metric", ...)` directly, so `speed_to_lead_seconds` (FLOWS §4's
  60-second target) existed in a log line and in no vocabulary. Metric names are checked
  in both directions against the same index, and emitting one outside `_record` fails.
* **Dangling operator vocabulary.** A backticked `snake_case` name in `runbooks/**` or in
  OPERATIONS §4 that matches nothing in the code tree is an instruction to look for
  something that does not exist. This is the shape "documented but never raised" takes
  when the doc talks in prose instead of naming a code.
* **Runbook pointers resolve.** An index row may cite a runbook; a citation to a file
  that does not exist is a 3am dead end.

**IT REFUSES WHEN IT MATCHES NOTHING** (`check_wiring`'s doctrine). A scanner whose regex
stopped matching would otherwise report a clean sweep of an empty set, which is the way a
guardrail dies without anybody noticing.

Run: `uv run python -m scripts.check_alarm_wiring`   (also in `make guardrails`)
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

from apps.api.core.alarm_severity import ALARM_SEVERITY as _ALARM_SEVERITY
from apps.api.core.alarm_severity import ALARM_SEVERITY_FAMILIES as _FAMILIES
from apps.api.core.alarm_severity import SEVERITIES

REPO_ROOT = Path(__file__).resolve().parent.parent
PY_ROOTS = (REPO_ROOT / "apps", REPO_ROOT / "packages", REPO_ROOT / "scripts")
SHELL_ROOT = REPO_ROOT / "scripts" / "backup"
INDEX = REPO_ROOT / "runbooks" / "alarm-index.md"
OPERATIONS = REPO_ROOT / "docs" / "OPERATIONS.md"
RUNBOOKS = REPO_ROOT / "runbooks"
#: Where a name an operator doc uses must resolve. `tests/` is IN it — not because a test
#: defines anything, but because several runbooks legitimately tell somebody to run a
#: named test, and a guardrail that called those dangling would be teaching people to
#: stop reading it.
CODE_ROOTS = (
    REPO_ROOT / "apps",
    REPO_ROOT / "packages",
    REPO_ROOT / "scripts",
    REPO_ROOT / "alembic",
    REPO_ROOT / "infra",
    REPO_ROOT / "tests",
)

#: A fenced block in a runbook is a thing the operator RUNS, not a name they look up — so
#: a SQL alias a runbook's own query defines (`count(*) ... AS waiting_on_backoff`) and
#: then refers to in the prose beside it is resolved, per document. Precision matters
#: here more than reach: a check that cried wolf about a column alias would be muted long
#: before it caught a real dangling alarm.
_FENCED = re.compile(r"```.*?```", re.DOTALL)

#: The `alert()` sites whose code is a runtime value, the codes each can raise, and why
#: the value cannot be a literal. An EXEMPTION THAT RE-VERIFIES: every code named here
#: must still appear as a string literal in the file it is claimed for, so renaming one
#: fails this guard instead of silently emptying the index. Same contract as
#: `check_compliance_invariants`'s named engine reaches.
DYNAMIC_ALERT_SITES: dict[str, tuple[tuple[str, ...], str]] = {
    "apps/api/core/settings.py": (
        (
            "audit_chain_not_configured",
            "idempotency_not_configured",
            "copilot_proposals_not_configured",
            "impersonation_not_configured",
        ),
        "`_unusable_hmac_key` is ONE refusal shared by four HMAC key resolutions, and the "
        "code is the CALLER's — `resolve_hmac_key(code=...)` is passed a literal at each "
        "of `compliance/audit.py`, `reliability/service.py`, `copilot/write_tools.py` and "
        "`core/impersonation.py`. Folding them into one code would tell an operator that "
        "a key is unusable without saying WHICH subsystem stopped, and these four stop "
        "very different things (the tamper-proof audit chain, idempotency, copilot write "
        "proposals, view-as grants). The factory is the right shape and the four literals "
        "are re-verified below, so a rename breaks the build rather than the index.",
    ),
    "apps/api/billing/ai_quota.py": (
        ("ai_platform_brake_tripped", "ai_platform_brake_near"),
        "the two platform-AI headroom lines are walked as a tuple of "
        "(threshold, code, detail) so that the most severe one wins with a `break`; the "
        "code is the loop variable",
    ),
    "apps/workers/settings.py": (
        ("job_function_not_registered", "job_retries_exhausted"),
        "the arq terminal alerter routes arq's own two warnings into `alert()`, so the "
        "code is looked up from `ARQ_TERMINAL_MESSAGES` by the log record's unformatted "
        "template — a dict lookup by construction, because the whole point is to read "
        "arq's intent rather than a rendered string",
    ),
    "apps/api/billing/caps.py": (
        ("tenant_spend_capped", "tenant_spend_cap_approaching"),
        "the same (threshold, code, detail) tuple walk `ai_quota` uses for the platform "
        "brake, and for the same reason: the most severe line that was crossed wins with "
        "a `break`, so one large charge crossing both is one page rather than two",
    ),
    "apps/api/ingest/graph.py": (
        ("meta_page_token_invalid", "meta_leads_retrieval_denied"),
        "the alarm IS the seam's authored reason code (`RetrievedLead.reason`), passed "
        "through so that one vocabulary describes the refusal in the alert, in "
        "`webhook_inbox_events.last_error` and on the client's activity view",
    ),
    "apps/api/core/errors.py": (
        (),
        "the RELAY: `alert(exc.failure_stage, exc.code)` re-raises whatever a "
        "ProblemError declared, so its codes are not this call site's to name — they are "
        "enumerated at the ProblemError constructors by shape (3) above, which is the "
        "only place they exist as literals",
    ),
    "scripts/host_alert.py": (
        (),
        "the HOST relay: the code arrives on stdin from `scripts/backup/notify.sh`, so "
        "the vocabulary belongs to the shell chain and is enumerated by shape (5) above "
        "— naming codes here would be a second copy of that list",
    ),
}

#: Codes an operator can receive that this scanner reads out of shell rather than Python.
#: The call shapes `scripts/backup/*.sh` actually use — `alert <code>`, `fail <code>`,
#: `"$notify" <code>`, and a `"code":"..."` inside an embedded JSON line. Not a list of
#: codes: a list of the FOUR SHAPES, so a new backup alarm written the way the existing
#: ones are is picked up without anybody editing this file.
_SHELL_CALL = re.compile(r'^\s*(?:alert|fail|"\$notify")\s+([a-z][a-z0-9_]+)', re.MULTILINE)
_SHELL_JSON = re.compile(r'"code"\s*:\s*"([a-z][a-z0-9_]+)"')

#: A row of the alarm index: `| \`code\` | STAGE | meaning | what to do |`.
_INDEX_ROW = re.compile(r"^\|\s*`([a-z][a-z0-9_]*)`\s*\|", re.MULTILINE)
#: The same row, read for its SECOND column as well. Separate from `_INDEX_ROW` rather
#: than replacing it, because the two questions fail differently: a row whose stage cell
#: is malformed still declares an alarm, and swallowing it into the code scan would turn
#: a typo in column 2 into "DOCUMENTED, NEVER RAISED" in column 1 — an error message
#: pointing at the wrong half of the row.
_INDEX_ROW_STAGE = re.compile(r"^\|\s*`([a-z][a-z0-9_]*)`\s*\|\s*([A-Z][A-Z_]*)\s*\|", re.MULTILINE)
#: The same row read for its THIRD column, the severity (D-591). A third pattern rather
#: than one that captures all three, for `_INDEX_ROW_STAGE`'s stated reason: the three
#: questions fail differently, and a malformed severity cell must report itself as a
#: missing severity rather than as a missing stage or a missing row.
_INDEX_ROW_SEVERITY = re.compile(
    r"^\|\s*`([a-z][a-z0-9_]*)`\s*\|\s*[A-Z][A-Z_]*\s*\|\s*([a-z]+)\s*\|", re.MULTILINE
)
#: A row of the metric index, which uses the same shape under its own heading.
_METRIC_ROW = re.compile(r"^\|\s*`([a-z][a-z0-9_]*)`\s*\|", re.MULTILINE)
_ALARM_HEADING = "## Alarm codes"
_METRIC_HEADING = "## Metric names"

_RUNBOOK_CITATION = re.compile(r"runbooks/([a-z0-9-]+\.md)")
_BACKTICKED = re.compile(r"`([^`\n]+)`")
_SNAKE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


#: The `ErrorKind`s `core/errors.py` maps to a 5xx — and therefore the ones whose
#: `ProblemError` reaches `alert()`. A 4xx refusal (validation, not_found, forbidden,
#: conflict, auth) is an answer to a caller and alarms nobody.
_ALARMING_KINDS: frozenset[str] = frozenset({"dependency", "transient", "internal"})


def _literal_anywhere(code: str) -> bool:
    """Is `code` a quoted literal in any scanned source? See its one caller for why the
    search is tree-wide rather than per-file."""
    needle = f'"{code}"'
    return any(
        needle in path.read_text(encoding="utf-8")
        for root in PY_ROOTS
        for path in root.rglob("*.py")
        if "__pycache__" not in path.as_posix()
    )


def _python_files() -> Iterator[Path]:
    for root in PY_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Top-level `NAME = "literal"` (and `NAME: Final = "literal"`), by name.

    One hop of resolution, deliberately no more: a constant defined beside the code that
    raises it is still a literal a reader can find, while following imports would make
    this scanner an interpreter.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if value is None or not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value.value
    return constants


def _literal_code(node: ast.expr) -> str | None:
    """The alarm a code expression names, or None when it is a runtime value.

    An f-string contributes its literal PREFIX: `f"unhandled_exception:{cls}"` is the
    `unhandled_exception` family, which is how the alert fingerprint reads it too.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        head = node.values[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            return head.value.rstrip(":").strip() or None
    return None


def raised_codes() -> tuple[dict[str, set[str]], dict[str, set[str]], list[str]]:
    """`(code -> files that raise it, code -> stages it is raised WITH, failures)`.

    The failure list holds unresolvable call sites: a code this scanner cannot name is a
    code the index cannot cover, and guessing would be the same as not checking.

    THE SECOND DICT IS THE STAGE, and it is collected here rather than by a second walk
    because the stage is written on the same call as the code — `alert(stage, code)` and
    `ProblemError(code=..., failure_stage=...)` — so a separate scan would be a second
    spelling of this one. It is a SET per code because one code may legitimately be
    raised from two call sites; the index carries a single cell, so two stages behind one
    code is itself a finding (the row cannot be true of both).
    """
    codes: dict[str, set[str]] = {}
    stages: dict[str, set[str]] = {}
    failures: list[str] = []

    def record(code: str, where: Path, stage: str | None = None) -> None:
        codes.setdefault(code, set()).add(where.relative_to(REPO_ROOT).as_posix())
        if stage is not None:
            stages.setdefault(code, set()).add(stage)

    for path in _python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - a syntax error fails CI earlier
            failures.append(f"{rel}: could not be parsed ({exc})")
            continue
        constants = _module_constants(tree)

        def resolve(node: ast.expr | None, table: dict[str, str] = constants) -> str | None:
            # `table` is bound as a default so the closure captures THIS module's
            # constants rather than the loop variable's last value.
            if node is None:
                return None
            if isinstance(node, ast.Name):
                return table.get(node.id)
            return _literal_code(node)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # (1)+(2) direct alert() calls.
            if isinstance(node.func, ast.Name) and node.func.id == "alert":
                arg = node.args[1] if len(node.args) > 1 else None
                code = resolve(arg)
                stage = resolve(node.args[0]) if node.args else None
                # A `*_code` field read off a frozen descriptor: the literal is declared
                # where the descriptor is built, and shape (4) below collects it.
                covered_by_meter = isinstance(arg, ast.Attribute) and arg.attr.endswith("_code")
                if code is not None:
                    record(code, path, stage)
                elif covered_by_meter:
                    pass  # shape (4): the literal is on the meter, read below
                elif rel in DYNAMIC_ALERT_SITES:
                    for named in DYNAMIC_ALERT_SITES[rel][0]:
                        record(named, path)
                else:
                    failures.append(
                        f"{rel}:{node.lineno}: alert() is called with a code this scan "
                        "cannot resolve. Use a literal, or add the site to "
                        "DYNAMIC_ALERT_SITES with the codes it can raise and why."
                    )
            # (3) a ProblemError with a failure_stage is relayed into alert() verbatim by
            # `core/errors.install_error_handlers`, so its `code` IS an alarm code.
            if isinstance(node.func, ast.Name) and node.func.id == "ProblemError":
                keywords = {kw.arg: kw.value for kw in node.keywords}
                # ⚠ **AN OMITTED `failure_stage` IS NOT AN OMITTED ALARM, AND THIS SCAN
                # USED TO ASSUME IT WAS.** `ProblemError.__init__` DEFAULTS the stage to
                # `ROUTE_HANDLER`, so a refusal that never names one still reaches
                # `alert()` through the same relay — provided its `kind` is a 5xx. That
                # left 44 codes invisible here, unclassified in `alarm_severity.py`, and
                # therefore `page` by its fail-loud default: `rate_limited` on every
                # throttled request, `too_many_attempts` on every throttled login,
                # `service_load_shed` and `platform_maintenance` on every shed one. The
                # founder's inbox found this, which is the wrong instrument.
                #
                # So the KIND decides, not the presence of a keyword. A 4xx refusal is a
                # conversation with a caller and alarms nobody; the three 5xx kinds are
                # alarms whether or not the call site says so. A kind this scan cannot
                # resolve is treated as alarming, for `DEFAULT_SEVERITY`'s reason: an
                # over-classified code costs one line in a registry, and a missed one
                # costs the outage it was written for.
                kind = resolve(keywords.get("kind"))
                alarms = "failure_stage" in keywords or kind is None or kind in _ALARMING_KINDS
                if not alarms:
                    continue
                code = resolve(keywords.get("code"))
                if code is not None:
                    # `install_error_handlers` relays `alert(exc.failure_stage, exc.code)`
                    # verbatim, so the keyword IS the stage an operator will read.
                    record(code, path, resolve(keywords.get("failure_stage")))
                elif rel in DYNAMIC_ALERT_SITES:
                    # THE SAME ESCAPE HATCH SHAPE (2) HAS, because it is the same problem.
                    # A `ProblemError` whose code is a PARAMETER is as unresolvable as an
                    # `alert()` whose code is — `core/settings.py::_unusable_hmac_key` is
                    # one refusal shared by four key resolutions, each passing its own
                    # literal — and having the hatch on only one of the two scans meant
                    # the other could only fail. Registering the site is still a diff that
                    # names the codes and the reason, and they are re-verified below.
                    for named in DYNAMIC_ALERT_SITES[rel][0]:
                        record(named, path)
                else:
                    failures.append(
                        f"{rel}:{node.lineno}: a ProblemError carries a failure_stage — "
                        "so it pages somebody — with a code this scan cannot resolve. Use "
                        "a literal, or add the site to DYNAMIC_ALERT_SITES with the codes "
                        "it can raise and why."
                    )
        # (4) the ack-budget meters: a `*_code` literal on a frozen dataclass rather than
        # on the call. Matched by the KEYWORD NAME, so a third such field is picked up
        # without editing this file — which is the property that keeps the scan honest.
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg and node.arg.endswith("_code"):
                code = _literal_code(node.value)
                if code is not None:
                    record(code, path)

    # (5) the host backup chain.
    shell_seen = 0
    for path in sorted(SHELL_ROOT.glob("*.sh")):
        body = path.read_text(encoding="utf-8")
        for match in list(_SHELL_CALL.finditer(body)) + list(_SHELL_JSON.finditer(body)):
            shell_seen += 1
            record(match.group(1), path)
    if not shell_seen:
        failures.append(
            f"{SHELL_ROOT.relative_to(REPO_ROOT)}: the host-alarm scan matched NOTHING. "
            "Either the backup chain stopped raising alarms or its call shape changed "
            "and this scanner went blind — both need a person."
        )
    return codes, stages, failures


def _section(text: str, heading: str) -> str:
    """The slice under `heading`, up to the next `## ` heading, or empty if it is gone.

    Its own function because three readers now want it and each applies a different
    pattern to it; a heading that moves must blind all three at once, not one of them.
    """
    start = text.find(heading)
    if start < 0:
        return ""
    rest = text[start + len(heading) :]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def _table_rows(text: str, heading: str, pattern: re.Pattern[str]) -> set[str]:
    """The first column of every row under `heading`, up to the next `## ` heading."""
    return {match.group(1) for match in pattern.finditer(_section(text, heading))}


def documented_codes() -> set[str]:
    return _table_rows(INDEX.read_text(encoding="utf-8"), _ALARM_HEADING, _INDEX_ROW)


def documented_stages() -> dict[str, str]:
    """`{code: the stage its index row claims}`.

    A row whose stage cell does not parse is simply absent here, which is deliberate: it
    then fails as an unstaged row (see `stage_disagreements`) rather than being silently
    compared against nothing.
    """
    section = _section(INDEX.read_text(encoding="utf-8"), _ALARM_HEADING)
    return {m.group(1): m.group(2) for m in _INDEX_ROW_STAGE.finditer(section)}


def documented_severities() -> dict[str, str]:
    """`{code: the severity its index row claims}`, from the index's THIRD column."""
    section = _section(INDEX.read_text(encoding="utf-8"), _ALARM_HEADING)
    return {m.group(1): m.group(2) for m in _INDEX_ROW_SEVERITY.finditer(section)}


#: The severity registry, bound at module scope like every path constant above and for the
#: same reason: `tests/alarm_wiring_guard_test.py` drives DOCTORED trees through these
#: functions, and a registry reached by a hard-coded import inside the check would be the
#: one input the sandbox could not repoint — so the guard's own negative controls would
#: have to assert against the real 224 codes.
CLASSIFIED: dict[str, str] = dict(_ALARM_SEVERITY)
#: The prefix families, read from the same module the runtime reads.
FAMILIES: dict[str, str] = dict(_FAMILIES)


def severity_failures(
    raised: dict[str, set[str]] | None = None,
    classified: dict[str, str] | None = None,
) -> list[str]:
    """Every raised code is classified, and the index agrees with the classification.

    WHY THIS IS THIS GUARD'S JOB AND NOT A SECOND ONE. The founder's inbox filled up
    because `alert()` treated every code as equally worth an email (D-591), and the fix is
    a severity on every code. A severity list that anybody can forget to extend is the
    same defect one step over from the one this file already exists for: a code raised in
    the tree and absent from the document. So the contract is the same contract — you
    cannot add an alarm without classifying it — and it is enforced in the same sweep,
    against the same derived-from-the-tree vocabulary.

    TWO DIRECTIONS, AND A THIRD CHECK BETWEEN THEM:

    * a code the tree can raise and `core/alarm_severity.ALARM_SEVERITY` does not name —
      it would fall to the `page` default, which is the SAFE direction but not a decision
      anybody took;
    * a code the registry names that nothing raises — a dead classification, which reads
      to the next person as evidence that an alarm exists;
    * and the registry against the INDEX ROW, because `runbooks/alarm-index.md` is what an
      operator reads at 3am and "did this page me, or is it sitting on a console screen?"
      is the first thing they need from it. The PYTHON IS THE SOURCE OF TRUTH — `alert()`
      reads it on the SIGTERM path and inside voice-runtime's 500ms ack budget, where
      parsing a markdown table is not available at any price — and the document is checked
      against it, never the reverse.
    """
    raised = raised_codes()[0] if raised is None else raised
    registry = CLASSIFIED if classified is None else classified
    documented = documented_severities()
    failures: list[str] = []

    # A FAMILY ENTRY COVERS ITS MEMBERS. Two call sites compose a code at runtime
    # (`http_{status}`, `assist_{reason}`), so this scan resolves only their literal
    # PREFIX and an exact-match registry could never satisfy it — see
    # `alarm_severity.ALARM_SEVERITY_FAMILIES`. Asked the same way `severity_of` asks, so
    # the gate and the runtime cannot disagree about what is covered.
    def _covered(code: str) -> bool:
        return code in registry or any(code.startswith(p) for p in FAMILIES)

    for code in sorted(c for c in set(raised) if not _covered(c)):
        failures.append(
            f"UNCLASSIFIED: `{code}` can reach somebody and has no entry in "
            "apps/api/core/alarm_severity.ALARM_SEVERITY. Every alarm has to choose: "
            f"{', '.join(SEVERITIES)}. Unclassified codes default to `page`, so the build "
            "fails here rather than the founder's phone buzzing for it."
        )
    for code in sorted(
        c for c in set(registry) - set(raised) if not any(c.startswith(p) for p in FAMILIES)
    ):
        failures.append(
            f"CLASSIFIED, NEVER RAISED: ALARM_SEVERITY names `{code}` and nothing in the "
            "tree raises it. A dead classification reads as evidence that an alarm exists."
        )
    for code, severity in sorted(registry.items()):
        claimed = documented.get(code)
        if claimed is None and code in documented_codes():
            failures.append(
                f"NO SEVERITY: the alarm index row for `{code}` has no readable severity "
                "in its third column. An operator reading this row cannot tell whether "
                "silence means nothing is wrong or means it did not mail."
            )
        elif claimed is not None and claimed != severity:
            failures.append(
                f"SEVERITY DISAGREES: the alarm index says `{code}` is `{claimed}`; "
                f"alarm_severity.py routes it as `{severity}`. The Python is what "
                "`alert()` obeys, so the row is telling an operator a comfortable lie."
            )
    return failures


def documented_metrics() -> set[str]:
    return _table_rows(INDEX.read_text(encoding="utf-8"), _METRIC_HEADING, _METRIC_ROW)


def recorded_metrics() -> tuple[set[str], list[str]]:
    """Metric names, and every place one is emitted outside the named recorders.

    `alerting._record` is the only writer by design (`core/alerting.py`'s closing
    section). A module reaching for `metrics_log` directly invents a series that no SLO
    rule can name, which is how `speed_to_lead_seconds` came to exist with no vocabulary.
    """
    names: set[str] = set()
    failures: list[str] = []
    for path in _python_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - reported by raised_codes already
            continue
        for node in ast.walk(tree):
            is_record = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_record"
                and bool(node.args)
            )
            if is_record:
                assert isinstance(node, ast.Call)
                name = _literal_code(node.args[0])
                if name is not None:
                    names.add(name)
                elif rel == "apps/api/core/alerting.py":
                    failures.append(
                        f"{rel}:{node.lineno}: a metric is recorded under a name this "
                        "scan cannot resolve, so no index can cover it."
                    )
            # The direct emission the module docstring forbids, in any module.
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=False):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "metric"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                        and rel != "apps/api/core/alerting.py"
                    ):
                        failures.append(
                            f"{rel}:{node.lineno}: emits the metric "
                            f"'{value.value}' directly. Metrics are named recorders in "
                            "core/alerting.py (its docstring: 'ad-hoc counters are not "
                            "accepted') — add a `record_*` function and call it."
                        )
    return names, failures


def stage_disagreements(
    raised: dict[str, set[str]] | None = None, documented: dict[str, str] | None = None
) -> list[str]:
    """The index's STAGE column against the stage the code actually passes.

    WHY THE SECOND COLUMN EARNS A CHECK. `runbooks/alarm-index.md` opens with **"Read the
    stage first"** and then maps each stage onto a different first move — `CORE_LOGIC` is
    a decision inside the app, `WORKER_STALL` is the reliability path backing up,
    `WORKER_TERMINAL` is retries exhausted. Until this existed the guard proved only that
    a row EXISTED for every code, so a row could send an operator down the wrong branch of
    its own instructions and every gate stayed green. `calls_never_finished` was documented
    `WORKER_TERMINAL` and raised `WORKER_STALL` for as long as it had had a row.

    WHAT IT CANNOT SEE, said rather than hidden: a stage is only comparable where it is
    written beside the code. The host backup chain emits from shell, the ack-budget meters
    carry a `*_code` literal with the stage on the `alert()` a file away, and
    `DYNAMIC_ALERT_SITES` names codes rather than calls — so those rows are checked for
    HAVING a stage and not for which one. `main()` prints how many of each, so a scan that
    quietly stopped resolving stages shows up as the number falling.
    """
    raised = raised_codes()[1] if raised is None else raised
    documented = documented_stages() if documented is None else documented
    failures: list[str] = []
    for code in sorted(raised):
        stages = raised[code]
        if len(stages) > 1:
            failures.append(
                f"TWO STAGES, ONE ROW: `{code}` is raised as {sorted(stages)}. The index "
                "carries one stage cell, so no row can be true of both — either give the "
                "two call sites one stage or give them two codes."
            )
            continue
        claimed = documented.get(code)
        if claimed is not None and claimed not in stages:
            failures.append(
                f"WRONG STAGE: the alarm index says `{code}` is {claimed}; the code raises "
                f"it as {next(iter(stages))}. The index tells an operator to read the "
                "stage first, so a wrong one sends them down the wrong branch of their "
                "own runbook."
            )
    for code in sorted(set(documented_codes()) - set(documented)):
        failures.append(
            f"NO STAGE: the alarm index row for `{code}` has no readable stage in its "
            "second column. Every row's first instruction is to read that cell."
        )
    return failures


def dynamic_site_failures() -> list[str]:
    """Every code an exemption claims must still be a literal in the file it names."""
    failures: list[str] = []
    for rel, (claimed, reason) in DYNAMIC_ALERT_SITES.items():
        path = REPO_ROOT / rel
        if not path.exists():
            failures.append(f"DYNAMIC_ALERT_SITES names {rel}, which does not exist.")
            continue
        if len(reason) < 40:
            failures.append(f"DYNAMIC_ALERT_SITES[{rel}] has no reason a reviewer can weigh.")
        body = path.read_text(encoding="utf-8")
        for code in claimed:
            # SEARCHED IN THE TREE, NOT ONLY IN THE RAISING FILE — because a FACTORY's
            # codes live at its callers. `core/settings.py::_unusable_hmac_key` is one
            # refusal shared by four key resolutions, and each literal sits in the module
            # that needs the key (`compliance/audit.py`, `reliability/service.py`,
            # `copilot/write_tools.py`, `core/impersonation.py`). Requiring the string in
            # the raising file would have forced either four copies of one refusal or a
            # single vague code that cannot say WHICH subsystem stopped.
            #
            # The property this check exists for is unchanged: the string must still be a
            # literal SOMEWHERE, so a rename still breaks the build rather than quietly
            # leaving the index describing an alarm nobody can receive.
            if f'"{code}"' not in body and not _literal_anywhere(code):
                failures.append(
                    f"DYNAMIC_ALERT_SITES claims {rel} raises '{code}', and that string "
                    "is nowhere in the tree. Renamed, or moved — either way the index "
                    "is now describing an alarm nobody can receive."
                )
    return failures


def _operator_docs() -> Iterator[tuple[Path, str]]:
    """The text an operator reads at 3am: every runbook, plus OPERATIONS §4."""
    for path in sorted(RUNBOOKS.glob("*.md")):
        yield path, path.read_text(encoding="utf-8")
    operations = OPERATIONS.read_text(encoding="utf-8")
    start = operations.find("## 4. Observability & Alerting")
    end = operations.find("\n## 5.", max(start, 0))
    if start >= 0:
        yield OPERATIONS, operations[start : end if end > 0 else len(operations)]


def dangling_names(known: Iterable[str]) -> list[str]:
    """Backticked snake_case names in the operator docs that resolve nowhere.

    The point is not tidiness. A runbook that tells somebody to look for
    `complaint_spike_detected` when nothing raises it sends them hunting for an alarm that
    does not exist, and it reads exactly like a real instruction.
    """
    corpus: list[str] = []
    for root in CODE_ROOTS:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix not in {".pyc", ".png", ".jpg", ".lock"}:
                try:
                    corpus.append(path.read_text(encoding="utf-8"))
                except (UnicodeDecodeError, OSError):
                    continue
    blob = "\n".join(corpus)
    known_set = set(known)
    failures: list[str] = []
    for path, text in _operator_docs():
        local = "\n".join(_FENCED.findall(text))
        for match in _BACKTICKED.finditer(text):
            token = match.group(1).strip()
            if not _SNAKE.match(token) or token in known_set:
                continue
            # One leading word may be a COMPOSITION rather than part of the name: the
            # ingest path labels its outcomes `f"blocked_{decision.rule}"`, so
            # `blocked_spend_cap` is a real string an operator will read in a log and a
            # string no file contains. Exactly one word is stripped, so a made-up name
            # cannot slip through by having a common tail.
            _, _, tail = token.partition("_")
            if token in blob or token in local or (tail and tail in blob):
                continue
            failures.append(
                f"{path.relative_to(REPO_ROOT)}: names `{token}`, which matches "
                "nothing in apps/, packages/, scripts/, alembic/ or infra/. Either "
                "it was renamed or it was never built."
            )
    return failures


def broken_runbook_citations() -> list[str]:
    text = INDEX.read_text(encoding="utf-8")
    failures = []
    for match in _RUNBOOK_CITATION.finditer(text):
        if not (RUNBOOKS / match.group(1)).exists():
            failures.append(
                f"{INDEX.relative_to(REPO_ROOT)}: points at runbooks/{match.group(1)}, "
                "which does not exist."
            )
    return failures


def evaluate() -> list[str]:
    failures: list[str] = []
    codes, stages, scan_failures = raised_codes()
    failures.extend(scan_failures)
    failures.extend(dynamic_site_failures())

    if not INDEX.exists():
        return [*failures, f"{INDEX.relative_to(REPO_ROOT)} is missing: nothing to check against."]

    documented = documented_codes()
    # THE REFUSAL (`check_wiring`'s doctrine). An empty side means the scan or the parse
    # broke, and reporting OK on an empty set is how a guard dies unnoticed.
    if not codes:
        failures.append("The alarm scan found NO alert() call sites at all — it is blind.")
    if not documented:
        failures.append(
            f"{INDEX.relative_to(REPO_ROOT)} has no rows under '{_ALARM_HEADING}'. "
            "Either the table moved or its shape changed; this guard is now checking "
            "nothing."
        )

    for code in sorted(documented - set(codes)):
        failures.append(
            f"DOCUMENTED, NEVER RAISED: `{code}` is in the alarm index and no code path "
            "raises it. An operator reading this believes they will be paged."
        )
    for code in sorted(set(codes) - documented):
        where = ", ".join(sorted(codes[code])[:3])
        failures.append(
            f"RAISED, UNDOCUMENTED: `{code}` ({where}) can reach somebody's phone and "
            "appears in no alarm index row. Add it, with what it means and what to do."
        )

    metrics, metric_failures = recorded_metrics()
    failures.extend(metric_failures)
    documented_metric_names = documented_metrics()
    if not metrics:
        failures.append("The metric scan found NO named recorders — it is blind.")
    if not documented_metric_names:
        failures.append(f"{INDEX.relative_to(REPO_ROOT)} has no rows under '{_METRIC_HEADING}'.")
    for name in sorted(documented_metric_names - metrics):
        failures.append(f"DOCUMENTED, NEVER RECORDED: metric `{name}` has no recorder.")
    for name in sorted(metrics - documented_metric_names):
        failures.append(f"RECORDED, UNDOCUMENTED: metric `{name}` is in no index row.")

    failures.extend(stage_disagreements(stages, documented_stages()))
    failures.extend(severity_failures(codes, CLASSIFIED))
    failures.extend(broken_runbook_citations())
    failures.extend(dangling_names({*codes, *documented, *metrics, *documented_metric_names}))
    return failures


def main() -> int:
    failures = evaluate()
    if failures:
        print("Alarm wiring check FAILED:\n")
        for failure in failures:
            print(f"  - {failure}")
        print(
            "\nThe index is runbooks/alarm-index.md. A documented alarm with no call "
            "site is a promise nobody keeps; a raised alarm with no row is a page with "
            "no runbook."
        )
        return 1
    codes, stages, _ = raised_codes()
    metrics, _ = recorded_metrics()
    print(
        f"Alarm wiring OK: {len(codes)} alarm code(s) and {len(metrics)} metric(s), "
        f"documented; {len(stages)} of the codes carry a stage this scan can read and "
        "every one matches its index row."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
