# Django and Postgres in one codebase

The web app is a single Django project that renders its own pages as a responsive website, backed by Postgres. There is no separate API and no native or Flutter app. We chose this because larp-llm is already Python, so the file parser, validator and prompt generator can be one Python package that lives in larp-llm and is installed here at a pinned version (see ADR-0001), and because the app is mostly forms, lists and approvals, which Django covers with its built-in login, roles and migrations.

The code is written to run on scale-to-zero container hosting, so it follows three rules: uploaded files are stored in Postgres, nothing is saved on the app's own disk, and there are no background workers. A self-hoster needs only a Postgres database and a way to send email.

## Considered Options

- **TypeScript with Postgres.** Rejected because parsing, validation and prompt generation would be written twice and kept in step with larp-llm only by discipline.
- **Flutter with Firestore.** Rejected despite offering a native app and offline sync, because it means a second codebase, queries that must be planned in advance, and a Firebase project for every self-hoster. The only offline need identified was a Mod Runner's copy of their Mod, which a download button covers.
- **Flutter with a Django API.** Rejected for the MVP as two codebases. Keeping logic in the shared package and out of page code leaves room to add an API and an app later.
- **Strapi.** Rejected because it needs an always-on server, its extensions are JavaScript, and it has no built-in way to keep one group's data from another's.
- **Google Cloud SQL as the database.** Rejected for hosting on cost: it bills monthly whether or not it is used. A scale-to-zero Postgres provider such as Neon is the intended host.

## Consequences

- Row-level security is part of the design (each Organization's data is kept apart inside the database), so development and tests run against real Postgres, never SQLite.
- Very interactive screens, offline editing and app-store presence are out of reach without adding a second codebase.
