"""`owned_runtime` is a real third `AgentHosting` shape, and every reader answers for it.

D-592, `docs/PIPECAT-MIGRATION.md` §1.1. Widening a `Literal` is the cheap half; the
expensive half is that a value with no reader is a branch nothing decided. These clauses
pin the decisions taken at each branching site, so a later edit that folds the new member
into an `else` fails here rather than in production.

NO DATABASE: this is the type and the capability descriptor, nothing more.
"""

from __future__ import annotations

from typing import get_args

from calevate_shared.engine import AgentHosting, EngineCapabilities


def _caps(hosting: AgentHosting) -> EngineCapabilities:
    """A descriptor that differs from its siblings on the hosting axis and nothing else,
    so a clause that fails says which axis it measured (`fake.py`'s own rule for its three
    profiles)."""
    return EngineCapabilities(
        stt="ours",
        tts="ours",
        llm="ours",
        agent_hosting=hosting,
        # Required since 18 Sep 2026 and given the value that keeps this fixture about the
        # axis it says it is about: `records_audio` is what composes clause 2 of the
        # truthful-answer floor, and it is exercised by `tests/disclosure_toggle_test.py`.
        records_audio=True,
        campaigns=False,
        knowledge_base=False,
        number_series=frozenset(),
        caller_id=True,
        inbound_binding=True,
        transfer=False,
        in_call_handoff=False,
        action_tools=False,
        script_override=True,
        webhook_auth="none",
    )


def test_the_port_declares_exactly_three_hosting_shapes() -> None:
    """Read off the type, so this clause cannot be satisfied by a comment."""
    assert get_args(AgentHosting) == (
        "control_plane",
        "external_deployment",
        "owned_runtime",
    )


def test_an_owned_runtime_engine_hosts_agents() -> None:
    """The decision §1.1 turns on: we hold the agent record AND run the program.

    `create_agent`, `publish_agent` and `get_agent` all gate on `hosts_agents()`, so a
    False here would make `publish_agent` refuse and nothing would ever be recorded `live`
    — which is exactly the `external_deployment` misdeclaration the third member exists to
    avoid, arrived at from the other direction.
    """
    assert _caps("owned_runtime").hosts_agents() is True
    assert _caps("control_plane").hosts_agents() is True
    assert _caps("external_deployment").hosts_agents() is False


def test_the_generic_capability_ask_agrees_with_the_predicate() -> None:
    """`has("agent_hosting")` and `hosts_agents()` are ONE fact — the existing clause in
    `tests/engine_capability_test.py` says so for two shapes; this extends it to the third
    rather than letting a second mapping appear."""
    for hosting in get_args(AgentHosting):
        caps = _caps(hosting)
        assert caps.has("agent_hosting") is caps.hosts_agents(), hosting


def test_hosts_agents_names_its_members_rather_than_excluding_one() -> None:
    """A FOURTH shape must not be admitted by default.

    The predicate is membership (`in ("control_plane", "owned_runtime")`), not
    `!= "external_deployment"` — the difference is invisible today and decides what
    happens to the next member. Asserted by source rather than by behaviour because
    behaviour cannot distinguish the two until that member exists, and by then the branch
    has already been taken. The DOCSTRING is stripped before the check — it argues this
    exact point and quotes the spelling it forbids, so a naive substring search over the
    whole function would fail on the prose explaining why it must not.
    """
    import ast
    import inspect
    import textwrap

    from calevate_shared.engine import EngineCapabilities as Caps

    fn = ast.parse(textwrap.dedent(inspect.getsource(Caps.hosts_agents))).body[0]
    assert isinstance(fn, ast.FunctionDef)
    if ast.get_docstring(fn) is not None:
        fn.body = fn.body[1:]
    body = ast.unparse(fn)
    assert '!= "external_deployment"' not in body, (
        "`hosts_agents` excludes a member instead of naming the ones it admits, so a "
        "fourth hosting shape would reach `create_agent` without anybody deciding it "
        "should"
    )
