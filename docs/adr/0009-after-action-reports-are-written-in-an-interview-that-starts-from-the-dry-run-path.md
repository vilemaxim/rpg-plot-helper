# After-Action Reports are written in an Interview that starts from the Dry Run path

> Amends [ADR-0002](./0002-mods-and-reports-are-written-in-the-users-own-llm.md) for After-Action Reports, as [ADR-0008](./0008-mods-are-written-in-an-interview-with-an-llm-the-deployment-configures.md) did for Mods.

A Mod Runner writes an After-Action Report in a report Interview with the app's LLM. When the Mod has a Dry Run (ADR-0007), the Interview starts with the Mod Runner walking the Path the Stretch actually took: the Hook and scenes, each Contest's result, and the ending or the scene where play stopped. This step uses plain code and no LLM. The LLM then gets the Path, the Mod's `expected_changes` and the Mod Runner's answers about what went off-script, and writes the report's Canon Changes, which plotcanon checks and the LLM fixes as in a Mod Interview. The Mod Runner reads the report and files it. A Mod with no Dry Run skips the walk, and the Mod Runner says in words what happened and where play stopped.

The report records its Path in a new optional `path` field, whose last step is where play stopped, and plotcanon checks it against the Mod's Dry Run. The Path sets `finished` (an ending reached means true), and the Mod Runner confirms it. The next Stretch's walk starts from where the last one stopped.

## Considered Options

- **A report built from the Dry Run alone, with no LLM.** Walk the Path, then propose the reached outcome's expected changes as Canon Changes. Rejected because `expected_changes` is the Mod Writer's intent for the whole Mod, written as free text for each entity. A Canon Change needs a kind, `from`/`to` for some kinds and a summary, which can't be read reliably from that text. Making it work would mean every Mod Writer writes structured changes for each outcome, a burden for every Mod to save one step for some.
- **A report Interview with no Path walk.** Rejected because the walk records the Path and the stopping point exactly, for free, and gives the LLM a firm skeleton to write from.

## Consequences

- `[interviews.report]` is a new kind of Interview in the config, with the same limits and filtering of what the LLM sees as ADR-0008.
- Pasting or uploading a report file stays available. In the web UI it is a secondary option next to the Interview, and the only one when the report Interview is off.
- The `after-action` schema in plotcanon gains `path`, and larp-llm takes it with the next release.
- Mods written before ADR-0007 still get reports, but with no Path. Revising them gains one.
