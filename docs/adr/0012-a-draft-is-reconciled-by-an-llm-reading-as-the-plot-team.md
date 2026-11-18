# A draft is reconciled by an LLM reading as the plot team, inside the request

> Amends [ADR-0010](./0010-reading-is-narrowed-per-document.md): a Reconciliation reads the World as the plot team, not through `readable_documents`.

A **Reconciliation** is the app's LLM checking a draft Mod against the whole World's Canon and the other drafts waiting for approval, and writing one report that only the plot team reads. It is advice: approving and sending back work as before, whatever it says.

The LLM reads the World as the plot team does, through `canon.access.as_plot_team`, whoever asks for the run: a Plot Master pressing Reconcile, an Organization Admin, or nobody at all on submission. This is the one deliberate exception to ADR-0010's single path, `readable_documents`. A Reconciliation is work done for the plot team, read only by them, and a check that could not see GM-only facts could not find the conflicts it exists to find.

Which LLM reconciles is set in the deployment's config file, as a top-level `[reconciliation]` table beside the Interviews' (ADR-0008): provider, model, effort and `max_tokens`, checked at startup the same way. With no valid entry and its provider's key there is no Reconcile button and nothing runs on submission. Its tokens count toward the same per-Organization monthly cap as the Interviews'; at the cap it does not run, and the draft's page says why.

Where an Organization Admin has turned it on, a draft is reconciled each time it is submitted or revised, inside the request that submits it, once the draft is saved and committed. There is no background worker (ADR-0003). A run that is refused or fails never stops the submission: the draft is saved, and its page tells the plot team that this revision has not been reconciled.

## Considered Options

- **Read as the person who asked.** Rejected: a run on submission has no person, and a Reconciliation is the plot team's, so it should find the same conflicts whichever Plot Master pressed the button.
- **A `[interviews.reconciliation]` entry.** Rejected because a Reconciliation is one report, not a conversation: it has no file for the LLM to fix, so `max_fix_attempts` means nothing for it.
- **A cap of its own.** Rejected: the operator pays for both from the same keys, and one cap is the one number they need to watch.
- **Leave drafts "not reconciled yet" for a later run.** Rejected: ADR-0003 rules out a background worker, not a slow request, and a Reconcile press and every Interview turn already call the LLM inside the request. A setting that only ever left drafts not reconciled would reconcile nothing.

## Consequences

- The deployment sends GM-only facts to the LLM provider for a Reconciliation whoever runs it, as it already does for a Plot Master's Interview. The report is kept in Postgres, per Organization, and is never written into the World's files or exports (ADR-0001).
- Submitting a draft where reconciling on submission is on waits for the LLM. Saving comes first, so a slow or failed run costs time, never the draft.
- Any other read of the World on the plot team's behalf by the app's LLM should go through `as_plot_team` too, and needs its own decision to do so.
