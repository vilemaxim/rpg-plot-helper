# RPG Plot Helper

Tracks the canon and plots of live-action and tabletop role-playing games, for plot teams, shared-world GMs and solo GMs.

This repo is the web app. Its vocabulary is in [GLOSSARY.md](./GLOSSARY.md) and its design decisions are in [docs/adr/](./docs/adr/).

## Run it on your own machine

You need [Docker](https://docs.docker.com/get-docker/) and [uv](https://docs.astral.sh/uv/). uv installs the right Python and the dependencies the first time you run a command.

Start Postgres:

```sh
scripts/db.sh
```

Start the app:

```sh
uv run manage.py migrate
uv run manage.py runserver
```

Open http://localhost:8000. `migrate` sets up the database; run it the first time and after pulling changes.

### Sign in

There are no passwords. Enter any email address on the sign-in page. Locally the email is not sent: it is printed in the terminal where `runserver` is running. Copy the link from there into your browser and press **Sign in**. A link works once and expires after 15 minutes.

### Run the tests

```sh
uv run manage.py test
```

The tests run against the same Postgres, in a separate database that is created and removed each time, so `scripts/db.sh` must be running. They never use SQLite.

### The database

| Command | What it does |
|---|---|
| `scripts/db.sh` | Starts Postgres on `localhost:5432`. Safe to run again. |
| `scripts/db.sh stop` | Stops it. Your data is kept. |
| `scripts/db.sh destroy` | Stops it and deletes your data. |

If port 5432 is taken, set `PLOTHELPER_DB_PORT` before the first `scripts/db.sh` and put the same port in `DATABASE_URL`, for example:

```sh
export PLOTHELPER_DB_PORT=5433
export DATABASE_URL=postgres://plothelper:plothelper@localhost:5433/plothelper
```

## License

Copyright (C) 2026 Jeffrey Brite

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the [GNU Affero General Public License](./LICENSE) for more details.
