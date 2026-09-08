"""The worker installs the attested-price readers at startup, or reads a quiet wrong answer.

`ops/pricing_snapshot.install_pricing_readers` points four SYNC, no-argument readers at an
in-process snapshot of the attested price store: the LLM price attestations
(`billing/rates`), the installed LLM legs and the dashboard data-use set
(`agents/llm_models`), and the TTS price predicate (`agents/voice_offer`). Each has a
DEFAULT for the process that never installed them, and every one of those defaults is the
conservative, plausible-looking answer — an operator's attestation is simply invisible,
nothing raises, nothing is logged.

`apps/api/main.py::_startup` adopts the seam for the API. The worker is a real consumer of
it (`kb_embeddings` gates a batch on `rates.llm_price_is_billable`, `document_ocr` and the
distillers price a leg with `rates.llm_inr_per_ktok`, and the voice picker's predicate has
the same shape) and did NOT, so the first worker to reach a sync reader got the default:
a Cartesia tier reading as not-billable in a process where an operator has attested its
price, on a billing surface, silently.

The check is read off the function's SOURCE rather than by booting a worker, for the reason
`tests/worker_terminal_alert_test.py::test_the_alerter_is_installed_at_worker_startup`
gives: `startup` wants Redis, a tracing provider and a database, and the property here is a
wiring one — a line that is either there or is not.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any

import pytest
from apps.api.agents import voice_offer
from apps.api.ops import pricing_snapshot
from apps.workers import settings as worker_settings


def _calls_in(function: Any) -> set[str]:
    """Names called at any depth inside `function`'s own body.

    AST rather than a substring, so a call cannot be satisfied by the word appearing in a
    comment or a docstring that merely says the worker ought to make it — which is exactly
    what `main.py`'s docstring said while nothing called it.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_the_pricing_readers_are_installed_at_worker_startup() -> None:
    assert "start_pricing_refresher" in _calls_in(worker_settings.startup), (
        "the worker never installs the attested-price readers: every sync reader in that "
        "process answers from its uninstalled default, so an operator's attestation is "
        "invisible to metering and to the pickers, with nothing raised"
    )


def test_the_name_the_worker_calls_is_the_real_one() -> None:
    """Half of the wiring is that the call exists; the other half is what it resolves to."""
    assert worker_settings.start_pricing_refresher is pricing_snapshot.start_pricing_refresher
    assert "install_pricing_readers" in _calls_in(pricing_snapshot.start_pricing_refresher), (
        "start_pricing_refresher no longer installs the readers — the worker's one line is "
        "adopting the poll only, and this test is now pinning the wrong function"
    )


@pytest.fixture
def _uninstalled() -> Any:
    """Leave the seam as it was found. The readers are process-global."""
    yield
    pricing_snapshot.uninstall_pricing_readers()


def test_without_the_readers_an_attested_cartesia_price_is_invisible(_uninstalled: Any) -> None:
    """The consequence, stated exactly: a WRONG answer, not an error.

    Uninstalled, `voice_offer.tts_price_is_billable` falls back to
    `default_tts_price_is_billable`, i.e. `provider == "sarvam"` — the honest answer for a
    process that has read nothing, and the wrong one for a process that simply forgot to
    read. Installed, the same call reports what the store says.
    """
    pricing_snapshot.uninstall_pricing_readers()
    assert voice_offer.tts_price_is_billable("cartesia") is False

    voice_offer.install_tts_price_reader(lambda provider: provider in {"sarvam", "cartesia"})
    assert voice_offer.tts_price_is_billable("cartesia") is True
