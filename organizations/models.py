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

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    """The roles a person can hold in one World."""

    PLOT_MASTER = "plot-master", "Plot Master"
    MOD_WRITER = "mod-writer", "Mod Writer"
    MOD_RUNNER = "mod-runner", "Mod Runner"


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


class Invitation(models.Model):
    """An email address an Organization Admin has asked to join. The person
    joins the next time they sign in with that address."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name="invitations")
    email = models.EmailField()
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["email"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "email"],
                                    name="one_invitation_per_address"),
        ]
