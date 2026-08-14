"""Which script arm a call gets, decided once and written down.

THE PROPERTY THIS FILE EXISTS FOR
----------------------------------
Which variant a call ran is a FACT ABOUT THAT CALL. It must be recoverable from the row
for as long as the row exists, and it must not change when anything else does.

That rules out the obvious implementation — `random.random() < split` at dial time, or
worse, `hash(phone) % 100 < split` evaluated in the REPORTING query. The second one is
the trap, because it looks reproducible: it produces a stable answer for a fixed split,
and then an operator ramps 50/50 to 80/20 and every historical call silently
re-attributes to the arm it never ran. Every conversion rate on the screen changes, and
nothing in the audit trail says why.

So: the bucket is DETERMINISTIC (so it can be reproduced and explained), and the
resulting variant is RECORDED (so it never has to be). `call_variant_assignments` is
that record, written in the same transaction as the `calls` row.

THE ASSIGNMENT UNIT IS THE PERSON, NOT THE CALL
------------------------------------------------
The hash input is the lead id when we have one and the destination number otherwise —
not the call id. Two reasons, and the first is the one that matters:

* **A repeat contact must hear the same script.** A prospect called twice in a campaign
  ladder who gets greeting A on Monday and greeting B on Wednesday has been given an
  experience neither arm describes, and their conversion belongs to neither. This is the
  standard experimentation practice of randomising by the stable unit rather than by the
  event; per-call randomisation buys marginally better balance and pays for it with
  contaminated units.
* It also makes the retry ladder in `campaigns` free of experiment side effects: attempt
  2 and attempt 3 land in the arm attempt 1 did, with no state to carry.

The experiment id is mixed into the hash as a salt so a SECOND experiment on the same
agent does not reproduce the first one's split — without it, every contact that landed
in A last month lands in A again, and the two experiments are correlated in a way no
reader would suspect.

blake2b rather than Python's `hash()`: `hash()` on a `str` is randomised per process by
PYTHONHASHSEED, so the "deterministic" bucket would differ between the API worker that
dialled and any process that tried to explain it. A cryptographic digest is overkill for
uniformity and exactly right for reproducibility. It is NOT a security boundary and is
not treated as one.

TWO WAYS A CALL LEARNS ITS ARM, AND ONLY ONE OF THEM DRAWS A BUCKET
--------------------------------------------------------------------
`assign` is the dial path: we are choosing to call, so we draw. `arm_of_engine_ref` is
the observation path: the engine has told us which agent object ran a call, and an arm
is its own agent object, so the arm is simply read off. Both write through `record`, so
both produce the same kind of row — a fact, written with the `calls` row.

There is deliberately no third way, and in particular nothing draws a bucket AFTER a
call. See `arm_of_engine_ref` for why that would be a fabrication rather than a feature.

PII: the destination number is hashed, never stored here and never logged (hard rule 6).
The assignment row carries ids only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.models import SPLIT_TOTAL_BP
from apps.api.db.base import uuid7

# The bucket space. Basis points, so it matches `weight_bp` exactly and a 2.5% ramp is
# expressible — a percent-wide space would silently round one.
BUCKETS = SPLIT_TOTAL_BP


@dataclass(frozen=True, slots=True)
class VariantArm:
    """One arm as the dial path needs it: who to dial as, and what to record."""

    variant_id: UUID
    label: str
    weight_bp: int
    engine_agent_ref: str | None


@dataclass(frozen=True, slots=True)
class Assignment:
    experiment_id: UUID
    arm: VariantArm


def bucket_of(experiment_id: UUID, unit_key: str) -> int:
    """A stable integer in [0, BUCKETS) for this contact in this experiment.

    Same inputs, same answer, in any process, on any day, forever — which is the whole
    contract. `digest_size=8` gives 64 bits, so the modulo bias against a 10,000-wide
    space is on the order of 1e-15 and cannot be observed by any experiment this
    platform will ever run.
    """
    digest = hashlib.blake2b(f"{experiment_id}:{unit_key}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % BUCKETS


def pick_arm(arms: list[VariantArm], bucket: int) -> VariantArm:
    """The arm this bucket falls in, walking the arms in LABEL order.

    Label order rather than insertion order or id order: it is the only ordering that is
    stable across every reader and visible to the operator, so "bucket 3,200 is in A" can
    be checked by hand from the screen.
    """
    edge = 0
    for arm in sorted(arms, key=lambda a: a.label):
        edge += arm.weight_bp
        if bucket < edge:
            return arm
    # Reachable only if the weights do not sum to BUCKETS, which `experiments.py`
    # refuses to write. Falling through to the last arm rather than raising: a dial in
    # flight must not fail because a split is malformed, and the last arm is a script
    # this agent is genuinely running.
    return sorted(arms, key=lambda a: a.label)[-1]


_RUNNING_SQL = (
    "SELECT e.id, v.id, v.label, v.weight_bp, v.engine_agent_ref "
    "FROM prompt_experiments e JOIN prompt_experiment_variants v ON v.experiment_id = e.id "
    "WHERE e.agent_id = :aid AND e.status = 'running' ORDER BY v.label"
)


async def running_arms(
    session: AsyncSession, agent_id: UUID
) -> tuple[UUID, list[VariantArm]] | None:
    """The live experiment on this agent and its arms, or None.

    One query on the dial path. It runs inside the caller's tenant session, so an
    experiment belonging to another tenant is not merely filtered out, it is invisible.
    """
    rows = (await session.execute(text(_RUNNING_SQL), {"aid": agent_id})).all()
    if not rows:
        return None
    return UUID(str(rows[0][0])), [
        VariantArm(
            variant_id=UUID(str(r[1])),
            label=str(r[2]),
            weight_bp=int(r[3]),
            engine_agent_ref=r[4],
        )
        for r in rows
    ]


_ARM_BY_REF_SQL = (
    "SELECT e.id, v.id, v.label, v.weight_bp, v.engine_agent_ref "
    "FROM prompt_experiment_variants v "
    "JOIN prompt_experiments e ON e.id = v.experiment_id "
    "WHERE v.engine_agent_ref = :ref AND e.status = 'running'"
)


async def arm_of_engine_ref(session: AsyncSession, *, engine_agent_ref: str) -> Assignment | None:
    """The arm whose OWN engine agent ran this call, as reported by the engine.

    This is the other half of `assign`, and the difference between them is the whole of
    inbound attribution.

    `assign` DECIDES: we are about to dial, so we draw the bucket and then dial the arm
    we drew. Nothing decides an inbound call — the caller dialled a number, the engine
    answered it with whatever agent object that number is attached to, and the script
    was fixed before the phone rang. The only honest question left is a question of
    fact: WHICH engine agent answered? The engine tells us, in
    `ExecutionSnapshot.engine_agent_ref`, and `publish_variant` gave every arm its own
    ref precisely so that answer is unambiguous.

    So a call is attributed here if and only if the engine says an arm's own agent ran
    it. An inbound call answered by the AGENT's ref ran neither arm and gets nothing —
    drawing a bucket for it at post-call time would invent an arm the caller never
    heard, which is the one failure mode this feature cannot survive.

    Same stored-fact property as the dial path: the caller writes the row in the same
    transaction as the `calls` row, and `record`'s ON CONFLICT keeps the first write.
    `status = 'running'` scopes it, so a late webhook naming a RETIRED arm attributes
    nothing to a concluded experiment.
    """
    row = (await session.execute(text(_ARM_BY_REF_SQL), {"ref": engine_agent_ref})).first()
    if row is None:
        return None
    return Assignment(
        experiment_id=UUID(str(row[0])),
        arm=VariantArm(
            variant_id=UUID(str(row[1])),
            label=str(row[2]),
            weight_bp=int(row[3]),
            engine_agent_ref=row[4],
        ),
    )


async def assign(session: AsyncSession, *, agent_id: UUID, unit_key: str) -> Assignment | None:
    """Decide the arm for a call about to be placed, or None when nothing is running."""
    running = await running_arms(session, agent_id)
    if running is None:
        return None
    experiment_id, arms = running
    return Assignment(
        experiment_id=experiment_id,
        arm=pick_arm(arms, bucket_of(experiment_id, unit_key)),
    )


async def record(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    assignment: Assignment,
) -> None:
    """Write the fact. Same transaction as the `calls` row, by construction — the caller
    holds one session and does both.

    `ON CONFLICT DO NOTHING` on the call: a replayed dispatch must not move a call
    between arms. First write wins, and there is no second.
    """
    await session.execute(
        text(
            "INSERT INTO call_variant_assignments (id, tenant_id, call_id, experiment_id, "
            "variant_id, created_at, updated_at) VALUES (:id, :tid, :cid, :eid, :vid, "
            "now(), now()) ON CONFLICT (call_id) DO NOTHING"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "cid": call_id,
            "eid": assignment.experiment_id,
            "vid": assignment.arm.variant_id,
        },
    )


__all__ = [
    "BUCKETS",
    "Assignment",
    "VariantArm",
    "arm_of_engine_ref",
    "assign",
    "bucket_of",
    "pick_arm",
    "record",
    "running_arms",
]
