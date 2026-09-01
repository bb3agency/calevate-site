"""The guardrails' own test suite: does each one FAIL when its rule is broken?

A guardrail that passes while the violation it names is present is worse than no
guardrail — it manufactures confidence. `make guardrails` proves the repo is currently
clean; nothing proved that the checks can still SEE a violation. That is what this file
is for, and it is why every test here calls the guardrail's own functions rather than
re-implementing the rule: a weakened guardrail must fail a test, not quietly agree with
a copy of itself.

Two kinds of test, deliberately:

- **wiring** — the guardrail is pointed at the real artefact (the live OpenAPI, the real
  `.env.example`, the real repo tree, the real `pg_catalog`), so a check that has become
  disconnected from reality fails here. A test that builds its own fixture and then
  asserts about that fixture proves only that the fixture exists.
- **detection** — take the REAL artefact, apply ONE minimal mutation that is exactly the
  violation the guardrail claims to catch, and assert it is reported. Mutating reality
  rather than inventing a fixture is what keeps the mutation meaningful: if the guardrail
  stops looking at that part of reality, these fail.
"""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from apps.api.db.registry import APPEND_ONLY_TABLES, RLS_EXEMPT_TENANT_COLUMNS, TENANT_TABLES
from scripts import (
    check_config_applies,
    check_env_parity,
    check_ledger_immutability,
    check_openapi_fresh,
    check_redaction_exposure,
    check_rls_coverage,
)
from scripts.check_rls_coverage import PolicyFacts, SchemaState
from sqlalchemy import Engine, create_engine, text

REPO_ROOT = Path(__file__).resolve().parent.parent
GUC = f"(tenant_id = NULLIF(current_setting('{check_rls_coverage.TENANT_GUC}', true), '')::uuid)"


# --- shared fixtures ----------------------------------------------------------


@pytest.fixture(scope="session")
def engine() -> Engine:
    """The migrated database, or a skip. Never a stand-in: the RLS and trigger
    guardrails read `pg_catalog` precisely because a migration file is a claim and the
    catalog is the fact."""
    from apps.api.core.settings import get_settings

    settings = get_settings()
    url = (settings.alembic_database_url or settings.database_url).replace("+asyncpg", "+psycopg")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - local machines without docker
        pytest.skip(f"no database: {type(exc).__name__}: {exc}")
    return engine


@pytest.fixture(scope="session")
def live_spec() -> dict[str, Any]:
    from apps.api.main import app

    return dict(app.openapi())


def _tenant_state() -> SchemaState:
    """A baseline built from the REAL registry: every tenant table the repo declares,
    each with the policy shape the migrations create. Adding a tenant table to the
    registry therefore widens these tests automatically."""
    policies = tuple(
        PolicyFacts(
            table=table,
            name=check_rls_coverage.POLICY_NAME,
            rls_enabled=True,
            rls_forced=True,
            using=GUC,
            with_check=None,
            cmd="*",
            permissive=True,
        )
        for table in [*TENANT_TABLES, "organizations", *RLS_EXEMPT_TENANT_COLUMNS]
    )
    return SchemaState(
        tenant_column_tables=frozenset({*TENANT_TABLES, *RLS_EXEMPT_TENANT_COLUMNS}),
        policies=policies,
        model_tables=frozenset({*TENANT_TABLES, "organizations", *RLS_EXEMPT_TENANT_COLUMNS}),
    )


def _without(state: SchemaState, table: str) -> SchemaState:
    return replace(state, policies=tuple(p for p in state.policies if p.table != table))


def _patched(state: SchemaState, table: str, **changes: Any) -> SchemaState:
    return replace(
        state,
        policies=tuple(replace(p, **changes) if p.table == table else p for p in state.policies),
    )


# ============================================================================
# check_rls_coverage — hard rule 1
# ============================================================================


class TestRlsCoverage:
    def test_wiring_reads_the_live_catalog(self, engine: Engine) -> None:
        """The check must see the real tables, not a list it was handed."""
        state = check_rls_coverage.fetch_state(engine)
        assert set(TENANT_TABLES) <= state.tenant_column_tables
        assert any(p.name == check_rls_coverage.POLICY_NAME for p in state.policies)

    def test_live_schema_is_clean(self, engine: Engine) -> None:
        assert check_rls_coverage.evaluate(check_rls_coverage.fetch_state(engine)) == []

    def test_baseline_passes(self) -> None:
        """Without this the detection tests below could pass for the wrong reason."""
        assert check_rls_coverage.evaluate(_tenant_state()) == []

    def test_catches_missing_policy(self) -> None:
        failures = check_rls_coverage.evaluate(_without(_tenant_state(), "leads"))
        assert any("leads" in f and "NO tenant_isolation policy" in f for f in failures)

    def test_catches_rls_enabled_but_not_forced(self) -> None:
        failures = check_rls_coverage.evaluate(_patched(_tenant_state(), "calls", rls_forced=False))
        assert any("calls" in f and "FORCEd" in f for f in failures)

    def test_catches_using_true(self) -> None:
        """A policy named `tenant_isolation` that reads no GUC isolates nothing — the
        name is not the check."""
        failures = check_rls_coverage.evaluate(_patched(_tenant_state(), "leads", using="true"))
        assert any("leads" in f and "isolates nothing" in f for f in failures)

    def test_catches_with_check_true(self) -> None:
        """USING alone still lets a tenant WRITE rows stamped with another tenant_id."""
        state = _patched(_tenant_state(), "leads", with_check="true")
        failures = check_rls_coverage.evaluate(state)
        assert any("leads" in f and "WITH CHECK" in f for f in failures)

    def test_catches_an_extra_permissive_policy_that_reopens_the_table(self) -> None:
        """Policies are OR'd: one `USING (true)` next to a perfect policy is a hole."""
        state = _tenant_state()
        rogue = PolicyFacts(
            table="leads",
            name="debug_all_access",
            rls_enabled=True,
            rls_forced=True,
            using="true",
            with_check=None,
            cmd="*",
            permissive=True,
        )
        failures = check_rls_coverage.evaluate(replace(state, policies=(*state.policies, rogue)))
        assert any("debug_all_access" in f for f in failures)

    def test_catches_a_new_tenant_table_missing_from_the_registry(self) -> None:
        state = _tenant_state()
        state = replace(
            state,
            tenant_column_tables=state.tenant_column_tables | {"whatsapp_threads"},
            model_tables=state.model_tables | {"whatsapp_threads"},
        )
        failures = check_rls_coverage.evaluate(state)
        assert any("whatsapp_threads" in f for f in failures)

    def test_catches_a_new_tenant_table_hidden_behind_a_thin_exemption(self) -> None:
        """The exemption list is the cheapest way to smuggle a table past this check.
        An exemption has to be an argument a reviewer can weigh."""
        state = _tenant_state()
        state = replace(
            state,
            tenant_column_tables=state.tenant_column_tables | {"whatsapp_threads"},
            model_tables=state.model_tables | {"whatsapp_threads"},
        )
        failures = check_rls_coverage.evaluate(
            state,
            exemptions={**RLS_EXEMPT_TENANT_COLUMNS, "whatsapp_threads": "TODO"},
        )
        assert any("whatsapp_threads" in f and "too thin" in f for f in failures)

    def test_catches_a_platform_table_nobody_registered(self) -> None:
        """Rule 7a, and the shape it exists for.

        `platform_state` and `platform_ai_spend` were both created AFTER two siblings had
        already been registered, and neither was added — because a table with no
        `tenant_id` is invisible to every column-driven rule above it. The prefix is this
        repo's own convention for "one row for the whole deployment", so it is a
        mechanical question with a mechanical answer.
        """
        state = _tenant_state()
        state = replace(state, all_tables=state.all_tables | {"platform_new_thing"})

        failures = check_rls_coverage.evaluate(state)

        assert any("platform_new_thing" in f and "platform-scoped" in f for f in failures)

    def test_catches_an_object_reference_to_tenant_data_with_no_tenant(self) -> None:
        """Rule 7b, and the one that mattered.

        A row holding `payload_ref` is a pointer INTO tenant data — it dereferences to a
        CRM payload carrying a lead's name and number — so it is tenant data at one
        remove. `webhook_deliveries` had no `tenant_id`, no policy, and its justification
        only in a model docstring that no guardrail reads and no test pinned.
        """
        state = _tenant_state()
        state = replace(
            state,
            all_tables=state.all_tables | {"delivery_receipts"},
            object_ref_tables=frozenset({"delivery_receipts"}),
        )

        failures = check_rls_coverage.evaluate(state)

        assert any("delivery_receipts" in f and "object-storage reference" in f for f in failures)

    def test_a_registered_object_reference_table_passes(self) -> None:
        """The control. Rule 7b asks for a WRITTEN REASON, not for a policy — a table
        that genuinely cannot carry a tenant_id at write time (an inbound webhook is
        recorded before tenant resolution) must be able to satisfy it."""
        state = _tenant_state()
        state = replace(
            state,
            all_tables=state.all_tables | {"delivery_receipts"},
            object_ref_tables=frozenset({"delivery_receipts"}),
        )

        failures = check_rls_coverage.evaluate(
            state,
            exemptions={
                **RLS_EXEMPT_TENANT_COLUMNS,
                "delivery_receipts": (
                    "recorded before tenant resolution; holds an object key and never a "
                    "payload, and the bytes behind it are reachable only through workers"
                ),
            },
        )

        assert not any("delivery_receipts" in f for f in failures)

    def test_catches_a_tenant_payload_held_inline(self) -> None:
        """Rule 7c, and the one 7b structurally could not see.

        7b matches on a column holding an object-storage KEY, so it catches the POINTER
        to a CRM body and is blind to the body itself sitting in a jsonb column — the
        same exposure with one less hop. `outbox_messages.payload` is that shape and is
        the worse of the two: it holds a subject's email address beside a plaintext
        password-reset secret, and the whole outbound delivery body (a lead's name,
        number and extracted fields). It had no tenant_id, no policy, and no entry in
        the dict whose contract is to answer "what is not tenant-isolated, and why".
        """
        state = _tenant_state()
        state = replace(
            state,
            all_tables=state.all_tables | {"job_queue"},
            inline_payload_tables=frozenset({"job_queue"}),
        )

        failures = check_rls_coverage.evaluate(state)

        assert any("job_queue" in f and "INLINE" in f for f in failures)

    def test_an_inline_payload_table_with_a_tenant_id_is_rules_1_to_3s_business(self) -> None:
        """The scoping control. 7c must fire only on tables the column-driven rules
        cannot see — `lead_events.payload` and `leads.data` are jsonb payloads too, and
        they are already isolated. A rule that also reported them would push a reviewer
        to register tables that need a POLICY, which is the opposite of its purpose."""
        state = _tenant_state()
        state = replace(state, inline_payload_tables=frozenset({"lead_events"}))

        failures = check_rls_coverage.evaluate(state)

        assert not any("lead_events" in f and "INLINE" in f for f in failures)

    def test_a_registered_inline_payload_table_passes(self) -> None:
        """The control. Like 7b, 7c asks for a WRITTEN REASON and not for a policy: the
        reliability triad is claimed by a dispatcher with no tenant context, so a tenant
        predicate is genuinely unavailable at write time and registering is the right
        answer."""
        state = _tenant_state()
        state = replace(
            state,
            all_tables=state.all_tables | {"job_queue"},
            inline_payload_tables=frozenset({"job_queue"}),
        )

        failures = check_rls_coverage.evaluate(
            state,
            exemptions={
                **RLS_EXEMPT_TENANT_COLUMNS,
                "job_queue": (
                    "claimed across tenants by a dispatcher that has no tenant context; "
                    "no client-realm route names it and the payload is scrubbed in the "
                    "same statement that flips the status"
                ),
            },
        )

        assert not any("job_queue" in f for f in failures)

    def test_every_policy_less_table_is_registered_or_tenant_scoped(self, engine: Engine) -> None:
        """THE STRUCTURAL COMPANION TO THE PIN, asking the DATABASE rather than the dict.

        `test_exemption_list_is_pinned` has named this test since P4.6 as the thing that
        makes the pin sufficient — and it did not exist. That is exactly the gap it was
        described to close: the pin proves nobody ADDED an exemption without review, and
        is silent about a table that was never registered at all. `outbox_messages` and
        `idempotency_records` were both in that silence, holding a plaintext reset secret
        and a replayed response body between them, while `webhook_deliveries` — which
        holds only a KEY to a comparable body — carried a fifteen-line entry.

        The claim is deliberately narrower than "every unpoliced table must be
        registered", for the reason `evaluate`'s rule 7 gives: a list long enough to
        include `alembic_version` is a list nobody reads. What it asserts is that the
        three SHAPES rule 7 names are, against the live catalog, actually covered — so a
        new table of any of those shapes fails here even if a future edit loosened the
        script.
        """
        with engine.connect() as connection:
            unpoliced = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT c.relname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
                        "AND NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid)"
                    )
                )
            }
            interesting = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT DISTINCT c.relname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "JOIN pg_attribute a ON a.attrelid = c.oid "
                        "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') "
                        "AND a.attnum > 0 AND NOT a.attisdropped AND ("
                        "  a.attname = 'tenant_id'"
                        "  OR a.attname = ANY(:refs)"
                        "  OR (a.attname = ANY(:inline) AND a.atttypid = 'jsonb'::regtype))"
                    ),
                    {
                        "refs": list(check_rls_coverage._OBJECT_REF_COLUMNS),
                        "inline": list(check_rls_coverage._INLINE_PAYLOAD_COLUMNS),
                    },
                )
            }
            platform = {t for t in unpoliced if t.startswith("platform_")}

        needs_reason = (unpoliced & interesting) | platform
        unregistered = sorted(needs_reason - set(RLS_EXEMPT_TENANT_COLUMNS))

        assert unregistered == [], (
            f"{unregistered} carry tenant data (or are platform state) and have NO RLS "
            "policy at all, and none is registered in RLS_EXEMPT_TENANT_COLUMNS. Either "
            "give the table a FORCEd tenant_isolation policy or state in the registry "
            "why cross-tenant access is correct and what stops the data leaking."
        )

    def test_catches_a_stale_exemption(self) -> None:
        failures = check_rls_coverage.evaluate(
            _tenant_state(),
            exemptions={
                **RLS_EXEMPT_TENANT_COLUMNS,
                "table_deleted_three_releases_ago": (
                    "kept around long after the table was dropped, which is how an "
                    "exemption list turns into a hiding place for the next table"
                ),
            },
        )
        assert any("STALE RLS exemption" in f for f in failures)

    def test_exemption_list_is_pinned(self) -> None:
        """Adding an RLS exemption must cost a visible diff in a TEST, not one line in
        a dict. If this fails, review the new exemption on its merits and update it.

        The `platform_*` entries are the second SHAPE this list carries: tables with no
        `tenant_id` at all, exempt because they are platform state rather than because a
        tenant policy was skipped (PLATFORM-CONFIG §5). They are in the same dict on
        purpose — one list answering "what is not tenant-isolated, and why" is
        reviewable; two lists is one list nobody reads.

        **AND THAT SECOND SHAPE IS EXACTLY WHY THIS PIN IS NOT ENOUGH ON ITS OWN (P4.6).**
        A table with no `tenant_id` is invisible to `check_rls_coverage`, which is
        column-driven — so `platform_state`, `platform_ai_spend` and `webhook_deliveries`
        sat outside this dict for months with nothing able to notice, while the registry's
        own contract says it is the one place a reviewer learns what is deliberately not
        tenant-isolated. `webhook_deliveries` is the one that mattered: it holds
        `payload_ref`, the object-storage key of a CRM payload carrying a lead's name and
        number, and its "why" lived only in a model docstring no guardrail reads. The
        structural companion to this pin is
        `test_every_policy_less_table_is_registered_or_tenant_scoped` below, which asks
        the DATABASE rather than the dict.
        """
        assert set(RLS_EXEMPT_TENANT_COLUMNS) == {
            "audit_log",
            # D-475: the pulled USD/INR rate. Platform state — one exchange rate for the
            # whole deployment at an instant, so there is no tenant whose row it could be —
            # and read only behind `platform:config` in the admin realm.
            "fx_rate_observations",
            "engine_agent_routes",
            "platform_settings",
            "platform_config_version",
            "platform_secrets",
            # D-459: the founder's attested per-model prices, set once per model in
            # the ops console and read by billing for `unit_cost_paid`. Platform-
            # global for the same reason `platform_secrets` is — a price is the
            # founder's, not a tenant's — so it carries no `tenant_id` and is
            # policied on the ops GUC rather than tenant-isolated.
            "platform_model_prices",
            # D-492: the self-serve list price per calling minute, effective-dated so a
            # CLOSED month renders at the rate it was struck at rather than at today's.
            # Platform-global for `platform_model_prices`' reason on the other side of the
            # margin — one published price for the whole self-serve motion at an instant,
            # and a managed client's price is their `plans` row.
            "platform_list_rates",
            "platform_dashboard_data_use",
            "platform_state",
            "platform_ai_spend",
            # D-499: the ADMIN copilot's own AI spend, and the operator memories that go
            # with it. Platform state for `platform_ai_spend`'s reason with one extra turn
            # of the screw — the payer is CALEVATE, never a client, so there is not merely
            # no tenant whose row this could be, there is a decision that it must not be a
            # client's. `viewing_tenant_id` on both tables is CONTEXT (which account was on
            # screen) and is nullable and SET NULL on delete; nothing prices it and no
            # client-facing figure reads it.
            "platform_ai_usage",
            "admin_copilot_memories",
            # The state behind `engine_error_spike` (OPERATIONS §4): one row per
            # (engine, minute) of vendor server errors. Platform state for the same
            # reason `platform_state` is — the engine is answering or it is not, for
            # everybody at once.
            "platform_engine_health",
            "webhook_deliveries",
            # The FOURTH shape, and the one `webhook_deliveries` above is one hop short
            # of: a tenant payload held INLINE rather than by reference. `payload` on the
            # outbox carries a subject's email address beside a plaintext password-reset
            # secret and the whole outbound CRM body; `response_payload` is a replayed
            # response, so for a client-realm route it is whatever that route returned.
            # Neither can carry a tenant predicate — the outbox dispatcher claims across
            # tenants with no context, and the idempotency record is scoped by its LOOKUP
            # KEY (`reliability.scope_key`, guarded by `check_idempotency_scope`) rather
            # than by a policy. Both sat outside this dict until rule 7c could see them.
            "outbox_messages",
            "idempotency_records",
            # The THIRD shape, added by D-165: tables that are policied HARDER than a
            # tenant table rather than more loosely. `auth_credentials` and
            # `auth_sessions` carry no `tenant_id` because identity crosses tenants, and
            # their FORCEd policy is `current_setting('app.auth', true) = 'on'` — a GUC
            # only `db/session.credential_session()` sets — so every tenant session sees
            # zero rows. They are listed here for the reason the `platform_*` entries
            # are: one dict answers "what is not tenant-isolated, and why", and a
            # password store absent from that answer is the worst possible omission from
            # it. `tests/authn_rls_test.py` drives the property against real rows.
            "auth_credentials",
            "auth_sessions",
            # D-170's flow tables, joining the same shape rather than a new one: a
            # one-time email token (reset, invitation, bootstrap) and a pending OTP
            # challenge belong to a PERSON mid-authentication, before any tenant context
            # exists to scope them by — which is why neither carries `tenant_id` and why
            # both are FORCEd onto the same `app.auth` GUC. Holding them to the tenant
            # rule would mean inventing a tenant for a subject who has not proved who
            # they are yet.
            "auth_email_tokens",
            "auth_otp_challenges",
        }


# ============================================================================
# check_ledger_immutability — hard rule 4
# ============================================================================


LEDGER_VIOLATIONS: dict[str, str] = {
    "raw sql, one line": 'await session.execute(text("UPDATE usage_events SET amount = 1"))',
    "raw sql, multi-line": (
        'await session.execute(text("""\n    UPDATE usage_events\n    SET amount = 1\n"""))'
    ),
    "raw sql, split string literals": (
        'await session.execute(text(\n    "UPDATE "\n    "usage_events SET amount = 1"\n))'
    ),
    "raw sql, schema-qualified": 'text("DELETE FROM public.usage_events WHERE id = :i")',
    "raw sql, quoted identifier": "text('UPDATE \"usage_events\" SET amount = 1')",
    "raw sql, truncate": 'text("TRUNCATE TABLE consent_ledger")',
    "orm update()": "await session.execute(update(UsageEvent).values(unit_cost_paid=0))",
    "orm delete()": "await session.execute(delete(AuditLogEntry).where(AuditLogEntry.id == i))",
    "orm query().delete()": "session.query(ConsentLedgerEntry).filter_by(id=i).delete()",
    "orm table update()": "await session.execute(UsageEvent.__table__.update().values(x=1))",
    "cascade relationship": (
        'entries = relationship("CreditLedgerEntry", cascade="all, delete-orphan")'
    ),
    "cascade foreign key": (
        "class UsageEvent(Base):\n"
        '    __tablename__ = "usage_events"\n'
        '    call_id: Mapped[UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"))\n'
    ),
}

LEDGER_LEGITIMATE: dict[str, str] = {
    "mutating a non-ledger table": 'text("UPDATE leads SET status = :s")',
    "reading a ledger": 'text("SELECT sum(amount) FROM usage_events WHERE tenant_id = :t")',
    "inserting into a ledger": 'text("INSERT INTO usage_events (id, amount) VALUES (:i, :a)")',
    "a dict update whose name merely mentions usage": "payload.update(usage_event_row)",
    "deleting a non-ledger row": "await session.execute(delete(Lead).where(Lead.id == i))",
    "restrict, not cascade": (
        "class UsageEvent(Base):\n"
        '    __tablename__ = "usage_events"\n'
        '    call_id: Mapped[UUID] = mapped_column(ForeignKey("calls.id", ondelete="RESTRICT"))\n'
    ),
}


class TestLedgerImmutability:
    def test_wiring_knows_the_real_model_classes(self) -> None:
        """The AST scan resolves ORM classes from the live mapper registry, so renaming
        `UsageEvent` cannot silently empty the check."""
        classes = check_ledger_immutability.ledger_model_classes()
        assert set(classes.values()) == set(APPEND_ONLY_TABLES)

    def test_real_tree_has_no_ledger_mutation(self) -> None:
        assert check_ledger_immutability.check_sources() == []

    def test_a_source_scan_that_reads_no_code_refuses_rather_than_passing(
        self, tmp_path: Path
    ) -> None:
        """D-176. Check 1 is a SEARCH: `(root / directory).rglob("*.py")` over a directory
        that has been renamed yields nothing and raises nothing, so `check_sources()`
        returns `[]` and the run prints `... no mutating statements in app code` having
        read no code. The first assertion is that vacuous pass, measured; the rest is the
        refusal seeing it.

        It LOOKED anchored: on an empty tree `check_allowances` fails, but only because
        `BOUNDED_MUTATIONS` happens to hold one entry naming a real file — an exception
        registry whose correct end state is empty. An anchor a correct change can delete
        is not an anchor, which is why the floor is its own section.
        """
        assert check_ledger_immutability.check_sources(root=tmp_path) == [], (
            "the vacuous pass this test exists for"
        )

        blind = check_ledger_immutability.blind_spots(root=tmp_path)
        assert any("does not exist" in failure for failure in blind), blind
        assert any("read 0 source file(s)" in failure for failure in blind), blind

    def test_an_empty_ledger_class_map_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The other half of check 1's left side: the ORM-mutation and cascade-delete
        matchers compare against `ledger_model_classes()`, and an empty map matches
        nothing while looking exactly like a tree with no offenders."""
        monkeypatch.setattr(check_ledger_immutability, "ledger_model_classes", dict)

        assert any("empty class map" in f for f in check_ledger_immutability.blind_spots())

    def test_the_live_tree_clears_the_floor(self) -> None:
        """The control on the control: if this ever fails, the `[]` asserted above is
        unreachable rather than earned."""
        assert check_ledger_immutability.blind_spots() == []

    @pytest.mark.parametrize("label", sorted(LEDGER_VIOLATIONS))
    def test_catches(self, label: str) -> None:
        findings = check_ledger_immutability.scan_source(
            Path("apps/api/billing/service.py"), LEDGER_VIOLATIONS[label]
        )
        assert findings, f"undetected ledger mutation: {label}"

    @pytest.mark.parametrize("label", sorted(LEDGER_LEGITIMATE))
    def test_does_not_cry_wolf(self, label: str) -> None:
        findings = check_ledger_immutability.scan_source(
            Path("apps/api/billing/service.py"), LEDGER_LEGITIMATE[label]
        )
        assert findings == [], f"false positive on legitimate code: {label}"

    def test_wiring_reads_real_triggers(self, engine: Engine) -> None:
        triggers = check_ledger_immutability.fetch_triggers(engine)
        assert {t.table for t in triggers} >= set(APPEND_ONLY_TABLES)
        assert check_ledger_immutability.evaluate_triggers(triggers) == []

    def test_catches_a_missing_trigger(self, engine: Engine) -> None:
        triggers = check_ledger_immutability.fetch_triggers(engine)
        surviving = [t for t in triggers if t.table != "usage_events"]
        failures = check_ledger_immutability.evaluate_triggers(surviving)
        assert any("usage_events" in f for f in failures)

    def test_catches_a_disabled_trigger(self, engine: Engine) -> None:
        """`ALTER TABLE ... DISABLE TRIGGER` leaves the row in `pg_trigger`. Counting
        rows would call that protected."""
        triggers = [
            replace(t, enabled=False) if t.table == "audit_log" else t
            for t in check_ledger_immutability.fetch_triggers(engine)
        ]
        failures = check_ledger_immutability.evaluate_triggers(triggers)
        assert any("audit_log" in f and "does not block" in f for f in failures)

    def test_catches_a_trigger_whose_function_never_raises(self, engine: Engine) -> None:
        triggers = [
            replace(t, raises=False) if t.table == "consent_ledger" else t
            for t in check_ledger_immutability.fetch_triggers(engine)
        ]
        failures = check_ledger_immutability.evaluate_triggers(triggers)
        assert any("consent_ledger" in f and "does not block" in f for f in failures)

    def test_catches_a_trigger_that_only_covers_update(self, engine: Engine) -> None:
        triggers = [
            replace(t, on_delete=False) if t.table == "credit_ledger" else t
            for t in check_ledger_immutability.fetch_triggers(engine)
        ]
        failures = check_ledger_immutability.evaluate_triggers(triggers)
        assert any("credit_ledger" in f and "DELETE" in f for f in failures)

    def test_catches_a_ledger_with_no_truncate_cover(self, engine: Engine) -> None:
        """UPDATE+DELETE cover is not immutability: a FOR EACH ROW trigger has no rows
        to fire per on TRUNCATE, so the verb that empties the table fastest walks past
        it. Migration a2e9f31c605d added the statement-level trigger; this is the
        evaluator's half of noticing it went away."""
        triggers = [
            t
            for t in check_ledger_immutability.fetch_triggers(engine)
            if not (t.table == "usage_events" and t.on_truncate)
        ]
        failures = check_ledger_immutability.evaluate_triggers(triggers)
        assert any("usage_events" in f and "TRUNCATE" in f for f in failures)

    def test_catches_a_trigger_left_in_origin_mode(self, engine: Engine) -> None:
        """`ENABLE ORIGIN` (the default) stops firing under
        `SET session_replication_role = replica` — a plain SET, no DDL, no schema diff.
        A trigger a session variable can switch off is not an immutability guarantee."""
        triggers = [
            replace(t, always=False) if t.table == "audit_log" else t
            for t in check_ledger_immutability.fetch_triggers(engine)
        ]
        failures = check_ledger_immutability.evaluate_triggers(triggers)
        assert any("audit_log" in f and "ENABLE ORIGIN" in f for f in failures)

    def test_the_database_function_actually_refuses(self, engine: Engine) -> None:
        """End-to-end proof that the catalog facts mean what they say: attach the REAL
        `calevate_forbid_mutation` to a temp table and watch it refuse. Everything runs
        inside a transaction that is rolled back, so no shared state is touched."""
        from sqlalchemy.exc import DatabaseError

        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(
                    text("CREATE TEMP TABLE guardrail_probe (id int) ON COMMIT DROP")
                )
                connection.execute(
                    text(
                        "CREATE TRIGGER guardrail_probe_append_only "
                        "BEFORE UPDATE OR DELETE ON guardrail_probe "
                        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
                    )
                )
                connection.execute(text("INSERT INTO guardrail_probe VALUES (1)"))
                mutations = ("UPDATE guardrail_probe SET id = 2", "DELETE FROM guardrail_probe")
                for statement in mutations:
                    savepoint = connection.begin_nested()
                    with pytest.raises(DatabaseError):
                        connection.execute(text(statement))
                    savepoint.rollback()
            finally:
                transaction.rollback()


# ============================================================================
# check_redaction_exposure — hard rule 5
# ============================================================================


def _add_model(spec: dict[str, Any], name: str, properties: dict[str, Any]) -> None:
    spec.setdefault("components", {}).setdefault("schemas", {})[name] = {
        "type": "object",
        "properties": properties,
    }


class TestRedactionExposure:
    def test_live_schema_exposes_no_raw_pii(self, live_spec: dict[str, Any]) -> None:
        assert check_redaction_exposure.check(live_spec) == []

    def test_exemption_registries_are_not_stale(self, live_spec: dict[str, Any]) -> None:
        assert check_redaction_exposure.check_registry_freshness(live_spec) == []

    def test_allowlisted_routes_are_role_checked_and_audited(self) -> None:
        facts = check_redaction_exposure.route_facts()
        assert check_redaction_exposure.check_allowlist(facts) == []

    def test_catches_a_new_transcript_field_on_an_existing_response_model(
        self, live_spec: dict[str, Any]
    ) -> None:
        """Rule 1, unmoved by D-436: transcript text is banned off an allowlisted route,
        and a role check does not buy it. `/v1/calls` is `calls:read` and that is exactly
        the reader DATA-MODEL §2 says never sees raw transcript."""
        spec = copy.deepcopy(live_spec)
        spec["components"]["schemas"]["CallSummaryOut"]["properties"]["transcript_text"] = {
            "type": "string"
        }
        offenders = check_redaction_exposure.check(spec)
        assert any("CallSummaryOut" in o and "transcript_text" in o for o in offenders)

    def test_a_contact_field_on_a_role_checked_response_is_permitted(
        self, live_spec: dict[str, Any]
    ) -> None:
        """Rule 2, and it is pinned here as deliberately as the ban it replaced.

        This test asserted the OPPOSITE until D-436: `from_e164` on `CallSummaryOut` was
        an offender, and that is what made a lead-capture product unable to yield a lead
        — the calls list could not print the number of the person who rang. A phone
        number on a response behind a declared permission is now the product working.

        The permission is the whole condition, and it is not decoration: `core.rbac`
        refuses to boot the app when a route declares one it does not enforce. The
        companion is `test_catches_a_phone_added_to_the_intake_receipt`, where nobody
        declares anything and the same field is still reported.
        """
        spec = copy.deepcopy(live_spec)
        spec["components"]["schemas"]["CallSummaryOut"]["properties"]["from_e164"] = {
            "type": "string"
        }
        offenders = check_redaction_exposure.check(spec)
        assert not any("from_e164" in o for o in offenders)
        # And the calls list really is the role-checked route this claim rests on.
        assert live_spec["paths"]["/v1/calls"]["get"]["x-calevate-permission"] == "calls:read", (
            "if this route stops declaring a permission the allowance above evaporates"
        )

    def test_catches_raw_text_two_levels_down(self, live_spec: dict[str, Any]) -> None:
        """Nesting was the hole: the old check only inspected models `$ref`-ed directly
        by the response, so a raw field one model deeper was invisible."""
        spec = copy.deepcopy(live_spec)
        _add_model(spec, "TurnAnnotationOut", {"raw_text": {"type": "string"}})
        spec["components"]["schemas"]["CallSummaryOut"]["properties"]["annotation"] = {
            "$ref": "#/components/schemas/TurnAnnotationOut"
        }
        offenders = check_redaction_exposure.check(spec)
        assert any("TurnAnnotationOut" in o for o in offenders)

    def test_catches_the_call_summary_when_its_exemption_is_taken_away(
        self, live_spec: dict[str, Any]
    ) -> None:
        """`summary` is transcript-DERIVED prose, and this check had never heard of the
        name — so a `staff` reader could pull a caller's spoken phone number off the
        calls list through it while the guardrail reported OK
        (tests/call_summary_redaction_test.py).

        The mutation here is the exemption, not the schema: the field is legitimately
        declared and legitimately named, and the ONLY thing keeping the check green is
        the `KNOWN_SAFE_FIELDS` entry saying the value has been through `redact()`.
        Removing it must bring the field back into view, or the entry is load-bearing
        for nothing and the next `summary`-shaped field ships unseen.
        """
        offenders = check_redaction_exposure.check(live_spec, safe_fields={})
        assert any("CallSummaryOut" in o and "summary" in o for o in offenders)
        assert any("CallDetailOut" in o and "summary" in o for o in offenders)

    def test_a_safe_field_exemption_does_not_blind_the_rest_of_its_model(
        self, live_spec: dict[str, Any]
    ) -> None:
        """The reason exemptions are `Model.field` and never `Model`. `TranscriptTurnOut`
        used to be exempt WHOLESALE for the sake of one field, so a second raw field
        added beside it would have shipped green.

        The mutation is `raw_text` rather than the `caller_e164` it used to be: D-436
        made a contact field on a role-checked response legitimate, so a phone number
        here would prove nothing about the exemption. A raw transcript column is the
        thing this model could plausibly grow and must never ship.
        """
        spec = copy.deepcopy(live_spec)
        spec["components"]["schemas"]["TranscriptTurnOut"]["properties"]["raw_text"] = {
            "type": "string"
        }
        offenders = check_redaction_exposure.check(spec)
        assert any("TranscriptTurnOut" in o and "raw_text" in o for o in offenders)
        assert not any("'text'" in o for o in offenders), "the exempt field stays exempt"

    def test_catches_a_new_freeform_dict_passthrough(self, live_spec: dict[str, Any]) -> None:
        """`dict[str, Any]` is an undeclared response model: whatever the query put in
        it ships, redaction included."""
        spec = copy.deepcopy(live_spec)
        spec["components"]["schemas"]["CallSummaryOut"]["properties"]["engine_payload"] = {
            "type": "object",
            "additionalProperties": True,
        }
        offenders = check_redaction_exposure.check(spec)
        assert any("CallSummaryOut.engine_payload" in o for o in offenders)

    def test_catches_a_stale_allowlist_entry(self, live_spec: dict[str, Any]) -> None:
        spec = copy.deepcopy(live_spec)
        spec["paths"].pop("/v1/leads/export.csv")
        failures = check_redaction_exposure.check_registry_freshness(spec)
        assert any("/v1/leads/export.csv" in f for f in failures)

    def test_catches_an_allowlisted_route_that_lost_its_role_check(self) -> None:
        """The whole point of the allowlist is the claim "role-checked AND audited".
        Only the raw-transcript route is weakened here — the rest of the app keeps its
        permissions, so this cannot pass via the blind-extraction escape hatch."""
        facts = [
            replace(route, enforced=frozenset())
            if route.path in check_redaction_exposure.ALLOWED_ROUTES
            else route
            for route in check_redaction_exposure.route_facts()
        ]
        failures = check_redaction_exposure.check_allowlist(facts)
        assert any("decoration" in f for f in failures)

    def test_catches_an_allowlisted_route_that_lost_its_audit_write(self) -> None:
        stripped = "async def handler():\n    return await service.get_call(session, call_id)"
        facts = [
            replace(route, source=stripped)
            if route.path in check_redaction_exposure.ALLOWED_ROUTES
            else route
            for route in check_redaction_exposure.route_facts()
        ]
        failures = check_redaction_exposure.check_allowlist(facts)
        assert any("without writing audit_log" in f for f in failures)

    def test_says_so_when_permission_extraction_goes_blind(self) -> None:
        """If `requires()` is refactored and the closure walk stops finding anything,
        this check must announce that it is blind rather than pass."""
        facts = [replace(r, enforced=frozenset()) for r in check_redaction_exposure.route_facts()]
        failures = check_redaction_exposure.check_allowlist(facts)
        assert any("this check is blind" in f for f in failures)

    def test_the_subject_export_is_inspected_rather_than_skipped(
        self, live_spec: dict[str, Any]
    ) -> None:
        """The DPDP export is on ALLOWED_ROUTES, and that used to mean "never looked at
        again". It is the one response whose payload is an entire named human being, so
        the allowance is scoped to `phone_e164` and the walk stays ON: a raw field added
        beside it must still be reported.
        """
        spec = copy.deepcopy(live_spec)
        spec["components"]["schemas"]["SubjectExportCallOut"]["properties"]["to_e164"] = {
            "type": "string"
        }
        offenders = check_redaction_exposure.check(spec)
        assert any("SubjectExportCallOut" in o and "to_e164" in o for o in offenders)
        assert not any("phone_e164" in o for o in offenders), "the allowed field stays allowed"

    def test_the_subject_exports_own_number_is_allowed_only_because_it_is_declared(
        self, live_spec: dict[str, Any]
    ) -> None:
        """The mutation is the allowance, not the schema. `phone_e164` is legitimately in
        that document — it is the subject's own number, echoed back so they can check the
        file is about them — and the ONLY thing keeping the check green is the field set
        on its `RawDisclosure`. Narrow it and the field must come back into view, or the
        entry is load-bearing for nothing."""
        narrowed = {
            path: replace(disclosure, fields=frozenset())
            if path == "/v1/compliance/subject-export"
            else disclosure
            for path, disclosure in check_redaction_exposure.ALLOWED_ROUTES.items()
        }
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(check_redaction_exposure, "ALLOWED_ROUTES", narrowed)
            offenders = check_redaction_exposure.check(live_spec)
        assert any("SubjectExportOut" in o and "phone_e164" in o for o in offenders)
        assert any("SubjectExportLeadOut" in o and "phone_e164" in o for o in offenders)

    def test_catches_a_raw_field_added_to_the_lead_source_dry_run(
        self, live_spec: dict[str, Any]
    ) -> None:
        """The dry run is INSPECTED, and this is the proof rather than the claim.

        `POST /v1/lead-sources/{id}/test` answered `dict[str, Any]` while holding a
        normalized caller number in scope two lines above its `return` — so it was not a
        response this check judged safe, it was one the check could not see, exactly like
        D-71's subject export. If this test stops failing, the route has gone back to a
        bare dict or the model has stopped being reachable from the response.

        The mutation is `transcript_text` rather than the `phone_e164` it used to be, and
        the swap is D-436 rather than a weakening: this route declares `leads:manage`, so
        a contact field on it is now permitted — showing the operator the number their
        mapping produced is the entire point of a dry run. What the route may still never
        do is grow a transcript column, and that is what is asserted.
        """
        spec = copy.deepcopy(live_spec)
        spec["components"]["schemas"]["LeadSourceDryRunStepOut"]["properties"][
            "transcript_text"
        ] = {"type": "string"}
        offenders = check_redaction_exposure.check(spec)
        assert any(
            "/v1/lead-sources/{webhook_id}/test" in o and "transcript_text" in o for o in offenders
        )

    def test_catches_a_phone_added_to_the_intake_receipt(self, live_spec: dict[str, Any]) -> None:
        """The same proof for the machine-facing half. `POST /hooks/v1/ingest/{id}` has
        the sender's ENTIRE payload in scope of its `return`, and the guardrail walks
        `/hooks` paths exactly like `/v1` ones — asserted, because a check that silently
        skipped the unauthenticated-by-session surface would be blind where it matters."""
        spec = copy.deepcopy(live_spec)
        spec["components"]["schemas"]["IngestAckOut"]["properties"]["caller_e164"] = {
            "type": "string"
        }
        offenders = check_redaction_exposure.check(spec)
        assert any("/hooks/v1/ingest/{webhook_id}" in o and "caller_e164" in o for o in offenders)

    def test_the_two_field_classes_are_pinned(self) -> None:
        """WHICH RULE governs a field name costs a diff here as well as in the script.

        The registries were one set under one rule until D-436, and the split is the
        load-bearing part: moving a name from `RAW_TRANSCRIPT_FIELDS` to
        `CONTACT_PII_FIELDS` downgrades it from "never, without an audit row" to
        "whenever a permission is declared", which is a policy change wearing the
        clothes of a tidy-up. `summary` is the name to watch — it READS like contact
        metadata and is model-written prose about a conversation.
        """
        assert set(check_redaction_exposure.CONTACT_PII_FIELDS) == {
            "phone_e164",
            "from_e164",
            "to_e164",
            "caller_e164",
            "phone",
            "phone_number",
            "email",
        }
        assert set(check_redaction_exposure.RAW_TRANSCRIPT_FIELDS) == {
            "text",
            "raw_text",
            "text_raw",
            "transcript_text",
            "summary",
            "call_summary",
            "recording_url",
        }
        assert not (
            check_redaction_exposure.CONTACT_PII_FIELDS
            & check_redaction_exposure.RAW_TRANSCRIPT_FIELDS
        ), "a name in both sets would be governed by whichever branch ran first"

    def test_exemption_registries_are_pinned(self) -> None:
        """Every raw-PII exemption costs a diff here as well as in the script."""
        assert set(check_redaction_exposure.ALLOWED_ROUTES) == {
            "/v1/calls/{call_id}/transcript/raw",
            "/v1/leads/export.csv",
            # The retained delivery body (D-23): the CRM payload we POSTed, byte for
            # byte. `calls:read_raw` + an audit row, which `check_allowlist` verifies
            # against the live app rather than taking from this comment.
            "/v1/integrations/deliveries/{delivery_id}/payload",
            # The DPDP subject access document. Field-SCOPED rather than a whole-path
            # skip (`RawDisclosure.fields`), so the rest of the document stays inspected.
            "/v1/compliance/subject-export",
        }
        assert {
            path
            for path, disclosure in check_redaction_exposure.ALLOWED_ROUTES.items()
            if disclosure.fields is not None
        } == {"/v1/compliance/subject-export"}, (
            "a whole-path skip is the widest form this registry has; adding one is a "
            "decision to stop inspecting a response model entirely"
        )
        assert set(check_redaction_exposure.KNOWN_SAFE_FIELDS) == {
            "TranscriptTurnOut.text",
            "CallSummaryOut.summary",
            "CallDetailOut.summary",
            # The assistant's re-summarise (D-127). It is the ONE entry in this registry
            # whose value cannot contain unredacted transcript text by CONSTRUCTION
            # rather than by a pass applied on the way out: the model is handed
            # `transcript_turns.text_redacted` and `run_assist` refuses input that
            # `redact()` still changes, so there is no unredacted digit in scope for it
            # to copy. The output goes through `crm.service.redacted_summary` anyway,
            # which is what makes its entry say the same sentence as `CallDetailOut`'s —
            # and `tests/call_assist_test.py` drives BOTH halves (the bytes sent to
            # Vertex, and a model that invents a phone-shaped run in its answer).
            "CallAssistOut.summary",
            "SubjectExportTurnOut.text",
            "SubjectExportCallOut.summary",
        }
        assert set(check_redaction_exposure.ACKNOWLEDGED_PASSTHROUGH) == {
            # ACTIONS feature: operator-authored tool config, a saved credential's
            # non-secret metadata, and the reply to an operator-run test invocation — all
            # free-form by necessity, none from a live call. See check_redaction_exposure.py.
            "ToolOut.config",
            "CredentialOut.non_secret",
            "TestActionOut.payload",
            "LeadOut.data",
            "CallDetailOut.extraction",
            "SubjectExportLeadOut.data",
        }


# ============================================================================
# check_env_parity
# ============================================================================


class TestEnvParity:
    def test_wiring_parses_the_real_example_file(self) -> None:
        declared, duplicates = check_env_parity.example_keys(REPO_ROOT / ".env.example")
        assert "database_url" in declared and "redis_url" in declared
        assert duplicates == []

    def test_catches_a_key_only_in_the_example_file(self) -> None:
        declared, _ = check_env_parity.example_keys(REPO_ROOT / ".env.example")
        from calevate_shared.config import Settings

        failures = check_env_parity.evaluate(
            declared | {"whatsapp_token"}, set(Settings.model_fields), {}
        )
        assert any("whatsapp_token" in f and "not Settings" in f for f in failures)

    def test_catches_a_key_only_in_settings(self) -> None:
        declared, _ = check_env_parity.example_keys(REPO_ROOT / ".env.example")
        from calevate_shared.config import Settings

        fields = set(Settings.model_fields) | {"whatsapp_token"}
        failures = check_env_parity.evaluate(declared, fields, {})
        # The message changed when the console became a second place a key can be
        # declared (PLATFORM-CONFIG §12): the failure is now "in neither", which is the
        # claim that was always doing the work.
        assert any("whatsapp_token" in f and "not in .env.example" in f for f in failures)

    def test_catches_a_worker_reading_the_environment_directly(self) -> None:
        """The direction the old check had no way to see: a key that exists in neither
        place because a job reads it straight off `os.environ`."""
        from calevate_shared.config import Settings

        declared, _ = check_env_parity.example_keys(REPO_ROOT / ".env.example")
        reads = {"WHATSAPP_TOKEN": ["apps/workers/notify.py:42"]}
        failures = check_env_parity.evaluate(declared, set(Settings.model_fields), reads)
        assert any("WHATSAPP_TOKEN" in f and "never fails fast" in f for f in failures)

    def test_catches_a_duplicate_key(self) -> None:
        from calevate_shared.config import Settings

        declared, _ = check_env_parity.example_keys(REPO_ROOT / ".env.example")
        failures = check_env_parity.evaluate(
            declared, set(Settings.model_fields), {}, duplicates=["redis_url"]
        )
        assert any("declared twice" in f for f in failures)

    def test_finds_env_reads_in_source(self, tmp_path: Path) -> None:
        """The AST scan, exercised on all three spellings."""
        (tmp_path / "apps").mkdir()
        (tmp_path / "apps" / "job.py").write_text(
            "import os\n"
            'a = os.getenv("ALPHA")\n'
            'b = os.environ["BETA"]\n'
            'c = os.environ.get("GAMMA")\n'
        )
        found = check_env_parity.direct_env_reads(tmp_path)
        assert set(found) == {"ALPHA", "BETA", "GAMMA"}

    def test_settings_reads_in_the_repo_are_accounted_for(self) -> None:
        """Wiring: the scan runs over the real tree and every key it finds is either a
        Settings field or a named infra variable."""
        from calevate_shared.config import Settings

        fields = set(Settings.model_fields)
        for key in check_env_parity.direct_env_reads():
            assert (
                key in check_env_parity.INFRA_ENV_KEYS
                # Operator tooling that runs outside every deployable (the restore
                # drill), each entry carrying the reason it is not application config.
                or key in check_env_parity.DRILL_ENV_KEYS
                # Variables a third-party SDK resolves for itself (botocore's AWS_*),
                # which a Settings field could shadow but never replace.
                or key in check_env_parity.SDK_ENV_KEYS
                or key.lower() in fields
            ), key

    def test_an_sdk_key_is_exempt_and_an_unregistered_one_is_not(self) -> None:
        """The exemption must be the REGISTRY, never the `AWS_` prefix.

        A pattern match would exempt every future `AWS_*` variable by accident — including
        one somebody adds for our own configuration, which is exactly the "config that
        never fails fast" this direction exists to catch. So the registry is a list, and
        an unlisted sibling of a listed key still fails.
        """
        from calevate_shared.config import Settings

        declared, _ = check_env_parity.example_keys(REPO_ROOT / ".env.example")
        fields = set(Settings.model_fields)

        exempt = check_env_parity.evaluate(
            declared, fields, {"AWS_REGION": ["apps/workers/storage.py:1"]}
        )
        assert not any("AWS_REGION" in failure for failure in exempt), exempt

        unregistered = check_env_parity.evaluate(
            declared, fields, {"AWS_ENDPOINT_URL_S3": ["apps/workers/storage.py:1"]}
        )
        assert any(
            "AWS_ENDPOINT_URL_S3" in failure and "never fails fast" in failure
            for failure in unregistered
        ), unregistered

    def test_a_search_that_looks_at_nothing_refuses(self, tmp_path: Path) -> None:
        """D-176. The third direction is a SEARCH, and `rglob` over a directory that has
        been renamed yields nothing without raising — so `0 direct environment reads
        accounted for` was printed beside the word OK. Both halves are pinned: a missing
        scan root, and a matcher that has stopped recognising the read."""
        assert check_env_parity.direct_env_reads(tmp_path) == {}, "the scan sees an empty tree"

        missing_root = check_env_parity.blind_spots(root=tmp_path)
        assert any("does not exist" in failure for failure in missing_root), missing_root
        assert any("AST matcher" in failure for failure in check_env_parity.blind_spots(reads={}))
        assert check_env_parity.blind_spots(reads=check_env_parity.direct_env_reads()) == []

    def test_every_sdk_exemption_carries_a_reason(self) -> None:
        """An entry with an empty reason is an exemption nobody has to justify, which is
        how a registry turns into a wildcard one line at a time."""
        for key, reason in check_env_parity.SDK_ENV_KEYS.items():
            assert len(reason) > 60, f"{key}'s exemption does not say why"


# ============================================================================
# check_config_applies — the registry it iterates is derived, so it can empty itself
# ============================================================================


class TestConfigApplies:
    """D-176. Four of this check's five sections iterate `classified_keys()`; iterating
    an empty tuple returns `[]` from each, which is indistinguishable from a clean run.
    `managed_fields()` is computed from `Settings` BY EXCLUSION, so nobody has to edit a
    list for that to happen — which is why the refusal is a section rather than a comment.
    """

    def test_the_live_registries_are_populated(self) -> None:
        assert check_config_applies.blind_spots() == []

    def test_an_empty_managed_set_is_refused_rather_than_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(check_config_applies, "managed_fields", tuple)

        assert check_config_applies.check_every_key_is_classified() == [], (
            "the vacuous pass: with nothing managed, the classification check has nothing "
            "to complain about"
        )
        assert check_config_applies.check_bounds() == []
        assert any(
            "console-managed setting" in failure for failure in check_config_applies.blind_spots()
        )

    def test_an_empty_credential_set_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(check_config_applies, "manageable_secret_keys", tuple)

        assert any("credential(s)" in f for f in check_config_applies.blind_spots())


# ============================================================================
# check_openapi_fresh
# ============================================================================


class TestOpenApiFresh:
    def test_wiring_shapes_the_live_app(self, live_spec: dict[str, Any]) -> None:
        shape = check_openapi_fresh._shape(live_spec)
        assert shape["paths"] and shape["schemas"]
        assert shape["paths"]["/v1/calls/{call_id}/transcript/raw"]["get"]["permission"] == (
            "calls:read_raw"
        )

    def test_catches_a_permission_change_with_no_path_change(
        self, live_spec: dict[str, Any]
    ) -> None:
        """The exact hole: downgrading the raw-transcript endpoint from `calls:read_raw`
        to `calls:read` changes no path and no property name, so a shape that compares
        only those reports a fresh snapshot."""
        weakened = copy.deepcopy(live_spec)
        route = weakened["paths"]["/v1/calls/{call_id}/transcript/raw"]["get"]
        route["x-calevate-permission"] = "calls:read"
        assert check_openapi_fresh._shape(live_spec) != check_openapi_fresh._shape(weakened)

    def test_catches_a_property_type_change(self, live_spec: dict[str, Any]) -> None:
        changed = copy.deepcopy(live_spec)
        changed["components"]["schemas"]["CallSummaryOut"]["properties"]["duration_s"] = {
            "type": "string"
        }
        assert check_openapi_fresh._shape(live_spec) != check_openapi_fresh._shape(changed)

    # --- the SECOND half of the generated client -------------------------------------
    #
    # A generated client is two files and only one was guarded: `openapi.json` was compared
    # against the live app, and `schema.d.ts` — the file the frontend actually compiles
    # against — was compared against nothing. Tonight's frontend was `tsc`-green for hours
    # against a contract the server had stopped serving, and two `lib/api` modules aliased
    # schema names the generator no longer emitted. `tsc` cannot see it: a stale `.d.ts` is
    # a perfectly consistent set of types, just not the server's.

    def test_the_generated_client_is_in_step_with_the_snapshot(
        self, live_spec: dict[str, Any]
    ) -> None:
        generated = check_openapi_fresh.GENERATED.read_text(encoding="utf-8")
        assert check_openapi_fresh.generated_drift(live_spec, generated) == []

    def test_catches_a_name_the_generator_never_emitted(self, live_spec: dict[str, Any]) -> None:
        """The shipped defect's shape: the snapshot gained a schema and nobody re-ran
        `gen:api`, so the frontend compiles against a type that no longer describes the
        wire."""
        generated = check_openapi_fresh.GENERATED.read_text(encoding="utf-8")
        missing = "CallSummaryOut"
        assert f"        {missing}:" in generated, "fixture premise: the name is emitted"
        drift = check_openapi_fresh.generated_drift(
            live_spec, generated.replace(f"        {missing}:", "        _RenamedAway:", 1)
        )
        assert any(f"+ schemas {missing} (in openapi.json" in line for line in drift), drift
        assert any("- schemas _RenamedAway (in schema.d.ts" in line for line in drift), drift

    def test_catches_an_operation_id_the_snapshot_dropped(self, live_spec: dict[str, Any]) -> None:
        """`operations` is compared too, not just paths and schemas — a renamed handler
        keeps its path and moves its operationId, which is the half a path diff misses."""
        generated = check_openapi_fresh.GENERATED.read_text(encoding="utf-8")
        shrunk = copy.deepcopy(live_spec)
        for methods in shrunk["paths"].values():
            for method, operation in methods.items():
                if method in check_openapi_fresh.METHODS and isinstance(operation, dict):
                    operation.pop("operationId", None)
        drift = check_openapi_fresh.generated_drift(shrunk, generated)
        assert any("- operations " in line for line in drift), drift

    def test_a_parser_that_stopped_matching_is_named_as_a_parser_bug(
        self, live_spec: dict[str, Any]
    ) -> None:
        """openapi-typescript's output format is the generator's to change on an upgrade,
        and a parser that quietly stopped matching would report EVERY name as missing —
        which reads exactly like a stale client and sends the next person to `gen:api` for
        a bug that is in this checker. The two have completely different fixes, so the
        checker has to tell them apart; a guardrail that cries wolf gets deleted."""
        generated = check_openapi_fresh.GENERATED.read_text(encoding="utf-8")
        moved = generated.replace("    schemas: {", "    schemaz: {", 1)
        drift = check_openapi_fresh.generated_drift(live_spec, moved)
        assert any("not a stale client" in line for line in drift), drift
        assert not any("+ schemas " in line for line in drift), (
            "a moved block header must not be reported name-by-name as a stale client",
            drift[:3],
        )

    def test_the_block_reader_does_not_swallow_nested_keys(self) -> None:
        """`_keys_at` stops at the closing brace rather than running to end-of-file — a
        reader that did not would fold every nested property name into the block's own set
        and then report hundreds of phantom extras."""
        text = "\n".join(
            [
                "export interface paths {",
                '    "/v1/calls": {',
                "        get: {",
                "            nested_should_not_count: never;",
                "        };",
                "    };",
                "}",
                "export interface operations {",
                "    other_block: never;",
                "}",
            ]
        )
        found = check_openapi_fresh._keys_at(text, "export interface paths {", 4)
        assert found == {"/v1/calls"}, found

    def test_catches_a_new_query_parameter(self, live_spec: dict[str, Any]) -> None:
        changed = copy.deepcopy(live_spec)
        changed["paths"]["/v1/calls"]["get"].setdefault("parameters", []).append(
            {"name": "include_raw", "in": "query", "required": False, "schema": {"type": "boolean"}}
        )
        assert check_openapi_fresh._shape(live_spec) != check_openapi_fresh._shape(changed)

    def test_catches_a_required_field_change(self, live_spec: dict[str, Any]) -> None:
        changed = copy.deepcopy(live_spec)
        schema = changed["components"]["schemas"]["CallSummaryOut"]
        schema["required"] = [*schema.get("required", []), "summary"]
        assert check_openapi_fresh._shape(live_spec) != check_openapi_fresh._shape(changed)

    def test_catches_a_removed_route(self, live_spec: dict[str, Any]) -> None:
        changed = copy.deepcopy(live_spec)
        changed["paths"].pop("/v1/leads/export.csv")
        assert check_openapi_fresh._shape(live_spec) != check_openapi_fresh._shape(changed)

    def test_ignores_prose_and_validation_bounds(self, live_spec: dict[str, Any]) -> None:
        """Calibration, not laziness: a reworded summary or a changed `le=` produces
        byte-identical TypeScript. A guardrail that fires on those trains people to
        regenerate without reading the diff."""
        cosmetic = copy.deepcopy(live_spec)
        operation = cosmetic["paths"]["/v1/calls"]["get"]
        operation["summary"] = "Totally reworded summary"
        operation["description"] = "A description nobody had written before"
        for parameter in operation.get("parameters", []):
            if parameter["name"] == "limit":
                parameter["schema"]["maximum"] = 999
        assert check_openapi_fresh._shape(live_spec) == check_openapi_fresh._shape(cosmetic)

    def test_snapshot_file_is_valid_json_at_the_expected_path(self) -> None:
        assert check_openapi_fresh.SNAPSHOT.exists()
        json.loads(check_openapi_fresh.SNAPSHOT.read_text(encoding="utf-8"))


# ============================================================================
# The Makefile is part of the guardrail surface
# ============================================================================


class TestMakefileWiring:
    """`make guardrails` IS the gate developers run. A target that cannot run, or that
    make decides is already up to date, is a gate that reports success without work."""

    def _makefile(self) -> str:
        return (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    def test_every_target_is_phony(self) -> None:
        import re

        text = self._makefile()
        phony: set[str] = set()
        for match in re.finditer(r"^\.PHONY:((?:[^\n\\]|\\\n)*)", text, re.MULTILINE):
            phony |= set(match.group(1).replace("\\\n", " ").split())
        targets = {m.group(1) for m in re.finditer(r"^([a-zA-Z][\w-]*):", text, re.MULTILINE)}
        assert targets - phony == set(), "a non-phony target is a no-op waiting to happen"

    def _makefile_recipes(self) -> dict[str, tuple[list[str], list[str]]]:
        """`{target: (prerequisites, recipe lines)}` — the Makefile as make reads it.

        A recipe line begins with a TAB; everything else is a target line, a variable or
        prose. A tab followed by `#` is a comment INSIDE a recipe, which make passes to
        the shell as a comment and which runs nothing. Both are dropped, for the reason
        in `test_every_guardrail_script_runs_in_both_gates`.

        KEYED BY TARGET rather than flattened, because `in the Makefile` and `in a target
        `make check` reaches` are different questions and only the second one is a gate.
        `restore-drill`, `pilot` and `seed-dev` all have recipes and none of them runs on
        anybody's push.
        """
        import re

        recipes: dict[str, tuple[list[str], list[str]]] = {}
        current: str | None = None
        for line in self._makefile().splitlines():
            if line.startswith("\t"):
                body = line.lstrip("\t")
                if current is not None and not body.startswith("#"):
                    recipes[current][1].append(body)
                continue
            # `:(?!=)` excludes `NAME := value`, which is an assignment and has no
            # recipe. Anything after a `#` on a target line is make's comment, and that
            # includes the `## help text` this file's targets carry — so the
            # prerequisites are read from the part before it, never from the sentence
            # describing the target.
            match = re.match(r"^([a-zA-Z][\w-]*):(?!=)(.*)$", line)
            if match:
                current = match.group(1)
                recipes.setdefault(current, ([], []))
                recipes[current][0].extend(match.group(2).split("#")[0].split())
            elif line.strip():
                current = None
        return recipes

    def _commands_reachable_from(self, goal: str) -> str:
        """Every recipe line `make <goal>` would run, prerequisites included.

        Transitive, because `check` runs nothing itself: it is six prerequisites, and a
        flat search of the file cannot tell a guard that runs on every push from one
        parked in a target nobody invokes.
        """
        recipes = self._makefile_recipes()
        seen: set[str] = set()
        pending = [goal]
        commands: list[str] = []
        while pending:
            target = pending.pop()
            if target in seen or target not in recipes:
                continue
            seen.add(target)
            prerequisites, body = recipes[target]
            commands.extend(body)
            pending.extend(prerequisites)
        return "\n".join(commands)

    def _makefile_commands(self) -> str:
        """Every recipe line in the file, whatever target carries it."""
        return "\n".join(line for _, (_, body) in self._makefile_recipes().items() for line in body)

    def _workflow_commands(self) -> str:
        """Every `run:` scalar in the workflow, from the parsed YAML.

        Parsed rather than grepped so that a script named in a step's `name:`, in a `#`
        comment, or in this file's own prose cannot stand in for a step that executes it.
        """
        import yaml

        document = yaml.safe_load(
            (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        )
        return "\n".join(
            str(step["run"])
            for job in document["jobs"].values()
            for step in job.get("steps", [])
            if isinstance(step, dict) and "run" in step
        )

    def test_every_guardrail_script_runs_in_both_gates(self) -> None:
        """Globbed off `scripts/`, never typed out here.

        The hand-written list this replaced named five checks and stayed green while
        `check_wiring` ran in `make guardrails` and in NO CI step — the local gate
        enforced a rule the gate that blocks merge did not, which is the one direction
        that matters. A list that grows itself cannot fall behind: a new `check_*.py` is
        in this test the moment the file exists, and it fails until both gates run it.

        **AND IT NOW LOOKS AT COMMANDS RATHER THAN AT FILE TEXT (D-176).** It used to ask
        whether `scripts.check_x` appeared ANYWHERE in the Makefile and anywhere in the
        workflow — and both files are heavily commented, several of those comments naming
        the very scripts beside them. A check deleted from the `guardrails` recipe but left
        in the comment that explains it, or a CI step whose `name:` says what its `run:` no
        longer does, satisfied every assertion here. That is the reference implementation's
        own defect in miniature — evidence produced by the thing being audited — inside the
        test whose job is to notice it. The two accessors above reduce each file to the
        lines a shell actually executes.
        """
        scripts = sorted(path.stem for path in (REPO_ROOT / "scripts").glob("check_*.py"))
        assert len(scripts) >= 5, "the guardrail pack cannot have shrunk to nothing"
        makefile = self._commands_reachable_from("check")
        workflow = self._workflow_commands()
        for script in scripts:
            assert f"scripts.{script}" in makefile, (
                f"{script} runs in no target `make check` reaches. A mention in a comment "
                "is not a gate, and neither is a recipe line parked in `restore-drill`, "
                "`pilot` or `seed-dev` — none of those runs on anybody's push."
            )
            assert f"scripts.{script}" in workflow, (
                f"{script} is in no CI step's `run:`. A step name that mentions it is not a "
                "step that runs it."
            )
        assert "lint-imports" in makefile and "lint-imports" in workflow

    def test_every_guardrail_script_is_named_in_the_catalogue(self) -> None:
        """ENGINEERING-PRACTICES §2 is where somebody looks up what guards what.

        It listed twelve of the twenty scripts when D-176 audited them — the eight it had
        never heard of are exactly the ones nobody would think to run, argue with, or
        notice the absence of. Keyed on the script PATH rather than the `check:` name so a
        row cannot satisfy this with a name the tree does not use.
        """
        catalogue = (REPO_ROOT / "docs" / "ENGINEERING-PRACTICES.md").read_text(encoding="utf-8")
        missing = [
            path.name
            for path in sorted((REPO_ROOT / "scripts").glob("check_*.py"))
            if f"scripts/{path.name}" not in catalogue
        ]
        assert missing == [], (
            f"{missing} run in both gates and appear in no row of the guardrail catalogue. "
            "A check the docs do not name is one the next reader cannot argue with."
        )

    def test_the_command_accessors_are_not_reading_everything(self) -> None:
        """The accessors above are the load-bearing half of the test before this one, so
        they get their own control: a string that appears ONLY in a comment in each file
        must not survive the reduction. Without this, a bug that returned the whole file
        would restore the weakness silently and every assertion would still pass."""
        assert "P4.3" in self._makefile(), "the Makefile comment this control keys on moved"
        assert "P4.3" not in self._makefile_commands()

        # And the reduction the assertion above actually runs against. `restore-drill` is
        # a real target with a real recipe that `make check` does not reach, so it is the
        # control for the narrowing: if `_commands_reachable_from` ever degrades into "the
        # whole file", this line is what notices.
        assert "scripts.restore_drill" in self._makefile_commands()
        assert "scripts.restore_drill" not in self._commands_reachable_from("check")

        raw = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert "Guardrail: engine isolation" in raw, "the CI step name this control keys on moved"
        assert "Guardrail: engine isolation" not in self._workflow_commands()

    def _workflow_steps(self) -> list[dict[str, Any]]:
        """Every step of every job, parsed. `_workflow_commands` above answers "what runs";
        this answers "under what condition", which is the half a `run:` string cannot."""
        import yaml

        document = yaml.safe_load(
            (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        )
        return [
            step
            for job in document["jobs"].values()
            for step in job.get("steps", [])
            if isinstance(step, dict)
        ]

    def test_no_guardrail_step_is_skipped_by_an_earlier_failure(self) -> None:
        """A CI step with no `if:` does not run once anything before it has failed.

        THIS IS A REGISTRATION THAT IS NOT AN ENFORCEMENT, and it is invisible from every
        green run — which is why it survived. The guardrail steps are a flat sequence of
        thirty in one job, each one an independent question about the tree, so the whole
        point of `if: ${{ !cancelled() }}` is that ONE red guard still lets the other
        twenty-nine report. A step that omits it is skipped by the first failure above it,
        and the later it sits the less often it runs at all: `check_deploy_workflow` was
        thirtieth and was the one that shipped without the condition, so it could only ever
        run on a build that was already green.

        `always()` is deliberately NOT accepted in its place. It also runs after a
        CANCELLATION — a queued job the author superseded with a new push — which spends a
        runner on a verdict nobody is waiting for and, on a cancelled deploy-adjacent run,
        reports a failure about a commit nobody is looking at.
        """
        # `python -m scripts.check_...`, not a bare `scripts.check_`: the `Tests` step
        # names `check_coverage_ratchet` as a pytest PLUGIN (`-p`), which is the suite
        # recording its own provenance rather than a guardrail reaching a verdict — and
        # that step is deliberately unconditional, since a suite run after a failed
        # migration measures nothing.
        offenders = [
            step.get("name")
            for step in self._workflow_steps()
            if (
                "python -m scripts.check_" in str(step.get("run", ""))
                or "lint-imports" in str(step.get("run", ""))
            )
            and "!cancelled()" not in str(step.get("if", ""))
        ]
        assert offenders == [], (
            f"{offenders} run a guardrail without `if: ${{{{ !cancelled() }}}}`, so each is "
            "SKIPPED whenever any earlier step in the job failed. A guard that only runs "
            "on an already-green build is registered, not enforced."
        )

    def test_the_condition_control_can_still_see_an_unconditional_step(self) -> None:
        """The test above is an emptiness assertion, so it passes if the step scan returns
        nothing. The setup steps are the control: `Install dependencies` MUST stay
        unconditional (a job whose dependencies did not install has nothing to say), so its
        presence proves the scan reads `if:` rather than inventing one."""
        unconditional = [step.get("name") for step in self._workflow_steps() if "if" not in step]
        assert "Install dependencies" in unconditional
        assert len(self._workflow_steps()) > 30

    def test_every_guardrail_script_has_negative_controls(self) -> None:
        """Every catalogue row ends "Negative controls in tests/..." and nothing checked it.

        This whole file exists because a guardrail that has stopped seeing violations is
        worse than none — and a guardrail with no test at all cannot be shown to see one.
        The scan is for the module NAME anywhere under `tests/`, which is deliberately
        generous: how a guard is exercised is the author's call, but a guard no test names
        is one nobody can weaken and find out.
        """
        import re

        blob = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in sorted((REPO_ROOT / "tests").rglob("*.py"))
        )
        assert len(blob) > 100_000, "the tests scan is reading the wrong place"
        untested = [
            path.stem
            for path in sorted((REPO_ROOT / "scripts").glob("check_*.py"))
            if not re.search(rf"\b{re.escape(path.stem)}\b", blob)
        ]
        assert untested == [], (
            f"{untested} are named by no file under tests/. Every row of the guardrail "
            "catalogue promises negative controls; a guard with none is a green line "
            "nobody can prove still means anything. Import it and assert on its own "
            "functions, the way every class above this one does."
        )

    def test_the_job_that_runs_pytest_installs_what_the_tests_import(self) -> None:
        """A CI job whose dependency install is narrower than what its tests import.

        `uv sync --all-packages` does NOT install optional dependency groups, and
        `tests/observability_security_test.py` imports `sentry_sdk` at module scope to pin
        the scrubber that keeps transcripts and caller names out of the error tracker
        (hard rule 6). The `types` job already passed `--group errors` for mypy's sake —
        CLAUDE.md explains why — and the job that RUNS THE TESTS did not.

        WHY IT WAS INVISIBLE HERE AND RED THERE: a development machine has the group
        installed, so the module imports and the suite is green locally. CI installs from
        the lockfile and hit `ModuleNotFoundError` at COLLECTION, which the coverage
        ratchet then reported as REFUSED TO SCORE — sending the reader to hunt a code
        defect that did not exist. An environment difference wearing a gate's error
        message is the worst kind, because the message is about something else entirely.

        The rejected fix is worth recording: skipping the module when the import fails
        would have made CI green while leaving a PII scrubber unexercised in the one
        environment that gates a merge. Install the dependency; never silence the guard.

        FAILS IF: the pytest job's install stops requesting the group.
        """
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        installs = [
            line.strip()
            for line in workflow.splitlines()
            if "uv sync" in line and not line.lstrip().startswith("#")
        ]
        assert installs, "no `uv sync` line found — this scan is reading the wrong file"
        assert all("--group errors" in line for line in installs), (
            "a CI job installs dependencies without `--group errors`, so a test module "
            "importing an optional dependency fails at collection there while passing on "
            "any machine that happens to have it: " + " | ".join(installs)
        )

    def test_make_check_runs_what_ci_runs(self) -> None:
        """CI is the authority; the Makefile is the local mirror. Every backend command
        in the workflow must have a home in `make check`."""
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        text = self._makefile()
        for command in ("lint-imports", "mypy apps packages", "scripts.eval"):
            assert command in workflow and command in text
        assert "ruff check ." in workflow and "ruff check ." in text
        assert "ruff format --check ." in workflow and "ruff format --check ." in text
