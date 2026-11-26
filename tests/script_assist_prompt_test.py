"""The brief every Pip script request is written from (`script_assist.ScriptBrief`), which CI
can check with no model key."""

from __future__ import annotations

from apps.workers.script_assist import ScriptBrief


def test_the_brief_carries_what_the_server_knows() -> None:
    message = ScriptBrief(
        business_name="Raghava Organics",
        business_type="retail",
        direction="outbound",
        language="te-IN",
        register="Neutral spoken Telugu",
        collect=("Name", "Area"),
        knowledge_titles=("Price list",),
        answers=(("what_you_offer", "Organic chilli and oils"),),
    ).user_message()
    assert "places calls to leads" in message
    assert "Details to collect: Name; Area" in message
    assert "Knowledge documents: Price list" in message
    assert "What do you sell or do? Organic chilli and oils" in message
