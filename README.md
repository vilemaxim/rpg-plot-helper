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

There are no passwords. Enter any email address on the sign-in page. Locally, an address that belongs to no Organization and has not been invited to one gets one of its own, with a first World, when it signs in. Locally the email is not sent: it is printed in the terminal where `runserver` is running. Copy the link from there into your browser and press **Sign in**. A link works once and expires after 15 minutes.

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

## Importing and browsing a World

A World's Canon arrives as files. A Plot Master of a World uploads one `.zip` of them from the link on the World's page, and everyone who can open that World can then browse it: Campaigns, Events, Mods, Plots, NPCs, factions, locations, PCs, After-Action Reports and timeline entries, each with a list and a page per item. A Mod's page shows its state, its Events and its Features, and each of those links to its own page. Every page also lists what refers to it, so a Campaign shows its Events and Mods, and an NPC shows the Mods that feature them and the reports that changed them.

To try it, make a zip of the sample World that ships with [plotcanon](https://github.com/vilemaxim/plotcanon):

```sh
uv run plotcanon sample --write demo
zip -r demo.zip demo
```

Things to know:

- **All or nothing.** The whole World is checked by plotcanon first. If anything in it is invalid, nothing is imported and the errors are shown, worded so they can be pasted back into the LLM that wrote the files.
- **Only into an empty World.** A World that already has Canon cannot be imported into. An Organization Admin can create a new World for the purpose.
- **Nothing touches the disk.** The upload is held in memory, and each of the World's documents is stored in Postgres exactly as it was uploaded. Other files in the zip, such as a README, are ignored.
- **A zip is not trusted.** An upload over 20 MB is refused, as is a zip with more than 5,000 files, a single file over 1 MB, or more than 50 MB once unpacked; the limits are settings, and are enforced while unpacking, whatever sizes the zip claims. Files that use YAML aliases are refused. Pictures in a document are not shown, since loading one from another site would tell that site who is reading.
- **The file format is plotcanon's.** plotcanon decides what is valid; this app stores and shows what it parsed ([ADR-0004](./docs/adr/0004-the-schema-lives-in-its-own-package-plotcanon.md)). To lay a page out, the app does know the names of some fields, such as a Mod's Features and a report's Canon Changes, and which fields hold a person's name and so are never links. That knowledge is in `canon/presenting.py`. The version of plotcanon in use is pinned in `pyproject.toml`.

## Who may create an Organization

One setting, `OPEN_SIGN_UP`, decides this. It is read from the environment.

| `OPEN_SIGN_UP` | What happens | Who it suits |
|---|---|---|
| `false` | While this copy has no Organization, the first person to sign in creates the one Organization and its first World. After that, a person who signs in and belongs to no Organization is told they need an invitation. | A self-hosted copy for one Organization. A copy on the internet then does not hand an Organization to every stranger. |
| `true` | Anyone who signs in and belongs to no Organization gets an Organization and a World of their own, unless an invitation is waiting for them: then they answer that first, and get their own only if they decline. | A public host serving many Organizations, or a self-hoster who hosts for others. |

The setting is off unless it is turned on, with one exception: **the local development settings turn it on**, so you can try the app with several email addresses. Those are the only settings in the repo so far, which means `uv run manage.py runserver` with nothing set has open sign-up. To see what a self-hosted copy does, start the app with `OPEN_SIGN_UP=false uv run manage.py runserver`.

The data is stored the same way in both cases. See [ADR-0005](./docs/adr/0005-one-setting-decides-who-may-create-an-organization.md).

## People, Worlds and roles

An Organization Admin runs these from the Organization page, reached by clicking the Organization's name at the top of any page.

- **The Organization's name.** A new Organization is called "My Organization". Rename it at the top of the Organization page. Links keep working after a rename.
- **More Worlds.** Create one by name.
- **Invitations.** Enter an email address. The person is emailed a link to the sign-in page with their address filled in. Once signed in with it they are shown the invitation and accept or decline; nobody is joined to an Organization without accepting. You can see who has not answered and who declined, and inviting an address again sends the email again.
- **Roles.** A new member can open nothing until they are given a role. Roles are per World: Plot Master, Mod Writer and Mod Runner, given and removed on each World's people page. A person can open only the Worlds they hold a role in; an Organization Admin can open them all.
- **A World's name.** This one is not the Organization Admin's to change: a World is renamed by one of its Plot Masters, from the link on the World's page. The first World is called "My first World". To rename a World you created later, give yourself Plot Master in it first.
- **Leaving.** Any member can leave an Organization, from the Leave link at the top of the page. Their roles in its Worlds go with them. The only Organization Admin of an Organization cannot leave it. Someone who leaves their last Organization gets one of their own if sign-up is open, and otherwise needs an invitation.
- **Several Organizations.** A person who belongs to more than one sees a switcher at the top of the page. The app remembers which one they are working in until they sign out.

## How Organizations are kept apart

Each Organization's data is kept apart twice: once by the app's own checks, and once by Postgres row-level security underneath them. Every request tells the database who is asking and which Organization they are working in, and the database returns only that Organization's rows. With nothing set, a query returns no rows at all. There are four deliberate exceptions. A person can always see the Organizations they belong to and their own membership of each, which is how the app finds out where they may work. A person can see an invitation sent to their own address, and the Organization that sent it for as long as they have not answered, so that they can be shown what they are being asked to join. And the database keeps a bare count of Organizations that any query can read, so that a copy with sign-up closed knows whether its one Organization exists yet.

This guards against a mistake in the app's queries. It is not a guard against the app running arbitrary SQL, because the app's database user owns the tables.

Two things follow for anyone running or changing the app:

- **The app must not connect as a database superuser**, or as a user marked `BYPASSRLS`. Postgres skips row-level security for both. `scripts/db.sh` creates an ordinary user, `plothelper`, and `uv run manage.py migrate` refuses to run as the wrong kind. `runserver` does not check, so always migrate first.
- **A new table that holds an Organization's data needs an `organization` column and a policy.** Add `rls.protect("<table name>")` to its migration, and `rls.same_organization(...)` for each column that points at another Organization-owned table; see `organizations/rls.py`.

If your local database was created before this was added, recreate it: `scripts/db.sh destroy && scripts/db.sh`, then `uv run manage.py migrate`.

## License

Copyright (C) 2026 Jeffrey Brite

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the [GNU Affero General Public License](./LICENSE) for more details.
