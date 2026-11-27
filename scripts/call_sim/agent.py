"""The agent side of a simulated call: what we would send the voice platform, as one model prompt.

The system prompt is `compose_engine_prompt` over the holder's config (the campaign's or inbound
line's, built by the publish path `agents/service.campaign_config` / `line_config`), then the
script's stages as the platform's own step list (`render_steps`, the preview's rendering of
`native_steps`), then ThinnestAI's speaking rules, which it reads to the model after our
instructions (`scripts/register_eval.vendor_rules`, VENDOR-STATED). How ThinnestAI itself merges
the step list into its model call is not published, so the step list here is a stand-in for
that part, and the report says so.

The tools offered are the platform's own in-call actions (`reliability/engine_actions.
definitions`: do-not-call, call back), the knowledge search the prompt names, and the holder's
own declared actions. Their answers are simulated; nothing is written anywhere.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal
from uuid import UUID

from apps.api.compliance.disclosure import ai_disclosure_for, recording_notice_for
from calevate_shared.call_script import (
    CallScript,
    CollectField,
    compile_call_script,
    native_steps,
    render_steps,
    substitute_variables,
    without_outline,
)
from calevate_shared.engine import (
    LAYER_SEPARATOR,
    AgentConfig,
    DisclosurePosture,
    compose_engine_prompt,
    compose_first_utterance,
    notice_fields,
)

ROOT: Final = Path(__file__).resolve().parents[2]
FIXTURES: Final = ROOT / "scripts" / "fixtures" / "call_sim"
KNOWLEDGE_TOOL: Final = "search_knowledge"


@dataclass(frozen=True, slots=True)
class AgentUnderTest:
    holder: str
    language: str
    direction: str
    system: str
    first_words: str
    max_tokens: int
    #: OpenAI-style function tools, as the model is offered them.
    tools: tuple[dict[str, Any], ...]
    #: The agent's script and facts as one text: what a reply may name without inventing it.
    known: str
    contact_name: str
    prior_contact: bool | None
    #: The script whose steps the step reading judges; None for a script without stages.
    script: CallScript | None
    facts: tuple[tuple[str, str], ...] = ()

    @property
    def prompt_sha(self) -> str:
        return hashlib.sha256(f"{self.system}\n{self.first_words}".encode()).hexdigest()


def system_prompt(cfg: AgentConfig, vendor: str) -> str:
    prompt = compose_engine_prompt(cfg)
    if cfg.script_steps:
        prompt = f"{prompt}\n\n{render_steps(cfg.script_steps)}"
    return f"{prompt}{LAYER_SEPARATOR}{vendor}" if vendor else prompt


def _function(name: str, description: str, params: dict[str, tuple[str, bool]]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    k: {"type": "string", "description": d} for k, (d, _r) in params.items()
                },
                "required": [k for k, (_d, r) in params.items() if r],
            },
        },
    }


def tools_for(cfg: AgentConfig) -> tuple[dict[str, Any], ...]:
    """The platform's own actions as every agent holds them, the knowledge search the prompt
    names, and the config's own actions."""
    from apps.api.reliability.engine_actions import RETIRED_ACTION_NAMES, definitions

    out = [
        _function(
            d.name, d.description, {p.name: (p.description, p.required) for p in d.parameters}
        )
        for d in definitions("thinnest", "call-sim")
        if d.name not in RETIRED_ACTION_NAMES
    ]
    if cfg.knowledge_tool:
        out.append(
            _function(
                cfg.knowledge_tool,
                "Search the business's knowledge for the answer to the caller's question.",
                {"query": ("What to look up, in a few words.", True)},
            )
        )
    for spec in cfg.action_tools:
        out.append(
            _function(
                spec.name,
                spec.description,
                {p.name: (p.description, p.required) for p in spec.params},
            )
        )
    return tuple(out)


def _opening(cfg: AgentConfig, contact_name: str) -> str:
    return substitute_variables(compose_first_utterance(cfg), {"lead_name": contact_name or None})


# --- the fixture ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fixture:
    name: str
    business: str
    agent_name: str
    contact_name: str
    prior_contact: bool | None
    language: str
    facts: tuple[tuple[str, str], ...]
    collect: tuple[CollectField, ...]
    script: CallScript
    #: "outbound" (a campaign placing the call) or "inbound" (a line answering one).
    direction: Literal["inbound", "outbound"] = "outbound"


def load_fixture(name: str) -> Fixture:
    raw = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return Fixture(
        name=name,
        business=raw["business"],
        agent_name=raw["agent_name"],
        contact_name=raw.get("contact_name") or "",
        prior_contact=raw.get("prior_contact"),
        language=raw["language"],
        facts=tuple((q, a) for q, a in raw.get("facts") or ()),
        collect=tuple(CollectField(label=lab) for _key, lab in raw.get("collect") or ()),
        script=CallScript.model_validate(raw["script"]),
        direction="inbound" if raw.get("direction") == "inbound" else "outbound",
    )


def fixture_known(fixture: Fixture, script: CallScript | None = None) -> str:
    """The compiled script. The fixture's facts are its knowledge, reached only by the search
    tool, so a question they answer needs a lookup, as on a real call (`call_mistakes.
    lookup_covered_topics` counts the script and pinned facts only)."""
    return compile_call_script(script or fixture.script, collect=fixture.collect)


def fixture_config(
    fixture: Fixture, *, script: CallScript | None = None, language: str | None = None
) -> AgentConfig:
    """The fixture as a campaign publishes it on day one: its compiled script, its facts in its
    knowledge, both notices on, the stages as the step list. Built the way
    `register_eval.reference_agent` builds its reference agent; a real holder goes through the
    publish path instead."""
    script = script or fixture.script
    language = language or fixture.language
    body = fixture_known(fixture, script)
    steps = native_steps(script)
    posture = DisclosurePosture(
        ai_disclosure_line=ai_disclosure_for(
            language=language, business=fixture.business, name=fixture.agent_name
        ),
        ai_disclosure_enabled=True,
        recording_notice_line=recording_notice_for(language=language),
        recording_notice_enabled=True,
    )
    return AgentConfig(
        tenant_id="call-sim",
        agent_id=f"call-sim-{fixture.name}",
        name=fixture.agent_name,
        business=fixture.business,
        direction=fixture.direction,
        language_primary=language,
        system_prompt=without_outline(body) if steps else body,
        **notice_fields(posture, call_is_recorded=True),
        call_is_recorded=True,
        facts_in_knowledge=True,
        knowledge_tool=KNOWLEDGE_TOOL,
        callbacks_offered=True,
        script_steps=steps,
    )


def fixture_agent(
    name: str,
    *,
    vendor: str = "",
    script: CallScript | None = None,
    prompt: str | None = None,
    language: str | None = None,
) -> AgentUnderTest:
    """`prompt` replaces the whole system prompt (a hand-slimmed candidate); `script` replaces
    the fixture's script and is composed like it."""
    fixture = load_fixture(name)
    cfg = fixture_config(fixture, script=script, language=language)
    return AgentUnderTest(
        holder=f"fixture:{name}",
        language=cfg.language_primary,
        direction=fixture.direction,
        system=prompt if prompt is not None else system_prompt(cfg, vendor),
        first_words=_opening(cfg, fixture.contact_name),
        max_tokens=cfg.max_reply_tokens,
        tools=tools_for(cfg),
        known=fixture_known(fixture, script),
        contact_name=fixture.contact_name,
        prior_contact=fixture.prior_contact,
        script=script or fixture.script,
        facts=fixture.facts,
    )


# --- a real holder ----------------------------------------------------------------------------

_DIRECTORY: Final = "SELECT id FROM organizations ORDER BY id"
_HOLDER_SQL: Final[dict[str, str]] = {
    "campaign": "SELECT script FROM campaigns WHERE id = :h",
    "line": "SELECT script FROM inbound_lines WHERE id = :h AND archived_at IS NULL",
}


def parse_holder(spec: str) -> tuple[str, UUID]:
    kind, _, raw = spec.partition(":")
    if kind not in _HOLDER_SQL or not raw:
        raise ValueError("--holder takes campaign:<uuid> or line:<uuid>")
    return kind, UUID(raw)


async def holder_agent(
    spec: str,
    *,
    vendor: str = "",
    script: CallScript | None = None,
    prompt: str | None = None,
    contact_name: str = "Ravi",
) -> AgentUnderTest:
    """A campaign's or inbound line's agent as its publish would send it, read in its own tenant
    and never written. `contact_name` is a made-up name for a campaign's `{{lead_name}}`."""
    from apps.api.agents import service as agents_service
    from apps.api.db.session import admin_session, tenant_session
    from sqlalchemy import text

    kind, holder_id = parse_holder(spec)
    async with admin_session() as directory:
        tenants = [UUID(str(t)) for t in (await directory.execute(text(_DIRECTORY))).scalars()]
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as session:
            saved = (await session.execute(text(_HOLDER_SQL[kind]), {"h": holder_id})).first()
            if saved is None:
                continue
            build = (
                agents_service.campaign_config if kind == "campaign" else agents_service.line_config
            )
            ident = {"campaign_id": holder_id} if kind == "campaign" else {"line_id": holder_id}
            cfg = await build(session, tenant_id=tenant_id, script=script, **ident)
            stored = script or (CallScript.model_validate(saved[0]) if saved[0] else None)
            outbound = kind == "campaign"
            name = contact_name if outbound else ""
            return AgentUnderTest(
                holder=spec,
                language=cfg.language_primary,
                direction="outbound" if outbound else "inbound",
                system=prompt if prompt is not None else system_prompt(cfg, vendor),
                first_words=_opening(cfg, name),
                max_tokens=cfg.max_reply_tokens,
                tools=tools_for(cfg),
                known=cfg.system_prompt or "",
                contact_name=name,
                # A campaign calls people already on its list; an inbound caller is unknown.
                prior_contact=True if outbound else None,
                script=stored if stored is not None and stored.stages else None,
            )
    raise LookupError(f"{kind} {holder_id} not found")


__all__ = [
    "AgentUnderTest",
    "Fixture",
    "fixture_agent",
    "fixture_config",
    "fixture_known",
    "holder_agent",
    "load_fixture",
    "parse_holder",
    "system_prompt",
    "tools_for",
]
