"""The gate-16c probe, driven end to end against a stub that keeps the real signature.

WHY THIS FILE EXISTS. `scripts/probe_bolna_providers.py` is an OPERATOR entry point: it
is run once, by hand, on the day a gate is settled, against a live vendor account. Nothing
imported it, nothing called it, and CI's typechecker does not reach it — CLAUDE.md's
command is `mypy apps packages`, and this file is in neither — so its one call into the
`VoiceEngine` Protocol was checked by nobody.

`set_llm_credential` grew a REQUIRED keyword-only `provider` when the posture opened to
three legs, and its docstring says why in as many words: *"Making it required turns that
into a type error at every call site instead."* It did, at every call site a gate looks
at. This one raised `TypeError` inside the probe's own `except Exception`, which printed
**"GATE: NEGATIVE (so far) — the write failed"** followed by three paragraphs telling the
operator their Bolna ACCOUNT disagreed with the vendor's documented credential name — a
wire-value question, answered wrongly, on the strength of our own arity error.

The stub below deliberately mirrors the Protocol's signature exactly (keyword-only
`provider`, no default). A stub that accepted `**kwargs` would absorb the same mismatch
the fake absorbs, and this test would prove nothing.
"""

from __future__ import annotations

import pytest
from apps.api.engine.bolna import BOLNA_CAPABILITIES
from calevate_shared.engine import AZURE_OPENAI_LEG, LlmCredentialPlacement, LlmProvider
from scripts import probe_bolna_providers as probe


class _RecordingEngine:
    """Enough of `VoiceEngine` for the probe, with `set_llm_credential`'s real arity."""

    name = "bolna"

    def __init__(self, *, llm_is_ours: bool = True) -> None:
        # The REAL descriptor, with one field moved. A hand-built one would let this
        # test drift from what the adapter declares, which is the thing the probe reads.
        self.capabilities = (
            BOLNA_CAPABILITIES
            if llm_is_ours
            else BOLNA_CAPABILITIES.model_copy(update={"llm": "dictated"})
        )
        self.calls: list[tuple[str, LlmProvider]] = []

    async def set_llm_credential(
        self, secret: str, *, provider: LlmProvider
    ) -> LlmCredentialPlacement:
        self.calls.append((secret, provider))
        return LlmCredentialPlacement(replaced_in_place=True, superseded_removed=0)


@pytest.fixture
def _stub(monkeypatch: pytest.MonkeyPatch) -> _RecordingEngine:
    import apps.api.engine as engine_module

    stub = _RecordingEngine()
    monkeypatch.setattr(engine_module, "get_engine", lambda settings: stub)
    return stub


async def test_the_probe_writes_the_credential_instead_of_raising(
    _stub: _RecordingEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    """RED BEFORE THE FIX: `TypeError: set_llm_credential() missing 1 required
    keyword-only argument: 'provider'`, swallowed and printed as a vendor finding."""
    code = await probe._run()
    out = capsys.readouterr().out

    assert code == 0, out
    assert "GATE: NEGATIVE" not in out
    assert _stub.calls == [(probe.PROBE_VALUE, "azure_openai")]


async def test_the_leg_is_the_declared_incumbent_rather_than_a_typed_string(
    _stub: _RecordingEngine,
) -> None:
    """The value is derived from the posture, so a leg rename moves it here too."""
    await probe._run()
    assert _stub.calls[0][1] == AZURE_OPENAI_LEG.provider


async def test_an_engine_that_dictates_its_model_is_still_skipped(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The branch that must NOT change: there is no credential of ours to install, and
    the probe says so instead of writing one."""
    import apps.api.engine as engine_module

    stub = _RecordingEngine(llm_is_ours=False)
    monkeypatch.setattr(engine_module, "get_engine", lambda settings: stub)

    assert await probe._run() == 0
    assert "SKIPPED" in capsys.readouterr().out
    assert stub.calls == []
