# Mods are written in an Interview with an LLM the deployment configures

> Amends [ADR-0002](./0002-mods-and-reports-are-written-in-the-users-own-llm.md) for Mods. [ADR-0009](./0009-after-action-reports-are-written-in-an-interview-that-starts-from-the-dry-run-path.md) does the same for After-Action Reports.

The web app now calls an LLM itself. A Mod Writer, or a Plot Master acting as one, writes a new Mod or revises a draft in an Interview: the app's LLM asks questions, writes the Mod file, checks it with plotcanon, and fixes errors without involving the person, up to a set number of attempts. The person reads the result and submits it through the same intake as a pasted file. An Interview is the default, and pasting or uploading a file stays available beside it. A revise Interview starts from the draft, the Plot Master's reason for sending it back, and its open Flags.

Each deployment brings its own keys, one environment variable per provider, and the app talks to providers through two small adapters of its own: one using the Anthropic SDK, and one using the OpenAI-compatible API, which covers OpenAI, OpenRouter, Gemini's compatibility endpoint and local models. Which provider, model and effort each kind of Interview uses, and its limits, are set in a TOML config file committed with defaults, which a self-hoster can point elsewhere with an environment variable. The file is checked at startup. A kind of Interview with no valid entry is off, and the paste path takes its place.

What the LLM is told lives in plotcanon, with a surface argument (`web` or `cli`), so larp-llm uses the same instructions and the app holds no prompt text. The app decides only how the call runs.

## Considered Options

- **Keep ADR-0002 as it was.** Rejected now that the model is proven: answering questions in the app is easier than carrying a prompt to another LLM and a file back.
- **A multi-provider library such as LiteLLM.** Rejected as a large dependency with a recent supply-chain compromise, for what two small adapters cover.
- **A key per Organization, entered in the app.** Deferred. One key per deployment is enough while the deployment's operator pays.
- **Interview instructions kept in the app.** Rejected because larp-llm needs them too (ADR-0001, ADR-0004).

## Consequences

- The deployment, not the user, now sends Organization data to an LLM provider, GM-only facts included. The LLM sees only what the person in the Interview may read, and the errors it gets back are filtered the same way.
- The operator pays for every Organization on the deployment, so the config file sets a turn limit per person per day and a token cap per Organization per month. Reaching either pauses the Interview and offers the paste path.
- Each turn streams back inside the request, with no background worker (ADR-0003).
- A transcript is kept in Postgres so an Interview survives a reload, until the file is submitted or 30 days pass without activity. It is not part of the World, is never exported, and Plot Masters do not see it.
- A provider failure mid-turn leaves the Interview at its last good turn, to be tried again.
