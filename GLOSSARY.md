# RPG Plot Helper

Tracks the canon and plots of live-action and tabletop role-playing games, for plot teams, shared-world GMs and solo GMs.

## Language

**Organization**:
A group that runs one or more Worlds, such as a LARP company or a solo GM. Each Organization's data is kept entirely separate from every other's.
_Avoid_: Tenant, account, group

**Organization Admin**:
The role that creates Worlds in an Organization, invites people and assigns their roles. It is the only role held across a whole Organization; all others are held per World. An Organization Admin may also do everything a Plot Master does, in every World of the Organization.
_Avoid_: Owner, superuser

**World**:
A setting whose Canon is shared by everyone who plays in it. A World belongs to one Organization and owns its NPCs, factions, locations, PCs, Plots and history.
_Avoid_: Setting, universe

**Campaign**:
One run of play inside a World, with its own GM or plot team and its own players. A Campaign owns its Events and Mods, and a World has one or more Campaigns.
_Avoid_: Game, chronicle

**Canon**:
The facts established as true in a World.
_Avoid_: Lore, continuity

**Plot**:
A storyline that runs across several Mods.
_Avoid_: Thread, arc, storyline

**Mod**:
A single runnable piece of play, written in advance by a Mod Writer and run for players by a Mod Runner. A Mod can be interrupted and continue later, even at another Event.
_Avoid_: Adventure, module

**Dry Run**:
A playable, branching version of a Mod, built from its scenes and Possible Outcomes, for walking through what could happen without players. Nothing in a Dry Run changes Canon. Anyone who may read the Mod may play its Dry Run; players never can.
_Avoid_: Twine, playtest, simulation

**Contest**:
A point in a Mod where what happens next depends on play that is not written in advance, such as a fight, a chase or a persuasion, and so has named results, at least success and failure. A Dry Run does not simulate a Contest; the reader picks its result.
_Avoid_: Combat, check, roll

**Premise**:
The situation a Mod opens on, before any player is drawn in. A Dry Run starts there.
_Avoid_: Intro, setup, background

**Hook**:
One way PCs are drawn into a Mod, leading on from its Premise into a scene. A Mod offers two or three, and they are a Dry Run's first choices.
_Avoid_: Lead-in, entry point

**Dry Run structure**:
How strictly a World asks for its Mods to be written so that a Dry Run can be built from them: off, encouraged or required. It is a World's setting, kept in the World's own files; a new World is given its Organization's default.
_Avoid_: Strictness, Dry Run mode

**Mod Writer**:
The role of writing a Mod and submitting it for the Plot Master's approval.
_Avoid_: Author, plot writer

**Handle**:
The name a Mod's file gives its Mod Writer, such as `sam`. It is a word in the file, not an account; a Plot Master links it to the person it means.
_Avoid_: Username, login

**Mod Runner**:
The role of running a Mod and reporting what happened in it. A solo GM is the Mod Runner of every Mod they run.

**Assignment**:
A Plot Master's choice of one Mod Runner to run a Mod, for one Event or until the Plot Master revokes it. A Mod can have several at once.
_Avoid_: Booking, slot, run

**Event**:
One real-world gathering of play, such as a LARP weekend or a tabletop night. An Event contains the Mods run at it.
_Avoid_: Session, game

**After-Action Report**:
A Mod Runner's account of what happened during one Stretch of a Mod, listing the changes to Canon it proposes and saying how the Stretch ended.
_Avoid_: Mod report, AAR

**Stretch**:
One continuous stretch of play of a Mod by one group, ending when play stops. A Mod is played in one or more Stretches, and when its players are split into groups, several run at once.
_Avoid_: Part, session, segment

**Group**:
Some of a Mod's players, playing it apart from the others at the same Event, with their own Mod Runner. Each Group plays its own Stretches; the Mod is finished when every Group is.
_Avoid_: Party, team, split

**Path**:
The way one Stretch went through a Mod's Dry Run: the Hook and scenes taken, each Contest's result, and the ending or the scene where play stopped.
_Avoid_: Route, playthrough, trace

**Debrief**:
What someone who took part in a Mod, whatever their part, thinks plot should know about it. It belongs to the Mod and its Event, and proposes no changes to Canon; a Plot Master reads it beside the After-Action Reports.
_Avoid_: Player report, extra report

**Reconciliation**:
The app's LLM checking a draft Mod against the whole World's Canon, and against the other Mods waiting for approval, and reporting what conflicts, for a Plot Master to read before approving the Mod or sending it back.
_Avoid_: Canon check, review

**World review**:
The app's LLM looking across a whole World for drift, dormant Plots and chances to bring recurring NPCs and Plots back, for the plot team.
_Avoid_: Audit, health check

**Interview**:
A conversation in which the app's LLM asks someone questions and writes their Mod, After-Action Report or Debrief from the answers. The person reads what it wrote and submits it themselves.
_Avoid_: Chat, assistant, wizard

**Plot Master**:
The role that approves Mods and proposed changes into a World's Canon. Several people can hold it, and it exists at the World level only.
_Avoid_: Plot lead, canon keeper

**Private link**:
A link to one Mod that lets whoever holds it read the Mod, download it as its file or for Twine and play its Dry Run, with no account. Filing an After-Action Report needs an account with a role in the Mod's World. A Plot Master creates one for a Mod Runner.
_Avoid_: Share link, guest link

**Interlude**:
The period between two Events, in which Canon can change without any Mod being run.
_Avoid_: Downtime, between-game

**Visibility**:
Who may know a fact in Canon: public, player-known or GM-only.

**Plot team**:
The people who may read everything in a World, GM-only facts included: its Plot Masters and its Organization's Admins. Anyone else reads what is public or player-known, and what they have been given more of.

**Grant**:
A Plot Master's choice to let one Mod Writer or Mod Runner read one document in full, GM-only facts included, until it is revoked.
_Avoid_: Plot grant, clearance, permission, share

**GM Notes**:
The section of a document that only the plot team may read, wherever the rest of the document is shown.

**PC**:
A player's character, held only as a stub: a name, who plays them, and their ties to NPCs, factions and Plots. Character sheets and the player roster live outside this system.
_Avoid_: Character, player (for the character)

**Player**:
A person who plays a PC, and the role that lets them file Debriefs.

**Cast member**:
A person who plays NPCs in Mods, and the role that lets them file Debriefs. An NPC is the character in Canon; the Cast member is the person playing them.
_Avoid_: NPC (for the person), crew

**Feature**:
An NPC, faction, location, PC or Plot that a Mod relies on. A Mod lists its Features.
_Avoid_: Dependency, cast

**Canon Change**:
One alteration to Canon, proposed by an After-Action Report or made during an Interlude, and approved or rejected by the Plot Master. Its kind is one of: status, location, affiliation, relationship, knowledge, narrative or created. The Plot Master may give a note with the decision, saying why; it is kept in the report's file beside the decision.
_Avoid_: Delta, update

**Flag**:
A warning on an unfinished Mod that a proposed Canon Change touches one of its Features. The Plot Master dismisses it or sends the Mod back to its Mod Writer.
_Avoid_: Conflict, alert
