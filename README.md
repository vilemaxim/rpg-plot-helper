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

There are no passwords. Enter any email address on the sign-in page. The first time an address signs in, it gets an Organization and a first World of its own. Locally the email is not sent: it is printed in the terminal where `runserver` is running. Copy the link from there into your browser and press **Sign in**. A link works once and expires after 15 minutes.

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

## Who may create an Organization

One setting, `OPEN_SIGN_UP`, decides this. It is read from the environment.

| `OPEN_SIGN_UP` | What happens | Who it suits |
|---|---|---|
| not set, or `false` | The first person to sign in gets the one Organization and its first World. Anyone who signs in after that is told they need an invitation. | A self-hosted copy for one group. This is the default, so a copy on the internet does not hand an Organization to every stranger. |
| `true` | Everyone who signs in for the first time gets an Organization and a World of their own. | A public host serving many groups, or a self-hoster who hosts for partner groups. |

Local development turns it on, so you can try the app with several email addresses. To see what a self-hosted copy does, start the app with `OPEN_SIGN_UP=false uv run manage.py runserver`.

The data is stored the same way in both cases. See [ADR-0005](./docs/adr/0005-one-setting-decides-who-may-create-an-organization.md).

## How Organizations are kept apart

Each Organization's data is kept apart twice: once by the app's own checks, and once by Postgres row-level security underneath them. Every request tells the database who is asking and which Organization they are working in, and the database returns only that Organization's rows. With nothing set, a query returns no rows at all. The one exception is that a person can always see the Organizations they belong to and their own membership of each, which is how the app finds out where they may work.

This guards against a mistake in the app's queries. It is not a guard against the app running arbitrary SQL, because the app's database user owns the tables.

Two things follow for anyone running or changing the app:

- **The app must not connect as a database superuser**, or as a user marked `BYPASSRLS`. Postgres skips row-level security for both. `scripts/db.sh` creates an ordinary user, `plothelper`, and `uv run manage.py migrate` refuses to run as the wrong kind. `runserver` does not check, so always migrate first.
- **A new table that holds an Organization's data needs an `organization` column and a policy.** Add `rls.protect("<table name>")` to its migration, and `rls.same_organization(...)` for each column that points at another Organization-owned table; see `organizations/rls.py`.

If your local database was created before this was added, recreate it: `scripts/db.sh destroy && scripts/db.sh`, then `uv run manage.py migrate`.

## License

Copyright (C) 2026 Jeffrey Brite

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the [GNU Affero General Public License](./LICENSE) for more details.
