# Coding standards

For the reviewer. Ruff, Django's checks and the tests already run in the pre-commit hook and CI (`scripts/hooks/pre-commit`, `.github/workflows/check.yml`); this file holds the judgement calls they cannot make.

## Rights and reading

- **Plot Master rights include the Admins.** An Organization Admin may do everything a Plot Master does, in every World of the Organization (`GLOSSARY.md`). Gate a Plot Master action on `is_plot_master` or `plot_master_or_403`, and ask who is on the plot team with `canon.roles.plot_team`. Ruff refuses `Role.PLOT_MASTER` outside those helpers; flag what it cannot see: a `WorldRole` query, a `"plot-master"` string or a new role tuple standing in for the same check, and a test or spec that refuses an Admin a Plot Master action.
- **What a person sees of a World comes through `canon/access.py`.** Every page, download, Twine file, Dry Run, Interview prompt and error takes a World's documents from it (ADR-0010). Domain modules query `Document` directly to change or look up records, which is fine; flag a direct query whose result reaches a page, a file someone downloads or an LLM, because it skips the narrowing to what that person may read.
- **A refusal does not reveal what exists.** A page someone may not open, or a World they are not in, raises `Http404("No such page")`, the same answer as for one that does not exist. `PermissionDenied` (403) is only for an action on a page they can already see.

## plotcanon

- **plotcanon owns the format and its words** (ADR-0004). Validation, defaults and messages a person reads come from plotcanon, not from a copy or rewording in the app.
- **A stopgap names the plotcanon issue it waits on**, in a comment starting `Stopgap until plotcanon #NN`, so that pinning the version that closes it (`rev` in `pyproject.toml`) is followed by a grep that removes every one.

## Words

- **Use the glossary's words** in names, test names, page text and commit messages: Mod, Mod Writer, Plot team, Canon Change, Group. A synonym for a glossary term is a finding; a concept the glossary lacks is a question for `/domain-modeling`, not a new word.
- **Tests read as sentences about a situation**: a class names who or what (`AModWriterWithNoModsOfTheirOwn`), and each method says what happens (`test_a_link_in_a_body_to_a_document_they_may_not_read_reads_another_document`).
- **A commit subject is one plain sentence saying what changed for the people using the app**, ending with its issue number, as in `Tell a draft a later draft may conflict with it only while both are drafts (#66)`.
