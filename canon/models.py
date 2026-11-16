"""A World's Canon, as the files it is made of.

Each document of a World (an NPC, a Mod, an After-Action Report and so on) is
one row. The file format belongs to the plotcanon package, which decides
what is valid. This app stores what plotcanon parsed and shows it (ADR-0004).
"""

import hashlib

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from organizations.models import Organization, World


class Document(models.Model):
    """One file of a World, kept exactly as it was uploaded, with what
    plotcanon parsed out of it alongside.

    `path` is where the file sits in the World, such as `canon/npcs/x.md`.
    `kind` and `slug` are the document's `type` and `id` in the file format.
    `name` is what to call it on a page. `fields` is its frontmatter and `body`
    its markdown. `text` is the whole file, which is what an export writes
    back out.
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    # The database also requires the World to be in the same Organization as
    # this row; see `rls.same_organization` in the migrations.
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="documents")
    path = models.CharField(max_length=500)
    kind = models.CharField(max_length=40)
    slug = models.CharField(max_length=200)
    name = models.CharField(max_length=300)
    fields = models.JSONField(encoder=DjangoJSONEncoder)
    body = models.TextField(blank=True)
    text = models.TextField()
    # Who submitted this file and when, for one that was submitted on its own.
    # Empty for a file that arrived as part of an imported World.
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    # Who last approved this Mod to be run, and when, for a Mod approved here.
    # Empty for any other document, and for a Mod approved before it arrived.
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    # The person a Plot Master reassigned a draft Mod to, and who did that and
    # when. Otherwise a Mod's Mod Writer is the person who submitted it, or
    # whoever its file's handle is linked to (`writers.py`). Never written
    # into the file (ADR-0001).
    writer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="+")
    reassigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
    reassigned_at = models.DateTimeField(null=True, blank=True)
    # The last time this Mod was sent back to its Mod Writer: by whom, when
    # and why. Kept while it is a draft and after, as its history.
    sent_back_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    sent_back_at = models.DateTimeField(null=True, blank=True)
    sent_back_reason = models.TextField(blank=True)
    # The private link an After-Action Report was filed through, with no
    # account, for the reports that have one. Nothing sets it.
    filed_through = models.ForeignKey("ModLink", null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="reports")

    class Meta:
        ordering = ["name", "slug"]
        constraints = [
            models.UniqueConstraint(fields=["world", "path"], name="one_document_per_path"),
            models.UniqueConstraint(fields=["world", "slug"], name="one_document_per_id"),
        ]
        indexes = [models.Index(fields=["world", "kind"])]

    def __str__(self):
        return self.name


class Decision(models.TextChoices):
    """Whether a Canon Change is Canon: only an approved one is. Written as it
    is here in the report's file, and kept with a decision that was undone."""

    PROPOSED = "proposed", "Proposed"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class CanonChangeQuerySet(models.QuerySet):
    def in_world(self, world):
        """A World's Canon Changes. The filter on the Organization repeats what
        the database already enforces."""
        return self.filter(organization=world.organization, world=world)

    def pending(self, world):
        """The Canon Changes of a World that nobody has decided yet."""
        return self.in_world(world).filter(decision=Decision.PROPOSED)

    def approved(self, world):
        """The Canon Changes of a World that are Canon."""
        return self.in_world(world).filter(decision=Decision.APPROVED)


class CanonChange(models.Model):
    """One alteration to Canon that an After-Action Report proposes.

    The report's file lists its changes; each also has a row here so that it
    can be found, decided and pointed at on its own. `position` is the change's
    place in the report's list, counting from 0. `entity` is the id of the
    document it changes. `decision` says whether it is Canon: only an approved
    change is.
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="canon_changes")
    report = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="canon_changes")
    position = models.PositiveIntegerField()
    entity = models.CharField(max_length=200)
    kind = models.CharField(max_length=40)
    decision = models.CharField(max_length=40, choices=Decision)
    before = models.TextField(blank=True)
    after = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    # Who approved or rejected this change, and when. Empty while it is
    # proposed, and for a change that arrived already decided in an import.
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    # Why the Plot Master approved or rejected it, in their words: plain text,
    # never markup. Also written beside the decision in the report's file.
    note = models.TextField(blank=True)
    # What approving this change replaced in the entity's file: the field it
    # moves and "as of", as they were. Undoing the approval puts them back.
    # Empty while it is not approved, and for a change approved before this
    # was kept, or that arrived already approved in an import.
    replaced = models.JSONField(default=dict, blank=True)

    objects = CanonChangeQuerySet.as_manager()

    # A decision, as this change holds it and as an Undo keeps it.
    DECISION_FIELDS = ("decision", "decided_by", "decided_at", "note")

    def decision_made(self):
        """This change's decision, who made it, when and why, as fields an
        Undo takes."""
        return {name: getattr(self, name) for name in self.DECISION_FIELDS}

    def record_decision(self, decision, by=None, at=None, note="", replaced=None):
        """Save this change's decision, who made it, when and why, and what
        approving it replaced, if anything."""
        self.decision, self.decided_by, self.decided_at, self.note = decision, by, at, note
        self.replaced = replaced or {}
        self.save(update_fields=[*self.DECISION_FIELDS, "replaced"])

    class Meta:
        ordering = ["report_id", "position"]
        constraints = [
            models.UniqueConstraint(fields=["report", "position"],
                                    name="one_canon_change_per_place"),
        ]
        indexes = [models.Index(fields=["world", "decision"])]


class Undo(models.Model):
    """A decision on a Canon Change that a Plot Master undid, returning the
    change to proposed: what the decision had been, who made it and when, the
    note they gave, and who undid it and when. A change undone more than once
    has one for each."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="+")
    change = models.ForeignKey(CanonChange, on_delete=models.CASCADE, related_name="undos")
    decision = models.CharField(max_length=40, choices=Decision)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    undone_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                                  on_delete=models.SET_NULL, related_name="+")
    undone_at = models.DateTimeField()

    class Meta:
        ordering = ["undone_at", "pk"]


class FlagQuerySet(models.QuerySet):
    def open_in(self, world):
        """A World's open Flags: those on a Mod that is still to be played. A
        Flag on a Mod that has since finished, or been shelved, stays on record
        but warns about nothing. The filter on the Organization repeats what
        the database already enforces."""
        import plotcanon

        unfinished = plotcanon.vocabularies()["mod_states_unfinished"]
        return self.filter(organization=world.organization, world=world, resolution="",
                           mod__fields__state__in=unfinished)


class Flag(models.Model):
    """A warning on an unfinished Mod that a proposed Canon Change touches one
    of its Features. The change names the Feature and the report it came from.

    Raised when the change is proposed, in any Campaign of the World. Which
    Mods a change flags is plotcanon's rule (`plotcanon.flags`).
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="flags")
    mod = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="flags")
    change = models.ForeignKey(CanonChange, on_delete=models.CASCADE, related_name="flags")
    raised_at = models.DateTimeField(auto_now_add=True)

    class Resolution(models.TextChoices):
        DISMISSED = "dismissed", "Dismissed"
        SENT_BACK = "sent-back", "Sent back to its Mod Writer"
        CHANGE_REJECTED = "change-rejected", "Cleared when the change was rejected"

    # How the Flag was resolved, by whom and when; empty while it is open.
    # `note` holds the reason given for sending a Mod back.
    resolution = models.CharField(max_length=20, choices=Resolution, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    objects = FlagQuerySet.as_manager()

    class Meta:
        ordering = ["raised_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["mod", "change"], name="one_flag_per_mod_and_change"),
        ]


class WriterHandle(models.Model):
    """A Mod Writer's handle, as a World's files name them (`mod_writer: sam`),
    linked to the person it means. Every Mod with that handle has that person
    as its Mod Writer, unless one has been reassigned. The link is kept here,
    not in the files: accounts never appear in files (ADR-0001)."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="writer_handles")
    handle = models.CharField(max_length=200)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="+")
    linked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    linked_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["world", "handle"], name="one_person_per_handle"),
        ]


class ModLink(models.Model):
    """A private link to one Mod, for a Mod Runner with no account. Anyone with
    it can read the Mod, download it as its file or for Twine and play its Dry
    Run, and nothing else in the World. Who may file an After-Action Report
    on it is told under **Private link** in GLOSSARY.md.

    Only a hash of the link's secret is kept, so the secret cannot be read
    back out of the database: it is shown once, when the link is created. The
    database lets a request that presents a secret's hash see that one link,
    with no Organization set (see migration 0013), which is how a visitor
    with no account is told which Organization they are in.
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="mod_links")
    mod = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="links")
    token_hash = models.CharField(max_length=64, unique=True)
    # Who the link is for, in the Plot Master's words; it may be empty.
    label = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    turned_off_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
    turned_off_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]

    @staticmethod
    def hash_of(secret):
        return hashlib.sha256(secret.encode()).hexdigest()

    def __str__(self):
        return self.label or f"link {self.pk}"


class Assignment(models.Model):
    """A Plot Master's choice of one Mod Runner to run a Mod, for one Event or
    until a Plot Master revokes it. A Mod can have several at once.

    `event` is the id of the Event it is for, or empty for one that stands
    until revoked. One for an Event stops being live once that Event's last
    day has passed; nothing has to run to end it. A revoked or ended one is
    kept as history. Kept here, never in the Mod's file (ADR-0001). Who is
    live is `assignments.py`'s to say.
    """

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="+")
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="assignments")
    mod = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="assignments")
    runner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="+")
    event = models.CharField(max_length=200, blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    assigned_at = models.DateTimeField()
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["assigned_at", "pk"]
        constraints = [
            # One unrevoked Assignment per person, Mod and Event, and one
            # standing one. One for an Event that has ended stays unrevoked,
            # but no new one can be made for that Event.
            models.UniqueConstraint(fields=["mod", "runner", "event"],
                                    condition=models.Q(revoked_at=None),
                                    name="one_live_assignment_per_runner_and_event"),
        ]
