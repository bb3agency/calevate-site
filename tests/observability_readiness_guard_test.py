"""The readiness ladder's negative controls: does it still SEE a silently-off component?

Two halves, matching the check:

* the CONFIGURATION half runs `observability.py`'s own predicates against doctored
  `Settings`, because that is what a deploy hands them;
* the STRUCTURAL half takes the REAL `observability.py` source, applies one minimal
  mutation that is exactly the leak being claimed, and requires it to be reported. Mutating
  reality rather than inventing a fixture is what keeps the mutation meaningful — if the
  check stops looking at that part of the file, these fail.

Nothing here touches a network, and nothing here asserts reachability: that is OPERATIONS
§2 gate 15 and it cannot be simulated (D-31/D-32).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.core.observability import (
    READINESS_MISCONFIGURED,
    READINESS_READY,
    READINESS_SKIPPED,
    init_observability,
    sentry_readiness,
    tracing_readiness,
)
from calevate_shared.config import Settings
from scripts import check_observability_ready as guard

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_SOURCE = (REPO_ROOT / "apps" / "api" / "core" / "observability.py").read_text(encoding="utf-8")

#: A DSN shaped exactly like Sentry's own, and deliberately not a real project: nothing in
#: this suite sends anything anywhere.
WELL_FORMED_DSN = "https://0123456789abcdef@o0.ingest.sentry.io/1234567"


def _settings(**overrides: Any) -> Any:
    """A settings stand-in carrying only the fields the ladder reads.

    A real `Settings()` needs five required env keys and a `.env`; the ladder's inputs are
    four attributes, and naming them here is what makes each test's mutation obvious.
    """
    base = {
        "app_env": "prod",
        "release_version": "abc1234",
        "sentry_dsn": None,
        "otel_exporter_otlp_endpoint": None,
        "otel_traces_sample_ratio": 0.1,
        # Read by `init_observability`'s alerting half, which the boot-path tests below
        # walk through on their way to the Sentry branch.
        "alerts_email": None,
    }
    return SimpleNamespace(**{**base, **overrides})


def _codes(component: Any) -> set[str]:
    return {problem.code for problem in component.problems}


# ============================================================================
# Rung 1 — disabled must SKIP cleanly
# ============================================================================


class TestDisabledSkipsCleanly:
    def test_no_dsn_is_a_skip_and_not_a_failure(self) -> None:
        """A laptop and CI both run with nothing configured. If that failed, everyone
        would learn to ignore this check long before it ever ran against a deploy."""
        assert sentry_readiness(_settings(app_env="local")).status == READINESS_SKIPPED

    def test_no_collector_is_a_skip(self) -> None:
        assert tracing_readiness(_settings(app_env="local")).status == READINESS_SKIPPED

    def test_the_skip_still_says_what_is_not_happening(self) -> None:
        """Skipping cleanly is not skipping silently — an operator reading the output has
        to be able to see that errors are going nowhere."""
        summary = sentry_readiness(_settings(app_env="local")).summary
        assert "SENTRY_DSN is unset" in summary and "OPERATIONS §8" in summary


# ============================================================================
# Rung 2 — enabled-but-misconfigured must FAIL, naming the setting
# ============================================================================


class TestSentryConfiguration:
    @pytest.mark.parametrize(
        ("dsn", "code"),
        [
            pytest.param("o0.ingest.sentry.io/1234567", "dsn_scheme_unsupported", id="no-scheme"),
            pytest.param("https://o0.ingest.sentry.io/1234567", "dsn_no_public_key", id="no-key"),
            pytest.param("https://key@/1234567", "dsn_no_host", id="no-host"),
            pytest.param("https://key@o0.ingest.sentry.io/", "dsn_no_project_id", id="no-project"),
            pytest.param(
                "https://key@o0.ingest.sentry.io/my-project",
                "dsn_project_id_not_numeric",
                id="project-slug-instead-of-id",
            ),
            pytest.param(
                "https://key@o0.ingest.sentry.io/1234567?environment=prod",
                "dsn_has_query_or_fragment",
                id="query-string",
            ),
        ],
    )
    def test_a_broken_dsn_is_named(self, dsn: str, code: str) -> None:
        readiness = sentry_readiness(_settings(sentry_dsn=dsn))
        assert readiness.status == READINESS_MISCONFIGURED
        assert code in _codes(readiness)

    def test_a_well_formed_dsn_raises_no_shape_complaint(self) -> None:
        """The control. Without it every test above could pass for the wrong reason."""
        readiness = sentry_readiness(_settings(sentry_dsn=WELL_FORMED_DSN))
        shape = {code for code in _codes(readiness) if code.startswith("dsn_")}
        assert shape == set()

    def test_a_missing_sdk_is_the_silent_off_state_and_is_reported(self) -> None:
        """`sentry-sdk` is a dependency GROUP, so a host that ran a plain `uv sync` has a
        DSN, an initialised-looking process, and no error reporting at all."""
        readiness = sentry_readiness(_settings(sentry_dsn=WELL_FORMED_DSN))
        installed = "sentry_sdk" in sys.modules or _import_available("sentry_sdk")
        assert ("sdk_missing" in _codes(readiness)) is not installed

    def test_a_default_release_on_a_deployed_host_is_reported(self) -> None:
        readiness = sentry_readiness(_settings(sentry_dsn=WELL_FORMED_DSN, release_version="dev"))
        assert "release_version_default" in _codes(readiness)

    def test_a_default_release_locally_is_not(self) -> None:
        readiness = sentry_readiness(
            _settings(app_env="local", sentry_dsn=WELL_FORMED_DSN, release_version="dev")
        )
        assert "release_version_default" not in _codes(readiness)

    def test_no_problem_message_ever_carries_the_dsn(self) -> None:
        """Hard rule 6, and the DSN is a credential besides. A check that helpfully
        echoed the bad value would put it in CI logs, which are not a secret store."""
        secret = "https://SUPERSECRETKEY@o0.ingest.sentry.io/not-a-number"
        readiness = sentry_readiness(_settings(sentry_dsn=secret))
        rendered = readiness.summary + " ".join(p.message for p in readiness.problems)
        assert "SUPERSECRETKEY" not in rendered
        assert secret not in rendered


class TestTracingConfiguration:
    @pytest.mark.parametrize(
        ("endpoint", "code"),
        [
            pytest.param("collector.internal:4318", "endpoint_not_absolute", id="bare-host"),
            pytest.param(
                "grpc://collector.internal:4317",
                "endpoint_scheme_unsupported",
                id="grpc-endpoint-for-an-http-exporter",
            ),
            pytest.param(
                "https://collector.internal?token=abc",
                "endpoint_has_query_or_fragment",
                id="query-string",
            ),
            pytest.param(
                "https://collector.internal/v1/traces",
                "endpoint_already_names_the_signal_path",
                id="signal-path-appended-twice",
            ),
            pytest.param(
                "https://collector.internal/v1/traces/",
                "endpoint_already_names_the_signal_path",
                id="signal-path-with-trailing-slash",
            ),
        ],
    )
    def test_a_broken_endpoint_is_named(self, endpoint: str, code: str) -> None:
        readiness = tracing_readiness(_settings(otel_exporter_otlp_endpoint=endpoint))
        assert readiness.status == READINESS_MISCONFIGURED
        assert code in _codes(readiness)

    def test_a_base_endpoint_is_accepted(self) -> None:
        readiness = tracing_readiness(
            _settings(otel_exporter_otlp_endpoint="https://collector.internal:4318")
        )
        assert readiness.status == READINESS_READY

    def test_a_zero_sample_ratio_is_the_middle_state_this_ladder_is_for(self) -> None:
        """Configured, wired, exporting nothing — and type-valid, so `check_config_applies`
        bounds cannot see it. The provider, the exporter thread and the middleware are all
        built, and no root trace is ever sampled."""
        readiness = tracing_readiness(
            _settings(
                otel_exporter_otlp_endpoint="https://collector.internal:4318",
                otel_traces_sample_ratio=0.0,
            )
        )
        assert readiness.status == READINESS_MISCONFIGURED
        assert "sample_ratio_zero" in _codes(readiness)

    def test_the_sample_ratio_is_only_judged_when_a_collector_is_configured(self) -> None:
        """0.0 with no endpoint is not a defect, it is a machine with tracing off."""
        readiness = tracing_readiness(_settings(otel_traces_sample_ratio=0.0))
        assert readiness.status == READINESS_SKIPPED


class TestTheSettingsFieldsAreTheOnesTheCodeReads:
    """Wiring: the ladder must read the same field names `init_tracing` and
    `sentry_sdk.init` read, or it is judging settings nobody consumes."""

    def test_the_fields_exist_on_the_real_settings_model(self) -> None:
        for field in ("sentry_dsn", "otel_exporter_otlp_endpoint", "otel_traces_sample_ratio"):
            assert field in Settings.model_fields

    def test_the_release_default_the_check_looks_for_is_the_real_one(self) -> None:
        assert Settings.model_fields["release_version"].default == "dev"


# ============================================================================
# Rung 3 — the export filters that carry hard rule 6
# ============================================================================


class TestSentryHooks:
    def test_the_live_file_is_clean(self) -> None:
        assert guard.check_sentry_hooks() == []

    @pytest.mark.parametrize(
        "keyword", ["before_send", "before_breadcrumb", "send_default_pii", "max_request_body_size"]
    )
    def test_removing_a_required_keyword_is_caught(self, keyword: str) -> None:
        mutated = _drop_keyword(LIVE_SOURCE, keyword)
        assert mutated != LIVE_SOURCE, f"the mutation did not apply for {keyword}"
        failures = guard.check_sentry_hooks(mutated)
        assert any(keyword in failure for failure in failures), failures

    def test_reintroducing_sentry_performance_tracing_is_caught(self) -> None:
        """The exact regression the module docstring records: `traces_sample_rate` starts a
        SECOND span pipeline whose transaction events `before_send` never sees."""
        mutated = LIVE_SOURCE.replace(
            "before_send=scrub_event,",
            "before_send=scrub_event,\n                traces_sample_rate=0.1,",
        )
        failures = guard.check_sentry_hooks(mutated)
        assert any("traces_sample_rate" in failure for failure in failures), failures

    def test_swapping_the_scrubber_for_something_else_is_caught(self) -> None:
        mutated = LIVE_SOURCE.replace("before_send=scrub_event,", "before_send=_passthrough,")
        failures = guard.check_sentry_hooks(mutated)
        assert any("scrub_event" in failure for failure in failures), failures

    def test_losing_the_init_call_entirely_is_reported_rather_than_passed(self) -> None:
        """A guardrail that cannot find its subject must say so — silence there is how a
        check keeps reporting green over a file it no longer understands."""
        mutated = LIVE_SOURCE.replace("sentry_sdk.init(", "sentry_sdk.setup(")
        failures = guard.check_sentry_hooks(mutated)
        assert any("no longer contains" in failure for failure in failures), failures


class TestTracingExportIsWrapped:
    def test_the_live_file_is_clean(self) -> None:
        assert guard.check_tracing_export_is_wrapped() == []

    def test_an_unwrapped_exporter_is_caught(self) -> None:
        """The leak: `record_exception=True` is the SDK default, so an unwrapped exporter
        ships `exception.message` and `exception.stacktrace` off every failing span."""
        mutated = LIVE_SOURCE.replace(
            "provider.add_span_processor(BatchSpanProcessor(redacting_exporter))",
            "provider.add_span_processor(BatchSpanProcessor(span_exporter))",
        )
        assert mutated != LIVE_SOURCE
        failures = guard.check_tracing_export_is_wrapped(mutated)
        assert any("_RedactingSpanExporter" in failure for failure in failures), failures

    def test_a_second_unwrapped_processor_added_beside_the_wrapped_one_is_caught(self) -> None:
        mutated = LIVE_SOURCE.replace(
            "otel_trace.set_tracer_provider(provider)",
            "provider.add_span_processor(SimpleSpanProcessor(span_exporter))\n"
            "    otel_trace.set_tracer_provider(provider)",
        )
        failures = guard.check_tracing_export_is_wrapped(mutated)
        assert any("SimpleSpanProcessor" in failure for failure in failures), failures

    def test_exporting_through_nothing_is_reported(self) -> None:
        mutated = LIVE_SOURCE.replace("BatchSpanProcessor(redacting_exporter)", "_noop()")
        failures = guard.check_tracing_export_is_wrapped(mutated)
        assert any("registers no span processor" in failure for failure in failures), failures


class TestLangfuse:
    def test_langfuse_is_absent_from_the_tree(self) -> None:
        """D-49's state, asserted rather than remembered. If this fails, either Langfuse
        was restored (and needs its decision-log entry and the OTLP export path) or a
        dependency dragged it in."""
        assert guard.langfuse_footholds() == []
        component, failures = guard.check_langfuse()
        assert component.status == READINESS_SKIPPED
        assert failures == []

    def test_an_import_anywhere_is_a_failure_naming_hard_rule_6(self, tmp_path: Path) -> None:
        """A direct Langfuse client is a SECOND OpenTelemetry pipeline that never meets
        `_RedactingSpanExporter` — and the one call site that would use it
        (`apps/workers/extraction.py`) holds a raw transcript."""
        module = tmp_path / "apps" / "workers"
        module.mkdir(parents=True)
        (module / "tracing.py").write_text("from langfuse import get_client\n", encoding="utf-8")
        # An EMPTY manifest rather than an absent one: since D-176 a surface this scan
        # could not open is a refusal, so isolating the import surface means handing it a
        # dependency list that exists and declares nothing.
        manifest = tmp_path / "pyproject.toml"
        manifest.write_text("[project]\ndependencies = []\n", encoding="utf-8")
        found = guard.langfuse_footholds(roots=(tmp_path,), pyproject=manifest)
        assert found and "imports langfuse" in found[0]
        _, failures = guard.check_langfuse(found)
        assert any("redaction hook" in failure for failure in failures), failures

    def test_a_dependency_is_a_foothold_even_with_no_import_yet(self, tmp_path: Path) -> None:
        manifest = tmp_path / "pyproject.toml"
        manifest.write_text('[project]\ndependencies = ["langfuse>=3.0"]\n', encoding="utf-8")
        found = guard.langfuse_footholds(roots=(), pyproject=manifest)
        assert found and "declares the langfuse package" in found[0]

    def test_a_scan_root_that_does_not_exist_refuses_rather_than_reporting_absence(
        self, tmp_path: Path
    ) -> None:
        """D-176. This rung's whole output is "langfuse is not here", and a walk over a
        directory that has been renamed produces exactly that answer for free — `rglob`
        yields nothing and raises nothing. Before the fix this returned `[]` and the run
        printed `[skip] langfuse: Not present in the tree`, a claim about a tree it had
        never opened. Both surfaces are pinned: the roots and the manifest."""
        missing = tmp_path / "gone"
        manifest = tmp_path / "pyproject.toml"
        manifest.write_text("[project]\ndependencies = []\n", encoding="utf-8")

        with pytest.raises(guard.ObservabilityBlindError, match="walked nothing"):
            guard.langfuse_footholds(roots=(missing,), pyproject=manifest)

        with pytest.raises(guard.ObservabilityBlindError, match="dependency surface"):
            guard.langfuse_footholds(roots=(), pyproject=tmp_path / "absent.toml")

    def test_the_live_tree_is_still_readable_by_both_surfaces(self) -> None:
        """The control on the control: the refusal above must not be firing today, or the
        `[]` the first test asserts would be unreachable rather than earned."""
        assert guard.langfuse_footholds() == []

    def test_prose_about_the_absent_client_is_not_a_foothold(self) -> None:
        """`config.py` explains at length why Langfuse is NOT wired. Detection is by AST,
        so the explanation cannot be mistaken for the thing it explains."""
        assert (
            "langfuse"
            in (REPO_ROOT / "packages" / "shared" / "src" / "calevate_shared" / "config.py")
            .read_text(encoding="utf-8")
            .lower()
        )
        assert guard.langfuse_footholds() == []


# ============================================================================
# The boot path: the ladder is applied where the configuration actually lives
# ============================================================================


class TestBootPath:
    def test_a_malformed_dsn_no_longer_takes_the_process_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`sentry_sdk.init` raises `BadDsn` (a ValueError) on a typo, and until this was
        handled a single wrong character in a console-managed field stopped voice-runtime
        from booting — the one service whose job is answering a telephone."""
        from apps.api.core import observability

        calls: list[str] = []

        def _raise(**_kwargs: Any) -> None:
            calls.append("init")
            raise ValueError("Unsupported scheme https://SECRET@host/x")

        fake = SimpleNamespace(init=_raise, set_tag=lambda *_a, **_k: None)
        monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
        monkeypatch.setattr(
            observability,
            "get_settings",
            lambda: _settings(app_env="local", sentry_dsn="https://SECRET@host/x"),
        )

        enabled = init_observability("api")

        assert calls == ["init"], "the init was never attempted"
        assert "sentry" not in enabled, "a refused init must not be reported as enabled"

    def test_the_ladder_is_consulted_at_boot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Wiring. A readiness function nothing calls is the half-wired feature CLAUDE.md
        names, and the deploy-time script alone would only cover hosts somebody ran it on."""
        from apps.api.core import observability

        seen: list[Any] = []
        monkeypatch.setattr(
            observability,
            "observability_readiness",
            lambda settings: seen.append(settings) or (),
        )
        monkeypatch.setattr(
            observability, "get_settings", lambda: _settings(app_env="local", sentry_dsn=None)
        )
        init_observability("api")
        assert len(seen) == 1


def _import_available(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _drop_keyword(source: str, keyword: str) -> str:
    """Delete the whole line carrying `keyword=` from the `sentry_sdk.init` call."""
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith(f"{keyword}=")
    )
