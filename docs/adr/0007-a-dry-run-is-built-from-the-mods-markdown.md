# A Dry Run is built from the Mod's markdown, and Twine is only an exchange format

A Mod stays one markdown-with-frontmatter file. Its branching is written into the body by convention: Hooks and scenes name where they lead, each Contest names where each of its results leads, and each outcome under `## Possible Outcomes` is an ending. The convention and its checks live in plotcanon (ADR-0004). The app builds a Dry Run and a Twine (Twee 3) file from that structure with plain code, with no LLM involved (ADR-0002). The Twine file carries the whole Mod: its story as linked passages, each other section as an unlinked passage tagged `mod-section`, and its frontmatter as a passage tagged `frontmatter`. A Twine file can therefore be submitted anywhere a Mod file can, so people can edit a Mod in Twine and bring the result back. Converting in both directions is file-format logic, so it lives in plotcanon and larp-llm gets it too.

## Considered Options

- **Mod Writers' LLMs produce a Twine file as a second output.** Rejected because the second file drifts from the Mod, and the app would be checking two documents that describe the same thing.
- **Mods are written in Twine instead of markdown.** Rejected because it would split the one shared file format (ADR-0001, ADR-0004). It also leaves `features`, `requires` and `expected_changes`, which drive Flags and preconditions, no natural home. Most of a Mod is not branching (casting, logistics, GM notes), and Plot Masters and Mod Runners need to read it top to bottom as a document.
- **The app guesses a story from the existing prose.** Rejected because prose names no links, so the result would be unreliable.

## Consequences

- The intake prompt for Mod Writers teaches the link convention.
- Mods written before the convention, including the sample World, have no Dry Run until they are revised. How strictly the convention is enforced is a setting per World.
- A Twine file goes through the same validation and intake as a Mod file. A Twine story written from scratch with no `frontmatter` passage fails validation like a markdown file with no frontmatter would.
- Twine features the convention does not use, such as variables, macros and styling, are kept as text and warned about. They do nothing in a Dry Run.
- The app has no visual builder of its own. Twine is the builder.
