"""A World's Canon, as the files it is made of.

Each document of a World (an NPC, a Mod, an After-Action Report and so on) is
one row. The file format belongs to the plotcanon package, which decides
what is valid. This app stores what plotcanon parsed and shows it (ADR-0004).
"""

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

    class Meta:
        ordering = ["name", "slug"]
        constraints = [
            models.UniqueConstraint(fields=["world", "path"], name="one_document_per_path"),
            models.UniqueConstraint(fields=["world", "slug"], name="one_document_per_id"),
        ]
        indexes = [models.Index(fields=["world", "kind"])]

    def __str__(self):
        return self.name


class CanonChangeQuerySet(models.QuerySet):
    def in_world(self, world):
        """A World's Canon Changes. The filter on the Organization repeats what
        the database already enforces."""
        return self.filter(organization=world.organization, world=world)

    def pending(self, world):
        """The Canon Changes of a World that nobody has decided yet."""
        return self.in_world(world).filter(decision="proposed")

    def approved(self, world):
        """The Canon Changes of a World that are Canon."""
        return self.in_world(world).filter(decision="approved")


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
    decision = models.CharField(max_length=40)
    before = models.TextField(blank=True)
    after = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    # Who approved or rejected this change, and when. Empty while it is
    # proposed, and for a change that arrived already decided in an import.
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)

    objects = CanonChangeQuerySet.as_manager()

    class Meta:
        ordering = ["report_id", "position"]
        constraints = [
            models.UniqueConstraint(fields=["report", "position"],
                                    name="one_canon_change_per_place"),
        ]
        indexes = [models.Index(fields=["world", "decision"])]


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
