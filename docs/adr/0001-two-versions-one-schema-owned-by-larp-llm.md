# Two versions, one schema owned by larp-llm

The system exists as two versions developed side by side: larp-llm, where a git repo per World is the system and Canon changes arrive as pull requests, and this repo, a multi-tenant web app for plot teams who will never open a terminal. larp-llm owns the shared schema (entity types, fields and vocabulary), and the web app follows it: a concept is added to larp-llm's schema before the app may use it. The two versions exchange Worlds only by importing and exporting files in one markdown-with-frontmatter format, and never sync live.

## Considered Options

- **One repo for both versions.** Rejected because in the Claude Code version the repo is the product a plot team clones and fills with Canon, so it must not carry app source code.
- **The web app owns the schema.** Rejected because larp-llm already has a working schema and is the faster place to prove a change to the model.
- **Live sync between git and the database.** Rejected as a project in itself; file exchange is enough to move a World between versions and to keep anyone from being locked in.

## Consequences

- A schema change is made in larp-llm first, then followed here.
- Both versions test against one sample World, kept in larp-llm beside the schema, with scripted After-Action Reports and known expected Flags.
- Accounts and access are outside the schema. The web app's Organization, its roles and its logins exist only in the app; files never mention them, and the unit of import and export is the World.
