# Current state is kept in the entity's file

An approved Canon Change updates the entity's stored file: its status, location or factions, and the Event its state is "as of". The entity's page shows that state, and its history is the list of approved Canon Changes, each with the report it came from. This departs from the spec's "Canon is stored as the full list of approved Canon Changes ... Current state is derived from that list". We chose it because the file format (plotcanon, ADR-0004) holds an entity's state in its file, larp-llm keeps it there, and an exported World must carry it. Deriving state from the list would mean the stored files no longer said what an export needs them to.

## Considered Options

- **Derive current state from approved changes on every read.** Rejected for now: the entity's file would go stale, and exporting would have to rewrite every file from the list. It also needs plotcanon to say how a change moves each field, which today the app works out from plotcanon's vocabularies.
- **Keep both, and recompute the file from the list whenever a change is decided.** Not needed yet. The two are kept in step at the one place they change, and plotcanon checks the World before anything is saved.

## Consequences

- The change's row, its `decision` in the report's file, and the entity's file are changed together. A decision is refused if plotcanon then finds an error, or warns that the entity's file disagrees with its approved changes. plotcanon only warns about the latest approved change, so the app also checks that each approved change follows on from the one before it and leads into the one after.
- A decision can be undone (#25) without revisiting this decision. Only the latest approved change to a field can be undone, and undoing an earlier one waits until the later ones are. The field goes back to where the approved change before it left it. An approval keeps what it replaced in the entity's file, so a list of factions and "as of" go back to that, "as of" never earlier than the latest approved change that remains. Approvals made before that was kept fall back to reversing the change.
- Approved changes to one field must follow on from each other in Event order. A change that does not is refused as a contradiction rather than stacked. Changes to a list of factions are decided in the order they happened.
- How changes are ordered and applied is knowledge of the file format that plotcanon should own (#23).
