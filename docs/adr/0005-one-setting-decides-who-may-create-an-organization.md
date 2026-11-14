# One setting decides who may create an Organization

A self-hosted copy normally serves one Organization, while our hosted copy serves many and lets a person belong to several. Both run the same code on the same data model. The only difference is a single setting, open sign-up, which decides who may create an Organization. With it off, the first person to sign in creates the one Organization and everyone after joins only by invitation. With it on, anyone who signs up gets an Organization of their own. It is off unless turned on, so a self-hoster is safe without configuring anything.

## Considered Options

- **A separate single-Organization mode with a simpler data model.** Rejected because it would be two designs to build, test and migrate between, and a self-hoster who later wants a second Organization would be stuck.
- **Always open.** Rejected because a self-hosted copy on the internet would hand an Organization to any stranger with an email address.
- **Always invitation-only, with the first Organization made by a command.** Rejected because our hosted copy needs people to sign up on their own, and a command-line step is a hurdle for a self-hoster.

## Consequences

- Row-level security and the Organization column on every row stay in place for self-hosters too, even with one Organization.
- A person in one Organization never sees a way to switch. A person in several sees a switcher, and the app remembers their choice until they sign out.
- With sign-up closed, a stranger who signs in has no Organization and is told they need an invitation.
- With sign-up open, a person who has been invited to an Organization answers the invitation before being given one of their own. If they accept, they are not given one; if they decline, they are.
- A self-hoster who wants several Organizations, such as a LARP company hosting for partner groups, turns the setting on.
