"""Organizations, the Worlds they run, and who may do what in them.

Every table here except the plain list of people is protected by row-level
security in Postgres (see `rls.py`): a query sees only the rows of the
Organization set for the current request. That is why every row carries its
Organization, even where it could be worked out from another column.
"""

import uuid

from django.conf import settings
from django.db import models


class Organization(models.Model):
    """A group that runs one or more Worlds. Its data is kept entirely
    separate from every other Organization's."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    """A person's place in an Organization. `is_admin` makes them an
    Organization Admin, the only role held across a whole Organization."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="memberships")
    is_admin = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"],
                                    name="one_membership_per_person"),
        ]


class World(models.Model):
    """A setting whose Canon is shared by everyone who plays in it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name="worlds")
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    # The World's settings file, `world.yml`, exactly as it stands, or empty
    # for a World that has none (plotcanon then uses its defaults). It is one
    # of the World's files, and `canon.storing.files_of` gives it with the
    # rest, so plotcanon checks every change against it and an export writes
    # it out. It is kept here rather than as a `canon.Document` row because it
    # is not a document: it has no id, type or name, and the app takes "the
    # World has Canon" to mean "the World has a document", which a new
    # World's settings file must not make true.
    settings_file = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    """The roles a person can hold in one World."""

    PLOT_MASTER = "plot-master", "Plot Master"
    MOD_WRITER = "mod-writer", "Mod Writer"
    MOD_RUNNER = "mod-runner", "Mod Runner"


# Who may write Mods in a World: its Mod Writers, and its Plot Masters, who
# may do anything a Mod Writer may.
WRITES_MODS = (Role.MOD_WRITER, Role.PLOT_MASTER)


class WorldRole(models.Model):
    """One role held by one person in one World. A person can hold several."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name="+")
    # The database also requires the World to be in the same Organization as
    # this row; see `rls.same_organization` in the migrations.
    # Likewise the person must belong to this Organization.
    world = models.ForeignKey(World, on_delete=models.CASCADE, related_name="roles")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="world_roles")
    role = models.CharField(max_length=20, choices=Role)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["world", "user", "role"],
                                    name="one_of_each_role_per_person"),
        ]


class InvitationQuerySet(models.QuerySet):
    def waiting(self):
        """Neither accepted nor declined yet."""
        return self.filter(accepted_at__isnull=True, declined_at__isnull=True)

    def declined(self):
        return self.filter(declined_at__isnull=False)

    def waiting_for(self, user):
        """The invitations sent to this person's address that they have not
        answered yet."""
        return self.filter(email=user.email).waiting()


class Invitation(models.Model):
    """An email address an Organization Admin has asked to join. The person is
    shown it when they sign in with that address, and accepts or declines.
    Until they do, it is waiting."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name="invitations")
    email = models.EmailField()
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)

    objects = InvitationQuerySet.as_manager()

    class Meta:
        ordering = ["email"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "email"],
                                    name="one_invitation_per_address"),
        ]
