"""One call's configuration, loaded out of OUR database (`docs/PIPECAT-MIGRATION.md` §2).

**WHAT THIS MODULE IS FOR, IN ONE SENTENCE.** It turns three ids — a call, a tenant, an
agent — into the `SessionConfig` that `pipeline.assemble_call` takes, and it is the only
place in this worker that knows which tables that configuration lives in.

**IT READS A VERSION, NOT AN AGENT, AND THAT IS §1.1's WHOLE DESIGN.** `pipecat_agents`
holds a pointer to the immutable `agent_config_versions` row the control plane last
published, and the prompt and the resolved `ModelConfig` are read FROM THAT ROW rather
than recomposed here. A worker that composed its own prompt would be a second author of
the sentences hard rule 5 requires, and its attestation — `prompt_sha256` recomputed over
what it actually loaded (`pipeline.recompute_prompt_sha256`) — would agree with the
control plane by construction, which is the exact defect the attestation exists to catch.

**HARD RULE 1.** Every statement here runs on a connection whose `app.tenant_id` is
already set, because that GUC is the isolation; the `tenant_id` in the WHERE clause is
belt to its braces (`apps/api/kb/pack.py::_ENTRIES_SQL` makes the same call for the same
reason — a predicate a reviewer can see, over a policy they have to go and read). This
module never opens a connection of its own; see `load_session_config` on who does.

**NO VENDOR SDK, IN THE ONE PACKAGE THAT IS ALLOWED ONE.** `SessionConfig` is plain data
and so is everything on the way to it; the Pipecat legs are built from it in `pipeline.py`.
Hard rule 2's third home (D-592) is a permission, not an instruction.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from calevate_shared.engine import AgentConfig, ModelConfig
from calevate_shared.events import CallDirection
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from voice_worker.pipeline import SessionConfig


class AgentNotRunnableError(RuntimeError):
    """This agent has nothing for a worker to run, so the call cannot be assembled.

    RAISED rather than answered with a default, which is the opposite of the choice
    `knowledge_pack_sha256 = None` gets in the same row — and the asymmetry is the point.
    A missing knowledge pack is an agent that has published nothing, which is an ordinary
    agent; a missing config VERSION is an agent with no prompt, and the prompt is where
    hard rule 5's truthful-answer floor lives. Assembling a call without one would put a
    live caller in front of a model running on whatever system message the vendor defaults
    to.

    Carries ids and never content (hard rule 6): an operator needs to know WHICH agent, and
    a row that does not exist has nothing to quote.
    """


#: One read, three tables, and the join is not a convenience.
#:
#: `pipecat_agents` is the runtime row (what the control plane last published, §1.1),
#: `agent_config_versions` is the immutable content it points at, and `agents` is where the
#: knowledge pack pointer lives (migration `b5d3a91e7c64`). Three round trips would let a
#: publish land between them and produce a `SessionConfig` whose prompt came from one
#: version and whose pack came from the next — a combination that never existed and that no
#: attestation could describe.
#:
#: **`knowledge_pack_sha256` IS SELECTED HERE AND NOWHERE ELSE**, which is the seam this
#: module closes: `kb/pack.refresh_published_pack` writes that column on publish, and until
#: this read existed nothing carried it into the process that answers the phone.
_SESSION_CONFIG_SQL: Final = """
SELECT p.agent_config_version_id,
       p.resolved_config,
       v.composed_prompt,
       v.prompt_sha256,
       v.model_config,
       a.knowledge_pack_sha256
FROM pipecat_agents AS p
JOIN agent_config_versions AS v ON v.id = p.agent_config_version_id
JOIN agents AS a ON a.id = p.agent_id
WHERE p.agent_id = :aid AND p.tenant_id = :tid
"""


async def load_session_config(
    connection: AsyncConnection,
    *,
    call_id: str,
    tenant_id: UUID,
    agent_id: UUID,
    direction: CallDirection,
) -> SessionConfig:
    """The configuration for one call. Raises `AgentNotRunnableError` when there is none.

    **`connection` IS AN ARGUMENT AND THIS MODULE OWNS NO ENGINE, WHICH IS A DECISION.**
    The obvious alternative — a process-global `AsyncEngine` built from `DATABASE_URL`
    right here — would put half a bootstrap in whichever module happened to need the
    database first. The worker's other database citizen is `NormalizedEventSink`, whose
    writer is the next wave (`pipeline.py`, "what is deliberately not here"), and one
    process wants ONE pool sized against ONE workload. So the engine belongs with the
    container entrypoint that owns both; until that entrypoint exists the caller supplies a
    connection — which is also what lets this be tested against a real database through
    `tenant_session`, with the RLS policy genuinely in force rather than mocked away.

    **`direction` IS AN ARGUMENT AND NOT A COLUMN**, because `AgentConfig.direction` may be
    `both`: it says what the agent is ALLOWED to do, and `CallDirection` says what this call
    IS. Deriving one from the other would make every call on a `both` agent claim inbound.

    **`call_id` IS OURS AND IS READ FROM NOWHERE.** §1.2 splits the record: the carrier's
    CDR is reconciled AGAINST this id rather than being its source.
    """
    row = (
        await connection.execute(text(_SESSION_CONFIG_SQL), {"aid": agent_id, "tid": tenant_id})
    ).first()
    if row is None:
        # Ids only (hard rule 6). Both causes are named because they need different people:
        # an agent nobody published is a client-facing state, and an agent whose row this
        # tenant cannot see is an isolation fault.
        raise AgentNotRunnableError(
            f"agent {agent_id} has no published runtime row visible to tenant {tenant_id}"
        )

    version_id, resolved_config, composed_prompt, prompt_sha256, model_config, pack_sha = row
    published = AgentConfig.model_validate(resolved_config)
    models = ModelConfig.model_validate(model_config)

    logger.info(
        "session config loaded",
        call_id=call_id,
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        agent_config_version_id=str(version_id),
        # A digest is an id and is loggable; the prompt it was taken over is not.
        prompt_sha256=prompt_sha256,
        # WHETHER this call has a pack, not which one. The digest is logged by
        # `knowledge.py` on the load itself, and two places logging one id is two places to
        # get hard rule 6 wrong later.
        knowledge_pack=pack_sha is not None,
    )
    return SessionConfig(
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        agent_config_version_id=version_id,
        direction=direction,
        system_prompt=composed_prompt,
        prompt_sha256=prompt_sha256,
        models=models,
        language=_session_language(published, models),
        # EVERY AGENT SPEAKS FIRST, ON BOTH LEGS, AND NO COLUMN DECIDES IT TODAY. D-163
        # makes the AI disclosure and the recording notice sentences the agent VOLUNTEERS
        # at the start of a call, inbound and outbound alike, and a caller cannot be
        # volunteered anything by a pipeline that waits for them to talk first. If a
        # per-agent "listen first" ever becomes a product question it is a column on
        # `agents` and a field on `AgentConfig`, not a default quietly flipped here.
        greet_first=True,
        knowledge_pack_sha256=pack_sha,
    )


def _session_language(published: AgentConfig, models: ModelConfig) -> str | None:
    """The BCP-47 code to pin the transcriber to, or `None` to let it detect.

    `stt_autodetect` WINS, and that is not a preference: D-584 records that no Sarvam model
    on our declared leg accepts `te-IN` at all, so an operator who turned detection on did
    it because pinning was refused on the wire. Sending the pin anyway would re-create the
    refusal the flag exists to route around — `pipeline._language` would hand Pipecat a
    language whose service rejects it at construction.
    """
    if models.stt_autodetect:
        return None
    return published.language_primary


__all__ = ["AgentNotRunnableError", "load_session_config"]
