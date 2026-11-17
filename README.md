# RPG Plot Helper

Tracks the canon and plots of live-action and tabletop role-playing games, for plot teams, shared-world GMs and solo GMs.

This repo is the web app. Its vocabulary is in [GLOSSARY.md](./GLOSSARY.md) and its design decisions are in [docs/adr/](./docs/adr/).

## Run it on your own machine

You need [Docker](https://docs.docker.com/get-docker/) and [uv](https://docs.astral.sh/uv/). uv installs the right Python and the dependencies the first time you run a command.

Start Postgres:

```sh
scripts/db.sh
```

Start the app:

```sh
uv run manage.py migrate
uv run manage.py runserver
```

Open http://localhost:8000. `migrate` sets up the database; run it the first time and after pulling changes.

### Sign in

There are no passwords. Enter any email address on the sign-in page. Locally, an address that belongs to no Organization and has not been invited to one gets one of its own, with a first World, when it signs in. Locally the email is not sent: it is printed in the terminal where `runserver` is running. Copy the link from there into your browser and press **Sign in**. A link works once and expires after 15 minutes.

### Run the tests

```sh
uv run manage.py test
```

The tests run against the same Postgres, in a separate database that is created and removed each time, so `scripts/db.sh` must be running. They never use SQLite.

### The database

| Command | What it does |
|---|---|
| `scripts/db.sh` | Starts Postgres on `localhost:5432`. Safe to run again. |
| `scripts/db.sh stop` | Stops it. Your data is kept. |
| `scripts/db.sh destroy` | Stops it and deletes your data. |

If port 5432 is taken, set `PLOTHELPER_DB_PORT` before the first `scripts/db.sh` and put the same port in `DATABASE_URL`, for example:

```sh
export PLOTHELPER_DB_PORT=5433
export DATABASE_URL=postgres://plothelper:plothelper@localhost:5433/plothelper
```

## Importing and browsing a World

A World's Canon arrives as files. A Plot Master of a World uploads one `.zip` of them from the link on the World's page, and everyone who can open that World can then browse it: Campaigns, Events, Mods, Plots, NPCs, factions, locations, PCs, After-Action Reports and timeline entries, each with a list and a page per item. A Mod's page shows its state, its Events and its Features, and each of those links to its own page. Every page also lists what refers to it, so a Campaign shows its Events and Mods, and an NPC shows the Mods that feature them and the reports that changed them.

### Who reads what

What each person may read is narrowed per document ([ADR-0010](./docs/adr/0010-reading-is-narrowed-per-document.md)), and decided in one place, `canon/access.py`, which every page, download, Twine file, Dry Run, Interview and check error takes World content from.

- **The plot team**, a World's Plot Masters and its Organization's Admins, reads everything in full.
- **Anyone else with a role in the World** reads every `public` and `player-known` document, and every Campaign and Event (their files have no `visibility`), with its `## GM Notes` removed (`plotcanon.without_gm_notes`). A Mod Writer also reads their own Mods in full, draft or not, and a Mod Runner the Mods they hold a live [Assignment](#assigning-mod-runners) for, for as long as it is live. Either of them also reads in full each document a Plot Master has given them a [Grant](#granting-documents) for, until it is revoked; a Grant made for an Assignment ends with it. Only someone with the Mod Writer or Mod Runner role, and not on the plot team, can hold one. An After-Action Report is read as its Mod is.
- **A document someone may not read** is not listed, its page is not found, the same answer as for one that does not exist, and wherever it is mentioned (a relationship, a Feature, a Plot, a link in a body or a Dry Run, a Canon Change or a decision's note) it reads "another document". A readable report leaves out its Canon Changes about such documents, and says there are more.
- **The Canon Changes waiting to be decided**, on their page or on a document's, and the records of Canon Changes made during an Interlude, are for the plot team only.
- **A private link** reads its own Mod in full and nothing else in the World.

To try it, make a zip of the sample World that ships with [plotcanon](https://github.com/vilemaxim/plotcanon):

```sh
uv run plotcanon sample --write demo
zip -r demo.zip demo
```

Things to know:

- **All or nothing.** The whole World is checked by plotcanon first. If anything in it is invalid, nothing is imported and the errors are shown, worded so they can be pasted back into the LLM that wrote the files.
- **Only into an empty World.** A World that already has Canon cannot be imported into. An Organization Admin can create a new World for the purpose.
- **Nothing touches the disk.** The upload is held in memory, and each of the World's documents is stored in Postgres exactly as it was uploaded, as is its settings file, `world.yml`, if it has one at its root. Other files in the zip, such as a README, are ignored.
- **The World's settings come with it.** The zip's `world.yml` replaces the one the World was given when it was created. A zip without one gives a World plotcanon's defaults: its Dry Run structure is `encouraged`, whatever the Organization's default.
- **A zip is not trusted.** An upload over 20 MB is refused, as is a zip with more than 5,000 files, a single file over 1 MB, or more than 50 MB once unpacked; the limits are settings, and are enforced while unpacking, whatever sizes the zip claims. plotcanon itself refuses files that use YAML aliases, which can expand to exhaust memory. Pictures in a document are not shown, since loading one from another site would tell that site who is reading.
- **The file format is plotcanon's.** plotcanon decides what is valid; this app stores and shows what it parsed ([ADR-0004](./docs/adr/0004-the-schema-lives-in-its-own-package-plotcanon.md)). To lay a page out, the app does know the names of some fields, such as a Mod's Features and a report's Canon Changes, and which fields hold a person's name and so are never links. That knowledge is in `canon/presenting.py`. The version of plotcanon in use is pinned in `pyproject.toml`.

## Exporting a World

A Plot Master downloads a World as one `.zip` of its files from "Export this World" on the World's page, so nobody is locked in ([ADR-0001](./docs/adr/0001-two-versions-one-schema-owned-by-larp-llm.md)). Each file is written exactly as it is stored now, with every report and decision since the import in it ([ADR-0006](./docs/adr/0006-current-state-is-kept-in-the-entitys-file.md)), inside one folder named after the World. The zip is made in memory, and plotcanon checks the World before it is handed over; a World it finds errors in is reported as a fault, not downloaded.

The zip imports into an empty World here, and unpacked it is a plotcanon World anywhere else: `plotcanon validate --root <folder>`, which is what a larp-llm repo's `scripts/validate.py` runs, passes on it. What lives only in the app is not in the files: who submitted or decided what, Flags and their resolutions, why a Mod was sent back, Mod Writers, Assignments, Grants, private links, and people and their roles. The export page says so.

## Filing an After-Action Report

Anyone who can open a World (anyone with a role in it, and its Organization Admins) can file a report on one of its Mods, from the link on the Mod's page. They write it in a [report Interview](#writing-an-after-action-report-in-an-interview) with the app's LLM, starting from the Path play took through the Mod's Dry Run, when the deployment has one; or they paste the report file their own LLM produced, or choose it. A Mod can take a report while it is approved or in progress, and can take several: one each time play stops.

What happens to a report:

- **It is checked first.** plotcanon checks it against the World as it is stored. If anything is wrong, nothing is saved and the errors are shown as text to paste back into the LLM. What was pasted is kept in the form.
- **Its Canon Changes are listed as waiting.** Every change in a submitted report must say `decision: proposed`; only a Plot Master decides one. Each goes on record as proposed and appears on the World's "Canon Changes waiting to be decided" page. **Nothing in Canon changes** until a Plot Master approves it: an NPC a report says died is still alive on their page.
- **Its Mod's state is brought up to date.** The Mod becomes finished if the report says `finished: true`, in progress if it says the Mod was played (`ran: true`) and has more to come, and stays as it was if it was not played. The Mod's stored file is changed to say so, and the whole World is checked again before anything is saved, so what is stored can always be exported as a World plotcanon accepts.
- **It records who and when.** The report's page shows its Mod, its Event, its Mod Runner, the PCs who took part, and who submitted it.

To try it, write the sample World's scripted reports to disk alongside the World, and file them in order from each Mod's page:

```sh
uv run plotcanon sample --write demo --script demo-script
```

### Assigning Mod Runners

A Plot Master assigns a Mod Runner to a Mod from its page, while the Mod is approved or in progress. An Assignment is for one Event that has not ended, which is the default, or until a Plot Master revokes it. A Mod can have several, such as one Mod Runner for each group its players split into at one Event.

- **Only someone with the Mod Runner role** in the World can be assigned, and not twice to the same Mod for the same Event, or twice until revoked. Anyone in the World but a Plot Master is answered 403.
- **Its Features can be granted with it.** The form lists the documents the Mod features, unticked. Each one ticked becomes a Grant to the Mod Runner that belongs to the Assignment and ends when it does.
- **One for an Event ends by itself** once that Event's last day (`real_date_end`, or `real_date` for a one-day Event) has passed.
- **Who sees them.** The Mod's page lists its live Assignments to everyone with a role in the World, and revoked and ended ones, with who assigned and revoked each and when, to Plot Masters. A Mod Runner's own live Assignments are listed on the World's page.
- **Kept in the app alone**, never in a file, so an export leaves them out.

### Granting documents

A Plot Master grants one document, of any kind, to a Mod Writer or Mod Runner from that document's page. The holder then reads it in full, GM Notes included, everywhere they read the World, until a Plot Master revokes it from the same page. Revoked Grants are kept, with who granted and revoked each and when.

- **Only someone with the Mod Writer or Mod Runner role** in the World, and not on its plot team, can be granted a document, and not twice while the first Grant is live. Anyone in the World but a Plot Master is answered 403.
- **Granting a Plot offers what is tied to it.** Once a Plot is granted, the Plot Master is shown the NPCs and factions whose `plots` list it and the Mods whose `features.plots` list it, none of them ticked, leaving out any the holder already holds a Grant of. Each one ticked is granted to the same person in one step, until revoked. Nothing is granted unless ticked.
- **One made for an Assignment ends with it**, when the Assignment is revoked or its Event is over. Every other Grant lasts until revoked.
- **Only while its holder may hold one.** A Grant is not live while its holder has neither the Mod Writer nor the Mod Runner role in the World, or is on its plot team. It is live again, unless revoked, once they may hold one again.
- **Who sees them.** A document's page lists who holds a live Grant of it to the plot team alone. A holder's own live Grants are listed on the World's page. Nobody else sees them.
- **Kept in the app alone**, never in a file, so an export leaves them out.

### Private links for Mod Runners

A Mod Runner does not need an account. A Plot Master creates a private link for a Mod from its page, saying who it is for if they like, and sends it on. Anyone with the link can read that Mod, download its file to read with no signal or to edit in Twine, play its [Dry Run](#playing-a-dry-run) and see its open Flags, and nothing else in the World. A link files nothing: an After-Action Report is filed by signing in with a role in the World (see [Filing an After-Action Report](#filing-an-after-action-report)), and the link's page says so without linking to sign-in. A report that has a link it was filed through says which link that is.

- **Shown once.** The link holds a long random secret, and only its hash is kept, so it is shown once, when it is created. A lost link is replaced by creating another.
- **It works while the Mod can be run**: while it is approved or in progress, and until a Plot Master turns it off from the Mod's page. A finished or shelved Mod's links open nothing.
- **Guessing is limited.** An address that presents 20 secrets no link has in 15 minutes is refused for the rest of that time (`MOD_LINK_FAILURES_ALLOWED`, `MOD_LINK_FAILURE_WINDOW`); reloading a link that has stopped working does not count. The counts are kept in Postgres and shared by every process, and an address is read as sign-in reads it (see [Limits on sign-in](#limits-on-sign-in)).
- **The secret is in the address.** It is never put in a message, cookie or session, but a web server's access log records addresses; keep those logs as private as the data.
- **The database opens one link.** A visitor has no Organization, so the table of links lets a request see the single link whose secret's hash it presents, and nothing else; the request then works in that link's Organization ([migration 0013](./canon/migrations/0013_mod_links_kept_apart.py)).

### Flags

Filing a report also raises Flags. Every Mod that is not finished or shelved, and that features something one of the report's changes touches, gets a Flag for that change, in any Campaign of the World. A report that finishes its own Mod does not flag that Mod. Which Mods are flagged is plotcanon's rule (`plotcanon.flags`); the app records the result.

The World page links to a list of open Flags, each naming the Mod, the Feature the change touches, the change, and the report it came from. A flagged Mod's page shows a warning listing its Flags, so a Mod Runner sees it before running the Mod. A Flag is open while its Mod is still to be played; once the Mod is finished or shelved the Flag stays on record but is no longer listed or warned about.

### Approving and rejecting Canon Changes

A Plot Master decides each Canon Change, one at a time, from the "Canon Changes waiting to be decided" page or from the report's own page. The waiting page groups changes by what they change, with the changes to it already decided alongside. Two waiting changes that move the same field from the same value to different ones are marked as disagreeing, before anyone tries to approve either.

- **Approving** makes the change Canon. If it moves a field (a status, a location, a faction), the entity's own file is updated, and its "as of" moves to the Event the change happened at. The entity's page shows the change in its History, with the report it came from and who approved it.
- **Rejecting** leaves Canon as it was. The change stays on record as rejected on the report's page.
- **A contradiction is refused.** Approved changes to one field follow on from each other in Event order. Approving a change that does not, such as "left alive" once "died" is approved, is turned down with the other change named, so that one of the two is rejected instead of both standing. Changes to a list of factions are decided in the order they happened.

Each decision is recorded in the change's row, in the report's stored file and, where a field moves, in the entity's stored file, and the World is checked by plotcanon before anything is saved: a decision is refused if plotcanon finds an error, or warns that the entity's file disagrees with its approved changes. Only a Plot Master of the World can decide.

A decision can be undone from the report's page, returning the change to proposed in its row and in the report's file, to be decided again:

- **Undoing an approval** takes the change out of Canon. The field goes back to where the approved change before it left it, or to what this one changed it from if there is none, and a list of factions to what it was before the approval. If the approval moved "as of", it goes back to what it was before, or to the Event of the latest approved change that remains if that is later. An approval keeps what it replaced in the entity's file for this; for one approved before that was kept, or imported already approved, the faction it put in is taken back out and the one it took out put back, and "as of" goes back to the latest approved change that remains, or stays where it is if none does.
- **An approval something follows on from waits.** If a later approved change to the same field follows on from it, that one must be undone first, and the Plot Master is told which. Changes to a list of factions are undone in the reverse of the order they were decided.
- **Undoing a rejection** never waits for another change to be undone. The Flags that rejecting it cleared are open again; Flags resolved some other way stay resolved. Undoing an approval leaves its Flags as they are.

Each undo is kept on record on the report's page: what the decision had been and who made it, and who undid it and when. Like a decision, it is checked by plotcanon before anything is saved.

### Interludes

Canon also changes between Events, with no Mod run: backstories, off-screen moves, letters. The time between two Events is an Interlude.

- **Adding one.** A Plot Master adds an Interlude from the Events list, naming it, choosing its Campaign and the Event it comes after. It takes the next place in the World's order, and every later Event moves up one: plotcanon requires the order to have no gaps, and everything refers to an Event by its id, so nothing else moves. The new Event's file is written and the whole World checked before anything is saved.
- **Recording changes.** From the Interlude's page, a Plot Master records changes made during it, one at a time in a form or several as a pasted `interlude-changes` file (plotcanon's format). A change of status or location entered in the form changes from what Canon says at the Interlude's place in the order, unless the Plot Master says otherwise; a change of affiliation names the faction left, which is never inferred. They are approved as they are recorded, since the Plot Master is the one making them, whatever a pasted file says (one that marks a change rejected is refused): each goes through the same decision as a reported change, so one that contradicts Canon is refused and nothing is saved. They raise Flags on the unfinished Mods they touch, and appear in each entity's History as "Changes during" the Interlude.
- **Who recorded them** is kept in the app. A file made from the form says `recorded_by: plot-master`, since accounts never appear in files.

### Resolving Flags

A Plot Master resolves each Flag in one of three ways, from the Flags page or the flagged Mod's page:

- **Dismiss it**, from the Flags page or the Mod's page, when the change does not matter to the Mod after all.
- **Send the Mod back to its Mod Writer**, from the Mod's page, saying why. The Mod becomes a draft again and can no longer be run or reported on, and every open Flag on it is resolved with that reason. A draft is not Canon, so its stored file moves to the inbox and is marked `canon: proposed`. Only a Mod that has not been played yet can be sent back; one already played has reports that say so. Its Mod Writer can then revise it, and a Plot Master approve it again (see [Submitting and approving Mods](#submitting-and-approving-mods)).
- **Reject the change** that raised it, from the review screen or the report's page. Every Flag that change raised is cleared, since what it reported did not happen.

A resolved Flag is no longer listed or warned about, and stays on record on the Mod's page, with how it was resolved, by whom and when. Only a Plot Master of the World can resolve a Flag.

## Submitting and approving Mods

A Mod is written in an [Interview](#writing-a-mod-in-an-interview) with the app's own LLM, when the deployment has one, or in the Mod Writer's own LLM and submitted as a file ([ADR-0008](./docs/adr/0008-mods-are-written-in-an-interview-with-an-llm-the-deployment-configures.md)). A World's Mod Writers and Plot Masters do either from the World's page, once the World has Canon: "Write a Mod" opens an Interview, and "Submit a Mod", or "paste or upload one" beside an Interview, takes a file pasted or chosen. Both end in the same intake:

- **It arrives as a draft.** It is kept in the World's inbox, says `state: draft` and `canon: proposed` whatever the file claimed, and is not Canon. A draft cannot be run or reported on, and submitting one raises no Flags.
- **It is checked first.** plotcanon checks it against the World as stored. If anything is wrong, nothing is saved and the errors are shown as text to paste back into the LLM, with what was pasted kept in the form. A draft may name people, places and factions the World does not have yet; plotcanon allows that in the inbox.
- **Its warnings are shown.** A Mod plotcanon warns about is still saved, and the warnings are shown as text to paste into the LLM, as they are when a draft is approved.
- **Its Dry Run structure is checked as the World asks.** See [Dry Run structure](#dry-run-structure).
- **Its id is its own.** A Mod whose id the World already uses is refused. To change a draft, revise it from its page with a file that keeps its id; its Mod Writer, and the World's Plot Masters, can. A revision keeps the draft's history: who submitted it, its Flags, and who sent it back and why.

A Plot Master approves a draft from its page, which makes it Canon and ready to be run. Its file moves to its Campaign's folder and says `state: approved` and `canon: approved`. A Mod that names no Campaign has one chosen as it is approved, and that is written into its file. The whole World is checked by plotcanon first, and nothing is saved if it finds an error, or a new warning on the Mod: a draft that names something the World does not have cannot be approved until it is revised. A Mod's open Flags stay open when it is approved. Its page says who approved it and when.

### Writing a Mod in an Interview

In an Interview the LLM asks about the Mod, works it through with the Mod Writer and writes its file. The file is shown with a Submit button; pressing it sends the file through the intake above, with the same checks and errors. The LLM never submits. Pasting or uploading a file stays a link away on every page of it.

- **What the LLM is told** is plotcanon's (`plotcanon.interview_instructions`), with the documents of the World that person may read, as they read them, GM Notes removed where they may not read them (see [Who reads what](#who-reads-what)). Errors the person or the LLM is shown are cut down the same way: one about a document they may not read is left out, and saying so ends them.
- **Each reply streams** into the page as it is written, inside the request, with no script, so it works on a phone. A turn the provider fails leaves the conversation as it was, with the answer ready to send again.
- **The conversation is kept** in Postgres, for that person alone, so it survives a reload, a dropped connection or a day away: opening the Interview again carries on where it was. "Start over" deletes it and begins a new one. It is deleted when its Mod is submitted, or after 30 days with no activity. It is not part of the World, so it is never exported.
- **The LLM fixes its own file first.** When a reply holds a Mod file, the app checks it the way the intake would, saving nothing. A file with errors goes back to the LLM with them, in plotcanon's words (`plotcanon.interview_fix_request`), up to `max_fix_attempts` times; the person sees a note that it is being fixed, and the file once it is good, or once the attempts are used up, with its errors. The fixing is not kept in the conversation: only the person's answer and the LLM's last reply are.
- **Revising a draft.** "Revise this draft" on a draft's page opens a revise Interview, for its Mod Writer or a Plot Master. The LLM is given the draft, why it was sent back, its open Flags and the Flags its latest send-back resolved, only those the person may read. Pressing Begin sends plotcanon's first message (`plotcanon.interview_revise_opener`) on the person's behalf, so the LLM speaks first, on the send-back reason and each Flag; that message is never shown as theirs. Submitting goes through the same revise intake as a pasted file, so the Mod keeps its id and its history. It is on or off on its own, as `[interviews.revise-mod]`.
- **Configured by the deployment.** `interviews.toml`, at the repo root, says which provider, model, `effort`, `max_tokens` and `max_fix_attempts` each kind of Interview (`new-mod`, `revise-mod`, and `report`, [below](#writing-an-after-action-report-in-an-interview)) uses; set `INTERVIEWS_CONFIG` to use another file. It is checked when the app starts, and a key it does not know, an unknown provider, a missing `model` or an `effort` the provider does not take stops it with the key named. A kind of Interview is on only if it has an entry and its provider's key is in the environment variable the file names (`ANTHROPIC_API_KEY` by default). Otherwise the Mod pages are as they were without it.
- **Providers.** Anthropic, through its SDK, and any endpoint that speaks OpenAI's Chat Completions API (OpenAI, OpenRouter, Gemini's compatibility endpoint, a local model), as a `[providers.<name>]` table with `kind = "openai-compatible"` and its `base_url`. Another provider is an adapter beside those in `interviews/providers/`, with no change to the Interview.
- **Spend limits.** The deployment pays for every Organization on it, so `[limits]` in `interviews.toml` can set `turns_per_person_per_day` and `tokens_per_organization_per_month`; one left out is no limit. Every LLM call an Interview makes counts its tokens against the Organization for the calendar month (UTC), fix attempts and calls that fail part way included, as far as the provider reported them; only the person's own turns count toward their day (UTC). When either is reached, the Interview pauses with the conversation kept, says which limit and when it starts again, and offers the paste path. The turn that crosses the token cap finishes. Both counts are kept in Postgres, shared by every process.

To try one locally, export `ANTHROPIC_API_KEY` before `uv run manage.py runserver`. The tests never call a provider.

### Writing an After-Action Report in an Interview

A report can be written in an Interview too, run as the Mod Interviews above are: the same streaming, kept conversation, fix loop, limits and paste path. It is on or off on its own, as `[interviews.report]`, and anyone who can [file a report](#filing-an-after-action-report) may use it. On a Mod's report page, "Write the report with an LLM" comes first and pasting or uploading second.

- **The Path comes first.** When the Mod has a Dry Run, the Mod Runner walks the **Path** the Stretch took through it, with no LLM: the Hook taken, an exit at each scene, a result at each Contest, and "Play ended here" at an ending or "Play stopped here" at a scene. They can step back. For a Mod in progress the walk starts where the last report's Path stopped, or at a Hook if they choose; when the last report has no Path, any scene can be picked up at. plotcanon writes the walk as the report's `path` steps (`plotcanon.path_steps`), by the rules it checks a report's `path` by, and the Path is kept with the Interview. On such a Mod there is no way into the Interview but the walk. A Mod with no Dry Run skips it.
- **Then the LLM.** Pressing Begin sends plotcanon's opener (`plotcanon.interview_report_opener`), and the LLM, given plotcanon's report instructions with the Mod, the Path and where play last stopped, asks the rest and writes the report.
- **The report is held to the Path.** It is checked as a pasted report is (`canon.submitting.check`), and also must give the Path walked as its `path`, or no `path` when none was walked. A report that does not goes back to the LLM to fix, and cannot be filed.
- **`finished` comes from the Path.** An ending reached proposes that the Mod is finished, and a scene that it is not, whatever the LLM wrote. The Mod Runner confirms or changes it as they file. Filing goes through the same `canon.submitting.submit` as a pasted report, so its Canon Changes wait to be decided.

### Dry Run structure

A Dry Run is built from the links a Mod's Hooks, scenes and Contests name, a convention that is part of plotcanon's file format ([ADR-0007](./docs/adr/0007-a-dry-run-is-built-from-the-mods-markdown.md)). Each World says how strictly it asks for that structure, and a Plot Master changes it from "Dry Run structure" on the World's page:

- **`off`.** Mods are not checked for it.
- **`encouraged`.** What is missing or broken is a warning: the Mod is saved, and the warnings are shown when it is submitted, revised and approved. A Mod with no structure at all is left alone.
- **`required`.** The same findings are errors, and a Mod with no structure at all is refused. Every Mod in the World is checked, finished ones too, so a World can only be set to `required` once all of its Mods have the structure. Until then the change is refused and plotcanon's findings are shown, to paste into the LLM that wrote each Mod.

The setting is kept in the World's settings file, `world.yml`, so an export carries it and larp-llm reads it too. A new World is given its Organization's default, which starts at plotcanon's default, `encouraged`; an Organization Admin changes it on the Organization page. The default is the app's own and is never written into a file, and changing it leaves existing Worlds as they are.

### Playing a Dry Run

"Play Dry Run" on a Mod's page walks through what could happen in it, with no players, one step at a time ([ADR-0007](./docs/adr/0007-a-dry-run-is-built-from-the-mods-markdown.md)). It starts at the Premise, with the Hooks as the first choices. Each scene shows its text and where it leads as choices, and a Contest shows each of its results, such as "win" and "lose", as a choice: the Dry Run does not play the Contest out, you pick. An outcome is an ending, with ways to start over or go back a step. Only the story is shown, with a link back to the full Mod.

- **It is read from the Mod's file.** The Mod's body says where each Hook, scene and Contest result leads, as `→ [[Name of a scene or outcome]]`; plotcanon reads the story from that, and the app reads nothing itself. The convention is in plotcanon's `schema/mod.md`.
- **When there is none, it says why.** A Mod written without the convention, or with a link to a heading that does not exist, has no Dry Run, and the page says why in text to paste back into the LLM that wrote it. A scene or outcome nothing leads to is named too, but the rest can still be played.
- **Anyone who can read the Mod can play it**, in any state, from draft on: its Mod Writer, the World's Plot Masters and Mod Runners, and a Mod Runner with a private link, on a phone in the field. Players never can.
- **Nothing is recorded.** Where you are is kept in the page's address, so going back is the browser's back button too, and a step can be bookmarked. Playing a Dry Run never touches Canon or After-Action Reports.

### Mod Writers

A Mod's file names its writer by a handle, such as `mod_writer: sam`, which is a word in the file and not an account. The app knows a Mod's Mod Writer as a person:

- **A Mod submitted here** belongs to the person who submitted it.
- **An imported Mod** belongs to whoever its handle is linked to. A Plot Master links each handle once, on the World's "Mod Writers" page, and that covers every Mod with it.
- **A draft can be reassigned** by a Plot Master, from its page, to anyone with the Mod Writer or Plot Master role in the World. The page says who reassigned it and when. This wins over both of the above.

A Mod's page shows its Mod Writer. Only its Mod Writer, or a Plot Master, can revise a draft. When a Mod is sent back, its Mod Writer is emailed which Mod, who sent it back, why, and a link to it, and their drafts are listed for them on the World's page, marked if they were sent back. None of this is written into any file: accounts never appear in files ([ADR-0001](./docs/adr/0001-two-versions-one-schema-owned-by-larp-llm.md)).

### Editing a Mod in Twine

A Mod can be taken into [Twine](https://twinery.org/) and brought back ([ADR-0007](./docs/adr/0007-a-dry-run-is-built-from-the-mods-markdown.md)). Twine is only a way to edit it: the Mod is always stored as its markdown file.

- **Download for Twine (.twee)** is on every Mod's page, draft or not, for anyone who can read the Mod, and on the page a private link opens. Import the file into Twine. Its scenes, Contests and outcomes are linked passages; every other section is a passage of its own tagged `mod-section`, and the frontmatter is a passage tagged `frontmatter`. Keep that one.
- **Bring it back** wherever a Mod file is submitted or a draft revised: choose the `.twee` file, or the `.html` file Twine saves or publishes. It is turned back into markdown, then checked, taken in as a draft and held to the revision rules exactly as a markdown file is. A story written in Twine from scratch with no `frontmatter` passage is refused like a file with no frontmatter.
- **What Twine adds that a Mod has no place for** (variables, macros, styling, tags, the story's JavaScript and stylesheet) is kept as text or left out, and each is listed as a warning beside plotcanon's messages, as the Mod is saved or refused. It does nothing in a Dry Run.
- **A Twine file may be up to 5 MB** (5,000,000 bytes, the most plotcanon reads), since a published story carries its story format's code. The Mod it turns into is still held to the 1 MB limit of a Mod file. A Twine file is recognised by its name ending `.twee`, `.tw`, `.html` or `.htm`; a pasted Mod is always read as markdown.

## Limits on sign-in

Asking for a sign-in link sends an email, so it is limited, or a stranger could use the app to flood someone's inbox or fill the database with accounts.

- **Per requester:** 10 links an hour from one network address, an IPv4 address or an IPv6 /64 network (`SIGN_IN_LINKS_PER_REQUESTER`, `SIGN_IN_REQUESTER_WINDOW`).
- **Per email address:** one link every 5 minutes (`SIGN_IN_LINKS_PER_ADDRESS`, `SIGN_IN_ADDRESS_WINDOW`). An email address is counted only for a requester within its own limit, so someone over theirs cannot keep a stranger from getting a link.
- **The same page either way.** Someone over a limit sees "Check your email" like anyone else, and no email is sent. The email is sent before the page returns, so that none is lost on hosting that stops once a response is sent; the cost is that the page is slower when an email goes, which could tell someone timing it whether one did.
- **No account is kept for an email address that never signs in.** Asking makes an account; one that has not signed in a day later (`SIGN_IN_UNUSED_ACCOUNT_AGE`), and that nobody has deactivated, is removed the next time anyone asks for a link, or by `uv run python manage.py remove_unused_accounts`, which can be run on a schedule.
- **A link works once**, even if it is used twice at the same moment.
- **Behind a proxy**, set `TRUSTED_PROXIES` to how many of your own proxies stand in front of the app, and a requester's network address is read from `X-Forwarded-For`. Left at 0, that header is ignored, since anyone can write it.

The counts are kept in Postgres and shared by every process. What was counted is kept as a hash, not as it was given, though a guessable value such as an email address can be found from its hash by trying ([ADR-0003](./docs/adr/0003-django-and-postgres-in-one-codebase.md)). Private links use the same counts.

## Who may create an Organization

One setting, `OPEN_SIGN_UP`, decides this. It is read from the environment.

| `OPEN_SIGN_UP` | What happens | Who it suits |
|---|---|---|
| `false` | While this copy has no Organization, the first person to sign in creates the one Organization and its first World. After that, a person who signs in and belongs to no Organization is told they need an invitation. | A self-hosted copy for one Organization. A copy on the internet then does not hand an Organization to every stranger. |
| `true` | Anyone who signs in and belongs to no Organization gets an Organization and a World of their own, unless an invitation is waiting for them: then they answer that first, and get their own only if they decline. | A public host serving many Organizations, or a self-hoster who hosts for others. |

The setting is off unless it is turned on, with one exception: **the local development settings turn it on**, so you can try the app with several email addresses. Those are the only settings in the repo so far, which means `uv run manage.py runserver` with nothing set has open sign-up. To see what a self-hosted copy does, start the app with `OPEN_SIGN_UP=false uv run manage.py runserver`.

The data is stored the same way in both cases. See [ADR-0005](./docs/adr/0005-one-setting-decides-who-may-create-an-organization.md).

## People, Worlds and roles

An Organization Admin runs these from the Organization page, reached by clicking the Organization's name at the top of any page.

- **The Organization's name.** A new Organization is called "My Organization". Rename it at the top of the Organization page. Links keep working after a rename.
- **More Worlds.** Create one by name. It is given the Organization's [Dry Run structure](#dry-run-structure), which you choose below the list of Worlds.
- **Invitations.** Enter an email address. The person is emailed a link to the sign-in page with their address filled in. Once signed in with it they are shown the invitation and accept or decline; nobody is joined to an Organization without accepting. You can see who has not answered and who declined, and inviting an address again sends the email again.
- **Roles.** A new member can open nothing until they are given a role. Roles are per World: Plot Master, Mod Writer and Mod Runner, given and removed on each World's people page. A person can open only the Worlds they hold a role in; an Organization Admin can open them all.
- **A World's name.** This one is not the Organization Admin's to change: a World is renamed by one of its Plot Masters, from the link on the World's page. The first World is called "My first World". To rename a World you created later, give yourself Plot Master in it first.
- **Removing members and withdrawing invitations.** Each person on the Organization page has a Remove button: their roles in its Worlds go with them, and they can open none of them. Their account and any other Organization they belong to are untouched, and they can be invited again. A waiting invitation can be withdrawn; signing in with that address then no longer offers it.
- **More Organization Admins.** Make any member an Organization Admin, or stop them being one, from the Organization page. An Organization always keeps at least one: the last Organization Admin cannot be removed or stop being one, so make someone else Organization Admin first.
- **Leaving.** Any member can leave an Organization, from the Leave link at the top of the page. Their roles in its Worlds go with them. The only Organization Admin of an Organization cannot leave it. Someone who leaves their last Organization gets one of their own if sign-up is open, and otherwise needs an invitation.
- **Several Organizations.** A person who belongs to more than one sees a switcher at the top of the page. The app remembers which one they are working in until they sign out.

### When an Organization has no Organization Admin

The app does not let an Organization lose its last Organization Admin, but it can still happen, for example by editing the database by hand. With sign-up closed nobody could then invite anyone or give a role. Someone with access to the server can name an Organization Admin:

```sh
uv run python manage.py make_organization_admin sam@example.com
```

The person must have an account, which they get by asking for a sign-in link. If they belong to more than one Organization, add `--organization "Its name"`. To add someone who does not belong to it at all, give its id instead: `--organization <id>`.

## How Organizations are kept apart

Each Organization's data is kept apart twice: once by the app's own checks, and once by Postgres row-level security underneath them. Every request tells the database who is asking and which Organization they are working in, and the database returns only that Organization's rows. With nothing set, a query returns no rows at all. There are four deliberate exceptions. A person can always see the Organizations they belong to and their own membership of each, which is how the app finds out where they may work. A person can see an invitation sent to their own address, and the Organization that sent it for as long as they have not answered, so that they can be shown what they are being asked to join. And the database keeps a bare count of Organizations that any query can read, so that a copy with sign-up closed knows whether its one Organization exists yet.

This guards against a mistake in the app's queries. It is not a guard against the app running arbitrary SQL, because the app's database user owns the tables.

Two things follow for anyone running or changing the app:

- **The app must not connect as a database superuser**, or as a user marked `BYPASSRLS`. Postgres skips row-level security for both. `scripts/db.sh` creates an ordinary user, `plothelper`, and `uv run manage.py migrate` refuses to run as the wrong kind. `runserver` does not check, so always migrate first.
- **A new table that holds an Organization's data needs an `organization` column and a policy.** Add `rls.protect("<table name>")` to its migration, and `rls.same_organization(...)` for each column that points at another Organization-owned table; see `organizations/rls.py`.

If your local database was created before this was added, recreate it: `scripts/db.sh destroy && scripts/db.sh`, then `uv run manage.py migrate`.

## License

Copyright (C) 2026 Jeffrey Brite

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the [GNU Affero General Public License](./LICENSE) for more details.
