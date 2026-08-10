#!/usr/bin/env bash
# Bring up a working local stack WITHOUT Docker.
#
# `make up` (docker compose) is the documented path and stays the default — use this
# only where Docker is unavailable or its registry is unreachable (a sandboxed CI
# container, a locked-down laptop). It provisions the same three things compose does,
# on the same ports, from distro packages:
#
#   postgres 16 on 5433 · redis on 6380 · roles calevate + calevate_app · migrations
#
# Object storage (MinIO) is NOT provisioned: nothing in the test suite needs it, and
# the one place that does — the recording copy — is stubbed in the smoke test with an
# explanatory comment. If you need it, run MinIO yourself and point OBJECT_STORE_* at it.
#
# Idempotent: safe to re-run.
set -euo pipefail

PG_VERSION="${PG_VERSION:-16}"
PG_PORT="${PG_PORT:-5433}"
REDIS_PORT="${REDIS_PORT:-6380}"
DB_NAME="${DB_NAME:-calevate}"
OWNER_ROLE="${OWNER_ROLE:-calevate}"
APP_ROLE="${APP_ROLE:-calevate_app}"

say() { printf '\033[1;36m==>\033[0m %s\n' "$1"; }

command -v "pg_ctlcluster" >/dev/null || {
  echo "postgresql-common is not installed. Install postgresql-${PG_VERSION} first." >&2
  exit 1
}

say "Setting postgres ${PG_VERSION}/main to port ${PG_PORT}"
CONF="/etc/postgresql/${PG_VERSION}/main/postgresql.conf"
sed -i -E "s/^#?port = [0-9]+/port = ${PG_PORT}/" "$CONF"

if ! pg_lsclusters | grep -qE "^${PG_VERSION}\s+main.*online"; then
  pg_ctlcluster "${PG_VERSION}" main start
else
  pg_ctlcluster "${PG_VERSION}" main restart
fi

say "Creating roles and database (idempotent)"
# The app role is NOSUPERUSER NOBYPASSRLS on purpose: hard rule 1's isolation is only
# real if the role the app connects as cannot bypass a policy.
sudo -u postgres psql -p "${PG_PORT}" -v ON_ERROR_STOP=0 <<SQL >/dev/null 2>&1 || true
CREATE ROLE ${OWNER_ROLE} LOGIN PASSWORD '${OWNER_ROLE}' SUPERUSER;
CREATE ROLE ${APP_ROLE} LOGIN PASSWORD '${APP_ROLE}' NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE ${DB_NAME} OWNER ${OWNER_ROLE};
SQL
PGPASSWORD="${OWNER_ROLE}" psql -h localhost -p "${PG_PORT}" -U "${OWNER_ROLE}" \
  -d "${DB_NAME}" -c "GRANT ALL ON SCHEMA public TO ${APP_ROLE}" >/dev/null

say "Starting redis on ${REDIS_PORT}"
redis-cli -p "${REDIS_PORT}" ping >/dev/null 2>&1 || \
  redis-server --port "${REDIS_PORT}" --daemonize yes

if [ ! -f .env ]; then
  say "Creating .env from .env.example"
  cp .env.example .env
fi

say "Applying migrations"
uv run alembic upgrade head

say "Seeding"
uv run python -m scripts.seed

say "Ready. Verify with: uv run pytest -q"
