# The schema lives in its own package, plotcanon

The shared schema, parser and validator live in a third repo, plotcanon, published as a Python package. Both larp-llm and this app install it at a pinned tag and neither holds file-format logic of its own. This replaces the part of ADR-0001 that made larp-llm the schema's owner: a concept is now added to plotcanon first, and both versions follow by moving their pin. The rest of ADR-0001 stands. The two versions still exchange Worlds only as files, and never sync live.

## Considered Options

- **Keep the package inside larp-llm.** Rejected because a larp-llm repo holds a plot team's real Canon and is private, while this app is public and anyone self-hosting it must be able to install the package.
- **Make larp-llm public and keep Canon elsewhere.** Rejected because in the Claude Code version the repo is the World; separating the tooling from the Canon it manages would undo that.

## Consequences

- A schema change is made in plotcanon, tagged, and then taken by larp-llm and this app separately.
- larp-llm keeps a copy of the schema docs for people and agents to read. The copy is refreshed from the package, and larp-llm's validator warns when it has drifted.
- The sample World that both versions test against lives in plotcanon beside the schema, not in larp-llm.
- plotcanon is licensed AGPL-3.0, the same as this app.
