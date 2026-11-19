# Reading is narrowed per document, and the plot team alone reads everything

> Amended by [ADR-0012](./0012-a-draft-is-reconciled-by-an-llm-reading-as-the-plot-team.md): a Reconciliation's LLM reads the World as the plot team, whoever asks, not through `readable_documents`.
>
> Amended by [ADR-0013](./0013-a-world-is-reviewed-by-an-llm-reading-as-the-plot-team-on-a-schedule.md): so does a World review's.

Until now everyone with a role in a World read all of it, GM-only facts included. Now only the **plot team** (a World's Plot Masters and its Organization's Admins) reads everything. Everyone else reads every `public` and `player-known` document with its `## GM Notes` removed, plus what their part gives them in full:

- a Mod Writer: their own Mods;
- a Mod Runner: the Mods they hold a live Assignment for;
- either of them: each document a Plot Master has given them a **Grant** for.

Players and Cast members read only `public` and `player-known` documents, and their own Debriefs, and are given no Grants.

An After-Action Report is readable to whoever can read its Mod. A Canon Change in it about a document the reader can't read is left out, and saying so ends the list. Anywhere else a document the reader can't read is mentioned, it reads "another document", as check errors already do. A Private link shows its own Mod in full and nothing else.

One function, `readable_documents`, answers what a person may read. Every page, download, Twine file, Dry Run, Interview and check error takes World content from it. Removing `## GM Notes` from a document's text is knowledge of the file format, so plotcanon provides it (ADR-0004).

## Considered Options

- **Plot-scoped grants.** A Plot Master grants a Plot, and the person reads the Plot and everything tied to it: NPCs and factions whose `plots` list it, and Mods that feature it. Rejected because a tie to a Plot doesn't mean a secret should travel with it. Granting a Plot instead suggests those documents for the Plot Master to tick one by one.
- **Roles that read the whole World.** Rejected: some Mod Writers should know more about some Plots than others, and a Mod Runner needs only the Mods they run.
- **Hiding mentions of unreadable documents.** Rejected because lists of relationships, Features and Plots would look wrong. "Another document" says something exists without saying what.

## Consequences

- Grants and Assignments are kept in the database only, never in the World's files (ADR-0001). A Grant made from an Assignment's suggestions ends with the Assignment.
- A draft Mod naming a document its Mod Writer can't read is still checked against the whole World, and they see only the findings they may read. Learning that an id exists is accepted. The Plot Master is told which references the Mod Writer hasn't been granted, and can grant them from there.
- The page of Canon Changes waiting to be decided is for the plot team only.
- Visibility is per document. A secret inside a public document belongs in `## GM Notes`, or it is shown to everyone.
