# A World is reviewed by an LLM reading as the plot team, and on a schedule by a command that may list every Organization

> Amends [ADR-0010](./0010-reading-is-narrowed-per-document.md), as [ADR-0012](./0012-a-draft-is-reconciled-by-an-llm-reading-as-the-plot-team.md) does: a World review reads the World as the plot team, not through `readable_documents`.

A **World review** is the app's LLM looking across a whole World for drift, dormant Plots and chances to bring recurring NPCs and Plots back, and writing one report that only the plot team reads. It is advice: nothing acts on it.

The LLM reads the whole World as the plot team does, through `canon.access.as_plot_team`, whoever runs it: a Plot Master, an Organization Admin, or the scheduled command with nobody asking. ADR-0012 said any other such read needs its own decision; this is that decision, for the same reason. A review is the plot team's, read only by them, and one that could not see GM-only facts could not find the drift it exists to find. It is given the whole World or refused: a part would miss what lies outside it, and say so nowhere.

Which LLM reviews is set in the deployment's config file, as a top-level `[world-review]` table beside `[reconciliation]`, with one more key, `context_tokens`, the model's context window. The app estimates the prompt's size before calling, erring toward too large, and refuses a World that would not fit, before anything is spent; a provider that still says the prompt is too long gets the same refusal. Its tokens count toward the same per-Organization monthly cap.

After each Event the plot team is offered a review on the World's page. Where an Organization Admin has turned "Run a World review after each Event" on, the review runs by itself instead. There is no background worker (ADR-0003), and nothing happens when an Event ends, only a date passing, so it runs from a management command, `run_world_reviews`, which the deployment schedules as it does `remove_unused_accounts`. It reviews each World at most once per Event: it claims the World with a Postgres advisory lock for as long as it runs and passes over a World another run has claimed, and the database refuses a second scheduled review for one Event. The lock is not on the World's row, so the plot team can still rename the World while the LLM writes.

The command runs with no person and no Organization, so row-level security shows it no Organizations at all. While a transaction sets `app.all_organizations` (`tenancy.all_organizations`), a policy for SELECT alone lets it read every Organization's row, and nothing else: no other table, and no Organization may be written or deleted that way. It then works in each Organization as a request does, through `tenancy.acting_as`.

## Considered Options

- **A database user with BYPASSRLS for the command.** Rejected: every self-hoster would need a second role and connection, and the app's startup check refuses such a user so that the wall cannot be removed by accident.
- **Run the review inside the request of whoever next opens the World after an Event.** Rejected: a review can take minutes, and the person opening the World did not ask for it.
- **Count tokens with the provider before calling.** Rejected for now: only some providers can, and it is a second call per run. The estimate and the provider's own refusal between them never send part of a World.
- **Review part of a World, by Campaign or Plot, when the whole does not fit.** Out of scope: a review that silently left things out would read as if it had looked.

## Consequences

- The deployment sends GM-only facts to the LLM provider for a World review whoever runs it, as it does for a Reconciliation. Reports are kept in Postgres, per Organization, and never written into the World's files or exports (ADR-0001).
- The flag is a session setting, so code that can run arbitrary SQL can set it; row-level security never guarded against that (see `organizations/rls.py`). It guards against a query forgetting its Organization, and the flag is set in one place only.
- A deployment that does not schedule the command still offers every review on the World's page; turning the setting on then does nothing until it is scheduled.
