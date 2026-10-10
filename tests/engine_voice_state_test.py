"""An agent whose voice was chosen from the engine's own catalogue reads as having a voice.

On ThinnestAI the voice picker saves `agents.engine_voice_id`, not `tts_voice`. The pending
read used only `tts_voice`, so a chosen voice showed "None chosen" and the agent's checklist
kept asking for one.
"""

from __future__ import annotations

from apps.api.agents.publishing import _AgentRow, _voice_state


def _row(**overrides: object) -> _AgentRow:
    fields: dict[str, object] = {
        "status": "draft",
        "engine_agent_ref": None,
        "draft_version": 1,
        "draft_at": None,
        "live_version": None,
        "max_call_duration_s": None,
        "tts_voice": None,
        "tts_provider": None,
        "live_tts_voice": None,
        "live_tts_provider": None,
        "verify_state": "unverified",
        "verified_at": None,
        "engine_voice_id": "hv_anika",
        "engine_voice_label": "Anika",
    }
    fields.update(overrides)
    return _AgentRow(**fields)  # type: ignore[arg-type]


def test_a_chosen_engine_voice_is_configured_and_named() -> None:
    state = _voice_state(_row())
    assert state.configured is not None and state.configured.voice_id == "hv_anika"
    assert state.live is None
    assert "Anika" in state.headline
    assert state.unnamed_note is None
    assert state.republish_required is False


def test_a_published_agent_hears_the_chosen_engine_voice() -> None:
    state = _voice_state(_row(status="live", engine_agent_ref="ag_1"))
    assert state.live is not None and state.live.voice_id == "hv_anika"
    assert state.headline == "Callers hear Anika."


def test_no_voice_at_all_still_reads_as_none() -> None:
    state = _voice_state(_row(engine_voice_id=None, engine_voice_label=None))
    assert state.configured is None
    assert state.headline == "No voice has been set on this agent."
