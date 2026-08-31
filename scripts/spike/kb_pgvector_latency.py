"""Measure whether a pgvector hybrid top_k=3 retrieval fits the in-call budget.

WHY THIS EXISTS. `docs/TRD.md` §6 gives in-call retrieval a **100ms budget** and D-28
moved the vector store to a managed API service, marking `kb_chunks` + pgvector a
CONTINGENCY that would be built "only if the bake-off fails". The bake-off never ran, so
the contingency has been carried for months on an argument rather than a number. This
harness produces the number for the contingency arm — the only arm of the three that CAN
be measured from inside this container, because the other two need a vendor credential
and a network path we do not have.

WHAT IT DOES AND DOES NOT MEASURE.

* It measures the **store component**: the time from a Python caller issuing a hybrid
  query over a loopback socket to the rows coming back. That is the same class of
  quantity TRD §6 already has for the tool endpoint's server half (p50 1.0ms, p95 1.4ms
  at one call in flight) and it composes with it, it does not replace it.
* It does NOT measure the ROUND TRIP. The engine's orchestrator is US-hosted
  (`bolna-findings/mirror/pages/concepts/security.md:29`), so an in-call retrieval that
  our server answers costs an ocean crossing this harness never touches. Nor does it
  measure the EMBEDDING of the caller's question, which on any real design is a network
  call to an embedding vendor and is very likely the dominant term. Both are named in the
  report; neither is estimated into it.
* The vectors are synthetic and uniformly random. For LATENCY that is representative or
  mildly pessimistic (a random graph gives HNSW no cluster structure to exploit). For
  RECALL it is meaningless, and this harness therefore reports NO recall figure.

SAFETY. It builds a throwaway database and refuses to touch `calevate`. On the SHARED dev
Postgres it also refuses to run at all while a coverage measurement is scoring that server,
because both the bulk load and the HNSW build are heavy enough to move somebody else's
numbers and turn their CI red for a reason invisible in their diff.

RERUN, on the shared server:

    make up   # if the shared Postgres is not already listening on 5433
    /home/user/calevate-site/.venv/bin/python -m scripts.spike.kb_pgvector_latency

RERUN, on a PRIVATE cluster — which is what was actually used for the figures in the
report, because the shared server was busy with back-to-back coverage runs for the whole
session. Nothing here touches the shared Postgres, so the guard above does not apply:

    mkdir -p /var/tmp/kbspike && chown postgres:postgres /var/tmp/kbspike
    su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /var/tmp/kbspike/data \
        -U calevate --auth=trust"
    su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/kbspike/data \
        -o '-p 55432 -k /var/tmp/kbspike' -l /var/tmp/kbspike/log start"
    /home/user/calevate-site/.venv/bin/python -m scripts.spike.kb_pgvector_latency \
        --dsn postgresql://calevate@127.0.0.1:55432/postgres

    # afterwards
    su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/kbspike/data stop"
    rm -rf /var/tmp/kbspike

⚠ A private cluster removes DATABASE contention, not CPU contention. This machine has 4
cores and the siblings' suites keep it oversubscribed, so record `/proc/loadavg` alongside
any figure — the harness prints it — and read a number taken under load as an UPPER BOUND.

Full options: `--help`. The defaults are the ones whose output is quoted in
`docs/evidence/kb-retrieval-bakeoff.md`; change one and you are reporting a different
experiment, so say which.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

try:
    import psycopg
    from psycopg import sql
except ModuleNotFoundError:  # pragma: no cover - spike, not app code
    sys.exit(
        "psycopg is not importable. This spike is not a workspace dependency; run it "
        "with the root interpreter: /home/user/calevate-site/.venv/bin/python -m "
        "scripts.spike.kb_pgvector_latency"
    )

# The shared dev Postgres. Port 5433 because 5432 is another project's (docker-compose.yml:35).
_SHARED_PORT = 5433
DEFAULT_DSN = f"postgresql://calevate:calevate@localhost:{_SHARED_PORT}/postgres"
PROTECTED_DATABASES = frozenset({"calevate", "postgres", "template0", "template1"})
SPIKE_DB = "kb_spike_pgvector"

# BGE-M3 / Cohere Embed v4 class. D-08 named both before D-28 superseded it; 1024 is also
# the widest dimension either offers at its default, so it is the honest one to measure.
EMBEDDING_DIM = 1024

# Reciprocal Rank Fusion constant. 60 is the value from the paper the technique comes from
# (Cormack, Clarke & Buettcher, SIGIR 2009) and the one every mainstream implementation
# ships as its default; it is not tuned here because tuning it would change RECALL, which
# this harness deliberately does not measure.
RRF_K = 60

# How deep each arm goes before fusion. Fusing top-3 against top-3 would make the hybrid
# nothing but a tie-break, so each arm retrieves a candidate pool and the fusion picks 3.
CANDIDATE_DEPTH = 20

TOP_K = 3

#: The HNSW index is named so EXPLAIN can be attributed to an access method. See
#: `_build_corpus` for the misreading that made this necessary.
HNSW_INDEX = "kb_chunks_hnsw"

# A small vocabulary produces documents that actually share terms, which is what makes the
# sparse arm do work rather than match nothing. Word salad with no overlap would measure an
# empty tsquery and flatter the result.
VOCABULARY = [
    "appointment",
    "booking",
    "clinic",
    "consultation",
    "dentist",
    "cleaning",
    "root",
    "canal",
    "crown",
    "filling",
    "whitening",
    "braces",
    "aligner",
    "extraction",
    "implant",
    "xray",
    "scan",
    "checkup",
    "hygienist",
    "emergency",
    "walkin",
    "timing",
    "sunday",
    "holiday",
    "fee",
    "charge",
    "price",
    "package",
    "discount",
    "insurance",
    "cashless",
    "reimbursement",
    "upi",
    "card",
    "cash",
    "emi",
    "instalment",
    "refund",
    "cancellation",
    "reschedule",
    "parking",
    "address",
    "landmark",
    "metro",
    "bus",
    "wheelchair",
    "lift",
    "waiting",
    "doctor",
    "specialist",
    "orthodontist",
    "paediatric",
    "senior",
    "junior",
    "experience",
    "qualification",
    "registration",
    "council",
    "sterilisation",
    "autoclave",
    "gloves",
    "mask",
    "anaesthesia",
    "sedation",
    "pain",
    "swelling",
    "bleeding",
    "sensitive",
    "gum",
    "tooth",
    "molar",
    "wisdom",
    "denture",
    "bridge",
    "veneer",
    "bonding",
    "polish",
    "scaling",
    "followup",
    "review",
    "report",
    "prescription",
    "medicine",
    "antibiotic",
    "warranty",
    "guarantee",
    "policy",
    "consent",
    "record",
    "referral",
    "second",
    "opinion",
]


@dataclass(frozen=True)
class Sample:
    """One latency distribution, in milliseconds."""

    label: str
    n: int
    p50: float
    p95: float
    p99: float
    maximum: float
    mean: float

    @classmethod
    def of(cls, label: str, timings_ms: list[float]) -> Sample:
        ordered = sorted(timings_ms)
        return cls(
            label=label,
            n=len(ordered),
            p50=_percentile(ordered, 0.50),
            p95=_percentile(ordered, 0.95),
            p99=_percentile(ordered, 0.99),
            maximum=ordered[-1],
            mean=statistics.fmean(ordered),
        )


def _percentile(ordered: list[float], q: float) -> float:
    """Nearest-rank percentile.

    Chosen over interpolation because at these sample sizes an interpolated p95 is a
    number no observation produced, and the point of the exercise is to report observed
    latencies rather than modelled ones.
    """
    if not ordered:
        raise ValueError("no observations")
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def _refuse_if_measurement_running(dsn: str, force: bool) -> None:
    """Refuse to add load to the SHARED dev Postgres while a coverage run is scoring it.

    Scoped to the shared server rather than applied blindly, and the distinction is the
    whole point: the harm this prevents is somebody else's CI going red for a reason
    invisible in their diff, and that harm only exists on the server their suite is using.
    A private cluster (see `--dsn`, and the recipe in the module docstring) is nobody
    else's, so refusing there would block the one escape hatch that makes this measurable
    while the shared server is busy.

    Deliberately a refusal rather than a warning on the server it does guard.
    """
    if force or f":{_SHARED_PORT}/" not in dsn:
        return
    probe = subprocess.run(
        ["pgrep", "-f", "coverage run -m pytest"], capture_output=True, text=True, check=False
    )
    if probe.returncode == 0:
        sys.exit(
            f"REFUSING: a coverage measurement is running against the shared Postgres on "
            f"port {_SHARED_PORT}. Either wait for `pgrep -f 'coverage run -m pytest'` to "
            f"return nothing, or measure on a private cluster instead — the module "
            f"docstring has the three commands that build one. --force overrides."
        )


def _loadavg() -> str:
    """1/5/15-minute load average, recorded beside every figure.

    This machine has 4 cores and sibling suites keep it oversubscribed, so a latency
    number without the load it was taken under is uninterpretable. Recording it makes a
    contended run honest — an UPPER BOUND — instead of silently wrong.
    """
    try:
        return " ".join(f"{value:.2f}" for value in os.getloadavg())
    except OSError:  # pragma: no cover - spike, not app code
        return "unavailable"


def _random_vector_literal(rng: random.Random) -> str:
    """A pgvector text literal.

    Not normalised: the queries use cosine distance (`<=>`), which normalises internally,
    so a unit-norm pass would cost time and change nothing measured here.
    """
    return "[" + ",".join(f"{rng.random() * 2 - 1:.5f}" for _ in range(EMBEDDING_DIM)) + "]"


def _random_chunk_text(rng: random.Random) -> str:
    """~300 tokens, the midpoint of TRD §6.1's 200-400 band."""
    return " ".join(rng.choice(VOCABULARY) for _ in range(300))


def _create_spike_database(dsn: str, db_name: str) -> str:
    if db_name in PROTECTED_DATABASES:
        sys.exit(f"REFUSING: {db_name!r} is a protected database. This spike builds its own.")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name)))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
    return dsn.rsplit("/", 1)[0] + "/" + db_name


def _build_corpus(
    conn: psycopg.Connection[Any], *, tenants: int, agents: int, chunks_per_agent: int, seed: int
) -> tuple[list[tuple[str, str]], float]:
    """Load the table and index it.

    The table and the three indexes are the CONTINGENCY schema this repository already
    specified for exactly this arm (`docs/DATA-MODEL.md:348-352`), not a shape invented
    here — so a number measured on it transfers to the thing that would actually be built.
    Returns the (tenant_id, agent_id) pairs and the HNSW build seconds.
    """
    rng = random.Random(seed)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(
        f"""
        CREATE TABLE kb_chunks (
            id             uuid PRIMARY KEY,
            tenant_id      uuid NOT NULL,
            agent_id       uuid NOT NULL,
            document_id    uuid NOT NULL,
            content        text NOT NULL,
            tsv            tsvector GENERATED ALWAYS AS
                               (to_tsvector('english', content)) STORED,
            embedding      vector({EMBEDDING_DIM}) NOT NULL,
            embed_model    text NOT NULL,
            embed_version  text NOT NULL,
            chunk_meta     jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            version        int NOT NULL,
            is_active      boolean NOT NULL
        )
        """
    )
    # Agents of one tenant share that tenant's id — the scope predicate is (tenant, agent),
    # and generating a fresh tenant id per agent would silently measure a table of
    # single-agent tenants instead of the multi-agent shape being asked for.
    scopes = [
        (tenant_id, _uuid_from(rng))
        for tenant_id in [_uuid_from(rng) for _ in range(tenants)]
        for _ in range(agents)
    ]

    with conn.cursor().copy(
        "COPY kb_chunks (id, tenant_id, agent_id, document_id, content, embedding, "
        "embed_model, embed_version, version, is_active) FROM STDIN"
    ) as copy:
        for tenant_id, agent_id in scopes:
            document_id = _uuid_from(rng)
            for _ in range(chunks_per_agent):
                copy.write_row(
                    (
                        _uuid_from(rng),
                        tenant_id,
                        agent_id,
                        document_id,
                        _random_chunk_text(rng),
                        _random_vector_literal(rng),
                        "bge-m3",
                        "1",
                        1,
                        True,
                    )
                )

    conn.execute("CREATE INDEX ON kb_chunks USING gin (tsv)")
    conn.execute("CREATE INDEX ON kb_chunks (tenant_id, agent_id, is_active)")

    # HNSW rather than IVFFlat, and the reason is operational rather than a benchmark
    # result. IVFFlat's lists are TRAINED on the rows present when the index is built, so a
    # knowledge base that grows by client upload drifts away from its own partitioning and
    # has to be REINDEXed to recover recall; HNSW is incremental and has no such cliff. It
    # also has no build-time minimum row count, which an SMB corpus of a few hundred chunks
    # would otherwise trip. DATA-MODEL.md:351 had already chosen HNSW; this spike measures
    # that choice rather than reopening it.
    # Named rather than auto-named, so the plan can be attributed. Postgres would call it
    # `kb_chunks_embedding_idx`, which reads in EXPLAIN as an ordinary "Index Scan using
    # kb_chunks_embedding_idx" and says nothing about the access method — the first run of
    # this harness reported "HNSW: False" for a plan that was in fact using it.
    started = time.perf_counter()
    conn.execute(f"CREATE INDEX {HNSW_INDEX} ON kb_chunks USING hnsw (embedding vector_cosine_ops)")
    build_seconds = time.perf_counter() - started

    conn.execute("VACUUM ANALYZE kb_chunks")
    return scopes, build_seconds


def _uuid_from(rng: random.Random) -> str:
    raw = rng.getrandbits(128)
    hexed = f"{raw:032x}"
    return f"{hexed[:8]}-{hexed[8:12]}-{hexed[12:16]}-{hexed[16:20]}-{hexed[20:]}"


# The scope predicate is the one the contingency index was specified for
# (`docs/DATA-MODEL.md:352`): retrieval is per-AGENT, not per-tenant, because an agent is
# what a caller is talking to and what a knowledge source is published against.
SCOPE = "tenant_id = %(tenant)s AND agent_id = %(agent)s AND is_active"

DENSE_SQL = f"""
SELECT id FROM kb_chunks
WHERE {SCOPE}
ORDER BY embedding <=> %(qvec)s
LIMIT %(depth)s
"""

SPARSE_SQL = f"""
SELECT id FROM kb_chunks, plainto_tsquery('english', %(qtext)s) AS q
WHERE {SCOPE} AND tsv @@ q
ORDER BY ts_rank_cd(tsv, q) DESC
LIMIT %(depth)s
"""

# One statement, so the measurement is one round trip — which is what an in-call handler
# would actually issue. Splitting the arms into two queries would add a loopback hop that
# a real implementation would not pay.
HYBRID_SQL = f"""
WITH dense AS (
    SELECT id, row_number() OVER () AS rank
    FROM (
        SELECT id FROM kb_chunks
        WHERE {SCOPE}
        ORDER BY embedding <=> %(qvec)s
        LIMIT %(depth)s
    ) d
), sparse AS (
    SELECT id, row_number() OVER () AS rank
    FROM (
        SELECT id FROM kb_chunks, plainto_tsquery('english', %(qtext)s) AS q
        WHERE {SCOPE} AND tsv @@ q
        ORDER BY ts_rank_cd(tsv, q) DESC
        LIMIT %(depth)s
    ) s
), fused AS (
    SELECT
        COALESCE(dense.id, sparse.id) AS id,
        COALESCE(1.0 / ({RRF_K} + dense.rank), 0)
      + COALESCE(1.0 / ({RRF_K} + sparse.rank), 0) AS score
    FROM dense FULL OUTER JOIN sparse ON dense.id = sparse.id
)
SELECT c.id, c.content
FROM fused JOIN kb_chunks c ON c.id = fused.id
ORDER BY fused.score DESC
LIMIT {TOP_K}
"""


# A semantic cache is the one in-call mitigation that can be measured from here rather
# than argued about. The premise is that an SMB's callers ask a small number of distinct
# questions, so a hit is a top-1 nearest-neighbour lookup against a table two orders of
# magnitude smaller than the corpus, returning a PRE-COMPOSED answer — no fusion, no
# candidate pool, no join back to the chunks. The threshold is applied by the caller on
# the returned distance rather than in SQL, because a WHERE on the distance would defeat
# the index scan; the query therefore measures the same work a real hit-or-miss does.
CACHE_SQL = """
SELECT answer, embedding <=> %(qvec)s AS distance
FROM kb_semantic_cache
WHERE tenant_id = %(tenant)s AND agent_id = %(agent)s
ORDER BY embedding <=> %(qvec)s
LIMIT 1
"""


def _build_semantic_cache(
    conn: psycopg.Connection[Any],
    *,
    scopes: list[tuple[str, str]],
    entries_per_agent: int,
    seed: int,
) -> Callable[[], dict[str, Any]]:
    """Populate the cache and return a factory that probes it with REAL cached questions.

    The probe vectors are drawn from the cached rows themselves, perturbed slightly. That
    is deliberate: this measurement is of the HIT path, which is the only path whose
    latency is a reason to build a cache at all. A miss costs the cache lookup plus the
    full retrieval below it, so it is the sum of two rows in this table, not a third one.
    """
    rng = random.Random(seed)
    conn.execute(
        f"""
        CREATE TABLE kb_semantic_cache (
            id         uuid PRIMARY KEY,
            tenant_id  uuid NOT NULL,
            agent_id   uuid NOT NULL,
            question   text NOT NULL,
            answer     text NOT NULL,
            embedding  vector({EMBEDDING_DIM}) NOT NULL
        )
        """
    )
    cached: list[tuple[str, str, str]] = []
    with conn.cursor().copy(
        "COPY kb_semantic_cache (id, tenant_id, agent_id, question, answer, embedding) FROM STDIN"
    ) as copy:
        for tenant_id, agent_id in scopes:
            for _ in range(entries_per_agent):
                vector = _random_vector_literal(rng)
                cached.append((tenant_id, agent_id, vector))
                copy.write_row(
                    (
                        _uuid_from(rng),
                        tenant_id,
                        agent_id,
                        " ".join(rng.choice(VOCABULARY) for _ in range(8)),
                        " ".join(rng.choice(VOCABULARY) for _ in range(40)),
                        vector,
                    )
                )
    conn.execute("CREATE INDEX ON kb_semantic_cache (tenant_id, agent_id)")
    conn.execute("CREATE INDEX ON kb_semantic_cache USING hnsw (embedding vector_cosine_ops)")
    conn.execute("VACUUM ANALYZE kb_semantic_cache")

    probe_rng = random.Random(seed + 1)

    def params() -> dict[str, Any]:
        tenant_id, agent_id, vector = probe_rng.choice(cached)
        return {"tenant": tenant_id, "agent": agent_id, "qvec": vector}

    return params


def _time_query(
    conn: psycopg.Connection[Any],
    statement: str,
    params_for: Any,
    *,
    label: str,
    warmups: int,
    iterations: int,
) -> Sample:
    for _ in range(warmups):
        conn.execute(statement, params_for()).fetchall()
    timings: list[float] = []
    for _ in range(iterations):
        params = params_for()
        started = time.perf_counter()
        conn.execute(statement, params).fetchall()
        timings.append((time.perf_counter() - started) * 1000.0)
    return Sample.of(label, timings)


def _measure_filter_yield(
    conn: psycopg.Connection[Any], params_for: Callable[[], dict[str, Any]], *, trials: int
) -> dict[str, Any]:
    """How many rows the FILTERED dense arm actually returns out of the depth requested.

    This is not a performance number, it is a CORRECTNESS one, and on this pgvector it is
    the decisive fact about multi-tenancy. An HNSW scan walks the graph over the WHOLE
    index and the scope predicate is applied to what the walk produces, so a scan bounded
    by `hnsw.ef_search` can surface far fewer than `LIMIT` rows for the agent being asked
    about — silently, as a short result rather than an error. pgvector only gained
    iterative index scans, which re-enter the graph until the LIMIT is satisfied, in
    **0.8.0** (`CHANGELOG.md`, "0.8.0 (2024-10-30) - Added support for iterative index
    scans", read from github.com/pgvector/pgvector on 31 Aug 2026), and the server here
    has 0.6.0. A short result is a RECALL failure that looks like a working query, which
    is exactly the class of defect this repository writes gates for, so it is measured
    rather than reasoned about.
    """
    # Which access path the planner actually chose. Without this the latency table is
    # uninterpretable: a sequential scan over a small table is fast for a reason that does
    # not survive growth, and reporting it as an HNSW figure would be the more flattering
    # of two very different results.
    plan_rows = conn.execute(f"EXPLAIN {DENSE_SQL}", params_for()).fetchall()
    plan = " ".join(str(row[0]).strip() for row in plan_rows)

    yields: list[int] = []
    for _ in range(trials):
        rows = conn.execute(DENSE_SQL, params_for()).fetchall()
        yields.append(len(rows))
    return {
        "dense_plan": plan,
        # Attribution by INDEX NAME, not by the word "hnsw": an ordinary
        # `Index Scan using <name>` names the index and never the access method, so a
        # substring search for "hnsw" reports a false negative on the one plan that
        # matters. A `Sort` node here means Postgres chose EXACT nearest-neighbour over
        # the approximate index, which is a better answer rather than a worse one.
        "used_hnsw": HNSW_INDEX in plan,
        "exact_scan": "Sort" in plan,
        "requested_depth": CANDIDATE_DEPTH,
        "trials": trials,
        "min_returned": min(yields),
        "median_returned": statistics.median(yields),
        "max_returned": max(yields),
        "trials_short_of_depth": sum(1 for count in yields if count < CANDIDATE_DEPTH),
        "trials_below_top_k": sum(1 for count in yields if count < TOP_K),
    }


def _query_params_factory(
    rng: random.Random, scopes: list[tuple[str, str]]
) -> Callable[[], dict[str, Any]]:
    """A fresh query per iteration, so nothing is answered from a repeated plan or a hit.

    Every call draws a NEW random probe vector and a NEW eight-word question. Reusing one
    query would measure Postgres returning a cached result set, which is not the quantity
    an in-call retrieval pays.
    """

    def params() -> dict[str, Any]:
        tenant_id, agent_id = rng.choice(scopes)
        return {
            "tenant": tenant_id,
            "agent": agent_id,
            "qvec": _random_vector_literal(rng),
            "qtext": " ".join(rng.choice(VOCABULARY) for _ in range(8)),
            "depth": CANDIDATE_DEPTH,
        }

    return params


def run(args: argparse.Namespace) -> dict[str, Any]:
    _refuse_if_measurement_running(args.dsn, args.force)
    spike_dsn = _create_spike_database(args.dsn, args.database)
    results: dict[str, Any] = {
        "embedding_dim": EMBEDDING_DIM,
        "top_k": TOP_K,
        "candidate_depth": CANDIDATE_DEPTH,
        "rrf_k": RRF_K,
        "iterations": args.iterations,
        "cores": os.cpu_count(),
        "loadavg_at_start": _loadavg(),
        "shapes": [],
    }

    with psycopg.connect(spike_dsn, autocommit=True) as conn:
        results["postgres_version"] = conn.execute("SELECT version()").fetchone()[0]  # type: ignore[index]
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        results["pgvector_version"] = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()[0]  # type: ignore[index]
        results["hnsw_ef_search"] = conn.execute("SHOW hnsw.ef_search").fetchone()[0]  # type: ignore[index]
        # The server settings that decide whether these figures are optimistic or
        # pessimistic, captured rather than assumed. A stock `initdb` gives 128MB of
        # shared_buffers and 64MB of maintenance_work_mem, which for a 1024-dim corpus of
        # any size means the table does not fit in cache and the HNSW graph does not fit in
        # the build memory. Numbers taken under those settings are an UPPER BOUND: a tuned
        # server does better, never worse. Reporting them without the settings would be
        # reporting a number nobody could reproduce or interpret.
        for setting in (
            "shared_buffers",
            "maintenance_work_mem",
            "work_mem",
            "max_parallel_maintenance_workers",
            "effective_cache_size",
        ):
            results[setting] = conn.execute(f"SHOW {setting}").fetchone()[0]  # type: ignore[index]
        conn.execute("DROP EXTENSION vector")

    for tenants, agents, per_agent in args.shape:
        spike_dsn = _create_spike_database(args.dsn, args.database)
        with psycopg.connect(spike_dsn, autocommit=True) as conn:
            scopes, build_seconds = _build_corpus(
                conn, tenants=tenants, agents=agents, chunks_per_agent=per_agent, seed=args.seed
            )
            rng = random.Random(args.seed + 1)
            size = conn.execute("SELECT pg_total_relation_size('kb_chunks')").fetchone()[0]  # type: ignore[index]

            params = _query_params_factory(rng, scopes)
            cache_params = _build_semantic_cache(
                conn, scopes=scopes, entries_per_agent=args.cache_entries, seed=args.seed + 2
            )

            shape = {
                "tenants": tenants,
                "agents_per_tenant": agents,
                "chunks_per_agent": per_agent,
                "total_chunks": tenants * agents * per_agent,
                "hnsw_build_seconds": round(build_seconds, 2),
                "total_relation_bytes": size,
                "loadavg": _loadavg(),
                "filter_yield": _measure_filter_yield(conn, params, trials=args.iterations),
                "samples": [
                    asdict(
                        _time_query(
                            conn,
                            statement,
                            factory,
                            label=label,
                            warmups=args.warmups,
                            iterations=args.iterations,
                        )
                    )
                    for label, statement, factory in (
                        ("dense-only", DENSE_SQL, params),
                        ("sparse-only", SPARSE_SQL, params),
                        ("hybrid-rrf", HYBRID_SQL, params),
                        ("semantic-cache", CACHE_SQL, cache_params),
                    )
                ],
            }
            results["shapes"].append(shape)
            _print_shape(shape)

    if not args.keep:
        drop = sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(args.database))
        with psycopg.connect(args.dsn, autocommit=True) as conn:
            conn.execute(drop)
    return results


def _print_shape(shape: dict[str, Any]) -> None:
    total = shape["total_chunks"]
    print(
        f"\n=== {shape['tenants']} tenant(s) x {shape['agents_per_tenant']} agent(s) x "
        f"{shape['chunks_per_agent']} chunks = {total:,} rows | table+indexes "
        f"{shape['total_relation_bytes'] / 1e6:.0f} MB | HNSW build "
        f"{shape['hnsw_build_seconds']}s ==="
    )
    print(f"{'query':<14}{'n':>6}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}   (ms)")
    for sample in shape["samples"]:
        print(
            f"{sample['label']:<14}{sample['n']:>6}{sample['p50']:>9.2f}"
            f"{sample['p95']:>9.2f}{sample['p99']:>9.2f}{sample['maximum']:>9.2f}"
        )
    yielded = shape["filter_yield"]
    print(
        f"filtered dense arm returned min/median/max "
        f"{yielded['min_returned']}/{yielded['median_returned']:.0f}/"
        f"{yielded['max_returned']} of {yielded['requested_depth']} requested; "
        f"{yielded['trials_short_of_depth']}/{yielded['trials']} short of depth, "
        f"{yielded['trials_below_top_k']} below top_k={TOP_K}"
    )
    print(f"dense plan uses HNSW: {yielded['used_hnsw']} | {yielded['dense_plan'][:160]}")
    print(f"loadavg during this shape: {shape['loadavg']}")


def _shape(raw: str) -> tuple[int, int, int]:
    tenants, agents, per_agent = raw.split("x")
    return int(tenants), int(agents), int(per_agent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="maintenance DSN (default: %(default)s)")
    parser.add_argument("--database", default=SPIKE_DB, help="throwaway db name")
    parser.add_argument(
        "--shape",
        type=_shape,
        nargs="+",
        default=[(1, 1, 500), (1, 1, 2000), (50, 2, 1000)],
        help=(
            "TENANTSxAGENTSxCHUNKS corpora to measure. Defaults are one median SMB with "
            "one agent (500 chunks), one large SMB (2000), and the shared multi-tenant "
            "table at 50 clients x 2 agents x 1000 = 100,000 rows."
        ),
    )
    parser.add_argument(
        "--cache-entries",
        type=int,
        default=200,
        help="semantic-cache rows per agent (default: %(default)s)",
    )
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--warmups", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument("--keep", action="store_true", help="do not drop the spike database")
    parser.add_argument("--force", action="store_true", help="run even if coverage is measuring")
    parser.add_argument("--json", help="also write the full result here")
    args = parser.parse_args(argv)

    results = run(args)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
