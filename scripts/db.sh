#!/usr/bin/env bash
# Start the local Postgres in Docker. Safe to run again: it starts the existing
# container if there is one. Data lives in a Docker volume and survives restarts.
#
#   scripts/db.sh          start it
#   scripts/db.sh stop     stop it (data is kept)
#   scripts/db.sh destroy  stop it and delete the data
set -euo pipefail

name=rpg-plot-helper-db
volume=rpg-plot-helper-db
port="${PLOTHELPER_DB_PORT:-5432}"

case "${1:-start}" in
  start)
    if docker container inspect "$name" >/dev/null 2>&1; then
      docker start "$name" >/dev/null
    else
      docker run --detach --name "$name" \
        --publish "127.0.0.1:${port}:5432" \
        --env POSTGRES_USER=plothelper \
        --env POSTGRES_PASSWORD=plothelper \
        --env POSTGRES_DB=plothelper \
        --volume "$volume:/var/lib/postgresql/data" \
        postgres:17 >/dev/null
    fi
    printf 'Waiting for Postgres'
    for _ in $(seq 60); do
      if docker exec "$name" pg_isready --quiet --host 127.0.0.1 --username plothelper; then
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
