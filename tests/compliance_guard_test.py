"""The compliance-invariants guardrail's own test suite: does it FAIL when the rule is?

`scripts/check_compliance_invariants.py` claims that nothing in this tree can place an
outbound call, or send a business-initiated message, without passing the gate — and that
no bypass exists. A guardrail making that claim while blind to a violation is worse than
no guardrail: it manufactures the confidence that stops anyone reading the diff.

Same two kinds of test `tests/guardrail_audit_test.py` established, for the same reasons:

- **wiring** — the check is pointed at the REAL tree and the REAL catalog, so a check
  that has drifted away from what it claims to read fails here. A test that builds its
  own fixture and asserts about the fixture proves only that the fixture exists.
- **detection** — take the real artefact, apply ONE minimal mutation that IS the
  violation, assert it is named. Every mutation below is a copy of a real repo file with
  one line changed, mirrored into a tmp tree — never an invented snippet, because an
  invented snippet stops resembling the code the moment the code moves.

The mutations are the four failures hard rule 5 is written against: a new dial site with
no gate, a dial site that calls the gate and ignores its answer, a `force=` parameter,
and an environment check inside the gate.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from scripts import check_compliance_invariants as guard
from scripts.check_compliance_invariants import CheckFacts, SchemaFacts, UniqueFacts
from sqlalchemy import Engine, create_engine, text

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- helpers ------------------------------------------------------------------


def _mirror(tmp_path: Path, *relative: str) -> Path:
    """Copy real repo files into a tmp tree at their real relative paths.

    The offender strings are relative paths, so a mutation only reads like the real
    thing if it sits where the real thing sits.
    """
    for name in relative:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / name, target)
    return tmp_path


def _edit(root: Path, relative: str, old: str, new: str) -> None:
    path = root / relative
    source = path.read_text(encoding="utf-8")
    assert old in source, f"the mutation no longer matches {relative} — update this test"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


@pytest.fixture(scope="session")
def engine() -> Engine:
    """The migrated database, or a skip — the same fixture the other guardrail suite
    uses, and for the same reason: a migration is a claim, the catalog is the fact."""
    from apps.api.core.settings import get_settings

    settings = get_settings()
    url = (settings.alembic_database_url or settings.database_url).replace("+asyncpg", "+psycopg")
    created = create_engine(url)
    try:
        with created.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - local machines without docker
        pytest.skip(f"no database: {type(exc).__name__}: {exc}")
    return created


# ============================================================================
# wiring — the check is looking at the real thing
# ============================================================================


class TestWiring:
    def test_the_gate_symbols_it_keys_on_still_exist(self) -> None:
        """If `check_dispatch` is renamed, every static section below silently matches
        nothing and reports OK. The check must announce that it has gone blind."""
        assert guard.blind_spots() == []
        registry = guard.gate_registry()
        assert registry.dial == "dispatch_call"
        assert "check_dispatch" in registry.gates and "assert_dispatch_allowed" in registry.gates

    def test_it_finds_the_real_dial_sites(self) -> None:
        """The count is not asserted — a new gated dial surface is legitimate and must
        not cost a test edit. What is asserted is that the scan SEES the known ones: a
        walk that found nothing would pass every section below."""
        sites = {site.qualname for site in guard.dial_sites()}
        assert "apps/api/crm/routes.py::call_lead" in sites
        assert "apps/workers/campaign_dispatch.py::_dispatch_for_campaign" in sites
        assert len(sites) >= 4, sites

    def test_it_sees_the_voice_runtime_tree(self) -> None:
        """`lint-imports` structurally cannot (grimp walks packages; D-18's directory is
        hyphenated), which is why this check walks paths itself. A dial added in the
        latency-critical service must be as visible as one added in `api`."""
        scanned = set(guard._python_files(guard.SCAN_ROOTS))
        assert any("voice-runtime" in str(path) for path in scanned)

    def test_the_real_tree_is_clean(self) -> None:
        assert guard.engine_reach() == []
        assert guard.ungated_dials() == []
        assert guard.unevidenced_messages() == []
        assert guard.gate_bypasses() == []
        assert guard.stale_exemptions() == []

    def test_the_live_schema_is_clean(self, engine: Engine) -> None:
        assert guard.evaluate_schema(guard.fetch_schema(engine)) == []

    def test_it_reads_the_real_catalog(self, engine: Engine) -> None:
        facts = guard.fetch_schema(engine)
        assert ("agents", "disclosure_line", True) in facts.columns
        assert any(check.table == "consent_ledger" for check in facts.checks)
        assert any(unique.table == "dnc_list" for unique in facts.uniques)


# ============================================================================
# detection — one real mutation each
# ============================================================================


class TestUngatedDial:
    """The defect this guardrail exists for: a FIFTH dial surface that forgot the gate."""

    def test_catches_a_new_dial_site_that_never_names_the_gate(self, tmp_path: Path) -> None:
        root = _mirror(tmp_path, "apps/api/crm/routes.py")
        (root / "apps/api/ops/quickdial.py").parent.mkdir(parents=True, exist_ok=True)
        (root / "apps/api/ops/quickdial.py").write_text(
            "from apps.api.agents.service import dispatch_call\n\n\n"
            "async def ring_this_lead(session, *, tenant_id, agent_id, phone_e164):\n"
            '    """An operator convenience nobody gated."""\n'
            "    return await dispatch_call(\n"
            "        session, tenant_id=tenant_id, agent_id=agent_id, lead_id=None,\n"
            "        phone_e164=phone_e164,\n"
            "    )\n",
            encoding="utf-8",
        )
        offenders = guard.ungated_dials(roots=(root,))
        assert any("quickdial.py::ring_this_lead" in o and "never calls" in o for o in offenders), (
            offenders
        )

    def test_catches_a_dial_that_calls_the_gate_and_ignores_the_answer(
        self, tmp_path: Path
    ) -> None:
        """The hole the existing per-function name check cannot see. `check_dispatch`
        RETURNS a decision rather than raising (so a UI can explain the refusal), which
        means naming it is not obeying it — delete four lines and the call is placed
        with the refusal sitting in a local variable."""
        root = _mirror(tmp_path, "apps/api/crm/routes.py")
        _edit(
            root,
            "apps/api/crm/routes.py",
            "    if not decision.allowed:\n"
            "        result = CallLeadOut(\n"
            '            status="blocked", blocked_reason=decision.reason, '
            "blocked_rule=decision.rule\n"
            "        )",
            "    if False:\n"
            "        result = CallLeadOut(\n"
            '            status="blocked", blocked_reason=decision.reason, '
            "blocked_rule=decision.rule\n"
            "        )",
        )
        offenders = guard.ungated_dials(roots=(root,))
        assert any("routes.py::call_lead" in o and "does not act on" in o for o in offenders), (
            offenders
        )

    def test_catches_a_gate_call_that_happens_after_the_dial(self, tmp_path: Path) -> None:
        """Order is the whole rule. A decision read after the phone has already rung is
        a log line, not a gate."""
        root = tmp_path
        (root / "apps/api/ops").mkdir(parents=True, exist_ok=True)
        (root / "apps/api/ops/late.py").write_text(
            "from apps.api.agents.service import dispatch_call\n"
            "from apps.api.compliance.service import check_dispatch\n\n\n"
            "async def ring_then_ask(session, *, tenant_id, agent_id, phone_e164):\n"
            "    handle = await dispatch_call(\n"
            "        session, tenant_id=tenant_id, agent_id=agent_id, lead_id=None,\n"
            "        phone_e164=phone_e164,\n"
            "    )\n"
            "    decision = await check_dispatch(\n"
            "        session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone_e164\n"
            "    )\n"
            "    if not decision.allowed:\n"
            "        return None\n"
            "    return handle\n",
            encoding="utf-8",
        )
        offenders = guard.ungated_dials(roots=(root,))
        assert any("late.py::ring_then_ask" in o for o in offenders), offenders

    def test_does_not_cry_wolf_on_the_raising_form(self, tmp_path: Path) -> None:
        """`assert_dispatch_allowed` raises, so there is no decision to branch on. A
        check that demanded an `if` would push callers back to the returning form."""
        root = tmp_path
        (root / "apps/api/ops").mkdir(parents=True, exist_ok=True)
        (root / "apps/api/ops/raising.py").write_text(
            "from apps.api.agents.service import dispatch_call\n"
            "from apps.api.compliance.service import assert_dispatch_allowed\n\n\n"
            "async def ring(session, *, tenant_id, agent_id, phone_e164):\n"
            "    await assert_dispatch_allowed(\n"
            "        session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone_e164\n"
            "    )\n"
            "    return await dispatch_call(\n"
            "        session, tenant_id=tenant_id, agent_id=agent_id, lead_id=None,\n"
            "        phone_e164=phone_e164,\n"
            "    )\n",
            encoding="utf-8",
        )
        assert guard.ungated_dials(roots=(root,)) == []


class TestEngineReach:
    def test_catches_a_second_route_to_the_engine(self, tmp_path: Path) -> None:
        """`dispatch_call` is the chokepoint only for as long as it is the only caller
        of the engine's outbound start. A module that reaches past it inherits none of
        the gate, the pre-dispatch call row or the audit trail."""
        root = tmp_path
        (root / "apps/api/ops").mkdir(parents=True, exist_ok=True)
        (root / "apps/api/ops/direct.py").write_text(
            "from apps.api.engine import get_engine\n\n\n"
            "async def ring(ref, phone, ctx):\n"
            "    return await get_engine().start_outbound_call(ref, phone, ctx)\n",
            encoding="utf-8",
        )
        offenders = guard.engine_reach(roots=(root,), exemptions={})
        assert any("direct.py::ring" in o for o in offenders), offenders

    def test_the_chokepoint_exemption_is_what_keeps_the_real_tree_green(self) -> None:
        """The exemption is load-bearing or it is decoration. Take it away and the one
        legitimate engine reach must come back into view — otherwise the check is not
        actually looking at `dispatch_call` and would not see a second one either."""
        offenders = guard.engine_reach(exemptions={})
        assert offenders == [
            "apps/api/agents/service.py::dispatch_call reaches the engine's "
            "outbound start directly (no exemption recorded)"
        ], offenders

    def test_catches_an_exemption_that_no_longer_names_a_live_dial(self) -> None:
        """Every exemption names a reason AND is verified live. One that stops matching
        a real engine reach is a hole waiting for the next module to land on that name —
        the same rule `impersonation_reads_test` applies to its route exemptions."""
        failures = guard.stale_exemptions(
            exemptions={
                **guard.ENGINE_REACH_EXEMPTIONS,
                "apps/api/telephony/legacy.py::place_call": "removed three releases ago",
            }
        )
        assert any("legacy.py::place_call" in f for f in failures), failures

    def test_catches_a_reasonless_exemption(self) -> None:
        failures = guard.stale_exemptions(
            exemptions={"apps/api/agents/service.py::dispatch_call": "TODO"}
        )
        assert any("too thin" in f for f in failures), failures


class TestBypasses:
    def test_catches_a_force_parameter_on_the_dispatcher(self, tmp_path: Path) -> None:
        """Hard rule 5: never a bypass "for testing". It arrives as a parameter, and the
        one place it gets left on is production."""
        root = _mirror(tmp_path, "apps/workers/campaign_dispatch.py")
        _edit(
            root,
            "apps/workers/campaign_dispatch.py",
            "    tenant_id: UUID, campaign_id: UUID, slots: int, retry_policy: dict[str, Any]\n",
            "    tenant_id: UUID, campaign_id: UUID, slots: int, retry_policy: dict[str, Any],\n"
            "    force: bool = False,\n",
        )
        offenders = guard.gate_bypasses(roots=(root,))
        assert any("_dispatch_for_campaign" in o and "force" in o for o in offenders), offenders

    def test_catches_a_bypass_keyword_passed_at_a_call_site(self, tmp_path: Path) -> None:
        """A parameter scan alone misses the other half: the flag can be declared on the
        callee and only ever be visible at the caller."""
        root = tmp_path
        (root / "apps/api/ops").mkdir(parents=True, exist_ok=True)
        (root / "apps/api/ops/staging.py").write_text(
            "from apps.api.compliance.service import check_dispatch\n\n\n"
            "async def preview(session, *, tenant_id, agent_id, phone_e164):\n"
            "    return await check_dispatch(\n"
            "        session, tenant_id=tenant_id, agent_id=agent_id,\n"
            "        phone_e164=phone_e164, skip_gate=True,\n"
            "    )\n",
            encoding="utf-8",
        )
        offenders = guard.gate_bypasses(roots=(root,))
        assert any("staging.py::preview" in o and "skip_gate" in o for o in offenders), offenders

    def test_catches_an_environment_check_inside_the_gate(self, tmp_path: Path) -> None:
        """The subtler bypass, and the one that does not look like one: `if
        settings.app_env != "production"` inside the gate weakens it everywhere the
        environment is not production — including every staging dial to a real phone."""
        root = _mirror(tmp_path, "apps/api/compliance/service.py")
        _edit(
            root,
            "apps/api/compliance/service.py",
            "    platform = await get_platform_status()",
            '    if get_settings().app_env != "production":\n'
            "        return DispatchDecision(allowed=True)\n"
            "    platform = await get_platform_status()",
        )
        offenders = guard.gate_bypasses(roots=(root,))
        assert any("check_dispatch" in o and "app_env" in o for o in offenders), offenders

    def test_does_not_cry_wolf_on_environment_reads_outside_the_gate(self) -> None:
        """`compliance/audit.py` salts the audit hash chain with `app_env`, and the
        WhatsApp transport factory refuses the dev sink outside local — both are reads of
        the environment in compliance-adjacent code, and neither weakens a gate. A check
        scoped by PACKAGE rather than by gate-bearing FUNCTION would report both, and the
        exemptions that followed would be the end of it."""
        assert guard.gate_bypasses() == []

    def test_does_not_cry_wolf_on_an_unrelated_force_parameter(self, tmp_path: Path) -> None:
        root = tmp_path
        (root / "apps/api/kb").mkdir(parents=True, exist_ok=True)
        (root / "apps/api/kb/reindex.py").write_text(
            "async def recompile(session, *, tenant_id, force: bool = False):\n    return force\n",
            encoding="utf-8",
        )
        assert guard.gate_bypasses(roots=(root,)) == []


class TestMessagingConsent:
    def test_catches_a_send_whose_opt_in_evidence_check_is_gone(self, tmp_path: Path) -> None:
        """SEC-COMP §4: messaging consent "is its own permission, and it is never
        inferred". Meta requires an affirmative opt-in producible on challenge, and DPDP
        §6 binds consent to its purpose — so a send that cannot point at one is a send
        that must not happen."""
        root = _mirror(tmp_path, "apps/workers/whatsapp.py")
        _edit(
            root,
            "apps/workers/whatsapp.py",
            "    if destination.opt_in_at is None:",
            "    if False:",
        )
        offenders = guard.unevidenced_messages(roots=(root,))
        assert any("_send_escalation" in o for o in offenders), offenders

    def test_catches_a_new_send_site_with_no_opt_in_check_at_all(self, tmp_path: Path) -> None:
        root = tmp_path
        (root / "apps/workers").mkdir(parents=True, exist_ok=True)
        (root / "apps/workers/blast.py").write_text(
            "from apps.workers.whatsapp import WhatsAppMessage, get_whatsapp_transport\n\n\n"
            "def announce(phone, template, locale):\n"
            "    return get_whatsapp_transport().send(\n"
            "        WhatsAppMessage(to_e164=phone, template=template, locale=locale,\n"
            "                        variables=())\n"
            "    )\n",
            encoding="utf-8",
        )
        offenders = guard.unevidenced_messages(roots=(root,))
        assert any("blast.py::announce" in o for o in offenders), offenders


# ============================================================================
# the catalog half — a migration is a claim, this is the fact
# ============================================================================


def _facts(engine: Engine) -> SchemaFacts:
    return guard.fetch_schema(engine)


class TestSchemaInvariants:
    def test_catches_a_nullable_disclosure_line(self, engine: Engine) -> None:
        """Hard rule 5's first clause, and SEC-COMP §2.1: "agents always have a non-null
        disclosure line". The gate's own check is belt-and-braces; the column is the
        guarantee."""
        facts = _facts(engine)
        weakened = replace(
            facts,
            columns=frozenset(
                (t, c, False) if (t, c) == ("agents", "disclosure_line") else (t, c, n)
                for t, c, n in facts.columns
            ),
        )
        failures = guard.evaluate_schema(weakened)
        assert any("disclosure_line" in f and "NOT NULL" in f for f in failures), failures

    def test_catches_the_loss_of_the_non_empty_check(self, engine: Engine) -> None:
        """NOT NULL alone admits `''` — an agent that opens a call disclosing nothing,
        which is the IT-Act exposure SEC-COMP §1 records, not a cosmetic gap."""
        facts = _facts(engine)
        weakened = replace(
            facts,
            checks=tuple(
                check
                for check in facts.checks
                if not (check.table == "agents" and "disclosure_line" in check.definition)
            ),
        )
        failures = guard.evaluate_schema(weakened)
        assert any("disclosure_line" in f and "empty" in f for f in failures), failures

    def test_catches_the_loss_of_the_dnc_conflict_target(self, engine: Engine) -> None:
        """`add_to_dnc` is `ON CONFLICT (tenant_id, phone_e164) DO NOTHING`. Without the
        unique key the statement is a runtime error, so the in-call "don't call me again"
        tool fails — and hard rule 5's propagation deadline is missed by the one path
        that matters most, the caller who asked."""
        facts = _facts(engine)
        weakened = replace(facts, uniques=tuple(u for u in facts.uniques if u.table != "dnc_list"))
        failures = guard.evaluate_schema(weakened)
        assert any("dnc_list" in f for f in failures), failures

    def test_catches_messaging_consent_that_need_not_name_its_source(self, engine: Engine) -> None:
        """SEC-COMP §4 encodes messaging consent as a ledger row "with a mandatory
        consent_source and evidence" — because what Meta asks for on challenge is the
        timestamp AND the source. A row that can omit the source is not evidence."""
        facts = _facts(engine)
        weakened = replace(
            facts,
            checks=tuple(
                check
                for check in facts.checks
                if not (check.table == "consent_ledger" and "messaging" in check.definition)
            ),
        )
        failures = guard.evaluate_schema(weakened)
        assert any("consent_ledger" in f and "messaging" in f for f in failures), failures

    def test_it_is_not_keyed_on_constraint_names(self, engine: Engine) -> None:
        """Renaming a constraint is a legal migration. A check that matched `conname`
        would fire on the rename and stay green on the drop — exactly backwards."""
        facts = _facts(engine)
        renamed = replace(
            facts,
            checks=tuple(replace(c, name=f"renamed_{i}") for i, c in enumerate(facts.checks)),
            uniques=tuple(UniqueFacts(u.table, u.columns) for u in facts.uniques),
        )
        assert guard.evaluate_schema(renamed) == []

    def test_baseline_holds(self, engine: Engine) -> None:
        """Without this, every mutation above could be passing for the wrong reason."""
        assert guard.evaluate_schema(_facts(engine)) == []

    def test_an_empty_catalog_is_reported_as_blindness_not_as_health(self) -> None:
        """A connection to the wrong database, or a schema that never migrated, must not
        read as "no violations found"."""
        failures = guard.evaluate_schema(SchemaFacts(columns=frozenset(), checks=(), uniques=()))
        assert failures, "an empty catalog must fail, loudly"
        assert any("agents" in f for f in failures)


def test_a_check_that_is_only_a_check_facts_shape() -> None:
    """Guard against the dataclasses drifting out from under the tests above."""
    assert CheckFacts("t", "n", "d").definition == "d"
    assert UniqueFacts("t", ("a", "b")).columns == ("a", "b")


# ============================================================================
# the Makefile / CI surface
# ============================================================================


def test_the_guardrail_runs_in_both_gates() -> None:
    """A check nobody runs is a file. `tests/guardrail_audit_test.py` asserts the same
    property for the other five; this keeps the new one honest without editing that
    file's pinned list."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts.check_compliance_invariants" in makefile
    assert "scripts.check_compliance_invariants" in workflow
