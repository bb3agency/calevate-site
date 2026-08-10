"""ARQ worker settings.

Run: uv run arq apps.workers.settings.WorkerSettings

Every job is idempotent and keyed (post-call work is keyed by call_id), retries 3
times with exponential backoff, and lands in a DLQ with a Sentry alert on
exhaustion (TRD §8).
"""

from arq.connections import RedisSettings

# Post-call pipeline, embeddings, campaign dispatch, notifications, redaction and
# retention jobs get registered here as they are built (ROADMAP M1).
FUNCTIONS: list[object] = []


class WorkerSettings:
    functions = FUNCTIONS
    redis_settings = RedisSettings()
    max_tries = 3
    job_timeout = 300
