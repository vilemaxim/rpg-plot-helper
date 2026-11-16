# Parallel Groups are labelled in the report, and `finished` and Paths follow each Group

When a Mod splits its players into **Groups** at one Event, each with its own Mod Runner, every Group's Mod Runner files their own After-Action Report. A report says which Group it covers in an optional `group` field, a short label the Mod Runner chooses. For one Mod at one Event, reports with different labels ran side by side, and reports with the same label, or none, follow each other in id order. A report with no `group` reads exactly as before.

Each Group has its own line of play:

- Its Path continues from its own previous report. A Group's first report continues from where the whole Mod stopped before the players split, or from a Hook.
- `finished: true` means the Group has nothing more to play. Nothing may follow a finishing report within that Group. The Mod is finished when every Group at its latest Event is.
- When a later report has no `group`, the players have come back together. It continues from the stopping point of the Group that hadn't finished. If several hadn't, its Path's first step says which.

Canon Changes still need one order to be decided in. Parallel reports keep id order as a tie-break, so the result is always the same, and plotcanon warns when two parallel Groups change the same field of the same entity, so a Plot Master checks it.

## Considered Options

- **One document for each Group, or a Group as its own kind of document.** Rejected as heavier than the problem: a Group exists only while a Mod is split, and has no facts of its own to keep.
- **Groups kept only in the app's database, linked to Assignments.** Rejected because larp-llm and the checks need to read the order of play from the files alone (ADR-0001, ADR-0004).
- **No order between parallel Groups: refuse to decide conflicting changes.** Rejected because a deterministic order with a warning lets the Plot Master see and fix the rare clash, instead of blocking every parallel report.

## Consequences

- `last_stop` and the `finished` checks take the Group into account. larp-llm takes the new schema with the next plotcanon release.
- In the app, a report asks for a `group` only when the Mod has more than one live Assignment at that Event. Groups aren't linked to Assignments in the database.
- Reports from before this change, which have no `group`, are one Group, as they always were.
