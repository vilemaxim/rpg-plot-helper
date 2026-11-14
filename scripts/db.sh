#!/usr/bin/env bash
# Start the local Postgres in Docker. Safe to run again: it starts the existing
# container if there is one. Data lives in a Docker volume and survives restarts.
#
# The app connects as `plothelper`, an ordinary database user. It must not be a
# superuser: Postgres never applies row-level security to one, and row-level
# security is what keeps each Organization's data apart. `postgres` is the
# superuser, used here only to create that user.
#
#   scripts/db.sh          start it
#   scripts/db.sh stop     stop it (data is kept)
#   scripts/db.sh destroy  stop it and delete the data
set -euo pipefail

name=rpg-plot-helper-db
volume=rpg-plot-helper-db
port="${PLOTHELPER_DB_PORT:-5432}"

# Create the app's database user and its database, if they are not there yet.
# CREATEDB lets the test runner make and drop its own test database.
create_app_user() {
  docker exec --interactive "$name" psql --quiet --username postgres --set ON_ERROR_STOP=1 >/dev/null <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'plothelper') THEN
    CREATE ROLE plothelper LOGIN PASSWORD 'plothelper' CREATEDB;
  ELSIF (SELECT rolsuper FROM pg_roles WHERE rolname = 'plothelper') THEN
    RAISE EXCEPTION 'this database was made by an older scripts/db.sh, with plothelper as a superuser. Run: scripts/db.sh destroy && scripts/db.sh';
  END IF;
END
$$;
SELECT 'CREATE DATABASE plothelper OWNER plothelper'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'plothelper') \gexec
SQL
}

case "${1:-start}" in
  start)
    if docker container inspect "$name" >/dev/null 2>&1; then
      docker start "$name" >/dev/null
    else
      docker run --detach --name "$name" \
        --publish "127.0.0.1:${port}:5432" \
        --env POSTGRES_PASSWORD=postgres \
        --volume "$volume:/var/lib/postgresql/data" \
        postgres:17 >/dev/null
    fi
    printf 'Waiting for Postgres'
    for _ in $(seq 60); do
      if docker exec "$name" pg_isready --quiet --host 127.0.0.1 --username postgres; then
        create_app_user || {
          echo " could not set up the app's database user." >&2
          echo "If this database was made by an older scripts/db.sh, run: scripts/db.sh destroy && scripts/db.sh" >&2
          exit 1
        }
        # Ask Docker for the port: an existing container keeps the one it was made with.
        echo " ready on $(docker port "$name" 5432/tcp | head -n 1)"
        exit 0
      fi
      printf '.'; sleep 1
    done
    echo " did not come up within a minute. See: docker logs $name" >&2
    exit 1
    ;;
  stop)
    docker stop "$name" >/dev/null && echo "stopped"
    ;;
  destroy)
    docker rm --force "$name" >/dev/null 2>&1 || true
    docker volume rm "$volume" >/dev/null 2>&1 || true
    echo "container and data removed"
    ;;
  *)
    echo "usage: scripts/db.sh [start|stop|destroy]" >&2
    exit 2
    ;;
esac
