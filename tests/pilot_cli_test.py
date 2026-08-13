"""The CLI an operator actually runs at 11pm, and the preflight they run on day one.

Two properties dominate: every refusal names the thing to change, and the exit code can
never say "fine" about a run that verified nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from calevate_shared.config import Settings
from scripts.pilot import config as config_module
from scripts.pilot import runner
from scripts.pilot.config import (
    VENDOR_API_URL,
    Reachability,
    format_preflight,
    preflight,
    probe_vendor,
    webhook_url_reachable,
)
from scripts.pilot.gates_api import GateContext
from scripts.pilot.results import GateRun, failed, not_run, passed
from scripts.pilot.safety import PilotRefusedError


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "app_env": "local",
        "database_url": "postgresql+psycopg://u:p@localhost:5432/x",
        "redis_url": "redis://localhost:6379/0",
        "object_store_endpoint": "http://localhost:9000",
        "object_store_bucket": "calevate",
    }
    base.update(overrides)
    return Settings(**base)


# --- preflight ----------------------------------------------------------------


def test_preflight_never_prints_a_secret() -> None:
    """A key is present or absent and never otherwise — not truncated, not fingerprinted.
    The output is pasted into chat and committed; a stable identifier for a live
    credential has no business in either."""
    secret = "sk-bolna-do-not-leak-me"
    report = preflight(_settings(bolna_api_key=secret, sarvam_api_key=secret, engine="bolna"))
    rendered = format_preflight(report) + json.dumps(report.as_dict())
    assert secret not in rendered
    assert "do-not-leak" not in rendered


def test_preflight_names_the_gates_each_missing_item_blocks() -> None:
    report = preflight(_settings(engine="bolna", webhook_base_url="https://tunnel.example.com"))
    blocked = report.blocked_gates()
    # No API key, so the three API gates are blocked and say so by number.
    assert blocked[1] == ["BOLNA_API_KEY"]
    assert blocked[2] == ["BOLNA_API_KEY", "SARVAM_API_KEY"]
    assert blocked[6] == ["BOLNA_API_KEY"]


def test_preflight_satisfied_when_everything_checkable_is_present() -> None:
    report = preflight(
        _settings(
            engine="bolna",
            bolna_api_key="x",
            sarvam_api_key="y",
            webhook_base_url="https://tunnel.example.com",
        ),
        Reachability(True, "the API answered (HTTP 401)"),
    )
    assert report.missing == ()
    # ...and the things it CANNOT check are still listed, unresolved, rather than
    # quietly counted as done.
    assert {r.key for r in report.unverifiable} == {
        "pilot phone number",
        "account credit",
        "nginx source-IP allowlist",
    }


def test_an_unreachable_vendor_is_a_blocking_requirement_not_an_exception() -> None:
    """The sandbox these gates were written in cannot reach `api.bolna.ai` at all — the
    egress proxy answers `CONNECT tunnel failed, 403`. An operator who has bought a
    number, topped up credit and obtained a key, and THEN discovers their network blocks
    the API on gate 2, has lost the session to the cheapest check in the harness."""
    blocked = preflight(
        _settings(engine="bolna", bolna_api_key="x", sarvam_api_key="y"),
        Reachability(False, "an egress proxy refused the connection (ProxyError)"),
    )
    assert blocked.blocked_gates()[2] == [f"network reachability ({VENDOR_API_URL})"]
    assert "egress proxy" in format_preflight(blocked)


def test_reachability_is_listed_first_because_it_costs_nothing_to_check() -> None:
    report = preflight(_settings(), Reachability(True, "the API answered (HTTP 401)"))
    assert report.requirements[0].key.startswith("network reachability")
    assert report.requirements[0].state == "satisfied"


def test_an_unprobed_network_is_unverifiable_never_assumed_fine() -> None:
    """An unasked question and a good answer must not look the same."""
    report = preflight(_settings())
    assert report.requirements[0].state == "unverifiable"
    assert report.requirements[0] not in report.missing


def test_any_http_answer_means_reachable_even_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Authorisation is a separate requirement with its own row. Conflating them would
    report a missing key as a network fault and send an operator at their firewall."""
    import httpx

    monkeypatch.setattr(
        config_module.httpx,
        "get",
        lambda *a, **k: httpx.Response(403, request=httpx.Request("GET", VENDOR_API_URL)),
    )
    probe = probe_vendor()
    assert probe.reachable is True
    assert "403" in probe.detail


def test_a_blocked_egress_proxy_reads_as_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact failure this environment produces."""
    import httpx

    def _refuse(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.ProxyError("CONNECT tunnel failed, response 403")

    monkeypatch.setattr(config_module.httpx, "get", _refuse)
    probe = probe_vendor()
    assert probe.reachable is False
    assert "egress proxy" in probe.detail


def test_a_dead_network_reads_as_unreachable_too(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def _timeout(*args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(config_module.httpx, "get", _timeout)
    assert probe_vendor().reachable is False


def test_a_loopback_webhook_url_is_caught_before_the_pilot_starts() -> None:
    """The engine calls back from its own cloud. A localhost URL means no delivery ever
    arrives, and gates 1 and 6 would score a silence that says nothing about Bolna."""
    assert webhook_url_reachable("http://localhost:8100") is False
    assert webhook_url_reachable("http://127.0.0.1:8100") is False
    assert webhook_url_reachable("https://calevate.ngrok.io") is True
    assert webhook_url_reachable("not-a-url") is False


# --- gate registry ------------------------------------------------------------


async def test_an_unimplemented_gate_is_reported_by_name_never_omitted() -> None:
    """A number no gate module will ever claim, deliberately: `scripts/pilot/` is written
    by several slices at once, so asserting this branch against a REAL gate number would
    turn a colleague shipping their gate into a failure on this file."""
    ctx = GateContext(engine=None, settings=_settings())  # type: ignore[arg-type]
    results, skipped = await runner.run_gates([99], ctx)
    assert results[0].status == "not_run"
    assert "another slice" in (results[0].blocked or "")
    assert skipped[0]["gate"] == "99"


async def test_a_gate_contributed_by_a_sibling_module_is_picked_up() -> None:
    """The seam works both ways: this file owns 1, 2 and 6, and any module exposing a
    `GATES` mapping joins the same run without either side importing the other."""
    runners, _ = runner.gate_registry()
    assert {1, 2, 6} <= set(runners)
    # Anything beyond those three arrived from a sibling slice, and its absence is not a
    # failure here — only its silent absence from the OUTPUT would be, and that is what
    # the test above pins.


async def test_human_only_gates_say_why_they_are_human_only() -> None:
    ctx = GateContext(engine=None, settings=_settings())  # type: ignore[arg-type]
    results, _skipped = await runner.run_gates([12], ctx)
    assert results[0].status == "not_run"
    assert "in writing" in (results[0].blocked or "")


def test_the_registry_carries_the_three_gates_this_slice_owns() -> None:
    runners, _ = runner.gate_registry()
    assert {1, 2, 6} <= set(runners)


# --- exit codes ---------------------------------------------------------------


def test_a_dry_run_that_verified_nothing_does_not_exit_zero() -> None:
    """The exit code is how a wrapper script learns what happened, and a harness that
    exits 0 after verifying nothing is a harness something will eventually believe."""
    assert runner.exit_code([GateRun(1, "t", checks=(not_run("a", "why"),))]) == 2


def test_a_failure_exits_one() -> None:
    assert runner.exit_code([GateRun(1, "t", checks=(failed("a", "broken"),))]) == 1


def test_only_all_green_exits_zero() -> None:
    assert runner.exit_code([GateRun(1, "t", checks=(passed("a", "ok"),))]) == 0


def test_an_empty_run_is_not_success() -> None:
    assert runner.exit_code([]) == 2


def test_a_failure_outranks_a_pass_in_the_same_run() -> None:
    assert (
        runner.exit_code(
            [
                GateRun(1, "t", checks=(passed("a", "ok"),)),
                GateRun(2, "t", checks=(failed("b", "broken"),)),
            ]
        )
        == 1
    )


# --- argument handling --------------------------------------------------------


def test_an_unknown_attestation_key_is_an_error_not_an_ignored_line() -> None:
    """The value of an attestation is that a human vouched for a SPECIFIC fact. A typo
    that silently vouches for nothing leaves the gate NOT RUN while its operator believes
    they answered it."""
    with pytest.raises(PilotRefusedError, match="not an attestable fact"):
        runner.parse_attestations(["gate6.call_contnued=yes"])


def test_an_attestation_without_a_value_is_refused() -> None:
    with pytest.raises(PilotRefusedError, match="key=value"):
        runner.parse_attestations(["gate6.call_continued"])


def test_known_attestations_parse() -> None:
    assert runner.parse_attestations(["gate6.retries_observed=0"]) == {
        "gate6.retries_observed": "0"
    }


def test_a_missing_capture_file_names_itself(tmp_path: Path) -> None:
    with pytest.raises(PilotRefusedError, match="no such file"):
        runner.load_captures([str(tmp_path / "nope.json")])


def test_a_capture_file_may_hold_one_delivery_or_many(tmp_path: Path) -> None:
    one = tmp_path / "one.json"
    one.write_text(json.dumps({"id": "a"}), encoding="utf-8")
    many = tmp_path / "many.json"
    many.write_text(json.dumps([{"id": "b"}, {"id": "c"}]), encoding="utf-8")
    assert runner.load_captures([str(one), str(many)]) == [{"id": "a"}, {"id": "b"}, {"id": "c"}]


def test_a_capture_that_is_not_a_delivery_is_refused_not_skipped(tmp_path: Path) -> None:
    """A capture that silently contributed nothing would leave gate 1 reporting NOT RUN
    for a reason the operator already believed they had solved."""
    junk = tmp_path / "junk.json"
    junk.write_text(json.dumps(["not", "objects"]), encoding="utf-8")
    with pytest.raises(PilotRefusedError, match="delivery object"):
        runner.load_captures([str(junk)])


def test_malformed_json_says_so(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    with pytest.raises(PilotRefusedError, match="not valid JSON"):
        runner.load_captures([str(bad)])


def test_gate_numbers_must_be_numbers() -> None:
    with pytest.raises(PilotRefusedError, match="not a gate number"):
        runner._requested_gates("1,two")


def test_the_default_gate_set_is_this_slice() -> None:
    args = runner.build_parser().parse_args(["run"])
    assert args.gates == "1,2,6"
    assert args.place_calls is False
    assert args.max_calls is None


def test_the_opt_in_flag_is_spelled_out_in_the_parser() -> None:
    args = runner.build_parser().parse_args(["run", "--yes-place-real-calls-and-spend-money"])
    assert args.place_calls is True


# --- rendering ----------------------------------------------------------------


def test_the_summary_spells_not_run_out_loud() -> None:
    text = runner.render([GateRun(1, "Webhook trust", checks=(not_run("a", "why"),))], None)
    assert "NOT RUN" in text
    assert "NOT RUN is not PASS" in text


def test_an_attested_check_is_labelled_in_the_output() -> None:
    from scripts.pilot.results import SubCheck

    text = runner.render(
        [
            GateRun(
                6,
                "Webhook loss",
                checks=(SubCheck(name="a", status="pass", detail="seen", attested=True),),
            )
        ],
        None,
    )
    assert "[operator-attested]" in text
